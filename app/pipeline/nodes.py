"""Pipeline node functions for each stage of the LangGraph newsletter pipeline."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.pipeline.state import PipelineState
from app.utils.logger import get_logger

logger = get_logger("pipeline.nodes")


def _strip_html(text: str) -> str:
    """Remove HTML tags from text, returning plain text."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _override_source_labels(newsletter_json: dict, articles: List[Dict[str, Any]]) -> dict:
    """Force-override writer-generated source labels with resolved values from extracted articles."""
    url_to_article: Dict[str, Dict[str, Any]] = {}
    for a in articles:
        url_to_article[a.get("url", "")] = a
        if a.get("secondary_source"):
            url_to_article[a["secondary_source"]] = a

    def _fix_item(item: dict | None) -> None:
        if not item or not isinstance(item, dict):
            return
        writer_url = item.get("source_url", "")
        match = url_to_article.get(writer_url)
        if not match:
            for a in articles:
                if a.get("title", "").lower()[:40] in (item.get("title", "").lower() or ""):
                    match = a
                    break
        if match:
            resolved_label = match.get("source_label", "")
            resolved_url = match.get("url", "")
            if resolved_label:
                item["source_label"] = resolved_label
            if resolved_url:
                item["source_url"] = resolved_url

    _fix_item(newsletter_json.get("headline"))
    for news_item in newsletter_json.get("latest_news", []):
        _fix_item(news_item)
    for cu_item in newsletter_json.get("company_updates", []):
        _fix_item(cu_item)
    _fix_item(newsletter_json.get("research_spotlight"))
    for tp_item in newsletter_json.get("tools_and_products", []):
        _fix_item(tp_item)
    for os_item in newsletter_json.get("open_source_spotlight", []):
        _fix_item(os_item)
    for qb_item in newsletter_json.get("quick_bytes", []):
        _fix_item(qb_item)

    return newsletter_json


MAX_CANDIDATES_TO_LLM = 80

_BASE_AI_TERMS = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "large language model", "gpt", "transformer",
    "nlp", "natural language", "computer vision", "reinforcement learning",
    "generative ai", "gen ai", "diffusion", "foundation model",
    "chatbot", "openai", "anthropic", "google deepmind", "meta ai",
    "hugging face", "huggingface", "pytorch", "tensorflow",
    "fine-tuning", "fine tuning", "rag", "retrieval augmented",
    "multimodal", "embedding", "vector", "agent", "agentic",
    "prompt engineering", "reasoning", "benchmark", "safety",
    "model", "inference", "training", "dataset", "neural",
    "robot", "automation", "copilot", "gemini", "claude",
    "mistral", "llama", "qwen", "stable diffusion", "midjourney",
}

_AI_FOCUSED_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "ai.meta.com",
    "huggingface.co", "marktechpost.com", "arstechnica.com",
    "venturebeat.com", "technologyreview.com", "theverge.com",
    "blog.google", "arxiv.org", "github.com",
    "techcrunch.com", "wired.com", "reddit.com",
}


def _extract_topic_keywords(topic_query: str) -> set[str]:
    """Build keyword set from the topic query + base AI terms."""
    words = set(re.findall(r"[a-z][a-z0-9+#.-]*", topic_query.lower()))
    phrases = set()
    lowered = topic_query.lower()
    for term in _BASE_AI_TERMS:
        if term in lowered:
            phrases.add(term)
    return words | phrases | _BASE_AI_TERMS


def _candidate_matches_keywords(title: str, snippet: str, keywords: set[str]) -> bool:
    """Check if title or snippet contains at least one keyword."""
    text = f"{title} {snippet}".lower()
    for kw in keywords:
        if kw in text:
            return True
    return False


def _match_source_priority(candidate, source_priority: Dict[str, float]) -> float:
    """Find the best matching source priority for a candidate by checking its URL against source URLs."""
    domain = (candidate.normalized_domain or "").lower()
    best = 0.5
    for source_url, score in source_priority.items():
        if domain and domain in source_url.lower():
            best = max(best, score)
    return best


_MAX_PER_DOMAIN = 8

def _prefilter_candidates(candidates: list, topic_query: str, source_priority: Dict[str, float] = None) -> list:
    """Keyword pre-filter + per-domain cap + round-robin interleaving.

    1. AI-focused domains bypass keyword matching.
    2. Each domain is capped at _MAX_PER_DOMAIN candidates (sorted by recency within domain).
    3. Domains are interleaved round-robin (ordered by source priority) so no single
       source can monopolise the global MAX_CANDIDATES_TO_LLM budget.
    """
    keywords = _extract_topic_keywords(topic_query)
    passed = [
        c for c in candidates
        if (c.normalized_domain or "") in _AI_FOCUSED_DOMAINS
        or _candidate_matches_keywords(c.title or "", c.snippet or "", keywords)
    ]

    domain_buckets: Dict[str, list] = {}
    for c in passed:
        domain = c.normalized_domain or "unknown"
        domain_buckets.setdefault(domain, []).append(c)

    _date_floor = datetime.min.replace(tzinfo=None)
    for domain, bucket in domain_buckets.items():
        bucket.sort(
            key=lambda c: c.pub_date_if_available or _date_floor,
            reverse=True,
        )
        domain_buckets[domain] = bucket[:_MAX_PER_DOMAIN]

    if source_priority:
        domain_order = sorted(
            domain_buckets.keys(),
            key=lambda d: max(
                (score for url, score in source_priority.items() if d in url.lower()),
                default=0.5,
            ),
            reverse=True,
        )
    else:
        domain_order = sorted(
            domain_buckets.keys(),
            key=lambda d: max(
                (c.pub_date_if_available or _date_floor for c in domain_buckets[d]),
                default=_date_floor,
            ),
            reverse=True,
        )

    result: list = []
    pointers = {d: 0 for d in domain_order}
    while len(result) < MAX_CANDIDATES_TO_LLM:
        added_this_round = False
        for domain in domain_order:
            idx = pointers[domain]
            bucket = domain_buckets[domain]
            if idx < len(bucket):
                result.append(bucket[idx])
                pointers[domain] = idx + 1
                added_this_round = True
                if len(result) >= MAX_CANDIDATES_TO_LLM:
                    break
        if not added_this_round:
            break

    return result


def _build_qa_feedback(qa_report: dict) -> str:
    """Convert QA report issues and improvements into a revision instruction string."""
    parts: list[str] = []
    qr = qa_report.get("quality_review", {})
    fc = qa_report.get("fact_check", {})

    sections = fc.get("sections", [])
    issues_found = [
        (s.get("title") or s.get("section_type", "?"), s.get("issues", []))
        for s in sections if s.get("issues")
    ]
    if issues_found:
        parts.append("FACT-CHECK ISSUES (these are HALLUCINATIONS — the summary states something not in the source):")
        parts.append("For each issue: REMOVE or CORRECT the false claim using only facts from the source article. Do NOT invent replacement details.")
        for section_name, issues in issues_found:
            for issue in issues:
                parts.append(f"  - [{section_name}] {issue}")

    improvements = qr.get("improvements", [])
    if improvements:
        parts.append("\nQUALITY IMPROVEMENTS:")
        for i, item in enumerate(improvements, 1):
            parts.append(f"  {i}. {item}")

    if not parts:
        return "The QA agent found minor issues. Please polish the newsletter for clarity and accuracy."

    return "\n".join(parts)


def create_nodes(db: AsyncSession, progress=None) -> Dict[str, Callable]:
    """Return node functions with the database session captured in closure."""

    def _emit(stage: str, status: str, detail: str = "", **kw):
        if progress:
            progress.emit(stage, status, detail, **kw)

    async def scout_node(state: PipelineState) -> dict:
        """Discover article candidates from seed sources and external providers."""
        from app.agents.scout_agent import ScoutAgent
        from app.services.scout_service import ScoutService

        logger.info("Node [scout]: Discovering article candidates")
        _emit("scout", "running", "Discovering candidates from RSS feeds and sources")
        stage_start = time.time()

        scout_service = ScoutService(db)
        agent = ScoutAgent()

        _emit("scout", "running", "Evaluating source priority...")
        source_priority: Dict[str, float] = {}
        try:
            sources_input = [
                {"source_url": url, "source_type": "rss"}
                for url in settings.SEED_SOURCES
            ]
            evaluations = await agent.evaluate_sources(state["topic_query"], sources_input)
            for ev in evaluations:
                source_priority[ev["source_url"]] = ev.get("priority_score", 0.5)
            logger.info(f"Node [scout]: Source evaluation ranked {len(source_priority)} sources")
        except Exception as e:
            logger.warning(f"Node [scout]: Source evaluation failed, using equal priority: {e}")

        candidates = await scout_service.discover_candidates(
            state["topic_id"],
            state["topic_query"],
        )
        discovery_stats = scout_service.get_discovery_stats()

        if source_priority:
            for c in candidates:
                c._source_priority = _match_source_priority(c, source_priority)

        _emit("scout", "running", f"Found {len(candidates)} raw candidates, filtering...", count=len(candidates))

        if candidates:
            raw_count = len(candidates)
            candidates = _prefilter_candidates(candidates, state["topic_query"], source_priority)
            logger.info(
                f"Node [scout]: Pre-filter kept {len(candidates)}/{raw_count} "
                f"candidates (keyword match + priority cap)"
            )

        if candidates:
            _emit("scout", "running", f"LLM assessing {len(candidates)} candidates...")
            batch = [
                {
                    "url": c.url,
                    "title": c.title or "",
                    "snippet": c.snippet or "",
                    "domain": c.normalized_domain or "",
                }
                for c in candidates
            ]
            assessments = await agent.assess_candidates(
                state["topic_query"], batch
            )
            keep_urls = {
                a["url"] for a in assessments if a.get("keep", True)
            }
            before = len(candidates)
            candidates = [c for c in candidates if c.url in keep_urls]
            logger.info(
                f"Node [scout]: Agent assessment kept "
                f"{len(candidates)}/{before} candidates"
            )

        if candidates:
            from app.repository.candidate_repository import ArticleCandidateRepository
            repo = ArticleCandidateRepository(db)
            approved_ids = [c.id for c in candidates if c.id]
            if approved_ids:
                await repo.mark_candidates_for_extraction(approved_ids, pass_to_extractor=True)
                logger.info(f"Node [scout]: Marked {len(approved_ids)} approved candidates in DB")

        elapsed = time.time() - stage_start
        logger.info(
            f"Node [scout]: Discovered {len(candidates)} candidates "
            f"in {elapsed:.2f}s"
        )
        _emit("scout", "done", f"{len(candidates)} candidates in {elapsed:.0f}s", count=len(candidates), time=elapsed)

        return {
            "candidates": candidates,
            "stages": {
                **state.get("stages", {}),
                "scout": {
                    "status": "success",
                    "candidates_discovered": len(candidates),
                    "time_seconds": elapsed,
                    "stats": discovery_stats,
                },
            },
        }

    async def curator_node(state: PipelineState) -> dict:
        """Score, filter, deduplicate, and select top-K candidates."""
        from app.core.curator.filters import CuratorConfig
        from app.services.curator_service import CuratorService

        curator_feedback = state.get("curator_feedback")
        is_re_curate = bool(curator_feedback)
        label = "Re-curating with feedback" if is_re_curate else "Scoring and selecting candidates"
        logger.info(f"Node [curator]: {label}")
        _emit("curator", "running", f"{label} with LLM...")
        stage_start = time.time()

        curator_config = CuratorConfig(
            skip_paywalled=settings.CURATOR_SKIP_PAYWALLED,
            min_quality_threshold=settings.CURATOR_MIN_QUALITY,
            domain_denylist=settings.CURATOR_DOMAIN_DENYLIST,
        )

        weights = state.get("scoring_weights", {})

        scout_candidates = state.get("candidates", [])

        curator_service = CuratorService(db, curator_config)
        _emit("curator", "running", "Scoring candidates and reading articles for editorial review...")
        curated = await curator_service.curate_candidates(
            topic_id=state["topic_id"],
            max_candidates=state.get("max_candidates", 8),
            weight_quality=weights.get("quality", settings.CURATOR_WEIGHT_QUALITY),
            weight_freshness=weights.get("freshness", settings.CURATOR_WEIGHT_FRESHNESS),
            weight_provider=weights.get("provider", settings.CURATOR_WEIGHT_PROVIDER),
            pre_filtered_candidates=scout_candidates if scout_candidates else None,
            editor_feedback=curator_feedback,
        )

        elapsed = time.time() - stage_start
        curation_stats = curator_service.get_curation_stats()

        logger.info(f"Node [curator]: Selected {len(curated)} candidates in {elapsed:.2f}s")
        _emit("curator", "done", f"{len(curated)} articles selected in {elapsed:.0f}s", count=len(curated), time=elapsed)

        return {
            "curated": curated,
            "curator_feedback": None,
            "stages": {
                **state.get("stages", {}),
                "curator": {
                    "status": "success",
                    "candidates_curated": len(curated),
                    "time_seconds": elapsed,
                    "stats": curation_stats,
                },
            },
        }

    _API_CONTENT_PROVIDERS = {"hf_papers", "github_trending"}

    async def extractor_node(state: PipelineState) -> dict:
        """Extract full article content from curated candidate URLs."""
        from app.agents.extractor_agent import ExtractorAgent
        from app.core.database import AsyncSessionLocal
        from app.repository.article_repository import ArticleRepository
        from app.schemas.article_schema import ArticleCreate
        from app.services.extract_service import ExtractService
        from app.utils.s3_utils import async_download_text, async_upload_text

        logger.info("Node [extractor]: Extracting article content")
        _emit("extractor", "running", "Fetching and extracting article content...")
        stage_start = time.time()

        extract_service = ExtractService()
        qa_agent = ExtractorAgent()
        curated: List[Any] = state.get("curated", [])

        seen_urls: Dict[str, Any] = {}
        unique_candidates: List[Any] = []
        for candidate in curated:
            if candidate.url not in seen_urls:
                seen_urls[candidate.url] = candidate
                unique_candidates.append(candidate)

        logger.info(
            f"Node [extractor]: {len(unique_candidates)} unique candidates "
            f"(removed {len(curated) - len(unique_candidates)} duplicates)"
        )

        extracted_articles: List[Dict[str, Any]] = []
        extraction_errors: List[str] = []

        import asyncio as _aio

        async def _extract_one(candidate):
            """Extract a single candidate with its own DB session."""
            if candidate.source_provider in _API_CONTENT_PROVIDERS:
                content = candidate.snippet or candidate.title or ""
                logger.info(
                    f"Using API content for {candidate.source_provider} candidate: "
                    f"{(candidate.title or '')[:60]} ({len(content)} chars)"
                )
                return ({
                    "id": str(candidate.id),
                    "url": candidate.url,
                    "title": candidate.title or "Untitled",
                    "content": content[:4000],
                    "domain": candidate.normalized_domain,
                    "curation_score": candidate.curation_score or 0,
                }, None)

            async with AsyncSessionLocal() as session:
                try:
                    repo = ArticleRepository(session)
                    existing_article = await repo.get_by_url(candidate.url)
                    if existing_article:
                        logger.info(f"Article already exists, reusing: {candidate.url}")
                        extracted_text = ""
                        if existing_article.bucket_key:
                            try:
                                extracted_text = await async_download_text(existing_article.bucket_key)
                            except Exception:
                                pass
                        return ({
                            "id": str(existing_article.id),
                            "url": existing_article.url,
                            "title": existing_article.title,
                            "content": extracted_text[:4000] if extracted_text else "",
                            "domain": candidate.normalized_domain,
                            "curation_score": candidate.curation_score or 0,
                        }, None)

                    extraction = await extract_service.robust_extract(candidate.url)
                    extracted_text = extraction.get("text", "")
                    final_url = extraction.get("final_url", candidate.url)

                    if not extracted_text:
                        logger.warning(f"Extraction failed for {candidate.url}")
                        return (None, candidate.url)

                    word_count = len(extracted_text.split())
                    if word_count < 200:
                        try:
                            quality = await qa_agent.evaluate_quality(
                                candidate.url, extracted_text, word_count,
                            )
                            if quality.get("recommendation") == "skip":
                                logger.warning(
                                    f"ExtractorAgent rejected low-quality extraction "
                                    f"({word_count} words, score={quality['quality_score']:.2f}): "
                                    f"{candidate.url}"
                                )
                                return (None, candidate.url)
                            logger.info(
                                f"ExtractorAgent accepted short extraction "
                                f"({word_count} words, score={quality['quality_score']:.2f})"
                            )
                        except Exception as eval_err:
                            logger.debug(f"ExtractorAgent quality eval failed, accepting anyway: {eval_err}")

                    existing_by_final = await repo.get_by_url(final_url)
                    if existing_by_final:
                        return ({
                            "id": str(existing_by_final.id),
                            "url": existing_by_final.url,
                            "title": existing_by_final.title,
                            "content": extracted_text[:4000],
                            "domain": candidate.normalized_domain,
                            "curation_score": candidate.curation_score or 0,
                        }, None)

                    bucket_key = await async_upload_text(extracted_text.encode("utf-8"))
                    article_data = ArticleCreate(
                        url=final_url,
                        title=extraction.get("title", candidate.title),
                        source=candidate.normalized_domain,
                        topic_id=state["topic_id"],
                        bucket_key=bucket_key,
                    )
                    article = await repo.create_article(article_data)
                    await session.commit()
                    logger.info(f"Extracted: {article.title}")

                    return ({
                        "id": str(article.id),
                        "url": article.url,
                        "title": article.title,
                        "content": extracted_text[:4000],
                        "domain": candidate.normalized_domain,
                        "curation_score": candidate.curation_score or 0,
                    }, None)

                except Exception as e:
                    logger.error(f"Error extracting {candidate.url}: {e}")
                    return (None, candidate.url)

        sem = _aio.Semaphore(4)

        async def _bounded(c):
            async with sem:
                return await _extract_one(c)

        results = await _aio.gather(*[_bounded(c) for c in unique_candidates], return_exceptions=False)

        for article_dict, error_url in results:
            if article_dict:
                extracted_articles.append(article_dict)
            if error_url:
                extraction_errors.append(error_url)

        elapsed = time.time() - stage_start
        logger.info(
            f"Node [extractor]: {len(extracted_articles)} articles extracted, "
            f"{len(extraction_errors)} failures in {elapsed:.2f}s"
        )
        _emit("extractor", "done", f"{len(extracted_articles)} articles extracted in {elapsed:.0f}s", count=len(extracted_articles), time=elapsed)

        return {
            "extracted_articles": extracted_articles,
            "stages": {
                **state.get("stages", {}),
                "extractor": {
                    "status": "success" if extracted_articles else "failed",
                    "articles_extracted": len(extracted_articles),
                    "extraction_failures": len(extraction_errors),
                    "time_seconds": elapsed,
                },
            },
        }

    async def source_resolver_node(state: PipelineState) -> dict:
        """Map secondary-source URLs to primary/official URLs where possible."""
        from app.services.source_resolver_service import SourceResolverService

        logger.info("Node [source_resolver]: Resolving secondary sources to primary URLs")
        stage_start = time.time()

        resolver = SourceResolverService()
        articles = list(state.get("extracted_articles", []))
        regex_resolved = 0
        llm_resolved = 0

        unresolved_indices: list[int] = []

        for idx, article_dict in enumerate(articles):
            original_url = article_dict["url"]
            content = article_dict.get("content", "")

            primary_url, source_label = resolver.extract_primary_url(content, original_url)

            if primary_url and primary_url != original_url:
                article_dict["url"] = primary_url
                article_dict["source_label"] = source_label
                article_dict["secondary_source"] = original_url
                regex_resolved += 1
                logger.info(f"Regex resolved to {source_label}: {primary_url[:60]}...")
            else:
                article_dict["source_label"] = source_label
                if resolver.is_secondary_source(original_url):
                    unresolved_indices.append(idx)

        if unresolved_indices:
            logger.info(f"LLM fallback: attempting resolution for {len(unresolved_indices)} secondary articles")

            async def _llm_resolve(idx: int) -> tuple[int, str | None, str]:
                a = articles[idx]
                url, label = await resolver.resolve_with_llm(
                    a.get("content", ""), a["url"], a.get("title", ""),
                )
                return idx, url, label

            results = await asyncio.gather(
                *[_llm_resolve(i) for i in unresolved_indices],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"LLM resolution task failed: {result}")
                    continue
                idx, primary_url, label = result
                if primary_url and primary_url != articles[idx]["url"]:
                    articles[idx]["secondary_source"] = articles[idx]["url"]
                    articles[idx]["url"] = primary_url
                    articles[idx]["source_label"] = label
                    llm_resolved += 1
                    logger.info(f"LLM resolved to {label}: {primary_url[:60]}...")
                elif label != articles[idx].get("source_label", ""):
                    articles[idx]["source_label"] = label
                    logger.info(f"LLM relabelled to '{label}' (URL unchanged)")

        total_resolved = regex_resolved + llm_resolved
        elapsed = time.time() - stage_start
        logger.info(
            f"Node [source_resolver]: {total_resolved}/{len(articles)} resolved "
            f"(regex={regex_resolved}, llm={llm_resolved}) in {elapsed:.2f}s"
        )

        return {
            "extracted_articles": articles,
            "stages": {
                **state.get("stages", {}),
                "source_resolver": {
                    "status": "success",
                    "articles_resolved": total_resolved,
                    "regex_resolved": regex_resolved,
                    "llm_resolved": llm_resolved,
                    "total_articles": len(articles),
                    "time_seconds": elapsed,
                },
            },
        }

    async def editor_node(state: PipelineState) -> dict:
        """Plan newsletter structure and assign articles to sections."""
        from app.agents.editor_agent import EditorAgent

        logger.info("Node [editor]: Planning newsletter structure")
        _emit("writer", "running", "Editor planning newsletter structure...")
        stage_start = time.time()

        articles = state.get("extracted_articles", [])
        agent = EditorAgent()
        editor_plan = await agent.plan_structure(articles)

        elapsed = time.time() - stage_start
        logger.info(
            f"Node [editor]: Structure planned in {elapsed:.2f}s — "
            f"headline={editor_plan.get('headline_id', 'N/A')[:12]}"
        )

        return {
            "editor_plan": editor_plan,
            "stages": {
                **state.get("stages", {}),
                "editor": {
                    "status": "success",
                    "headline_id": editor_plan.get("headline_id", ""),
                    "sections_count": len(editor_plan.get("sections", [])),
                    "narrative_arc": editor_plan.get("narrative_arc", ""),
                    "time_seconds": elapsed,
                },
            },
        }

    async def writer_node(state: PipelineState) -> dict:
        """Generate full newsletter content from the editor plan, or revise based on feedback."""
        from app.agents.writer_agent import WriterAgent
        from app.services.assembler_service import NewsletterAssembler

        user_feedback = state.get("user_feedback")
        qa_feedback = state.get("qa_revision_feedback")
        revision_feedback = user_feedback or qa_feedback
        is_revision = bool(revision_feedback and state.get("newsletter_json"))

        if is_revision:
            source = "QA" if qa_feedback else "user"
            logger.info(f"Node [writer]: Revising newsletter based on {source} feedback")
            _emit("writer", "running", f"Revising newsletter with {source} feedback...")
        else:
            logger.info("Node [writer]: Generating structured newsletter")
            _emit("writer", "running", "Writing newsletter content...")
        stage_start = time.time()

        articles = state.get("extracted_articles", [])
        editor_plan = state.get("editor_plan", {})

        agent = WriterAgent()

        if is_revision:
            newsletter_json = await agent.revise_newsletter(
                previous_json=state["newsletter_json"],
                feedback=revision_feedback,
                articles=articles,
                issue_number=state.get("issue_number"),
            )
        else:
            newsletter_json = await agent.write_newsletter(
                articles=articles,
                editor_plan=editor_plan,
                issue_number=state.get("issue_number"),
                newsletter_title=state.get("newsletter_title") or settings.NEWSLETTER_TITLE,
            )

        if newsletter_json:
            newsletter_json = _override_source_labels(newsletter_json, articles)

        newsletter_markdown: str | None = None
        newsletter_html: str | None = None

        if newsletter_json:
            assembler = NewsletterAssembler()
            newsletter_markdown = assembler.to_markdown(newsletter_json)
            newsletter_html = assembler.to_html(newsletter_json)

        elapsed = time.time() - stage_start
        generated = newsletter_json is not None

        logger.info(
            f"Node [writer]: {'Generated' if generated else 'FAILED to generate'} "
            f"newsletter in {elapsed:.2f}s"
        )
        _emit("writer", "done" if generated else "error", f"Newsletter {'generated' if generated else 'failed'} in {elapsed:.0f}s", time=elapsed)

        revision_count = state.get("qa_revision_count", 0)
        if qa_feedback:
            revision_count += 1

        return {
            "newsletter_json": newsletter_json,
            "newsletter_markdown": newsletter_markdown,
            "newsletter_html": newsletter_html,
            "user_feedback": None,
            "qa_revision_count": revision_count,
            "error": None,
            "stages": {
                **state.get("stages", {}),
                "writer": {
                    "status": "success" if generated else "failed",
                    "newsletter_generated": generated,
                    "format": "structured (AI Newsletter)",
                    "total_articles": newsletter_json.get("total_articles", 0) if newsletter_json else 0,
                    "sections": {
                        "headline": 1 if (newsletter_json or {}).get("headline") else 0,
                        "latest_news": len((newsletter_json or {}).get("latest_news", [])),
                        "company_updates": len((newsletter_json or {}).get("company_updates", [])),
                        "research_spotlight": 1 if (newsletter_json or {}).get("research_spotlight") else 0,
                        "tools_and_products": len((newsletter_json or {}).get("tools_and_products", [])),
                        "quick_bytes": len((newsletter_json or {}).get("quick_bytes", [])),
                    },
                    "time_seconds": elapsed,
                    "revision_number": revision_count,
                },
            },
        }

    async def qa_node(state: PipelineState) -> dict:
        """Validate the newsletter: fact-check and quality review."""
        from app.agents.qa_agent import QAAgent

        logger.info("Node [qa]: Running newsletter quality assurance")
        _emit("qa", "running", "QA checking newsletter quality...")
        stage_start = time.time()

        newsletter_json = state.get("newsletter_json")
        source_articles = state.get("extracted_articles", [])

        if not newsletter_json:
            logger.warning("Node [qa]: No newsletter to validate")
            return {
                "qa_report": {"skipped": True, "reason": "no newsletter"},
                "stages": {
                    **state.get("stages", {}),
                    "qa": {"status": "skipped", "time_seconds": 0},
                },
            }

        agent = QAAgent()

        fact_result = await agent.fact_check(newsletter_json, source_articles)
        quality_result = await agent.quality_review(newsletter_json)

        qa_report = {
            "fact_check": fact_result,
            "quality_review": quality_result,
            "overall_pass": (
                fact_result.get("overall_accuracy", 0) >= 0.5
                and quality_result.get("verdict") != "rewrite"
            ),
        }

        elapsed = time.time() - stage_start
        verdict = quality_result.get("verdict", "N/A")
        logger.info(
            f"Node [qa]: QA completed in {elapsed:.2f}s — "
            f"accuracy={fact_result.get('overall_accuracy', 0):.2f}, "
            f"quality={quality_result.get('overall_quality', 0):.2f}, "
            f"verdict={verdict}"
        )
        _emit("qa", "done", f"QA {verdict} in {elapsed:.0f}s", time=elapsed)

        return {
            "qa_report": qa_report,
            "qa_revision_feedback": None,
            "stages": {
                **state.get("stages", {}),
                "qa": {
                    "status": "success",
                    "overall_accuracy": fact_result.get("overall_accuracy", 0),
                    "overall_quality": quality_result.get("overall_quality", 0),
                    "verdict": quality_result.get("verdict", "review"),
                    "overall_pass": qa_report["overall_pass"],
                    "time_seconds": elapsed,
                },
            },
        }

    async def review_qa_node(state: PipelineState) -> dict:
        """HITL checkpoint: show QA report and let user approve, revise, or reject."""
        qa_report = state.get("qa_report", {})
        _emit("review", "waiting", "Waiting for QA review...")
        logger.info("Node [review_qa]: Pausing for user review of QA report")

        decision = interrupt({
            "type": "review_qa",
            "qa_report": qa_report,
            "newsletter_html": state.get("newsletter_html", ""),
            "newsletter_json": state.get("newsletter_json"),
        })

        if isinstance(decision, dict):
            action = decision.get("action", "approve")
            feedback = decision.get("feedback", "")
        else:
            action = str(decision)
            feedback = ""

        if action == "reject":
            logger.info("Node [review_qa]: User rejected after QA")
            _emit("review", "done", "Newsletter rejected after QA review")
            return {"error": "Newsletter rejected after QA review", "qa_revision_feedback": None}

        if action == "revise_with_qa":
            auto_feedback = _build_qa_feedback(qa_report)
            logger.info(f"Node [review_qa]: Auto-revision from QA ({len(auto_feedback)} chars)")
            _emit("review", "done", "Revising with QA feedback — re-running writer")
            return {"qa_revision_feedback": auto_feedback, "error": None}

        if action == "revise" and feedback:
            logger.info(f"Node [review_qa]: Custom revision from QA review ({len(feedback)} chars)")
            _emit("review", "done", "Revising with custom feedback — re-running writer")
            return {"qa_revision_feedback": feedback, "error": None}

        logger.info("Node [review_qa]: User approved after QA")
        _emit("review", "done", "Newsletter approved after QA")
        return {"qa_revision_feedback": None}

    async def email_node(state: PipelineState) -> dict:
        """Send the generated newsletter via email."""
        from app.services.email_service import EmailService

        recipient = state.get("recipient_email")
        logger.info(f"Node [email]: Sending newsletter to {recipient}")
        _emit("email", "running", f"Sending to {recipient}...")
        stage_start = time.time()

        try:
            email_service = EmailService()
            newsletter_json = state.get("newsletter_json", {}) or {}
            issue_number = state.get("issue_number")
            subject = (
                f"{newsletter_json.get('issue_title', 'AI Newsletter')} "
                f"- Issue #{issue_number or 'N'}"
            )

            email_result = await email_service.send_newsletter_email(
                recipient,
                subject,
                state.get("newsletter_html", ""),
            )

            sent = email_result.get("success", False)
            elapsed = time.time() - stage_start
            logger.info(f"Node [email]: sent={sent} in {elapsed:.2f}s")

            return {
                "stages": {
                    **state.get("stages", {}),
                    "email": {
                        "status": "success" if sent else "failed",
                        "email_sent": sent,
                        "recipient": recipient,
                        "time_seconds": elapsed,
                    },
                },
            }
        except Exception as e:
            elapsed = time.time() - stage_start
            logger.error(f"Node [email]: Error sending email: {e}")
            return {
                "stages": {
                    **state.get("stages", {}),
                    "email": {
                        "status": "failed",
                        "error": str(e),
                        "time_seconds": elapsed,
                    },
                },
            }

    async def review_articles_node(state: PipelineState) -> dict:
        """HITL checkpoint: pause for user to approve/reject/re-curate articles."""
        curated = state.get("curated", [])
        payload = [
            {
                "id": str(c.id),
                "url": c.url,
                "title": _strip_html(c.title or ""),
                "snippet": _strip_html(c.snippet or "")[:200],
                "score": c.curation_score or 0,
                "domain": c.normalized_domain or "",
                "reasoning": _strip_html(c.reason_notes or "")[:200] if c.reason_notes else "",
                "discovered_at": c.discovered_at.isoformat() if c.discovered_at else "",
            }
            for c in curated
        ]
        _emit("review", "waiting", "Waiting for article approval...")
        logger.info(f"Node [review_articles]: Pausing for user review of {len(payload)} candidates")

        decision = interrupt({"type": "review_articles", "candidates": payload})

        if isinstance(decision, dict):
            action = decision.get("action", "continue")
            feedback = decision.get("feedback", "")
            approved_ids = decision.get("approved_ids", [])
        else:
            action = "continue"
            feedback = ""
            approved_ids = decision if isinstance(decision, list) else []

        if action == "reject":
            logger.info("Node [review_articles]: User rejected all articles")
            _emit("review", "done", "Articles rejected by user")
            return {"error": "Articles rejected by user", "curated": [], "curator_feedback": None}

        if action == "re_curate" and feedback:
            logger.info(f"Node [review_articles]: User requested re-curation ({len(feedback)} chars feedback)")
            _emit("review", "done", "Re-curation requested — re-running curator")
            return {"curator_feedback": feedback, "error": None}

        if approved_ids:
            id_set = set(approved_ids)
            curated = [c for c in curated if str(c.id) in id_set]
            logger.info(f"Node [review_articles]: User approved {len(curated)} articles")
        else:
            logger.info("Node [review_articles]: User approved all articles (no filter)")

        _emit("review", "done", f"User approved {len(curated)} articles")
        return {"curated": curated, "curator_feedback": None}

    async def review_newsletter_node(state: PipelineState) -> dict:
        """HITL checkpoint: pause for user to approve/revise/reject newsletter."""
        _emit("review", "waiting", "Waiting for newsletter approval...")
        logger.info("Node [review_newsletter]: Pausing for user review of newsletter")

        decision = interrupt({
            "type": "review_newsletter",
            "newsletter_html": state.get("newsletter_html", ""),
            "newsletter_json": state.get("newsletter_json"),
        })

        # Accept both old string format and new dict format
        if isinstance(decision, dict):
            action = decision.get("action", "approve")
            feedback = decision.get("feedback", "")
        else:
            action = str(decision)
            feedback = ""

        if action == "reject":
            logger.info("Node [review_newsletter]: User rejected the newsletter")
            _emit("review", "done", "Newsletter rejected by user")
            return {"error": "Newsletter rejected by user", "newsletter_json": None, "user_feedback": None}

        if action == "revise" and feedback:
            logger.info(f"Node [review_newsletter]: User requested revision ({len(feedback)} chars feedback)")
            _emit("review", "done", "Revision requested — re-running writer")
            return {"user_feedback": feedback, "error": None}

        logger.info("Node [review_newsletter]: User approved the newsletter")
        _emit("review", "done", "Newsletter approved")
        return {"user_feedback": None}

    return {
        "scout": scout_node,
        "curator": curator_node,
        "review_articles": review_articles_node,
        "extractor": extractor_node,
        "source_resolver": source_resolver_node,
        "editor": editor_node,
        "writer": writer_node,
        "review_newsletter": review_newsletter_node,
        "qa": qa_node,
        "review_qa": review_qa_node,
        "email": email_node,
    }

"""Curator Service - orchestrates candidate scoring, filtering, dedup, and selection."""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candidate_model import ArticleCandidate
from app.repository.candidate_repository import ArticleCandidateRepository
from app.core.curator.scoring import (
    calculate_freshness_score,
    calculate_provider_score,
    calculate_composite_score,
    build_reason_notes
)
from app.core.curator.deduplication import (
    canonicalize_url,
    find_duplicates
)
from app.core.curator.filters import (
    CuratorConfig,
    should_filter_out,
)
from app.utils.logger import get_logger

logger = get_logger("curator_service")

CURATOR_VERSION = "v3.0.0-llm-quality"


class CuratorService:

    def __init__(
        self,
        db: AsyncSession,
        config: Optional[CuratorConfig] = None,
    ):
        self.db = db
        self.candidate_repo = ArticleCandidateRepository(db)
        self.config = config or CuratorConfig()
        self._curator_agent = None

        logger.info(f"CuratorService initialized (denylist={self.config.domain_denylist})")

        self.stats = {
            "total_candidates": 0,
            "scored_candidates": 0,
            "filtered_candidates": 0,
            "duplicate_candidates": 0,
            "selected_candidates": 0,
            "processing_time_seconds": 0.0,
        }

    @property
    def curator_agent(self):
        if self._curator_agent is None:
            from app.agents.curator_agent import CuratorAgent
            self._curator_agent = CuratorAgent()
        return self._curator_agent

    async def curate_candidates(
        self,
        topic_id: str,
        max_candidates: int = 8,
        weight_quality: float = 0.60,
        weight_freshness: float = 0.25,
        weight_provider: float = 0.15,
        pre_filtered_candidates: Optional[List[ArticleCandidate]] = None,
        editor_feedback: Optional[str] = None,
    ) -> List[ArticleCandidate]:
        logger.info(f"Starting curation for topic: {topic_id}")
        start_time = time.time()

        try:
            if pre_filtered_candidates is not None:
                candidates = pre_filtered_candidates
                logger.info(f"Using {len(candidates)} pre-filtered candidates from scout")
            else:
                candidates = await self.candidate_repo.get_candidates_by_topic(topic_id)
            self.stats["total_candidates"] = len(candidates)

            if not candidates:
                logger.warning(f"No candidates found for topic: {topic_id}")
                return []

            logger.info(f"Found {len(candidates)} candidates to curate")

            scored_candidates = await self._score_candidates(
                candidates, weight_quality, weight_freshness, weight_provider
            )

            filtered_candidates = await self._filter_candidates(scored_candidates)
            deduplicated_candidates = self._deduplicate_candidates(filtered_candidates)
            diverse_candidates = self._enforce_diversity(deduplicated_candidates, max_per_domain=1)

            top_candidates = await self._agent_editorial_select(
                diverse_candidates, max_candidates, editor_feedback=editor_feedback
            )

            curated_candidates = await self._finalize_selection(top_candidates)

            self.stats["selected_candidates"] = len(curated_candidates)
            self.stats["processing_time_seconds"] = time.time() - start_time

            logger.info(
                f"Curation complete: {len(curated_candidates)} selected from "
                f"{len(candidates)} total, took {self.stats['processing_time_seconds']:.2f}s"
            )

            return curated_candidates

        except Exception as e:
            logger.error(f"Error during curation for topic {topic_id}: {e}")
            raise

    async def _score_candidates(
        self,
        candidates: List[ArticleCandidate],
        weight_quality: float,
        weight_freshness: float,
        weight_provider: float
    ) -> List[ArticleCandidate]:
        """Score candidates using LLM quality + freshness + provider dimensions."""
        logger.info(f"Scoring {len(candidates)} candidates")

        agent_relevance_map, agent_reasoning_map = (
            await self._agent_batch_relevance(candidates)
        )

        scored = []

        for candidate in candidates:
            try:
                freshness_score = calculate_freshness_score(
                    candidate.pub_date_if_available,
                    candidate.discovered_at,
                    lambda_days=3
                )

                provider_score = calculate_provider_score(
                    candidate.source_provider,
                    candidate.provider_rank,
                    candidate.is_seed_source
                )

                cid = str(candidate.id)
                quality_score = agent_relevance_map.get(cid, 0.5)
                agent_note = agent_reasoning_map.get(cid, "")

                composite_score = calculate_composite_score(
                    quality_score,
                    freshness_score,
                    provider_score,
                    weight_quality,
                    weight_freshness,
                    weight_provider,
                    domain=candidate.normalized_domain,
                    pub_date=candidate.pub_date_if_available
                )

                reason_notes = build_reason_notes(
                    quality_score, freshness_score, provider_score, composite_score
                )
                if agent_note:
                    reason_notes = f"[Agent] {agent_note}. {reason_notes}"

                logger.info(f"Setting scores for: {(candidate.title or '')[:50]}")
                logger.info(
                    f"   quality={quality_score:.3f}, fresh={freshness_score:.3f}, "
                    f"provider={provider_score:.3f}, composite={composite_score:.3f}"
                )

                candidate.freshness_score = freshness_score
                candidate.semantic_score = quality_score
                candidate.provider_score = provider_score
                candidate.curation_score = composite_score
                candidate.reason_notes = reason_notes
                candidate.curated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                candidate.curator_version = CURATOR_VERSION

                candidate = await self.db.merge(candidate)
                scored.append(candidate)

            except Exception as e:
                logger.error(f"Failed to score candidate {candidate.url}: {e}")
                candidate.freshness_score = 0.0
                candidate.semantic_score = 0.0
                candidate.provider_score = 0.0
                candidate.curation_score = 0.0
                candidate.reason_notes = f"Scoring failed: {e}"
                scored.append(candidate)
                continue

        self.stats["scored_candidates"] = len(scored)
        logger.info(f"Successfully scored {len(scored)} candidates")

        try:
            if scored:
                sample = scored[0]
                logger.debug(
                    f"BEFORE COMMIT - Sample: {(sample.title or '')[:50]} "
                    f"curation={sample.curation_score}"
                )

            await self.db.commit()
            logger.info(f"Scores committed to database for {len(scored)} candidates")

            for candidate in scored:
                await self.db.refresh(candidate)

        except Exception as e:
            logger.error(f"Failed to commit scores: {e}")
            await self.db.rollback()
            raise

        return scored

    async def _agent_batch_relevance(
        self, candidates: List[ArticleCandidate]
    ) -> tuple:
        """Call CuratorAgent.score_relevance; returns (score_map, reasoning_map)."""
        score_map: Dict[str, float] = {}
        reasoning_map: Dict[str, str] = {}

        topic_query = candidates[0].topic_query if candidates else ""

        batch = [
            {
                "id": str(c.id),
                "title": c.title or "",
                "snippet": c.snippet or "",
                "domain": c.normalized_domain or "",
            }
            for c in candidates
        ]

        results = await self.curator_agent.score_relevance(topic_query, batch)
        for item in results:
            cid = str(item["id"])
            score_map[cid] = item["relevance_score"]
            reasoning_map[cid] = item.get("reasoning", "")
        logger.info(f"Agent quality scoring returned {len(score_map)} scores")

        return score_map, reasoning_map

    async def _filter_candidates(
        self,
        candidates: List[ArticleCandidate]
    ) -> List[ArticleCandidate]:
        logger.info(f"Filtering {len(candidates)} candidates")
        filtered = []
        filtered_count = 0

        for candidate in candidates:
            try:
                should_filter, reason = await should_filter_out(
                    candidate,
                    self.config,
                )

                if should_filter:
                    logger.debug(f"Filtered out {candidate.url}: {reason}")
                    filtered_count += 1
                    candidate.reason_notes = f"Filtered: {reason}"
                    candidate.pass_to_extractor = False
                    await self.db.merge(candidate)
                else:
                    filtered.append(candidate)

            except Exception as e:
                logger.error(f"Error filtering candidate {candidate.url}: {e}")
                filtered.append(candidate)

        self.stats["filtered_candidates"] = filtered_count
        logger.info(f"Filtered out {filtered_count} candidates, {len(filtered)} remaining")

        await self.db.commit()

        return filtered

    def _deduplicate_candidates(
        self,
        candidates: List[ArticleCandidate]
    ) -> List[ArticleCandidate]:
        logger.info(f"Deduplicating {len(candidates)} candidates")

        duplicate_map = find_duplicates(candidates)
        duplicate_ids = set(duplicate_map.keys())
        unique_candidates = [c for c in candidates if c.id not in duplicate_ids]

        self.stats["duplicate_candidates"] = len(duplicate_ids)
        logger.info(
            f"Removed {len(duplicate_ids)} duplicates, "
            f"{len(unique_candidates)} unique candidates remaining"
        )

        return unique_candidates

    _RESEARCH_DOMAINS = {"arxiv.org", "huggingface.co", "github.com"}

    def _enforce_diversity(
        self,
        candidates: List[ArticleCandidate],
        max_per_domain: int = 1
    ) -> List[ArticleCandidate]:
        """Prevents single-domain dominance by applying a -0.2 penalty per extra article.
        Research-heavy domains (arXiv, HuggingFace, GitHub) get a higher threshold of 3.
        """
        logger.info(f"Enforcing diversity (max {max_per_domain} per domain without penalty, 3 for research)")

        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.curation_score or 0,
            reverse=True
        )

        domain_counts = {}
        adjusted_candidates = []

        for candidate in sorted_candidates:
            domain = candidate.normalized_domain or "unknown"
            count = domain_counts.get(domain, 0)
            effective_max = 3 if domain in self._RESEARCH_DOMAINS else max_per_domain

            if count >= effective_max:
                penalty = (count - effective_max + 1) * 0.15
                original_score = candidate.curation_score or 0
                candidate.curation_score = max(0, original_score - penalty)

                logger.debug(
                    f"Diversity penalty for {domain} (article #{count + 1}): "
                    f"{original_score:.3f} -> {candidate.curation_score:.3f}"
                )

            domain_counts[domain] = count + 1
            adjusted_candidates.append(candidate)

        logger.info(f"Domain distribution after diversity enforcement:")
        for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1])[:5]:
            logger.info(f"  {domain}: {count} candidates")

        return adjusted_candidates

    async def _finalize_selection(
        self,
        candidates: List[ArticleCandidate]
    ) -> List[ArticleCandidate]:
        logger.info(f"Finalizing selection of {len(candidates)} candidates")
        finalized = []

        for rank, candidate in enumerate(candidates, start=1):
            try:
                candidate.curated_rank = rank
                candidate.pass_to_extractor = True
                candidate = await self.db.merge(candidate)
                finalized.append(candidate)

                score_val = candidate.curation_score if candidate.curation_score is not None else 0
                logger.debug(
                    f"Rank {rank}: {candidate.title} "
                    f"(score: {score_val:.3f})"
                )

            except Exception as e:
                logger.error(f"Failed to finalize candidate {candidate.id}: {e}")
                finalized.append(candidate)

        await self.db.commit()
        logger.info(f"Finalized {len(finalized)} candidates with ranks and scores")

        return finalized

    async def _agent_editorial_select(
        self,
        candidates: List[ArticleCandidate],
        max_candidates: int,
        editor_feedback: Optional[str] = None,
    ) -> List[ArticleCandidate]:
        """Sends ~2x max_candidates top-scored candidates to CuratorAgent for editorial pick."""
        pool_size = min(len(candidates), max_candidates * 2)
        candidates_sorted = sorted(
            candidates,
            key=lambda c: c.curation_score or 0.0,
            reverse=True,
        )
        pool = candidates_sorted[:pool_size]

        topic_query = pool[0].topic_query if pool else ""

        agent_input = [
            {
                "id": str(c.id),
                "title": c.title or "",
                "url": c.url or "",
                "snippet": c.snippet or "",
                "domain": c.normalized_domain or "",
                "curation_score": c.curation_score or 0.0,
                "quality_score": c.semantic_score or 0.0,
                "freshness_score": c.freshness_score or 0.0,
            }
            for c in pool
        ]

        results = await self.curator_agent.select_editorial_agentic(
            topic_query, agent_input, max_candidates, editor_feedback=editor_feedback
        )

        id_to_candidate = {str(c.id): c for c in pool}
        selected = []
        for item in results:
            cid = str(item["id"])
            if cid in id_to_candidate:
                candidate = id_to_candidate[cid]
                editorial_note = item.get("editorial_reasoning", "")
                if editorial_note:
                    candidate.reason_notes = (
                        f"[Editorial] {editorial_note}. "
                        f"{candidate.reason_notes or ''}"
                    )
                selected.append(candidate)

        logger.info(f"Agent editorial selection picked {len(selected)} articles")
        return selected

    def get_curation_stats(self) -> Dict[str, Any]:
        return self.stats.copy()

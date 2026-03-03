"""WriterAgent — LLM-powered newsletter content generation."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.writer")

class WriterAgent(BaseAgent):
    """LLM-powered writer for newsletter content generation."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(
            model=model or getattr(settings, "WRITER_AGENT_MODEL", None) or settings.NVIDIA_MODEL,
            temperature=temperature if temperature is not None else 0.4,
            max_tokens=8192,
        )

    async def write_newsletter(self, articles: List[Dict[str, Any]], editor_plan: Dict[str, Any],
                                issue_number: Optional[int] = None, newsletter_title: Optional[str] = None) -> Dict[str, Any]:
        """Generate full newsletter from articles + editor plan."""
        if not articles:
            return self._empty_newsletter(issue_number)

        logger.info(f"WriterAgent: writing newsletter with {len(articles)} articles, issue #{issue_number or 'N'}")
        start = time.time()

        import json as _json
        articles_block = _json.dumps([
            {
                "id": a["id"],
                "title": a.get("title", "Untitled"),
                "domain": a.get("domain", "unknown"),
                "url": a.get("url", ""),
                "source_label": a.get("source_label", ""),
                "secondary_source": a.get("secondary_source", ""),
                "curation_score": a.get("curation_score", 0),
                "content_preview": (a.get("content") or "")[:3000],
                "editor_hint": self._editor_hint(a, editor_plan),
            }
            for a in articles
        ], indent=2)

        user_prompt = load_prompt(
            "writer", "structured_newsletter_user",
            issue_number=issue_number or "N",
            article_count=len(articles),
            articles_json=articles_block,
            date_iso=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        raw = await self._invoke_json(
            load_prompt("writer", "structured_newsletter_system"),
            user_prompt,
        )
        result = self._normalise_newsletter(raw, articles, issue_number)
        logger.info(f"WriterAgent: written in {time.time() - start:.2f}s — {result.get('total_articles', 0)} articles")
        return result

    async def revise_newsletter(
        self,
        previous_json: Dict[str, Any],
        feedback: str,
        articles: List[Dict[str, Any]],
        issue_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Revise an existing newsletter draft based on human feedback."""
        import json as _json

        logger.info(f"WriterAgent: revising newsletter based on feedback ({len(feedback)} chars)")
        start = time.time()

        articles_block = _json.dumps([
            {
                "id": a.get("id", ""),
                "title": a.get("title", "Untitled"),
                "url": a.get("url", ""),
                "source_label": a.get("source_label", ""),
                "content_preview": (a.get("content") or "")[:3000],
            }
            for a in articles
        ], indent=2)

        revision_prompt = load_prompt(
            "writer", "revision_instructions",
            feedback=feedback,
            articles_json=articles_block,
            previous_draft=_json.dumps(previous_json, indent=2),
        )

        system_prompt = load_prompt("writer", "structured_newsletter_system")

        raw = await self._invoke_json(system_prompt, revision_prompt)
        result = self._normalise_newsletter(raw, articles, issue_number)
        logger.info(f"WriterAgent: revision done in {time.time() - start:.2f}s")
        return result

    @staticmethod
    def _editor_hint(article: Dict[str, Any], editor_plan: Dict[str, Any]) -> str:
        """Return a hint like 'headline' or 'latest_news' based on editor plan."""
        aid = str(article.get("id", ""))
        if aid == editor_plan.get("headline_id"):
            return "HEADLINE"
        for s in editor_plan.get("sections", []):
            if aid in [str(x) for x in s.get("article_ids", [])]:
                return s.get("section", "").upper()
        return "QUICK_BYTES"

    @staticmethod
    def _ensure_article_dict(item: Any) -> Optional[Dict[str, Any]]:
        """Ensure an article item is a dict with required keys, or return None."""
        if isinstance(item, str):
            return {"title": item, "summary": item, "source_label": "", "source_url": ""}
        if isinstance(item, dict):
            return item
        return None

    @classmethod
    def _normalise_newsletter(cls, raw: Any, articles: List[Dict[str, Any]], issue_number: Optional[int]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")

        headline = raw.get("headline")
        if isinstance(headline, str):
            headline = {"title": headline, "summary": "", "source_label": "", "source_url": ""}
        elif not isinstance(headline, dict):
            headline = None

        research = raw.get("research_spotlight")
        if isinstance(research, str):
            research = {"title": research, "summary": "", "source_label": "", "source_url": ""}
        elif not isinstance(research, dict):
            research = None

        def _clean_list(key: str) -> List[Dict[str, Any]]:
            items = raw.get(key, [])
            if not isinstance(items, list):
                return []
            return [d for d in (cls._ensure_article_dict(i) for i in items) if d]

        newsletter = {
            "issue_title": raw.get("issue_title", "AI Newsletter"),
            "issue_number": raw.get("issue_number", issue_number),
            "date_iso": raw.get("date_iso", datetime.now(timezone.utc).isoformat()),
            "subheadline": raw.get("subheadline", ""),
            "intro": raw.get("intro", ""),
            "headline": headline,
            "latest_news": _clean_list("latest_news"),
            "company_updates": _clean_list("company_updates"),
            "research_spotlight": research,
            "tools_and_products": _clean_list("tools_and_products"),
            "open_source_spotlight": _clean_list("open_source_spotlight"),
            "quick_bytes": _clean_list("quick_bytes"),
            "wrap": raw.get("wrap", "Keep building, keep learning."),
            "footer": raw.get("footer", "\u00a9 AI Newsletter"),
            "total_articles": len(articles),
            "estimated_read_time": raw.get("estimated_read_time", "4-6 minutes"),
            "quality_checks": raw.get("quality_checks", {"all_sections_present": True, "word_counts_valid": True, "all_articles_included": True}),
        }
        return newsletter

    @staticmethod
    def _empty_newsletter(issue_number: Optional[int]) -> Dict[str, Any]:
        return {
            "issue_title": "AI Newsletter", "issue_number": issue_number,
            "date_iso": datetime.now(timezone.utc).isoformat(), "subheadline": "No articles available",
            "intro": "No articles were provided for this edition.", "headline": None,
            "latest_news": [], "company_updates": [], "research_spotlight": None,
            "tools_and_products": [], "open_source_spotlight": [], "quick_bytes": [], "wrap": "",
            "footer": "\u00a9 AI Newsletter", "total_articles": 0,
            "estimated_read_time": "0 minutes",
            "quality_checks": {"all_sections_present": False, "word_counts_valid": False, "all_articles_included": False},
        }


"""EditorAgent — LLM-powered newsletter structure planning."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.editor")

VALID_SECTIONS = {"latest_news", "company_updates", "research_spotlight", "tools_and_products", "quick_bytes"}


class EditorAgent(BaseAgent):
    """LLM-powered editor for newsletter structure planning."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(
            model=model or getattr(settings, "EDITOR_AGENT_MODEL", None) or settings.NVIDIA_MODEL,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=8192,
        )

    async def plan_structure(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a structural plan: headline, section assignments, narrative arc."""
        if not articles:
            return self._empty_plan()

        logger.info(f"EditorAgent: planning structure for {len(articles)} articles")
        start = time.time()

        system_prompt = load_prompt("editor", "structure_planning", article_count=len(articles))
        raw = await self._invoke_json(system_prompt, self._build_structure_prompt(articles))
        result = self._normalise_plan(raw, articles)
        logger.info(f"EditorAgent: planned in {time.time() - start:.2f}s — headline={result['headline_id'][:12]}...")
        return result

    @staticmethod
    def _build_structure_prompt(articles: List[Dict[str, Any]]) -> str:
        lines = [f"You have {len(articles)} articles to organize:\n"]
        for i, a in enumerate(articles, 1):
            lines.append(
                f'{i}. id="{a["id"]}"\n'
                f"   Title: {(a.get('title') or 'Untitled')[:200]}\n"
                f"   Domain: {a.get('domain', 'unknown')}\n"
                f"   Score: {a.get('curation_score', 0):.3f}\n"
                f"   Preview: {(a.get('content') or '')[:300]}\n"
            )
        lines.append("\nCreate a structural plan. Assign every article to exactly one section. Return JSON only.")
        return "\n".join(lines)

    @staticmethod
    def _normalise_plan(raw: Any, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")

        valid_ids = {str(a["id"]) for a in articles}
        headline_id = str(raw.get("headline_id", ""))
        if headline_id not in valid_ids:
            best = max(articles, key=lambda a: a.get("curation_score", 0))
            headline_id = str(best["id"])

        assigned_ids = {headline_id}
        sections = []
        for s in (raw.get("sections") or []):
            if not isinstance(s, dict):
                continue
            section_name = str(s.get("section", ""))
            if section_name not in VALID_SECTIONS:
                continue
            article_ids = s.get("article_ids", [])
            if not isinstance(article_ids, list):
                continue
            clean_ids = []
            for aid in article_ids:
                aid_str = str(aid)
                if aid_str in valid_ids and aid_str not in assigned_ids:
                    clean_ids.append(aid_str)
                    assigned_ids.add(aid_str)
            if clean_ids:
                sections.append({"section": section_name, "article_ids": clean_ids})

        unassigned = [str(a["id"]) for a in articles if str(a["id"]) not in assigned_ids]
        if unassigned:
            sections.append({"section": "quick_bytes", "article_ids": unassigned})

        return {
            "headline_id": headline_id,
            "sections": sections,
            "narrative_arc": str(raw.get("narrative_arc", ""))[:200],
            "editorial_notes": str(raw.get("editorial_notes", ""))[:300],
        }

    @staticmethod
    def _empty_plan() -> Dict[str, Any]:
        return {"headline_id": "", "sections": [], "narrative_arc": "", "editorial_notes": ""}


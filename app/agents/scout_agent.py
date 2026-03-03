"""ScoutAgent — LLM-powered source evaluation and candidate assessment."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.scout")

BATCH_SIZE = 15


class ScoutAgent(BaseAgent):
    """LLM-powered scout for source evaluation and candidate assessment."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(
            model=model or getattr(settings, "SCOUT_AGENT_MODEL", None) or settings.NVIDIA_MODEL,
            temperature=temperature if temperature is not None else 0.2,
            max_tokens=8192,
        )

    async def evaluate_sources(self, topic_query: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rank sources by expected relevance."""
        if not sources:
            return []

        logger.info(f"ScoutAgent: evaluating {len(sources)} sources (topic: {topic_query!r})")
        start = time.time()
        user_prompt = self._build_source_eval_prompt(topic_query, sources)

        raw_results = await self._invoke_json(load_prompt("scout", "source_evaluation"), user_prompt)
        results = self._normalise_source_results(raw_results, sources)
        logger.info(f"ScoutAgent: source evaluation completed in {time.time() - start:.2f}s ({len(results)} ranked)")
        return results

    async def assess_candidates(self, topic_query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Triage raw candidates in batches to avoid LLM output truncation."""
        if not candidates:
            return []

        logger.info(f"ScoutAgent: assessing {len(candidates)} candidates in batches of {BATCH_SIZE} (topic: {topic_query!r})")
        start = time.time()
        system_prompt = load_prompt("scout", "candidate_assessment")

        all_raw: list = []
        for batch_idx in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[batch_idx : batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1
            total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"ScoutAgent: processing batch {batch_num}/{total_batches} ({len(batch)} candidates)")

            user_prompt = self._build_candidate_assess_prompt(topic_query, batch)
            raw_results = await self._invoke_json(system_prompt, user_prompt)
            if isinstance(raw_results, list):
                all_raw.extend(raw_results)

        results = self._normalise_candidate_results(all_raw, candidates)
        kept = sum(1 for r in results if r["keep"])
        logger.info(f"ScoutAgent: assessment completed in {time.time() - start:.2f}s ({kept}/{len(results)} kept)")
        return results

    @staticmethod
    def _build_source_eval_prompt(topic_query: str, sources: List[Dict[str, Any]]) -> str:
        lines = [f'Newsletter topic: "{topic_query}"\n', "Available sources:\n"]
        for i, s in enumerate(sources, 1):
            lines.append(f'{i}. url="{s.get("source_url", "unknown")}" type={s.get("source_type", "unknown")}\n')
        lines.append("\nReturn a JSON array with one object per source, in the same order as above.")
        return "\n".join(lines)

    @staticmethod
    def _build_candidate_assess_prompt(topic_query: str, candidates: List[Dict[str, Any]]) -> str:
        lines = [f'Newsletter topic: "{topic_query}"\n', "Candidates:\n"]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f'{i}. url="{c.get("url", "unknown")}"\n'
                f"   Title: {(c.get('title') or 'No title')[:200]}\n"
                f"   Snippet: {(c.get('snippet') or 'No snippet')[:300]}\n"
                f"   Domain: {c.get('domain', 'unknown')}\n"
            )
        lines.append("\nReturn a JSON array with one object per candidate, in the same order as above.")
        return "\n".join(lines)

    @staticmethod
    def _normalise_source_results(raw: Any, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            raise ValueError(f"Expected list, got {type(raw).__name__}")

        result_map: Dict[str, Dict] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("source_url", ""))
            score = item.get("priority_score", 0.5)
            try:
                score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                score = 0.5
            result_map[url] = {"source_url": url, "priority_score": score, "reasoning": str(item.get("reasoning", ""))[:200]}

        results = []
        for s in sources:
            url = s.get("source_url", "")
            results.append(result_map.get(url, {"source_url": url, "priority_score": 0.5, "reasoning": "Not evaluated by LLM"}))
        results.sort(key=lambda r: r["priority_score"], reverse=True)
        return results

    @staticmethod
    def _normalise_candidate_results(raw: Any, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            raise ValueError(f"Expected list, got {type(raw).__name__}")

        result_map: Dict[str, Dict] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            score = item.get("relevance_score", 0.5)
            keep = item.get("keep", True)
            try:
                score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                score = 0.5
            if not isinstance(keep, bool):
                keep = score >= 0.3
            result_map[url] = {"url": url, "relevance_score": score, "keep": keep, "reasoning": str(item.get("reasoning", ""))[:200]}

        results = []
        for c in candidates:
            url = c.get("url", "")
            if url in result_map:
                results.append(result_map[url])
            else:
                logger.warning(f"LLM omitted candidate {url[:60]}, using fallback")
                results.append({"url": url, "relevance_score": 0.5, "keep": True, "reasoning": "Not assessed by LLM (missing from response)"})
        return results


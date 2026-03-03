"""CuratorAgent — LLM-powered relevance scoring and editorial selection."""

from __future__ import annotations

import json as _json
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.curator")

BATCH_SIZE = 15
_MAX_REACT_STEPS = 12


class CuratorAgent(BaseAgent):
    """LLM-powered curator for relevance scoring and editorial selection."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(model=model, temperature=temperature or settings.CURATOR_AGENT_TEMPERATURE)

    async def score_relevance(self, topic_query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Score candidates for relevance in batches to avoid output truncation."""
        if not candidates:
            return []

        logger.info(f"CuratorAgent: scoring relevance for {len(candidates)} candidates in batches of {BATCH_SIZE}")
        start = time.time()
        system_prompt = load_prompt("curator", "relevance_scoring")

        all_raw: list = []
        for batch_idx in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[batch_idx : batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1
            total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"CuratorAgent: scoring batch {batch_num}/{total_batches} ({len(batch)} candidates)")

            user_prompt = self._build_relevance_prompt(topic_query, batch)
            raw_results = await self._invoke_json(system_prompt, user_prompt)
            if isinstance(raw_results, list):
                all_raw.extend(raw_results)

        results = self._normalise_relevance_results(all_raw, candidates)
        logger.info(f"CuratorAgent: relevance scoring completed in {time.time() - start:.2f}s ({len(results)} scores)")
        return results

    async def select_editorial(
        self,
        topic_query: str,
        scored_candidates: List[Dict[str, Any]],
        max_articles: int = 8,
        editor_feedback: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Pick best article combination. Returns list with id/rank/editorial_reasoning."""
        if not scored_candidates:
            return []

        max_articles = min(max_articles, len(scored_candidates))
        logger.info(f"CuratorAgent: editorial selection for {len(scored_candidates)} candidates, picking top {max_articles}")
        start = time.time()

        user_prompt = self._build_editorial_prompt(topic_query, scored_candidates, max_articles)
        if editor_feedback:
            feedback_addendum = load_prompt("curator", "re_curate_instructions", feedback=editor_feedback)
            user_prompt = f"{user_prompt}\n\n{feedback_addendum}"
            logger.info(f"CuratorAgent: appending editor feedback ({len(editor_feedback)} chars)")

        system_prompt = load_prompt("curator", "editorial_selection", max_articles=max_articles)

        raw_results = await self._invoke_json(system_prompt, user_prompt)
        results = self._normalise_editorial_results(raw_results, scored_candidates, max_articles)
        logger.info(f"CuratorAgent: editorial selection completed in {time.time() - start:.2f}s ({len(results)} selected)")
        return results

    async def select_editorial_agentic(
        self,
        topic_query: str,
        scored_candidates: List[Dict[str, Any]],
        max_articles: int = 8,
        editor_feedback: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Agentic editorial selection — the LLM can read articles before picking."""
        if not scored_candidates:
            return []

        max_articles = min(max_articles, len(scored_candidates))
        logger.info(
            f"CuratorAgent: AGENTIC editorial selection for "
            f"{len(scored_candidates)} candidates, picking top {max_articles}"
        )
        start = time.time()

        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            from langgraph.prebuilt import create_react_agent
            from app.agents.curator_tools import read_article

            model = ChatNVIDIA(
                model=self._model,
                api_key=getattr(settings, "NVIDIA_API_KEY", ""),
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )

            system_prompt = load_prompt(
                "curator", "editorial_selection_agentic",
                max_articles=max_articles,
            )

            candidates_text = self._build_editorial_prompt(
                topic_query, scored_candidates, max_articles,
            )
            if editor_feedback:
                feedback_addendum = load_prompt(
                    "curator", "re_curate_instructions", feedback=editor_feedback,
                )
                candidates_text = f"{candidates_text}\n\n{feedback_addendum}"

            agent = create_react_agent(
                model=model,
                tools=[read_article],
                prompt=system_prompt,
            )

            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": candidates_text}]},
                config={"recursion_limit": _MAX_REACT_STEPS},
            )

            final_text = self._extract_final_message(result)
            raw_results = self._parse_json_from_text(final_text)
            results = self._normalise_editorial_results(
                raw_results, scored_candidates, max_articles,
            )
            elapsed = time.time() - start
            logger.info(
                f"CuratorAgent: agentic selection completed in {elapsed:.2f}s "
                f"({len(results)} selected)"
            )
            return results

        except Exception as exc:
            elapsed = time.time() - start
            logger.warning(
                f"CuratorAgent: agentic selection failed after {elapsed:.2f}s "
                f"({exc}), falling back to basic selection"
            )
            return await self.select_editorial(
                topic_query, scored_candidates, max_articles, editor_feedback,
            )

    @staticmethod
    def _extract_final_message(result: Dict[str, Any]) -> str:
        """Pull the last AI message text out of the ReAct agent result."""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )
            if content and isinstance(content, str) and content.strip():
                tc = getattr(msg, "tool_calls", None)
                if not tc:
                    return content
        return ""

    @staticmethod
    def _parse_json_from_text(text: str) -> Any:
        """Extract a JSON array from text that may contain prose around it."""
        import re
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            pass
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            try:
                return _json.loads(text[start : end + 1])
            except _json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse JSON from agent output: {text[:300]}")

    @staticmethod
    def _build_relevance_prompt(topic_query: str, candidates: List[Dict[str, Any]]) -> str:
        lines = [f'Newsletter topic: "{topic_query}"\n', "Candidates:\n"]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f'{i}. id="{c["id"]}"\n'
                f"   Title: {(c.get('title') or 'No title')[:200]}\n"
                f"   Snippet: {(c.get('snippet') or 'No snippet')[:300]}\n"
                f"   Domain: {c.get('domain', 'unknown')}\n"
            )
        lines.append("\nReturn a JSON array with one object per candidate, in the same order as above.")
        return "\n".join(lines)

    @staticmethod
    def _build_editorial_prompt(topic_query: str, candidates: List[Dict[str, Any]], max_articles: int) -> str:
        lines = [f'Newsletter topic: "{topic_query}"', f"Select exactly {max_articles} articles.\n", "Candidates (pre-scored):\n"]
        for i, c in enumerate(candidates, 1):
            scores = (
                f"composite={c.get('curation_score', 0):.3f}, quality={c.get('quality_score', 0):.3f}, "
                f"freshness={c.get('freshness_score', 0):.3f}"
            )
            url_line = f"   URL: {c['url']}\n" if c.get("url") else ""
            lines.append(
                f'{i}. id="{c["id"]}" | {c.get("domain", "unknown")}\n'
                f"   Title: {(c.get('title') or 'No title')[:200]}\n"
                f"{url_line}"
                f"   Snippet: {(c.get('snippet') or '')[:300]}\n"
                f"   Scores: {scores}\n"
            )
        lines.append(f"\nPick the best {max_articles} articles. Return a JSON array ordered by rank (1 = headline).")
        return "\n".join(lines)

    @staticmethod
    def _normalise_relevance_results(raw: Any, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            raise ValueError(f"Expected list, got {type(raw).__name__}")

        result_map: Dict[str, Dict] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id", ""))
            score = item.get("relevance_score", 0.5)
            try:
                score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                score = 0.5
            result_map[cid] = {"id": cid, "relevance_score": score, "reasoning": str(item.get("reasoning", ""))[:200]}

        results = []
        for c in candidates:
            cid = str(c["id"])
            if cid in result_map:
                results.append(result_map[cid])
            else:
                logger.warning(f"LLM omitted candidate {cid}, using fallback 0.5")
                results.append({"id": cid, "relevance_score": 0.5, "reasoning": "Not scored by LLM (missing from response)"})
        return results

    @staticmethod
    def _normalise_editorial_results(raw: Any, candidates: List[Dict[str, Any]], max_articles: int) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            raise ValueError(f"Expected list, got {type(raw).__name__}")

        valid_ids = {str(c["id"]) for c in candidates}
        results, seen_ids = [], set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id", ""))
            if cid not in valid_ids or cid in seen_ids:
                continue
            seen_ids.add(cid)
            results.append({"id": cid, "rank": len(results) + 1, "editorial_reasoning": str(item.get("editorial_reasoning", ""))[:200]})
            if len(results) >= max_articles:
                break

        if not results:
            raise ValueError("LLM returned no valid selections")
        return results


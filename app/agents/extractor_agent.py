"""ExtractorAgent — LLM-powered extraction strategy planning and quality evaluation."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.extractor")

VALID_STRATEGIES = {"trafilatura", "playwright", "trafilatura_then_playwright"}
VALID_RECOMMENDATIONS = {"accept", "retry_playwright", "skip"}


class ExtractorAgent(BaseAgent):
    """LLM-powered extractor for strategy planning and quality evaluation."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(
            model=model or getattr(settings, "EXTRACTOR_AGENT_MODEL", None) or settings.NVIDIA_MODEL,
            temperature=temperature if temperature is not None else 0.2,
            max_tokens=2048,
        )

    async def plan_extraction(self, url: str, domain: str) -> Dict[str, Any]:
        """Recommend optimal extraction strategy for a URL."""
        logger.info(f"ExtractorAgent: planning extraction for {url[:80]}")
        start = time.time()

        raw = await self._invoke_json(load_prompt("extractor", "extraction_strategy"), self._build_strategy_prompt(url, domain))
        result = self._normalise_strategy_result(raw)
        logger.info(f"ExtractorAgent: strategy={result['strategy']} for {domain} in {time.time() - start:.2f}s")
        return result

    async def evaluate_quality(self, url: str, extracted_text: str, word_count: int) -> Dict[str, Any]:
        """Evaluate extracted text quality."""
        logger.info(f"ExtractorAgent: evaluating quality for {url[:80]} ({word_count} words)")
        start = time.time()

        raw = await self._invoke_json(load_prompt("extractor", "content_quality"), self._build_quality_prompt(url, extracted_text, word_count))
        result = self._normalise_quality_result(raw, word_count)
        logger.info(f"ExtractorAgent: quality={result['quality_score']:.2f}, rec={result['recommendation']} in {time.time() - start:.2f}s")
        return result

    @staticmethod
    def _build_strategy_prompt(url: str, domain: str) -> str:
        return f'URL: "{url}"\nDomain: "{domain}"\n\nRecommend the best extraction strategy for this URL.'

    @staticmethod
    def _build_quality_prompt(url: str, extracted_text: str, word_count: int) -> str:
        return f'URL: "{url}"\nWord count: {word_count}\n\nExtracted text preview (first 1500 chars):\n---\n{extracted_text[:1500]}\n---\n\nEvaluate the quality of this extraction.'

    @staticmethod
    def _normalise_strategy_result(raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")
        strategy = str(raw.get("strategy", "trafilatura_then_playwright"))
        if strategy not in VALID_STRATEGIES:
            strategy = "trafilatura_then_playwright"
        challenges = raw.get("expected_challenges", [])
        if not isinstance(challenges, list):
            challenges = []
        return {"strategy": strategy, "reasoning": str(raw.get("reasoning", ""))[:200], "expected_challenges": [str(c)[:100] for c in challenges[:3]]}

    @staticmethod
    def _normalise_quality_result(raw: Any, word_count: int) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")

        score = raw.get("quality_score", 0.5)
        try:
            score = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            score = 0.5

        is_usable = raw.get("is_usable", score >= 0.4)
        if not isinstance(is_usable, bool):
            is_usable = score >= 0.4

        recommendation = str(raw.get("recommendation", "accept"))
        if recommendation not in VALID_RECOMMENDATIONS:
            recommendation = "accept" if is_usable else "skip"

        issues = raw.get("issues", [])
        if not isinstance(issues, list):
            issues = []

        return {"quality_score": score, "is_usable": is_usable, "issues": [str(i)[:100] for i in issues[:3]], "recommendation": recommendation, "reasoning": str(raw.get("reasoning", ""))[:200]}


"""QAAgent — LLM-powered fact-checking and quality review for newsletters."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.base_agent import BaseAgent, load_prompt
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("agents.qa")

VALID_VERDICTS_FACT = {"pass", "warning", "fail"}
VALID_VERDICTS_QUALITY = {"publish", "review", "rewrite"}


class QAAgent(BaseAgent):
    """LLM-powered QA agent for newsletter validation."""

    def __init__(self, model: Optional[str] = None, temperature: Optional[float] = None):
        super().__init__(
            model=model or getattr(settings, "QA_AGENT_MODEL", None) or settings.NVIDIA_MODEL,
            temperature=temperature if temperature is not None else 0.1,
            max_tokens=4096,
        )

    async def fact_check(self, newsletter_json: Dict[str, Any], source_articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verify summaries against source content. Returns overall_accuracy + per-section verdicts."""
        logger.info(f"QAAgent: fact-checking newsletter with {len(source_articles)} source articles")
        start = time.time()

        raw = await self._invoke_json(load_prompt("qa", "fact_check"), self._build_fact_check_prompt(newsletter_json, source_articles))
        result = self._normalise_fact_check(raw)
        logger.info(f"QAAgent: fact-check completed in {time.time() - start:.2f}s — accuracy={result['overall_accuracy']:.2f}")
        return result

    async def quality_review(self, newsletter_json: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate overall newsletter quality. Returns overall_quality + criteria + verdict."""
        logger.info("QAAgent: reviewing newsletter quality")
        start = time.time()

        raw = await self._invoke_json(load_prompt("qa", "quality_review"), self._build_quality_prompt(newsletter_json))
        result = self._normalise_quality_review(raw)
        logger.info(f"QAAgent: quality review in {time.time() - start:.2f}s — quality={result['overall_quality']:.2f}, verdict={result['verdict']}")
        return result

    _SECTION_LABELS = {
        "headline": "Headline",
        "latest_news": "Latest News",
        "company_updates": "Company Updates",
        "tools_and_products": "Tools & Products",
        "open_source_spotlight": "Open Source Spotlight",
        "quick_bytes": "Quick Bytes",
        "research_spotlight": "Research Spotlight",
    }

    @classmethod
    def _build_fact_check_prompt(cls, newsletter_json: Dict[str, Any], source_articles: List[Dict[str, Any]]) -> str:
        lines = ["NEWSLETTER SECTIONS TO VERIFY:\n"]

        headline = newsletter_json.get("headline")
        if headline and isinstance(headline, dict):
            title = headline.get("title", "N/A")
            lines.append(f"[Headline] {title}\n  Summary: {headline.get('summary', 'N/A')}\n  Source: {headline.get('source_url', 'N/A')}\n")

        for section_key in ["latest_news", "company_updates", "tools_and_products", "open_source_spotlight", "quick_bytes"]:
            label = cls._SECTION_LABELS.get(section_key, section_key)
            items = newsletter_json.get(section_key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = item.get("title", "N/A")
                lines.append(f"[{label}] {title}\n  Summary: {item.get('summary', 'N/A')}\n  Source: {item.get('source_url', 'N/A')}\n")

        research = newsletter_json.get("research_spotlight")
        if research and isinstance(research, dict):
            lines.append(f"[Research Spotlight] {research.get('title', 'N/A')}\n  Summary: {research.get('summary', 'N/A')}\n  Source: {research.get('source_url', 'N/A')}\n")

        lines.append("\nSOURCE ARTICLES:\n")
        for a in source_articles:
            lines.append(f"- URL: {a.get('url', 'N/A')}\n  Title: {a.get('title', 'N/A')}\n  Content: {(a.get('content') or '')[:3000]}\n")

        lines.append("\nFact-check each section against the source articles. Use the exact section label (e.g. 'Headline', 'Latest News') and article title in your response.")
        return "\n".join(lines)

    @staticmethod
    def _build_quality_prompt(newsletter_json: Dict[str, Any]) -> str:
        import json as _json
        compact = {k: v for k, v in newsletter_json.items() if k != "quality_checks"}
        return f"Review the following newsletter draft for quality:\n\n{_json.dumps(compact, indent=2, default=str)[:4000]}\n\nEvaluate completeness, tone, summary quality, structure, and formatting."

    @staticmethod
    def _normalise_fact_check(raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")

        accuracy = raw.get("overall_accuracy", 0.8)
        try:
            accuracy = max(0.0, min(1.0, float(accuracy)))
        except (TypeError, ValueError):
            accuracy = 0.8

        sections = []
        for s in (raw.get("sections") or []):
            if not isinstance(s, dict):
                continue
            score = s.get("accuracy_score", 0.8)
            try:
                score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                score = 0.8
            verdict = str(s.get("verdict", "pass"))
            if verdict not in VALID_VERDICTS_FACT:
                verdict = "pass" if score >= 0.7 else ("warning" if score >= 0.4 else "fail")
            issues = s.get("issues", [])
            if not isinstance(issues, list):
                issues = []
            sections.append({
                "section_type": str(s.get("section_type", "")), "title": str(s.get("title", "")),
                "accuracy_score": score, "issues": [str(i)[:200] for i in issues[:3]], "verdict": verdict,
            })

        return {"overall_accuracy": accuracy, "sections": sections}

    @staticmethod
    def _normalise_quality_review(raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Expected dict, got {type(raw).__name__}")

        quality = raw.get("overall_quality", 0.8)
        try:
            quality = max(0.0, min(1.0, float(quality)))
        except (TypeError, ValueError):
            quality = 0.8

        criteria_raw = raw.get("criteria") or {}
        criteria = {}
        for key in ["completeness", "tone_consistency", "summary_quality", "structure", "formatting"]:
            val = criteria_raw.get(key, 0.8) if isinstance(criteria_raw, dict) else 0.8
            try:
                criteria[key] = max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                criteria[key] = 0.8

        improvements = raw.get("improvements", [])
        if not isinstance(improvements, list):
            improvements = []

        verdict = str(raw.get("verdict", "publish"))
        if verdict not in VALID_VERDICTS_QUALITY:
            verdict = "publish" if quality >= 0.7 else ("review" if quality >= 0.4 else "rewrite")

        return {"overall_quality": quality, "criteria": criteria, "improvements": [str(i)[:200] for i in improvements[:5]], "verdict": verdict}


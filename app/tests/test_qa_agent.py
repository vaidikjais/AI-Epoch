"""Tests for QAAgent - LLM-powered newsletter quality assurance."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.qa_agent import QAAgent


def _newsletter():
    return {
        "issue_title": "AI Newsletter",
        "headline": {
            "section_type": "headline",
            "title": "GPT-5 Launch",
            "summary": "OpenAI releases GPT-5 with major improvements.",
            "source_label": "OpenAI",
            "source_url": "https://openai.com/gpt5",
        },
        "latest_news": [{
            "section_type": "news",
            "title": "AI Regulation",
            "summary": "EU proposes new AI regulation framework.",
            "source_label": "CNBC",
            "source_url": "https://cnbc.com/ai-regulation",
        }],
        "company_updates": [],
        "research_spotlight": None,
        "tools_and_products": [],
        "quick_bytes": [],
    }


def _source_articles():
    return [
        {
            "id": "1",
            "title": "GPT-5 Launch",
            "url": "https://openai.com/gpt5",
            "content": "OpenAI has released GPT-5 with significant improvements...",
        },
        {
            "id": "2",
            "title": "AI Regulation",
            "url": "https://cnbc.com/ai-regulation",
            "content": "The EU has proposed a new framework for AI regulation...",
        },
    ]


class TestFactCheck:

    @pytest.mark.asyncio
    async def test_successful_fact_check(self):
        mock_response = json.dumps({
            "overall_accuracy": 0.92,
            "sections": [
                {
                    "section_type": "headline",
                    "title": "GPT-5 Launch",
                    "accuracy_score": 0.95,
                    "issues": [],
                    "verdict": "pass",
                },
                {
                    "section_type": "news",
                    "title": "AI Regulation",
                    "accuracy_score": 0.88,
                    "issues": ["Minor detail about timeline"],
                    "verdict": "pass",
                },
            ],
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.fact_check(_newsletter(), _source_articles())

        assert result["overall_accuracy"] == 0.92
        assert len(result["sections"]) == 2
        assert result["sections"][0]["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_low_accuracy_detected(self):
        mock_response = json.dumps({
            "overall_accuracy": 0.35,
            "sections": [
                {
                    "section_type": "headline",
                    "title": "GPT-5 Launch",
                    "accuracy_score": 0.2,
                    "issues": ["Claims GPT-5 is open source but source says nothing about this"],
                    "verdict": "fail",
                },
            ],
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.fact_check(_newsletter(), _source_articles())

        assert result["overall_accuracy"] == 0.35
        assert result["sections"][0]["verdict"] == "fail"

    @pytest.mark.asyncio
    async def test_accuracy_score_clamped(self):
        mock_response = json.dumps({
            "overall_accuracy": 1.5,
            "sections": [],
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.fact_check(_newsletter(), _source_articles())

        assert result["overall_accuracy"] == 1.0

    @pytest.mark.asyncio
    async def test_invalid_verdict_normalised(self):
        """Invalid verdict is derived from score."""
        mock_response = json.dumps({
            "overall_accuracy": 0.8,
            "sections": [{
                "section_type": "headline",
                "title": "Test",
                "accuracy_score": 0.3,
                "issues": [],
                "verdict": "maybe",
            }],
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.fact_check(_newsletter(), _source_articles())

        # Score 0.3 < 0.4 -> "fail"
        assert result["sections"][0]["verdict"] == "fail"

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.fact_check(_newsletter(), _source_articles())


class TestQualityReview:

    @pytest.mark.asyncio
    async def test_successful_review(self):
        mock_response = json.dumps({
            "overall_quality": 0.85,
            "criteria": {
                "completeness": 0.9,
                "tone_consistency": 0.85,
                "summary_quality": 0.8,
                "structure": 0.85,
                "formatting": 0.85,
            },
            "improvements": ["Add more detail to quick bytes"],
            "verdict": "publish",
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.quality_review(_newsletter())

        assert result["overall_quality"] == 0.85
        assert result["verdict"] == "publish"
        assert len(result["improvements"]) == 1
        assert result["criteria"]["completeness"] == 0.9

    @pytest.mark.asyncio
    async def test_rewrite_verdict(self):
        mock_response = json.dumps({
            "overall_quality": 0.3,
            "criteria": {
                "completeness": 0.2,
                "tone_consistency": 0.3,
                "summary_quality": 0.3,
                "structure": 0.4,
                "formatting": 0.3,
            },
            "improvements": ["Rewrite all summaries", "Fix structure", "Add missing articles"],
            "verdict": "rewrite",
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.quality_review(_newsletter())

        assert result["verdict"] == "rewrite"
        assert result["overall_quality"] == 0.3

    @pytest.mark.asyncio
    async def test_quality_score_clamped(self):
        mock_response = json.dumps({
            "overall_quality": -0.5,
            "criteria": {},
            "improvements": [],
            "verdict": "rewrite",
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.quality_review(_newsletter())

        assert result["overall_quality"] == 0.0

    @pytest.mark.asyncio
    async def test_invalid_verdict_normalised(self):
        mock_response = json.dumps({
            "overall_quality": 0.8,
            "criteria": {},
            "improvements": [],
            "verdict": "unknown",
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.quality_review(_newsletter())

        # quality 0.8 >= 0.7 -> "publish"
        assert result["verdict"] == "publish"

    @pytest.mark.asyncio
    async def test_missing_criteria_get_defaults(self):
        mock_response = json.dumps({
            "overall_quality": 0.7,
            "improvements": [],
            "verdict": "publish",
        })

        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.quality_review(_newsletter())

        assert all(k in result["criteria"] for k in [
            "completeness", "tone_consistency", "summary_quality",
            "structure", "formatting",
        ])

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        agent = QAAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.quality_review(_newsletter())


class TestQAPromptBuilders:

    def test_fact_check_prompt_contains_sections(self):
        prompt = QAAgent._build_fact_check_prompt(_newsletter(), _source_articles())
        assert "GPT-5 Launch" in prompt
        assert "AI Regulation" in prompt
        assert "openai.com/gpt5" in prompt

    def test_quality_prompt_contains_newsletter(self):
        prompt = QAAgent._build_quality_prompt(_newsletter())
        assert "AI Newsletter" in prompt
        assert "GPT-5 Launch" in prompt



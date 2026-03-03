"""Tests for ExtractorAgent - LLM-powered extraction strategy and quality evaluation."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.extractor_agent import ExtractorAgent


class TestPlanExtraction:

    @pytest.mark.asyncio
    async def test_successful_strategy(self):
        mock_response = json.dumps({
            "strategy": "trafilatura",
            "reasoning": "Standard news site with clean HTML",
            "expected_challenges": ["Cookie banner"],
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_extraction(
                "https://techcrunch.com/2025/01/01/ai-news",
                "techcrunch.com",
            )

        assert result["strategy"] == "trafilatura"
        assert "Standard news" in result["reasoning"]
        assert len(result["expected_challenges"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_strategy_normalised(self):
        """Invalid strategy values fall back to trafilatura_then_playwright."""
        mock_response = json.dumps({
            "strategy": "selenium",
            "reasoning": "Custom tool",
            "expected_challenges": [],
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_extraction("https://example.com", "example.com")

        assert result["strategy"] == "trafilatura_then_playwright"

    @pytest.mark.asyncio
    async def test_playwright_strategy(self):
        mock_response = json.dumps({
            "strategy": "playwright",
            "reasoning": "SPA with dynamic content loading",
            "expected_challenges": ["Dynamic rendering", "JS hydration"],
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_extraction(
                "https://openai.com/blog/gpt5", "openai.com"
            )

        assert result["strategy"] == "playwright"
        assert len(result["expected_challenges"]) == 2

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.plan_extraction("https://example.com", "example.com")

    @pytest.mark.asyncio
    async def test_challenges_truncated(self):
        """Challenges list is limited to 3 items."""
        mock_response = json.dumps({
            "strategy": "trafilatura",
            "reasoning": "Test",
            "expected_challenges": ["a", "b", "c", "d", "e"],
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_extraction("https://example.com", "example.com")

        assert len(result["expected_challenges"]) == 3


class TestEvaluateQuality:

    @pytest.mark.asyncio
    async def test_high_quality_accepted(self):
        mock_response = json.dumps({
            "quality_score": 0.9,
            "is_usable": True,
            "issues": [],
            "recommendation": "accept",
            "reasoning": "Clean article text with proper paragraphs",
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.evaluate_quality(
                "https://example.com/article",
                "This is a well-written article about AI...",
                500,
            )

        assert result["quality_score"] == 0.9
        assert result["is_usable"] is True
        assert result["recommendation"] == "accept"

    @pytest.mark.asyncio
    async def test_low_quality_skip(self):
        mock_response = json.dumps({
            "quality_score": 0.1,
            "is_usable": False,
            "issues": ["Paywall message detected", "No article content"],
            "recommendation": "skip",
            "reasoning": "Text is a paywall login prompt",
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.evaluate_quality(
                "https://example.com/article",
                "Please login to continue reading...",
                15,
            )

        assert result["quality_score"] == 0.1
        assert result["is_usable"] is False
        assert result["recommendation"] == "skip"

    @pytest.mark.asyncio
    async def test_retry_recommendation(self):
        mock_response = json.dumps({
            "quality_score": 0.35,
            "is_usable": False,
            "issues": ["Content appears truncated"],
            "recommendation": "retry_playwright",
            "reasoning": "Only navigation text extracted",
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.evaluate_quality(
                "https://spa-site.com/article", "Nav | Home | About", 5
            )

        assert result["recommendation"] == "retry_playwright"

    @pytest.mark.asyncio
    async def test_score_clamped(self):
        mock_response = json.dumps({
            "quality_score": 1.5,
            "is_usable": True,
            "issues": [],
            "recommendation": "accept",
            "reasoning": "Over-scored",
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.evaluate_quality("https://example.com", "text", 100)

        assert result["quality_score"] == 1.0

    @pytest.mark.asyncio
    async def test_invalid_recommendation_normalised(self):
        mock_response = json.dumps({
            "quality_score": 0.8,
            "is_usable": True,
            "issues": [],
            "recommendation": "reprocess",
            "reasoning": "Unknown rec",
        })

        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.evaluate_quality("https://example.com", "text", 100)

        # is_usable=True -> recommendation defaults to "accept"
        assert result["recommendation"] == "accept"

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        agent = ExtractorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.evaluate_quality("https://example.com", "text " * 100, 100)


class TestExtractorPromptBuilders:

    def test_strategy_prompt_contains_url_and_domain(self):
        prompt = ExtractorAgent._build_strategy_prompt(
            "https://techcrunch.com/ai-news", "techcrunch.com"
        )
        assert "techcrunch.com/ai-news" in prompt
        assert "techcrunch.com" in prompt

    def test_quality_prompt_contains_text_preview(self):
        text = "This is a test article about artificial intelligence." * 10
        prompt = ExtractorAgent._build_quality_prompt(
            "https://example.com/art", text, 100
        )
        assert "example.com/art" in prompt
        assert "100" in prompt
        assert "artificial intelligence" in prompt



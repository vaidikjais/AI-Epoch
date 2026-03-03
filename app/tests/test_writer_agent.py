"""Tests for WriterAgent - LLM-powered newsletter content generation."""

import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.writer_agent import WriterAgent


def _article(title="AI breakthrough", domain="example.com", score=0.8):
    return {
        "id": str(uuid4()),
        "title": title,
        "url": f"https://{domain}/article",
        "domain": domain,
        "content": f"Full article about {title} with detailed coverage...",
        "curation_score": score,
    }


def _plan(articles, headline_idx=0):
    headline_id = articles[headline_idx]["id"]
    remaining = [a for i, a in enumerate(articles) if i != headline_idx]
    return {
        "headline_id": headline_id,
        "sections": [
            {
                "section": "latest_news",
                "article_ids": [a["id"] for a in remaining],
            }
        ],
        "narrative_arc": "AI developments this week",
        "editorial_notes": "Focus on impact",
    }


class TestWriteNewsletter:

    @pytest.mark.asyncio
    async def test_successful_generation(self):
        a1 = _article("GPT-5 Launch", "openai.com", 0.95)
        a2 = _article("AI Regulation News", "cnbc.com", 0.8)
        articles = [a1, a2]
        plan = _plan(articles)

        mock_response = json.dumps({
            "issue_title": "AI Newsletter",
            "issue_number": 42,
            "date_iso": "2025-01-01T00:00:00Z",
            "subheadline": "GPT-5 launches, AI regulation heats up",
            "intro": "Welcome to AI Newsletter...",
            "headline": {
                "section_type": "headline",
                "title": "GPT-5 Launch",
                "summary": "OpenAI releases GPT-5...",
                "source_label": "OpenAI",
                "source_url": a1["url"],
                "emoji": "🏆",
                "confidence": "high",
            },
            "latest_news": [{
                "section_type": "news",
                "title": "AI Regulation",
                "summary": "New regulations proposed...",
                "source_label": "CNBC",
                "source_url": a2["url"],
                "emoji": "📰",
                "confidence": "high",
            }],
            "company_updates": [],
            "research_spotlight": None,
            "tools_and_products": [],
            "quick_bytes": [],
            "wrap": "Keep building.",
            "footer": "© AI Newsletter",
            "total_articles": 2,
            "estimated_read_time": "4 minutes",
            "quality_checks": {
                "all_sections_present": True,
                "word_counts_valid": True,
                "all_articles_included": True,
            },
        })

        agent = WriterAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.write_newsletter(articles, plan, issue_number=42)

        assert result["issue_title"] == "AI Newsletter"
        assert result["total_articles"] == 2
        assert result["headline"]["title"] == "GPT-5 Launch"
        assert len(result["latest_news"]) == 1

    @pytest.mark.asyncio
    async def test_missing_fields_get_defaults(self):
        a1 = _article("Article", "example.com")
        plan = _plan([a1])

        mock_response = json.dumps({
            "headline": {"title": "Test", "summary": "Test summary"},
            "latest_news": [],
        })

        agent = WriterAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.write_newsletter([a1], plan, issue_number=1)

        assert result["issue_title"] == "AI Newsletter"
        assert result["total_articles"] == 1
        assert "date_iso" in result
        assert isinstance(result["company_updates"], list)
        assert isinstance(result["quick_bytes"], list)

    @pytest.mark.asyncio
    async def test_list_fields_normalised(self):
        """Non-list section fields are normalised to empty lists."""
        a1 = _article("Article")
        plan = _plan([a1])

        mock_response = json.dumps({
            "latest_news": "not a list",
            "company_updates": None,
            "tools_and_products": 42,
            "quick_bytes": {"bad": "type"},
        })

        agent = WriterAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.write_newsletter([a1], plan)

        assert isinstance(result["latest_news"], list)
        assert isinstance(result["company_updates"], list)
        assert isinstance(result["tools_and_products"], list)
        assert isinstance(result["quick_bytes"], list)

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        a1 = _article("Top story", "openai.com", 0.9)
        a2 = _article("News", "cnbc.com", 0.8)
        articles = [a1, a2]
        plan = _plan(articles)

        agent = WriterAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.write_newsletter(articles, plan, issue_number=5)

    @pytest.mark.asyncio
    async def test_empty_articles_returns_empty(self):
        agent = WriterAgent()
        result = await agent.write_newsletter([], {}, issue_number=1)
        assert result["total_articles"] == 0
        assert result["headline"] is None


class TestWriterHelpers:

    def test_empty_newsletter(self):
        result = WriterAgent._empty_newsletter(42)
        assert result["total_articles"] == 0
        assert result["issue_number"] == 42
        assert result["headline"] is None

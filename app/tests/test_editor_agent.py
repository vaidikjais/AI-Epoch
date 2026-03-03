"""Tests for EditorAgent - LLM-powered newsletter structure planning."""

import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.editor_agent import EditorAgent


def _article(title="AI breakthrough", domain="example.com", score=0.8):
    return {
        "id": str(uuid4()),
        "title": title,
        "url": f"https://{domain}/article",
        "domain": domain,
        "content": f"Article about {title}",
        "curation_score": score,
    }


class TestPlanStructure:

    @pytest.mark.asyncio
    async def test_successful_plan(self):
        a1 = _article("GPT-5 Launch", "openai.com", 0.95)
        a2 = _article("AI regulation", "cnbc.com", 0.8)
        a3 = _article("New tool", "github.com", 0.7)
        articles = [a1, a2, a3]

        mock_response = json.dumps({
            "headline_id": a1["id"],
            "sections": [
                {"section": "latest_news", "article_ids": [a2["id"]]},
                {"section": "tools_and_products", "article_ids": [a3["id"]]},
            ],
            "narrative_arc": "AI safety and new tools dominate the week",
            "editorial_notes": "Emphasize GPT-5 impact",
        })

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_structure(articles)

        assert result["headline_id"] == a1["id"]
        assert len(result["sections"]) == 2
        assert result["sections"][0]["section"] == "latest_news"
        assert result["narrative_arc"] == "AI safety and new tools dominate the week"

    @pytest.mark.asyncio
    async def test_invalid_headline_id_picks_best(self):
        """If headline_id is invalid, picks highest-scored article."""
        a1 = _article("Low score", "a.com", 0.3)
        a2 = _article("High score", "b.com", 0.9)

        mock_response = json.dumps({
            "headline_id": "nonexistent-id",
            "sections": [],
            "narrative_arc": "Test",
        })

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_structure([a1, a2])

        assert result["headline_id"] == a2["id"]

    @pytest.mark.asyncio
    async def test_unassigned_articles_go_to_quick_bytes(self):
        a1 = _article("Headline", "openai.com", 0.9)
        a2 = _article("Unassigned", "random.com", 0.5)

        mock_response = json.dumps({
            "headline_id": a1["id"],
            "sections": [],
            "narrative_arc": "Minimal edition",
        })

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_structure([a1, a2])

        # a2 should appear in quick_bytes
        quick_bytes = [s for s in result["sections"] if s["section"] == "quick_bytes"]
        assert len(quick_bytes) == 1
        assert a2["id"] in quick_bytes[0]["article_ids"]

    @pytest.mark.asyncio
    async def test_duplicate_ids_in_sections_deduplicated(self):
        a1 = _article("Headline", "openai.com", 0.9)
        a2 = _article("Article", "cnbc.com", 0.8)

        mock_response = json.dumps({
            "headline_id": a1["id"],
            "sections": [
                {"section": "latest_news", "article_ids": [a2["id"]]},
                {"section": "company_updates", "article_ids": [a2["id"]]},
            ],
            "narrative_arc": "Test",
        })

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_structure([a1, a2])

        # a2 should only appear once
        all_ids = []
        for s in result["sections"]:
            all_ids.extend(s["article_ids"])
        assert all_ids.count(a2["id"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_section_name_filtered(self):
        a1 = _article("Headline", "a.com", 0.9)
        a2 = _article("Article", "b.com", 0.8)

        mock_response = json.dumps({
            "headline_id": a1["id"],
            "sections": [
                {"section": "nonexistent_section", "article_ids": [a2["id"]]},
            ],
            "narrative_arc": "Test",
        })

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            result = await agent.plan_structure([a1, a2])

        # a2 ends up in quick_bytes (unassigned)
        quick_bytes = [s for s in result["sections"] if s["section"] == "quick_bytes"]
        assert len(quick_bytes) == 1
        assert a2["id"] in quick_bytes[0]["article_ids"]

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        a1 = _article("Top story", "openai.com", 0.9)
        a2 = _article("News", "cnbc.com", 0.8)

        agent = EditorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.plan_structure([a1, a2])

    @pytest.mark.asyncio
    async def test_empty_articles_returns_empty_plan(self):
        agent = EditorAgent()
        result = await agent.plan_structure([])
        assert result["headline_id"] == ""
        assert result["sections"] == []


class TestEditorPromptBuilder:

    def test_prompt_contains_all_articles(self):
        a1 = _article("Article One", "a.com", 0.9)
        a2 = _article("Article Two", "b.com", 0.7)
        prompt = EditorAgent._build_structure_prompt([a1, a2])
        assert "Article One" in prompt
        assert "Article Two" in prompt
        assert a1["id"] in prompt
        assert "a.com" in prompt

    def test_prompt_includes_scores(self):
        a1 = _article("Test", "example.com", 0.876)
        prompt = EditorAgent._build_structure_prompt([a1])
        assert "0.876" in prompt



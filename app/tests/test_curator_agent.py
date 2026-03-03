"""Tests for CuratorAgent - LLM-powered relevance scoring and editorial selection."""

import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.base_agent import BaseAgent
from app.agents.curator_agent import CuratorAgent


def _candidate(title="AI breakthrough", snippet="New model released", domain="example.com"):
    return {
        "id": str(uuid4()),
        "title": title,
        "snippet": snippet,
        "domain": domain,
    }


def _scored_candidate(
    title="AI breakthrough",
    snippet="New model released",
    domain="example.com",
    curation_score=0.8,
    quality_score=0.85,
    freshness_score=0.9,
):
    return {
        "id": str(uuid4()),
        "title": title,
        "snippet": snippet,
        "domain": domain,
        "curation_score": curation_score,
        "quality_score": quality_score,
        "freshness_score": freshness_score,
    }


class TestExtractJson:

    def test_clean_json_object(self):
        raw = '{"key": "value"}'
        assert BaseAgent._extract_json(raw) == {"key": "value"}

    def test_clean_json_array(self):
        raw = '[{"id": 1}]'
        assert BaseAgent._extract_json(raw) == [{"id": 1}]

    def test_markdown_fenced_json(self):
        raw = '```json\n{"key": "value"}\n```'
        assert BaseAgent._extract_json(raw) == {"key": "value"}

    def test_markdown_fenced_no_lang(self):
        raw = '```\n[{"a": 1}]\n```'
        assert BaseAgent._extract_json(raw) == [{"a": 1}]

    def test_json_embedded_in_prose(self):
        raw = 'Here is the result:\n{"key": "value"}\nDone.'
        assert BaseAgent._extract_json(raw) == {"key": "value"}

    def test_array_embedded_in_prose(self):
        raw = 'Sure!\n[{"id": "x", "score": 0.5}]\nHope this helps!'
        result = BaseAgent._extract_json(raw)
        assert isinstance(result, list)
        assert result[0]["id"] == "x"

    def test_unparseable_returns_none(self):
        assert BaseAgent._extract_json("no json here") is None

    def test_empty_string_returns_none(self):
        assert BaseAgent._extract_json("") is None


class TestScoreRelevance:

    @pytest.mark.asyncio
    async def test_successful_scoring(self):
        c1 = _candidate(title="GPT-5 launch", domain="openai.com")
        c2 = _candidate(title="Cloud pricing update", domain="aws.com")
        candidates = [c1, c2]

        mock_response = json.dumps([
            {"id": c1["id"], "relevance_score": 0.95, "reasoning": "Direct GPT coverage"},
            {"id": c2["id"], "relevance_score": 0.3, "reasoning": "Tangential to AI"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.score_relevance("AI news", candidates)

        assert len(results) == 2
        assert results[0]["id"] == c1["id"]
        assert results[0]["relevance_score"] == 0.95
        assert results[1]["relevance_score"] == 0.3

    @pytest.mark.asyncio
    async def test_missing_candidate_gets_fallback_score(self):
        """If LLM omits a candidate, it gets a 0.5 fallback."""
        c1 = _candidate(title="Article 1")
        c2 = _candidate(title="Article 2")

        # LLM only returns score for c1
        mock_response = json.dumps([
            {"id": c1["id"], "relevance_score": 0.9, "reasoning": "Great article"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.score_relevance("AI news", [c1, c2])

        assert len(results) == 2
        assert results[0]["relevance_score"] == 0.9
        assert results[1]["relevance_score"] == 0.5  # fallback

    @pytest.mark.asyncio
    async def test_score_clamped_to_valid_range(self):
        c1 = _candidate()
        mock_response = json.dumps([
            {"id": c1["id"], "relevance_score": 1.5, "reasoning": "Over-scored"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.score_relevance("AI news", [c1])

        assert results[0]["relevance_score"] == 1.0

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        c1 = _candidate()
        c2 = _candidate()

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.score_relevance("AI news", [c1, c2])

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self):
        agent = CuratorAgent()
        results = await agent.score_relevance("AI news", [])
        assert results == []

    @pytest.mark.asyncio
    async def test_malformed_json_triggers_retry(self):
        c1 = _candidate()
        good_response = json.dumps([
            {"id": c1["id"], "relevance_score": 0.8, "reasoning": "Good"},
        ])

        agent = CuratorAgent()
        # First call returns garbage, second returns valid JSON
        with patch.object(
            agent, "_invoke",
            new_callable=AsyncMock,
            side_effect=["not valid json at all", good_response],
        ):
            results = await agent.score_relevance("AI news", [c1])

        assert len(results) == 1
        assert results[0]["relevance_score"] == 0.8


class TestSelectEditorial:

    @pytest.mark.asyncio
    async def test_successful_selection(self):
        c1 = _scored_candidate(title="Story A", domain="openai.com")
        c2 = _scored_candidate(title="Story B", domain="bbc.com")
        c3 = _scored_candidate(title="Story C", domain="arxiv.org")
        candidates = [c1, c2, c3]

        mock_response = json.dumps([
            {"id": c2["id"], "rank": 1, "editorial_reasoning": "Top headline from trusted news"},
            {"id": c1["id"], "rank": 2, "editorial_reasoning": "Primary source announcement"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.select_editorial("AI news", candidates, max_articles=2)

        assert len(results) == 2
        assert results[0]["id"] == c2["id"]
        assert results[0]["rank"] == 1
        assert results[1]["id"] == c1["id"]
        assert results[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_invalid_ids_filtered_out(self):
        c1 = _scored_candidate(title="Story A")

        mock_response = json.dumps([
            {"id": "nonexistent-id", "rank": 1, "editorial_reasoning": "Ghost article"},
            {"id": c1["id"], "rank": 2, "editorial_reasoning": "Real article"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.select_editorial("AI news", [c1], max_articles=2)

        assert len(results) == 1
        assert results[0]["id"] == c1["id"]
        assert results[0]["rank"] == 1  # re-ranked after filtering

    @pytest.mark.asyncio
    async def test_duplicate_ids_deduplicated(self):
        """If LLM returns the same ID twice, only the first is kept."""
        c1 = _scored_candidate(title="Story A")

        mock_response = json.dumps([
            {"id": c1["id"], "rank": 1, "editorial_reasoning": "First pick"},
            {"id": c1["id"], "rank": 2, "editorial_reasoning": "Duplicate pick"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.select_editorial("AI news", [c1], max_articles=2)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        c1 = _scored_candidate(title="Low score", curation_score=0.3)
        c2 = _scored_candidate(title="High score", curation_score=0.9)

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.select_editorial("AI news", [c1, c2], max_articles=2)

    @pytest.mark.asyncio
    async def test_max_articles_capped_at_candidate_count(self):
        c1 = _scored_candidate()

        mock_response = json.dumps([
            {"id": c1["id"], "rank": 1, "editorial_reasoning": "Only option"},
        ])

        agent = CuratorAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock, return_value=mock_response):
            results = await agent.select_editorial("AI news", [c1], max_articles=5)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self):
        agent = CuratorAgent()
        results = await agent.select_editorial("AI news", [], max_articles=3)
        assert results == []


class TestPromptBuilders:

    def test_relevance_prompt_contains_all_candidates(self):
        c1 = _candidate(title="Article One", domain="a.com")
        c2 = _candidate(title="Article Two", domain="b.com")
        prompt = CuratorAgent._build_relevance_prompt("AI news", [c1, c2])
        assert "AI news" in prompt
        assert "Article One" in prompt
        assert "Article Two" in prompt
        assert c1["id"] in prompt
        assert c2["id"] in prompt
        assert "a.com" in prompt
        assert "b.com" in prompt

    def test_editorial_prompt_includes_scores(self):
        c1 = _scored_candidate(
            title="Scored Article",
            curation_score=0.8,
            quality_score=0.85,
        )
        prompt = CuratorAgent._build_editorial_prompt("AI news", [c1], 1)
        assert "0.800" in prompt  # composite score
        assert "0.850" in prompt  # quality score
        assert "Scored Article" in prompt



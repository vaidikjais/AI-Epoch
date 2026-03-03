"""Tests for ScoutAgent - LLM-powered source evaluation and candidate assessment."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.scout_agent import ScoutAgent


def _source(url="https://example.com/feed", source_type="rss"):
    return {"source_url": url, "source_type": source_type}


def _candidate(url="https://example.com/article", title="AI breakthrough",
               snippet="New model released today", domain="example.com"):
    return {"url": url, "title": title, "snippet": snippet, "domain": domain}


class TestEvaluateSources:

    @pytest.mark.asyncio
    async def test_successful_evaluation(self):
        s1 = _source("https://openai.com/blog/rss", "rss")
        s2 = _source("https://bbc.com/news/tech", "html")
        sources = [s1, s2]

        mock_response = json.dumps([
            {"source_url": s1["source_url"], "priority_score": 0.95,
             "reasoning": "Primary AI lab blog"},
            {"source_url": s2["source_url"], "priority_score": 0.6,
             "reasoning": "General tech news"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.evaluate_sources("AI news", sources)

        assert len(results) == 2
        # Results sorted by priority_score descending
        assert results[0]["source_url"] == s1["source_url"]
        assert results[0]["priority_score"] == 0.95
        assert results[1]["priority_score"] == 0.6

    @pytest.mark.asyncio
    async def test_missing_source_gets_fallback(self):
        """If LLM omits a source, it gets a 0.5 fallback."""
        s1 = _source("https://openai.com/blog/rss")
        s2 = _source("https://bbc.com/news/tech")

        mock_response = json.dumps([
            {"source_url": s1["source_url"], "priority_score": 0.9,
             "reasoning": "AI lab blog"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.evaluate_sources("AI news", [s1, s2])

        assert len(results) == 2
        # s2 should have fallback score
        s2_result = next(r for r in results if r["source_url"] == s2["source_url"])
        assert s2_result["priority_score"] == 0.5

    @pytest.mark.asyncio
    async def test_score_clamped(self):
        s1 = _source("https://example.com")
        mock_response = json.dumps([
            {"source_url": s1["source_url"], "priority_score": 1.5,
             "reasoning": "Over-scored"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.evaluate_sources("AI news", [s1])

        assert results[0]["priority_score"] == 1.0

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        s1 = _source("https://a.com")
        s2 = _source("https://b.com")

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.evaluate_sources("AI news", [s1, s2])

    @pytest.mark.asyncio
    async def test_empty_sources_returns_empty(self):
        agent = ScoutAgent()
        results = await agent.evaluate_sources("AI news", [])
        assert results == []


class TestAssessCandidates:

    @pytest.mark.asyncio
    async def test_successful_assessment(self):
        c1 = _candidate("https://openai.com/gpt5", "GPT-5 released", "Major launch", "openai.com")
        c2 = _candidate("https://example.com/gadgets", "Top 10 gadgets", "Listicle", "example.com")
        candidates = [c1, c2]

        mock_response = json.dumps([
            {"url": c1["url"], "relevance_score": 0.95, "keep": True,
             "reasoning": "Direct AI model release"},
            {"url": c2["url"], "relevance_score": 0.1, "keep": False,
             "reasoning": "Generic gadget listicle"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.assess_candidates("AI news", candidates)

        assert len(results) == 2
        assert results[0]["url"] == c1["url"]
        assert results[0]["keep"] is True
        assert results[0]["relevance_score"] == 0.95
        assert results[1]["keep"] is False

    @pytest.mark.asyncio
    async def test_missing_candidate_gets_keep_true_fallback(self):
        """If LLM omits a candidate, it defaults to keep=True, score=0.5."""
        c1 = _candidate("https://a.com/art1", "Article 1")
        c2 = _candidate("https://b.com/art2", "Article 2")

        mock_response = json.dumps([
            {"url": c1["url"], "relevance_score": 0.9, "keep": True,
             "reasoning": "Great article"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.assess_candidates("AI news", [c1, c2])

        assert len(results) == 2
        assert results[0]["relevance_score"] == 0.9
        assert results[1]["relevance_score"] == 0.5
        assert results[1]["keep"] is True

    @pytest.mark.asyncio
    async def test_score_clamped(self):
        c1 = _candidate("https://a.com/art")
        mock_response = json.dumps([
            {"url": c1["url"], "relevance_score": -0.5, "keep": False,
             "reasoning": "Negative score"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.assess_candidates("AI news", [c1])

        assert results[0]["relevance_score"] == 0.0

    @pytest.mark.asyncio
    async def test_keep_derived_from_score_when_not_bool(self):
        """If LLM returns non-boolean keep, derive from score >= 0.3."""
        c1 = _candidate("https://a.com/art")
        mock_response = json.dumps([
            {"url": c1["url"], "relevance_score": 0.5, "keep": "yes",
             "reasoning": "String keep value"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          return_value=mock_response):
            results = await agent.assess_candidates("AI news", [c1])

        assert results[0]["keep"] is True  # score 0.5 >= 0.3

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """If LLM raises, the error propagates."""
        c1 = _candidate("https://a.com/art1")
        c2 = _candidate("https://b.com/art2")

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=Exception("LLM down")):
            with pytest.raises(Exception, match="LLM down"):
                await agent.assess_candidates("AI news", [c1, c2])

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self):
        agent = ScoutAgent()
        results = await agent.assess_candidates("AI news", [])
        assert results == []

    @pytest.mark.asyncio
    async def test_malformed_json_triggers_retry(self):
        c1 = _candidate("https://a.com/art")
        good_response = json.dumps([
            {"url": c1["url"], "relevance_score": 0.8, "keep": True,
             "reasoning": "Good"},
        ])

        agent = ScoutAgent()
        with patch.object(agent, "_invoke", new_callable=AsyncMock,
                          side_effect=["not valid json", good_response]):
            results = await agent.assess_candidates("AI news", [c1])

        assert len(results) == 1
        assert results[0]["relevance_score"] == 0.8


class TestScoutPromptBuilders:

    def test_source_eval_prompt_contains_all_sources(self):
        s1 = _source("https://openai.com/blog/rss", "rss")
        s2 = _source("https://bbc.com/news", "html")
        prompt = ScoutAgent._build_source_eval_prompt("AI news", [s1, s2])
        assert "AI news" in prompt
        assert "openai.com/blog/rss" in prompt
        assert "bbc.com/news" in prompt
        assert "rss" in prompt
        assert "html" in prompt

    def test_candidate_assess_prompt_contains_all_candidates(self):
        c1 = _candidate("https://a.com/art", "Article One", "Snippet one", "a.com")
        c2 = _candidate("https://b.com/art", "Article Two", "Snippet two", "b.com")
        prompt = ScoutAgent._build_candidate_assess_prompt("AI news", [c1, c2])
        assert "AI news" in prompt
        assert "Article One" in prompt
        assert "Article Two" in prompt
        assert "a.com" in prompt
        assert "b.com" in prompt



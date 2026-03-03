"""Unit tests for app.core.curator.filters."""
from datetime import datetime, timezone, timedelta
import pytest

from app.core.curator.filters import (
    should_filter_out,
    is_likely_article_url,
    CuratorConfig,
)


@pytest.mark.asyncio
async def test_should_filter_out_passes_good_article(make_candidate):
    candidate = make_candidate(
        title="OpenAI announces new GPT model",
        snippet="Machine learning and large language models",
        url="https://techcrunch.com/2024/01/15/openai-gpt",
        semantic_score=0.8
    )
    config = CuratorConfig()
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is False
    assert reason == ""


@pytest.mark.asyncio
async def test_should_filter_out_filters_old_article(make_candidate):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old_date = now - timedelta(days=20)
    candidate = make_candidate(
        title="OpenAI releases new GPT model",
        snippet="Machine learning advances",
        pub_date_if_available=old_date,
        semantic_score=0.8
    )
    config = CuratorConfig(max_age_days=14)
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert "old" in reason.lower()


@pytest.mark.asyncio
async def test_should_filter_out_filters_paywalled_domain(make_candidate):
    candidate = make_candidate(
        title="OpenAI releases new GPT model",
        snippet="Machine learning breakthrough",
        normalized_domain="wsj.com",
        semantic_score=0.9
    )
    config = CuratorConfig(skip_paywalled=True)
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert "paywall" in reason.lower()


@pytest.mark.asyncio
async def test_should_filter_out_filters_denylisted_domain(make_candidate):
    candidate = make_candidate(
        title="OpenAI releases new GPT model",
        snippet="Machine learning advances",
        normalized_domain="spam-site.com",
        semantic_score=0.8
    )
    config = CuratorConfig(domain_denylist=["spam-site.com"])
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert "denylist" in reason.lower()


@pytest.mark.asyncio
async def test_should_filter_out_filters_missing_title(make_candidate):
    candidate = make_candidate(title=None, snippet="Machine learning content")
    config = CuratorConfig()
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert "title" in reason.lower()


@pytest.mark.asyncio
async def test_should_filter_out_filters_suspicious_file_extensions(make_candidate):
    candidate = make_candidate(
        title="OpenAI releases new GPT model",
        snippet="Machine learning research",
        url="https://example.com/paper.pdf",
        semantic_score=0.8
    )
    config = CuratorConfig()
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert ".pdf" in reason or "extension" in reason.lower()


@pytest.mark.asyncio
async def test_should_filter_out_filters_low_quality_score(make_candidate):
    candidate = make_candidate(
        title="OpenAI releases new GPT model",
        snippet="Machine learning advances",
        semantic_score=0.2
    )
    config = CuratorConfig(min_quality_threshold=0.3)
    should_filter, reason = await should_filter_out(candidate, config)
    assert should_filter is True
    assert "quality" in reason.lower()


def test_is_likely_article_url_youtube_returns_false():
    assert is_likely_article_url("https://www.youtube.com/watch?v=abc123") is False
    assert is_likely_article_url("https://youtu.be/abc123") is False


def test_is_likely_article_url_blog_returns_true():
    assert is_likely_article_url("https://example.com/blog/my-article") is True


def test_is_likely_article_url_date_pattern_returns_true():
    assert is_likely_article_url("https://example.com/2024/01/my-article") is True


def test_is_likely_article_url_category_tag_returns_false():
    assert is_likely_article_url("https://example.com/category/tech") is False
    assert is_likely_article_url("https://example.com/tag/ai") is False


def test_curator_config_defaults_are_sensible():
    config = CuratorConfig()
    assert config.skip_paywalled is True
    assert config.min_quality_threshold == 0.3
    assert config.min_title_length == 15
    assert config.min_snippet_length == 20
    assert config.domain_denylist == []
    assert config.max_age_days == 14

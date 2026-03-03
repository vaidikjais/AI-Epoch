"""Shared fixtures for curator and related tests."""
import os

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from sqlmodel import SQLModel, create_engine, Session

from app.models.candidate_model import ArticleCandidate
from app.models.article_model import Article


@pytest.fixture
def test_session():
    test_db_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/newsletter_test"
    )
    engine = create_engine(test_db_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_article_data():
    return {
        "url": "https://example.com/test-article",
        "title": "Test Article",
        "content": "This is test content for the article.",
        "source_name": "example.com",
        "status": "ingested"
    }


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.fixture
def make_candidate():
    """Factory fixture that creates ArticleCandidate objects with sensible defaults."""

    def _make(
        *,
        topic_id: str = "topic-1",
        topic_query: str = "AI and machine learning",
        url: str = "https://example.com/article-ai",
        title: str = "OpenAI releases new GPT model",
        snippet: str = "Machine learning breakthrough in natural language processing",
        source_provider: str = "tavily",
        provider_rank: int | None = 1,
        canonical_url: str | None = None,
        normalized_domain: str = "example.com",
        discovered_at: datetime | None = None,
        pub_date_if_available: datetime | None = None,
        is_seed_source: bool = False,
        semantic_score: float | None = 0.9,
        curation_score: float | None = 0.85,
        **kwargs
    ) -> ArticleCandidate:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return ArticleCandidate(
            topic_id=topic_id,
            topic_query=topic_query,
            url=url,
            title=title,
            snippet=snippet,
            source_provider=source_provider,
            provider_rank=provider_rank,
            canonical_url=canonical_url or url,
            normalized_domain=normalized_domain,
            discovered_at=discovered_at or now,
            pub_date_if_available=pub_date_if_available,
            is_seed_source=is_seed_source,
            semantic_score=semantic_score,
            curation_score=curation_score,
            **kwargs
        )

    return _make


@pytest.fixture
def make_article():
    """Factory fixture that creates Article objects with sensible defaults."""

    def _make(
        *,
        url: str = "https://example.com/article",
        title: str = "Test Article",
        source: str | None = "example.com",
        status: str = "ingested",
        **kwargs
    ) -> Article:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return Article(
            url=url,
            title=title,
            source=source,
            status=status,
            ingested_at=now,
            **kwargs
        )

    return _make

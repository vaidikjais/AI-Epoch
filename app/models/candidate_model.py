"""ArticleCandidate database model for tracking discovered article candidates."""
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class ArticleCandidate(SQLModel, table=True):
    __tablename__ = "article_candidates"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True, index=True)

    topic_id: str = Field(index=True, description="Topic identifier for grouping candidates")
    topic_query: str = Field(description="Search query used to discover this candidate")

    url: str = Field(index=True, description="Original article URL")
    title: Optional[str] = Field(default=None, description="Article title if available")
    snippet: Optional[str] = Field(default=None, description="Article snippet or summary")

    source_provider: str = Field(description="Provider that discovered this candidate (seed, tavily, etc.)")
    provider_rank: Optional[int] = Field(default=None, description="Rank from provider if available")

    canonical_url: str = Field(index=True, description="Canonical/normalized URL")
    normalized_domain: str = Field(index=True, description="Normalized domain name")

    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        description="When this candidate was discovered"
    )
    pub_date_if_available: Optional[datetime] = Field(
        default=None,
        description="Publication date if available from source"
    )

    is_seed_source: bool = Field(default=False, description="Whether this came from seed sources")

    curated_rank: Optional[int] = Field(default=None, description="Final rank after curation")
    curation_score: Optional[float] = Field(default=None, description="Final curation score (weighted composite)")

    freshness_score: Optional[float] = Field(default=None, description="Freshness/recency score (0-1)")
    semantic_score: Optional[float] = Field(default=None, description="LLM quality/relevance score (0-1)")
    provider_score: Optional[float] = Field(default=None, description="Provider rank score (0-1)")

    reason_notes: Optional[str] = Field(default=None, description="Notes about curation decision")
    curated_at: Optional[datetime] = Field(default=None, description="When curation was performed")
    curator_version: Optional[str] = Field(default=None, description="Curator algorithm version")

    pass_to_extractor: bool = Field(default=False, description="Whether to pass to extractor for processing")

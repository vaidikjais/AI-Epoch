"""Pydantic schemas for article candidate management."""
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime


class CandidateDiscoveryIn(BaseModel):
    topic_id: str = Field(description="Topic identifier")
    topic_query: str = Field(description="Search query for discovery")


class CandidateCurationIn(BaseModel):
    topic_id: str = Field(description="Topic identifier")
    max_candidates_per_section: Optional[Dict[str, int]] = Field(
        default=None,
        description="Max candidates per section"
    )


class ArticleCandidateCreate(BaseModel):
    topic_id: str
    topic_query: str
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    source_provider: str
    provider_rank: Optional[int] = None
    canonical_url: str
    normalized_domain: str
    pub_date_if_available: Optional[datetime] = None
    is_seed_source: bool = False
    pass_to_extractor: bool = False


class ArticleCandidateUpdate(BaseModel):
    title: Optional[str] = None
    snippet: Optional[str] = None
    curated_rank: Optional[int] = None
    curation_score: Optional[float] = None
    freshness_score: Optional[float] = None
    semantic_score: Optional[float] = None
    provider_score: Optional[float] = None
    reason_notes: Optional[str] = None
    curated_at: Optional[datetime] = None
    curator_version: Optional[str] = None
    pass_to_extractor: Optional[bool] = None


class CandidateSelectionUpdate(BaseModel):
    candidate_ids: List[UUID] = Field(description="List of candidate IDs to update")
    pass_to_extractor: bool = Field(description="Whether to pass to extractor")


class ArticleCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_id: str
    topic_query: str
    url: str
    title: Optional[str]
    snippet: Optional[str]
    source_provider: str
    provider_rank: Optional[int]
    canonical_url: str
    normalized_domain: str
    discovered_at: datetime
    pub_date_if_available: Optional[datetime]
    is_seed_source: bool
    curated_rank: Optional[int]
    curation_score: Optional[float]
    reason_notes: Optional[str]
    curated_at: Optional[datetime]
    pass_to_extractor: bool


class CandidateDiscoveryResult(BaseModel):
    topic_id: str
    topic_query: str
    total_discovered: int
    from_seed_sources: int
    from_external_sources: int
    candidates: List[ArticleCandidateOut]


class CandidateCurationResult(BaseModel):
    topic_id: str
    total_candidates: int
    selected_for_extraction: int
    section_breakdown: Dict[str, int]
    curation_summary: str


class ScoutExtractResult(BaseModel):
    topic_id: str
    topic_query: str
    candidates_discovered: int
    candidates_selected: int
    articles_extracted: int
    extraction_success_rate: float
    processing_time_seconds: float


class CandidateBatchCreate(BaseModel):
    candidates: List[ArticleCandidateCreate]


class CandidateBatchUpdate(BaseModel):
    updates: List[Dict[str, Any]] = Field(description="List of updates with candidate_id and fields to update")

"""Pydantic schemas for article discovery."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class DiscoverRequest(BaseModel):
    topic_id: str = Field(..., description="Unique topic identifier")
    topic_query: str = Field(..., description="Search query for discovery")
    max_results: int = Field(default=50, ge=1, le=100, description="Maximum candidates to discover")
    enable_tavily: bool = Field(default=True, description="Use Tavily API for external search")
    seed_sources_only: bool = Field(default=False, description="Skip external providers")


class CandidateOut(BaseModel):
    id: UUID
    url: str
    canonical_url: str
    normalized_domain: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    source_provider: str = Field(..., description="tavily or seed")
    provider_rank: Optional[int] = None
    is_seed_source: bool
    discovered_at: datetime
    pub_date_if_available: Optional[datetime] = None


class DiscoverResponse(BaseModel):
    topic_id: str
    topic_query: str
    total_discovered: int
    from_seed_sources: int
    from_external_sources: int
    discovery_time_seconds: float
    candidates: List[CandidateOut]
    stats: Dict[str, Any] = Field(default_factory=dict)


class CandidateListResponse(BaseModel):
    topic_id: str
    total: int
    limit: int
    offset: int
    items: List[CandidateOut]

"""Pydantic schemas for article curation."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


class ScoringWeights(BaseModel):
    quality: float = Field(default=0.60, ge=0, le=1, description="LLM quality score weight")
    freshness: float = Field(default=0.25, ge=0, le=1, description="Freshness/recency weight")
    provider: float = Field(default=0.15, ge=0, le=1, description="Provider rank weight")


class CuratorFilters(BaseModel):
    skip_paywalled: bool = Field(default=True, description="Skip paywalled content")
    min_quality_threshold: float = Field(default=0.3, ge=0, le=1, description="Minimum LLM quality score")
    domain_denylist: List[str] = Field(default=[], description="Domains to exclude")


class CurateRequest(BaseModel):
    topic_id: str = Field(..., description="Topic identifier")
    max_candidates: int = Field(default=8, ge=1, le=20, description="Max candidates to select")
    weights: Optional[ScoringWeights] = Field(default=None)
    filters: Optional[CuratorFilters] = Field(default=None)


class CuratedCandidateOut(BaseModel):
    id: UUID
    url: str
    title: Optional[str]
    curation_score: float = Field(..., description="Weighted composite score")
    quality_score: float = Field(description="LLM-judged holistic quality score")
    freshness_score: float
    provider_score: float
    curated_rank: int = Field(..., description="Rank 1 is best")
    reason_notes: Optional[str] = None
    pass_to_extractor: bool


class CurateResponse(BaseModel):
    topic_id: str
    candidates_scored: int
    candidates_filtered: int
    candidates_selected: int
    processing_time_seconds: float
    selected_candidates: List[CuratedCandidateOut]
    curation_stats: Dict[str, Any] = Field(default_factory=dict)

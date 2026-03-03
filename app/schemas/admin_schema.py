"""Pydantic schemas for system administration."""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ComponentHealth(BaseModel):
    status: str = Field(..., description="connected|disconnected|degraded")
    response_time_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str = Field(..., description="healthy|degraded|unhealthy")
    timestamp: datetime
    version: str
    components: Dict[str, ComponentHealth] = Field(default_factory=dict)


class ArticleMetrics(BaseModel):
    total: int
    ingested_today: int
    by_status: Dict[str, int] = Field(default_factory=dict)


class CandidateMetrics(BaseModel):
    total: int
    by_topic: Dict[str, int] = Field(default_factory=dict)


class PipelineMetrics(BaseModel):
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    avg_duration_seconds: float


class MetricsResponse(BaseModel):
    timestamp: datetime
    articles: ArticleMetrics
    candidates: CandidateMetrics
    pipelines: PipelineMetrics
    additional_stats: Dict[str, Any] = Field(default_factory=dict)

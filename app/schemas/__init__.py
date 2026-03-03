"""Pydantic schemas for API input/output validation."""
from .article_schema import ArticleIn, ArticleOut, ArticleListResponse
from .pipeline_schema import PipelineRunRequest, PipelineRunResponse, PipelineResumeRequest, PipelineInterruptResponse
from .scout_schema import DiscoverRequest, DiscoverResponse, CandidateListResponse
from .curator_schema import CurateRequest, CurateResponse
from .extractor_schema import ExtractRequest, ExtractResponse, ExtractCandidatesRequest, ExtractCandidatesResponse
from .email_schema import SendEmailRequest, SendEmailResponse
from .admin_schema import HealthResponse, MetricsResponse

__all__ = [
    "ArticleIn", "ArticleOut", "ArticleListResponse",
    "PipelineRunRequest", "PipelineRunResponse", "PipelineResumeRequest", "PipelineInterruptResponse",
    "DiscoverRequest", "DiscoverResponse", "CandidateListResponse",
    "CurateRequest", "CurateResponse",
    "ExtractRequest", "ExtractResponse", "ExtractCandidatesRequest", "ExtractCandidatesResponse",
    "SendEmailRequest", "SendEmailResponse",
    "HealthResponse", "MetricsResponse",
]

"""Pydantic schemas for pipeline orchestration."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class NewsletterConfig(BaseModel):
    title: Optional[str] = Field(default="AI Newsletter", description="Newsletter title")
    issue_number: Optional[int] = Field(default=None, description="Issue number")
    format: str = Field(default="structured", description="Format: structured or basic")
    estimated_read_time: str = Field(default="5 minutes", description="Estimated read time")


class DeliveryConfig(BaseModel):
    send_email: bool = Field(default=False, description="Whether to send email")
    recipients: List[str] = Field(default=[], description="Email recipients")
    from_name: Optional[str] = Field(default="AI Newsletter", description="Sender name")


class ScoringWeights(BaseModel):
    quality: float = Field(default=0.60, ge=0, le=1, description="LLM quality score weight")
    freshness: float = Field(default=0.25, ge=0, le=1, description="Freshness/recency weight")
    provider: float = Field(default=0.15, ge=0, le=1, description="Provider rank weight")


class PipelineRunRequest(BaseModel):
    topic_id: str = Field(..., description="Unique topic identifier")
    topic_query: str = Field(..., description="Search query for discovery")
    max_candidates: int = Field(default=8, ge=1, le=20, description="Max articles to include")
    newsletter_config: Optional[NewsletterConfig] = Field(default=None)
    delivery: Optional[DeliveryConfig] = Field(default=None)
    scoring_weights: Optional[ScoringWeights] = Field(default=None, description="Custom curator weights")


class StageResult(BaseModel):
    status: str = Field(..., description="Status: success|failed|skipped")
    time_seconds: float = Field(..., description="Stage execution time")
    message: Optional[str] = Field(default=None)


class ScoutStageResult(StageResult):
    candidates_discovered: int = Field(..., description="Number of candidates found")
    from_seed_sources: int = Field(default=0)
    from_external_sources: int = Field(default=0)


class CuratorStageResult(StageResult):
    candidates_scored: int = Field(..., description="Candidates scored")
    candidates_filtered: int = Field(..., description="Candidates filtered out")
    candidates_selected: int = Field(..., description="Candidates selected")


class ExtractorStageResult(StageResult):
    articles_extracted: int = Field(..., description="Articles successfully extracted")
    extraction_failures: int = Field(..., description="Failed extractions")


class WriterStageResult(StageResult):
    newsletter_generated: bool = Field(..., description="Whether newsletter was generated")
    format: Optional[str] = Field(default=None)
    total_articles: int = Field(default=0)


class QAStageResult(StageResult):
    overall_pass: bool = Field(default=False, description="Whether QA passed")


class EmailStageResult(StageResult):
    email_sent: bool = Field(..., description="Whether email was sent")
    recipients_count: int = Field(default=0)


class PipelineStages(BaseModel):
    scout: Optional[ScoutStageResult] = None
    curator: Optional[CuratorStageResult] = None
    extractor: Optional[ExtractorStageResult] = None
    writer: Optional[WriterStageResult] = None
    qa: Optional[QAStageResult] = None
    email: Optional[EmailStageResult] = None


class PipelineRunResponse(BaseModel):
    success: bool = Field(..., description="Overall success status")
    topic_id: str
    topic_query: str
    stages: PipelineStages
    total_time_seconds: float
    newsletter_json: Optional[Dict[str, Any]] = None
    newsletter_markdown: Optional[str] = None
    newsletter_html: Optional[str] = None
    qa_report: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineResumeRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID from the initial /run response")
    user_response: Any = Field(..., description="Approved article IDs (list) or 'approve'/'reject' (str)")


class CandidatePreview(BaseModel):
    id: str
    url: str
    title: str
    snippet: str
    score: float
    domain: str
    reasoning: str = ""
    discovered_at: str = ""


class PipelineInterruptResponse(BaseModel):
    status: str = Field(..., description="awaiting_article_review, awaiting_newsletter_review, or awaiting_qa_review")
    thread_id: str
    topic_id: str
    interrupt_type: str = Field(..., description="review_articles, review_newsletter, or review_qa")
    candidates: Optional[List[CandidatePreview]] = None
    newsletter_html: Optional[str] = None
    newsletter_json: Optional[Dict[str, Any]] = None
    qa_report: Optional[Dict[str, Any]] = None
    stages: Optional[PipelineStages] = None
    total_time_seconds: float = 0


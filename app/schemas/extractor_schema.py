"""Pydantic schemas for content extraction."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime


class ExtractRequest(BaseModel):
    url: HttpUrl = Field(..., description="URL to extract content from")
    force_playwright: bool = Field(default=False, description="Force Playwright extraction")
    min_words: int = Field(default=120, description="Minimum word count")
    timeout_seconds: int = Field(default=30, description="Extraction timeout")


class ExtractCandidatesRequest(BaseModel):
    topic_id: str = Field(..., description="Topic identifier")
    max_concurrent: int = Field(default=3, ge=1, le=10, description="Parallel extraction limit")
    skip_existing: bool = Field(default=True, description="Skip if article already exists")


class ExtractionMetadata(BaseModel):
    domain: str
    extraction_method: str = Field(..., description="trafilatura or playwright")
    extraction_time_seconds: float
    word_count: int
    published_date: Optional[datetime] = None
    author: Optional[str] = None


class ExtractResponse(BaseModel):
    success: bool
    url: str
    final_url: str = Field(..., description="URL after redirects")
    title: str
    content: str
    bucket_key: Optional[str] = Field(default=None, description="S3 storage key")
    metadata: ExtractionMetadata


class ExtractedArticle(BaseModel):
    article_id: str
    candidate_id: Optional[str] = None
    url: str
    title: str
    word_count: int
    bucket_key: Optional[str] = None


class FailedExtraction(BaseModel):
    candidate_id: Optional[str] = None
    url: str
    error: str


class ExtractCandidatesResponse(BaseModel):
    topic_id: str
    candidates_selected: int
    articles_extracted: int
    extraction_failures: int
    extraction_time_seconds: float
    extracted_articles: List[ExtractedArticle]
    failed_extractions: List[FailedExtraction]

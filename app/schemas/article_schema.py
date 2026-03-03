"""Pydantic schemas for article API input/output."""
from typing import List, Optional, Any
from pydantic import BaseModel, ConfigDict, HttpUrl
from uuid import UUID
from datetime import datetime


class ArticleIn(BaseModel):
    url: HttpUrl


class ArticleCreate(BaseModel):
    url: str
    title: Optional[str] = None
    source: Optional[str] = None
    bucket_key: Optional[str] = None
    status: str = "ingested"


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    draft_json: Optional[dict] = None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    title: Optional[str]
    source: Optional[str]
    bucket_key: Optional[str] = None
    status: str
    ingested_at: datetime
    draft_json: Optional[Any] = None


class ArticleListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ArticleOut]

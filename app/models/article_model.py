"""Article database model for article storage."""
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, JSON

class Article(SQLModel, table=True):
    __tablename__ = "articles"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True, index=True)
    url: str = Field(index=True, unique=True)
    title: Optional[str] = None
    source: Optional[str] = None
    bucket_key: Optional[str] = None
    draft_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="ingested")
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

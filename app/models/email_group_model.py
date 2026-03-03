"""Email group and membership models for managing newsletter recipients."""
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class EmailGroup(SQLModel, table=True):
    __tablename__ = "email_groups"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class EmailGroupMember(SQLModel, table=True):
    __tablename__ = "email_group_members"

    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True, index=True)
    group_id: UUID = Field(foreign_key="email_groups.id", index=True)
    email: str = Field(index=True)
    name: Optional[str] = Field(default=None)
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

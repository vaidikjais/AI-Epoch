"""Pydantic schemas for email delivery and group management."""
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime


class SendEmailRequest(BaseModel):
    html_content: str = Field(..., description="HTML email content")
    subject: str = Field(..., description="Email subject")
    recipients: List[EmailStr] = Field(default=[], description="Individual email recipients")
    group_ids: List[UUID] = Field(default=[], description="Email group IDs to resolve and send to")
    from_name: Optional[str] = Field(default="AI Newsletter", description="Sender name")
    from_email: Optional[EmailStr] = Field(default=None, description="Override from email")
    reply_to: Optional[EmailStr] = Field(default=None, description="Reply-to address")


class SendEmailResponse(BaseModel):
    sent: bool = Field(..., description="Whether email was sent successfully")
    recipients_count: int
    message_id: Optional[str] = Field(default=None, description="SMTP message ID")
    sent_at: Optional[datetime] = None
    provider: str = Field(..., description="smtp or mock")
    delivery_time_seconds: float
    error: Optional[str] = Field(default=None, description="Error message if failed")


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Group name")
    description: Optional[str] = Field(default=None, max_length=500)


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class MemberResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    added_at: Optional[str] = None


class GroupResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    member_count: int = 0
    created_at: Optional[str] = None


class GroupDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    members: List[MemberResponse] = []


class AddMembersRequest(BaseModel):
    emails: List[EmailStr] = Field(..., min_length=1, description="Emails to add to the group")

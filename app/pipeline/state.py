"""Typed state definition for the LangGraph newsletter pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class PipelineState(TypedDict, total=False):
    topic_id: str
    topic_query: str
    max_candidates: int
    recipient_email: Optional[str]
    newsletter_title: Optional[str]
    issue_number: Optional[int]
    scoring_weights: Dict[str, float]

    candidates: List[Any]
    curated: List[Any]
    extracted_articles: List[Dict[str, Any]]
    editor_plan: Optional[Dict[str, Any]]
    newsletter_json: Optional[Dict[str, Any]]
    newsletter_markdown: Optional[str]
    newsletter_html: Optional[str]
    qa_report: Optional[Dict[str, Any]]

    user_feedback: Optional[str]
    curator_feedback: Optional[str]
    qa_revision_feedback: Optional[str]
    qa_revision_count: int

    stages: Dict[str, Any]
    error: Optional[str]
    success: bool

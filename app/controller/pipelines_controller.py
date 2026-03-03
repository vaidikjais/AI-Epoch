"""Pipelines controller — complete newsletter pipeline orchestration with HITL."""

import json
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.pipeline.graph import build_pipeline
from app.pipeline.progress import create_tracker, get_tracker, remove_tracker
from app.pipeline.state import PipelineState
from app.schemas.pipeline_schema import (
    CandidatePreview,
    CuratorStageResult,
    EmailStageResult,
    ExtractorStageResult,
    PipelineInterruptResponse,
    PipelineResumeRequest,
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineStages,
    QAStageResult,
    ScoutStageResult,
    WriterStageResult,
)
from app.utils.logger import get_logger

logger = get_logger("pipelines_controller")

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])

# In-memory store for active pipeline instances keyed by thread_id.
# Each entry holds the compiled graph and metadata needed for resume calls.
_active_pipelines: Dict[str, Dict[str, Any]] = {}


def _build_stages(stages_dict: dict) -> PipelineStages:
    """Convert raw stages dict from pipeline state into PipelineStages schema."""
    scout_stage = None
    if "scout" in stages_dict:
        s = stages_dict["scout"]
        scout_stage = ScoutStageResult(
            status=s.get("status", "success"),
            time_seconds=s.get("time_seconds", 0),
            candidates_discovered=s.get("candidates_discovered", 0),
            from_seed_sources=0,
            from_external_sources=0,
        )

    curator_stage = None
    if "curator" in stages_dict:
        c = stages_dict["curator"]
        curator_stage = CuratorStageResult(
            status=c.get("status", "success"),
            time_seconds=c.get("time_seconds", 0),
            candidates_scored=c.get("candidates_curated", 0),
            candidates_filtered=0,
            candidates_selected=c.get("candidates_curated", 0),
        )

    extractor_stage = None
    if "extractor" in stages_dict:
        e = stages_dict["extractor"]
        extractor_stage = ExtractorStageResult(
            status=e.get("status", "success"),
            time_seconds=e.get("time_seconds", 0),
            articles_extracted=e.get("articles_extracted", 0),
            extraction_failures=e.get("extraction_failures", 0),
        )

    writer_stage = None
    if "writer" in stages_dict:
        w = stages_dict["writer"]
        writer_stage = WriterStageResult(
            status=w.get("status", "success"),
            time_seconds=w.get("time_seconds", 0),
            newsletter_generated=w.get("newsletter_generated", False),
            format=w.get("format", "structured"),
            total_articles=w.get("total_articles", 0),
        )

    qa_stage = None
    if "qa" in stages_dict:
        q = stages_dict["qa"]
        qa_stage = QAStageResult(
            status=q.get("status", "success"),
            time_seconds=q.get("time_seconds", 0),
            overall_pass=q.get("overall_pass", False),
        )

    email_stage = None
    if "email" in stages_dict:
        em = stages_dict["email"]
        email_stage = EmailStageResult(
            status=em.get("status", "skipped"),
            time_seconds=em.get("time_seconds", 0),
            email_sent=em.get("email_sent", False),
            recipients_count=1 if em.get("email_sent") else 0,
        )

    return PipelineStages(
        scout=scout_stage,
        curator=curator_stage,
        extractor=extractor_stage,
        writer=writer_stage,
        qa=qa_stage,
        email=email_stage,
    )


def _check_interrupt(pipeline, config: dict) -> dict | None:
    """Check if the pipeline is interrupted and return the interrupt payload if so."""
    state_snapshot = pipeline.get_state(config)
    tasks = state_snapshot.tasks if hasattr(state_snapshot, "tasks") else ()
    for task in tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            return task.interrupts[0].value
    return None


def _build_completed_response(result: dict, topic_id: str, topic_query: str, total_time: float) -> PipelineRunResponse:
    """Build the final PipelineRunResponse from completed pipeline state."""
    stages_dict = result.get("stages", {})
    return PipelineRunResponse(
        success=result.get("newsletter_json") is not None,
        topic_id=topic_id,
        topic_query=topic_query,
        stages=_build_stages(stages_dict),
        total_time_seconds=total_time,
        newsletter_json=result.get("newsletter_json"),
        newsletter_markdown=result.get("newsletter_markdown"),
        newsletter_html=result.get("newsletter_html"),
        qa_report=result.get("qa_report"),
        error=result.get("error"),
    )


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_pipeline(
    request: PipelineRunRequest,
    db: AsyncSession = Depends(get_session),
):
    """Start the newsletter pipeline. Returns interrupt response or final result."""
    try:
        pipeline_start = time.time()
        thread_id = str(uuid.uuid4())

        newsletter_config = request.newsletter_config
        newsletter_title = (
            newsletter_config.title
            if newsletter_config and hasattr(newsletter_config, "title")
            else "AI Newsletter"
        )
        issue_number = (
            newsletter_config.issue_number
            if newsletter_config and hasattr(newsletter_config, "issue_number")
            else None
        )

        delivery = request.delivery
        recipient_email = None
        if (
            delivery
            and hasattr(delivery, "send_email")
            and delivery.send_email
            and hasattr(delivery, "recipients")
            and delivery.recipients
        ):
            recipient_email = delivery.recipients[0]

        weights = request.scoring_weights
        scoring_weights = {}
        if weights:
            scoring_weights = {
                "quality": weights.quality if hasattr(weights, "quality") else 0.60,
                "freshness": weights.freshness if hasattr(weights, "freshness") else 0.25,
                "provider": weights.provider if hasattr(weights, "provider") else 0.15,
            }

        initial_state: PipelineState = {
            "topic_id": request.topic_id,
            "topic_query": request.topic_query,
            "max_candidates": request.max_candidates,
            "recipient_email": recipient_email,
            "newsletter_title": newsletter_title,
            "issue_number": issue_number,
            "scoring_weights": scoring_weights,
            "candidates": [],
            "curated": [],
            "extracted_articles": [],
            "newsletter_json": None,
            "newsletter_markdown": None,
            "newsletter_html": None,
            "stages": {},
            "error": None,
            "success": False,
        }

        tracker = create_tracker(request.topic_id)
        pipeline = build_pipeline(db, progress=tracker)
        config = {"configurable": {"thread_id": thread_id}}

        # Store pipeline instance for resume calls
        _active_pipelines[thread_id] = {
            "pipeline": pipeline,
            "config": config,
            "topic_id": request.topic_id,
            "topic_query": request.topic_query,
            "tracker": tracker,
            "start_time": pipeline_start,
        }

        result = await pipeline.ainvoke(initial_state, config)

        # Check if we hit an interrupt
        interrupt_payload = _check_interrupt(pipeline, config)
        if interrupt_payload and isinstance(interrupt_payload, dict):
            elapsed = time.time() - pipeline_start
            interrupt_type = interrupt_payload.get("type", "unknown")

            if interrupt_type == "review_articles":
                candidates = [
                    CandidatePreview(**c) for c in interrupt_payload.get("candidates", [])
                ]
                return PipelineInterruptResponse(
                    status="awaiting_article_review",
                    thread_id=thread_id,
                    topic_id=request.topic_id,
                    interrupt_type=interrupt_type,
                    candidates=candidates,
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )
            elif interrupt_type == "review_newsletter":
                return PipelineInterruptResponse(
                    status="awaiting_newsletter_review",
                    thread_id=thread_id,
                    topic_id=request.topic_id,
                    interrupt_type=interrupt_type,
                    newsletter_html=interrupt_payload.get("newsletter_html"),
                    newsletter_json=interrupt_payload.get("newsletter_json"),
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )
            elif interrupt_type == "review_qa":
                return PipelineInterruptResponse(
                    status="awaiting_qa_review",
                    thread_id=thread_id,
                    topic_id=request.topic_id,
                    interrupt_type=interrupt_type,
                    qa_report=interrupt_payload.get("qa_report"),
                    newsletter_html=interrupt_payload.get("newsletter_html"),
                    newsletter_json=interrupt_payload.get("newsletter_json"),
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )

        # Pipeline completed without interrupt (or no candidates found)
        total_time = time.time() - pipeline_start
        tracker.finish()
        remove_tracker(request.topic_id)
        _active_pipelines.pop(thread_id, None)

        return _build_completed_response(result, request.topic_id, request.topic_query, total_time)

    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {str(e)}",
        )


@router.post("/resume", status_code=status.HTTP_200_OK)
async def resume_pipeline(request: PipelineResumeRequest):
    """Resume pipeline after a HITL interrupt with the user's response."""
    thread_id = request.thread_id

    if thread_id not in _active_pipelines:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active pipeline found for thread_id: {thread_id}. It may have expired or completed.",
        )

    try:
        entry = _active_pipelines[thread_id]
        pipeline = entry["pipeline"]
        config = entry["config"]
        topic_id = entry["topic_id"]
        topic_query = entry["topic_query"]
        tracker = entry["tracker"]
        pipeline_start = entry["start_time"]

        result = await pipeline.ainvoke(
            Command(resume=request.user_response),
            config,
        )

        # Check if we hit another interrupt
        interrupt_payload = _check_interrupt(pipeline, config)
        if interrupt_payload and isinstance(interrupt_payload, dict):
            elapsed = time.time() - pipeline_start
            interrupt_type = interrupt_payload.get("type", "unknown")

            if interrupt_type == "review_articles":
                candidates = [
                    CandidatePreview(**c) for c in interrupt_payload.get("candidates", [])
                ]
                return PipelineInterruptResponse(
                    status="awaiting_article_review",
                    thread_id=thread_id,
                    topic_id=topic_id,
                    interrupt_type=interrupt_type,
                    candidates=candidates,
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )

            if interrupt_type == "review_newsletter":
                return PipelineInterruptResponse(
                    status="awaiting_newsletter_review",
                    thread_id=thread_id,
                    topic_id=topic_id,
                    interrupt_type=interrupt_type,
                    newsletter_html=interrupt_payload.get("newsletter_html"),
                    newsletter_json=interrupt_payload.get("newsletter_json"),
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )

            if interrupt_type == "review_qa":
                return PipelineInterruptResponse(
                    status="awaiting_qa_review",
                    thread_id=thread_id,
                    topic_id=topic_id,
                    interrupt_type=interrupt_type,
                    qa_report=interrupt_payload.get("qa_report"),
                    newsletter_html=interrupt_payload.get("newsletter_html"),
                    newsletter_json=interrupt_payload.get("newsletter_json"),
                    stages=_build_stages(result.get("stages", {})),
                    total_time_seconds=elapsed,
                )

        # Pipeline completed
        total_time = time.time() - pipeline_start
        tracker.finish()
        remove_tracker(topic_id)
        _active_pipelines.pop(thread_id, None)

        return _build_completed_response(result, topic_id, topic_query, total_time)

    except Exception as e:
        logger.error(f"Pipeline resume failed: {e}")
        _active_pipelines.pop(thread_id, None)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline resume failed: {str(e)}",
        )


@router.get("/progress/{topic_id}")
async def stream_progress(topic_id: str, request: Request):
    """SSE endpoint for real-time pipeline progress updates."""

    async def event_generator():
        tracker = get_tracker(topic_id)
        if not tracker:
            yield f"data: {json.dumps({'stage': '__done__', 'status': 'not_found'})}\n\n"
            return

        async for event in tracker.listen():
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

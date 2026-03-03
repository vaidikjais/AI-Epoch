"""
Pipeline Package - LangGraph-based Newsletter Generation Pipeline

Provides a state-graph pipeline that orchestrates the newsletter generation
workflow: Scout -> Curator -> Extractor -> SourceResolver -> Writer -> Email.

Each stage is an isolated graph node. Conditional edges control flow
(e.g. skip email when no recipient is provided, stop early when a stage
produces no output).

Usage:
    from app.pipeline.graph import build_pipeline

    pipeline = build_pipeline(db_session)
    result = await pipeline.ainvoke(initial_state)
"""

from app.pipeline.state import PipelineState
from app.pipeline.graph import build_pipeline

__all__ = ["PipelineState", "build_pipeline"]

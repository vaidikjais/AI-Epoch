"""LangGraph StateGraph definition and builder for the newsletter pipeline."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.nodes import create_nodes
from app.pipeline.state import PipelineState
from app.utils.logger import get_logger

logger = get_logger("pipeline.graph")


def _after_scout(state: PipelineState) -> str:
    if state.get("candidates"):
        return "curator"
    logger.info("Graph: No candidates discovered -- stopping pipeline")
    return END


def _after_curator(state: PipelineState) -> str:
    if state.get("curated"):
        return "review_articles"
    logger.info("Graph: No candidates passed curation -- stopping pipeline")
    return END


def _after_review_articles(state: PipelineState) -> str:
    if state.get("error"):
        logger.info("Graph: Articles rejected by user -- stopping pipeline")
        return END
    if state.get("curator_feedback"):
        logger.info("Graph: User requested re-curation -- looping back to curator")
        return "curator"
    if state.get("curated"):
        return "extractor"
    logger.info("Graph: No articles approved by user -- stopping pipeline")
    return END


def _after_extractor(state: PipelineState) -> str:
    if state.get("extracted_articles"):
        return "source_resolver"
    logger.info("Graph: No articles extracted -- stopping pipeline")
    return END


def _after_writer(state: PipelineState) -> str:
    if not state.get("newsletter_json"):
        logger.info("Graph: No newsletter generated -- stopping pipeline")
        return END
    if state.get("qa_revision_feedback"):
        logger.info("Graph: QA revision — skipping newsletter review, going straight to QA")
        return "qa"
    return "review_newsletter"


def _after_review_newsletter(state: PipelineState) -> str:
    if state.get("error"):
        logger.info("Graph: Newsletter rejected by user -- stopping pipeline")
        return END
    if state.get("user_feedback"):
        logger.info("Graph: User requested revision -- looping back to writer")
        return "writer"
    if state.get("newsletter_json"):
        return "qa"
    return END


def _after_qa(state: PipelineState) -> str:
    return "review_qa"


MAX_QA_REVISIONS = 3


def _after_review_qa(state: PipelineState) -> str:
    if state.get("error"):
        logger.info("Graph: Newsletter rejected after QA -- stopping pipeline")
        return END
    if state.get("qa_revision_feedback"):
        count = state.get("qa_revision_count", 0)
        if count >= MAX_QA_REVISIONS:
            logger.warning(f"Graph: QA revision cap reached ({count}/{MAX_QA_REVISIONS}) — proceeding without further revision")
        else:
            logger.info(f"Graph: QA revision requested ({count}/{MAX_QA_REVISIONS}) -- looping back to writer")
            return "writer"
    if state.get("recipient_email") and state.get("newsletter_html"):
        return "email"
    logger.info("Graph: Skipping email (no recipient or no HTML)")
    return END


def build_pipeline(db: AsyncSession, progress=None, checkpointer=None):
    """Construct and compile the newsletter-generation state graph.

    Args:
        db: Async database session for node closures.
        progress: Optional PipelineProgress tracker for SSE events.
        checkpointer: Optional LangGraph checkpointer for HITL interrupts.
                      If None, a new MemorySaver is created.
    Returns:
        Compiled StateGraph with checkpointer attached.
    """
    nodes = create_nodes(db, progress=progress)

    graph = StateGraph(PipelineState)

    graph.add_node("scout", nodes["scout"])
    graph.add_node("curator", nodes["curator"])
    graph.add_node("review_articles", nodes["review_articles"])
    graph.add_node("extractor", nodes["extractor"])
    graph.add_node("source_resolver", nodes["source_resolver"])
    graph.add_node("editor", nodes["editor"])
    graph.add_node("writer", nodes["writer"])
    graph.add_node("review_newsletter", nodes["review_newsletter"])
    graph.add_node("qa", nodes["qa"])
    graph.add_node("review_qa", nodes["review_qa"])
    graph.add_node("email", nodes["email"])

    graph.set_entry_point("scout")

    graph.add_conditional_edges("scout", _after_scout)
    graph.add_conditional_edges("curator", _after_curator)
    graph.add_conditional_edges("review_articles", _after_review_articles)
    graph.add_conditional_edges("extractor", _after_extractor)
    graph.add_edge("source_resolver", "editor")
    graph.add_edge("editor", "writer")
    graph.add_conditional_edges("writer", _after_writer)
    graph.add_conditional_edges("review_newsletter", _after_review_newsletter)
    graph.add_conditional_edges("qa", _after_qa)
    graph.add_conditional_edges("review_qa", _after_review_qa)
    graph.add_edge("email", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("Newsletter pipeline graph compiled with HITL checkpointer")
    return compiled

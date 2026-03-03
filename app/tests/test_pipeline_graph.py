"""Tests for pipeline graph conditional edges and build_pipeline."""

from unittest.mock import AsyncMock

from langgraph.graph import END

from app.pipeline.graph import (
    _after_scout,
    _after_curator,
    _after_review_articles,
    _after_extractor,
    _after_writer,
    _after_review_newsletter,
    _after_qa,
    build_pipeline,
)


class TestAfterScout:
    def test_continues_when_candidates_exist(self):
        state = {"candidates": [{"url": "https://example.com"}]}
        assert _after_scout(state) == "curator"

    def test_stops_when_no_candidates(self):
        state = {"candidates": []}
        assert _after_scout(state) == END

    def test_stops_when_candidates_key_missing(self):
        state = {}
        assert _after_scout(state) == END


class TestAfterCurator:
    def test_continues_to_review_when_curated_exist(self):
        state = {"curated": [{"url": "https://example.com"}]}
        assert _after_curator(state) == "review_articles"

    def test_stops_when_no_curated(self):
        state = {"curated": []}
        assert _after_curator(state) == END

    def test_stops_when_curated_key_missing(self):
        state = {}
        assert _after_curator(state) == END


class TestAfterReviewArticles:
    def test_continues_to_extractor_when_articles_approved(self):
        state = {"curated": [{"url": "https://example.com"}]}
        assert _after_review_articles(state) == "extractor"

    def test_stops_when_all_articles_removed(self):
        state = {"curated": []}
        assert _after_review_articles(state) == END

    def test_stops_when_key_missing(self):
        state = {}
        assert _after_review_articles(state) == END


class TestAfterExtractor:
    def test_continues_when_articles_extracted(self):
        state = {"extracted_articles": [{"id": "1"}]}
        assert _after_extractor(state) == "source_resolver"

    def test_stops_when_no_articles(self):
        state = {"extracted_articles": []}
        assert _after_extractor(state) == END

    def test_stops_when_key_missing(self):
        state = {}
        assert _after_extractor(state) == END


class TestAfterWriter:
    def test_continues_to_review_when_newsletter_exists(self):
        state = {"newsletter_json": {"issue_title": "Test"}}
        assert _after_writer(state) == "review_newsletter"

    def test_stops_when_no_newsletter(self):
        state = {"newsletter_json": None}
        assert _after_writer(state) == END

    def test_stops_when_key_missing(self):
        state = {}
        assert _after_writer(state) == END


class TestAfterReviewNewsletter:
    def test_continues_to_qa_when_approved(self):
        state = {"newsletter_json": {"issue_title": "Test"}}
        assert _after_review_newsletter(state) == "qa"

    def test_loops_to_writer_when_feedback_set(self):
        state = {"user_feedback": "make it punchier", "newsletter_json": {"issue_title": "Test"}}
        assert _after_review_newsletter(state) == "writer"

    def test_stops_when_rejected(self):
        state = {"error": "Newsletter rejected by user", "newsletter_json": None}
        assert _after_review_newsletter(state) == END

    def test_reject_takes_priority_over_feedback(self):
        state = {"error": "rejected", "user_feedback": "something"}
        assert _after_review_newsletter(state) == END

    def test_stops_when_no_newsletter(self):
        state = {"newsletter_json": None}
        assert _after_review_newsletter(state) == END


class TestAfterQA:
    def test_always_routes_to_review_qa(self):
        state = {"newsletter_json": {"issue_title": "Test"}}
        assert _after_qa(state) == "review_qa"


class TestBuildPipeline:
    def test_returns_compiled_graph(self):
        mock_db = AsyncMock()
        compiled = build_pipeline(mock_db)
        assert hasattr(compiled, "ainvoke")
        assert callable(compiled.ainvoke)

    def test_graph_has_hitl_nodes(self):
        mock_db = AsyncMock()
        compiled = build_pipeline(mock_db)
        graph_nodes = set(compiled.get_graph().nodes.keys())
        expected = {
            "scout", "curator", "review_articles",
            "extractor", "source_resolver", "editor",
            "writer", "review_newsletter", "qa", "email",
        }
        assert expected.issubset(graph_nodes)

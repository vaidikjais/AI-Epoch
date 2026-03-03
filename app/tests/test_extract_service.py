"""Tests for app.services.extract_service.ExtractService."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.extract_service import ExtractService


@pytest.fixture
def extract_service():
    return ExtractService()


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Article Title</title></head>
<body>
    <article>
        <h1>Test Article Title</h1>
        <p>This is the first paragraph of the article with some meaningful content.
           We need enough words here to pass the quality check. The article discusses
           artificial intelligence and machine learning advances. Researchers have
           made significant progress in natural language processing. This content
           should be extractable by trafilatura.</p>
        <p>Second paragraph with more details about the topic. Additional context
           for the reader. Enough words to form a valid article body.</p>
    </article>
</body>
</html>
"""


class TestTrafilaturaExtract:

    def test_extracts_title_and_text(self, extract_service):
        result = extract_service._trafilatura_extract(SAMPLE_HTML, "https://example.com/article")

        assert "title" in result
        assert "text" in result
        assert "date" in result
        assert "lang" in result
        assert isinstance(result["text"], str)
        assert isinstance(result["title"], str)


class TestQualityOk:

    def test_returns_false_for_empty_text(self, extract_service):
        assert extract_service._quality_ok(None) is False
        assert extract_service._quality_ok("") is False

    def test_returns_false_below_min_words(self, extract_service):
        with patch("app.services.extract_service.settings") as mock_settings:
            mock_settings.SCRAPE_MIN_WORDS = 50
            text = "one two three four five"
            assert extract_service._quality_ok(text, min_words=50) is False
            assert extract_service._quality_ok(text, min_words=10) is False

    def test_returns_true_at_min_words(self, extract_service):
        text = " ".join(["word"] * 120)
        with patch("app.services.extract_service.settings") as mock_settings:
            mock_settings.SCRAPE_MIN_WORDS = 120
            assert extract_service._quality_ok(text) is True
        assert extract_service._quality_ok(text, min_words=120) is True

    def test_returns_true_above_min_words(self, extract_service):
        text = " ".join(["word"] * 200)
        assert extract_service._quality_ok(text, min_words=120) is True


class TestLooksJsHeavy:

    def test_returns_true_for_empty_html(self, extract_service):
        assert extract_service._looks_js_heavy("") is True

    def test_returns_true_for_little_visible_text(self, extract_service):
        html = "<html><body><div id='root'></div></body></html>"
        assert extract_service._looks_js_heavy(html) is True

    def test_returns_true_for_next_data_marker(self, extract_service):
        html = "<html><body><script>__NEXT_DATA__</script><p>Some text</p>" + "x" * 300 + "</body></html>"
        assert extract_service._looks_js_heavy(html) is True

    def test_returns_true_for_react_helmet_marker(self, extract_service):
        html = "<html><body data-rh='x'><p>Content</p>" + "x" * 250 + "</body></html>"
        assert extract_service._looks_js_heavy(html) is True

    def test_returns_true_for_id_next(self, extract_service):
        html = '<html><body><div id="__next">content</div>' + "x" * 250 + "</body></html>"
        assert extract_service._looks_js_heavy(html) is True

    def test_returns_false_for_substantial_static_html(self, extract_service):
        html = "<html><body><p>" + "Lorem ipsum dolor sit amet. " * 30 + "</p></body></html>"
        assert extract_service._looks_js_heavy(html) is False


class TestNormalizeWhitespace:

    def test_collapses_multiple_newlines(self, extract_service):
        text = "Para 1\n\n\n\n\nPara 2"
        result = extract_service._normalize_whitespace(text)
        assert "\n\n\n" not in result
        assert "Para 1" in result and "Para 2" in result

    def test_normalizes_space_before_newline(self, extract_service):
        text = "Line 1   \n   \nLine 2"
        result = extract_service._normalize_whitespace(text)
        assert "   \n" not in result or result.count("\n") <= 2

    def test_strips_whitespace(self, extract_service):
        text = "  \n  content  \n  "
        result = extract_service._normalize_whitespace(text)
        assert result.strip() == result


class TestRobustExtract:

    async def test_robust_extract_wrapper_format(self, extract_service):
        mock_result = {
            "ok": True,
            "final_url": "https://example.com/article",
            "title": "Test Title",
            "text": "Article body text here with enough words.",
            "meta": {"date": None, "lang": "en"},
        }

        with patch.object(
            extract_service,
            "fetch_and_extract",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await extract_service.robust_extract("https://example.com/article")

        assert result["final_url"] == "https://example.com/article"
        assert result["title"] == "Test Title"
        assert result["text"] == "Article body text here with enough words."
        assert "hash" in result
        assert "word_count" in result
        assert result["word_count"] == 7  # "Article body text here with enough words."
        assert "last_modified" in result
        assert "lang" in result


class TestFetchAndExtract:

    async def test_successful_httpx_trafilatura_path(self, extract_service):
        mock_html = SAMPLE_HTML
        mock_http_resp = {
            "ok": True,
            "html": mock_html,
            "final_url": "https://example.com/article",
            "headers": {},
            "elapsed_ms": 100,
        }
        mock_tf = {
            "title": "Test Article Title",
            "text": "This is the first paragraph. " * 50,
            "date": None,
            "lang": "en",
        }

        with patch.object(
            extract_service,
            "_http_fetch",
            new=AsyncMock(return_value=mock_http_resp),
        ):
            with patch.object(
                extract_service,
                "_async_trafilatura_extract",
                new=AsyncMock(return_value=mock_tf),
            ):
                result = await extract_service.fetch_and_extract("https://example.com/article")

        assert result["ok"] is True
        assert result["source"] == "httpx"
        assert "text" in result
        assert result["final_url"] == "https://example.com/article"

    async def test_fallback_to_playwright_path(self, extract_service):
        with patch.object(
            extract_service,
            "_http_fetch",
            new=AsyncMock(side_effect=Exception("HTTP error")),
        ):
            with patch("app.services.extract_service.settings") as mock_settings:
                mock_settings.PLAYWRIGHT_ENABLED = True
                mock_settings.SCRAPE_MIN_WORDS = 120

                mock_playwright_result = {
                    "final_url": "https://example.com/article",
                    "html": "<html><body><p>" + "content " * 150 + "</p></body></html>",
                    "title": "Playwright Title",
                    "text": "Rendered content " * 80,
                }

                with patch.object(
                    extract_service,
                    "_attempt_playwright",
                    new=AsyncMock(return_value=mock_playwright_result),
                ):
                    result = await extract_service.fetch_and_extract("https://example.com/article")

        assert result["ok"] is True
        assert result["source"] == "playwright"
        assert "Playwright Title" in result["title"] or "content" in result["text"]

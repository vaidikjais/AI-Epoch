"""Tests for app.services.assembler_service.NewsletterAssembler."""
import pytest

from app.services.assembler_service import NewsletterAssembler


@pytest.fixture
def complete_newsletter_json():
    return {
        "issue_title": "AI Newsletter",
        "issue_number": 42,
        "date_iso": "2025-02-13T12:00:00Z",
        "subheadline": "AI breakthroughs, research updates, and product launches",
        "intro": "Welcome to another edition of AI Newsletter. This week we cover the latest in AI.",
        "headline": {
            "section_type": "headline",
            "title": "OpenAI Releases GPT-5",
            "summary": "OpenAI has unveiled GPT-5 with significant improvements. - OpenAI Blog",
            "source_label": "OpenAI Blog",
            "source_url": "https://openai.com/news/gpt5",
            "emoji": "🏆",
            "confidence": "high",
        },
        "latest_news": [
            {
                "section_type": "news",
                "title": "CNBC: AI Stocks Rally",
                "summary": "Major AI companies see stock gains. - CNBC",
                "source_label": "CNBC",
                "source_url": "https://cnbc.com/ai-rally",
                "emoji": "📰",
                "confidence": "high",
            },
        ],
        "company_updates": [
            {
                "section_type": "company_update",
                "title": "Anthropic Claude 4",
                "summary": "Anthropic announces Claude 4 with improved reasoning. - Anthropic",
                "source_label": "Anthropic",
                "source_url": "https://anthropic.com/claude4",
                "emoji": "🏢",
                "confidence": "high",
            },
        ],
        "research_spotlight": {
            "section_type": "research",
            "title": "New Paper: Efficient Transformers",
            "summary": "Researchers present a more efficient transformer architecture. - arXiv",
            "source_label": "arXiv",
            "source_url": "https://arxiv.org/abs/2502.12345",
            "emoji": "🔬",
            "confidence": "high",
        },
        "tools_and_products": [
            {
                "section_type": "product",
                "title": "HuggingFace New Model",
                "summary": "HuggingFace releases new open weights model. - HuggingFace",
                "source_label": "HuggingFace",
                "source_url": "https://huggingface.co/model",
                "emoji": "⚙️",
                "confidence": "high",
            },
        ],
        "quick_bytes": [
            {
                "section_type": "quick_byte",
                "title": "Quick Update",
                "summary": "Short news snippet. - Source",
                "source_label": "Source",
                "source_url": "https://example.com",
                "emoji": "⚡",
                "confidence": "high",
            },
        ],
        "wrap": "Keep building, keep learning. See you next week.",
        "footer": "© 2025 AI Newsletter | Curated with intelligence, crafted with care",
        "estimated_read_time": "4-6 minutes",
        "quality_checks": {
            "all_sections_present": True,
            "word_counts_valid": True,
            "all_articles_included": True,
        },
    }


@pytest.fixture
def minimal_newsletter_json():
    return {
        "issue_title": "Minimal Issue",
        "intro": "Brief intro",
        "footer": "© 2025",
    }


class TestToMarkdown:

    def test_to_markdown_complete_returns_markdown_with_header_sections(
        self, complete_newsletter_json
    ):
        assembler = NewsletterAssembler()
        result = assembler.to_markdown(complete_newsletter_json)

        assert "# AI Newsletter" in result
        assert "Issue #42" in result
        assert "2025-02-13" in result
        assert "HEADLINE" in result
        assert "OpenAI Releases GPT-5" in result
        assert "LATEST NEWS" in result
        assert "COMPANY UPDATES" in result
        assert "RESEARCH SPOTLIGHT" in result
        assert "TOOLS & RELEASES" in result
        assert "QUICK BYTES" in result
        assert "OpenAI Blog" in result or "openai.com" in result
        assert "4-6 minutes" in result

    def test_to_markdown_minimal_does_not_crash(self, minimal_newsletter_json):
        assembler = NewsletterAssembler()
        result = assembler.to_markdown(minimal_newsletter_json)

        assert "Minimal Issue" in result
        assert "Brief intro" in result
        assert "© 2025" in result

    def test_to_markdown_empty_dict_does_not_crash(self):
        assembler = NewsletterAssembler()
        result = assembler.to_markdown({})

        assert isinstance(result, str)
        assert len(result) > 0


class TestToHtml:

    def test_to_html_complete_returns_html_with_proper_structure(
        self, complete_newsletter_json
    ):
        assembler = NewsletterAssembler()
        result = assembler.to_html(complete_newsletter_json)

        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "<head>" in result
        assert "<body" in result
        assert "AI Newsletter" in result
        assert "Issue #42" in result
        assert "HEADLINE" in result
        assert "Latest News" in result
        assert "Company Updates" in result
        assert "Research Spotlight" in result
        assert "Tools" in result
        assert "Quick Bytes" in result
        assert "OpenAI Releases GPT-5" in result
        assert "openai.com" in result or "https://" in result

    def test_to_html_minimal_does_not_crash(self, minimal_newsletter_json):
        assembler = NewsletterAssembler()
        result = assembler.to_html(minimal_newsletter_json)

        assert "<!DOCTYPE html>" in result
        assert "Minimal Issue" in result
        assert "Brief intro" in result

    def test_to_html_empty_dict_does_not_crash(self):
        assembler = NewsletterAssembler()
        result = assembler.to_html({})

        assert isinstance(result, str)
        assert "<!DOCTYPE html>" in result
        assert len(result) > 0

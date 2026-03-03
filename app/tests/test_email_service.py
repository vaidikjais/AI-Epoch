"""Tests for app.services.email_service."""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.email_service import (
    MockEmailProvider,
    EmailService,
    SMTPEmailProvider,
)


class TestMockEmailProvider:

    async def test_send_email_always_returns_true(self):
        provider = MockEmailProvider()
        result = await provider.send_email(
            to_email="test@example.com",
            subject="Test Subject",
            html_body="<p>Test body</p>",
        )
        assert result is True


class TestEmailServiceWithMockProvider:

    async def test_send_newsletter_email_returns_success_dict(self):
        mock_provider = AsyncMock(spec=MockEmailProvider)
        mock_provider.send_email = AsyncMock(return_value=True)

        service = EmailService(provider=mock_provider)
        result = await service.send_newsletter_email(
            to_email="subscriber@example.com",
            subject="Weekly Digest",
            html_body="<h1>Newsletter</h1><p>Content here</p>",
        )

        assert result["success"] is True
        assert result["error"] is None
        mock_provider.send_email.assert_called_once_with(
            "subscriber@example.com",
            "Weekly Digest",
            "<h1>Newsletter</h1><p>Content here</p>",
        )

    async def test_send_simple_email_returns_true(self):
        mock_provider = AsyncMock(spec=MockEmailProvider)
        mock_provider.send_email = AsyncMock(return_value=True)

        service = EmailService(provider=mock_provider)
        result = await service.send_simple_email(
            to_email="user@example.com",
            subject="Hello",
            html_body="<p>Hello world</p>",
        )

        assert result is True

    async def test_send_simple_email_returns_false_on_provider_failure(self):
        mock_provider = AsyncMock(spec=MockEmailProvider)
        mock_provider.send_email = AsyncMock(return_value=False)

        service = EmailService(provider=mock_provider)
        result = await service.send_simple_email(
            to_email="user@example.com",
            subject="Hello",
            html_body="<p>Hello</p>",
        )

        assert result is False


class TestSMTPEmailProvider:

    async def test_send_email_returns_false_when_smtp_not_configured(self):
        with patch("app.services.email_service.settings") as mock_settings:
            mock_settings.SMTP_HOST = ""
            mock_settings.SMTP_FROM = ""

            provider = SMTPEmailProvider()
            result = await provider.send_email(
                to_email="test@example.com",
                subject="Test",
                html_body="<p>Test</p>",
            )

        assert result is False


class TestEmailServiceErrorHandling:

    async def test_send_newsletter_email_handles_provider_exception(self):
        mock_provider = AsyncMock(spec=MockEmailProvider)
        mock_provider.send_email = AsyncMock(
            side_effect=ConnectionError("SMTP connection failed")
        )

        service = EmailService(provider=mock_provider)
        result = await service.send_newsletter_email(
            to_email="user@example.com",
            subject="Test",
            html_body="<p>Body</p>",
        )

        assert result["success"] is False
        assert result["error"] == "SMTP connection failed"

    async def test_send_newsletter_email_returns_error_when_provider_returns_false(self):
        mock_provider = AsyncMock(spec=MockEmailProvider)
        mock_provider.send_email = AsyncMock(return_value=False)

        service = EmailService(provider=mock_provider)
        result = await service.send_newsletter_email(
            to_email="user@example.com",
            subject="Test",
            html_body="<p>Body</p>",
        )

        assert result["success"] is False
        assert result["error"] == "email_send_failed"

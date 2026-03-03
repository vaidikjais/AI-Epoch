"""Email composition and delivery with provider abstraction for newsletter publishing."""
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("email_service")


class EmailProvider(ABC):
    
    @abstractmethod
    async def send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        pass


class SMTPEmailProvider(EmailProvider):

    def _send_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            if settings.SMTP_TLS:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)

            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
            server.quit()
            logger.info("Email sent to %s", to_email)
            return True
        except Exception as e:
            logger.error("Failed to send email to %s: %s", to_email, e)
            return False

    async def send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        if not settings.SMTP_HOST or not settings.SMTP_FROM:
            logger.warning("SMTP not configured; skipping real send. to=%s subject=%s", to_email, subject)
            return False

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._send_sync, to_email, subject, html_body)


class MockEmailProvider(EmailProvider):
    
    async def send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        logger.info("MOCK EMAIL: To=%s, Subject=%s, Body length=%d", to_email, subject, len(html_body))
        return True


class EmailService:
    
    def __init__(self, provider: Optional[EmailProvider] = None):
        self.provider = provider or self._get_default_provider()
    
    def _get_default_provider(self) -> EmailProvider:
        if settings.SMTP_HOST and settings.SMTP_FROM:
            return SMTPEmailProvider()
        else:
            logger.warning("SMTP not configured, using mock email provider")
            return MockEmailProvider()
    
    async def send_newsletter_email(self, to_email: str, subject: str, html_body: str) -> Dict[str, Any]:
        try:
            success = await self.provider.send_email(to_email, subject, html_body)
            return {
                "success": success,
                "error": None if success else "email_send_failed"
            }
        except Exception as e:
            logger.error(f"Email service error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_simple_email(self, to_email: str, subject: str, html_body: str) -> bool:
        result = await self.send_newsletter_email(to_email, subject, html_body)
        return result["success"]

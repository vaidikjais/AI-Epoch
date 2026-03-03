"""Email controller — newsletter email delivery."""
import time
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.email_service import EmailService
from app.services.email_group_service import EmailGroupService
from app.schemas.email_schema import SendEmailRequest, SendEmailResponse
from app.utils.logger import get_logger

logger = get_logger("email_controller")

router = APIRouter(prefix="/email", tags=["Email"])


def email_svc_dep() -> EmailService:
    return EmailService()


def group_svc_dep(db: AsyncSession = Depends(get_session)) -> EmailGroupService:
    return EmailGroupService(db)


@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    request: SendEmailRequest,
    email_svc: EmailService = Depends(email_svc_dep),
    group_svc: EmailGroupService = Depends(group_svc_dep),
):
    """Send email to individual recipients and/or email groups."""
    try:
        start_time = time.time()

        final_recipients = await group_svc.resolve_recipients(
            group_ids=request.group_ids,
            extra_emails=[str(e) for e in request.recipients],
        )

        if not final_recipients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No recipients — provide at least one email or group",
            )

        sent_count = 0
        errors = []

        for recipient in final_recipients:
            try:
                result = await email_svc.send_newsletter_email(
                    to_email=recipient,
                    subject=request.subject,
                    html_body=request.html_content,
                )
                if result.get("success"):
                    sent_count += 1
                else:
                    errors.append(f"{recipient}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Error sending to {recipient}: {e}")
                errors.append(f"{recipient}: {str(e)}")

        delivery_time = time.time() - start_time
        all_sent = sent_count == len(final_recipients)
        provider = "smtp" if hasattr(email_svc.provider, '__class__') and "SMTP" in email_svc.provider.__class__.__name__ else "mock"

        return SendEmailResponse(
            sent=all_sent,
            recipients_count=sent_count,
            message_id=None,
            sent_at=None,
            provider=provider,
            delivery_time_seconds=delivery_time,
            error="; ".join(errors) if errors else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email sending failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Email sending failed: {str(e)}",
        )


@router.post("/test", response_model=SendEmailResponse)
async def test_email(
    recipient: str = Query(..., description="Test recipient email"),
    email_svc: EmailService = Depends(email_svc_dep),
):
    """Send a test email to verify configuration."""
    try:
        start_time = time.time()

        test_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Email</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f9f9f9;">
            <div style="background-color: white; padding: 30px; border-radius: 8px; max-width: 600px; margin: 0 auto;">
                <h1 style="color: #2563eb;">Test Email from AI Newsletter</h1>
                <p style="color: #333; line-height: 1.6;">This is a test email to verify your email configuration.</p>
                <p style="color: #666; font-size: 14px; margin-top: 30px;">If you received this, your email settings are working correctly!</p>
                <hr style="border: 0; height: 1px; background: #e2e8f0; margin: 20px 0;">
                <p style="color: #999; font-size: 12px; text-align: center;">AI Newsletter System</p>
            </div>
        </body>
        </html>
        """

        result = await email_svc.send_newsletter_email(
            to_email=recipient,
            subject="Test Email from AI Newsletter",
            html_body=test_html,
        )

        delivery_time = time.time() - start_time
        provider = "smtp" if hasattr(email_svc.provider, '__class__') and "SMTP" in email_svc.provider.__class__.__name__ else "mock"

        return SendEmailResponse(
            sent=result.get("success", False),
            recipients_count=1 if result.get("success") else 0,
            message_id=None,
            sent_at=None,
            provider=provider,
            delivery_time_seconds=delivery_time,
            error=result.get("error") if not result.get("success") else None,
        )

    except Exception as e:
        logger.error(f"Test email failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test email failed: {str(e)}",
        )

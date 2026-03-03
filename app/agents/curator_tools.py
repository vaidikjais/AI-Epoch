"""Tools available to the agentic Curator for reading article content."""

from __future__ import annotations

import asyncio
from typing import Optional

from langchain_core.tools import tool

from app.utils.logger import get_logger

logger = get_logger("agents.curator_tools")

_READ_TIMEOUT_SECS = 10
_MAX_CONTENT_CHARS = 2000


@tool
async def read_article(url: str) -> str:
    """Fetch and read the full content of an article URL.

    Use this tool when you need to assess the actual substance and quality of
    an article before making an editorial decision.  Returns the article title
    and the first ~2 000 characters of extracted text.
    """
    from app.services.extract_service import ExtractService

    logger.info(f"read_article tool called for {url[:80]}")
    try:
        svc = ExtractService()
        result = await asyncio.wait_for(
            svc.robust_extract(url),
            timeout=_READ_TIMEOUT_SECS,
        )
        title = result.get("title", "") or ""
        text = result.get("text", "") or ""
        word_count = len(text.split())

        if not text:
            return f"[Extraction failed — no readable content for {url}]"

        preview = text[:_MAX_CONTENT_CHARS]
        return (
            f"Title: {title}\n"
            f"Word count: {word_count}\n"
            f"Content:\n{preview}"
        )
    except asyncio.TimeoutError:
        logger.warning(f"read_article timed out for {url}")
        return f"[Timed out after {_READ_TIMEOUT_SECS}s trying to read {url}]"
    except Exception as exc:
        logger.warning(f"read_article failed for {url}: {exc}")
        return f"[Failed to read article: {exc}]"

"""Multi-strategy content extraction from web articles using httpx, trafilatura, and Playwright."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Dict, Optional, Any

import httpx
import trafilatura
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from app.utils.logger import get_logger
from app.core.config import settings

logger = get_logger("extract_service")


class ExtractService:

    def __init__(self):
        self.ua = getattr(settings, "USER_AGENT", "AgenticNewsletterBot/1.0 (+contact:you@example.com)")
        self.default_headers = {
            "User-Agent": self.ua, 
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=10))
    async def _http_fetch(self, url: str, timeout: int = None) -> Dict[str, Any]:
        t0 = time.time()
        timeout = timeout or getattr(settings, "SCRAPE_TIMEOUT_SECS", 30)
        headers = dict(self.default_headers)
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, http2=False, timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
                elapsed_ms = int((time.time() - t0) * 1000)
                return {
                    "ok": True,
                    "status_code": resp.status_code,
                    "final_url": str(resp.url),
                    "html": html,
                    "headers": dict(resp.headers),
                    "elapsed_ms": elapsed_ms,
                }
        except Exception as e:
            logger.debug("HTTP fetch error for %s: %s", url, e)
            raise

    def _trafilatura_extract(self, html: str, url: str) -> Dict[str, Any]:
        # favor_recall=True to be more aggressive on short articles
        text = (
            trafilatura.extract(
                html,
                url=url,
                include_links=False,
                include_comments=False,
                favor_recall=True,
            )
            or ""
        )
        meta = trafilatura.metadata.extract_metadata(html)
        title = (getattr(meta, "title", "") or "").strip() if meta else ""
        date = getattr(meta, "date", None) or getattr(meta, "updated", None) if meta else None
        lang = getattr(meta, "language", None) if meta else None
        return {"title": title, "text": (text or "").strip(), "date": date, "lang": lang}

    async def _async_trafilatura_extract(self, html: str, url: str) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._trafilatura_extract, html, url)

    def _quality_ok(self, text: Optional[str], min_words: Optional[int] = None) -> bool:
        if not text:
            return False
        min_words = min_words or getattr(settings, "SCRAPE_MIN_WORDS", 120)
        return len((text or "").split()) >= min_words

    def _looks_js_heavy(self, html: str) -> bool:
        if not html:
            return True
        text_without_tags = re.sub(r"<[^>]+>", " ", html)
        text_without_ws = re.sub(r"\s+", " ", text_without_tags).strip()
        return (
            len(text_without_ws) < 200
            or "__NEXT_DATA__" in html
            or "data-rh" in html
            or 'id="__next"' in html
        )

    async def _attempt_playwright(self, url: str, wait_selector: Optional[str] = None, timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        if not getattr(settings, "PLAYWRIGHT_ENABLED", True):
            raise RuntimeError("Playwright is disabled in settings")

        timeout_ms = timeout_ms or (getattr(settings, "SCRAPE_TIMEOUT_SECS", 30) * 1000)
        wait_selector = wait_selector or "main, article, [role='main'], #__next, .article, .post"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=self.ua)

            async def route_handler(route, request):
                rtype = request.resource_type
                urlreq = request.url
                if rtype in ("image", "font", "media"):
                    await route.abort()
                elif rtype == "script" and ("analytics" in urlreq or "googletag" in urlreq or "gtag" in urlreq):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", route_handler)

            try:
                await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                
                try:
                    await page.wait_for_selector(wait_selector, timeout=5000)
                except PWTimeout:
                    pass

                READABILITY_URL = "https://unpkg.com/@mozilla/readability@0.5.0/Readability.js"
                try:
                    await page.add_script_tag(url=READABILITY_URL)
                except Exception:
                    logger.debug("Could not inject Readability.js on %s", url)

                extract_script = """
                () => {
                    try {
                        const doc = document.cloneNode(true);
                        const reader = new Readability(doc);
                        const art = reader.parse();
                        if (!art) return null;
                        return { title: art.title || document.title || "", textContent: art.textContent || "", content: art.content || "" };
                    } catch (e) {
                        return null;
                    }
                }
                """
                readable = None
                try:
                    readable = await page.evaluate(extract_script)
                except Exception:
                    readable = None

                final_html = await page.content()
                final_url = page.url
                title = ""
                text = ""
                if readable and isinstance(readable, dict):
                    title = readable.get("title", "") or await page.title() or ""
                    text = readable.get("textContent", "") or ""
                
                return {"final_url": final_url, "html": final_html, "title": title, "text": text}
            finally:
                await browser.close()

    def _normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+\n", "\n", re.sub(r"\n{3,}", "\n\n", text or "")).strip()

    async def robust_extract(self, url: str) -> Dict[str, Any]:
        """Legacy wrapper around fetch_and_extract for backward compatibility."""
        result = await self.fetch_and_extract(url)
        
        return {
            "final_url": result.get("final_url", url),
            "title": result.get("title", ""),
            "text": result.get("text", ""),
            "last_modified": result.get("meta", {}).get("date"),
            "lang": result.get("meta", {}).get("lang"),
            "hash": hashlib.sha256((result.get("text", "") or "").encode("utf-8")).hexdigest(),
            "word_count": len(result.get("text", "").split()) if result.get("text") else 0,
        }

    async def fetch_and_extract(self, url: str, min_words: Optional[int] = None) -> Dict[str, Any]:
        """Tries httpx+trafilatura, then Playwright+Readability, then trafilatura on rendered HTML."""
        min_words = min_words or getattr(settings, "SCRAPE_MIN_WORDS", 120)

        # Ensure tf exists even if httpx path raises
        tf: Dict[str, Any] = {"text": "", "title": "", "date": None, "lang": None}

        try:
            t0 = time.time()
            resp = await self._http_fetch(url)
            html = resp.get("html", "") or ""
            final_url = resp.get("final_url", url)
            tf = await self._async_trafilatura_extract(html, final_url)
            if self._quality_ok(tf.get("text"), min_words=min_words) and not self._looks_js_heavy(html):
                meta = {
                    "headers": resp.get("headers"),
                    "elapsed_ms": resp.get("elapsed_ms"),
                    "source_method": "httpx+trafilatura",
                }
                txt = self._normalize_whitespace(tf.get("text", ""))
                result = {
                    "ok": True,
                    "source": "httpx",
                    "html": html,
                    "text": txt,
                    "title": tf.get("title") or "",
                    "final_url": final_url,
                    "meta": {**meta, "lang": tf.get("lang"), "date": tf.get("date")},
                    "reason": None,
                }
                logger.info("[extract] httpx+trafilatura success for %s (%d words)", final_url, len(txt.split()))
                return result
        except Exception as e:
            logger.debug("httpx fetch/extract failed for %s: %s", url, e)

        if getattr(settings, "PLAYWRIGHT_ENABLED", True):
            try:
                logger.info("[extract] falling back to Playwright for %s", url)
                rendered = await self._attempt_playwright(url)
                rendered_html = rendered.get("html", "")
                final_url = rendered.get("final_url", url)
                text = (rendered.get("text") or "").strip()
                title = rendered.get("title") or ""
                if self._quality_ok(text, min_words=min_words):
                    txt = self._normalize_whitespace(text)
                    meta = {"source_method": "playwright+readability"}
                    logger.info("[extract] playwright+readability success for %s (%d words)", final_url, len(txt.split()))
                    return {
                        "ok": True,
                        "source": "playwright",
                        "html": rendered_html,
                        "text": txt,
                        "title": title,
                        "final_url": final_url,
                        "meta": meta,
                        "reason": None,
                    }

                # Try trafilatura on rendered HTML with relaxed threshold
                tf2 = await self._async_trafilatura_extract(rendered_html, final_url)
                if self._quality_ok(tf2.get("text"), min_words=max(60, min_words // 2)):
                    txt = self._normalize_whitespace(tf2.get("text"))
                    meta = {"source_method": "trafilatura_on_rendered"}
                    logger.info("[extract] trafilatura_on_rendered success for %s (%d words)", final_url, len(txt.split()))
                    return {
                        "ok": True,
                        "source": "trafilatura_render",
                        "html": rendered_html,
                        "text": txt,
                        "title": tf2.get("title") or title,
                        "final_url": final_url,
                        "meta": meta,
                        "reason": None,
                    }

                # Best-effort: return whatever text we have
                txt = self._normalize_whitespace(text or tf.get("text", "") or tf2.get("text", ""))
                meta = {"source_method": "playwright_low_quality"}
                logger.warning("[extract] low-quality extraction for %s; returning best-effort text", final_url)
                return {
                    "ok": len(txt.split()) > 0,
                    "source": "playwright",
                    "html": rendered_html,
                    "text": txt,
                    "title": title or tf.get("title") or tf2.get("title", ""),
                    "final_url": final_url,
                    "meta": meta,
                    "reason": "low_quality_after_render",
                }
            except Exception as e:
                logger.exception("Playwright extraction failed for %s: %s", url, e)

        # Last resort: re-run trafilatura on previously fetched HTML if available
        try:
            if 'resp' in locals():
                tf_final = await self._async_trafilatura_extract(resp.get("html", ""), resp.get("final_url", url))
                txt = self._normalize_whitespace(tf_final.get("text", ""))
                if txt:
                    logger.info("[extract] final trafilatura fallback success for %s (%d words)", url, len(txt.split()))
                    return {
                        "ok": True,
                        "source": "trafilatura_final",
                        "html": resp.get("html", ""),
                        "text": txt,
                        "title": tf_final.get("title", ""),
                        "final_url": resp.get("final_url", url),
                        "meta": {"source_method": "trafilatura_final"},
                        "reason": None,
                    }
        except Exception:
            pass

        logger.error("[extract] extraction failed for %s", url)
        return {"ok": False, "source": "none", "html": "", "text": "", "title": "", "final_url": url, "meta": {}, "reason": "extraction_failed"}

"""Article lifecycle service — ingestion and retrieval."""
from typing import Optional, List, Any

from app.repository.article_repository import ArticleRepository
from app.repository.candidate_repository import ArticleCandidateRepository
from app.services.extract_service import ExtractService
from app.utils.s3_utils import async_upload_text, async_download_text
from app.models.article_model import Article
from app.schemas.article_schema import ArticleCreate
from app.utils.logger import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("article_service")


class ArticleService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.article_repo = ArticleRepository(db)
        self.candidate_repo = ArticleCandidateRepository(db)
        self.extract_service = ExtractService()

    async def ingest_single_url(self, url: str) -> Optional[Article]:
        """Idempotent: returns existing article if already ingested."""
        url_str = str(url)
        try:
            existing_article = await self.article_repo.get_by_url(url_str)
            if existing_article:
                logger.info(f"Article already ingested: {url_str}")
                return existing_article

            import time
            start = time.time()
            result = await self.extract_service.robust_extract(url_str)
            fetch_time_ms = int((time.time() - start) * 1000)

            text = result.get("text") or ""
            final_url = result.get("final_url") or url_str
            title = result.get("title") or self._extract_title_from_text(text)
            last_modified = result.get("last_modified")
            word_count = len(text.split())

            if not text or word_count < 60:
                logger.error(f"Failed to extract sufficient text from {url_str}")
                return None

            preview = text[:400]
            bucket_key = await async_upload_text(data=text.encode("utf-8"))

            article_data = ArticleCreate(
                url=final_url,
                title=title,
                raw_text_preview=preview,
                bucket_key=bucket_key,
                published_at=last_modified
            )

            article = await self.article_repo.create_article(article_data)
            logger.info(f"Article ingested: {final_url} ({fetch_time_ms}ms, {word_count}w)")
            return article

        except Exception as e:
            logger.error(f"Error ingesting article {url_str}: {e}")
            return None

    async def list_recent_articles(self, limit: int = 50, offset: int = 0) -> List[Article]:
        try:
            return await self.article_repo.list_recent_articles(limit=limit, offset=offset)
        except Exception as e:
            logger.error(f"Error listing articles: {e}")
            return []

    async def get_article_by_id(self, article_id: str) -> Optional[Article]:
        return await self.article_repo.get_by_id(article_id)

    async def get_article_content(self, article_id: str) -> Optional[str]:
        article = await self.article_repo.get_by_id(article_id)
        if not article or not article.bucket_key:
            return None
        try:
            return await async_download_text(article.bucket_key)
        except Exception as e:
            logger.error(f"Failed to download content for {article_id}: {e}")
            return None

    def _extract_title_from_text(self, text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line[:80]
        return text[:80] if text else "Untitled Article"

"""Extractor controller — article content extraction."""
import time
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.article_service import ArticleService
from app.services.extract_service import ExtractService
from app.schemas.extractor_schema import (
    ExtractRequest, ExtractResponse, ExtractCandidatesRequest,
    ExtractCandidatesResponse, ExtractionMetadata, ExtractedArticle, FailedExtraction
)
from app.schemas.article_schema import ArticleCreate
from app.utils.s3_utils import async_upload_text
from app.utils.logger import get_logger

logger = get_logger("extractor_controller")

router = APIRouter(prefix="/extractor", tags=["Extractor"])


def service_dep(db: AsyncSession = Depends(get_session)) -> ArticleService:
    return ArticleService(db)


@router.post("/extract", response_model=ExtractResponse)
async def extract_url(
    request: ExtractRequest,
    svc: ArticleService = Depends(service_dep)
):
    """Extract content from a single URL."""
    try:
        start_time = time.time()

        result = await svc.extract_service.robust_extract(str(request.url))

        extraction_time = time.time() - start_time

        text = result.get("text") or ""
        final_url = result.get("final_url") or str(request.url)
        title = result.get("title") or "Untitled"

        if not text or len(text.split()) < request.min_words:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient content extracted (minimum {request.min_words} words required)"
            )

        bucket_key = await async_upload_text(text.encode('utf-8'))

        from urllib.parse import urlparse
        domain = urlparse(final_url).netloc.replace('www.', '')

        word_count = len(text.split())

        metadata = ExtractionMetadata(
            domain=domain,
            extraction_method="trafilatura",  # TODO: track actual method used
            extraction_time_seconds=extraction_time,
            word_count=word_count,
            published_date=result.get("last_modified"),
            author=None  # TODO: extract author if available
        )

        return ExtractResponse(
            success=True,
            url=str(request.url),
            final_url=final_url,
            title=title,
            content=text,
            bucket_key=bucket_key,
            metadata=metadata
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Extraction failed for {request.url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {str(e)}"
        )


@router.post("/extract-candidates", response_model=ExtractCandidatesResponse)
async def extract_candidates(
    topic_id: str = Query(..., description="Topic identifier"),
    max_concurrent: int = Query(3, ge=1, le=10, description="Parallel extraction limit"),
    skip_existing: bool = Query(True, description="Skip if article already exists"),
    svc: ArticleService = Depends(service_dep)
):
    """Extract content from curated candidates for a topic."""
    try:
        start_time = time.time()

        candidates = await svc.candidate_repo.get_candidates_for_extraction(topic_id)

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No candidates marked for extraction for topic {topic_id}"
            )

        extracted_articles = []
        failed_extractions = []

        for candidate in candidates:
            try:
                if skip_existing:
                    existing = await svc.article_repo.get_by_url(candidate.url)
                    if existing:
                        logger.info(f"Skipping existing article: {candidate.url}")
                        extracted_articles.append(ExtractedArticle(
                            article_id=str(existing.id),
                            candidate_id=str(candidate.id),
                            url=existing.url,
                            title=existing.title or "Untitled",
                            word_count=len(existing.raw_text_preview.split()) if existing.raw_text_preview else 0,
                            bucket_key=existing.bucket_key
                        ))
                        continue

                result = await svc.extract_service.robust_extract(candidate.url)

                text = result.get("text") or ""
                final_url = result.get("final_url") or candidate.url
                title = result.get("title") or candidate.title or "Untitled"

                if not text or len(text.split()) < 60:
                    logger.warning(f"Insufficient content for {candidate.url}")
                    failed_extractions.append(FailedExtraction(
                        candidate_id=str(candidate.id),
                        url=candidate.url,
                        error="Insufficient content"
                    ))
                    continue

                bucket_key = await async_upload_text(text.encode('utf-8'))

                article_data = ArticleCreate(
                    url=final_url,
                    title=title,
                    source=f"scout_{candidate.source_provider}",
                    published_at=candidate.pub_date_if_available,
                    raw_text_preview=text[:500],
                    bucket_key=bucket_key,
                    status="ingested"
                )

                article = await svc.article_repo.create_article(article_data)

                word_count = len(text.split())

                extracted_articles.append(ExtractedArticle(
                    article_id=str(article.id),
                    candidate_id=str(candidate.id),
                    url=article.url,
                    title=article.title or "Untitled",
                    word_count=word_count,
                    bucket_key=bucket_key
                ))

                logger.info(f"Successfully extracted: {article.title}")

            except Exception as e:
                logger.error(f"Error extracting {candidate.url}: {e}")
                failed_extractions.append(FailedExtraction(
                    candidate_id=str(candidate.id),
                    url=candidate.url,
                    error=str(e)
                ))

        extraction_time = time.time() - start_time

        return ExtractCandidatesResponse(
            topic_id=topic_id,
            candidates_selected=len(candidates),
            articles_extracted=len(extracted_articles),
            extraction_failures=len(failed_extractions),
            extraction_time_seconds=extraction_time,
            extracted_articles=extracted_articles,
            failed_extractions=failed_extractions
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch extraction failed: {str(e)}"
        )

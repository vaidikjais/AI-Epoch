"""Articles controller — article CRUD operations."""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.article_service import ArticleService
from app.schemas.article_schema import ArticleIn, ArticleOut, ArticleListResponse
from app.utils.s3_utils import async_download_text
from app.utils.logger import get_logger

logger = get_logger("articles_controller")

router = APIRouter(prefix="/articles", tags=["Articles"])


def service_dep(db: AsyncSession = Depends(get_session)) -> ArticleService:
    return ArticleService(db)


@router.post("", response_model=ArticleOut, status_code=status.HTTP_201_CREATED)
async def create_article(
    data: ArticleIn,
    response: Response,
    svc: ArticleService = Depends(service_dep)
):
    """Ingest a single article by URL (idempotent)."""
    try:
        existing_article = await svc.article_repo.get_by_url(str(data.url))

        article = await svc.ingest_single_url(data.url)

        if not article:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to ingest article"
            )

        if existing_article:
            response.status_code = status.HTTP_200_OK
        else:
            response.status_code = status.HTTP_201_CREATED

        return article

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating article: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error ingesting article: {str(e)}"
        )


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Items to skip (for pagination)"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    svc: ArticleService = Depends(service_dep)
):
    """List recent articles with pagination."""
    try:
        articles = await svc.list_recent_articles(limit=limit, offset=offset)

        # TODO: Implement total count query
        total = len(articles)

        return ArticleListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=articles
        )

    except Exception as e:
        logger.error(f"Error listing articles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing articles: {str(e)}"
        )


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(
    article_id: UUID,
    svc: ArticleService = Depends(service_dep)
):
    """Get article by ID."""
    try:
        article = await svc.article_repo.get_by_id(str(article_id))

        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Article {article_id} not found"
            )

        return article

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting article {article_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving article: {str(e)}"
        )


@router.get("/{article_id}/content", response_class=PlainTextResponse)
async def get_article_content(
    article_id: UUID,
    svc: ArticleService = Depends(service_dep)
):
    """Get article full content as plain text from S3."""
    try:
        article = await svc.article_repo.get_by_id(str(article_id))

        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Article {article_id} not found"
            )

        if not article.bucket_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article content not available (no S3 key)"
            )

        try:
            content = await async_download_text(article.bucket_key)
        except Exception as e:
            logger.error(f"Error downloading content from S3: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error retrieving article content from storage"
            )

        if not content:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article content not found in storage"
            )

        return PlainTextResponse(content=content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting article content {article_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving article content: {str(e)}"
        )

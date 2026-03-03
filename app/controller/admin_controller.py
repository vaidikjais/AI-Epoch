"""Admin controller — system health and metrics."""
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.admin_service import AdminService
from app.schemas.admin_schema import (
    HealthResponse,
    MetricsResponse,
    ComponentHealth,
    ArticleMetrics,
    CandidateMetrics,
    PipelineMetrics,
)
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("admin_controller")

router = APIRouter(prefix="/admin", tags=["Admin"])


def service_dep(db: AsyncSession = Depends(get_session)) -> AdminService:
    return AdminService(db)


@router.get("/health", response_model=HealthResponse)
async def health_check(svc: AdminService = Depends(service_dep)):
    """Check system health status."""
    try:
        from datetime import datetime, timezone

        components = {}

        db_start = time.time()
        try:
            from app.models.article_model import Article
            from sqlmodel import select

            statement = select(Article).limit(1)
            result = await svc.db.execute(statement)
            _ = result.scalar_one_or_none()

            db_time = (time.time() - db_start) * 1000
            components["database"] = ComponentHealth(
                status="connected",
                response_time_ms=db_time,
                details={"provider": "postgresql"}
            )
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            components["database"] = ComponentHealth(
                status="disconnected",
                details={"error": str(e)}
            )

        s3_start = time.time()
        try:
            import asyncio
            from app.utils.s3_utils import get_s3_client

            loop = asyncio.get_running_loop()
            s3_client = await loop.run_in_executor(None, get_s3_client)
            await loop.run_in_executor(None, s3_client.list_buckets)

            s3_time = (time.time() - s3_start) * 1000
            components["storage"] = ComponentHealth(
                status="connected",
                response_time_ms=s3_time,
                details={"provider": "minio", "endpoint": settings.S3_ENDPOINT}
            )
        except Exception as e:
            logger.error(f"S3 health check failed: {e}")
            components["storage"] = ComponentHealth(
                status="disconnected",
                details={"error": str(e)}
            )

        overall_status = "healthy"
        if components["database"].status != "connected" or components["storage"].status != "connected":
            overall_status = "degraded"

        return HealthResponse(
            status=overall_status,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            version="1.0.0",
            components=components
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {str(e)}"
        )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(svc: AdminService = Depends(service_dep)):
    """Get system metrics and statistics."""
    try:
        from datetime import datetime, timezone
        from app.models.article_model import Article
        from app.models.candidate_model import ArticleCandidate
        from sqlmodel import select, func

        article_total_stmt = select(func.count()).select_from(Article)
        result = await svc.db.execute(article_total_stmt)
        article_total = result.scalar() or 0

        article_metrics = ArticleMetrics(
            total=article_total,
            ingested_today=0,
            by_status={}
        )

        candidate_total_stmt = select(func.count()).select_from(ArticleCandidate)
        result = await svc.db.execute(candidate_total_stmt)
        candidate_total = result.scalar() or 0

        candidate_metrics = CandidateMetrics(
            total=candidate_total,
            by_topic={}
        )

        pipeline_metrics = PipelineMetrics(
            total_runs=0,
            successful_runs=0,
            failed_runs=0,
            success_rate=0.0,
            avg_duration_seconds=0.0
        )

        return MetricsResponse(
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            articles=article_metrics,
            candidates=candidate_metrics,
            pipelines=pipeline_metrics,
            additional_stats={}
        )

    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving metrics: {str(e)}"
        )

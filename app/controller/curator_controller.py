"""Curator controller — article scoring, filtering, and selection."""
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.article_service import ArticleService
from app.services.curator_service import CuratorService
from app.core.curator.filters import CuratorConfig
from app.schemas.curator_schema import CurateRequest, CurateResponse, CuratedCandidateOut
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("curator_controller")

router = APIRouter(prefix="/curator", tags=["Curator"])


def service_dep(db: AsyncSession = Depends(get_session)) -> ArticleService:
    return ArticleService(db)


@router.post("/curate", response_model=CurateResponse)
async def curate_candidates(
    request: CurateRequest,
    svc: ArticleService = Depends(service_dep)
):
    """Curate article candidates for a topic."""
    try:
        start_time = time.time()

        filters = request.filters if request.filters else {}
        curator_config = CuratorConfig(
            skip_paywalled=filters.skip_paywalled if hasattr(filters, 'skip_paywalled') else settings.CURATOR_SKIP_PAYWALLED,
            min_quality_threshold=filters.min_quality_threshold if hasattr(filters, 'min_quality_threshold') else settings.CURATOR_MIN_QUALITY,
            domain_denylist=filters.domain_denylist if hasattr(filters, 'domain_denylist') else settings.CURATOR_DOMAIN_DENYLIST
        )

        weights = request.weights if request.weights else {}
        weight_quality = weights.quality if hasattr(weights, 'quality') else settings.CURATOR_WEIGHT_QUALITY
        weight_freshness = weights.freshness if hasattr(weights, 'freshness') else settings.CURATOR_WEIGHT_FRESHNESS
        weight_provider = weights.provider if hasattr(weights, 'provider') else settings.CURATOR_WEIGHT_PROVIDER

        curator_service = CuratorService(svc.db, curator_config)

        curated_candidates = await curator_service.curate_candidates(
            topic_id=request.topic_id,
            max_candidates=request.max_candidates,
            weight_quality=weight_quality,
            weight_freshness=weight_freshness,
            weight_provider=weight_provider
        )

        processing_time = time.time() - start_time

        stats = curator_service.get_curation_stats()

        curated_outs = []
        for candidate in curated_candidates:
            curated_outs.append(CuratedCandidateOut(
                id=candidate.id,
                url=candidate.url,
                title=candidate.title,
                curation_score=candidate.curation_score or 0.0,
                quality_score=candidate.semantic_score or 0.0,
                freshness_score=candidate.freshness_score or 0.0,
                provider_score=candidate.provider_score or 0.0,
                curated_rank=candidate.curated_rank or 0,
                reason_notes=candidate.reason_notes,
                pass_to_extractor=candidate.pass_to_extractor
            ))

        return CurateResponse(
            topic_id=request.topic_id,
            candidates_scored=stats.get("total_candidates", 0),
            candidates_filtered=stats.get("filtered_candidates", 0),
            candidates_selected=len(curated_candidates),
            processing_time_seconds=processing_time,
            selected_candidates=curated_outs,
            curation_stats=stats
        )

    except Exception as e:
        logger.error(f"Curation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Curation failed: {str(e)}"
        )

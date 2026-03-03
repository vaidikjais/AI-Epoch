"""Scout controller — article candidate discovery."""
import time
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.article_service import ArticleService
from app.schemas.scout_schema import DiscoverRequest, DiscoverResponse, CandidateListResponse, CandidateOut
from app.utils.logger import get_logger

logger = get_logger("scout_controller")

router = APIRouter(prefix="/scout", tags=["Scout"])


def service_dep(db: AsyncSession = Depends(get_session)) -> ArticleService:
    return ArticleService(db)


@router.post("/discover", response_model=DiscoverResponse)
async def discover_candidates(
    request: DiscoverRequest,
    svc: ArticleService = Depends(service_dep)
):
    """Discover article candidates for a topic."""
    try:
        start_time = time.time()

        candidates = await svc.scout_service.discover_candidates(
            topic_id=request.topic_id,
            topic_query=request.topic_query
        )

        discovery_time = time.time() - start_time

        stats = svc.scout_service.get_discovery_stats()

        candidate_outs = []
        for candidate in candidates:
            candidate_outs.append(CandidateOut(
                id=candidate.id,
                url=candidate.url,
                canonical_url=candidate.canonical_url,
                normalized_domain=candidate.normalized_domain,
                title=candidate.title,
                snippet=candidate.snippet,
                source_provider=candidate.source_provider,
                provider_rank=candidate.provider_rank,
                is_seed_source=candidate.is_seed_source,
                discovered_at=candidate.discovered_at,
                pub_date_if_available=candidate.pub_date_if_available
            ))

        from_seed = sum(1 for c in candidates if c.is_seed_source)
        from_external = len(candidates) - from_seed

        return DiscoverResponse(
            topic_id=request.topic_id,
            topic_query=request.topic_query,
            total_discovered=len(candidates),
            from_seed_sources=from_seed,
            from_external_sources=from_external,
            discovery_time_seconds=discovery_time,
            candidates=candidate_outs,
            stats=stats
        )

    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Discovery failed: {str(e)}"
        )


@router.get("/candidates", response_model=CandidateListResponse)
async def get_candidates(
    topic_id: str = Query(..., description="Topic identifier"),
    limit: int = Query(50, ge=1, le=200, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    svc: ArticleService = Depends(service_dep)
):
    """Get all candidates for a topic with pagination."""
    try:
        candidates = await svc.candidate_repo.list_by_topic(
            topic_id=topic_id,
            limit=limit,
            offset=offset
        )

        candidate_outs = []
        for candidate in candidates:
            candidate_outs.append(CandidateOut(
                id=candidate.id,
                url=candidate.url,
                canonical_url=candidate.canonical_url,
                normalized_domain=candidate.normalized_domain,
                title=candidate.title,
                snippet=candidate.snippet,
                source_provider=candidate.source_provider,
                provider_rank=candidate.provider_rank,
                is_seed_source=candidate.is_seed_source,
                discovered_at=candidate.discovered_at,
                pub_date_if_available=candidate.pub_date_if_available
            ))

        total = await svc.candidate_repo.count_by_topic(topic_id)

        return CandidateListResponse(
            topic_id=topic_id,
            total=total,
            limit=limit,
            offset=offset,
            items=candidate_outs
        )

    except Exception as e:
        logger.error(f"Error getting candidates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving candidates: {str(e)}"
        )

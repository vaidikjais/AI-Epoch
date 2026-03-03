"""Multi-dimensional article scoring for curation."""
import math
from typing import Optional
from datetime import datetime, timezone

from app.utils.logger import get_logger

logger = get_logger("curator_scoring")


def calculate_freshness_score(
    pub_date: Optional[datetime],
    discovered_at: datetime,
    lambda_days: int = 3
) -> float:
    """Exponential decay: score = exp(-(age_days / lambda_days))."""
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        date_to_use = pub_date if pub_date else discovered_at

        if date_to_use.tzinfo is not None:
            date_to_use = date_to_use.replace(tzinfo=None)

        age_days = (now - date_to_use).total_seconds() / 86400
        score = math.exp(-age_days / lambda_days)
        return max(0.0, min(1.0, score))

    except Exception as e:
        logger.error(f"Error calculating freshness score: {e}")
        return 0.6


def calculate_provider_score(
    provider: str,
    rank: Optional[int],
    is_seed: bool,
    max_rank: int = 20
) -> float:
    try:
        score = 0.0

        if rank is not None and provider in ["tavily", "serpapi", "pse"]:
            normalized_rank = max(1, min(rank, max_rank))
            score = 1.0 - ((normalized_rank - 1) / (max_rank - 1))
        elif is_seed:
            score = 0.6
        else:
            score = 0.5

        if is_seed:
            score = min(1.0, score + 0.05)

        return max(0.0, min(1.0, score))

    except Exception as e:
        logger.error(f"Error calculating provider score: {e}")
        return 0.5


def calculate_composite_score(
    quality_score: float,
    freshness_score: float,
    provider_score: float,
    weight_quality: float = 0.60,
    weight_freshness: float = 0.25,
    weight_provider: float = 0.15,
    domain: Optional[str] = None,
    pub_date: Optional[datetime] = None
) -> float:
    """Weighted composite from 3 dimensions: LLM quality, freshness, provider."""
    try:
        total_weight = weight_quality + weight_freshness + weight_provider
        if total_weight == 0:
            return 0.0

        w_q = weight_quality / total_weight
        w_f = weight_freshness / total_weight
        w_p = weight_provider / total_weight

        score = w_q * quality_score + w_f * freshness_score + w_p * provider_score

        if domain and pub_date:
            try:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if pub_date.tzinfo is not None:
                    pub_date = pub_date.replace(tzinfo=None)
                hours_old = (now - pub_date).total_seconds() / 3600
                if hours_old < 24:
                    boost = 0.10 * (1 - hours_old / 24)
                    score = min(1.0, score + boost)
                    logger.debug(f"Recency boost for {domain}: +{boost:.3f} ({hours_old:.1f}h old)")
            except Exception:
                pass

        return max(0.0, min(1.0, score))

    except Exception as e:
        logger.error(f"Error calculating composite score: {e}")
        return 0.0


def build_reason_notes(
    quality_score: float,
    freshness_score: float,
    provider_score: float,
    composite_score: float
) -> str:
    notes_parts = []

    if composite_score >= 0.8:
        notes_parts.append("Excellent candidate")
    elif composite_score >= 0.6:
        notes_parts.append("Good candidate")
    elif composite_score >= 0.4:
        notes_parts.append("Moderate candidate")
    else:
        notes_parts.append("Weak candidate")

    score_parts = []

    if quality_score >= 0.7:
        score_parts.append(f"high quality ({quality_score:.2f})")
    elif quality_score <= 0.3:
        score_parts.append(f"low quality ({quality_score:.2f})")

    if freshness_score >= 0.8:
        score_parts.append(f"very fresh ({freshness_score:.2f})")
    elif freshness_score <= 0.3:
        score_parts.append(f"old ({freshness_score:.2f})")

    if score_parts:
        notes_parts.append("; ".join(score_parts))

    notes_parts.append(f"[score: {composite_score:.3f}]")

    return ". ".join(notes_parts)

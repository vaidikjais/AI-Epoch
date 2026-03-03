"""Unit tests for app.core.curator.scoring."""
from datetime import datetime, timezone, timedelta
import pytest

from app.core.curator import scoring


def test_calculate_freshness_score_recent_date_gets_high_score():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_date = now - timedelta(hours=6)
    discovered_at = now - timedelta(hours=1)
    score = scoring.calculate_freshness_score(pub_date, discovered_at, lambda_days=3)
    assert score > 0.8


def test_calculate_freshness_score_old_date_gets_low_score():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_date = now - timedelta(days=10)
    discovered_at = now - timedelta(days=9)
    score = scoring.calculate_freshness_score(pub_date, discovered_at, lambda_days=3)
    assert score < 0.15


def test_calculate_freshness_score_none_pub_date_uses_discovered_at():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    discovered_at = now - timedelta(days=5)
    score = scoring.calculate_freshness_score(None, discovered_at, lambda_days=3)
    assert 0.1 < score < 0.35


def test_calculate_freshness_score_returns_06_on_error():
    invalid_discovered_at = 12345
    score = scoring.calculate_freshness_score(None, invalid_discovered_at, lambda_days=3)
    assert score == 0.6


def test_calculate_provider_score_rank1_tavily_gives_near_1():
    score = scoring.calculate_provider_score("tavily", rank=1, is_seed=False, max_rank=20)
    assert abs(score - 1.0) < 0.01


def test_calculate_provider_score_rank20_tavily_gives_near_0():
    score = scoring.calculate_provider_score("tavily", rank=20, is_seed=False, max_rank=20)
    assert abs(score - 0.0) < 0.01


def test_calculate_provider_score_seed_source_gets_065():
    score = scoring.calculate_provider_score("seed", rank=None, is_seed=True, max_rank=20)
    assert abs(score - 0.65) < 0.01


def test_calculate_provider_score_non_seed_non_ranked_gets_05():
    score = scoring.calculate_provider_score("other", rank=None, is_seed=False, max_rank=20)
    assert abs(score - 0.5) < 0.01


def test_calculate_composite_score_all_ones_gives_one():
    score = scoring.calculate_composite_score(
        quality_score=1.0,
        freshness_score=1.0,
        provider_score=1.0
    )
    assert abs(score - 1.0) < 0.01


def test_calculate_composite_score_uniform_value():
    # 0.60*0.8 + 0.25*0.8 + 0.15*0.8 = 0.8
    score = scoring.calculate_composite_score(
        quality_score=0.8,
        freshness_score=0.8,
        provider_score=0.8
    )
    assert abs(score - 0.8) < 0.01


def test_calculate_composite_score_zero_weights_returns_0():
    score = scoring.calculate_composite_score(
        quality_score=1.0,
        freshness_score=1.0,
        provider_score=1.0,
        weight_quality=0.0,
        weight_freshness=0.0,
        weight_provider=0.0
    )
    assert score == 0.0


def test_build_reason_notes_high_composite_gives_excellent_candidate():
    notes = scoring.build_reason_notes(
        quality_score=0.9,
        freshness_score=0.9,
        provider_score=0.9,
        composite_score=0.85
    )
    assert "Excellent candidate" in notes


def test_build_reason_notes_low_composite_gives_weak_candidate():
    notes = scoring.build_reason_notes(
        quality_score=0.2,
        freshness_score=0.2,
        provider_score=0.2,
        composite_score=0.25
    )
    assert "Weak candidate" in notes

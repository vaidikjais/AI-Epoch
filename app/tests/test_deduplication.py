"""Unit tests for app.core.curator.deduplication."""
import pytest

from app.core.curator.deduplication import (
    canonicalize_url,
    fuzzy_title_similarity,
    find_duplicates,
)


def test_canonicalize_url_removes_utm_params():
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&page=2"
    result = canonicalize_url(url)
    assert "utm_source" not in result
    assert "utm_medium" not in result
    assert "page=2" in result


def test_canonicalize_url_removes_www_prefix():
    url = "https://www.example.com/article"
    result = canonicalize_url(url)
    assert "www." not in result
    assert "example.com" in result


def test_canonicalize_url_removes_trailing_slash():
    url = "https://example.com/article/"
    result = canonicalize_url(url)
    assert not result.endswith("/") or result == "https://example.com/"


def test_canonicalize_url_removes_fragment():
    url = "https://example.com/article#section1"
    result = canonicalize_url(url)
    assert "#" not in result


def test_canonicalize_url_preserves_non_tracking_params():
    url = "https://example.com/article?id=123&page=2"
    result = canonicalize_url(url)
    assert "id=123" in result
    assert "page=2" in result


def test_fuzzy_title_similarity_exact_match_returns_1():
    assert fuzzy_title_similarity("OpenAI releases GPT-4", "OpenAI releases GPT-4") == 1.0


def test_fuzzy_title_similarity_similar_titles_return_high():
    score = fuzzy_title_similarity(
        "OpenAI releases new GPT model",
        "OpenAI releases new GPT 4 model"
    )
    assert score > 0.85


def test_fuzzy_title_similarity_different_titles_return_low():
    score = fuzzy_title_similarity(
        "OpenAI releases GPT-4",
        "Tesla stock price surges"
    )
    assert score < 0.5


def test_fuzzy_title_similarity_none_empty_returns_0():
    assert fuzzy_title_similarity(None, "Some title") == 0.0
    assert fuzzy_title_similarity("Title", None) == 0.0
    assert fuzzy_title_similarity("", "Title") == 0.0
    assert fuzzy_title_similarity("Title", "") == 0.0


def test_find_duplicates_no_duplicates_returns_empty(make_candidate):
    c1 = make_candidate(
        url="https://example.com/article1",
        title="Article One"
    )
    c2 = make_candidate(
        url="https://example.com/article2",
        title="Article Two"
    )
    duplicates = find_duplicates([c1, c2])
    assert duplicates == {}


def test_find_duplicates_url_duplicate_identifies_it(make_candidate):
    base_url = "https://example.com/same-article"
    c1 = make_candidate(
        url=base_url,
        title="Same Article",
        canonical_url=base_url
    )
    c2 = make_candidate(
        url=base_url + "?utm_source=twitter",
        title="Same Article",
        canonical_url=base_url
    )
    duplicates = find_duplicates([c1, c2])
    assert len(duplicates) == 1
    # One of them should be marked as duplicate of the other
    assert any(
        id1 in duplicates and duplicates[id1] == id2
        for id1 in [c1.id, c2.id] for id2 in [c1.id, c2.id] if id1 != id2
    )


def test_find_duplicates_similar_titles_identifies_duplicate(make_candidate):
    c1 = make_candidate(
        url="https://example.com/article-a",
        title="OpenAI releases new GPT model for developers"
    )
    c2 = make_candidate(
        url="https://example.com/article-b",
        title="OpenAI releases new GPT model for developers today"
    )
    duplicates = find_duplicates(
        [c1, c2],
        title_similarity_threshold=0.85
    )
    assert len(duplicates) == 1

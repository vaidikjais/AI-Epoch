"""URL canonicalization and duplicate candidate detection."""
import difflib
from typing import List, Dict
from uuid import UUID
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from app.models.candidate_model import ArticleCandidate
from app.utils.logger import get_logger

logger = get_logger("curator_deduplication")


def canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        
        query_params = parse_qs(parsed.query)
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', 'ref', 'source', 'campaign', 'medium',
            '_ga', '_gl', 'mc_cid', 'mc_eid'
        }
        
        filtered_params = {k: v for k, v in query_params.items() if k not in tracking_params}
        new_query = urlencode(filtered_params, doseq=True)
        
        normalized_netloc = parsed.netloc.lower()
        if normalized_netloc.startswith('www.'):
            normalized_netloc = normalized_netloc[4:]
        
        normalized_path = parsed.path
        if normalized_path != '/' and normalized_path.endswith('/'):
            normalized_path = normalized_path.rstrip('/')
        
        canonical = urlunparse((
            parsed.scheme.lower() if parsed.scheme else 'https',
            normalized_netloc,
            normalized_path,
            parsed.params,
            new_query,
            ''
        ))
        
        return canonical
        
    except Exception as e:
        logger.warning(f"Failed to canonicalize URL {url}: {e}")
        return url


def fuzzy_title_similarity(title1: str, title2: str) -> float:
    if not title1 or not title2:
        return 0.0
    
    try:
        t1_normalized = title1.lower().strip()
        t2_normalized = title2.lower().strip()
        
        if t1_normalized == t2_normalized:
            return 1.0
        
        similarity = difflib.SequenceMatcher(None, t1_normalized, t2_normalized).ratio()
        return similarity
        
    except Exception as e:
        logger.warning(f"Error calculating title similarity: {e}")
        return 0.0


def find_duplicates(
    candidates: List[ArticleCandidate],
    url_similarity_threshold: float = 1.0,
    title_similarity_threshold: float = 0.78
) -> Dict[UUID, UUID]:
    """Returns mapping of duplicate_id -> keep_id."""
    duplicates = {}
    seen_urls = {}
    seen_titles = {}
    
    for candidate in candidates:
        canonical = candidate.canonical_url or canonicalize_url(candidate.url)
        
        if canonical in seen_urls:
            existing_id = seen_urls[canonical]
            existing = next((c for c in candidates if c.id == existing_id), None)
            
            if existing:
                if _should_keep_over(candidate, existing):
                    duplicates[existing_id] = candidate.id
                    seen_urls[canonical] = candidate.id
                    if existing.title:
                        old_key = existing.title.lower().strip()
                        if old_key in seen_titles:
                            seen_titles[old_key] = candidate.id
                else:
                    duplicates[candidate.id] = existing_id
                    continue
        else:
            seen_urls[canonical] = candidate.id
        
        if candidate.title:
            title_normalized = candidate.title.lower().strip()
            
            found_similar = False
            for seen_title, seen_id in list(seen_titles.items()):
                similarity = fuzzy_title_similarity(title_normalized, seen_title)
                
                if similarity >= title_similarity_threshold:
                    existing = next((c for c in candidates if c.id == seen_id), None)
                    
                    if existing and existing.id != candidate.id:
                        if _should_keep_over(candidate, existing):
                            duplicates[seen_id] = candidate.id
                            del seen_titles[seen_title]
                            seen_titles[title_normalized] = candidate.id
                        else:
                            duplicates[candidate.id] = seen_id
                        
                        found_similar = True
                        break
            
            if not found_similar and candidate.id not in duplicates:
                seen_titles[title_normalized] = candidate.id
    
    logger.info(f"Found {len(duplicates)} duplicate candidates")
    return duplicates


def _should_keep_over(candidate: ArticleCandidate, existing: ArticleCandidate) -> bool:
    """Pick winner by curation score > earlier discovery."""
    if candidate.curation_score is not None and existing.curation_score is not None:
        if candidate.curation_score > existing.curation_score:
            return True
        elif candidate.curation_score < existing.curation_score:
            return False

    if candidate.discovered_at < existing.discovered_at:
        return True

    return False



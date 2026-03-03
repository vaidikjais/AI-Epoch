"""Quality and safety filtering for article candidates."""
import re
from typing import Tuple
from datetime import datetime, timezone
from app.models.candidate_model import ArticleCandidate
from app.utils.logger import get_logger

logger = get_logger("curator_filters")

PAYWALLED_DOMAINS = frozenset({
    "wsj.com", "ft.com", "nytimes.com", "bloomberg.com",
    "economist.com", "theinformation.com", "theathletic.com",
})


class CuratorConfig:
    def __init__(
        self,
        skip_paywalled: bool = True,
        min_quality_threshold: float = 0.3,
        min_title_length: int = 15,
        min_snippet_length: int = 20,
        domain_denylist: list = None,
        max_age_days: int = 14
    ):
        self.skip_paywalled = skip_paywalled
        self.min_quality_threshold = min_quality_threshold
        self.min_title_length = min_title_length
        self.min_snippet_length = min_snippet_length
        self.domain_denylist = domain_denylist or []
        self.max_age_days = max_age_days


async def should_filter_out(
    candidate: ArticleCandidate,
    config: CuratorConfig,
    authority_repo=None,
) -> Tuple[bool, str]:
    if config.max_age_days and candidate.pub_date_if_available:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            pub_date = candidate.pub_date_if_available
            if pub_date.tzinfo is not None:
                pub_date = pub_date.replace(tzinfo=None)
            age_days = (now - pub_date).total_seconds() / 86400
            if age_days > config.max_age_days:
                logger.info(f"Filtering old article ({age_days:.1f} days old): {candidate.url[:80]}")
                return (True, f"Article too old: {age_days:.1f} days (max: {config.max_age_days})")
        except Exception as e:
            logger.debug(f"Could not check age for {candidate.url}: {e}")

    if config.skip_paywalled:
        domain = (candidate.normalized_domain or "").lower()
        if any(pw in domain for pw in PAYWALLED_DOMAINS):
            return (True, f"Paywalled domain: {candidate.normalized_domain}")

    if candidate.normalized_domain in config.domain_denylist:
        logger.info(f"Filtering denylisted domain: {candidate.normalized_domain}")
        return (True, f"Domain in denylist: {candidate.normalized_domain}")
    
    # Also check substring matches for subdomains/variations
    for denied in config.domain_denylist:
        if denied in (candidate.normalized_domain or ""):
            logger.info(f"Filtering domain containing '{denied}': {candidate.normalized_domain}")
            return (True, f"Domain matches denylist pattern: {denied}")
    
    if candidate.title:
        title_words = len(candidate.title.split())
        if title_words < config.min_title_length / 5:
            return (True, f"Title too short: {title_words} words")
    else:
        return (True, "Missing title")
    
    if candidate.snippet:
        snippet_words = len(candidate.snippet.split())
        if snippet_words < config.min_snippet_length / 5:
            logger.debug(f"Candidate {candidate.url} has short snippet but not filtering")
    
    if candidate.semantic_score is not None:
        if candidate.semantic_score < config.min_quality_threshold:
            return (
                True,
                f"Low quality score ({candidate.semantic_score:.2f})"
            )
    
    blocked_patterns = [
        '403', '404', '500',
        '/error/', '/blocked/', '/unavailable/'
    ]
    url_lower = candidate.url.lower()
    for pattern in blocked_patterns:
        if pattern in url_lower:
            return (True, f"URL contains error pattern: {pattern}")
    
    suspicious_extensions = [
        '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.zip',
        '.exe', '.dmg', '.pkg'
    ]
    for ext in suspicious_extensions:
        if url_lower.endswith(ext):
            return (True, f"Suspicious file extension: {ext}")
    
    if not is_likely_article_url(candidate.url):
        return (True, f"URL appears to be a non-article page (category/tag/label)")
    
    return (False, "")


def is_likely_article_url(url: str) -> bool:
    """Heuristic check: filters out video platforms, social media, and non-article pages."""
    url_lower = url.lower()
    
    video_domains = [
        'youtube.com', 'youtu.be', 'vimeo.com', 
        'dailymotion.com', 'twitch.tv', 'tiktok.com'
    ]
    if any(domain in url_lower for domain in video_domains):
        logger.info(f"Filtering video platform URL: {url[:100]}")
        return False
    
    excluded_social_domains = [
        'facebook.com', 'fb.com', 'fb.watch',
        'linkedin.com', 'instagram.com'
    ]
    if any(domain in url_lower for domain in excluded_social_domains):
        logger.info(f"Filtering social media URL: {url[:100]}")
        return False
    
    positive_patterns = [
        '/blog/', '/post/', '/article/', '/news/', '/story/',
        '/research/', '/paper/', '/publication/', '/report/'
    ]
    
    negative_patterns = [
        '/tag/', '/tags/', '/category/', '/categories/', '/label/',
        '/author/', '/authors/', '/about', '/contact',
        '/privacy', '/terms', '/search', '/archive',
        '/rss', '/feed', '/api/', '/login', '/signup'
    ]
    
    has_positive = any(pattern in url_lower for pattern in positive_patterns)
    has_negative = any(pattern in url_lower for pattern in negative_patterns)
    has_date_pattern = bool(re.search(r'/\d{4}/\d{2}/', url_lower))
    has_long_slug = len(url_lower.split('/')[-1]) > 15
    
    if has_negative:
        return False
    
    if has_positive or has_date_pattern or has_long_slug:
        return True
    
    return True



"""Scout Service - Article discovery and candidate management."""
from __future__ import annotations

import re
import time
import json
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime, timezone

import httpx
import feedparser
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.search_adapters.tavily_adapter import TavilyAdapter
from app.repository.candidate_repository import ArticleCandidateRepository
from app.schemas.candidate_schema import ArticleCandidateCreate
from app.utils.logger import get_logger

logger = get_logger("scout_service")


class ScoutService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.candidate_repo = ArticleCandidateRepository(db)
        self.tavily_adapter = TavilyAdapter()

        # Lightweight HTTP client for HTML fetching (not content extraction)
        self.http_headers = {
            "User-Agent": "AgenticNewsletterBot/1.0 (+contact:you@example.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        self.stats = {
            "seed_sources_processed": 0,
            "external_sources_processed": 0,
            "total_candidates_discovered": 0,
        }

    async def discover_candidates(self, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        logger.info(f"Starting candidate discovery for topic '{topic_id}' with query '{topic_query}'")
        start_time = time.time()

        all_candidates = []

        self.stats = {
            "seed_sources_processed": 0,
            "external_sources_processed": 0,
            "total_candidates_discovered": 0,
        }

        seed_candidates = await self._discover_from_seed_sources(topic_id, topic_query)
        all_candidates.extend(seed_candidates)
        self.stats["seed_sources_processed"] = len(settings.SEED_SOURCES)

        try:
            hf_candidates = await self._discover_from_hf_daily_papers(topic_id, topic_query)
            all_candidates.extend(hf_candidates)
        except Exception as e:
            logger.warning(f"HF Daily Papers discovery failed: {e}")

        try:
            github_candidates = await self._discover_from_github_trending(topic_id, topic_query)
            all_candidates.extend(github_candidates)
        except Exception as e:
            logger.warning(f"GitHub trending discovery failed: {e}")

        if self.tavily_adapter.is_enabled():
            try:
                external_candidates = await self._discover_from_external_sources(topic_id, topic_query)
                all_candidates.extend(external_candidates)
                self.stats["external_sources_processed"] = 1
            except Exception as e:
                logger.warning(f"External search failed, continuing with seed sources only: {e}")

        normalized_candidates = self._normalize_candidates(all_candidates)
        deduplicated_candidates = self._deduplicate_candidates(normalized_candidates)

        if deduplicated_candidates:
            persisted_candidates = await self.candidate_repo.create_candidates_batch(deduplicated_candidates)
            self.stats["total_candidates_discovered"] = len(persisted_candidates)
        else:
            persisted_candidates = []

        elapsed_time = time.time() - start_time
        logger.info(
            f"Discovery complete: {len(persisted_candidates)} candidates from "
            f"{self.stats['seed_sources_processed']} seed sources, "
            f"{self.stats['external_sources_processed']} external sources, "
            f"took {elapsed_time:.2f}s"
        )

        return persisted_candidates

    async def _discover_from_seed_sources(self, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        logger.info(f"Discovering from {len(settings.SEED_SOURCES)} seed sources")
        candidates = []

        for seed_url in settings.SEED_SOURCES:
            try:
                logger.debug(f"Processing seed source: {seed_url}")
                seed_candidates = await self._extract_article_links(seed_url, topic_id, topic_query)
                candidates.extend(seed_candidates)
                logger.debug(f"Found {len(seed_candidates)} candidates from {seed_url}")
            except Exception as e:
                logger.error(f"Failed to process seed source {seed_url}: {e}")
                continue

        logger.info(f"Discovered {len(candidates)} candidates from seed sources")
        return candidates

    async def _discover_from_external_sources(self, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        logger.info("Discovering from external search providers")
        candidates = []

        try:
            search_results = await self.tavily_adapter.search(topic_query, num=10)
            logger.info(f"Tavily returned {len(search_results)} results")

            for result in search_results:
                url = result.get("url", "") or ""
                title = result.get("title", "") or ""
                snippet = result.get("snippet", "") or ""
                rank = result.get("rank")

                if self._is_article_hub_url(url):
                    # Expand hub/listing page into individual article links
                    try:
                        expanded = await self._extract_article_links(url, topic_id, topic_query)
                        for link in expanded:
                            # Re-mark as Tavily provenance
                            link.source_provider = "tavily"
                            link.is_seed_source = False
                            link.provider_rank = rank
                            candidates.append(link)
                        logger.debug(f"Expanded Tavily hub URL into {len(expanded)} articles: {url}")
                    except Exception as expand_err:
                        logger.warning(f"Failed to expand Tavily hub URL {url}: {expand_err}")
                        continue
                else:
                    candidate = ArticleCandidateCreate(
                        topic_id=topic_id,
                        topic_query=topic_query,
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_provider="tavily",
                        provider_rank=rank,
                        canonical_url=url,
                        normalized_domain="",
                        is_seed_source=False,
                        pass_to_extractor=False,
                    )
                    candidates.append(candidate)

        except Exception as e:
            logger.error(f"Tavily search failed: {e}")

        logger.info(f"Discovered {len(candidates)} candidates from external sources")
        return candidates

    async def _discover_from_hf_daily_papers(self, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        """Fetch community-curated AI papers from Hugging Face Daily Papers API."""
        logger.info("Discovering papers from HuggingFace Daily Papers")
        candidates = []

        try:
            async with httpx.AsyncClient(headers=self.http_headers, timeout=15.0) as client:
                resp = await client.get("https://huggingface.co/api/daily_papers")
                if resp.status_code != 200:
                    logger.warning(f"HF Daily Papers API returned {resp.status_code}")
                    return candidates
                papers = resp.json()

            papers.sort(key=lambda p: p.get("paper", {}).get("upvotes", 0), reverse=True)

            for entry in papers[:15]:
                try:
                    paper = entry.get("paper", {})
                    paper_id = paper.get("id", "")
                    title = entry.get("title") or paper.get("title", "")
                    if not paper_id or not title:
                        continue

                    arxiv_url = f"https://arxiv.org/abs/{paper_id}"
                    ai_summary = paper.get("ai_summary", "")
                    summary = entry.get("summary", "")
                    snippet = ai_summary or summary[:500]

                    pub_date = None
                    pub_str = entry.get("publishedAt") or paper.get("publishedAt", "")
                    if pub_str:
                        try:
                            pub_date = datetime.fromisoformat(
                                pub_str.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        except Exception:
                            pass

                    upvotes = paper.get("upvotes", 0)
                    github_repo = paper.get("githubRepo", "")
                    github_stars = paper.get("githubStars", 0)

                    extra_info = []
                    if upvotes:
                        extra_info.append(f"{upvotes} upvotes on HF")
                    if github_stars:
                        extra_info.append(f"{github_stars} GitHub stars")
                    if extra_info:
                        snippet = f"{snippet} [{', '.join(extra_info)}]"

                    candidate = ArticleCandidateCreate(
                        topic_id=topic_id,
                        topic_query=topic_query,
                        url=arxiv_url,
                        title=title,
                        snippet=snippet,
                        source_provider="hf_papers",
                        provider_rank=None,
                        canonical_url=arxiv_url,
                        normalized_domain="huggingface.co",
                        is_seed_source=False,
                        pass_to_extractor=False,
                        pub_date_if_available=pub_date,
                    )
                    candidates.append(candidate)
                except Exception as e:
                    logger.debug(f"Error parsing HF paper entry: {e}")
                    continue

        except Exception as e:
            logger.error(f"HF Daily Papers discovery failed: {e}")

        logger.info(f"Discovered {len(candidates)} papers from HuggingFace Daily Papers")
        return candidates

    _TRENDING_AI_KEYWORDS = {
        "ai", "ml", "llm", "gpt", "transformer", "neural", "deep-learning",
        "machine-learning", "diffusion", "agent", "rag", "embedding", "nlp",
        "vision", "language-model", "fine-tuning", "fine-tune", "inference",
        "multimodal", "reasoning", "pytorch", "tensorflow", "jax", "mcp",
        "reinforcement-learning", "generative", "stable-diffusion", "chatbot",
        "copilot", "openai", "anthropic", "huggingface", "langchain",
    }

    async def _discover_from_github_trending(self, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        """Scrape actual GitHub trending page for weekly trending AI/ML repos."""
        logger.info("Discovering weekly trending repos from GitHub")
        candidates = []

        try:
            async with httpx.AsyncClient(
                headers=self.http_headers, timeout=15.0, follow_redirects=True
            ) as client:
                resp = await client.get(
                    "https://github.com/trending",
                    params={"since": "weekly", "spoken_language_code": "en"},
                )
                if resp.status_code != 200:
                    logger.warning(f"GitHub trending page returned {resp.status_code}")
                    return candidates
                html = resp.text

            soup = BeautifulSoup(html, "html.parser")
            repo_articles = soup.select("article.Box-row")
            if not repo_articles:
                logger.warning("No repo articles found on GitHub trending page")
                return candidates

            logger.info(f"Found {len(repo_articles)} repos on GitHub trending page")

            for article in repo_articles:
                try:
                    h2 = article.select_one("h2 a")
                    if not h2:
                        continue
                    href = h2.get("href", "").strip()
                    if not href:
                        continue
                    full_name = href.strip("/")
                    repo_url = f"https://github.com/{full_name}"

                    desc_el = article.select_one("p")
                    description = desc_el.get_text(strip=True) if desc_el else ""

                    stars_el = article.select_one("a[href$='/stargazers']")
                    total_stars = 0
                    if stars_el:
                        stars_text = stars_el.get_text(strip=True).replace(",", "")
                        try:
                            total_stars = int(stars_text)
                        except ValueError:
                            pass

                    weekly_stars = 0
                    span_els = article.select("span.d-inline-block.float-sm-right")
                    if not span_els:
                        span_els = article.select("span.float-sm-right")
                    for span in span_els:
                        text = span.get_text(strip=True)
                        if "stars" in text.lower():
                            nums = re.findall(r"[\d,]+", text)
                            if nums:
                                try:
                                    weekly_stars = int(nums[0].replace(",", ""))
                                except ValueError:
                                    pass

                    lang_el = article.select_one("[itemprop='programmingLanguage']")
                    language = lang_el.get_text(strip=True) if lang_el else ""

                    searchable = f"{full_name} {description} {language}".lower()
                    is_ai = any(kw in searchable for kw in self._TRENDING_AI_KEYWORDS)
                    if not is_ai:
                        continue

                    stars_label = f"{total_stars:,} stars"
                    if weekly_stars:
                        stars_label += f", +{weekly_stars:,} this week"
                    snippet = f"{description} [{stars_label}]" if description else f"Trending repo [{stars_label}]"

                    candidate = ArticleCandidateCreate(
                        topic_id=topic_id,
                        topic_query=topic_query,
                        url=repo_url,
                        title=f"{full_name}: {description[:100]}" if description else full_name,
                        snippet=snippet,
                        source_provider="github_trending",
                        provider_rank=None,
                        canonical_url=repo_url,
                        normalized_domain="github.com",
                        is_seed_source=False,
                        pass_to_extractor=False,
                    )
                    candidates.append(candidate)

                    if len(candidates) >= 10:
                        break

                except Exception as e:
                    logger.debug(f"Error parsing trending repo article: {e}")
                    continue

        except Exception as e:
            logger.error(f"GitHub trending discovery failed: {e}")

        logger.info(f"Discovered {len(candidates)} AI/ML trending repos from GitHub")
        return candidates

    def _is_article_hub_url(self, url: str) -> bool:
        """Heuristic to detect listing/tag/home pages that should be expanded into article links."""
        try:
            path = urlparse(url).path.lower()
        except Exception:
            return False

        if not path or path == "/":
            return True

        hub_keywords = [
            "tag", "tags", "category", "categories", "news", "ai",
            "technology", "tech", "blog", "posts", "updates"
        ]

        # Short paths with hub keywords are likely listing pages
        looks_short = len(path.strip("/").split("/")) <= 2
        has_hub_kw = any(k in path for k in hub_keywords)

        # Article-like signals: dated paths or long slugs
        looks_article_like = bool(re.search(r"/\\d{4}/\\d{2}/", path)) or (len(path.split("/")[-1]) >= 15)

        return (looks_short and has_hub_kw) and not looks_article_like

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=10))
    async def _extract_article_links(self, seed_url: str, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        is_rss = any(pattern in seed_url.lower() for pattern in ['/feed', '/rss', '.xml', '.rss', '/atom'])

        if is_rss:
            logger.info(f"Detected RSS feed: {seed_url}")
            return await self._parse_rss_feed(seed_url, topic_id, topic_query)
        else:
            logger.info(f"Parsing as HTML page: {seed_url}")
            return await self._parse_html_page(seed_url, topic_id, topic_query)

    _MAX_ENTRIES_PER_FEED = 20
    _RECENCY_CUTOFF_DAYS = 3

    async def _parse_rss_feed(self, feed_url: str, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        candidates = []
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        try:
            async with httpx.AsyncClient(
                headers=self.http_headers,
                follow_redirects=True,
                timeout=30.0
            ) as client:
                response = await client.get(feed_url)
                response.raise_for_status()
                feed_content = response.text

            logger.debug(f"Fetched RSS feed from {feed_url} ({len(feed_content)} chars)")

            feed = feedparser.parse(feed_content)

            if not feed.entries:
                logger.warning(f"No entries found in RSS feed: {feed_url}")
                return candidates

            logger.info(f"Found {len(feed.entries)} entries in RSS feed")

            skipped_old = 0
            for entry in feed.entries:
                if len(candidates) >= self._MAX_ENTRIES_PER_FEED:
                    break

                try:
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_date = datetime(*entry.updated_parsed[:6])

                    if pub_date:
                        age_days = (now - pub_date).total_seconds() / 86400
                        if age_days > self._RECENCY_CUTOFF_DAYS:
                            skipped_old += 1
                            continue

                    title = entry.get('title', '').strip()
                    if not title:
                        continue

                    url = entry.get('link', '').strip()
                    if not url:
                        continue

                    snippet = ''
                    if hasattr(entry, 'summary'):
                        snippet = re.sub(r'<[^>]+>', ' ', entry.summary)
                        snippet = re.sub(r'\s+', ' ', snippet).strip()[:500]
                    elif hasattr(entry, 'description'):
                        snippet = re.sub(r'<[^>]+>', ' ', entry.description)
                        snippet = re.sub(r'\s+', ' ', snippet).strip()[:500]

                    candidate = ArticleCandidateCreate(
                        topic_id=topic_id,
                        topic_query=topic_query,
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_provider="seed",
                        provider_rank=None,
                        canonical_url=url,
                        normalized_domain="",
                        is_seed_source=True,
                        pub_date_if_available=pub_date,
                        discovered_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        pass_to_extractor=False,
                    )
                    candidates.append(candidate)

                except Exception as e:
                    logger.debug(f"Error parsing RSS entry: {e}")
                    continue

            logger.info(
                f"Extracted {len(candidates)} recent candidates from RSS feed "
                f"(skipped {skipped_old} older than {self._RECENCY_CUTOFF_DAYS}d)"
            )

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching RSS feed {feed_url}: {e}")
        except Exception as e:
            logger.error(f"Error parsing RSS feed {feed_url}: {e}")

        return candidates

    async def _parse_html_page(self, seed_url: str, topic_id: str, topic_query: str) -> List[ArticleCandidateCreate]:
        candidates = []

        try:
            async with httpx.AsyncClient(
                headers=self.http_headers,
                follow_redirects=True,
                http2=False,
                timeout=30.0
            ) as client:
                response = await client.get(seed_url)
                response.raise_for_status()
                html = response.text
                final_url = str(response.url)

            logger.debug(f"Fetched HTML from {seed_url} -> {final_url} ({len(html)} chars)")

            article_links = self._parse_article_links_from_html(html, final_url)

            # Only fetch individual article pages for pub dates on announcement sites
            # (fewer articles, worth the extra requests)
            should_extract_pub_dates = any(
                domain in seed_url.lower()
                for domain in ['anthropic.com', 'openai.com', 'claude.com']
            )

            logger.info(f"Found {len(article_links)} articles from {seed_url}")
            if should_extract_pub_dates:
                logger.info(f"Will extract publication dates from individual article metadata")

            for link_data in article_links:
                pub_date = None

                if should_extract_pub_dates:
                    pub_date = await self._extract_pub_date_from_article_page(link_data["url"])
                    if pub_date:
                        logger.debug(f"Extracted pub date {pub_date.strftime('%Y-%m-%d')} from {link_data['url'][:80]}")

                candidate = ArticleCandidateCreate(
                    topic_id=topic_id,
                    topic_query=topic_query,
                    url=link_data["url"],
                    title=link_data["title"],
                    snippet=link_data.get("snippet", ""),
                    source_provider="seed",
                    provider_rank=None,
                    canonical_url=link_data["url"],
                    normalized_domain="",
                    is_seed_source=True,
                    pub_date_if_available=pub_date,
                    pass_to_extractor=False,
                )
                candidates.append(candidate)

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching {seed_url}: {e}")
        except Exception as e:
            logger.error(f"Error extracting links from {seed_url}: {e}")

        return candidates

    async def _extract_pub_date_from_article_page(self, url: str) -> Optional[datetime]:
        """Extract pub date from article HTML via OG tags, JSON-LD, time elements, or meta tags."""
        try:
            async with httpx.AsyncClient(
                headers=self.http_headers,
                follow_redirects=True,
                timeout=10.0
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

            soup = BeautifulSoup(html, 'html.parser')

            meta_tag = soup.find('meta', property='article:published_time')
            if meta_tag and meta_tag.get('content'):
                date_str = meta_tag['content']
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    pass

            # JSON-LD structured data (used by Anthropic and others)
            script_tags = soup.find_all('script', type='application/ld+json')
            for script in script_tags:
                try:
                    if script.string:
                        data = json.loads(script.string)
                        # Handle both single object and array of objects
                        if isinstance(data, list):
                            data = data[0] if data else {}
                        if isinstance(data, dict):
                            date_str = data.get('datePublished') or data.get('publishedDate')
                            if date_str:
                                return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    continue

            time_tag = soup.find('time', attrs={'datetime': True})
            if time_tag:
                date_str = time_tag['datetime']
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    pass

            meta_tag = soup.find('meta', attrs={'name': 'publication_date'})
            if meta_tag and meta_tag.get('content'):
                date_str = meta_tag['content']
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    pass

            return None

        except Exception as e:
            logger.debug(f"Could not extract pub date from {url[:80]}: {e}")
            return None

    def _parse_article_links_from_html(self, html: str, base_url: str) -> List[Dict[str, str]]:
        logger.debug(f"Parsing HTML from {base_url} ({len(html)} chars)")

        article_links = []

        try:
            cnbc_pattern = r'<a[^>]+href=["\']([^"\']*cnbc\.com/\d{4}/\d{2}/\d{2}/[^"\']*)["\'][^>]*>([^<]*)</a>'
            bbc_pattern = r'<a[^>]+href=["\']([^"\']*bbc\.co[^"\']*(?:innovation|technology|article)[^"\']*)["\'][^>]*>([^<]*)</a>'
            date_pattern = r'<a[^>]+href=["\']([^"\']*/\d{4}/\d{2}/[^"\']*)["\'][^>]*>([^<]*)</a>'
            keyword_pattern = r'<a[^>]+href=["\']([^"\']*(?:blog|article|post|news|research)[^"\']*)["\'][^>]*>([^<]*)</a>'
            long_slug_pattern = r'<a[^>]+href=["\']([^"\']*[a-zA-Z0-9-]{15,}[^"\']*)["\'][^>]*>([^<]*)</a>'
            title_pattern = r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>([^<]{20,})</a>'

            patterns = [
                (cnbc_pattern, "cnbc-specific"),
                (bbc_pattern, "bbc-specific"),
                (date_pattern, "date-based"),
                (keyword_pattern, "keyword-based"),
                (long_slug_pattern, "long-slug"),
                (title_pattern, "title-based")
            ]

            for pattern, pattern_type in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                logger.debug(f"Pattern '{pattern_type}' found {len(matches)} matches")

                for match in matches:
                    href, title = match

                    if not href or href.startswith('#') or href.startswith('javascript:'):
                        continue

                    full_url = urljoin(base_url, href)

                    if full_url == base_url:
                        continue

                    skip_patterns = [
                        '/tag/', '/category/', '/author/', '/about', '/contact',
                        '/privacy', '/terms', '/subscribe', '/newsletter',
                        '/search', '/archive', '/rss', '/feed', '/sitemap',
                        '.pdf', '.jpg', '.png', '.gif', '.css', '.js',
                        'mailto:', 'tel:', 'twitter.com', 'facebook.com', 'linkedin.com',
                        'doomwiki.org', 'wikipedia.org', 'wiktionary.org'
                    ]

                    if any(skip in full_url.lower() for skip in skip_patterns):
                        continue

                    # Trailing-slash-only URLs are likely category pages, not articles
                    if full_url.endswith('/') and not full_url.endswith('//'):
                        continue

                    title = re.sub(r'<[^>]+>', '', title).strip()
                    title = re.sub(r'&[a-zA-Z0-9#]+;', ' ', title)
                    title = re.sub(r'\s+', ' ', title).strip()

                    if (len(title) < 15 or
                        title.lower() in ['read more', 'continue reading', 'view all', 'more', '...', '0', '1', '2', '3', '4', '5']):
                        continue

                    score = self._score_article_link(full_url, title, pattern_type)

                    article_links.append({
                        "url": full_url,
                        "title": title,
                        "snippet": "",
                        "score": score,
                        "pattern": pattern_type
                    })

            seen_urls = set()
            unique_links = []
            for link in article_links:
                if link["url"] not in seen_urls:
                    seen_urls.add(link["url"])
                    unique_links.append(link)

            unique_links.sort(key=lambda x: x["score"], reverse=True)
            unique_links = unique_links[:25]

            logger.debug(f"Found {len(unique_links)} article links from {base_url}")
            return unique_links

        except Exception as e:
            logger.error(f"Error parsing HTML from {base_url}: {e}")
            return []

    def _score_article_link(self, url: str, title: str, pattern_type: str) -> int:
        score = 0

        pattern_scores = {
            "cnbc-specific": 15,
            "bbc-specific": 15,
            "date-based": 10,
            "keyword-based": 8,
            "long-slug": 6,
            "title-based": 4
        }
        score += pattern_scores.get(pattern_type, 0)

        if any(domain in url.lower() for domain in ['cnbc.com', 'bbc.com', 'bbc.co.uk']):
            score += 8

        if re.search(r'/\d{4}/\d{2}/', url):
            score += 5

        if any(keyword in url.lower() for keyword in ['blog', 'article', 'post', 'news', 'research']):
            score += 3

        if len(url.split('/')[-1]) > 20:
            score += 2

        if 20 <= len(title) <= 100:
            score += 2

        ai_keywords = ['ai', 'artificial intelligence', 'machine learning', 'deep learning', 'neural', 'gpt', 'openai', 'anthropic', 'google', 'meta', 'nvidia']
        if any(keyword in title.lower() for keyword in ai_keywords):
            score += 3

        if '/video/' in url.lower():
            score -= 2

        return score

    def _normalize_candidates(self, candidates: List[ArticleCandidateCreate]) -> List[ArticleCandidateCreate]:
        normalized = []

        for candidate in candidates:
            try:
                canonical_url = self._normalize_url(candidate.url)
                normalized_domain = self._extract_domain(canonical_url)

                candidate.canonical_url = canonical_url
                candidate.normalized_domain = normalized_domain

                normalized.append(candidate)

            except Exception as e:
                logger.warning(f"Failed to normalize candidate {candidate.url}: {e}")
                continue

        return normalized

    def _deduplicate_candidates(self, candidates: List[ArticleCandidateCreate]) -> List[ArticleCandidateCreate]:
        seen_urls = set()
        unique_candidates = []

        for candidate in candidates:
            if candidate.canonical_url not in seen_urls:
                seen_urls.add(candidate.canonical_url)
                unique_candidates.append(candidate)
            else:
                logger.debug(f"Duplicate candidate removed: {candidate.canonical_url}")

        logger.info(f"Deduplicated {len(candidates)} candidates to {len(unique_candidates)} unique")
        return unique_candidates

    def _normalize_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)

            # Strip tracking params (utm_*, fbclid, gclid, etc.)
            query_params = parse_qs(parsed.query)
            tracking_params = {
                'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                'fbclid', 'gclid', 'ref', 'source', 'campaign', 'medium'
            }

            filtered_params = {k: v for k, v in query_params.items() if k not in tracking_params}
            new_query = urlencode(filtered_params, doseq=True)

            normalized = urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))

            return normalized

        except Exception as e:
            logger.warning(f"Failed to normalize URL {url}: {e}")
            return url

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            if domain.startswith('www.'):
                domain = domain[4:]

            return domain

        except Exception as e:
            logger.warning(f"Failed to extract domain from {url}: {e}")
            return ""

    def get_discovery_stats(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        return self.stats.copy()

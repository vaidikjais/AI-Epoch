"""Tavily search API adapter for external article discovery."""
from typing import Any, List, Dict, Optional
import httpx
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger("tavily_adapter")


class TavilyAdapter:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.enabled = bool(settings.ENABLE_TAVILY and self.api_key)
        
        if not self.enabled:
            logger.info("Tavily adapter disabled - no API key or ENABLE_TAVILY=False")
        else:
            logger.info("Tavily adapter enabled with API key")

    async def search(self, query: str, num: int = 10) -> List[Dict]:
        if not self.enabled:
            raise RuntimeError("Tavily disabled or missing API key")

        api_url = "https://api.tavily.com/search"
        payload = {
            "query": query,
            "num": min(num, 20),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AgenticNewsletterBot/1.0 (+contact:you@example.com)",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(api_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            logger.error(f"Tavily HTTP error: {e}")
            return []
        except Exception as e:
            logger.error(f"Tavily unexpected error: {e}")
            return []

        results: List[Dict] = []
        for i, item in enumerate(data.get("results", [])):
            results.append({
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("content", item.get("snippet", "")),
                "rank": i + 1,
            })
        logger.info(f"Tavily returned {len(results)} results for '{query}'")
        return results

    async def search_with_filters(self, query: str, num: int = 10, 
                                include_domains: Optional[List[str]] = None,
                                exclude_domains: Optional[List[str]] = None) -> List[Dict]:
        if not self.enabled:
            raise RuntimeError("Tavily disabled or missing API key")
        
        logger.debug(f"Tavily filtered search: '{query}', include: {include_domains}, exclude: {exclude_domains}")
        
        # TODO: pass include/exclude params to Tavily API
        return await self.search(query, num)

    def is_enabled(self) -> bool:
        return self.enabled

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "has_api_key": bool(self.api_key),
            "provider": "tavily",
            "configured": self.enabled,
        }

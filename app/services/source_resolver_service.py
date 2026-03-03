"""Resolves news article URLs to their primary/official source URLs."""
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from app.agents.base_agent import BaseAgent, load_prompt
from app.utils.logger import get_logger

logger = get_logger("source_resolver")

_CONTENT_TRUNCATE_CHARS = 2500


class SourceResolverService:
    
    PRIMARY_DOMAINS = [
        'openai.com', 'anthropic.com', 'deepmind.google', 'deepmind.com',
        'ai.meta.com', 'research.google', 'microsoft.com/research',
        'huggingface.co', 'github.com', 'arxiv.org', 'stability.ai',
        'cohere.com', 'ai.google', 'blog.google', 'nvidia.com',
        'aws.amazon.com/blogs', 'research.ibm.com',
        'apple.com/machine-learning', 'ai.facebook.com',
        'mistral.ai', 'x.ai',
    ]
    
    SECONDARY_DOMAINS = [
        'cnbc.com', 'bbc.com', 'bbc.co.uk', 'techcrunch.com', 
        'venturebeat.com', 'theverge.com', 'arstechnica.com', 
        'technologyreview.com', 'marktechpost.com',
        'reuters.com', 'bloomberg.com', 'wired.com', 'engadget.com',
        'zdnet.com', 'cnet.com', 'theinformation.com'
    ]
    
    def is_secondary_source(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return any(secondary in domain for secondary in self.SECONDARY_DOMAINS)
    
    def is_primary_source(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return any(primary in domain for primary in self.PRIMARY_DOMAINS)
    
    _SKIP_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.ico'}

    def extract_primary_url(self, content: str, article_url: str) -> Tuple[Optional[str], str]:
        if not self.is_secondary_source(article_url):
            return None, self._get_source_label(article_url)

        url_pattern = r'https?://[^\s<>"{}|\\^\[\]`]+'
        found_urls = re.findall(url_pattern, content)

        primary_candidates = []
        for url in found_urls:
            clean_url = url.rstrip('.,;:)').split('#')[0]
            if not self.is_primary_source(clean_url):
                continue
            parsed = urlparse(clean_url)
            if any(parsed.path.lower().endswith(ext) for ext in self._SKIP_EXTENSIONS):
                continue
            primary_candidates.append(clean_url)

        if not primary_candidates:
            logger.debug(f"No primary source found in {urlparse(article_url).netloc} article")
            return None, self._get_source_label(article_url)

        # Prefer URLs with meaningful paths (blog posts/papers) over bare domains
        deep = [u for u in primary_candidates if len(urlparse(u).path.strip('/').split('/')) >= 2]
        best = deep[0] if deep else primary_candidates[0]
        source_label = self._get_source_label(best)

        logger.info(f"Resolved {urlparse(article_url).netloc} -> {urlparse(best).netloc}")
        return best, source_label
    
    def _get_source_label(self, url: str) -> str:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        
        labels = {
            'openai.com': 'OpenAI',
            'anthropic.com': 'Anthropic',
            'deepmind.google': 'DeepMind',
            'deepmind.com': 'DeepMind',
            'ai.meta.com': 'Meta AI',
            'ai.facebook.com': 'Meta AI',
            'huggingface.co': 'Hugging Face',
            'arxiv.org': 'arXiv',
            'github.com': 'GitHub',
            'stability.ai': 'Stability AI',
            'cohere.com': 'Cohere',
            'nvidia.com': 'NVIDIA',
            'research.google': 'Google Research',
            'ai.google': 'Google AI',
            'blog.google': 'Google AI Blog',
            'microsoft.com': 'Microsoft Research',
            'mistral.ai': 'Mistral AI',
            'x.ai': 'xAI',
            'aws.amazon.com': 'AWS',
            'research.ibm.com': 'IBM Research',
            'apple.com': 'Apple',
            'cnbc.com': 'CNBC',
            'bbc.com': 'BBC',
            'bbc.co.uk': 'BBC',
            'techcrunch.com': 'TechCrunch',
            'venturebeat.com': 'VentureBeat',
            'theverge.com': 'The Verge',
            'arstechnica.com': 'Ars Technica',
            'technologyreview.com': 'MIT Technology Review',
            'marktechpost.com': 'MarkTechPost',
            'reuters.com': 'Reuters',
            'bloomberg.com': 'Bloomberg',
            'wired.com': 'Wired',
        }
        
        for key, label in labels.items():
            if key in domain:
                return label
        
        return domain.split('.')[0].title()

    async def resolve_with_llm(self, content: str, article_url: str, title: str = "") -> Tuple[Optional[str], str]:
        """Use LLM to identify the primary source and subject when regex resolution fails."""
        if not self.is_secondary_source(article_url):
            return None, self._get_source_label(article_url)

        source_domain = urlparse(article_url).netloc.replace("www.", "")
        truncated_content = content[:_CONTENT_TRUNCATE_CHARS] if content else ""

        if not truncated_content.strip():
            return None, self._get_source_label(article_url)

        try:
            user_prompt = load_prompt(
                "source_resolver",
                "find_primary_source",
                source_domain=source_domain,
                article_url=article_url,
                article_title=title,
                content=truncated_content,
            )
            system_prompt = "You identify original primary sources and subjects for news articles. Always return JSON."

            agent = BaseAgent(temperature=0.0, max_tokens=256)
            raw = await agent._invoke(system_prompt, user_prompt)
            raw = raw.strip()

            if raw.lower() == "null" or not raw:
                logger.debug(f"LLM returned null for {source_domain}")
                return None, self._get_source_label(article_url)

            parsed = BaseAgent._extract_json(raw)
            if not isinstance(parsed, dict):
                return None, self._get_source_label(article_url)

            primary_url = parsed.get("primary_url")
            subject_label = parsed.get("subject_label", "")
            llm_label = parsed.get("source_label", "")

            if primary_url and isinstance(primary_url, str) and primary_url.startswith("http"):
                known_label = self._get_source_label(primary_url)
                final_label = known_label if known_label != urlparse(primary_url).netloc.split('.')[0].title() else (llm_label or known_label)
                logger.info(f"LLM resolved {source_domain} -> {urlparse(primary_url).netloc} ({final_label})")
                return primary_url, final_label

            if subject_label and subject_label.lower() != source_domain.lower():
                logger.info(f"LLM labelled {source_domain} as '{subject_label}' (no primary URL)")
                return None, subject_label

            return None, self._get_source_label(article_url)

        except Exception as e:
            logger.warning(f"LLM source resolution failed for {article_url}: {e}")
            return None, self._get_source_label(article_url)

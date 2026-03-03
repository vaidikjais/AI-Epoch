"""Application settings and environment variable management."""
from typing import List, Dict
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/newsletter", 
        env="DATABASE_URL", 
        description="PostgreSQL database URL"
    )
    
    POSTGRES_HOST: str = Field(default="localhost", env="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, env="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="newsletter", env="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="postgres", env="POSTGRES_PASSWORD")

    S3_ENDPOINT: str = Field(default="localhost:9000", env="S3_ENDPOINT")
    S3_ACCESS_KEY: str = Field(default="minioadmin", env="S3_ACCESS_KEY")
    S3_SECRET_KEY: str = Field(default="minioadmin", env="S3_SECRET_KEY")
    S3_BUCKET: str = Field(default="articles", env="S3_BUCKET", description="S3/MinIO bucket name")
    S3_SECURE: bool = Field(default=False, env="S3_SECURE", description="Use TLS for S3/MinIO connections")

    NEWSLETTER_TITLE: str = Field(default="AI Newsletter", env="NEWSLETTER_TITLE", description="Newsletter brand name")
    NEWSLETTER_COPYRIGHT: str = Field(default="2025 AI Newsletter", env="NEWSLETTER_COPYRIGHT", description="Copyright line for footer")

    NVIDIA_API_KEY: str = Field(default="", env="NVIDIA_API_KEY")
    OPENAI_API_KEY: str = Field(default="", env="OPENAI_API_KEY")
    GEMINI_API_KEY: str = Field(default="", env="GEMINI_API_KEY")
    LLM_PROVIDER: str = Field(default="gemini", env="LLM_PROVIDER", description="LLM provider: openai, gemini")
    LLM_MODEL: str = Field(default="gemini-1.5-flash", env="LLM_MODEL", description="LLM model name")
    NVIDIA_MODEL: str = Field(default="meta/llama-3.3-70b-instruct", env="NVIDIA_MODEL", description="NVIDIA LLM model name")

    PLAYWRIGHT_ENABLED: bool = Field(default=True, env="PLAYWRIGHT_ENABLED", description="Enable Playwright fallback")

    USER_AGENT: str = Field(default="AgenticNewsletterBot/1.0 (+contact:you@example.com)", env="USER_AGENT", description="User agent for web scraping")
    SCRAPE_TIMEOUT_SECS: int = Field(default=30, env="SCRAPE_TIMEOUT_SECS", description="Timeout for web scraping requests")
    SCRAPE_MIN_WORDS: int = Field(default=120, env="SCRAPE_MIN_WORDS", description="Minimum word count for valid content")

    DEBUG: bool = Field(default=False, env="DEBUG")

    SMTP_HOST: str = Field(default="", env="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, env="SMTP_PORT")
    SMTP_USER: str = Field(default="", env="SMTP_USER")
    SMTP_PASSWORD: str = Field(default="", env="SMTP_PASSWORD")
    SMTP_FROM: str = Field(default="", env="SMTP_FROM")
    SMTP_TLS: bool = Field(default=True, env="SMTP_TLS")

    SERVER_HOST: str = Field(
        default="0.0.0.0", env="SERVER_HOST", description="Host interface to bind the API server on"
    )
    SERVER_PORT: int = Field(
        default=8000, env="SERVER_PORT", description="Port to bind the API server on"
    )

    TAVILY_API_KEY: str = Field(default="", env="TAVILY_API_KEY", description="Tavily API key for search")
    ENABLE_TAVILY: bool = Field(default=False, env="ENABLE_TAVILY", description="Enable Tavily search provider")

    SEED_SOURCES: List[str] = Field(
        default=[
            # News outlets (verified RSS feeds)
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://venturebeat.com/category/ai/feed",
            "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
            "https://www.technologyreview.com/feed/",
            "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
            "https://arstechnica.com/ai/feed/",
            "https://marktechpost.com/feed",
            "https://www.wired.com/feed/rss",
            # AI lab blogs (verified RSS feeds — primary sources)
            "https://openai.com/news/rss.xml",
            "https://blog.google/technology/ai/rss/",
            "https://huggingface.co/blog/feed.xml",
            # Research papers (primary sources)
            "https://rss.arxiv.org/rss/cs.AI",
            "https://rss.arxiv.org/rss/cs.LG",
            "https://rss.arxiv.org/rss/cs.CL",
            # Community / Reddit
            "https://www.reddit.com/r/MachineLearning/.rss",
            "https://www.reddit.com/r/artificial/.rss",
            "https://www.reddit.com/r/LocalLLaMA/.rss",
        ],
        description="Curated AI news sources: outlets, lab blogs, research, community, and Reddit"
    )

    SECTION_TARGETS: Dict[str, int] = Field(
        default={
            "headline": 1,
            "top_news": 3,
            "research": 1,
            "open_source": 2,
            "tools": 2,
            "community": 1,
            "quick_bytes": 3,
        },
        description="Target number of articles per newsletter section"
    )

    PREFERRED_SECTIONS: Dict[str, str] = Field(
        default={
            "arxiv.org": "research",
            "deepmind.google": "research", 
            "research.google": "research",
            "anthropic.com": "top_news",
            "huggingface.co": "research",
            "aws.amazon.com": "top_news",
            "cnbc.com": "top_news",
            "marktechpost.com": "top_news",
            "github.com": "tools",
        },
        description="Preferred section for domains based on content type"
    )

    SECTION_WEIGHTS: Dict[str, Dict[str, float]] = Field(
        default={
            "headline": {"quality": 0.55, "freshness": 0.30, "provider": 0.15},
            "top_news": {"quality": 0.55, "freshness": 0.30, "provider": 0.15},
            "research": {"quality": 0.65, "freshness": 0.20, "provider": 0.15},
            "open_source": {"quality": 0.50, "freshness": 0.35, "provider": 0.15},
            "tools": {"quality": 0.50, "freshness": 0.35, "provider": 0.15},
            "community": {"quality": 0.45, "freshness": 0.40, "provider": 0.15},
            "quick_bytes": {"quality": 0.40, "freshness": 0.45, "provider": 0.15},
        },
        description="Scoring weights per section (quality = LLM-judged holistic quality)"
    )

    CURATOR_TOP_K: int = Field(default=8, env="CURATOR_TOP_K", description="Number of top candidates to select")
    CURATOR_SKIP_PAYWALLED: bool = Field(default=True, env="CURATOR_SKIP_PAYWALLED", description="Skip paywalled content")
    CURATOR_MIN_QUALITY: float = Field(default=0.3, env="CURATOR_MIN_QUALITY", description="Minimum LLM quality score threshold")
    CURATOR_FRESHNESS_LAMBDA_DAYS: int = Field(default=3, env="CURATOR_FRESHNESS_LAMBDA_DAYS", description="Freshness decay parameter in days")
    CURATOR_DOMAIN_DENYLIST: List[str] = Field(
        default=[
            "doomwiki.org", "wikipedia.org", "wiktionary.org", "wikimedia.org",
            "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv", "tiktok.com",
            "facebook.com", "fb.com", "fb.watch", "linkedin.com", "instagram.com"
        ],
        env="CURATOR_DOMAIN_DENYLIST",
        description="List of domains to exclude from curation"
    )
    
    CURATOR_WEIGHT_QUALITY: float = Field(default=0.60, env="CURATOR_WEIGHT_QUALITY", description="LLM quality score weight")
    CURATOR_WEIGHT_FRESHNESS: float = Field(default=0.25, env="CURATOR_WEIGHT_FRESHNESS", description="Freshness score weight")
    CURATOR_WEIGHT_PROVIDER: float = Field(default=0.15, env="CURATOR_WEIGHT_PROVIDER", description="Provider score weight")

    CURATOR_AGENT_MODEL: str = Field(default="", env="CURATOR_AGENT_MODEL", description="Override model for CuratorAgent (falls back to NVIDIA_MODEL)")
    CURATOR_AGENT_TEMPERATURE: float = Field(default=0.2, env="CURATOR_AGENT_TEMPERATURE", description="LLM temperature for CuratorAgent (lower = more consistent)")

    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8", 
        extra="ignore"
    )


settings = Settings()

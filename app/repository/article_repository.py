"""Article repository for article database operations."""
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID
from app.models.article_model import Article
from app.schemas.article_schema import ArticleCreate, ArticleUpdate


class ArticleRepository:
    
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_url(self, url: str) -> Optional[Article]:
        statement = select(Article).where(Article.url == url)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(self, article_id: str) -> Optional[Article]:
        try:
            uuid_obj = UUID(article_id)
            return await self.db.get(Article, uuid_obj)
        except ValueError:
            return None

    async def create_article(self, data: ArticleCreate) -> Article:
        """Returns existing article if URL already exists (upsert-like behavior)."""
        from sqlalchemy.exc import IntegrityError
        from app.utils.logger import get_logger
        logger = get_logger("article_repo")
        
        existing = await self.get_by_url(data.url)
        if existing:
            logger.info(f"Article already exists, returning existing: {data.url}")
            return existing
        
        article = Article(**data.dict())
        self.db.add(article)
        
        try:
            await self.db.commit()
            await self.db.refresh(article)
            return article
        except IntegrityError as e:
            logger.warning(f"Duplicate article detected during commit: {data.url}")
            await self.db.rollback()
            
            existing = await self.get_by_url(data.url)
            if existing:
                logger.info(f"Retrieved existing article after rollback: {data.url}")
                return existing
            
            logger.error(f"Could not find article after duplicate error: {data.url}")
            try:
                existing = await self.get_by_url(data.url)
                if existing:
                    return existing
            except:
                pass
            
            raise e
        except Exception as e:
            await self.db.rollback()
            raise e

    async def list_recent_articles(self, limit: int = 50, offset: int = 0) -> List[Article]:
        statement = select(Article).order_by(Article.ingested_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(statement)
        return result.scalars().all()

    async def update_article(self, article_id: str, data: ArticleUpdate) -> Optional[Article]:
        try:
            uuid_obj = UUID(article_id)
            article = await self.db.get(Article, uuid_obj)
        except ValueError:
            return None
        if not article:
            return None
        
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(article, key, value)
        
        self.db.add(article)
        await self.db.commit()
        await self.db.refresh(article)
        return article

    async def update_article_status(self, article: Article, status: str) -> Article:
        article.status = status
        self.db.add(article)
        await self.db.commit()
        await self.db.refresh(article)
        return article

    async def save_article_draft(self, article: Article, draft_json: dict) -> Article:
        article.draft_json = draft_json
        article.status = "drafted"
        self.db.add(article)
        await self.db.commit()
        await self.db.refresh(article)
        return article

    async def delete_article(self, article_id: str) -> bool:
        try:
            uuid_obj = UUID(article_id)
            article = await self.db.get(Article, uuid_obj)
        except ValueError:
            return False
        if not article:
            return False
        
        await self.db.delete(article)
        await self.db.commit()
        return True

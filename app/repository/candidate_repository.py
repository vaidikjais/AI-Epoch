"""ArticleCandidate repository for candidate database operations."""
from sqlmodel import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from app.models.candidate_model import ArticleCandidate
from app.schemas.candidate_schema import ArticleCandidateCreate, ArticleCandidateUpdate


class ArticleCandidateRepository:
    
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, candidate_id: UUID) -> Optional[ArticleCandidate]:
        try:
            return await self.db.get(ArticleCandidate, candidate_id)
        except Exception:
            return None

    async def get_by_url(self, url: str) -> Optional[ArticleCandidate]:
        statement = select(ArticleCandidate).where(ArticleCandidate.url == url)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_canonical_url(self, canonical_url: str) -> Optional[ArticleCandidate]:
        statement = select(ArticleCandidate).where(ArticleCandidate.canonical_url == canonical_url)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_topic(self, topic_id: str, limit: int = 100, offset: int = 0) -> List[ArticleCandidate]:
        statement = (
            select(ArticleCandidate)
            .where(ArticleCandidate.topic_id == topic_id)
            .order_by(ArticleCandidate.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(statement)
        return result.scalars().all()

    async def list_recent_candidates(self, limit: int = 50, offset: int = 0) -> List[ArticleCandidate]:
        statement = (
            select(ArticleCandidate)
            .order_by(ArticleCandidate.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(statement)
        return result.scalars().all()

    async def create_candidate(self, data: ArticleCandidateCreate) -> ArticleCandidate:
        candidate = ArticleCandidate(**data.model_dump())
        self.db.add(candidate)
        await self.db.commit()
        await self.db.refresh(candidate)
        return candidate

    async def create_candidates_batch(self, candidates_data: List[ArticleCandidateCreate]) -> List[ArticleCandidate]:
        candidates = []
        for data in candidates_data:
            candidate = ArticleCandidate(**data.model_dump())
            merged = await self.db.merge(candidate)
            candidates.append(merged)
        await self.db.commit()
        return candidates

    async def update_candidate(self, candidate_id: UUID, data: ArticleCandidateUpdate) -> Optional[ArticleCandidate]:
        candidate = await self.db.get(ArticleCandidate, candidate_id)
        if not candidate:
            return None
        
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(candidate, key, value)
        
        self.db.add(candidate)
        await self.db.commit()
        await self.db.refresh(candidate)
        return candidate

    async def update_candidates_batch(self, updates: List[Dict[str, Any]]) -> int:
        updated_count = 0
        for update in updates:
            candidate_id = update.get("candidate_id")
            if not candidate_id:
                continue
                
            candidate = await self.db.get(ArticleCandidate, candidate_id)
            if not candidate:
                continue
            
            for key, value in update.items():
                if key != "candidate_id" and hasattr(candidate, key):
                    setattr(candidate, key, value)
            
            self.db.add(candidate)
            updated_count += 1
        
        await self.db.commit()
        return updated_count

    async def mark_candidates_for_extraction(self, candidate_ids: List[UUID], pass_to_extractor: bool = True) -> int:
        statement = (
            select(ArticleCandidate)
            .where(ArticleCandidate.id.in_(candidate_ids))
        )
        result = await self.db.execute(statement)
        candidates = result.scalars().all()
        
        updated_count = 0
        for candidate in candidates:
            candidate.pass_to_extractor = pass_to_extractor
            self.db.add(candidate)
            updated_count += 1
        
        await self.db.commit()
        return updated_count

    async def get_candidates_for_extraction(self, topic_id: str) -> List[ArticleCandidate]:
        statement = (
            select(ArticleCandidate)
            .where(
                and_(
                    ArticleCandidate.topic_id == topic_id,
                    ArticleCandidate.pass_to_extractor == True
                )
            )
            .order_by(ArticleCandidate.curated_rank.asc().nulls_last())
        )
        result = await self.db.execute(statement)
        return result.scalars().all()

    async def get_candidates_by_section(self, topic_id: str, section_label: str) -> List[ArticleCandidate]:
        statement = (
            select(ArticleCandidate)
            .where(
                and_(
                    ArticleCandidate.topic_id == topic_id,
                    ArticleCandidate.section_label == section_label
                )
            )
            .order_by(ArticleCandidate.curation_score.desc().nulls_last())
        )
        result = await self.db.execute(statement)
        return result.scalars().all()

    async def count_by_topic(self, topic_id: str) -> int:
        statement = select(ArticleCandidate).where(ArticleCandidate.topic_id == topic_id)
        result = await self.db.execute(statement)
        return len(result.scalars().all())

    async def count_by_section(self, topic_id: str, section_label: str) -> int:
        statement = select(ArticleCandidate).where(
            and_(
                ArticleCandidate.topic_id == topic_id,
                ArticleCandidate.section_label == section_label
            )
        )
        result = await self.db.execute(statement)
        return len(result.scalars().all())

    async def delete_candidate(self, candidate_id: UUID) -> bool:
        candidate = await self.db.get(ArticleCandidate, candidate_id)
        if not candidate:
            return False
        
        await self.db.delete(candidate)
        await self.db.commit()
        return True

    async def delete_candidates_by_topic(self, topic_id: str) -> int:
        statement = select(ArticleCandidate).where(ArticleCandidate.topic_id == topic_id)
        result = await self.db.execute(statement)
        candidates = result.scalars().all()
        
        deleted_count = 0
        for candidate in candidates:
            await self.db.delete(candidate)
            deleted_count += 1
        
        await self.db.commit()
        return deleted_count

    async def get_duplicate_candidates(self, topic_id: str) -> List[ArticleCandidate]:
        statement = (
            select(ArticleCandidate)
            .where(ArticleCandidate.topic_id == topic_id)
            .order_by(ArticleCandidate.canonical_url, ArticleCandidate.discovered_at.desc())
        )
        result = await self.db.execute(statement)
        return result.scalars().all()
    
    async def get_candidates_by_topic(self, topic_id: str) -> List[ArticleCandidate]:
        """Alias for list_by_topic without pagination."""
        statement = (
            select(ArticleCandidate)
            .where(ArticleCandidate.topic_id == topic_id)
            .order_by(ArticleCandidate.discovered_at.desc())
        )
        result = await self.db.execute(statement)
        return result.scalars().all()
    
    async def get_curated_candidates(self, topic_id: str) -> List[ArticleCandidate]:
        """Alias for get_candidates_for_extraction."""
        return await self.get_candidates_for_extraction(topic_id)

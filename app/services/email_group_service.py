"""Service for managing email groups and resolving recipients."""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_group_model import EmailGroup, EmailGroupMember
from app.utils.logger import get_logger

logger = get_logger("email_group_service")


class EmailGroupService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_group(self, name: str, description: Optional[str] = None) -> EmailGroup:
        group = EmailGroup(name=name.strip(), description=description)
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group)
        logger.info(f"Created email group '{name}' ({group.id})")
        return group

    async def list_groups(self) -> List[dict]:
        stmt = (
            select(
                EmailGroup.id,
                EmailGroup.name,
                EmailGroup.description,
                EmailGroup.created_at,
                func.count(EmailGroupMember.id).label("member_count"),
            )
            .outerjoin(EmailGroupMember, EmailGroup.id == EmailGroupMember.group_id)
            .group_by(EmailGroup.id)
            .order_by(EmailGroup.name)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "member_count": r.member_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def get_group(self, group_id: UUID) -> Optional[dict]:
        group = await self.db.get(EmailGroup, group_id)
        if not group:
            return None

        members_stmt = (
            select(EmailGroupMember)
            .where(EmailGroupMember.group_id == group_id)
            .order_by(EmailGroupMember.email)
        )
        result = await self.db.execute(members_stmt)
        members = result.scalars().all()

        return {
            "id": str(group.id),
            "name": group.name,
            "description": group.description,
            "created_at": group.created_at.isoformat() if group.created_at else None,
            "members": [
                {
                    "id": str(m.id),
                    "email": m.email,
                    "name": m.name,
                    "added_at": m.added_at.isoformat() if m.added_at else None,
                }
                for m in members
            ],
        }

    async def update_group(self, group_id: UUID, name: Optional[str] = None, description: Optional[str] = None) -> Optional[EmailGroup]:
        group = await self.db.get(EmailGroup, group_id)
        if not group:
            return None
        if name is not None:
            group.name = name.strip()
        if description is not None:
            group.description = description
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group)
        return group

    async def delete_group(self, group_id: UUID) -> bool:
        group = await self.db.get(EmailGroup, group_id)
        if not group:
            return False
        await self.db.execute(
            delete(EmailGroupMember).where(EmailGroupMember.group_id == group_id)
        )
        await self.db.delete(group)
        await self.db.flush()
        logger.info(f"Deleted email group '{group.name}' ({group_id})")
        return True

    async def add_members(self, group_id: UUID, emails: List[str]) -> List[EmailGroupMember]:
        group = await self.db.get(EmailGroup, group_id)
        if not group:
            raise ValueError(f"Group {group_id} not found")

        existing_stmt = select(EmailGroupMember.email).where(EmailGroupMember.group_id == group_id)
        result = await self.db.execute(existing_stmt)
        existing_emails = {r.lower() for r in result.scalars().all()}

        added = []
        for email in emails:
            clean = email.strip().lower()
            if clean and clean not in existing_emails:
                member = EmailGroupMember(group_id=group_id, email=clean)
                self.db.add(member)
                added.append(member)
                existing_emails.add(clean)

        if added:
            await self.db.flush()
            for m in added:
                await self.db.refresh(m)
            logger.info(f"Added {len(added)} members to group '{group.name}'")

        return added

    async def remove_member(self, group_id: UUID, member_id: UUID) -> bool:
        stmt = select(EmailGroupMember).where(
            EmailGroupMember.id == member_id,
            EmailGroupMember.group_id == group_id,
        )
        result = await self.db.execute(stmt)
        member = result.scalar_one_or_none()
        if not member:
            return False
        await self.db.delete(member)
        await self.db.flush()
        return True

    async def resolve_recipients(self, group_ids: List[UUID], extra_emails: List[str] | None = None) -> List[str]:
        """Expand group IDs to individual emails, merge with extras, deduplicate."""
        all_emails: set[str] = set()

        if group_ids:
            stmt = select(EmailGroupMember.email).where(
                EmailGroupMember.group_id.in_(group_ids)
            )
            result = await self.db.execute(stmt)
            for email in result.scalars().all():
                all_emails.add(email.strip().lower())

        if extra_emails:
            for email in extra_emails:
                clean = email.strip().lower()
                if clean:
                    all_emails.add(clean)

        resolved = sorted(all_emails)
        logger.info(f"Resolved {len(resolved)} unique recipients from {len(group_ids)} groups + {len(extra_emails or [])} extras")
        return resolved

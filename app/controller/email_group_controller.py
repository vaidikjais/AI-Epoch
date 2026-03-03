"""Email groups controller — CRUD for recipient groups and members."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.email_group_service import EmailGroupService
from app.schemas.email_schema import (
    CreateGroupRequest,
    UpdateGroupRequest,
    GroupResponse,
    GroupDetailResponse,
    AddMembersRequest,
    MemberResponse,
)

router = APIRouter(prefix="/email/groups", tags=["Email Groups"])


def _svc(db: AsyncSession = Depends(get_session)) -> EmailGroupService:
    return EmailGroupService(db)


@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(req: CreateGroupRequest, svc: EmailGroupService = Depends(_svc)):
    try:
        group = await svc.create_group(req.name, req.description)
        return GroupResponse(
            id=str(group.id),
            name=group.name,
            description=group.description,
            member_count=0,
            created_at=group.created_at.isoformat() if group.created_at else None,
        )
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status.HTTP_409_CONFLICT, f"Group '{req.name}' already exists")
        raise


@router.get("/", response_model=List[GroupResponse])
async def list_groups(svc: EmailGroupService = Depends(_svc)):
    groups = await svc.list_groups()
    return [GroupResponse(**g) for g in groups]


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(group_id: UUID, svc: EmailGroupService = Depends(_svc)):
    group = await svc.get_group(group_id)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return GroupDetailResponse(**group)


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(group_id: UUID, req: UpdateGroupRequest, svc: EmailGroupService = Depends(_svc)):
    group = await svc.update_group(group_id, req.name, req.description)
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    groups = await svc.list_groups()
    match = next((g for g in groups if g["id"] == str(group_id)), None)
    return GroupResponse(**(match or {"id": str(group.id), "name": group.name, "description": group.description, "member_count": 0, "created_at": group.created_at.isoformat() if group.created_at else None}))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID, svc: EmailGroupService = Depends(_svc)):
    deleted = await svc.delete_group(group_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")


@router.post("/{group_id}/members", response_model=List[MemberResponse], status_code=status.HTTP_201_CREATED)
async def add_members(group_id: UUID, req: AddMembersRequest, svc: EmailGroupService = Depends(_svc)):
    try:
        members = await svc.add_members(group_id, [str(e) for e in req.emails])
        return [
            MemberResponse(
                id=str(m.id),
                email=m.email,
                name=m.name,
                added_at=m.added_at.isoformat() if m.added_at else None,
            )
            for m in members
        ]
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")


@router.delete("/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: UUID, member_id: UUID, svc: EmailGroupService = Depends(_svc)):
    removed = await svc.remove_member(group_id, member_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.database import get_db
from app.services.consortium_service import process_consortium_evaluation
from app.schemas.consortium_schema import ConsortiumScorecardOutput, ConsortiumMemberCreate
from sqlalchemy import select
import uuid as uuid_mod

router = APIRouter(
    prefix="/cases",
    tags=["Consortium"]
)

@router.post("/{case_id}/consortium/calculate", response_model=ConsortiumScorecardOutput)
async def api_compute_consortium(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Orchestrates the overall evaluation of a group (Consortium).
    Aggregates member scores and calculates risk discount and mutual synergies.
    """
    decision = await process_consortium_evaluation(case_id=case_id, db=db)
    return decision


@router.post("/{case_id}/consortium/members")
async def add_consortium_member(case_id: str, body: ConsortiumMemberCreate, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Add a new member to the consortium for a case."""
    from app.db.models import ConsortiumMember
    member = ConsortiumMember(
        case_id=uuid_mod.UUID(case_id),
        bidder_id=body.bidder_id,
        bidder_name=body.bidder_name,
        role=body.role,
        participation_pct=body.participation_pct,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.patch("/{case_id}/consortium/members/{member_id}")
async def update_consortium_member(case_id: str, member_id: str, body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update an existing consortium member."""
    from app.db.models import ConsortiumMember
    result = await db.execute(
        select(ConsortiumMember).where(
            ConsortiumMember.id == uuid_mod.UUID(member_id),
            ConsortiumMember.case_id == uuid_mod.UUID(case_id),
        )
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consortium member not found")
    for key, value in body.items():
        if hasattr(member, key):
            setattr(member, key, value)
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/{case_id}/consortium/members/{member_id}", status_code=204)
async def delete_consortium_member(case_id: str, member_id: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Remove a consortium member."""
    from app.db.models import ConsortiumMember
    result = await db.execute(
        select(ConsortiumMember).where(
            ConsortiumMember.id == uuid_mod.UUID(member_id),
            ConsortiumMember.case_id == uuid_mod.UUID(case_id),
        )
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consortium member not found")
    await db.delete(member)
    await db.commit()
    return None

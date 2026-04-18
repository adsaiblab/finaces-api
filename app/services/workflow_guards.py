"""
app/services/workflow_guards.py
Guards métier pour enforcer l'ordre du workflow FinaCES.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.db.models import GateResult


async def assert_gate_passed(case_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Vérifie que le Gate a été évalué et validé (is_passed=True) pour ce dossier.
    Lève HTTP 403 sinon.
    """
    result = await db.execute(
        select(GateResult).where(
            GateResult.case_id == case_id,
            GateResult.is_passed == True
        )
    )
    gate = result.scalar_one_or_none()
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Gate validation required before this step. "
                "Please complete and validate the Gate workflow first."
            )
        )

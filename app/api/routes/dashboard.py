"""
app/api/routes/dashboard.py
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel

from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.dashboard_service import get_dashboard_statistics

router = APIRouter(tags=["Dashboard"])

class RecentEventSchema(BaseModel):
    id: str
    event_type: str
    case_id: Optional[str]
    description: str
    created_at: datetime

class RecentCaseSchema(BaseModel):
    id: str
    market_reference: Optional[str]
    status: str
    risk_class: Optional[str]
    created_at: datetime

class DashboardStatsResponse(BaseModel):
    total_cases: int
    by_status: Dict[str, int]
    risk_distribution: Dict[str, int]
    recent_events: List[RecentEventSchema]
    recent_cases: List[RecentCaseSchema]


class DashboardStatsOut(BaseModel):
    total_cases: int = 0
    by_status: dict[str, int] = {}
    risk_distribution: dict[str, int] = {}
    recent_events: list[dict] = []
    recent_cases: list[dict] = []
    total_active_cases: int = 0
    cases_pending_gate: int = 0
    cases_with_tension_alert: int = 0
    convergence_percentage: float = 0.0
    avg_mcc_score_7days: float = 0.0
    avg_ia_score_7days: float = 0.0
    divergences_count_7days: int = 0
    last_updated: str = ""

@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns the overall dashboard KPIs."""
    return await get_dashboard_statistics(db=db)


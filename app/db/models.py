"""
db/models.py
FEW Solo V1.2 — Full SQLAlchemy 2.0 Models
Migration stricte de V1.1 vers V1.2 stricte
"""

import uuid
import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    String, Integer, Boolean, Text, ForeignKey,
    UniqueConstraint, Index, CheckConstraint, Numeric, Enum, func, DateTime
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from app.db.database import Base

from app.schemas.enums import (
    JVType, ConsortiumRole, LiabilityType, CaseType, CaseStatus,
    Recommendation, DocType, DocStatus, ReliabilityLevel, AuditorOpinion,
    DDVerdict, Referentiel, AdjustmentType, AdjustmentMode, RiskClass,
    OverrideType, OverrideStatus, StressResult, ReportStatus,
    InterpretationLabel, UserRole, AuditEventType
)

# ════════════════════════════════════════════════════════════════
# 00 — USER
# ════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user", lazy="selectin")

    def __repr__(self):
        return f"<User {self.email} role={self.role}>"


# ════════════════════════════════════════════════════════════════
# 01 — POLICY VERSION
# ════════════════════════════════════════════════════════════════

class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_label: Mapped[str] = mapped_column(String, nullable=False)
    effective_date: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)

    cases: Mapped[list["EvaluationCase"]] = relationship(back_populates="policy_version", lazy="selectin")
    scorecards: Mapped[list["Scorecard"]] = relationship(back_populates="policy_version", lazy="selectin")

    def __repr__(self):
        return f"<PolicyVersion {self.version_label} active={self.is_active}>"


# ════════════════════════════════════════════════════════════════
# 02 — BIDDER
# ════════════════════════════════════════════════════════════════

class Bidder(Base):
    __tablename__ = "bidders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    legal_form: Mapped[str | None] = mapped_column(String, nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    cases: Mapped[list["EvaluationCase"]] = relationship(back_populates="bidder", lazy="selectin")
    consortium_memberships: Mapped[list["ConsortiumMember"]] = relationship(back_populates="bidder", lazy="selectin")

    __table_args__ = (
        Index("ix_bidders_name", "name"),
    )

    def __repr__(self):
        return f"<Bidder {self.name} [{self.country}]>"


# ════════════════════════════════════════════════════════════════
# 03 — CONSORTIUM
# ════════════════════════════════════════════════════════════════

class Consortium(Base):
    __tablename__ = "consortiums"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    jv_type: Mapped[JVType] = mapped_column(Enum(JVType, native_enum=False, length=50), nullable=False)
    market_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    members: Mapped[list["ConsortiumMember"]] = relationship(back_populates="consortium", cascade="all, delete-orphan", lazy="selectin")
    cases: Mapped[list["EvaluationCase"]] = relationship(back_populates="consortium", lazy="selectin")

    def __repr__(self):
        return f"<Consortium {self.name} type={self.jv_type}>"


class ConsortiumMember(Base):
    __tablename__ = "consortium_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consortium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consortiums.id", ondelete="CASCADE"), nullable=False)
    bidder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bidders.id", ondelete="RESTRICT"), nullable=False)
    individual_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[ConsortiumRole] = mapped_column(Enum(ConsortiumRole, native_enum=False, length=50), nullable=False)
    participation_pct: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    liability_type: Mapped[LiabilityType | None] = mapped_column(Enum(LiabilityType, native_enum=False, length=50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    consortium: Mapped["Consortium"] = relationship(back_populates="members", lazy="selectin")
    bidder: Mapped["Bidder"] = relationship(back_populates="consortium_memberships", lazy="selectin")
    individual_case: Mapped["EvaluationCase | None"] = relationship(foreign_keys=[individual_case_id], lazy="selectin")

    __table_args__ = (
        Index("ix_consortium_members_consortium_id", "consortium_id"),
        CheckConstraint(
            'participation_pct >= 0 AND participation_pct <= 100',
            name='ck_participation_pct'
        ),
    )

    def __repr__(self):
        return (
            f"<ConsortiumMember consortium={self.consortium_id} "
            f"bidder={self.bidder_id} role={self.role}>"
        )


# ════════════════════════════════════════════════════════════════
# 03.5 — CONSORTIUM RESULT
# ════════════════════════════════════════════════════════════════

class ConsortiumResult(Base):
    __tablename__ = "consortium_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False, unique=True)
    consortium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consortiums.id", ondelete="CASCADE"), nullable=False)

    jv_type: Mapped[str | None] = mapped_column(String, nullable=True)
    aggregation_method: Mapped[str | None] = mapped_column(String, nullable=True)
    
    weighted_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    synergy_index: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    synergy_bonus: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    
    base_risk_class: Mapped[str | None] = mapped_column(String, nullable=True)
    final_risk_class: Mapped[str | None] = mapped_column(String, nullable=True)
    
    weak_link_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weak_link_member: Mapped[str | None] = mapped_column(String, nullable=True)
    
    leader_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    leader_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    aggregated_stress: Mapped[str | None] = mapped_column(String, nullable=True)
    
    members_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    mitigations_suggested_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])

    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(lazy="selectin")
    consortium: Mapped["Consortium"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_consortium_results_case_id", "case_id"),
    )

    def __repr__(self):
        return (
            f"<ConsortiumResult case={str(self.case_id)[:8]} "
            f"score={self.weighted_score}>"
        )


# ════════════════════════════════════════════════════════════════
# 04 — EVALUATION CASE (Evaluation file)
# ════════════════════════════════════════════════════════════════

class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_type: Mapped[CaseType] = mapped_column(Enum(CaseType, native_enum=False, length=50), nullable=False, default=CaseType.SINGLE)
    bidder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bidders.id", ondelete="RESTRICT"), nullable=True)
    consortium_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consortiums.id", ondelete="SET NULL"), nullable=True)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=True)
    market_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    market_object: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    contract_currency: Mapped[str | None] = mapped_column(String, nullable=True, default="USD")
    contract_duration_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus, native_enum=False, length=50), nullable=False, default=CaseStatus.DRAFT)
    recommendation: Mapped[Recommendation | None] = mapped_column(Enum(Recommendation, native_enum=False, length=50), nullable=True)
    analyst_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    bidder: Mapped["Bidder | None"] = relationship(back_populates="cases", lazy="selectin")
    consortium: Mapped["Consortium | None"] = relationship(back_populates="cases", foreign_keys=[consortium_id], lazy="selectin")
    policy_version: Mapped["PolicyVersion | None"] = relationship(back_populates="cases", lazy="selectin")
    
    financial_statements: Mapped[list["FinancialStatementRaw"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    documents: Mapped[list["DocumentEvidence"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    due_diligence_checks: Mapped[list["DueDiligenceCheck"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    ratio_sets: Mapped[list["RatioSet"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    interpretation: Mapped["ExpertInterpretation | None"] = relationship(back_populates="case", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    scorecards: Mapped[list["Scorecard"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    overrides: Mapped[list["OverrideDecision"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    capacity_assessments: Mapped[list["ContractCapacityAssessment"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    reports: Mapped[list["MCCGradeReport"]] = relationship(back_populates="case", cascade="all, delete-orphan", lazy="selectin")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="case", cascade="save-update, merge", lazy="raise") # <-- FIX P2-06
    
    ia_predictions: Mapped[list["IAPrediction"]] = relationship("IAPrediction", back_populates="case", cascade="all, delete-orphan")
    ia_features: Mapped[list["IAFeatures"]] = relationship("IAFeatures", back_populates="case", cascade="all, delete-orphan")
    ia_tensions: Mapped[list["IATension"]] = relationship("IATension", back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_evaluation_cases_status", "status"),
        Index("ix_evaluation_cases_bidder_id", "bidder_id"),
        Index("ix_evaluation_cases_updated_at", "updated_at"),
        CheckConstraint(
            "status IN ('DRAFT','IN_ANALYSIS','SCORING','COMPLETED','ARCHIVED')",
            name='ck_evaluation_case_status'
        ),
    )

    def __repr__(self):
        return (
            f"<EvaluationCase {str(self.id)[:8]} "
            f"market={self.market_reference} "
            f"status={self.status}>"
        )


# ════════════════════════════════════════════════════════════════
# 05 — EVIDENCE DOCUMENT (Documents provided)
# ════════════════════════════════════════════════════════════════

class DocumentEvidence(Base):
    __tablename__ = "document_evidences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType, native_enum=False, length=50), nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_kb: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus, native_enum=False, length=50), nullable=False, default=DocStatus.PRESENT)
    reliability_level: Mapped[ReliabilityLevel | None] = mapped_column(Enum(ReliabilityLevel, native_enum=False, length=50), nullable=True, default=ReliabilityLevel.MEDIUM)
    auditor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    auditor_opinion: Mapped[AuditorOpinion | None] = mapped_column(Enum(AuditorOpinion, native_enum=False, length=50), nullable=True)
    red_flags_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="documents", lazy="selectin")

    __table_args__ = (
        Index("ix_doc_evidence_case_id", "case_id"),
        Index("ix_doc_evidence_doc_type", "doc_type"),
        Index("ix_doc_evidence_fiscal_year", "fiscal_year"),
    )

    def __repr__(self):
        return (
            f"<DocumentEvidence {self.doc_type} "
            f"year={self.fiscal_year} "
            f"status={self.status}>"
        )


# ════════════════════════════════════════════════════════════════
# 06 — DUE DILIGENCE CHECK
# ════════════════════════════════════════════════════════════════

class DueDiligenceCheck(Base):
    __tablename__ = "due_diligence_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    dd_level: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[DDVerdict] = mapped_column(Enum(DDVerdict, native_enum=False, length=50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="due_diligence_checks", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("case_id", "dd_level", name="uq_dd_case_level"),
        Index("ix_dd_checks_case_id", "case_id"),
    )

    def __repr__(self):
        return f"<DueDiligenceCheck level={self.dd_level} verdict={self.verdict}>"


# ════════════════════════════════════════════════════════════════
# 07 — FINANCIAL STATEMENT RAW
# ════════════════════════════════════════════════════════════════

class FinancialStatementRaw(Base):
    __tablename__ = "financial_statements_raw"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    currency_original: Mapped[str | None] = mapped_column(String, nullable=True, default="USD")
    exchange_rate_to_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=1.0)
    referentiel: Mapped[Referentiel | None] = mapped_column(Enum(Referentiel, native_enum=False, length=50), nullable=True)

    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    liquid_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    inventory: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    accounts_receivable: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    non_current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    intangible_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tangible_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    total_liabilities_and_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    reserves: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    retained_earnings_prior: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_year_earnings: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    non_current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    long_term_debt: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    long_term_provisions: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    short_term_debt: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    accounts_payable: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_and_social_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sold_production: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_operating_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_of_goods_sold: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    external_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    personnel_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    taxes_and_duties: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    depreciation_and_amortization: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    income_before_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    extraordinary_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    income_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ebitda: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    investing_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financing_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    change_in_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    beginning_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ending_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backlog_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    dividends_distributed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    capex: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    is_consolidated: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    source_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="financial_statements", lazy="selectin")
    normalized_statements: Mapped[list["FinancialStatementNormalized"]] = relationship(back_populates="raw_statement", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("case_id", "fiscal_year", name="uq_raw_case_year"),
        Index("ix_fs_raw_case_id", "case_id"),
        Index("ix_fs_raw_fiscal_year", "fiscal_year"),
    )

    def __repr__(self):
        return (
            f"<FinancialStatementRaw "
            f"case={str(self.case_id)[:8]} "
            f"year={self.fiscal_year}>"
        )


# ════════════════════════════════════════════════════════════════
# 08 — FINANCIAL STATEMENT NORMALIZED
# ════════════════════════════════════════════════════════════════

class FinancialStatementNormalized(Base):
    __tablename__ = "financial_statements_normalized"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_statement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_statements_raw.id", ondelete="CASCADE"), nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency_usd: Mapped[str | None] = mapped_column(String, nullable=True, default="USD")
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True, default=1.0)

    # ── Assets ────────────────────────────────────────────────────
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    liquid_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    inventory: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    accounts_receivable: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    non_current_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    intangible_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tangible_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_assets: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Liabilities & Equity ──────────────────────────────────────
    total_liabilities_and_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    reserves: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    retained_earnings_prior: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_year_earnings: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    non_current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    long_term_debt: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    long_term_provisions: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    short_term_debt: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    accounts_payable: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_and_social_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_current_liabilities: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Income Statement ──────────────────────────────────────────
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sold_production: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_operating_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_of_goods_sold: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    external_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    personnel_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    taxes_and_duties: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    depreciation_and_amortization: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    other_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    income_before_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    extraordinary_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    income_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ebitda: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Cash Flows ────────────────────────────────────────────────
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    investing_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financing_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    change_in_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    beginning_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ending_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Operational ───────────────────────────────────────────────
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backlog_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    capex: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    is_consolidated: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    adjustments_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    normalized_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=lambda: {}) # <-- FIX P2-07
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    raw_statement: Mapped["FinancialStatementRaw"] = relationship(back_populates="normalized_statements", lazy="selectin")
    ratio_sets: Mapped[list["RatioSet"]] = relationship(back_populates="normalized_statement", lazy="selectin")

    __table_args__ = (
        Index("ix_fs_norm_raw_id", "raw_statement_id"),
    )

    def __repr__(self):
        return f"<FinancialStatementNormalized raw={str(self.raw_statement_id)[:8]} year={self.fiscal_year}>"


# ════════════════════════════════════════════════════════════════
# 09 — NORMALIZATION ADJUSTMENT (Adjustment log)
# ════════════════════════════════════════════════════════════════

class NormalizationAdjustment(Base):
    __tablename__ = "normalization_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    raw_statement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_statements_raw.id", ondelete="CASCADE"), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    adjustment_type: Mapped[AdjustmentType] = mapped_column(Enum(AdjustmentType, native_enum=False, length=50), nullable=False)
    field_affected: Mapped[str] = mapped_column(String, nullable=False)
    amount_before: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    mode: Mapped[AdjustmentMode] = mapped_column(Enum(AdjustmentMode, native_enum=False, length=50), nullable=False, default=AdjustmentMode.add)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_norm_adj_case_id", "case_id"),
        Index("ix_norm_adj_raw_id", "raw_statement_id"),
    )

    def __repr__(self):
        return (
            f"<NormalizationAdjustment "
            f"type={self.adjustment_type} "
            f"field={self.field_affected} "
            f"year={self.fiscal_year}>"
        )


# ════════════════════════════════════════════════════════════════
# 10 — RATIO SET (Set of calculated ratios)
# ════════════════════════════════════════════════════════════════

class RatioSet(Base):
    __tablename__ = "ratio_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_statement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_statements_normalized.id", ondelete="CASCADE"), nullable=False)

    current_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quick_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cash_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    working_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    debt_to_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    financial_autonomy: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    gearing: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    interest_coverage: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    net_margin: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ebitda_margin: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    operating_margin: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    roa: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    roe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    dso_days: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    dpo_days: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    dio_days: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cash_conversion_cycle: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    working_capital_requirement: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    working_capital_requirement_pct_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    cash_flow_capacity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cash_flow_capacity_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    debt_repayment_years: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    negative_equity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    negative_operating_cash_flow: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    z_score_altman: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    z_score_zone: Mapped[str | None] = mapped_column(String, nullable=True)

    coherence_alerts_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="ratio_sets", lazy="selectin")
    normalized_statement: Mapped["FinancialStatementNormalized"] = relationship(back_populates="ratio_sets", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("case_id", "fiscal_year", name="uq_ratio_case_year"),
        Index("ix_ratio_sets_case_id", "case_id"),
        Index("ix_ratio_sets_fiscal_year", "fiscal_year"),
    )

    def __repr__(self):
        return (
            f"<RatioSet case={str(self.case_id)[:8]} "
            f"year={self.fiscal_year} "
            f"CR={self.current_ratio}>"
        )


# ════════════════════════════════════════════════════════════════
# 11 — EXPERT INTERPRETATION (Guided interpretation)
# ════════════════════════════════════════════════════════════════

class ExpertInterpretation(Base):
    __tablename__ = "expert_interpretations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False, unique=True)

    liquidity_label: Mapped[InterpretationLabel | None] = mapped_column(Enum(InterpretationLabel, native_enum=False, length=50), nullable=True)
    liquidity_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    solvency_label: Mapped[InterpretationLabel | None] = mapped_column(Enum(InterpretationLabel, native_enum=False, length=50), nullable=True)
    solvency_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    profitability_label: Mapped[InterpretationLabel | None] = mapped_column(Enum(InterpretationLabel, native_enum=False, length=50), nullable=True)
    profitability_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity_label: Mapped[InterpretationLabel | None] = mapped_column(Enum(InterpretationLabel, native_enum=False, length=50), nullable=True)
    capacity_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_label: Mapped[InterpretationLabel | None] = mapped_column(Enum(InterpretationLabel, native_enum=False, length=50), nullable=True)
    quality_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    dynamic_analysis_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    coherence_warnings_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])

    is_complete: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="interpretation", lazy="selectin")

    def __repr__(self):
        return (
            f"<ExpertInterpretation "
            f"case={str(self.case_id)[:8]} "
            f"complete={self.is_complete}>"
        )


# ════════════════════════════════════════════════════════════════
# 12 — SCORECARD (Scoring MCC-grade)
# ════════════════════════════════════════════════════════════════

class Scorecard(Base):
    __tablename__ = "scorecards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True)

    score_liquidity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    score_solvency: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    score_profitability: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    score_capacity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    score_quality: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    score_global: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    risk_class: Mapped[RiskClass | None] = mapped_column(Enum(RiskClass, native_enum=False, length=50), nullable=True)

    overrides_applied_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=lambda: []) # <-- FIX P2-07

    risk_profile: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_description: Mapped[str | None] = mapped_column(String, nullable=True)
    synergy_index: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    synergy_bonus: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cross_analysis_alerts: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    trends_summary: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)

    smart_recommendations_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=lambda: []) # <-- FIX P2-07
    expert_interpretations_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=lambda: {}) # <-- FIX P2-07

    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="scorecards", lazy="selectin")
    policy_version: Mapped["PolicyVersion | None"] = relationship(back_populates="scorecards", lazy="selectin")

    __table_args__ = (
        Index("ix_scorecards_case_id", "case_id"),
        Index("ix_scorecards_computed_at", "computed_at"),
        UniqueConstraint('case_id', 'computed_at', name='uq_scorecard_case_time'), # <-- FIX P2-05
    )

    def __repr__(self):
        return (
            f"<Scorecard case={str(self.case_id)[:8]} "
            f"score={self.score_global} "
            f"class={self.risk_class}>"
        )


# ════════════════════════════════════════════════════════════════
# 13 — GATE RESULT (Knockout & Due Diligence Result)
# ════════════════════════════════════════════════════════════════

class GateResult(Base):
    __tablename__ = "gate_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    is_gate_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocking_reasons_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    
    is_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    reliability_level: Mapped[str | None] = mapped_column(String, nullable=True)
    reliability_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    
    missing_mandatory_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    missing_optional_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    reserve_flags_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_gate_results_case_id", "case_id"),
    )

    def __repr__(self):
        return (
            f"<GateResult case={str(self.case_id)[:8]} "
            f"passed={self.is_passed} "
            f"blocking={self.is_gate_blocking}>"
        )


# ════════════════════════════════════════════════════════════════
# 14 — OVERRIDE DECISION
# ════════════════════════════════════════════════════════════════

class OverrideDecision(Base):
    __tablename__ = "override_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    override_type: Mapped[OverrideType] = mapped_column(Enum(OverrideType, native_enum=False, length=50), nullable=False)
    red_flag_code: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_risk_class: Mapped[RiskClass] = mapped_column(Enum(RiskClass, native_enum=False, length=50), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_evidences.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[OverrideStatus] = mapped_column(Enum(OverrideStatus, native_enum=False, length=50), nullable=False, default=OverrideStatus.ACTIVE)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="overrides", lazy="selectin")
    evidence_document: Mapped["DocumentEvidence | None"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_override_case_id", "case_id"),
        Index("ix_override_status", "status"),
    )

    def __repr__(self):
        return (
            f"<OverrideDecision type={self.override_type} "
            f"→ {self.proposed_risk_class} "
            f"status={self.status}>"
        )


# ════════════════════════════════════════════════════════════════
# 15 — CONTRACT CAPACITY ASSESSMENT
# ════════════════════════════════════════════════════════════════

class ContractCapacityAssessment(Base):
    __tablename__ = "contract_capacity_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)

    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    annual_ca_avg: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    exposition_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    backlog_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    bank_guarantee: Mapped[bool] = mapped_column(Boolean, default=False)
    bank_guarantee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    credit_lines_confirmed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    cash_available: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    working_capital_requirement_estimate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    advance_payment_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0.0)
    payment_milestones_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default=[])
    monthly_flows_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)

    stress_60d_result: Mapped[StressResult | None] = mapped_column(Enum(StressResult, native_enum=False, length=50), nullable=True)
    stress_90d_result: Mapped[StressResult | None] = mapped_column(Enum(StressResult, native_enum=False, length=50), nullable=True)
    stress_60d_cash_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    stress_90d_cash_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    score_capacity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    capacity_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenarios_results_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="capacity_assessments", lazy="selectin")

    __table_args__ = (
        Index("ix_capacity_case_id", "case_id"),
    )

    def __repr__(self):
        return (
            f"<ContractCapacityAssessment "
            f"case={str(self.case_id)[:8]} "
            f"stress60={self.stress_60d_result}>"
        )


# ════════════════════════════════════════════════════════════════
# 15.5 — STRESS SCENARIO (Simulation of Basic Scenarios)
# ════════════════════════════════════════════════════════════════

class StressScenario(Base):
    __tablename__ = "stress_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    
    # Test inputs
    scenario_name: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_parameters_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default={})
    
    # Opposable Results
    simulated_score_global: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    simulated_risk_class: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Details
    stress_results_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default={})

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_stress_scenario_case_id", "case_id"),
    )

    def __repr__(self):
        return (
            f"<StressScenario case={str(self.case_id)[:8]} "
            f"name={self.scenario_name}>"
        )


# ════════════════════════════════════════════════════════════════
# 15.7 — EXPERT REVIEW (Qualitative opinion of the analyst & Final decision)
# ════════════════════════════════════════════════════════════════

class ExpertReview(Base):
    __tablename__ = "expert_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)

    analyst_id: Mapped[str] = mapped_column(String, nullable=False)
    qualitative_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_risk_override: Mapped[str | None] = mapped_column(String, nullable=True)
    final_decision: Mapped[str] = mapped_column(
        String,
        CheckConstraint("final_decision IN ('APPROVED', 'REJECTED', 'ESCALATED')", name='ck_expert_final_decision'),
        nullable=False,
        default="ESCALATED"
    )

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_expert_reviews_case_id", "case_id"),
    )

    def __repr__(self):
        return (
            f"<ExpertReview case={str(self.case_id)[:8]} "
            f"decision={self.final_decision}>"
        )


# ════════════════════════════════════════════════════════════════
# 16 — MCC GRADE REPORT (Note MCC-grade)
# ════════════════════════════════════════════════════════════════

class MCCGradeReport(Base):
    __tablename__ = "mcc_grade_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, native_enum=False, length=50), nullable=False, default=ReportStatus.DRAFT)
    recommendation: Mapped[Recommendation | None] = mapped_column(Enum(Recommendation, native_enum=False, length=50), nullable=True)

    section_01_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_02_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_03_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_04_executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_05_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_06_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_07_capacity: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_08_red_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_09_mitigants: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_10_scoring: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_11_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_12_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_13_limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_14_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    export_word_path: Mapped[str | None] = mapped_column(String, nullable=True)
    export_pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)

    sections_complete_flags: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True, default={})

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase"] = relationship(back_populates="reports", lazy="selectin")

    __table_args__ = (
        Index("ix_reports_case_id", "case_id"),
        Index("ix_reports_status", "status"),
        Index("ix_reports_created_at", "created_at"),
        CheckConstraint(
            "status IN ('DRAFT', 'FINAL', 'ARCHIVED')",
            name="ck_report_status"
        ),
    )

    def __repr__(self):
        return (
            f"<MCCGradeReport "
            f"case={str(self.case_id)[:8]} "
            f"v{self.version_number} "
            f"status={self.status}>"
        )


# ════════════════════════════════════════════════════════════════
# 17 — AUDIT LOG (Complete audit trail)
# ════════════════════════════════════════════════════════════════

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType, native_enum=False, length=50), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_value_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    new_value_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    case: Mapped["EvaluationCase | None"] = relationship(back_populates="audit_logs", lazy="selectin")
    user: Mapped["User | None"] = relationship(back_populates="audit_logs", lazy="selectin")

    __table_args__ = (
        Index("ix_audit_case_id", "case_id"),
        Index("ix_audit_event_type", "event_type"),
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_entity_type", "entity_type"),
    )

    def __repr__(self):
        return (
            f"<AuditLog event={self.event_type} "
            f"case={str(self.case_id)[:8] if self.case_id else 'SYSTEM'} "
            f"at={self.created_at.strftime('%Y-%m-%d') if self.created_at else 'N/A'}>"
        )


# ════════════════════════════════════════════════════════════════
# 18 — COMPARISON SESSION
# ════════════════════════════════════════════════════════════════

class ComparisonSession(Base):
    __tablename__ = "comparison_sessions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_ref: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), default=func.now(), nullable=True)
    case_ids_json: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)


# ════════════════════════════════════════════════════════════════
# 19 — IA PREDICTION
# ════════════════════════════════════════════════════════════════

class IAPrediction(Base):
    __tablename__ = "ia_predictions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id"), index=True, nullable=False)
    ia_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    ia_probability_default: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    ia_risk_class: Mapped[str] = mapped_column(String(20), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
    case: Mapped["EvaluationCase"] = relationship("EvaluationCase", back_populates="ia_predictions")


# ════════════════════════════════════════════════════════════════
# 20 — IA FEATURES
# ════════════════════════════════════════════════════════════════

class IAFeatures(Base):
    __tablename__ = "ia_features"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id"), index=True, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    case: Mapped["EvaluationCase"] = relationship("EvaluationCase", back_populates="ia_features")


# ════════════════════════════════════════════════════════════════
# 21 — IA TENSION
# ════════════════════════════════════════════════════════════════

class IATension(Base):
    __tablename__ = "ia_tensions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_cases.id"), index=True, nullable=False)
    mcc_risk_class: Mapped[str] = mapped_column(String(20), nullable=False)
    ia_risk_class: Mapped[str] = mapped_column(String(20), nullable=False)
    tension_type: Mapped[str] = mapped_column(String(50), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    case: Mapped["EvaluationCase"] = relationship("EvaluationCase", back_populates="ia_tensions")


# ════════════════════════════════════════════════════════════════
# 22 — IA MODEL
# ════════════════════════════════════════════════════════════════

class IAModel(Base):
    __tablename__ = "ia_models"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    hyperparameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feature_names: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


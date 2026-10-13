import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaseCreate(BaseModel):
    product: str = Field(min_length=2, max_length=200)
    narrative: str = Field(min_length=30, max_length=10_000)
    company: str | None = Field(default=None, max_length=300)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    consent_to_store_redacted_text: bool

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    source_complaint_id: int | None
    product: str
    issue: str | None
    narrative: str
    company: str | None
    state: str | None
    status: str
    assigned_team: str | None
    priority: str | None
    classification_confidence: float | None
    redaction_count: int
    created_at: datetime
    updated_at: datetime


class CaseCreated(CaseRead):
    privacy_message: str


class CaseList(BaseModel):
    items: list[CaseRead]
    total: int


class Classification(BaseModel):
    product: str
    issue: str
    assigned_team: str
    priority: Literal["standard", "priority"]
    confidence: float = Field(ge=0, le=1)
    escalation_flags: list[str]


class Citation(BaseModel):
    collection: Literal["historical_complaints", "operating_policies"]
    source_id: str
    label: str
    excerpt: str


class AgentRecommendation(BaseModel):
    summary: str
    classification: Classification
    recommended_actions: list[str]
    rationale: list[str]
    citations: list[Citation]
    provider: Literal["mock", "openai"]
    requires_human_review: bool = True


class AnalysisRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: str
    recommendation: AgentRecommendation
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    tool_trace: list[dict] = Field(default_factory=list)
    created_at: datetime


class ReviewCreate(BaseModel):
    action: Literal["approved", "edited", "rejected"]
    notes: str | None = Field(default=None, max_length=2_000)
    edited_recommendation: AgentRecommendation | None = None


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_run_id: uuid.UUID
    action: str
    reviewer: str
    notes: str | None
    edited_recommendation: AgentRecommendation | None
    created_at: datetime


class ReviewHistory(BaseModel):
    items: list[ReviewRead]


class EvaluationSummary(BaseModel):
    completed_analyses: int
    reviewed_analyses: int
    approved_reviews: int
    edited_reviews: int
    rejected_reviews: int
    dual_collection_citation_rate: float | None
    average_latency_seconds: float | None
    total_estimated_cost_usd: float
    average_estimated_cost_usd: float | None


class BaselineEvaluation(BaseModel):
    sample_size: int
    team_accuracy: float | None
    priority_accuracy: float | None
    dataset: str
    evaluated_system: str


class RetrievalEvaluation(BaseModel):
    sample_size: int
    judged_precision_at_5: float | None
    judgment_coverage_at_5: float | None
    graded_ndcg_at_5: float | None
    graded_judgment_coverage_at_5: float | None
    known_relevant_hit_at_10: float | None
    known_relevant_mrr_at_10: float | None
    policy_top_1_accuracy: float | None
    policy_hit_at_3: float | None
    policy_mrr_at_3: float | None
    limitations: str

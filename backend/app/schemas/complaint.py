from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ComplaintSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date_received: date
    product: str
    issue: str
    company: str
    state: str | None
    narrative: str | None
    timely_response: bool | None
    ingested_at: datetime


class ComplaintList(BaseModel):
    items: list[ComplaintSummary]
    total: int
    limit: int
    offset: int


class RoutePreview(BaseModel):
    team: str
    priority: str
    reasons: list[str]
    requires_human_review: bool = True

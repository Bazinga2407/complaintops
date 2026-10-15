"""Create or remove a small, synthetic operations queue for portfolio demonstrations."""

import argparse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agent.mock import analyze_with_mock
from app.db.models import AnalysisRun, Case, Complaint, ReviewAction
from app.db.session import SessionLocal

DEMO_NAMESPACE = uuid.UUID("9753a9b4-8b7e-47b3-b764-5b90b1e51a8d")
DEMO_REVIEWER = "ComplaintOps Demo Reviewer"


@dataclass(frozen=True)
class DemoCaseSpec:
    key: str
    product: str
    narrative: str
    company: str
    state: str
    final_status: str
    age_hours: int


DEMO_CASES = (
    DemoCaseSpec(
        key="unknown-debt-priority",
        product="Debt collection",
        narrative=(
            "A collector is repeatedly calling about a debt I do not recognize. I requested "
            "validation, but the calls continued and the account still appears to be mine."
        ),
        company="Northstar Demo Collections",
        state="IL",
        final_status="awaiting_review",
        age_hours=2,
    ),
    DemoCaseSpec(
        key="credit-report-identity",
        product="Credit reporting or other personal consumer reports",
        narrative=(
            "My credit report contains an account that is not mine. I submitted an identity "
            "theft report, but the disputed account was verified without an explanation."
        ),
        company="Example Demo Credit Bureau",
        state="TX",
        final_status="awaiting_review",
        age_hours=6,
    ),
    DemoCaseSpec(
        key="checking-fee-refund",
        product="Checking or savings account",
        narrative=(
            "The bank charged duplicate overdraft fees after a deposit was delayed. Support "
            "promised a refund, but the fees have not been returned."
        ),
        company="Contoso Demo Bank",
        state="WA",
        final_status="awaiting_review",
        age_hours=18,
    ),
    DemoCaseSpec(
        key="mortgage-payment-approved",
        product="Mortgage",
        narrative=(
            "My mortgage payment was withdrawn on time but posted late. The servicer added a "
            "late fee and sent a delinquency notice even though the payment cleared."
        ),
        company="Fabrikam Demo Mortgage",
        state="CA",
        final_status="approved",
        age_hours=30,
    ),
    DemoCaseSpec(
        key="transfer-scam-rejected",
        product="Money transfer, virtual currency, or money service",
        narrative=(
            "A transfer was sent after a scammer impersonated customer support. The initial "
            "response closed the dispute without reviewing the reported impersonation."
        ),
        company="Adventure Works Demo Payments",
        state="NY",
        final_status="rejected",
        age_hours=48,
    ),
)


@dataclass(frozen=True)
class DemoSeedResult:
    created: int
    skipped: int
    removed: int


def demo_case_id(key: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, f"case:{key}")


def demo_analysis_id(key: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, f"analysis:{key}")


def demo_case_ids() -> list[uuid.UUID]:
    return [demo_case_id(spec.key) for spec in DEMO_CASES]


def remove_demo_cases(db: Session) -> int:
    ids = demo_case_ids()
    existing = list(db.scalars(select(Case.id).where(Case.id.in_(ids))).all())
    if existing:
        db.execute(delete(Case).where(Case.id.in_(existing)))
        db.commit()
    return len(existing)


def seed_demo_cases(db: Session, *, replace: bool = False) -> DemoSeedResult:
    removed = remove_demo_cases(db) if replace else 0
    ids = demo_case_ids()
    existing = set(db.scalars(select(Case.id).where(Case.id.in_(ids))).all())
    created = 0
    now = datetime.now(UTC)

    for spec in DEMO_CASES:
        case_id = demo_case_id(spec.key)
        if case_id in existing:
            continue

        created_at = now - timedelta(hours=spec.age_hours)
        case = Case(
            id=case_id,
            source="demo",
            product=spec.product,
            narrative=spec.narrative,
            company=spec.company,
            state=spec.state,
            status=spec.final_status,
            redaction_count=0,
            created_at=created_at,
            updated_at=created_at,
        )
        similar = list(
            db.scalars(
                select(Complaint)
                .where(
                    Complaint.product == spec.product,
                    Complaint.narrative.is_not(None),
                )
                .order_by(Complaint.date_received.desc())
                .limit(3)
            ).all()
        )
        recommendation = analyze_with_mock(case, similar)
        classification = recommendation.classification
        case.issue = classification.issue
        case.assigned_team = classification.assigned_team
        case.priority = classification.priority
        case.classification_confidence = classification.confidence

        run = AnalysisRun(
            id=demo_analysis_id(spec.key),
            case=case,
            status="completed",
            provider="mock",
            model="deterministic-demo-seed-v1",
            classification=classification.model_dump(),
            recommendation=recommendation.model_dump(),
            citations=[citation.model_dump() for citation in recommendation.citations],
            tool_trace=[
                {"tool": "demo_seed", "status": "completed"},
                {
                    "tool": "search_similar_complaints",
                    "status": "completed",
                    "result_count": len(similar),
                },
                {
                    "tool": "search_operating_policies",
                    "status": "completed",
                    "result_count": 2,
                },
            ],
            estimated_cost_usd=0.0,
            created_at=created_at + timedelta(minutes=2),
            completed_at=created_at + timedelta(minutes=2, seconds=4),
        )
        if spec.final_status in {"approved", "rejected"}:
            run.review_actions.append(
                ReviewAction(
                    action=spec.final_status,
                    reviewer=DEMO_REVIEWER,
                    notes="Synthetic decision included for the portfolio demonstration.",
                    created_at=created_at + timedelta(minutes=8),
                )
            )
        db.add(case)
        created += 1

    db.commit()
    return DemoSeedResult(created=created, skipped=len(DEMO_CASES) - created, removed=removed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true", help="Insert missing demo cases")
    action.add_argument("--remove", action="store_true", help="Delete only seeded demo cases")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="With --execute, replace the deterministic demo set",
    )
    args = parser.parse_args()
    if args.replace and not args.execute:
        parser.error("--replace requires --execute")
    if not args.execute and not args.remove:
        print(
            f"Dry run: would create up to {len(DEMO_CASES)} synthetic cases. "
            "Add --execute to insert them or --remove to delete only the demo set."
        )
        return

    with SessionLocal() as db:
        if args.remove:
            removed = remove_demo_cases(db)
            print(f"Removed {removed} synthetic demo cases")
            return
        result = seed_demo_cases(db, replace=args.replace)
    print(
        f"Demo seed complete: {result.created} created, {result.skipped} already present, "
        f"{result.removed} replaced"
    )


if __name__ == "__main__":
    main()

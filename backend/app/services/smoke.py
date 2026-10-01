"""Run a zero-cost authenticated API workflow against the local database.

The runner creates one clearly marked temporary case, analyzes it with the mock
provider, approves it, verifies persistence, and removes only that case in a
finally block. It never calls the OpenAI API.
"""

import json
import os
import uuid

# This must be set before the application and cached settings are imported.
os.environ["AGENT_PROVIDER"] = "mock"

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import cookie_name, create_session
from app.db.models import Case
from app.db.session import SessionLocal
from app.main import app


def run_smoke_test() -> dict:
    settings = get_settings()
    case_id: uuid.UUID | None = None
    steps: list[str] = []
    token, csrf = create_session(settings.operator_username or "Smoke Operator", settings)
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}

    try:
        with TestClient(app, base_url="http://testserver") as client:
            client.cookies.set(cookie_name(settings), token)

            session = client.get("/api/v1/auth/session")
            session.raise_for_status()
            assert session.json()["authenticated"] is True
            steps.append("authenticated_session")

            users = client.get("/api/v1/users")
            users.raise_for_status()
            assert "items" in users.json()
            steps.append("verified_admin_access")

            created = client.post(
                "/api/v1/cases",
                headers=headers,
                json={
                    "product": "Debt collection",
                    "narrative": (
                        "ComplaintOps smoke test: a collector contacted me about an account "
                        "I do not recognize. Reply to smoke-test@example.com."
                    ),
                    "company": "Smoke Test Financial",
                    "state": "IL",
                    "consent_to_store_redacted_text": True,
                },
            )
            created.raise_for_status()
            created_body = created.json()
            case_id = uuid.UUID(created_body["id"])
            assert created_body["redaction_count"] == 1
            assert "smoke-test@example.com" not in created_body["narrative"]
            steps.append("created_redacted_case")

            analyzed = client.post(f"/api/v1/cases/{case_id}/analyze", headers=headers)
            analyzed.raise_for_status()
            analysis = analyzed.json()
            assert analysis["recommendation"]["provider"] == "mock"
            assert {item["collection"] for item in analysis["recommendation"]["citations"]} == {
                "historical_complaints",
                "operating_policies",
            }
            steps.append("analyzed_with_two_collections")

            reviewed = client.post(
                f"/api/v1/cases/analyses/{analysis['id']}/reviews",
                headers=headers,
                json={
                    "action": "approved",
                    "notes": "Automated local smoke test",
                    "edited_recommendation": None,
                },
            )
            reviewed.raise_for_status()
            assert reviewed.json()["action"] == "approved"
            steps.append("approved_recommendation")

            persisted = client.get(f"/api/v1/cases/{case_id}")
            persisted.raise_for_status()
            assert persisted.json()["status"] == "approved"
            history = client.get(f"/api/v1/cases/{case_id}/reviews")
            history.raise_for_status()
            assert len(history.json()["items"]) == 1
            steps.append("verified_persistence")
    finally:
        if case_id is not None:
            with SessionLocal() as db:
                temporary_case = db.get(Case, case_id)
                if temporary_case is not None:
                    db.delete(temporary_case)
                    db.commit()

    return {
        "passed": True,
        "provider": "mock",
        "paid_api_calls": 0,
        "steps": steps,
        "temporary_case_removed": case_id is not None,
    }


def main() -> None:
    print(json.dumps(run_smoke_test(), indent=2))


if __name__ == "__main__":
    main()

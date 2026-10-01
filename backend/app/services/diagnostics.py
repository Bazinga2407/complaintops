import json

from sqlalchemy import text

from app.db.session import engine


def database_status() -> dict[str, str | int | float | None]:
    with engine.connect() as connection:
        return {
            "database": connection.scalar(text("SELECT current_database()")),
            "pgvector_version": connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ),
            "public_table_count": connection.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ),
            "historical_complaint_count": connection.scalar(
                text("SELECT count(*) FROM complaints")
            ),
            "historical_narrative_count": connection.scalar(
                text("SELECT count(*) FROM complaints WHERE narrative IS NOT NULL")
            ),
            "complaint_embedding_count": connection.scalar(
                text("SELECT count(*) FROM complaint_embeddings")
            ),
            "active_policy_document_count": connection.scalar(
                text("SELECT count(*) FROM policy_documents WHERE is_active")
            ),
            "policy_embedding_count": connection.scalar(
                text("SELECT count(*) FROM policy_chunks WHERE embedding IS NOT NULL")
            ),
            "active_case_count": connection.scalar(text("SELECT count(*) FROM cases")),
            "completed_analysis_count": connection.scalar(
                text("SELECT count(*) FROM analysis_runs WHERE status = 'completed'")
            ),
            "tracked_agent_cost_usd": connection.scalar(
                text("SELECT COALESCE(sum(estimated_cost_usd), 0)::float FROM analysis_runs")
            ),
        }


def main() -> None:
    print(json.dumps(database_status(), indent=2))


if __name__ == "__main__":
    main()

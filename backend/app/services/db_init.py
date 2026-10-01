"""Apply the idempotent starter schema to a fresh pgvector-enabled database."""

from pathlib import Path

from sqlalchemy import text

from app.db.session import engine


def main() -> None:
    schema_dir = Path(__file__).resolve().parents[3] / "database" / "init"
    with engine.begin() as connection:
        for schema_path in sorted(schema_dir.glob("*.sql")):
            statements = [
                part.strip() for part in schema_path.read_text(encoding="utf-8").split(";")
            ]
            for statement in statements:
                if statement:
                    connection.execute(text(statement))
    print("ComplaintOps schema is ready")


if __name__ == "__main__":
    main()

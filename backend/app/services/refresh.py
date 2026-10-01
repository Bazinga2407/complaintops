"""Scheduled CFPB refresh followed by cost-capped embedding. Opt-in execution."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.cfpb_client import CfpbClient
from app.services.embeddings import OpenAIEmbedder, run_embedding_pipeline
from app.services.ingestion import ingest_window


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Actually fetch and embed data")
    parser.add_argument("--days", type=int, default=7, help="Overlapping CFPB lookback window")
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    args = parser.parse_args()
    if not 1 <= args.days <= 90 or not 0 < args.max_cost_usd <= 10:
        parser.error("Choose 1–90 days and an embedding budget greater than $0 and at most $10")
    date_to = datetime.now(UTC).date()
    date_from = date_to - timedelta(days=args.days)
    if not args.execute:
        print(
            f"Dry run: would import public narratives from {date_from} before {date_to} "
            f"and embed missing rows with a ${args.max_cost_usd:.2f} estimated cost cap. "
            "Add --execute to run."
        )
        return

    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        parser.error("OPENAI_API_KEY is required to embed new complaints")
    client = CfpbClient(settings.cfpb_api_base_url)
    embedder = OpenAIEmbedder(
        api_key=api_key,
        model=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
    )
    policy_dir = Path(__file__).resolve().parents[3] / "policies"
    with SessionLocal() as db:
        imported = ingest_window(
            db,
            client,
            date_from=date_from,
            date_to=date_to,
            narratives_only=True,
        )
        embedded = run_embedding_pipeline(
            db,
            embedder,
            policy_dir=policy_dir,
            max_cost_usd=args.max_cost_usd,
        )
    print(
        f"Processed {imported.processed} public complaints; embedded "
        f"{embedded.complaints_embedded} complaints and "
        f"{embedded.policy_chunks_embedded} policy chunks; estimated embedding cost "
        f"${embedded.estimated_cost_usd:.4f}"
    )


if __name__ == "__main__":
    main()

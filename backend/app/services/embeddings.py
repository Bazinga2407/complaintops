import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

import tiktoken
from openai import OpenAI
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Complaint, ComplaintEmbedding, PolicyChunk, PolicyDocument
from app.db.session import SessionLocal

EMBEDDING_PRICE_PER_MILLION_TOKENS_USD = 0.02
MAX_INPUT_TOKENS = 7_800
MAX_BATCH_TOKENS = 250_000


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]: ...


@dataclass(frozen=True)
class PolicySection:
    heading: str
    content: str


@dataclass(frozen=True)
class PreparedText:
    record_id: int
    text: str
    token_count: int


@dataclass(frozen=True)
class EmbeddingRunResult:
    complaints_embedded: int
    policy_chunks_embedded: int
    input_tokens: int
    estimated_cost_usd: float


class OpenAIEmbedder:
    def __init__(self, *, api_key: str, model: str, dimensions: int = 1536) -> None:
        self.model = model
        self.dimensions = dimensions
        self.client = OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        response = self.client.embeddings.create(
            input=texts,
            model=self.model,
            dimensions=self.dimensions,
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        return vectors, response.usage.total_tokens


def chunk_policy_markdown(content: str) -> list[PolicySection]:
    sections: list[PolicySection] = []
    heading = "Overview"
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append(PolicySection(heading=heading, content=body))

    for line in content.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            lines = []
            continue
        lines.append(line)
    flush()
    return sections


def _policy_metadata(content: str, fallback_title: str) -> tuple[str, str]:
    title_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    version_match = re.search(r"^Version:\s*(.+)$", content, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else fallback_title
    version = version_match.group(1).strip() if version_match else "unversioned"
    return title, version


def sync_policy_documents(db: Session, policy_dir: Path) -> int:
    synced_chunks = 0
    for path in sorted(policy_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        source_path = f"policies/{path.name}"
        document = db.scalar(select(PolicyDocument).where(PolicyDocument.checksum == checksum))
        if document is not None:
            document.is_active = True
            db.execute(
                update(PolicyDocument)
                .where(
                    PolicyDocument.source_path == source_path,
                    PolicyDocument.id != document.id,
                )
                .values(is_active=False)
            )
            continue

        title, version = _policy_metadata(raw, path.stem)
        db.execute(
            update(PolicyDocument)
            .where(PolicyDocument.source_path == source_path)
            .values(is_active=False)
        )
        document = PolicyDocument(
            title=title,
            version=version,
            source_path=source_path,
            checksum=checksum,
            is_active=True,
        )
        db.add(document)
        db.flush()
        for index, section in enumerate(chunk_policy_markdown(raw)):
            db.add(
                PolicyChunk(
                    document_id=document.id,
                    chunk_index=index,
                    heading=section.heading,
                    content=section.content,
                    metadata_json={"source_path": source_path, "version": version},
                )
            )
            synced_chunks += 1
    db.commit()
    return synced_chunks


def complaint_embedding_text(complaint: Complaint) -> str:
    fields = [
        f"Product: {complaint.product}",
        f"Issue: {complaint.issue}",
        f"Company: {complaint.company}",
    ]
    if complaint.company_response:
        fields.append(f"Company response: {complaint.company_response}")
    fields.append(f"Consumer narrative: {complaint.narrative or ''}")
    return "\n".join(fields)


def policy_embedding_text(chunk: PolicyChunk) -> str:
    return f"Policy section: {chunk.heading or 'Overview'}\n{chunk.content}"


def prepare_text(record_id: int, text: str) -> PreparedText:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) > MAX_INPUT_TOKENS:
        tokens = tokens[:MAX_INPUT_TOKENS]
        text = encoding.decode(tokens)
    return PreparedText(record_id=record_id, text=text, token_count=len(tokens))


T = TypeVar("T", bound=PreparedText)


def make_batches(items: list[T], batch_size: int) -> list[list[T]]:
    batches: list[list[T]] = []
    batch: list[T] = []
    batch_tokens = 0
    for item in items:
        if batch and (
            len(batch) >= batch_size or batch_tokens + item.token_count > MAX_BATCH_TOKENS
        ):
            batches.append(batch)
            batch = []
            batch_tokens = 0
        batch.append(item)
        batch_tokens += item.token_count
    if batch:
        batches.append(batch)
    return batches


def _projected_cost(token_count: int) -> float:
    return token_count / 1_000_000 * EMBEDDING_PRICE_PER_MILLION_TOKENS_USD


def _embed_complaints(
    db: Session,
    embedder: Embedder,
    *,
    batch_size: int,
    limit: int | None,
    remaining_budget_usd: float,
) -> tuple[int, int, float]:
    statement = (
        select(Complaint)
        .outerjoin(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
        .where(
            Complaint.narrative.is_not(None),
            or_(
                ComplaintEmbedding.complaint_id.is_(None),
                ComplaintEmbedding.embedding_model != embedder.model,
            ),
        )
        .order_by(Complaint.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    complaints = list(db.scalars(statement).all())
    prepared = [
        prepare_text(complaint.id, complaint_embedding_text(complaint)) for complaint in complaints
    ]

    embedded = 0
    input_tokens = 0
    cost = 0.0
    for batch in make_batches(prepared, batch_size):
        estimated_batch_cost = _projected_cost(sum(item.token_count for item in batch))
        if cost + estimated_batch_cost > remaining_budget_usd:
            break
        vectors, used_tokens = embedder.embed([item.text for item in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding response count did not match the request")
        rows = [
            {
                "complaint_id": item.record_id,
                "embedding_model": embedder.model,
                "embedding": vector,
            }
            for item, vector in zip(batch, vectors, strict=True)
        ]
        statement = insert(ComplaintEmbedding).values(rows)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[ComplaintEmbedding.complaint_id],
                set_={
                    "embedding_model": statement.excluded.embedding_model,
                    "embedding": statement.excluded.embedding,
                },
            )
        )
        db.commit()
        embedded += len(batch)
        input_tokens += used_tokens
        cost += _projected_cost(used_tokens)
        print(f"Embedded {embedded}/{len(prepared)} complaints")
    return embedded, input_tokens, cost


def _embed_policy_chunks(
    db: Session,
    embedder: Embedder,
    *,
    batch_size: int,
    remaining_budget_usd: float,
) -> tuple[int, int, float]:
    chunks = list(
        db.scalars(
            select(PolicyChunk)
            .join(PolicyDocument)
            .where(
                PolicyDocument.is_active.is_(True),
                or_(
                    PolicyChunk.embedding.is_(None),
                    PolicyChunk.embedding_model != embedder.model,
                ),
            )
            .order_by(PolicyChunk.document_id, PolicyChunk.chunk_index)
        ).all()
    )
    prepared = [prepare_text(chunk.id, policy_embedding_text(chunk)) for chunk in chunks]
    embedded = 0
    input_tokens = 0
    cost = 0.0
    for batch in make_batches(prepared, batch_size):
        estimated_batch_cost = _projected_cost(sum(item.token_count for item in batch))
        if cost + estimated_batch_cost > remaining_budget_usd:
            break
        vectors, used_tokens = embedder.embed([item.text for item in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding response count did not match the request")
        by_id = {item.record_id: vector for item, vector in zip(batch, vectors, strict=True)}
        for chunk in chunks:
            if chunk.id in by_id:
                chunk.embedding = by_id[chunk.id]
                chunk.embedding_model = embedder.model
        db.commit()
        embedded += len(batch)
        input_tokens += used_tokens
        cost += _projected_cost(used_tokens)
    return embedded, input_tokens, cost


def run_embedding_pipeline(
    db: Session,
    embedder: Embedder,
    *,
    policy_dir: Path,
    batch_size: int = 64,
    complaint_limit: int | None = None,
    max_cost_usd: float = 1.0,
    include_complaints: bool = True,
    include_policies: bool = True,
) -> EmbeddingRunResult:
    complaint_count = 0
    policy_count = 0
    input_tokens = 0
    cost = 0.0
    if include_policies:
        sync_policy_documents(db, policy_dir)
        policy_count, policy_tokens, policy_cost = _embed_policy_chunks(
            db,
            embedder,
            batch_size=batch_size,
            remaining_budget_usd=max_cost_usd - cost,
        )
        input_tokens += policy_tokens
        cost += policy_cost
    if include_complaints:
        complaint_count, complaint_tokens, complaint_cost = _embed_complaints(
            db,
            embedder,
            batch_size=batch_size,
            limit=complaint_limit,
            remaining_budget_usd=max_cost_usd - cost,
        )
        input_tokens += complaint_tokens
        cost += complaint_cost
    return EmbeddingRunResult(
        complaints_embedded=complaint_count,
        policy_chunks_embedded=policy_count,
        input_tokens=input_tokens,
        estimated_cost_usd=cost,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed complaints and policies into pgvector")
    parser.add_argument("--limit", type=int, help="Maximum complaints to embed in this run")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--complaints-only", action="store_true")
    parser.add_argument("--policies-only", action="store_true")
    args = parser.parse_args()
    if args.complaints_only and args.policies_only:
        parser.error("Choose only one of --complaints-only or --policies-only")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.max_cost_usd <= 0:
        parser.error("--max-cost-usd must be positive")

    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        parser.error("OPENAI_API_KEY is missing from .env")
    embedder = OpenAIEmbedder(
        api_key=api_key,
        model=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
    )
    project_root = Path(__file__).resolve().parents[3]
    with SessionLocal() as db:
        result = run_embedding_pipeline(
            db,
            embedder,
            policy_dir=project_root / "policies",
            batch_size=args.batch_size,
            complaint_limit=args.limit,
            max_cost_usd=args.max_cost_usd,
            include_complaints=not args.policies_only,
            include_policies=not args.complaints_only,
        )
    print(
        "Embedding run complete: "
        f"{result.complaints_embedded} complaints, "
        f"{result.policy_chunks_embedded} policy chunks, "
        f"{result.input_tokens} input tokens, "
        f"estimated cost ${result.estimated_cost_usd:.4f}"
    )


if __name__ == "__main__":
    main()

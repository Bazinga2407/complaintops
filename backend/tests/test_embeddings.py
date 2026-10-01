from app.services.embeddings import (
    MAX_INPUT_TOKENS,
    PreparedText,
    chunk_policy_markdown,
    make_batches,
    prepare_text,
)


def test_policy_markdown_is_split_into_retrievable_sections() -> None:
    sections = chunk_policy_markdown(
        "# Policy\nVersion: 1.0\n\n## Triage\nRoute the case.\n\n## Review\nHuman approval."
    )

    assert [section.heading for section in sections] == ["Overview", "Triage", "Review"]
    assert sections[1].content == "Route the case."


def test_prepare_text_truncates_oversized_inputs() -> None:
    prepared = prepare_text(7, "complaint " * (MAX_INPUT_TOKENS + 500))

    assert prepared.record_id == 7
    assert prepared.token_count == MAX_INPUT_TOKENS


def test_batching_respects_record_limit() -> None:
    items = [PreparedText(record_id=index, text="x", token_count=1) for index in range(5)]

    batches = make_batches(items, batch_size=2)

    assert [len(batch) for batch in batches] == [2, 2, 1]

"""Compile a generated retrieval candidate pack with a separate judgment overlay."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_GRADE_REASONS = {
    0: "Different underlying consumer problem or operational resolution path.",
    1: "Same product or workflow context, but only partially relevant to the core problem.",
    2: "Closely related problem with material shared facts, but a different subtype or outcome.",
    3: "Same core consumer problem and operational resolution path.",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_judgments(candidate_rows: list[dict], label_set: dict) -> dict:
    """Apply audited labels while rejecting missing, duplicate, or stale candidate IDs."""
    label_rows = label_set.get("anchors")
    if not isinstance(label_rows, list):
        raise TypeError("Label set must contain an anchors list")

    labels_by_anchor: dict[int, dict] = {}
    for row in label_rows:
        anchor_id = row.get("anchor_id")
        if not isinstance(anchor_id, int) or anchor_id in labels_by_anchor:
            raise ValueError("Every label anchor_id must be a unique integer")
        labels_by_anchor[anchor_id] = row

    candidate_ids = {row.get("anchor_id") for row in candidate_rows}
    if candidate_ids != set(labels_by_anchor):
        missing = sorted(candidate_ids - set(labels_by_anchor))
        stale = sorted(set(labels_by_anchor) - candidate_ids)
        raise ValueError(f"Label anchors do not match candidates; missing={missing}, stale={stale}")

    compiled_rows = deepcopy(candidate_rows)
    judgment_count = 0
    for row in compiled_rows:
        anchor_id = row["anchor_id"]
        label_row = labels_by_anchor[anchor_id]
        expected_headings = label_row.get("expected_policy_headings")
        if not isinstance(expected_headings, list) or not expected_headings:
            raise ValueError(f"Anchor {anchor_id} needs at least one expected policy heading")
        row["expected_policy_headings"] = expected_headings

        grades = label_row.get("candidate_grades")
        if not isinstance(grades, dict):
            raise TypeError(f"Anchor {anchor_id} must provide candidate_grades")
        actual_ids = {str(candidate["complaint_id"]) for candidate in row["judged_candidates"]}
        if actual_ids != set(grades):
            missing = sorted(actual_ids - set(grades))
            stale = sorted(set(grades) - actual_ids)
            raise ValueError(
                f"Anchor {anchor_id} candidate labels do not match; "
                f"missing={missing}, stale={stale}"
            )

        reasons = label_row.get("candidate_reasons", {})
        for candidate in row["judged_candidates"]:
            key = str(candidate["complaint_id"])
            grade = grades[key]
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
                raise ValueError(f"Anchor {anchor_id} candidate {key} has an invalid grade")
            candidate["relevance_grade"] = grade
            candidate["reason"] = reasons.get(key, DEFAULT_GRADE_REASONS[grade])
            judgment_count += 1

    metadata = {
        key: value for key, value in label_set.items() if key != "anchors"
    }
    metadata.update(
        {
            "anchor_count": len(compiled_rows),
            "candidate_judgment_count": judgment_count,
        }
    )
    return {"metadata": metadata, "judgments": compiled_rows}


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=project_root / "docs" / "retrieval-candidates.json",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=project_root / "docs" / "retrieval-labels.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "docs" / "retrieval-judgments-expanded.json",
    )
    args = parser.parse_args()

    candidate_rows = _load_json(args.candidates)
    if not isinstance(candidate_rows, list):
        parser.error("Candidate file must contain a JSON list")
    label_set = _load_json(args.labels)
    if not isinstance(label_set, dict):
        parser.error("Label file must contain a JSON object")

    compiled = compile_judgments(candidate_rows, label_set)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(compiled, indent=2) + "\n", encoding="utf-8")
    print(
        f"Compiled {compiled['metadata']['anchor_count']} anchors and "
        f"{compiled['metadata']['candidate_judgment_count']} candidate judgments "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()

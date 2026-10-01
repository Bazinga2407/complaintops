import json
from importlib.resources import files

from app.schemas.case import BaselineEvaluation
from app.services.routing import preview_route


def evaluate_mock_routing() -> BaselineEvaluation:
    """Evaluate the deterministic routing baseline on hand-labeled synthetic cases."""
    fixture = files("app.evaluations").joinpath("golden_cases.json")
    examples = json.loads(fixture.read_text(encoding="utf-8"))
    team_correct = 0
    priority_correct = 0
    for example in examples:
        predicted = preview_route(example["product"], example["narrative"])
        team_correct += predicted.team == example["expected_team"]
        priority_correct += predicted.priority == example["expected_priority"]
    count = len(examples)
    return BaselineEvaluation(
        sample_size=count,
        team_accuracy=team_correct / count if count else None,
        priority_accuracy=priority_correct / count if count else None,
        dataset="Eight hand-labeled synthetic intake examples",
        evaluated_system="Deterministic mock routing baseline (not the live AI agent)",
    )

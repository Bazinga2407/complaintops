from app.services.baseline import evaluate_mock_routing


def test_mock_baseline_is_labeled_and_exposes_priority_limitation() -> None:
    result = evaluate_mock_routing()

    assert result.sample_size == 8
    assert result.team_accuracy == 1.0
    assert result.priority_accuracy == 0.875
    assert "not the live AI agent" in result.evaluated_system

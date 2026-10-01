from app.services.privacy import redact_sensitive_text


def test_redacts_common_sensitive_values() -> None:
    result = redact_sensitive_text(
        "Email me at consumer@example.com or 312-555-0198. My SSN is 123-45-6789."
    )

    assert "consumer@example.com" not in result.text
    assert "312-555-0198" not in result.text
    assert "123-45-6789" not in result.text
    assert result.count == 3


def test_preserves_text_without_sensitive_values() -> None:
    narrative = "The transfer has been pending for fourteen days."

    result = redact_sensitive_text(narrative)

    assert result.text == narrative
    assert result.count == 0

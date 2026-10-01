import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    labels: list[str]

    @property
    def count(self) -> int:
        return len(self.labels)


PATTERNS = (
    ("social_security_number", re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b")),
    ("email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone_number", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")),
    (
        "account_number",
        re.compile(r"(?i)\b(account|acct)\s*(number|no\.?|#)?\s*[:=-]?\s*[A-Z0-9-]{6,24}\b"),
    ),
)


def redact_sensitive_text(text: str) -> RedactionResult:
    redacted = text
    labels: list[str] = []
    for label, pattern in PATTERNS:
        redacted, replacements = pattern.subn(f"[{label.upper()} REDACTED]", redacted)
        labels.extend([label] * replacements)
    return RedactionResult(text=redacted, labels=labels)

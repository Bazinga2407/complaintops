import pytest
from fastapi import HTTPException

from app.api.routes.health import ready


class FakeResult:
    def __init__(self, row: tuple[str | None, str | None, str | None]) -> None:
        self.row = row

    def one(self) -> tuple[str | None, str | None, str | None]:
        return self.row


class FakeSession:
    def __init__(self, row: tuple[str | None, str | None, str | None]) -> None:
        self.row = row

    def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self.row)


def test_readiness_requires_initialized_schema() -> None:
    result = ready(FakeSession(("complaints", "cases", "users")))  # type: ignore[arg-type]
    assert result == {"status": "ready", "database": "connected"}

    with pytest.raises(HTTPException) as error:
        ready(FakeSession(("complaints", None, "users")))  # type: ignore[arg-type]
    assert error.value.status_code == 503

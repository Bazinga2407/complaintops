from datetime import date
from typing import Any

import pytest

from app.services.cfpb_client import CfpbClient


class FakeCfpbClient(CfpbClient):
    def __init__(self) -> None:
        super().__init__("https://example.invalid")
        self.calls: list[tuple[int, str | None]] = []

    def fetch_page(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int = 100,
        page_number: int = 1,
        search_after: str | None = None,
        products: list[str] | None = None,
        states: list[str] | None = None,
        narratives_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int, str | None]:
        self.calls.append((page_number, search_after))
        pages = {
            1: ([{"complaint_id": "1"}], 3, "cursor_2"),
            2: ([{"complaint_id": "2"}], 3, "cursor_3"),
            3: ([{"complaint_id": "3"}], 3, None),
        }
        return pages[page_number]


class CursorHorizonClient(CfpbClient):
    def __init__(self) -> None:
        super().__init__("https://example.invalid")
        self.windows: list[tuple[date, date]] = []

    def fetch_page(self, *, date_from: date, date_to: date, **_: Any):
        self.windows.append((date_from, date_to))
        return ([{"complaint_id": str(len(self.windows))}], 10_000, None)


def test_iterator_uses_search_after_cursor() -> None:
    client = FakeCfpbClient()

    rows = list(
        client.iter_complaints(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 2),
            page_size=1,
        )
    )

    assert [row["complaint_id"] for row in rows] == ["1", "2", "3"]
    assert client.calls == [(1, None), (2, "cursor_2"), (3, "cursor_3")]


def test_rejects_page_sizes_without_cursors() -> None:
    client = CfpbClient("https://example.invalid")

    with pytest.raises(ValueError, match="between 1 and 100"):
        client.fetch_page(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 1, 2),
            page_size=101,
        )


def test_iterator_moves_to_next_slice_when_cursor_horizon_is_reached() -> None:
    client = CursorHorizonClient()

    rows = list(
        client.iter_complaints(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 2, 2),
            page_size=1,
        )
    )

    assert [row["complaint_id"] for row in rows] == ["1", "2"]
    assert client.windows == [
        (date(2025, 1, 1), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 2, 1)),
    ]

from collections.abc import Iterator
from datetime import date, timedelta
from time import sleep
from typing import Any

import httpx


class CfpbClient:
    """Small client for the CFPB public Consumer Complaint API."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

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
        if not 1 <= page_size <= 100:
            raise ValueError("CFPB paginated searches require a page size between 1 and 100")
        params = {
            "date_received_min": date_from.isoformat(),
            "date_received_max": date_to.isoformat(),
            "field": "all",
            "no_aggs": "true",
            "size": page_size,
            "frm": 0 if page_number == 1 else page_size,
            "sort": "created_date_asc",
        }
        if page_number > 1:
            params["page"] = page_number
        if search_after:
            params["search_after"] = search_after
        if products:
            params["product"] = products
        if states:
            params["state"] = states
        if narratives_only:
            params["has_narrative"] = "true"
        last_error: httpx.HTTPError | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    response = client.get(self.base_url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                break
            except httpx.HTTPError as error:
                last_error = error
                if attempt == 2:
                    raise
                sleep(2**attempt)
        else:  # pragma: no cover - defensive; the loop always exits or raises
            raise RuntimeError("CFPB request failed") from last_error

        hits_node = payload.get("hits", {})
        raw_hits = hits_node.get("hits", [])
        records = [hit.get("_source", hit) for hit in raw_hits]
        raw_total = hits_node.get("total", 0)
        total = raw_total.get("value", 0) if isinstance(raw_total, dict) else int(raw_total)
        next_break_point = (
            payload.get("_meta", {}).get("break_points", {}).get(str(page_number + 1))
        )
        next_search_after = (
            "_".join(str(value) for value in next_break_point) if next_break_point else None
        )
        return records, total, next_search_after

    def iter_complaints(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int = 100,
        max_records: int | None = None,
        products: list[str] | None = None,
        states: list[str] | None = None,
        narratives_only: bool = False,
    ) -> Iterator[dict[str, Any]]:
        yielded = 0
        slice_from = date_from
        while slice_from < date_to:
            # CFPB date bounds are inclusive. Internally date_to is exclusive, so
            # month-sized slices avoid duplicate boundary days and overly broad
            # searches that exceed the API's finite cursor horizon.
            slice_to = min(slice_from + timedelta(days=31), date_to)
            api_date_to = slice_to - timedelta(days=1)
            page_number = 1
            search_after: str | None = None
            slice_yielded = 0
            while True:
                records, total, next_search_after = self.fetch_page(
                    date_from=slice_from,
                    date_to=api_date_to,
                    page_size=page_size,
                    page_number=page_number,
                    search_after=search_after,
                    products=products,
                    states=states,
                    narratives_only=narratives_only,
                )
                if not records:
                    break
                for record in records:
                    yield record
                    yielded += 1
                    slice_yielded += 1
                    if max_records is not None and yielded >= max_records:
                        return
                if len(records) < page_size or slice_yielded >= total:
                    break
                if not next_search_after:
                    # The API stops publishing cursors at its search horizon. Keep
                    # the rows already yielded and continue with the next slice.
                    break
                page_number += 1
                search_after = next_search_after
            slice_from = slice_to

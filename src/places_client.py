"""
Thin client around the Places API (New) -- Text Search + pagination.

Uses raw `requests` rather than a heavy SDK: the API surface we need is small,
and a direct REST call keeps the dependency footprint (and thing-that-can-break
count) low. Field masks are used on every call, since Places API (New) bills
per-field-group and an unmasked request pulls (and pays for) far more than we need.

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"

# Only request the fields we actually use -- keeps cost down and payloads small.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "nextPageToken",
    ]
)


@dataclass
class PlaceResult:
    place_id: str
    business_name: str
    formatted_address: str | None
    phone: str | None
    website_url: str | None
    rating: float | None
    review_count: int | None
    business_status: str | None


class PlacesClient:
    def __init__(self, api_key: str, requests_per_minute: int = 50):
        self._api_key = api_key
        self._min_interval = 60.0 / max(requests_per_minute, 1)
        self._last_call_ts: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
    )
    def _post(self, body: dict) -> dict:
        self._throttle()
        resp = requests.post(
            SEARCH_TEXT_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            json=body,
            timeout=15,
        )
        if resp.status_code == 429:
            # Let tenacity's backoff handle rate limit responses too.
            raise requests.exceptions.RequestException(f"429 rate limited: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def search_text(self, query: str, max_pages: int = 3) -> list[PlaceResult]:
        """
        Runs a text search, following pagination up to `max_pages` (Places API
        returns up to 20 results per page). 3 pages = up to 60 results per query,
        which matches the legacy API's cap and is plenty for a per-city-per-niche query.
        """
        results: list[PlaceResult] = []
        page_token: str | None = None

        for page_num in range(max_pages):
            body: dict = {"textQuery": query, "maxResultCount": 20}
            if page_token:
                body["pageToken"] = page_token

            try:
                data = self._post(body)
            except requests.exceptions.RequestException as exc:
                logger.error("Places search failed for query=%r: %s", query, exc)
                break

            places = data.get("places", [])
            for p in places:
                results.append(
                    PlaceResult(
                        place_id=p["id"],
                        business_name=p.get("displayName", {}).get("text", "Unknown"),
                        formatted_address=p.get("formattedAddress"),
                        phone=p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
                        website_url=p.get("websiteUri"),
                        rating=p.get("rating"),
                        review_count=p.get("userRatingCount"),
                        business_status=p.get("businessStatus"),
                    )
                )

            page_token = data.get("nextPageToken")
            logger.info(
                "query=%r page=%d results=%d has_more=%s",
                query, page_num + 1, len(places), bool(page_token),
            )
            if not page_token:
                break

            # Google requires a short delay before the next page token becomes valid.
            time.sleep(2)

        return results

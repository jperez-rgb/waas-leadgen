"""
For leads with no website (or a dead one), searches the web via Searlo
(https://searlo.tech -- a SERP API, chosen after discovering Google's Custom
Search JSON API is closed to new customers as of 2025) for their business
name + city, and scans the returned SNIPPET TEXT ONLY for a published email --
never fetches or scrapes the actual destination pages (directories, Yelp,
BBB, etc. all have their own ToS around automated access; consuming a search
API's own output sidesteps that entirely).

Cost: $0.30 per 1,000 queries (Searlo pricing as of setup time -- confirm
current pricing before a large run, since third-party API pricing can change).

Endpoint/response format confirmed live on 2026-08-20: GET /api/v1/search
returns results under "organic", each with "title"/"link"/"snippet" fields
(their docs showed a different, incorrect shape elsewhere -- this is what's
actually live).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.searlo.tech/api/v1/search"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

JUNK_EMAIL_SUBSTRINGS = [
    "example.com", "sentry.io", "wixpress.com", "godaddy.com",
    "schema.org", "yourdomain.com", "domain.com", "@2x",
    "wikimedia.org", "gstatic.com", "googleusercontent.com",
]


@dataclass
class SnippetSearchResult:
    email: str | None
    confidence: str
    source_url: str | None
    notes: str


def _clean_candidates(raw_emails: list[str]) -> list[str]:
    seen = []
    for e in raw_emails:
        e_lower = e.lower().strip().rstrip(".,;")
        if any(junk in e_lower for junk in JUNK_EMAIL_SUBSTRINGS):
            continue
        if e_lower not in seen:
            seen.append(e_lower)
    return seen


class GoogleSnippetFinder:
    def __init__(self, api_key: str):
        self._api_key = api_key

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
    )
    def _search(self, query: str) -> dict:
        resp = requests.get(
            SEARCH_URL,
            headers={"X-API-Key": self._api_key},
            params={"q": query},
            timeout=15,
        )
        if resp.status_code == 429:
            raise requests.exceptions.RequestException("429 rate limited")
        resp.raise_for_status()
        return resp.json()

    def find_email(self, business_name: str, city: str) -> SnippetSearchResult:
        query = f'"{business_name}" {city} FL contact email'
        try:
            data = self._search(query)
        except Exception as exc:
            return SnippetSearchResult(
                email=None, confidence="none", source_url=None,
                notes=f"Search API call failed: {exc.__class__.__name__}",
            )

        results = data.get("organic", [])
        for item in results:
            text_blob = " ".join([item.get("title", ""), item.get("snippet", "")])
            candidates = _clean_candidates(EMAIL_RE.findall(text_blob))
            if candidates:
                return SnippetSearchResult(
                    email=candidates[0], confidence="search_snippet",
                    source_url=item.get("link"),
                    notes=f"Found in search snippet for {item.get('link', 'unknown source')}.",
                )

        return SnippetSearchResult(
            email=None, confidence="none", source_url=None,
            notes=f"No email found in top {len(results)} search results.",
        )

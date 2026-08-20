"""
For leads with no website (or a dead one), searches Google via the Custom
Search JSON API for their business name + city, and scans the returned
SNIPPET TEXT ONLY for a published email -- never fetches or scrapes the
actual destination pages (directories, Yelp, BBB, etc. all have their own
ToS around automated access; consuming Google's own search API output
sidesteps that entirely, since we're reading what Google chose to show in
its own result preview, not scraping a third-party site ourselves).

Cost: ~$5 per 1,000 queries after a small daily free tier. Expect a modest,
not high, hit rate -- most business listings show phone/address/hours in
their snippet, not email.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

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
    def __init__(self, api_key: str, cx: str):
        self._api_key = api_key
        self._cx = cx

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
    )
    def _search(self, query: str) -> dict:
        resp = requests.get(
            SEARCH_URL,
            params={"key": self._api_key, "cx": self._cx, "q": query, "num": 10},
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

        items = data.get("items", [])
        for item in items:
            text_blob = " ".join([
                item.get("title", ""),
                item.get("snippet", ""),
                item.get("displayLink", ""),
            ])
            candidates = _clean_candidates(EMAIL_RE.findall(text_blob))
            if candidates:
                return SnippetSearchResult(
                    email=candidates[0], confidence="search_snippet",
                    source_url=item.get("link"),
                    notes=f"Found in Google search snippet for {item.get('displayLink', 'unknown source')}.",
                )

        return SnippetSearchResult(
            email=None, confidence="none", source_url=None,
            notes=f"No email found in top {len(items)} search snippets.",
        )

"""
Visits a business's website with Playwright and classifies it into one of the
`website_status` buckets defined in migrations/001_init.sql.

This is deliberately heuristic, not a perfect classifier -- it's meant to do the
first-pass triage across hundreds of leads so a human only has to eyeball the
borderline cases, not start from zero. Every grading run stores its reasoning
in `website_notes` so you can sanity-check (and tune the heuristics) later.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Free/low-effort site builders -- a domain on one of these almost always means
# "no real website," even if it technically loads fine.
PLACEHOLDER_HOST_SUBSTRINGS = [
    "sites.google.com",
    "linktr.ee",
    "facebook.com",
    "business.site",       # Google Business free site builder
    "godaddysites.com",
    "weebly.com",
    "wixsite.com",
    "square.site",
    "carrd.co",
]

THIN_CONTENT_WORD_THRESHOLD = 40   # fewer real words than this -> "thin"
OUTDATED_COPYRIGHT_YEAR_CUTOFF = 2020  # copyright year older than this -> "outdated" signal

COPYRIGHT_YEAR_RE = re.compile(r"(?:©|copyright)\D{0,10}(20\d{2})", re.IGNORECASE)


@dataclass
class GradeResult:
    status: str          # one of the website_status enum values
    notes: str
    word_count: int = 0
    has_viewport_meta: bool = False
    copyright_year: int | None = None
    screenshot_path: str | None = None


def _host_is_placeholder_builder(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(sub in host for sub in PLACEHOLDER_HOST_SUBSTRINGS)


def _grade_page(page, url: str, screenshot_dir: str | None, timeout_ms: int) -> GradeResult:
    """Core grading logic against an already-open page. Split out so both the
    'reuse one browser per worker' path and the old 'launch fresh browser'
    path share identical logic -- only page/browser lifecycle differs."""
    page.set_default_timeout(timeout_ms)

    try:
        response = page.goto(url, wait_until="domcontentloaded")
    except PlaywrightError as exc:
        logger.info("Unreachable: %s (%s)", url, exc)
        return GradeResult(
            status="unreachable",
            notes=f"Failed to load: {exc.__class__.__name__}: {str(exc)[:200]}",
        )

    if response is not None and response.status >= 400:
        if response.status in (401, 403, 429, 503):
            return GradeResult(
                status="unreachable",
                notes=(
                    f"HTTP {response.status} -- likely bot-detection blocking the "
                    f"automated check, NOT necessarily a real outage. "
                    f"VERIFY MANUALLY in a real browser before using this as a pitch point."
                ),
            )
        return GradeResult(
            status="unreachable",
            notes=f"Site returned HTTP {response.status}.",
        )

    page.wait_for_timeout(1500)

    try:
        text_content = page.evaluate("document.body ? document.body.innerText : ''") or ""
        has_viewport_meta = page.evaluate(
            "!!document.querySelector('meta[name=\"viewport\"]')"
        )
    except PlaywrightError as exc:
        logger.info("Execution context lost while reading %s (likely a redirect): %s", url, exc)
        return GradeResult(
            status="unreachable",
            notes=(
                "Page kept redirecting/navigating while we tried to read it -- "
                "could not reliably analyze. VERIFY MANUALLY before treating as broken."
            ),
        )

    year_match = COPYRIGHT_YEAR_RE.search(text_content)
    copyright_year = int(year_match.group(1)) if year_match else None
    word_count = len(text_content.split())

    screenshot_path = None
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", urlparse(url).netloc)[:80]
        screenshot_path = os.path.join(screenshot_dir, f"{safe_name}_{int(time.time())}.png")
        try:
            page.screenshot(path=screenshot_path, full_page=False)
        except PlaywrightError:
            screenshot_path = None

    if _host_is_placeholder_builder(url):
        status = "thin"
        notes = f"Hosted on a free site builder ({urlparse(url).netloc}); treat as no real website."
    elif word_count < THIN_CONTENT_WORD_THRESHOLD:
        status = "thin"
        notes = f"Only ~{word_count} words of visible content -- effectively a placeholder page."
    elif copyright_year and copyright_year < OUTDATED_COPYRIGHT_YEAR_CUTOFF:
        status = "outdated"
        notes = f"Copyright year {copyright_year}; likely stale design/content."
    elif not has_viewport_meta:
        status = "outdated"
        notes = "No mobile viewport meta tag -- site is not mobile-responsive."
    else:
        status = "ok"
        notes = f"Loaded fine, {word_count} words, mobile-responsive. Looks like a real site."

    return GradeResult(
        status=status,
        notes=notes,
        word_count=word_count,
        has_viewport_meta=has_viewport_meta,
        copyright_year=copyright_year,
        screenshot_path=screenshot_path,
    )


def grade_website(url: str | None, screenshot_dir: str | None = None,
                   timeout_ms: int = 15000, browser=None) -> GradeResult:
    """
    If `browser` is provided (an already-launched Playwright Browser), reuses
    it -- just opens and closes a page, not a whole new browser process. This
    is the path run_grade() uses: one browser launched per worker thread for
    the entire batch, instead of one browser per lead. Launching/tearing down
    a full Chromium process 25,000+ times (even at low concurrency) is exactly
    the kind of pattern that causes gradual memory creep on a constrained
    instance -- reusing one browser per thread for the whole run fixes that
    at the root instead of just lowering worker count further.

    If `browser` is None (e.g. calling this function standalone, outside the
    batch pipeline), falls back to the original launch-a-fresh-browser
    behavior so this function still works on its own.
    """
    if not url:
        return GradeResult(status="none", notes="No website listed on Google Business Profile.")

    if browser is not None:
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        )
        try:
            return _grade_page(page, url, screenshot_dir, timeout_ms)
        finally:
            page.close()

    with sync_playwright() as p:
        fresh_browser = p.chromium.launch(headless=True)
        try:
            page = fresh_browser.new_page(
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            try:
                return _grade_page(page, url, screenshot_dir, timeout_ms)
            finally:
                page.close()
        finally:
            fresh_browser.close()

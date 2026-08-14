"""
Visits a lead's website looking for a scrapable contact email. Only worth running
on Bucket A (real, working-enough domain) -- see config.NON_SCRAPABLE_EMAIL_HOSTS
for the hosts this deliberately skips.

Strategy, in order of trust:
  1. mailto: links anywhere on the homepage (highest confidence -- explicitly
     published as a contact method)
  2. Plain-text email pattern on the homepage
  3. If nothing found, follow a same-site "contact us" link and repeat 1-2

We deliberately do NOT guess addresses like info@domain.com when nothing is
published -- an unpublished guess is far more likely to bounce or, worse, land
on someone who never agreed to be contacted this way.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .config import NON_SCRAPABLE_EMAIL_HOSTS

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Generic addresses that exist on every site's shared hosting/template and are
# not the business's own -- filter these out if they slip through.
JUNK_EMAIL_SUBSTRINGS = [
    "example.com", "sentry.io", "wixpress.com", "godaddy.com",
    "yourdomain.com", "domain.com", "@2x", "schema.org",
]

CONTACT_LINK_TEXT_RE = re.compile(r"contact|reach us|get in touch", re.IGNORECASE)


@dataclass
class EmailFindResult:
    email: str | None
    confidence: str  # 'mailto' | 'text_pattern' | 'none'
    source_url: str | None
    notes: str


def _is_scrapable(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return not any(bad in host for bad in NON_SCRAPABLE_EMAIL_HOSTS)


def _clean_candidates(raw_emails: list[str]) -> list[str]:
    seen = []
    for e in raw_emails:
        e_lower = e.lower().strip().rstrip(".,;")
        if any(junk in e_lower for junk in JUNK_EMAIL_SUBSTRINGS):
            continue
        if e_lower not in seen:
            seen.append(e_lower)
    return seen


def _extract_from_page(page) -> tuple[str | None, str]:
    """Returns (email, confidence) from the currently loaded page."""
    try:
        # mailto links first -- highest trust
        mailto_hrefs = page.eval_on_selector_all(
            "a[href^='mailto:']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        mailto_emails = _clean_candidates(
            [h.replace("mailto:", "").split("?")[0] for h in mailto_hrefs if h]
        )
        if mailto_emails:
            return mailto_emails[0], "mailto"

        # fall back to plain-text pattern match on visible body text
        body_text = page.evaluate("document.body ? document.body.innerText : ''") or ""
        text_emails = _clean_candidates(EMAIL_RE.findall(body_text))
        if text_emails:
            return text_emails[0], "text_pattern"
    except PlaywrightError:
        # Same redirect-mid-evaluate scenario as the site grader -- treat as
        # "nothing found" rather than propagating the crash.
        return None, "none"

    return None, "none"


def _find_email_on_page(page, url: str) -> EmailFindResult:
    """Core email-finding logic against an already-open page. Split out so
    both the shared-browser path and the standalone-launch path use identical
    logic -- only page/browser lifecycle differs."""
    try:
        page.goto(url, wait_until="domcontentloaded")
    except PlaywrightError as exc:
        return EmailFindResult(
            email=None, confidence="none", source_url=url,
            notes=f"Could not load site to search for email: {exc.__class__.__name__}",
        )
    page.wait_for_timeout(1000)

    email, confidence = _extract_from_page(page)
    if email:
        return EmailFindResult(email=email, confidence=confidence, source_url=url, notes="Found on homepage.")

    try:
        contact_href = page.eval_on_selector_all(
            "a",
            """els => {
                const rx = /contact|reach us|get in touch/i;
                for (const e of els) {
                    if (rx.test(e.innerText || '')) return e.getAttribute('href');
                }
                return null;
            }""",
        )
    except PlaywrightError:
        contact_href = None
    if contact_href:
        contact_url = urljoin(url, contact_href)
        try:
            page.goto(contact_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            email, confidence = _extract_from_page(page)
            if email:
                return EmailFindResult(
                    email=email, confidence=confidence, source_url=contact_url,
                    notes="Found on contact page.",
                )
        except PlaywrightError:
            pass

    return EmailFindResult(
        email=None, confidence="none", source_url=url,
        notes="No published email found on homepage or contact page.",
    )


def find_email(url: str, timeout_ms: int = 15000, browser=None) -> EmailFindResult:
    """
    Same reasoning as site_grader.grade_website: if `browser` is provided,
    reuses it (one browser per worker thread for the whole batch) instead of
    launching a fresh browser process per lead. Falls back to launching its
    own browser if called standalone with browser=None.
    """
    if not url or not _is_scrapable(url):
        return EmailFindResult(
            email=None, confidence="none", source_url=None,
            notes="Site is on a social/builder platform with no scrapable email.",
        )

    if browser is not None:
        page = browser.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            return _find_email_on_page(page, url)
        finally:
            page.close()

    with sync_playwright() as p:
        fresh_browser = p.chromium.launch(headless=True)
        try:
            page = fresh_browser.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                return _find_email_on_page(page, url)
            finally:
                page.close()
        finally:
            fresh_browser.close()

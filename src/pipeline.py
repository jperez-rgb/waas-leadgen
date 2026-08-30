"""
Orchestrates the phases of the Lead Generation + Outreach Engine.
Run via run.py, not this file directly.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from playwright.sync_api import sync_playwright

from . import db
from .config import NICHES, TARGET_AREAS, Settings
from .email_finder import EmailFindResult, find_email
from .instantly_client import InstantlyClient
from .notify import notify
from .places_client import PlacesClient
from .site_grader import GradeResult, grade_website
from .snippet_search_finder import GoogleSnippetFinder, SnippetSearchResult
from .whois_finder import WhoisResult, find_whois_email

logger = logging.getLogger(__name__)

_progress_lock = threading.Lock()

BROWSER_RECYCLE_EVERY = 50

_thread_local = threading.local()


def _get_thread_browser():
    needs_new = (
        not hasattr(_thread_local, "browser")
        or _thread_local.count >= BROWSER_RECYCLE_EVERY
    )
    if needs_new:
        if hasattr(_thread_local, "browser"):
            try:
                _thread_local.browser.close()
                _thread_local.playwright.stop()
            except Exception:
                pass
        playwright = sync_playwright().start()
        _thread_local.playwright = playwright
        _thread_local.browser = playwright.chromium.launch(headless=True)
        _thread_local.count = 0
    _thread_local.count += 1
    return _thread_local.browser


def run_scrape(settings: Settings, niches: list[tuple[str, str]] | None = None) -> None:
    """
    `niches` defaults to the main NICHES list (JoshWeb's own service niches)
    if not provided -- pass LAAS_NICHES to run a separate scrape for the
    JoshWeb Leads product line without touching JoshWeb's own target niches.
    """
    active_niches = niches if niches is not None else NICHES
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    places = PlacesClient(
        api_key=settings.google_places_api_key,
        requests_per_minute=settings.places_requests_per_minute,
    )

    total_queries = len(TARGET_AREAS) * len(active_niches)
    total_upserted = 0
    skipped = 0
    query_num = 0

    for query_fragment, city, county in TARGET_AREAS:
        for niche_label, niche_key in active_niches:
            query_num += 1
            query = f"{niche_label} in {query_fragment}"

            if db.is_query_completed(client, query):
                skipped += 1
                continue

            results = places.search_text(query)
            for place in results:
                db.upsert_place(
                    client, place, city=city, county=county,
                    source_query=query, niche=niche_key,
                )
            total_upserted += len(results)
            db.mark_query_completed(client, query)
            logger.info(
                "[%d/%d] Upserted %d leads for %r",
                query_num, total_queries, len(results), query,
            )

    logger.info(
        "Scrape phase complete. Total leads upserted (incl. duplicates/updates): %d. "
        "Skipped %d already-completed queries from a prior run.",
        total_upserted, skipped,
    )
    notify(
        f"🔍 Scrape phase complete. {total_upserted} leads upserted "
        f"({skipped} queries skipped as already done) across {len(TARGET_AREAS)} cities × {len(active_niches)} niches."
    )


def _grade_one(lead: dict, settings: Settings) -> tuple[dict, GradeResult]:
    url = lead.get("website_url")
    time.sleep(random.uniform(0, 1.5))
    try:
        browser = _get_thread_browser()
        grade = grade_website(url, screenshot_dir=settings.screenshot_dir,
                               timeout_ms=settings.site_grade_timeout_ms, browser=browser)
    except Exception as exc:
        logger.error("Unexpected error grading %s (%s): %s -- marking for manual review, continuing.",
                     lead.get("business_name"), url, exc)
        grade = GradeResult(
            status="unreachable",
            notes=f"Grading crashed unexpectedly ({exc.__class__.__name__}): {str(exc)[:200]}. VERIFY MANUALLY.",
        )
    return lead, grade


def run_grade(settings: Settings, max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_ungraded_leads(
        client, min_rating=settings.min_rating, min_reviews=settings.min_reviews,
        limit=max_leads or 500,
    )

    total = len(leads)
    logger.info("Grading %d leads that meet the reputation bar (rating>=%.1f, reviews>=%d) using %d workers",
                total, settings.min_rating, settings.min_reviews, settings.grade_workers)

    completed = 0
    with ThreadPoolExecutor(max_workers=settings.grade_workers) as pool:
        futures = {pool.submit(_grade_one, lead, settings): lead for lead in leads}
        for future in as_completed(futures):
            lead, grade = future.result()
            db.upsert_grade(client, lead["place_id"], grade)

            with _progress_lock:
                completed += 1
                current = completed

            logger.info(
                "[%d/%d] %s -> %s (%s)",
                current, total, lead.get("business_name"), grade.status,
                lead.get("website_url") or "no website",
            )

    logger.info("Grade phase complete.")
    notify(f"✅ Grade phase complete. {total} leads graded.")


def _find_email_one(lead: dict, settings: Settings) -> tuple[dict, EmailFindResult]:
    url = lead.get("website_url")
    time.sleep(random.uniform(0, 1.5))
    try:
        browser = _get_thread_browser()
        result = find_email(url, timeout_ms=settings.site_grade_timeout_ms, browser=browser)
    except Exception as exc:
        logger.error("Unexpected error finding email on %s (%s): %s -- skipping, continuing.",
                     lead.get("business_name"), url, exc)
        result = EmailFindResult(
            email=None, confidence="none", source_url=url,
            notes=f"Email search crashed unexpectedly ({exc.__class__.__name__}): {str(exc)[:200]}",
        )
    return lead, result


def run_find_emails(settings: Settings, max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_bucket_a_leads_for_email_search(
        client, min_rating=settings.min_rating, min_reviews=settings.min_reviews,
        limit=max_leads or 500,
    )
    total = len(leads)
    logger.info("Searching for emails on %d Bucket A leads using %d workers", total, settings.grade_workers)

    found_count = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=settings.grade_workers) as pool:
        futures = {pool.submit(_find_email_one, lead, settings): lead for lead in leads}
        for future in as_completed(futures):
            lead, result = future.result()
            db.upsert_email_search_result(
                client, lead["place_id"], result.email, result.confidence,
                result.source_url, result.notes,
            )
            if result.email:
                found_count += 1

            with _progress_lock:
                completed += 1
                current = completed

            logger.info(
                "[%d/%d] %s -> %s (%s)",
                current, total, lead.get("business_name"), result.email or "NOT FOUND", result.confidence,
            )

    logger.info("Email search complete. Found emails for %d/%d leads.", found_count, total)
    notify(f"📧 Email search complete. Found {found_count}/{total} emails.")


def _whois_one(lead: dict) -> tuple[dict, WhoisResult]:
    time.sleep(random.uniform(0.3, 1.0))
    try:
        result = find_whois_email(lead.get("website_url"))
    except Exception as exc:
        logger.error("Unexpected error on WHOIS lookup for %s: %s -- skipping.",
                     lead.get("business_name"), exc)
        result = WhoisResult(email=None, confidence="none", notes=f"WHOIS crashed: {exc.__class__.__name__}")
    return lead, result


def run_find_whois_emails(settings: Settings, max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_unreachable_leads_for_whois_search(client, limit=max_leads or 500)
    total = len(leads)
    logger.info("Running WHOIS/RDAP lookups on %d unreachable-domain leads", total)

    found_count = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_whois_one, lead): lead for lead in leads}
        for future in as_completed(futures):
            lead, result = future.result()
            db.upsert_email_search_result(
                client, lead["place_id"], result.email, result.confidence,
                lead.get("website_url"), result.notes,
            )
            if result.email:
                found_count += 1

            with _progress_lock:
                completed += 1
                current = completed

            logger.info(
                "[%d/%d] %s -> %s",
                current, total, lead.get("business_name"), result.email or "NOT FOUND",
            )

    logger.info("WHOIS search complete. Found emails for %d/%d leads.", found_count, total)
    notify(f"🔎 WHOIS search complete. Found {found_count}/{total} emails from dead domains.")


def _snippet_one(lead: dict, finder: GoogleSnippetFinder) -> tuple[dict, SnippetSearchResult]:
    try:
        result = finder.find_email(lead.get("business_name", ""), lead.get("city", ""))
    except Exception as exc:
        logger.error("Unexpected error on snippet search for %s: %s -- skipping.",
                     lead.get("business_name"), exc)
        result = SnippetSearchResult(email=None, confidence="none", source_url=None,
                                      notes=f"Snippet search crashed: {exc.__class__.__name__}")
    return lead, result


def run_find_snippet_emails(searlo_api_key: str,
                             settings: Settings, max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_leads_for_snippet_search(client, limit=max_leads or 500)
    total = len(leads)
    logger.info("Running snippet searches on %d leads with no confirmed email "
                "(estimated cost: ~$%.2f at $0.30/1000 queries)", total, total * 0.0003)

    finder = GoogleSnippetFinder(searlo_api_key)

    found_count = 0
    delay_seconds = 0.3

    for i, lead in enumerate(leads, start=1):
        lead, result = _snippet_one(lead, finder)
        db.upsert_email_search_result(
            client, lead["place_id"], result.email, result.confidence,
            result.source_url, result.notes,
        )
        if result.email:
            found_count += 1

        logger.info(
            "[%d/%d] %s -> %s",
            i, total, lead.get("business_name"), result.email or "NOT FOUND",
        )
        time.sleep(delay_seconds)

    logger.info("Snippet search complete. Found %d/%d emails. Actual cost: ~$%.2f",
                found_count, total, total * 0.0003)
    notify(f"🔍 Snippet search complete. Found {found_count}/{total} emails. Cost: ~${total * 0.0003:.2f}")


def run_push_instantly(settings: Settings, api_key: str, campaign_id: str,
                        max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    instantly = InstantlyClient(api_key)
    leads = db.get_leads_ready_for_instantly(client, limit=max_leads or 500)

    logger.info("Pushing %d leads with a found email into Instantly campaign %s", len(leads), campaign_id)

    pushed, failed = 0, 0
    for i, lead in enumerate(leads, start=1):
        try:
            instantly.add_lead(
                campaign_id=campaign_id,
                email=lead["contact_email"],
                company_name=lead.get("business_name"),
                website=lead.get("website_url"),
                phone=lead.get("phone"),
                custom_variables={
                    "city": lead.get("city") or "",
                    "county": lead.get("county") or "",
                    "website_status": lead.get("website_status") or "",
                    "website_notes": (lead.get("website_notes") or "")[:500],
                    "rating": lead.get("rating") or 0,
                    "review_count": lead.get("review_count") or 0,
                },
            )
            db.mark_lead_queued(client, lead["place_id"])
            pushed += 1
            logger.info("[%d/%d] Pushed %s (%s)", i, len(leads), lead.get("business_name"), lead["contact_email"])
        except Exception as exc:
            db.mark_lead_push_failed(client, lead["place_id"], f"Instantly push failed: {exc}")
            failed += 1
            logger.error("[%d/%d] FAILED to push %s: %s", i, len(leads), lead.get("business_name"), exc)

        time.sleep(1.0)

    logger.info("Instantly push complete. Pushed: %d, Failed: %d", pushed, failed)
    notify(f"🚀 Instantly push complete. Pushed {pushed}, failed {failed}.")


def print_golden_leads_summary(settings: Settings) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_golden_leads(client, settings.min_rating, settings.min_reviews)

    print(f"\n{len(leads)} golden leads found:\n")
    for lead in leads:
        print(
            f"  {lead['business_name']:<45} {lead['city']:<20} "
            f"{lead['rating']}★ ({lead['review_count']}) "
            f"[{lead['website_status']}] {lead.get('phone') or 'no phone'}"
        )

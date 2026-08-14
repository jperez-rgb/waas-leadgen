"""
Orchestrates the two phases of the Lead Generation Engine:

  1. scrape  -- walk every (niche x city) combo in TARGET_AREAS, pull results
                from Places API, upsert into Supabase.
  2. grade   -- pull leads that clear the rating/review bar and haven't been
                graded yet, visit each website with Playwright, classify it,
                write the result back.

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

logger = logging.getLogger(__name__)

# Shared progress counter across worker threads. A plain int with a lock is
# enough here -- we only need "how many done so far" for log lines, not
# anything more sophisticated.
_progress_lock = threading.Lock()

# One Playwright browser per worker THREAD, recycled (closed + relaunched)
# every BROWSER_RECYCLE_EVERY leads instead of kept alive for the entire run.
# Reusing forever isn't enough on its own -- visiting thousands of *different*
# websites in one long-lived Chromium process still causes gradual internal
# memory growth (per-site renderer processes, caching) that only a fresh
# browser process resets. Recycling periodically caps that growth instead of
# letting it accumulate for the whole multi-day run.
BROWSER_RECYCLE_EVERY = 200

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
            except Exception:  # noqa: BLE001 -- best-effort cleanup, never let this crash the run
                pass
        playwright = sync_playwright().start()
        _thread_local.playwright = playwright
        _thread_local.browser = playwright.chromium.launch(headless=True)
        _thread_local.count = 0
    _thread_local.count += 1
    return _thread_local.browser


def run_scrape(settings: Settings) -> None:
    """
    Resumable: before running each (niche, city) query, checks scrape_progress
    to see if it already completed successfully in a prior run, and skips it
    if so. This is what makes it safe (and cheap) to restart after a crash,
    a Ctrl+C, or a Render redeploy -- without this, every restart would
    silently re-burn Places API budget re-querying everything from the top,
    even though the resulting rows wouldn't duplicate.
    """
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    places = PlacesClient(
        api_key=settings.google_places_api_key,
        requests_per_minute=settings.places_requests_per_minute,
    )

    total_queries = len(TARGET_AREAS) * len(NICHES)
    total_upserted = 0
    skipped = 0
    query_num = 0

    for query_fragment, city, county in TARGET_AREAS:
        for niche_label, niche_key in NICHES:
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
        f"({skipped} queries skipped as already done) across {len(TARGET_AREAS)} cities × {len(NICHES)} niches."
    )


def _grade_one(lead: dict, settings: Settings) -> tuple[dict, GradeResult]:
    url = lead.get("website_url")
    # Small random stagger even within a worker so N workers starting at once
    # don't all fire their first request in the same instant.
    time.sleep(random.uniform(0, 1.5))
    try:
        browser = _get_thread_browser()
        grade = grade_website(url, screenshot_dir=settings.screenshot_dir,
                               timeout_ms=settings.site_grade_timeout_ms, browser=browser)
    except Exception as exc:  # noqa: BLE001 -- a single site's quirks must never kill a multi-hour batch
        logger.error("Unexpected error grading %s (%s): %s -- marking for manual review, continuing.",
                     lead.get("business_name"), url, exc)
        grade = GradeResult(
            status="unreachable",
            notes=f"Grading crashed unexpectedly ({exc.__class__.__name__}): {str(exc)[:200]}. VERIFY MANUALLY.",
        )
    return lead, grade


def run_grade(settings: Settings, max_leads: int | None = None) -> None:
    """
    Grades leads in parallel using a thread pool. Each worker thread launches
    ONE Playwright browser and reuses it for every lead it processes (see
    _get_thread_browser) -- not a fresh browser per lead. This is safe to
    parallelize since each thread hits a *different* business's website (no
    politeness concern running several at once). Worker count is tunable via
    GRADE_WORKERS since the right number depends on the machine's CPU/memory
    -- on a memory-constrained instance, keep this low (2-3); with more RAM,
    4-8 is reasonable.
    """
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
    except Exception as exc:  # noqa: BLE001 -- same reasoning as run_grade: never let one site kill the batch
        logger.error("Unexpected error finding email on %s (%s): %s -- skipping, continuing.",
                     lead.get("business_name"), url, exc)
        result = EmailFindResult(
            email=None, confidence="none", source_url=url,
            notes=f"Email search crashed unexpectedly ({exc.__class__.__name__}): {str(exc)[:200]}",
        )
    return lead, result


def run_find_emails(settings: Settings, max_leads: int | None = None) -> None:
    """Parallelized the same way as run_grade -- see its docstring for why
    this is safe to run concurrently."""
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
        except Exception as exc:  # noqa: BLE001 -- log and keep going, don't abort the whole batch
            db.mark_lead_push_failed(client, lead["place_id"], f"Instantly push failed: {exc}")
            failed += 1
            logger.error("[%d/%d] FAILED to push %s: %s", i, len(leads), lead.get("business_name"), exc)

        # Instantly's own rate limits apply -- be a little conservative.
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

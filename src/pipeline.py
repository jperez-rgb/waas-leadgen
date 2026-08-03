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
import time

from . import db
from .config import NICHES, TARGET_AREAS, Settings
from .places_client import PlacesClient
from .site_grader import grade_website

logger = logging.getLogger(__name__)


def run_scrape(settings: Settings) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    places = PlacesClient(
        api_key=settings.google_places_api_key,
        requests_per_minute=settings.places_requests_per_minute,
    )

    total_upserted = 0
    for query_fragment, city, county in TARGET_AREAS:
        for niche_label, niche_key in NICHES:
            query = f"{niche_label} in {query_fragment}"
            results = places.search_text(query)
            for place in results:
                db.upsert_place(
                    client, place, city=city, county=county,
                    source_query=query, niche=niche_key,
                )
            total_upserted += len(results)
            logger.info("Upserted %d leads for %r", len(results), query)

    logger.info("Scrape phase complete. Total leads upserted (incl. duplicates/updates): %d",
                total_upserted)


def run_grade(settings: Settings, max_leads: int | None = None) -> None:
    client = db.get_client(settings.supabase_url, settings.supabase_key)
    leads = db.get_ungraded_leads(
        client, min_rating=settings.min_rating, min_reviews=settings.min_reviews,
        limit=max_leads or 500,
    )

    logger.info("Grading %d leads that meet the reputation bar (rating>=%.1f, reviews>=%d)",
                len(leads), settings.min_rating, settings.min_reviews)

    for i, lead in enumerate(leads, start=1):
        url = lead.get("website_url")
        grade = grade_website(url, screenshot_dir=settings.screenshot_dir,
                               timeout_ms=settings.site_grade_timeout_ms)
        db.upsert_grade(client, lead["place_id"], grade)

        logger.info(
            "[%d/%d] %s -> %s (%s)",
            i, len(leads), lead.get("business_name"), grade.status, url or "no website",
        )

        # Be a polite scraper: fixed delay + jitter, not a tight loop.
        # This isn't for evading anything -- it's to avoid hammering small
        # business web hosts and to reduce the odds of your outbound IP
        # getting rate-limited or blocked mid-run.
        time.sleep(settings.site_grade_delay_seconds + random.uniform(0, 1.0))

    logger.info("Grade phase complete.")


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

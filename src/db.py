"""
Thin wrapper around the Supabase Python client. Kept intentionally small --
this is the only file that should ever construct a supabase Client, so if the
schema or client library changes, this is the one place to update.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import Client, create_client

from .places_client import PlaceResult
from .site_grader import GradeResult

logger = logging.getLogger(__name__)


def get_client(url: str, key: str) -> Client:
    return create_client(url, key)


def upsert_place(client: Client, place: PlaceResult, city: str, county: str,
                  source_query: str, niche: str) -> None:
    """Insert or update a lead by place_id. Never overwrites website grading
    fields -- that's a separate step (see upsert_grade)."""
    payload = {
        "place_id": place.place_id,
        "business_name": place.business_name,
        "formatted_address": place.formatted_address,
        "city": city,
        "county": county,
        "phone": place.phone,
        "website_url": place.website_url,
        "rating": place.rating,
        "review_count": place.review_count,
        "source_query": source_query,
        "niche": niche,
    }
    # website_status only gets set to 'none' here if there's truly no website URL;
    # otherwise leave it as whatever it already was (default 'unknown') so the
    # grading step knows to pick it up.
    if not place.website_url:
        payload["website_status"] = "none"
        payload["website_notes"] = "No website listed on Google Business Profile."

    client.table("leads").upsert(payload, on_conflict="place_id").execute()


def get_ungraded_leads(client: Client, min_rating: float, min_reviews: int,
                        limit: int = 500) -> list[dict]:
    """
    Leads that meet the reputation bar (rating/review count) and either have
    a website we haven't visited yet, or no website at all (already gradeable
    without a visit, but we still want them flagged if somehow missed).
    """
    resp = (
        client.table("leads")
        .select("*")
        .eq("website_status", "unknown")
        .gte("rating", min_rating)
        .gte("review_count", min_reviews)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def upsert_grade(client: Client, place_id: str, grade: GradeResult) -> None:
    client.table("leads").update(
        {
            "website_status": grade.status,
            "website_notes": grade.notes,
            "screenshot_path": grade.screenshot_path,
            "website_graded_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("place_id", place_id).execute()


def get_golden_leads(client: Client, min_rating: float, min_reviews: int) -> list[dict]:
    resp = (
        client.table("leads")
        .select("*")
        .eq("is_golden_lead", True)
        .gte("rating", min_rating)
        .gte("review_count", min_reviews)
        .order("review_count", desc=True)
        .execute()
    )
    return resp.data or []

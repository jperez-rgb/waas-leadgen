"""
Thin wrapper around the Supabase Python client. Kept intentionally small --
this is the only file that should ever construct a supabase Client, so if the
schema or client library changes, this is the one place to update.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import Client, create_client

from .config import EXCLUDED_NAME_SUBSTRINGS, infer_city, infer_county
from .places_client import PlaceResult
from .site_grader import GradeResult

logger = logging.getLogger(__name__)


def _is_excluded(business_name: str) -> bool:
    name_lower = business_name.lower()
    return any(substr in name_lower for substr in EXCLUDED_NAME_SUBSTRINGS)


def get_client(url: str, key: str) -> Client:
    return create_client(url, key)


def is_query_completed(client: Client, query: str) -> bool:
    resp = client.table("scrape_progress").select("query").eq("query", query).execute()
    return len(resp.data or []) > 0


def mark_query_completed(client: Client, query: str) -> None:
    client.table("scrape_progress").upsert({"query": query}, on_conflict="query").execute()


def upsert_place(client: Client, place: PlaceResult, city: str, county: str,
                  source_query: str, niche: str) -> None:
    """Insert or update a lead by place_id. Never overwrites website grading
    fields -- that's a separate step (see upsert_grade).

    Skips known national chains/distributors/non-service businesses entirely
    (see EXCLUDED_NAME_SUBSTRINGS) -- wrong customer profile, no point storing them.

    City is derived from the actual formatted_address rather than trusted from
    whichever search query happened to surface this place_id, since Places Text
    Search returns nearby-city results too and a naive overwrite silently
    corrupts the city on re-runs.
    """
    if _is_excluded(place.business_name):
        logger.info("Skipping excluded business: %s", place.business_name)
        return

    resolved_city = infer_city(place.formatted_address, fallback_city=city)
    resolved_county = infer_county(resolved_city, fallback_county=county)

    payload = {
        "place_id": place.place_id,
        "business_name": place.business_name,
        "formatted_address": place.formatted_address,
        "city": resolved_city,
        "county": resolved_county,
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


PAGE_SIZE = 1000  # Supabase's own server-side cap, regardless of what limit we pass -- see functions below.


def get_ungraded_leads(client: Client, min_rating: float, min_reviews: int,
                        limit: int = 500) -> list[dict]:
    """
    Leads that meet the reputation bar (rating/review count) and either have
    a website we haven't visited yet, or no website at all (already gradeable
    without a visit, but we still want them flagged if somehow missed).

    Paginates in pages of PAGE_SIZE. This matters regardless of Supabase's
    project-level "Max Rows" setting: even with that raised, relying on a
    single request to return an arbitrarily large `limit` is fragile -- this
    makes the function actually return up to `limit` rows no matter what,
    without depending on a dashboard setting staying configured correctly.
    """
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        resp = (
            client.table("leads")
            .select("*")
            .eq("website_status", "unknown")
            .gte("rating", min_rating)
            .gte("review_count", min_reviews)
            .range(offset, offset + page_limit - 1)
            .execute()
        )
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break  # fewer rows than asked for -- we've hit the end of what matches
        offset += page_limit
    return all_leads


def upsert_grade(client: Client, place_id: str, grade: GradeResult) -> None:
    client.table("leads").update(
        {
            "website_status": grade.status,
            "website_notes": grade.notes,
            "screenshot_path": grade.screenshot_path,
            "website_graded_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("place_id", place_id).execute()


def get_bucket_a_leads_for_email_search(client: Client, min_rating: float, min_reviews: int,
                                          limit: int = 500) -> list[dict]:
    """
    Bucket A: golden leads with an actual website worth scraping for an email --
    i.e. website_status is thin/outdated/generic_builder (has SOME url) and we
    haven't searched it yet. Excludes 'none'/'unreachable' entirely since those
    have no site to visit in the first place.

    Paginated the same way as get_ungraded_leads -- see its docstring for why.
    """
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        resp = (
            client.table("leads")
            .select("*")
            .in_("website_status", ["thin", "outdated", "generic_builder"])
            .not_.is_("website_url", "null")
            .is_("email_searched_at", "null")
            .gte("rating", min_rating)
            .gte("review_count", min_reviews)
            .not_.is_("phone", "null")
            .range(offset, offset + page_limit - 1)
            .execute()
        )
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
    return all_leads


def upsert_email_search_result(client: Client, place_id: str, email: str | None,
                                 confidence: str, source_url: str | None, notes: str) -> None:
    payload = {
        "email_confidence": confidence,
        "email_source_url": source_url,
        "email_found_notes": notes,
        "email_searched_at": datetime.now(timezone.utc).isoformat(),
    }
    if email:
        payload["contact_email"] = email
    client.table("leads").update(payload).eq("place_id", place_id).execute()


def get_leads_ready_for_instantly(client: Client, limit: int = 500) -> list[dict]:
    """Golden leads with a found email that haven't been pushed to Instantly yet.
    Paginated the same way as get_ungraded_leads -- see its docstring for why."""
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        resp = (
            client.table("leads")
            .select("*")
            .not_.is_("contact_email", "null")
            .eq("email_status", "not_started")
            .range(offset, offset + page_limit - 1)
            .execute()
        )
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
    return all_leads


def mark_lead_queued(client: Client, place_id: str, assigned_domain: str | None = None) -> None:
    payload = {"email_status": "queued"}
    if assigned_domain:
        payload["assigned_sending_domain"] = assigned_domain
    client.table("leads").update(payload).eq("place_id", place_id).execute()


def mark_lead_push_failed(client: Client, place_id: str, note: str) -> None:
    client.table("leads").update(
        {"email_status": "not_started", "email_found_notes": note}
    ).eq("place_id", place_id).execute()


def get_golden_leads(client: Client, min_rating: float, min_reviews: int) -> list[dict]:
    """Only returns leads that also have a phone number -- 'Active' was one of
    the three original criteria, a lead you can't call isn't callable.
    Paginated (no explicit cap here, but Supabase's server-side 1,000-row
    default applies regardless of what we ask for -- this is what makes
    `summary` actually show every golden lead instead of silently truncating)."""
    all_leads: list[dict] = []
    offset = 0
    while True:
        resp = (
            client.table("leads")
            .select("*")
            .eq("is_golden_lead", True)
            .gte("rating", min_rating)
            .gte("review_count", min_reviews)
            .not_.is_("phone", "null")
            .order("review_count", desc=True)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_leads


def update_reply_status(client: Client, place_id: str, status: str, notes: str | None = None) -> None:
    """
    status: one of 'no_reply', 'interested', 'not_interested', 'needs_followup',
    'closed_won', 'closed_lost'. Call this whenever a lead replies to a cold email
    so nothing gets lost -- there's no automatic reply detection here (that would
    need an Instantly webhook, a future addition), this is meant to be updated
    manually via a quick script or the Supabase table editor as replies come in.
    """
    payload: dict = {"reply_status": status, "last_contacted_at": datetime.now(timezone.utc).isoformat()}
    if notes:
        payload["reply_notes"] = notes
    client.table("leads").update(payload).eq("place_id", place_id).execute()


def get_leads_by_reply_status(client: Client, status: str) -> list[dict]:
    resp = client.table("leads").select("*").eq("reply_status", status).execute()
    return resp.data or []


def mark_unsubscribed(client: Client, email: str) -> None:
    """Marks every lead row matching this email as unsubscribed. Wired to
    Instantly's unsubscribe webhook eventually -- for now, callable manually
    if someone emails back asking to be removed."""
    client.table("leads").update(
        {"unsubscribed": True, "email_status": "unsubscribed"}
    ).eq("contact_email", email).execute()

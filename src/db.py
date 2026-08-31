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

PAGE_SIZE = 1000  # Supabase's own server-side cap, regardless of what limit we pass.


def get_client(url: str, key: str) -> Client:
    return create_client(url, key)


def _is_excluded(business_name: str) -> bool:
    name_lower = business_name.lower()
    return any(substr in name_lower for substr in EXCLUDED_NAME_SUBSTRINGS)


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
    if not place.website_url:
        payload["website_status"] = "none"
        payload["website_notes"] = "No website listed on Google Business Profile."

    client.table("leads").upsert(payload, on_conflict="place_id").execute()


def _apply_reputation_filter(query, min_rating: float, min_reviews: int):
    """
    Applies the rating/review-count filter ONLY when it would actually mean
    something (> 0). Real SQL gotcha: NULL >= 0 evaluates to NULL (not true)
    in Postgres, so a naive .gte("rating", 0) silently EXCLUDES every lead
    where Google Places never returned a rating at all -- even though
    min_rating=0 is supposed to mean "no filter, include everyone." Skipping
    the filter entirely when the threshold is 0 avoids that trap.
    """
    if min_rating > 0:
        query = query.gte("rating", min_rating)
    if min_reviews > 0:
        query = query.gte("review_count", min_reviews)
    return query


def get_ungraded_leads(client: Client, min_rating: float, min_reviews: int,
                        limit: int = 500) -> list[dict]:
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        query = (
            client.table("leads")
            .select("*")
            .eq("website_status", "unknown")
        )
        query = _apply_reputation_filter(query, min_rating, min_reviews)
        resp = query.range(offset, offset + page_limit - 1).execute()
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
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
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        query = (
            client.table("leads")
            .select("*")
            .in_("website_status", ["thin", "outdated", "generic_builder"])
            .not_.is_("website_url", "null")
            .is_("email_searched_at", "null")
            .not_.is_("phone", "null")
        )
        query = _apply_reputation_filter(query, min_rating, min_reviews)
        resp = query.range(offset, offset + page_limit - 1).execute()
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
    return all_leads


def get_unreachable_leads_for_whois_search(client: Client, limit: int = 500) -> list[dict]:
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        resp = (
            client.table("leads")
            .select("*")
            .eq("website_status", "unreachable")
            .not_.is_("website_url", "null")
            .is_("email_searched_at", "null")
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


def get_leads_for_snippet_search(client: Client, limit: int = 500) -> list[dict]:
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        resp = (
            client.table("leads")
            .select("*")
            .in_("website_status", ["none", "unreachable"])
            .is_("contact_email", "null")
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
    all_leads: list[dict] = []
    offset = 0
    while True:
        query = (
            client.table("leads")
            .select("*")
            .eq("is_golden_lead", True)
            .not_.is_("phone", "null")
            .order("review_count", desc=True)
        )
        query = _apply_reputation_filter(query, min_rating, min_reviews)
        resp = query.range(offset, offset + PAGE_SIZE - 1).execute()
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_leads


def update_reply_status(client: Client, place_id: str, status: str, notes: str | None = None) -> None:
    payload: dict = {"reply_status": status, "last_contacted_at": datetime.now(timezone.utc).isoformat()}
    if notes:
        payload["reply_notes"] = notes
    client.table("leads").update(payload).eq("place_id", place_id).execute()


def get_leads_by_reply_status(client: Client, status: str) -> list[dict]:
    resp = client.table("leads").select("*").eq("reply_status", status).execute()
    return resp.data or []


def mark_unsubscribed(client: Client, email: str) -> None:
    client.table("leads").update(
        {"unsubscribed": True, "email_status": "unsubscribed"}
    ).eq("contact_email", email).execute()


def get_laas_available_leads(client: Client, exclude_counties: list[str],
                               niches: list[str] | None = None,
                               limit: int = 500) -> list[dict]:
    """
    Leads eligible to sell as part of JoshWeb Leads (LaaS) -- i.e. NOT in
    JoshWeb's own core counties (never sold, those are reserved for JoshWeb's
    own outreach), and marked 'available' (not already sold/reserved to
    another subscriber). Optionally filtered to specific niches.
    """
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        query = (
            client.table("leads")
            .select("*")
            .eq("laas_status", "available")
            .not_.in_("county", exclude_counties)
            .not_.is_("phone", "null")
        )
        if niches:
            query = query.in_("niche", niches)
        resp = query.range(offset, offset + page_limit - 1).execute()
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
    return all_leads


def mark_leads_sold_to(client: Client, place_ids: list[str], subscriber_email: str) -> None:
    """Marks a batch of leads as sold/exclusive to a specific LaaS subscriber
    -- excludes them from all future exports to anyone else."""
    client.table("leads").update({
        "laas_status": "sold",
        "laas_sold_to": subscriber_email,
        "laas_sold_at": datetime.now(timezone.utc).isoformat(),
    }).in_("place_id", place_ids).execute()


def get_laas_leads_for_email_search(client: Client, exclude_counties: list[str],
                                      niches: list[str], limit: int = 500) -> list[dict]:
    """
    LaaS-specific email search targets: agencies in the given niches, outside
    JoshWeb's core counties, with a real website to scrape, that haven't had
    an email search attempted yet. Deliberately does NOT filter on
    website_status -- unlike JoshWeb's own leads, we don't care whether these
    agencies' own sites are good or bad, we just need their contact email, so
    skipping the grading step entirely is fine here.
    """
    all_leads: list[dict] = []
    offset = 0
    while len(all_leads) < limit:
        page_limit = min(PAGE_SIZE, limit - len(all_leads))
        query = (
            client.table("leads")
            .select("*")
            .in_("niche", niches)
            .not_.in_("county", exclude_counties)
            .not_.is_("website_url", "null")
            .is_("email_searched_at", "null")
        )
        resp = query.range(offset, offset + page_limit - 1).execute()
        batch = resp.data or []
        all_leads.extend(batch)
        if len(batch) < page_limit:
            break
        offset += page_limit
    return all_leads

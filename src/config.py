"""
Central configuration. Loads from environment variables (via .env in local dev,
or real env vars on Render). Fails loudly and early if something required is missing
-- better to crash on startup than half-run a scrape with a bad key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass(frozen=True)
class Settings:
    google_places_api_key: str
    supabase_url: str
    supabase_key: str

    # Tuning knobs -- all overridable via env so you don't have to touch code
    # to change scrape pace or thresholds.
    min_rating: float = float(os.getenv("MIN_RATING", "4.0"))
    min_reviews: int = int(os.getenv("MIN_REVIEWS", "15"))

    places_requests_per_minute: int = int(os.getenv("PLACES_RPM", "50"))
    site_grade_delay_seconds: float = float(os.getenv("SITE_GRADE_DELAY_SECONDS", "2.0"))
    site_grade_timeout_ms: int = int(os.getenv("SITE_GRADE_TIMEOUT_MS", "15000"))

    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", "./screenshots")


def load_settings() -> Settings:
    return Settings(
        google_places_api_key=_require("GOOGLE_PLACES_API_KEY"),
        supabase_url=_require("SUPABASE_URL"),
        supabase_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
    )


# Central Florida target list: (search query fragment, city, county)
# This mirrors the manual scope from the original lead list -- edit freely.
TARGET_AREAS: list[tuple[str, str, str]] = [
    ("Lakeland FL", "Lakeland", "Polk"),
    ("Winter Haven FL", "Winter Haven", "Polk"),
    ("Bartow FL", "Bartow", "Polk"),
    ("Davenport FL", "Davenport", "Polk"),
    ("Haines City FL", "Haines City", "Polk"),
    ("Orlando FL", "Orlando", "Orange"),
    ("Apopka FL", "Apopka", "Orange"),
    ("Winter Park FL", "Winter Park", "Orange"),
    ("Winter Garden FL", "Winter Garden", "Orange"),
    ("Ocoee FL", "Ocoee", "Orange"),
    ("Kissimmee FL", "Kissimmee", "Osceola"),
    ("St. Cloud FL", "St. Cloud", "Osceola"),
    ("Celebration FL", "Celebration", "Osceola"),
    ("Sanford FL", "Sanford", "Seminole"),
    ("Altamonte Springs FL", "Altamonte Springs", "Seminole"),
    ("Oviedo FL", "Oviedo", "Seminole"),
    ("Casselberry FL", "Casselberry", "Seminole"),
    ("Clermont FL", "Clermont", "Lake"),
    ("Leesburg FL", "Leesburg", "Lake"),
    ("Mount Dora FL", "Mount Dora", "Lake"),
    ("Tavares FL", "Tavares", "Lake"),
]

NICHES: list[tuple[str, str]] = [
    ("landscaping companies", "landscaping"),
    ("lawn care companies", "lawn_care"),
    ("hardscaping companies", "hardscaping"),
]

"""
Central configuration. Loads from environment variables (via .env in local dev,
or real env vars on Render). Fails loudly and early if something required is missing
-- better to crash on startup than half-run a scrape with a bad key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

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

    min_rating: float = float(os.getenv("MIN_RATING", "0"))
    min_reviews: int = int(os.getenv("MIN_REVIEWS", "0"))

    places_requests_per_minute: int = int(os.getenv("PLACES_RPM", "50"))
    site_grade_delay_seconds: float = float(os.getenv("SITE_GRADE_DELAY_SECONDS", "2.0"))
    site_grade_timeout_ms: int = int(os.getenv("SITE_GRADE_TIMEOUT_MS", "15000"))
    grade_workers: int = int(os.getenv("GRADE_WORKERS", "6"))

    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", "./screenshots")


def load_settings() -> Settings:
    return Settings(
        google_places_api_key=_require("GOOGLE_PLACES_API_KEY"),
        supabase_url=_require("SUPABASE_URL"),
        supabase_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
    )


def load_instantly_key() -> str:
    return _require("INSTANTLY_API_KEY")


def load_instantly_campaign_id() -> str:
    return _require("INSTANTLY_CAMPAIGN_ID")


# Full official list of all 268 incorporated Florida cities (per current Census
# Bureau / Florida League of Cities data), paired with their county. Source:
# Wikipedia "List of municipalities in Florida", filtered to entries labeled
# "City" specifically (excludes towns and villages, which use a different
# governance label but aren't legally distinct -- kept out simply to match
# the well-known "267/268 cities" framing rather than all 411 municipalities).
TARGET_AREAS: list[tuple[str, str, str]] = [
    ("Alachua FL", "Alachua", "Alachua"),
    ("Altamonte Springs FL", "Altamonte Springs", "Seminole"),
    ("Anna Maria FL", "Anna Maria", "Manatee"),
    ("Apalachicola FL", "Apalachicola", "Franklin"),
    ("Apopka FL", "Apopka", "Orange"),
    ("Arcadia FL", "Arcadia", "DeSoto"),
    ("Archer FL", "Archer", "Alachua"),
    ("Atlantic Beach FL", "Atlantic Beach", "Duval"),
    ("Atlantis FL", "Atlantis", "Palm Beach"),
    ("Auburndale FL", "Auburndale", "Polk"),
    ("Aventura FL", "Aventura", "Miami-Dade"),
    ("Avon Park FL", "Avon Park", "Highlands"),
    ("Bartow FL", "Bartow", "Polk"),
    ("Bay Lake FL", "Bay Lake", "Orange"),
    ("Belle Glade FL", "Belle Glade", "Palm Beach"),
    ("Belle Isle FL", "Belle Isle", "Orange"),
    ("Belleair Beach FL", "Belleair Beach", "Pinellas"),
    ("Belleair Bluffs FL", "Belleair Bluffs", "Pinellas"),
    ("Belleview FL", "Belleview", "Marion"),
    ("Blountstown FL", "Blountstown", "Calhoun"),
    ("Boca Raton FL", "Boca Raton", "Palm Beach"),
    ("Bonifay FL", "Bonifay", "Holmes"),
    ("Bonita Springs FL", "Bonita Springs", "Lee"),
    ("Bowling Green FL", "Bowling Green", "Hardee"),
    ("Boynton Beach FL", "Boynton Beach", "Palm Beach"),
    ("Bradenton FL", "Bradenton", "Manatee"),
    ("Bradenton Beach FL", "Bradenton Beach", "Manatee"),
    ("Bristol FL", "Bristol", "Liberty"),
    ("Brooksville FL", "Brooksville", "Hernando"),
    ("Bunnell FL", "Bunnell", "Flagler"),
    ("Bushnell FL", "Bushnell", "Sumter"),
    ("Callaway FL", "Callaway", "Bay"),
    ("Cape Canaveral FL", "Cape Canaveral", "Brevard"),
    ("Cape Coral FL", "Cape Coral", "Lee"),
    ("Carrabelle FL", "Carrabelle", "Franklin"),
    ("Casselberry FL", "Casselberry", "Seminole"),
    ("Cedar Key FL", "Cedar Key", "Levy"),
    ("Center Hill FL", "Center Hill", "Sumter"),
    ("Chattahoochee FL", "Chattahoochee", "Gadsden"),
    ("Chiefland FL", "Chiefland", "Levy"),
    ("Chipley FL", "Chipley", "Washington"),
    ("Clearwater FL", "Clearwater", "Pinellas"),
    ("Clermont FL", "Clermont", "Lake"),
    ("Clewiston FL", "Clewiston", "Hendry"),
    ("Cocoa FL", "Cocoa", "Brevard"),
    ("Cocoa Beach FL", "Cocoa Beach", "Brevard"),
    ("Coconut Creek FL", "Coconut Creek", "Broward"),
    ("Coleman FL", "Coleman", "Sumter"),
    ("Cooper City FL", "Cooper City", "Broward"),
    ("Coral Gables FL", "Coral Gables", "Miami-Dade"),
    ("Coral Springs FL", "Coral Springs", "Broward"),
    ("Crescent City FL", "Crescent City", "Putnam"),
    ("Crestview FL", "Crestview", "Okaloosa"),
    ("Crystal River FL", "Crystal River", "Citrus"),
    ("Dade City FL", "Dade City", "Pasco"),
    ("Dania Beach FL", "Dania Beach", "Broward"),
    ("Davenport FL", "Davenport", "Polk"),
    ("Daytona Beach FL", "Daytona Beach", "Volusia"),
    ("Daytona Beach Shores FL", "Daytona Beach Shores", "Volusia"),
    ("DeBary FL", "DeBary", "Volusia"),
    ("Deerfield Beach FL", "Deerfield Beach", "Broward"),
    ("DeFuniak Springs FL", "DeFuniak Springs", "Walton"),
    ("DeLand FL", "DeLand", "Volusia"),
    ("Delray Beach FL", "Delray Beach", "Palm Beach"),
    ("Deltona FL", "Deltona", "Volusia"),
    ("Destin FL", "Destin", "Okaloosa"),
    ("Doral FL", "Doral", "Miami-Dade"),
    ("Dunedin FL", "Dunedin", "Pinellas"),
    ("Dunnellon FL", "Dunnellon", "Marion"),
    ("Eagle Lake FL", "Eagle Lake", "Polk"),
    ("Edgewater FL", "Edgewater", "Volusia"),
    ("Edgewood FL", "Edgewood", "Orange"),
    ("Eustis FL", "Eustis", "Lake"),
    ("Everglades City FL", "Everglades City", "Collier"),
    ("Fanning Springs FL", "Fanning Springs", "Levy"),
    ("Fellsmere FL", "Fellsmere", "Indian River"),
    ("Fernandina Beach FL", "Fernandina Beach", "Nassau"),
    ("Flagler Beach FL", "Flagler Beach", "Flagler"),
    ("Florida City FL", "Florida City", "Miami-Dade"),
    ("Fort Lauderdale FL", "Fort Lauderdale", "Broward"),
    ("Fort Meade FL", "Fort Meade", "Polk"),
    ("Fort Myers FL", "Fort Myers", "Lee"),
    ("Fort Pierce FL", "Fort Pierce", "St. Lucie"),
    ("Fort Walton Beach FL", "Fort Walton Beach", "Okaloosa"),
    ("Freeport FL", "Freeport", "Walton"),
    ("Frostproof FL", "Frostproof", "Polk"),
    ("Fruitland Park FL", "Fruitland Park", "Lake"),
    ("Gainesville FL", "Gainesville", "Alachua"),
    ("Graceville FL", "Graceville", "Jackson"),
    ("Green Cove Springs FL", "Green Cove Springs", "Clay"),
    ("Greenacres FL", "Greenacres", "Palm Beach"),
    ("Gretna FL", "Gretna", "Gadsden"),
    ("Groveland FL", "Groveland", "Lake"),
    ("Gulf Breeze FL", "Gulf Breeze", "Santa Rosa"),
    ("Gulfport FL", "Gulfport", "Pinellas"),
    ("Haines City FL", "Haines City", "Polk"),
    ("Hallandale Beach FL", "Hallandale Beach", "Broward"),
    ("Hampton FL", "Hampton", "Bradford"),
    ("Hawthorne FL", "Hawthorne", "Alachua"),
    ("Hialeah FL", "Hialeah", "Miami-Dade"),
    ("Hialeah Gardens FL", "Hialeah Gardens", "Miami-Dade"),
    ("High Springs FL", "High Springs", "Alachua"),
    ("Holly Hill FL", "Holly Hill", "Volusia"),
    ("Hollywood FL", "Hollywood", "Broward"),
    ("Holmes Beach FL", "Holmes Beach", "Manatee"),
    ("Homestead FL", "Homestead", "Miami-Dade"),
    ("Indian Harbour Beach FL", "Indian Harbour Beach", "Brevard"),
    ("Indian Rocks Beach FL", "Indian Rocks Beach", "Pinellas"),
    ("Inverness FL", "Inverness", "Citrus"),
    ("Jacksonville FL", "Jacksonville", "Duval"),
    ("Jacksonville Beach FL", "Jacksonville Beach", "Duval"),
    ("Jacob City FL", "Jacob City", "Jackson"),
    ("Jasper FL", "Jasper", "Hamilton"),
    ("Key Colony Beach FL", "Key Colony Beach", "Monroe"),
    ("Key West FL", "Key West", "Monroe"),
    ("Keystone Heights FL", "Keystone Heights", "Clay"),
    ("Kissimmee FL", "Kissimmee", "Osceola"),
    ("LaBelle FL", "LaBelle", "Hendry"),
    ("Lake Alfred FL", "Lake Alfred", "Polk"),
    ("Lake Buena Vista FL", "Lake Buena Vista", "Orange"),
    ("Lake Butler FL", "Lake Butler", "Union"),
    ("Lake City FL", "Lake City", "Columbia"),
    ("Lake Helen FL", "Lake Helen", "Volusia"),
    ("Lake Mary FL", "Lake Mary", "Seminole"),
    ("Lake Wales FL", "Lake Wales", "Polk"),
    ("Lake Worth Beach FL", "Lake Worth Beach", "Palm Beach"),
    ("Lakeland FL", "Lakeland", "Polk"),
    ("Largo FL", "Largo", "Pinellas"),
    ("Lauderdale Lakes FL", "Lauderdale Lakes", "Broward"),
    ("Lauderhill FL", "Lauderhill", "Broward"),
    ("Laurel Hill FL", "Laurel Hill", "Okaloosa"),
    ("Lawtey FL", "Lawtey", "Bradford"),
    ("Layton FL", "Layton", "Monroe"),
    ("Leesburg FL", "Leesburg", "Lake"),
    ("Lighthouse Point FL", "Lighthouse Point", "Broward"),
    ("Live Oak FL", "Live Oak", "Suwannee"),
    ("Longwood FL", "Longwood", "Seminole"),
    ("Lynn Haven FL", "Lynn Haven", "Bay"),
    ("Macclenny FL", "Macclenny", "Baker"),
    ("Madeira Beach FL", "Madeira Beach", "Pinellas"),
    ("Madison FL", "Madison", "Madison"),
    ("Maitland FL", "Maitland", "Orange"),
    ("Marathon FL", "Marathon", "Monroe"),
    ("Marco Island FL", "Marco Island", "Collier"),
    ("Margate FL", "Margate", "Broward"),
    ("Marianna FL", "Marianna", "Jackson"),
    ("Mary Esther FL", "Mary Esther", "Okaloosa"),
    ("Mascotte FL", "Mascotte", "Lake"),
    ("Melbourne FL", "Melbourne", "Brevard"),
    ("Mexico Beach FL", "Mexico Beach", "Bay"),
    ("Miami FL", "Miami", "Miami-Dade"),
    ("Miami Beach FL", "Miami Beach", "Miami-Dade"),
    ("Miami Gardens FL", "Miami Gardens", "Miami-Dade"),
    ("Miami Springs FL", "Miami Springs", "Miami-Dade"),
    ("Midway FL", "Midway", "Gadsden"),
    ("Milton FL", "Milton", "Santa Rosa"),
    ("Minneola FL", "Minneola", "Lake"),
    ("Miramar FL", "Miramar", "Broward"),
    ("Monticello FL", "Monticello", "Jefferson"),
    ("Moore Haven FL", "Moore Haven", "Glades"),
    ("Mount Dora FL", "Mount Dora", "Lake"),
    ("Mulberry FL", "Mulberry", "Polk"),
    ("Naples FL", "Naples", "Collier"),
    ("Neptune Beach FL", "Neptune Beach", "Duval"),
    ("New Port Richey FL", "New Port Richey", "Pasco"),
    ("New Smyrna Beach FL", "New Smyrna Beach", "Volusia"),
    ("Newberry FL", "Newberry", "Alachua"),
    ("Niceville FL", "Niceville", "Okaloosa"),
    ("North Bay Village FL", "North Bay Village", "Miami-Dade"),
    ("North Lauderdale FL", "North Lauderdale", "Broward"),
    ("North Miami FL", "North Miami", "Miami-Dade"),
    ("North Miami Beach FL", "North Miami Beach", "Miami-Dade"),
    ("North Port FL", "North Port", "Sarasota"),
    ("Oak Hill FL", "Oak Hill", "Volusia"),
    ("Oakland Park FL", "Oakland Park", "Broward"),
    ("Ocala FL", "Ocala", "Marion"),
    ("Ocoee FL", "Ocoee", "Orange"),
    ("Okeechobee FL", "Okeechobee", "Okeechobee"),
    ("Oldsmar FL", "Oldsmar", "Pinellas"),
    ("Opa-locka FL", "Opa-locka", "Miami-Dade"),
    ("Orange City FL", "Orange City", "Volusia"),
    ("Orlando FL", "Orlando", "Orange"),
    ("Ormond Beach FL", "Ormond Beach", "Volusia"),
    ("Oviedo FL", "Oviedo", "Seminole"),
    ("Pahokee FL", "Pahokee", "Palm Beach"),
    ("Palatka FL", "Palatka", "Putnam"),
    ("Palm Bay FL", "Palm Bay", "Brevard"),
    ("Palm Beach Gardens FL", "Palm Beach Gardens", "Palm Beach"),
    ("Palm Coast FL", "Palm Coast", "Flagler"),
    ("Palmetto FL", "Palmetto", "Manatee"),
    ("Panama City FL", "Panama City", "Bay"),
    ("Panama City Beach FL", "Panama City Beach", "Bay"),
    ("Parker FL", "Parker", "Bay"),
    ("Parkland FL", "Parkland", "Broward"),
    ("Pembroke Pines FL", "Pembroke Pines", "Broward"),
    ("Pensacola FL", "Pensacola", "Escambia"),
    ("Perry FL", "Perry", "Taylor"),
    ("Pinellas Park FL", "Pinellas Park", "Pinellas"),
    ("Plant City FL", "Plant City", "Hillsborough"),
    ("Plantation FL", "Plantation", "Broward"),
    ("Polk City FL", "Polk City", "Polk"),
    ("Pompano Beach FL", "Pompano Beach", "Broward"),
    ("Port Orange FL", "Port Orange", "Volusia"),
    ("Port Richey FL", "Port Richey", "Pasco"),
    ("Port St. Joe FL", "Port St. Joe", "Gulf"),
    ("Port St. Lucie FL", "Port St. Lucie", "St. Lucie"),
    ("Punta Gorda FL", "Punta Gorda", "Charlotte"),
    ("Quincy FL", "Quincy", "Gadsden"),
    ("Riviera Beach FL", "Riviera Beach", "Palm Beach"),
    ("Rockledge FL", "Rockledge", "Brevard"),
    ("Safety Harbor FL", "Safety Harbor", "Pinellas"),
    ("San Antonio FL", "San Antonio", "Pasco"),
    ("Sanford FL", "Sanford", "Seminole"),
    ("Sanibel FL", "Sanibel", "Lee"),
    ("Sarasota FL", "Sarasota", "Sarasota"),
    ("Satellite Beach FL", "Satellite Beach", "Brevard"),
    ("Sebastian FL", "Sebastian", "Indian River"),
    ("Sebring FL", "Sebring", "Highlands"),
    ("Seminole FL", "Seminole", "Pinellas"),
    ("Sopchoppy FL", "Sopchoppy", "Wakulla"),
    ("South Bay FL", "South Bay", "Palm Beach"),
    ("South Daytona FL", "South Daytona", "Volusia"),
    ("South Miami FL", "South Miami", "Miami-Dade"),
    ("South Pasadena FL", "South Pasadena", "Pinellas"),
    ("Springfield FL", "Springfield", "Bay"),
    ("St. Augustine FL", "St. Augustine", "St. Johns"),
    ("St. Augustine Beach FL", "St. Augustine Beach", "St. Johns"),
    ("St. Cloud FL", "St. Cloud", "Osceola"),
    ("St. Marks FL", "St. Marks", "Wakulla"),
    ("St. Pete Beach FL", "St. Pete Beach", "Pinellas"),
    ("St. Petersburg FL", "St. Petersburg", "Pinellas"),
    ("Starke FL", "Starke", "Bradford"),
    ("Stuart FL", "Stuart", "Martin"),
    ("Sunny Isles Beach FL", "Sunny Isles Beach", "Miami-Dade"),
    ("Sunrise FL", "Sunrise", "Broward"),
    ("Sweetwater FL", "Sweetwater", "Miami-Dade"),
    ("Tallahassee FL", "Tallahassee", "Leon"),
    ("Tamarac FL", "Tamarac", "Broward"),
    ("Tampa FL", "Tampa", "Hillsborough"),
    ("Tarpon Springs FL", "Tarpon Springs", "Pinellas"),
    ("Tavares FL", "Tavares", "Lake"),
    ("Temple Terrace FL", "Temple Terrace", "Hillsborough"),
    ("Titusville FL", "Titusville", "Brevard"),
    ("Treasure Island FL", "Treasure Island", "Pinellas"),
    ("Trenton FL", "Trenton", "Gilchrist"),
    ("Umatilla FL", "Umatilla", "Lake"),
    ("Valparaiso FL", "Valparaiso", "Okaloosa"),
    ("Venice FL", "Venice", "Sarasota"),
    ("Vernon FL", "Vernon", "Washington"),
    ("Vero Beach FL", "Vero Beach", "Indian River"),
    ("Waldo FL", "Waldo", "Alachua"),
    ("Wauchula FL", "Wauchula", "Hardee"),
    ("Webster FL", "Webster", "Sumter"),
    ("West Melbourne FL", "West Melbourne", "Brevard"),
    ("West Miami FL", "West Miami", "Miami-Dade"),
    ("West Palm Beach FL", "West Palm Beach", "Palm Beach"),
    ("West Park FL", "West Park", "Broward"),
    ("Westlake FL", "Westlake", "Palm Beach"),
    ("Weston FL", "Weston", "Broward"),
    ("Wewahitchka FL", "Wewahitchka", "Gulf"),
    ("Wildwood FL", "Wildwood", "Sumter"),
    ("Williston FL", "Williston", "Levy"),
    ("Wilton Manors FL", "Wilton Manors", "Broward"),
    ("Winter Garden FL", "Winter Garden", "Orange"),
    ("Winter Haven FL", "Winter Haven", "Polk"),
    ("Winter Park FL", "Winter Park", "Orange"),
    ("Winter Springs FL", "Winter Springs", "Seminole"),
    ("Zephyrhills FL", "Zephyrhills", "Pasco"),
]

# Curated batch 1: highest-converting local service niches to start with --
# high ticket size, chronic underinvestment in web presence, heavy reliance
# on local search/word-of-mouth rather than national advertising. Landscaping
# already scraped in a prior run; keeping it here too is harmless (upsert
# dedupes by place_id) and ensures a landscaper who also does hardscaping still
# gets picked up under whichever niche query surfaces them.
NICHES: list[tuple[str, str]] = [
    ("landscaping companies", "landscaping"),
    ("lawn care companies", "lawn_care"),
    ("hardscaping companies", "hardscaping"),
    ("roofing companies", "roofing"),
    ("plumbing companies", "plumbing"),
    ("HVAC companies", "hvac"),
    ("pool service companies", "pool_service"),
    ("pressure washing companies", "pressure_washing"),
    ("general contractors", "general_contractor"),
]

# Businesses whose *name* matches one of these are excluded outright -- either
# national chains/distributors (wrong customer profile: not the small operator
# who does the physical work, and already has a professional website), or
# they're not actually a service company at all. Case-insensitive substring
# match against business_name. Expanded for the broader niche set -- worth
# revisiting after the first big scrape to catch niche-specific chains we missed.
EXCLUDED_NAME_SUBSTRINGS: list[str] = [
    "siteone",
    "home depot",
    "lowe's",
    "lowes",
    "ace hardware",
    "walmart",
    "everglades equipment",
    "roto-rooter",
    "mr. rooter",
    "one hour heating",
    "aire serv",
    "servpro",
    "puronics",
    "leaf home",
    "trugreen",
    "the woodhouse",
    "massey services",
    "terminix",
    "orkin",
    "rescue rooter",
    "conditioned air",
    "ferguson",
    "menards",
]


def infer_city(formatted_address: str | None, fallback_city: str) -> str:
    """
    Places Text Search for 'X in <city>' isn't strictly bounded to that city --
    it happily returns nearby matches too. Trusting the query's city blindly
    means the wrong city can silently overwrite a correct one on a later
    upsert of the same place_id. Instead, derive the city from the actual
    formatted_address whenever possible, and only fall back to the query's
    city if none of our known target cities appear in the address.
    """
    if not formatted_address:
        return fallback_city
    addr_lower = formatted_address.lower()
    for _, city, _ in TARGET_AREAS:
        if city.lower() in addr_lower:
            return city
    return fallback_city


def infer_county(city: str, fallback_county: str) -> str:
    for _, area_city, county in TARGET_AREAS:
        if area_city == city:
            return county
    return fallback_county


NON_SCRAPABLE_EMAIL_HOSTS = [
    "facebook.com",
    "instagram.com",
    "sites.google.com",
    "business.site",
    "linktr.ee",
]


def load_google_search_key() -> str:
    return _require("GOOGLE_SEARCH_API_KEY")


def load_google_search_cx() -> str:
    return _require("GOOGLE_SEARCH_CX")


def load_searlo_key() -> str:
    return _require("SEARLO_API_KEY")


# JoshWeb Leads (LaaS) -- your own 5 core counties are NEVER sold as LaaS
# leads, since you're personally pursuing them for JoshWeb's own outreach.
LAAS_CORE_COUNTIES: list[str] = ["Polk", "Orange", "Osceola", "Seminole", "Lake"]

# Separate niche list for the LaaS product -- scraped independently from
# JoshWeb's own service niches, using the same 268-city target list.
LAAS_NICHES: list[tuple[str, str]] = [
    ("web design agency", "web_design_agency"),
    ("website design company", "website_design_company"),
    ("digital marketing agency", "digital_marketing_agency"),
]

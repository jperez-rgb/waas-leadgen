"""
Looks up domain RDAP records (the modern replacement for WHOIS) for leads
whose website_status is 'unreachable' -- they own a real domain, it's just
currently dead. Checks whether a registrant contact email is publicly listed.

Expect a LOW hit rate. Most registrars have auto-enabled WHOIS privacy
protection by default since GDPR (2018), replacing the real registrant email
with a privacy-proxy forwarding address (or hiding it entirely). This is a
cheap, no-browser-needed bonus channel -- not a primary one.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

PRIVACY_PROXY_SUBSTRINGS = [
    "domainsbyproxy.com", "contactprivacy.com", "whoisguard.com",
    "perfectprivacy.com", "withheldforprivacy.com", "privacyprotect.org",
    "identity-protect.org", "privatewhois.net", "whoisprivacyservice.org",
    "proxy.dreamhost.com", "privacy.link", "anonymised.email",
]


@dataclass
class WhoisResult:
    email: str | None
    confidence: str
    notes: str


def _extract_domain(url: str) -> str | None:
    try:
        host = urlparse(url).netloc.lower()
        return host.replace("www.", "") or None
    except Exception:
        return None


def find_whois_email(website_url: str | None, timeout_s: int = 10) -> WhoisResult:
    if not website_url:
        return WhoisResult(email=None, confidence="none", notes="No website URL to look up.")

    domain = _extract_domain(website_url)
    if not domain:
        return WhoisResult(email=None, confidence="none", notes="Could not parse domain from URL.")

    try:
        resp = requests.get(f"https://rdap.org/domain/{domain}", timeout=timeout_s)
        if resp.status_code != 200:
            return WhoisResult(email=None, confidence="none", notes=f"RDAP lookup returned HTTP {resp.status_code}.")
        data = resp.json()
    except Exception as exc:
        return WhoisResult(email=None, confidence="none", notes=f"RDAP lookup failed: {exc.__class__.__name__}")

    candidates: list[str] = []
    for entity in data.get("entities", []):
        vcard = entity.get("vcardArray")
        if not vcard or len(vcard) < 2:
            continue
        for field in vcard[1]:
            if len(field) >= 4 and field[0] == "email":
                candidates.append(str(field[3]))

    if not candidates:
        candidates = EMAIL_RE.findall(str(data))

    for email in candidates:
        email_lower = email.lower().strip()
        if any(proxy in email_lower for proxy in PRIVACY_PROXY_SUBSTRINGS):
            continue
        return WhoisResult(email=email_lower, confidence="whois", notes=f"Found via RDAP lookup on {domain}.")

    return WhoisResult(email=None, confidence="none", notes="No non-privacy-shielded email found in RDAP record.")

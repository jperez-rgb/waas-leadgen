"""
Minimal client for Instantly.ai API v2 -- just enough to push a graded, verified
lead into an existing campaign. Assumes you've already created the campaign
(and written its email sequence) in the Instantly dashboard -- this script's job
is purely to get clean leads into it, not to write your copy for you.

Docs: https://developer.instantly.ai/api-reference/groups/lead
Auth: Bearer token (API v2 key from Instantly workspace settings)
"""
from __future__ import annotations

import logging

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

BASE_URL = "https://api.instantly.ai/api/v2"


class InstantlyClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
    )
    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(f"{BASE_URL}{path}", headers=self._headers, json=body, timeout=15)
        if resp.status_code == 429:
            raise requests.exceptions.RequestException(f"429 rate limited: {resp.text}")
        if resp.status_code >= 400:
            # Don't retry on 4xx other than 429 -- that's a bad request, retrying won't help.
            logger.error("Instantly API error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    def add_lead(
        self,
        campaign_id: str,
        email: str,
        first_name: str | None = None,
        company_name: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        custom_variables: dict | None = None,
    ) -> dict:
        """
        Adds a single lead to a campaign. Uses skip_if_in_* flags so re-running
        this after a partial failure never creates duplicates.
        """
        body = {
            "campaign": campaign_id,
            "email": email,
            "skip_if_in_workspace": True,
            "skip_if_in_campaign": True,
            "skip_if_in_list": True,
        }
        if first_name:
            body["first_name"] = first_name
        if company_name:
            body["company_name"] = company_name
        if website:
            body["website"] = website
        if phone:
            body["phone"] = phone
        if custom_variables:
            body["custom_variables"] = custom_variables

        return self._post("/leads", body)

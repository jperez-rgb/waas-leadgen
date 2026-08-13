"""
Fire-and-forget Discord notifications for pipeline milestones. Entirely optional --
if DISCORD_WEBHOOK_URL isn't set, every call here is a silent no-op. This means
you can add/remove the webhook at any time without touching pipeline code.

Setup (2 minutes): in your Discord server, go to a channel's Settings -> Integrations
-> Webhooks -> New Webhook -> copy the URL -> paste it into Render's env vars as
DISCORD_WEBHOOK_URL. Never paste that URL into a chat with Claude or anyone else --
anyone with the URL can post to your channel.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


def notify(message: str) -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return  # Not configured -- silently skip, this is optional.

    try:
        requests.post(webhook_url, json={"content": message}, timeout=10)
    except requests.exceptions.RequestException as exc:
        # Never let a notification failure affect the actual pipeline run.
        logger.warning("Discord notification failed (non-fatal): %s", exc)

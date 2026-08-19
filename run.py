#!/usr/bin/env python3
"""
CLI entry point for the Lead Generation Engine + Outreach Pipeline.

Usage:
    python run.py scrape                # pull fresh leads from Places API into Supabase
    python run.py grade                 # visit + classify websites for ungraded leads
    python run.py grade --limit 50      # grade only the next 50 (useful for testing)
    python run.py find-emails           # scrape Bucket A leads' sites for a contact email
    python run.py find-whois-emails     # RDAP/WHOIS lookup for leads with dead domains
    python run.py push-instantly        # push leads with a found email into your Instantly campaign
    python run.py summary               # print current golden leads from the DB
    python run.py mark-reply --email x@y.com --status interested --notes "wants a call"
    python run.py all                   # scrape, then grade, then summary
"""
from __future__ import annotations

import argparse
import logging
import sys

from src import db
from src.config import load_instantly_campaign_id, load_instantly_key, load_settings
from src.pipeline import (
    print_golden_leads_summary,
    run_find_emails,
    run_find_whois_emails,
    run_grade,
    run_push_instantly,
    run_scrape,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

REPLY_STATUSES = ["no_reply", "interested", "not_interested", "needs_followup", "closed_won", "closed_lost"]


def main() -> int:
    parser = argparse.ArgumentParser(description="WaaS Agency Lead Generation + Outreach Engine")
    parser.add_argument(
        "command",
        choices=["scrape", "grade", "find-emails", "find-whois-emails", "push-instantly",
                 "summary", "mark-reply", "all"],
        help="Which phase to run.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max leads to process in this run (grade/find-emails/find-whois-emails/push-instantly commands).",
    )
    parser.add_argument("--email", type=str, default=None, help="Lead's email (mark-reply command).")
    parser.add_argument("--status", type=str, choices=REPLY_STATUSES, default=None,
                         help="Reply status to set (mark-reply command).")
    parser.add_argument("--notes", type=str, default=None, help="Optional notes (mark-reply command).")
    args = parser.parse_args()

    settings = load_settings()

    if args.command in ("scrape", "all"):
        run_scrape(settings)
    if args.command in ("grade", "all"):
        run_grade(settings, max_leads=args.limit)
    if args.command == "find-emails":
        run_find_emails(settings, max_leads=args.limit)
    if args.command == "find-whois-emails":
        run_find_whois_emails(settings, max_leads=args.limit)
    if args.command == "push-instantly":
        api_key = load_instantly_key()
        campaign_id = load_instantly_campaign_id()
        run_push_instantly(settings, api_key, campaign_id, max_leads=args.limit)
    if args.command == "mark-reply":
        if not args.email or not args.status:
            parser.error("mark-reply requires --email and --status")
        client = db.get_client(settings.supabase_url, settings.supabase_key)
        leads = client.table("leads").select("place_id").eq("contact_email", args.email).execute()
        if not leads.data:
            print(f"No lead found with email {args.email}")
            return 1
        for lead in leads.data:
            db.update_reply_status(client, lead["place_id"], args.status, args.notes)
        print(f"Marked {args.email} as '{args.status}'" + (f" -- {args.notes}" if args.notes else ""))
    if args.command in ("summary", "all"):
        print_golden_leads_summary(settings)

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
CLI entry point for the Lead Generation Engine + Outreach Pipeline.

Usage:
    python run.py scrape                # pull fresh leads from Places API into Supabase
    python run.py grade                 # visit + classify websites for ungraded leads
    python run.py grade --limit 50      # grade only the next 50 (useful for testing)
    python run.py find-emails           # scrape Bucket A leads' sites for a contact email
    python run.py push-instantly        # push leads with a found email into your Instantly campaign
    python run.py summary               # print current golden leads from the DB
    python run.py all                   # scrape, then grade, then summary
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_instantly_campaign_id, load_instantly_key, load_settings
from src.pipeline import (
    print_golden_leads_summary,
    run_find_emails,
    run_grade,
    run_push_instantly,
    run_scrape,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="WaaS Agency Lead Generation + Outreach Engine")
    parser.add_argument(
        "command",
        choices=["scrape", "grade", "find-emails", "push-instantly", "summary", "all"],
        help="Which phase to run.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max leads to process in this run (grade/find-emails/push-instantly commands).",
    )
    args = parser.parse_args()

    settings = load_settings()

    if args.command in ("scrape", "all"):
        run_scrape(settings)
    if args.command in ("grade", "all"):
        run_grade(settings, max_leads=args.limit)
    if args.command == "find-emails":
        run_find_emails(settings, max_leads=args.limit)
    if args.command == "push-instantly":
        api_key = load_instantly_key()
        campaign_id = load_instantly_campaign_id()
        run_push_instantly(settings, api_key, campaign_id, max_leads=args.limit)
    if args.command in ("summary", "all"):
        print_golden_leads_summary(settings)

    return 0


if __name__ == "__main__":
    sys.exit(main())

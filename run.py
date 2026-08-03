#!/usr/bin/env python3
"""
CLI entry point for the Lead Generation Engine.

Usage:
    python run.py scrape            # pull fresh leads from Places API into Supabase
    python run.py grade             # visit + classify websites for ungraded leads
    python run.py grade --limit 50  # grade only the next 50 (useful for testing)
    python run.py summary           # print current golden leads from the DB
    python run.py all               # scrape, then grade, then summary
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_settings
from src.pipeline import print_golden_leads_summary, run_grade, run_scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="WaaS Agency Lead Generation Engine")
    parser.add_argument(
        "command", choices=["scrape", "grade", "summary", "all"],
        help="Which phase to run.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max leads to grade in this run (grade/all commands only).",
    )
    args = parser.parse_args()

    settings = load_settings()

    if args.command in ("scrape", "all"):
        run_scrape(settings)
    if args.command in ("grade", "all"):
        run_grade(settings, max_leads=args.limit)
    if args.command in ("summary", "all"):
        print_golden_leads_summary(settings)

    return 0


if __name__ == "__main__":
    sys.exit(main())

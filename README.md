# WaaS Agency — Lead Generation Engine

Goal 1 of the outreach pipeline: find Central Florida landscaping/lawn care/hardscaping
businesses with a strong Google reputation (4.0+ rating, 15+ reviews) but a weak or
missing website, and store them in Supabase ready for the outreach layer to consume.

Two phases, run independently so you can re-run grading without re-hitting the Places API:

1. **`scrape`** — walks every (niche × city) combination for the 5 target counties,
   pulls results from the Places API (New), upserts into the `leads` table.
2. **`grade`** — for leads that clear the rating/review bar and haven't been graded yet,
   visits the website with Playwright (mobile viewport) and classifies it as
   `none` / `unreachable` / `thin` / `generic_builder` / `outdated` / `ok`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# fill in GOOGLE_PLACES_API_KEY and SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
```

### Supabase setup
1. Create a new Supabase project.
2. Open the SQL editor, paste in `migrations/001_init.sql`, run it.
3. Grab the Project URL and `service_role` key from Project Settings → API, put them in `.env`.

### Google Places API setup
1. In Google Cloud Console, enable **"Places API (New)"** (not the legacy Places API).
2. Create an API key, restrict it to Places API (New) for safety.
3. Put it in `.env` as `GOOGLE_PLACES_API_KEY`.

## Usage

```bash
python run.py scrape            # populate the DB from Places API
python run.py grade              # grade all ungraded leads that meet the reputation bar
python run.py grade --limit 20   # grade just the next 20 (good for a test run)
python run.py summary            # print current golden leads
python run.py all                # scrape -> grade -> summary in one go
```

## Notes / things to tune before a big run

- `TARGET_AREAS` and `NICHES` live in `src/config.py` — edit the lists directly to
  add/remove cities or niches.
- `MIN_RATING` / `MIN_REVIEWS` are env-configurable if you want to loosen/tighten
  the reputation bar without touching code.
- The grader's heuristics (thin-content word threshold, outdated-copyright-year
  cutoff, placeholder-builder host list) live in `src/site_grader.py` — expect to
  tune these after eyeballing the first real run's results.
- `is_golden_lead` is a generated column in Postgres — it's always in sync with
  `website_status`, you never write to it directly.
- Rate limiting: Places API calls are throttled via `PLACES_RPM`; site grading
  visits are spaced out via `SITE_GRADE_DELAY_SECONDS` + jitter. Both exist to
  avoid hammering Google or small business hosts, not to evade anything —
  tune up if you're impatient, just don't remove the delay entirely.

## What's NOT in this script (later goals)

- Cold email sending infrastructure (Instantly/Smartlead integration, SPF/DKIM/DMARC setup)
- Email sequence generation / personalization using `website_notes`
- Reply handling / unsubscribe webhook

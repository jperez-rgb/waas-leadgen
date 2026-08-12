# WaaS Agency — Lead Generation Engine

Goal 1 of the outreach pipeline: find Florida businesses across 9 service niches
(landscaping, lawn care, hardscaping, roofing, plumbing, HVAC, pool service, pressure
washing, general contracting) with a weak or missing website, across all 268 official
Florida cities, and store them in Supabase ready for the outreach layer to consume.

Two phases, run independently so you can re-run grading without re-hitting the Places API:

1. **`scrape`** — walks every (niche × city) combination — 268 cities × 9 niches =
   2,412 queries — pulls results from the Places API (New), upserts into the `leads` table.
2. **`grade`** — for leads that haven't been graded yet, visits the website with Playwright
   (mobile viewport) and classifies it as `none` / `unreachable` / `thin` / `generic_builder`
   / `outdated` / `ok`. Runs multiple sites concurrently (see `GRADE_WORKERS`) since a
   sequential pass over tens of thousands of leads would take days.

At this scale, run this on Render (see below) rather than a laptop — a multi-hour+ job
that dies because a lid closed is a bad time.

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
python run.py find-emails        # scrape Bucket A leads' real websites for a contact email
python run.py push-instantly     # push leads with a found email into your Instantly campaign
python run.py summary            # print current golden leads
python run.py all                # scrape -> grade -> summary in one go
```

## Outreach pipeline (Bucket A / Bucket B split)

Cold email needs an email address, and Google Places doesn't provide one. Leads split into:

- **Bucket A** -- `website_status` is `thin` / `outdated` / `generic_builder` (has *some* real
  website, not on a social/builder platform). `find-emails` visits these sites and scrapes a
  published email (mailto link first, then plain-text pattern match, then the same on a linked
  contact page). It never guesses an unpublished address like `info@domain.com`.
- **Bucket B** -- `website_status` is `none` or `unreachable`. No site to scrape, no email to
  find. These are intentionally skipped by this pipeline -- they need a different channel
  (phone, social DM, physical mail) if you want to reach them at all.

### Before running `push-instantly`

1. Create the campaign in the Instantly dashboard yourself, including writing the actual email
   sequence copy -- this script only pushes clean leads into an existing campaign, it doesn't
   generate your outreach copy.
2. Grab the campaign's ID and put it in `.env` as `INSTANTLY_CAMPAIGN_ID`.
3. Generate an API v2 key (Workspace Settings -> Integrations -> API) with at least the
   `leads:create` scope, put it in `.env` as `INSTANTLY_API_KEY`.
4. Make sure the sending mailboxes assigned to that campaign have been warming up for at least
   2-3 weeks -- see the domain/DNS/warmup setup notes from project planning.

Custom variables pushed with each lead (usable in your Instantly email template via
`{{city}}`, `{{website_status}}`, etc.): `city`, `county`, `website_status`, `website_notes`,
`rating`, `review_count` -- handy for personalizing the opener (e.g. referencing the specific
issue found on their site).

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

## Deploying to Render (recommended at this scale)

Playwright needs its browser binaries plus a pile of OS-level dependencies. Fighting
`apt-get` permissions inside a generic Python buildpack is a common headache on most
PaaS platforms, so this repo deploys via **Docker** using Playwright's official base
image instead, which has everything pre-installed.

1. Push this repo to GitHub if you haven't already (`git add . && git commit -m "..." && git push`).
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New +** → **Background Worker**.
3. Connect your GitHub repo.
4. Under **Environment**, choose **Docker** (Render should auto-detect the `Dockerfile`).
5. Pick an instance type — **Starter (512MB RAM / 0.5 CPU, $7/mo)** to begin with. If
   grading feels slow or the container runs out of memory with `GRADE_WORKERS=6`, bump
   to Standard (2GB/1CPU, $25/mo) or lower `GRADE_WORKERS` in your env vars instead.
6. Under **Environment Variables**, add every variable from your `.env` file
   (`GOOGLE_PLACES_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MIN_RATING`,
   `MIN_REVIEWS`, `GRADE_WORKERS`, etc.) — same keys, same values, just entered in
   Render's dashboard instead of a local file.
7. Click **Deploy**.

**This container doesn't run anything automatically.** On purpose — auto-running `scrape`
every time the container restarts would silently re-burn API budget. Instead:

8. Once deployed, open the service page → **Shell** tab. This gives you a terminal
   running *inside* the deployed container — same commands as local:
   ```bash
   python run.py scrape
   python run.py grade
   python run.py find-emails
   python run.py summary
   ```
9. Close the browser tab whenever you want — the job keeps running on Render's
   servers regardless of whether your laptop is open, asleep, or across the room.

## What's NOT in this script (later goals)

- Cold email sending infrastructure (Instantly/Smartlead integration, SPF/DKIM/DMARC setup)
- Email sequence generation / personalization using `website_notes`
- Reply handling / unsubscribe webhook

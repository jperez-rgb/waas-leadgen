-- WaaS Agency Lead Gen — initial schema
-- Run this in the Supabase SQL editor, or via `supabase db push` once linked.

create extension if not exists pgcrypto;

create table if not exists leads (
    id                    uuid primary key default gen_random_uuid(),

    -- Identity / dedupe key from Google Places
    place_id              text unique not null,

    -- Core business info
    business_name         text not null,
    formatted_address      text,
    city                  text,
    county                text,
    phone                 text,
    website_url           text,

    -- Reputation signals (the "Golden Lead" filter)
    rating                numeric(2,1),
    review_count          integer,

    -- Website grading (populated by the Playwright grader)
    website_status        text not null default 'unknown'
                           constraint website_status_check
                           check (website_status in (
                               'unknown',          -- not graded yet
                               'none',              -- no website on Google profile at all
                               'unreachable',        -- domain doesn't resolve / times out / errors
                               'thin',               -- loads, but near-empty content (e.g. bare Google Sites page)
                               'generic_builder',     -- spammy/templated builder site, low quality
                               'outdated',           -- old copyright year, no mobile viewport, dated design
                               'ok'                  -- decent modern site, not a lead
                           )),
    website_notes         text,               -- human-readable summary of what the grader found
    website_graded_at     timestamptz,
    screenshot_path        text,               -- optional local/S3 path if a screenshot was captured

    -- Derived flag: true if website_status is one of the "bad" states
    is_golden_lead         boolean generated always as (
                               website_status in ('none', 'unreachable', 'thin', 'generic_builder', 'outdated')
                           ) stored,

    -- Outreach pipeline state (used by later email scripts)
    email_status           text not null default 'not_started'
                           constraint email_status_check
                           check (email_status in (
                               'not_started', 'queued', 'sent', 'replied', 'bounced', 'unsubscribed'
                           )),
    assigned_sending_domain text,
    contact_email          text,
    unsubscribed           boolean not null default false,

    -- Bookkeeping
    source_query           text,               -- the search query that surfaced this lead
    niche                  text,               -- landscaping | lawn_care | hardscaping
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);

create index if not exists idx_leads_is_golden on leads (is_golden_lead) where is_golden_lead = true;
create index if not exists idx_leads_website_status on leads (website_status);
create index if not exists idx_leads_county_city on leads (county, city);
create index if not exists idx_leads_email_status on leads (email_status);

-- Keep updated_at fresh on every write
create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_leads_updated_at on leads;
create trigger trg_leads_updated_at
    before update on leads
    for each row execute procedure set_updated_at();

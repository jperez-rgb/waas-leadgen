-- Adds columns to support the email-finding step (Bucket A leads only).
-- Run this in the Supabase SQL editor same as 001_init.sql.

alter table leads add column if not exists email_confidence text
    constraint email_confidence_check
    check (email_confidence in ('mailto', 'text_pattern', 'none') or email_confidence is null);

alter table leads add column if not exists email_source_url text;
alter table leads add column if not exists email_found_notes text;
alter table leads add column if not exists email_searched_at timestamptz;

create index if not exists idx_leads_contact_email on leads (contact_email) where contact_email is not null;

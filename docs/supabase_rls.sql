-- Supernova / Supabase hardening
--
-- Run this in Supabase SQL Editor after the production tables exist.
-- The Flask app connects server-side through DATABASE_URL, so browser users do
-- not need direct Supabase table access through the anon/authenticated roles.

ALTER TABLE IF EXISTS public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.media_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.rss_feeds ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.rss_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.post_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.social_accounts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.posts FROM anon, authenticated;
REVOKE ALL ON TABLE public.logs FROM anon, authenticated;
REVOKE ALL ON TABLE public.media_assets FROM anon, authenticated;
REVOKE ALL ON TABLE public.rss_feeds FROM anon, authenticated;
REVOKE ALL ON TABLE public.rss_items FROM anon, authenticated;
REVOKE ALL ON TABLE public.post_schedules FROM anon, authenticated;
REVOKE ALL ON TABLE public.social_accounts FROM anon, authenticated;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- Intentionally no public policies:
-- all reads/writes should go through the authenticated Flask app.

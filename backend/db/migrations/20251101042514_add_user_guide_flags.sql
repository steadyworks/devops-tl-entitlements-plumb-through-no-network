-- 20251031_add_user_guide_flags.sql

-- migrate:up

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS seen_cover_guide boolean,
  ADD COLUMN IF NOT EXISTS seen_section_guide boolean,
  ADD COLUMN IF NOT EXISTS seen_page_content_guide boolean;

COMMENT ON COLUMN public.users.seen_cover_guide IS 'Has the user seen the cover editor onboarding/guide.';
COMMENT ON COLUMN public.users.seen_section_guide IS 'Has the user seen the section editor onboarding/guide.';
COMMENT ON COLUMN public.users.seen_page_content_guide IS 'Has the user seen the page content editor onboarding/guide.';

-- migrate:down

ALTER TABLE public.users
  DROP COLUMN IF EXISTS seen_cover_guide,
  DROP COLUMN IF EXISTS seen_section_guide,
  DROP COLUMN IF EXISTS seen_page_content_guide;

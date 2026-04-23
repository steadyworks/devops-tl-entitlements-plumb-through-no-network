-- 20251024_add_theme_to_background_img_registry.sql
-- migrate:up

-- 1) Create enum type if missing
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'background_theme_enum' AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.background_theme_enum AS ENUM (
      'thanksgiving',
      'christmas',
      'kid',
      'travel',
      'pet',
      'birthday',
      'neutral',
      'new_year'
    );
  END IF;
END$$;

-- 2) Ensure values exist (no-ops if already present)
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'thanksgiving';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'christmas';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'kid';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'travel';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'pet';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'birthday';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'halloween';
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'new_year';

-- 3) Add the column (nullable for safety)
ALTER TABLE public.background_img_registry
  ADD COLUMN IF NOT EXISTS theme public.background_theme_enum;

COMMENT ON COLUMN public.background_img_registry.theme IS
  'Theme for this background (enum): thanksgiving, christmas, kid, travel, pet, birthday, neutral, new_year';

-- (Optional) Set a default and backfill, then enforce NOT NULL:
-- ALTER TABLE public.background_img_registry ALTER COLUMN theme SET DEFAULT 'neutral'::public.background_theme_enum;
-- UPDATE public.background_img_registry SET theme = 'neutral' WHERE theme IS NULL;
-- ALTER TABLE public.background_img_registry ALTER COLUMN theme SET NOT NULL;


-- migrate:down

-- Drop the column (keeps the enum type in case others use it)
ALTER TABLE public.background_img_registry
  DROP COLUMN IF EXISTS theme;

-- Optionally drop the enum type (will error if still in use elsewhere)
-- DROP TYPE IF EXISTS public.background_theme_enum;

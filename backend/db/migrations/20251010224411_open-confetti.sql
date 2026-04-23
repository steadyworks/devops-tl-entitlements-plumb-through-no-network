-- migrate:up
-- migrate:up

-- Create enum type if it doesn't already exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'open_confetti' AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.open_confetti AS ENUM (
      'thanksgiving_pumpkin',
      'thanksgiving_gift',
      'thanksgiving_heart',
      'christmas_santa',
      'christmas_gift',
      'christmas_light'
    );
    COMMENT ON TYPE public.open_confetti IS 'Confetti style shown when opening a photobook.';
  END IF;
END
$$;

-- Add column to photobooks (nullable, no default)
ALTER TABLE public.photobooks
  ADD COLUMN IF NOT EXISTS open_confetti public.open_confetti;

COMMENT ON COLUMN public.photobooks.open_confetti IS 'Optional confetti theme to use on open (e.g., thanksgiving_pumpkin, thanksgiving_gift).';


-- migrate:down

-- migrate:down

-- Drop the column first (removes dependency on the enum)
ALTER TABLE public.photobooks
  DROP COLUMN IF EXISTS open_confetti;

-- Drop the enum type if no longer used anywhere
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    JOIN pg_attribute a ON a.atttypid = t.oid
    WHERE t.typname = 'open_confetti'
      AND n.nspname = 'public'
      AND a.attnum > 0
  ) THEN
    DROP TYPE IF EXISTS public.open_confetti;
  END IF;
END
$$;

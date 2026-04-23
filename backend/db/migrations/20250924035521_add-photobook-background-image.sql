-- migrate:up
DO $$
BEGIN
  -- Create enum type if it doesn't already exist
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'background_type'
      AND n.nspname = 'public'
  ) THEN
    CREATE TYPE public.background_type AS ENUM ('color', 'staticimg');
  END IF;
END$$;

ALTER TABLE public.photobooks
  ADD COLUMN IF NOT EXISTS background public.background_type NOT NULL DEFAULT 'color',
  ADD COLUMN IF NOT EXISTS bg_img_name text;

-- Optional: drop runtime default so future inserts must be explicit
ALTER TABLE public.photobooks
  ALTER COLUMN background DROP DEFAULT;

-- migrate:down
ALTER TABLE public.photobooks
  DROP COLUMN IF EXISTS bg_img_name,
  DROP COLUMN IF EXISTS background;

DO $$
BEGIN
  -- Drop enum only if no columns still depend on it
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE udt_schema = 'public'
      AND udt_name   = 'background_type'
  ) THEN
    DROP TYPE IF EXISTS public.background_type;
  END IF;
END$$;

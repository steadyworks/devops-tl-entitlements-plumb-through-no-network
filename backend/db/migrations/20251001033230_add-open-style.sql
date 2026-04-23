-- migrate:up

-- Create enum type if it doesn't already exist
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'open_style') THEN
    CREATE TYPE public.open_style AS ENUM ('twod_envelope');
  END IF;
END$$;

-- Add columns to photobooks
ALTER TABLE public.photobooks
  ADD COLUMN open_style public.open_style,
  ADD COLUMN open_param jsonb;

-- Optional: document intent
-- COMMENT ON COLUMN public.photobooks.open_style IS 'How the photobook opens (enum).';
-- COMMENT ON COLUMN public.photobooks.open_param IS 'Arbitrary parameters for the chosen open_style (JSONB).';


-- migrate:down

-- Drop columns first (to release dependency on the enum type)
ALTER TABLE public.photobooks
  DROP COLUMN IF EXISTS open_param,
  DROP COLUMN IF EXISTS open_style;

-- Then drop the enum type
DROP TYPE IF EXISTS public.open_style;
-- migrate:up

-- Ensure enum type exists with all values; otherwise add missing ones in order.
DO $$
DECLARE
  need_create boolean;
BEGIN
  SELECT NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'font_style' AND n.nspname = 'public'
  ) INTO need_create;

  IF need_create THEN
    CREATE TYPE public.font_style AS ENUM (
      'unspecified',
      'playfair',
      'cinzel',
      'lora',
      'zilla_slab',
      'caveat',
      'caveat_brush',
      'fredoka',
      'grandstander'
    );
    COMMENT ON TYPE public.font_style IS 'Font selection for photobooks.';
  ELSE
    -- Append any missing values, preserving order after 'unspecified'
    PERFORM 1;
    DO $inner$
    DECLARE
      labels text[] := ARRAY[
        'playfair',
        'cinzel',
        'lora',
        'zilla_slab',
        'caveat',
        'caveat_brush',
        'fredoka',
        'grandstander'
      ];
      prev text := 'unspecified';
      lbl  text;
    BEGIN
      FOREACH lbl IN ARRAY labels LOOP
        EXECUTE format(
          'ALTER TYPE public.font_style ADD VALUE IF NOT EXISTS %L AFTER %L',
          lbl, prev
        );
        prev := lbl;
      END LOOP;
    END
    $inner$;
  END IF;
END$$;

-- Add column to photobooks
ALTER TABLE public.photobooks
  ADD COLUMN IF NOT EXISTS font public.font_style
  DEFAULT 'unspecified'::public.font_style
  NOT NULL;

COMMENT ON COLUMN public.photobooks.font IS 'Primary display font for this photobook.';

-- migrate:down

-- Drop the column (keep the enum type since other tables may use it)
ALTER TABLE public.photobooks
  DROP COLUMN IF EXISTS font;

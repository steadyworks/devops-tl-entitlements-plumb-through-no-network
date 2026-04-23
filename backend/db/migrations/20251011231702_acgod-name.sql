-- migrate:up

DO $$
BEGIN
  -- Only run if the type exists and the old label is present and the new one isn't.
  IF EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider'
  )
  AND EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON t.oid = e.enumtypid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider' AND e.enumlabel = 'acgod'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON t.oid = e.enumtypid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider' AND e.enumlabel = 'agcod'
  )
  THEN
    ALTER TYPE public.giftcard_provider RENAME VALUE 'acgod' TO 'agcod';
  END IF;
END
$$;

-- migrate:down

DO $$
BEGIN
  -- Reverse the rename safely if needed.
  IF EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider'
  )
  AND EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON t.oid = e.enumtypid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider' AND e.enumlabel = 'agcod'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM pg_enum e
    JOIN pg_type t ON t.oid = e.enumtypid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'giftcard_provider' AND e.enumlabel = 'acgod'
  )
  THEN
    ALTER TYPE public.giftcard_provider RENAME VALUE 'agcod' TO 'acgod';
  END IF;
END
$$;

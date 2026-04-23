-- migrate:up

-- Drop dependent indexes first (some DBs won't allow dropping a column referenced by an index)
DROP INDEX IF EXISTS public.uq_giftcards_provider_id;
DROP INDEX IF EXISTS public.uq_giftcards_idempotency;

-- Add the new internal-only UUID column (nullable first so we can backfill safely)
ALTER TABLE public.giftcards
  ADD COLUMN IF NOT EXISTS provider_giftcard_id_internal_only uuid;

-- Backfill existing rows (requires gen_random_uuid(); your schema already uses it)
UPDATE public.giftcards
SET provider_giftcard_id_internal_only = gen_random_uuid()
WHERE provider_giftcard_id_internal_only IS NULL;

-- Enforce NOT NULL after backfill
ALTER TABLE public.giftcards
  ALTER COLUMN provider_giftcard_id_internal_only SET NOT NULL;

-- Now drop the old columns
ALTER TABLE public.giftcards
  DROP COLUMN IF EXISTS provider_giftcard_id,
  DROP COLUMN IF EXISTS idempotency_key;

-- migrate:down


-- Re-add the old columns as nullable (can’t restore data that was dropped)
ALTER TABLE public.giftcards
  ADD COLUMN IF NOT EXISTS provider_giftcard_id text,
  ADD COLUMN IF NOT EXISTS idempotency_key text;

-- Recreate the original indexes (use IF NOT EXISTS for idempotence)
-- Unique on (provider, provider_giftcard_id) when provider_giftcard_id is not null
CREATE UNIQUE INDEX IF NOT EXISTS uq_giftcards_provider_id
  ON public.giftcards USING btree (provider, provider_giftcard_id)
  WHERE provider_giftcard_id IS NOT NULL;

-- Unique idempotency_key when not null
CREATE UNIQUE INDEX IF NOT EXISTS uq_giftcards_idempotency
  ON public.giftcards USING btree (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- Drop the internal-only column
ALTER TABLE public.giftcards
  DROP COLUMN IF EXISTS provider_giftcard_id_internal_only;


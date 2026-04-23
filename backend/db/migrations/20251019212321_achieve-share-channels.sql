-- migrate:up

-- 1) Add archive columns to share_channels
ALTER TABLE public.share_channels
  ADD COLUMN archived_at timestamptz;

-- 2) Replace the existing unique constraint with an ACTIVE-only unique index.
-- Drop (photobook_id, channel_type, destination) unique that forces one row forever.
DROP INDEX IF EXISTS uq_share_channel_dest_per_photobook;

-- Recreate as "active only" (archived_at IS NULL).
CREATE UNIQUE INDEX uq_share_channel_dest_per_photobook_active
  ON public.share_channels (photobook_id, channel_type, destination)
  WHERE archived_at IS NULL;

-- migrate:down

-- 1) Restore the original unique index across all rows
DROP INDEX IF EXISTS uq_share_channel_dest_per_photobook_active;

CREATE UNIQUE INDEX uq_share_channel_dest_per_photobook
  ON public.share_channels (photobook_id, channel_type, destination);

-- 2) Drop archive columns
ALTER TABLE public.share_channels
  DROP COLUMN IF EXISTS archived_at;
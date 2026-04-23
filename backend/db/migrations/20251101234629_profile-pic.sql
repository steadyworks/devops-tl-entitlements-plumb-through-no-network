-- migrate:up
-- Add nullable FK from users.profile_pic_asset_id -> assets.id
ALTER TABLE public.users
  ADD COLUMN profile_pic_asset_id uuid;

COMMENT ON COLUMN public.users.profile_pic_asset_id IS
  'Optional reference to public.assets.id for the user’s profile picture.';

-- Create an index for quick lookups / joins
CREATE INDEX IF NOT EXISTS idx_users_profile_pic_asset_id
  ON public.users (profile_pic_asset_id);

-- Add the FK constraint (explicitly named for easy rollback)
ALTER TABLE public.users
  ADD CONSTRAINT users_profile_pic_asset_id_fkey
  FOREIGN KEY (profile_pic_asset_id)
  REFERENCES public.assets (id)
  ON DELETE SET NULL
  ON UPDATE CASCADE;

-- migrate:down
-- Remove FK, index, and column (reverse order-safe)
ALTER TABLE public.users
  DROP CONSTRAINT IF EXISTS users_profile_pic_asset_id_fkey;

DROP INDEX IF EXISTS idx_users_profile_pic_asset_id;

ALTER TABLE public.users
  DROP COLUMN IF EXISTS profile_pic_asset_id;

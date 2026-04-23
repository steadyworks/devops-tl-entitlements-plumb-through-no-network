-- migrate:up

-- Drop the old FK which used ON DELETE SET NULL
ALTER TABLE public.payments
  DROP CONSTRAINT IF EXISTS payments_created_by_user_id_fkey;

-- Make the column NOT NULL (safe since existing rows are populated)
ALTER TABLE public.payments
  ALTER COLUMN created_by_user_id SET NOT NULL;

-- Recreate the FK without ON DELETE SET NULL (defaults to NO ACTION)
ALTER TABLE public.payments
  ADD CONSTRAINT payments_created_by_user_id_fkey
  FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);

-- migrate:down

-- Drop the updated FK
ALTER TABLE public.payments
  DROP CONSTRAINT IF EXISTS payments_created_by_user_id_fkey;

-- Allow NULLs again
ALTER TABLE public.payments
  ALTER COLUMN created_by_user_id DROP NOT NULL;

-- Restore original FK behavior
ALTER TABLE public.payments
  ADD CONSTRAINT payments_created_by_user_id_fkey
  FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

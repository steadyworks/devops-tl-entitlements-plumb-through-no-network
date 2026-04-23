-- migrate:up

-- Up: make payments.photobook_id NOT NULL and change FK to RESTRICT

-- Drop the old FK that used ON DELETE SET NULL
ALTER TABLE ONLY public.payments
  DROP CONSTRAINT IF EXISTS payments_photobook_id_fkey;

-- Make column NOT NULL
ALTER TABLE ONLY public.payments
  ALTER COLUMN photobook_id SET NOT NULL;

-- Recreate FK with a non-null-compatible delete action
-- RESTRICT (equivalent to NO ACTION in Postgres) prevents deleting a photobook
-- that has payments, which is usually what you want for auditability.
ALTER TABLE ONLY public.payments
  ADD CONSTRAINT payments_photobook_id_fkey
  FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE RESTRICT;



-- migrate:down

ALTER TABLE ONLY public.payments
  DROP CONSTRAINT IF EXISTS payments_photobook_id_fkey;

ALTER TABLE ONLY public.payments
  ALTER COLUMN photobook_id DROP NOT NULL;

ALTER TABLE ONLY public.payments
  ADD CONSTRAINT payments_photobook_id_fkey
  FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE SET NULL;


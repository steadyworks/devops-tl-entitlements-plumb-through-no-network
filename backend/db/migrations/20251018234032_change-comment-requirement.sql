-- migrate:up

ALTER TABLE public.photobook_comments
  DROP CONSTRAINT IF EXISTS photobook_comments_check;

-- Allow guest_email to be NULL for guest comments.
-- Valid rows are:
--   1) Auth user: user_id IS NOT NULL AND guest_* must be NULL
--   2) Guest:     user_id IS NULL AND guest_name IS NOT NULL (guest_email optional)
ALTER TABLE public.photobook_comments
  ADD CONSTRAINT photobook_comments_check
  CHECK (
    (user_id IS NOT NULL AND guest_name IS NULL AND guest_email IS NULL)
    OR
    (user_id IS NULL AND guest_name IS NOT NULL)
  );


-- migrate:down


ALTER TABLE public.photobook_comments
  DROP CONSTRAINT IF EXISTS photobook_comments_check;

-- Restore the original stricter rule where guest_email is required for guests.
ALTER TABLE public.photobook_comments
  ADD CONSTRAINT photobook_comments_check
  CHECK (
    ((user_id IS NOT NULL) AND (guest_name IS NULL) AND (guest_email IS NULL))
    OR
    ((user_id IS NULL) AND (guest_name IS NOT NULL) AND (guest_email IS NOT NULL))
  );

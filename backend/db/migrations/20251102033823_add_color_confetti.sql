-- migrate:up
ALTER TYPE public.open_confetti ADD VALUE IF NOT EXISTS 'color_only';

-- migrate:down
-- No-op: PostgreSQL doesn't support dropping a single enum value.


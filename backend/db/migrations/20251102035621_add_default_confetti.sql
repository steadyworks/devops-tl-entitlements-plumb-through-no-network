-- migrate:up
ALTER TYPE public.open_confetti ADD VALUE IF NOT EXISTS 'default';

-- migrate:down
-- No-op: PostgreSQL doesn't support dropping a single enum value.
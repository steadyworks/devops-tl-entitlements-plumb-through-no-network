-- migrate:up
-- migrate:up

-- 1) Schema changes on public.users
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS updated_at       timestamptz,
  ADD COLUMN IF NOT EXISTS confirmed_at     timestamptz,
  ADD COLUMN IF NOT EXISTS banned_until     timestamptz,
  ADD COLUMN IF NOT EXISTS deleted_at       timestamptz,
  ADD COLUMN IF NOT EXISTS is_anonymous     boolean DEFAULT false NOT NULL;

-- 2) Replace INSERT function with UPSERT and extra columns
CREATE OR REPLACE FUNCTION public.handle_user_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
  INSERT INTO public.users (
      id,
      email,
      phone,
      email_confirmed_at,
      phone_confirmed_at,
      name,
      created_at,
      updated_at,
      confirmed_at,
      banned_until,
      deleted_at,
      is_anonymous
  )
  VALUES (
      NEW.id,
      NEW.email,
      NEW.phone,
      NEW.email_confirmed_at,
      NEW.phone_confirmed_at,
      user_name,
      NEW.created_at,
      NEW.updated_at,
      NEW.confirmed_at,
      NEW.banned_until,
      NEW.deleted_at,
      COALESCE(NEW.is_anonymous, false)
  )
  ON CONFLICT (id) DO UPDATE
  SET email               = EXCLUDED.email,
      phone               = EXCLUDED.phone,
      email_confirmed_at  = EXCLUDED.email_confirmed_at,
      phone_confirmed_at  = EXCLUDED.phone_confirmed_at,
      name                = EXCLUDED.name,
      created_at          = EXCLUDED.created_at,
      updated_at          = EXCLUDED.updated_at,
      confirmed_at        = EXCLUDED.confirmed_at,
      banned_until        = EXCLUDED.banned_until,
      deleted_at          = EXCLUDED.deleted_at,
      is_anonymous        = EXCLUDED.is_anonymous;
  RETURN NEW;
END;
$$;

-- 3) Replace UPDATE function to sync extra columns
CREATE OR REPLACE FUNCTION public.handle_user_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
  UPDATE public.users
  SET
      email               = NEW.email,
      phone               = NEW.phone,
      email_confirmed_at  = NEW.email_confirmed_at,
      phone_confirmed_at  = NEW.phone_confirmed_at,
      name                = user_name,
      created_at          = NEW.created_at,
      updated_at          = NEW.updated_at,
      confirmed_at        = NEW.confirmed_at,
      banned_until        = NEW.banned_until,
      deleted_at          = NEW.deleted_at,
      is_anonymous        = COALESCE(NEW.is_anonymous, false)
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;

-- (Deletion function stays as-is; no change)
-- CREATE OR REPLACE FUNCTION public.handle_user_delete() ... (unchanged)

-- 4) One-time backfill from auth.users -> public.users
INSERT INTO public.users (
    id,
    email,
    phone,
    email_confirmed_at,
    phone_confirmed_at,
    name,
    created_at,
    updated_at,
    confirmed_at,
    banned_until,
    deleted_at,
    is_anonymous
)
SELECT
    u.id,
    u.email,
    u.phone,
    u.email_confirmed_at,
    u.phone_confirmed_at,
    (u.raw_user_meta_data->>'name')::text,
    u.created_at,
    u.updated_at,
    u.confirmed_at,
    u.banned_until,
    u.deleted_at,
    COALESCE(u.is_anonymous, false)
FROM auth.users u
ON CONFLICT (id) DO UPDATE
SET email               = EXCLUDED.email,
    phone               = EXCLUDED.phone,
    email_confirmed_at  = EXCLUDED.email_confirmed_at,
    phone_confirmed_at  = EXCLUDED.phone_confirmed_at,
    name                = EXCLUDED.name,
    created_at          = EXCLUDED.created_at,
    updated_at          = EXCLUDED.updated_at,
    confirmed_at        = EXCLUDED.confirmed_at,
    banned_until        = EXCLUDED.banned_until,
    deleted_at          = EXCLUDED.deleted_at,
    is_anonymous        = EXCLUDED.is_anonymous;


-- migrate:down

-- Revert the INSERT/UPDATE functions to the previous (minimal) versions
-- and drop the added columns. (Delete function remains unchanged.)

CREATE OR REPLACE FUNCTION public.handle_user_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
  INSERT INTO public.users (
      id,
      email,
      phone,
      email_confirmed_at,
      phone_confirmed_at,
      name
  )
  VALUES (
      NEW.id,
      NEW.email,
      NEW.phone,
      NEW.email_confirmed_at,
      NEW.phone_confirmed_at,
      user_name
  );
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.handle_user_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
  UPDATE public.users
  SET
      email = NEW.email,
      phone = NEW.phone,
      email_confirmed_at = NEW.email_confirmed_at,
      phone_confirmed_at = NEW.phone_confirmed_at,
      name = user_name
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;

ALTER TABLE public.users
  DROP COLUMN IF EXISTS is_anonymous,
  DROP COLUMN IF EXISTS deleted_at,
  DROP COLUMN IF EXISTS banned_until,
  DROP COLUMN IF EXISTS confirmed_at,
  DROP COLUMN IF EXISTS updated_at;

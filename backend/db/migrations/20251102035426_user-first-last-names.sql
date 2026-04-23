-- migrate:up

-- 1) add optional columns to public.users
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS first_name text,
  ADD COLUMN IF NOT EXISTS last_name  text;

-- 2) update trigger functions to also sync first_name / last_name

CREATE OR REPLACE FUNCTION public.handle_user_insert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
  user_name       TEXT := (NEW.raw_user_meta_data->>'name');
  user_first_name TEXT := (NEW.raw_user_meta_data->>'first_name');
  user_last_name  TEXT := (NEW.raw_user_meta_data->>'last_name');
BEGIN
  INSERT INTO public.users (
      id,
      email,
      phone,
      email_confirmed_at,
      phone_confirmed_at,
      name,
      first_name,
      last_name,
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
      user_first_name,
      user_last_name,
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
      first_name          = EXCLUDED.first_name,
      last_name           = EXCLUDED.last_name,
      created_at          = EXCLUDED.created_at,
      updated_at          = EXCLUDED.updated_at,
      confirmed_at        = EXCLUDED.confirmed_at,
      banned_until        = EXCLUDED.banned_until,
      deleted_at          = EXCLUDED.deleted_at,
      is_anonymous        = EXCLUDED.is_anonymous;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.handle_user_update() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
  user_name       TEXT := (NEW.raw_user_meta_data->>'name');
  user_first_name TEXT := (NEW.raw_user_meta_data->>'first_name');
  user_last_name  TEXT := (NEW.raw_user_meta_data->>'last_name');
BEGIN
  UPDATE public.users
  SET
      email               = NEW.email,
      phone               = NEW.phone,
      email_confirmed_at  = NEW.email_confirmed_at,
      phone_confirmed_at  = NEW.phone_confirmed_at,
      name                = user_name,
      first_name          = user_first_name,
      last_name           = user_last_name,
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

-- migrate:down

-- Revert functions to prior behavior (only syncing 'name')
CREATE OR REPLACE FUNCTION public.handle_user_insert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
AS $$
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

CREATE OR REPLACE FUNCTION public.handle_user_update() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
AS $$
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

-- Drop the added columns
ALTER TABLE public.users
  DROP COLUMN IF EXISTS first_name,
  DROP COLUMN IF EXISTS last_name;

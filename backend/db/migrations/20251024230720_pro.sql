-- migrate:up

CREATE TABLE public.background_img_registry (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    pro boolean DEFAULT false NOT NULL,
    CONSTRAINT background_img_registry_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE public.background_img_registry IS 'Registry of background images available to users.';
COMMENT ON COLUMN public.background_img_registry.id IS 'Auto-generated UUID primary key.';
COMMENT ON COLUMN public.background_img_registry.name IS 'hashed name of the background image. must be unique, and can be used to reference the image.';
COMMENT ON COLUMN public.background_img_registry.description IS 'Optional longer description.';
COMMENT ON COLUMN public.background_img_registry.pro IS 'Whether this background is Pro-gated.';

-- Enforce case-insensitive uniqueness on name
CREATE UNIQUE INDEX uq_background_img_registry_name_nocase
  ON public.background_img_registry (lower(name));

-- migrate:down

-- Drop the unique index first (safe even if table is dropped later)
DROP INDEX IF EXISTS uq_background_img_registry_name_nocase;

DROP TABLE IF EXISTS public.background_img_registry;

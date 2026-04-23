-- migrate:up
ALTER TYPE public.background_theme_enum ADD VALUE IF NOT EXISTS 'midautumn';

-- migrate:down
ALTER TYPE public.background_theme_enum DROP VALUE IF EXISTS 'midautumn';

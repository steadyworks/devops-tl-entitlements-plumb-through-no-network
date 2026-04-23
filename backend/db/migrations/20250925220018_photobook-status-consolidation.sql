-- migrate:up
-- First, rename the old type

-- Clean up invalid values (scheduled -> draft)
UPDATE photobooks
SET status = 'draft'
WHERE status::text NOT IN (
    'draft',
    'pending',
    'deleted',
    'permanently_deleted',
    'shared'
);

-- Drop default to avoid cast errors (if any)
ALTER TABLE photobooks ALTER COLUMN status DROP DEFAULT;

-- Rename old type
ALTER TYPE photobook_status RENAME TO photobook_status_old;

-- Create new type without 'scheduled'
CREATE TYPE photobook_status AS ENUM (
    'draft',
    'pending',
    'deleted',
    'permanently_deleted',
    'shared'
);

-- Update column to use new type
ALTER TABLE photobooks
    ALTER COLUMN status TYPE photobook_status
    USING status::text::photobook_status;

-- Drop old type
DROP TYPE photobook_status_old;






-- migrate:down
-- Drop default first
ALTER TABLE photobooks ALTER COLUMN status DROP DEFAULT;

-- Rename current type
ALTER TYPE photobook_status RENAME TO photobook_status_old;

-- Recreate type with 'scheduled'
CREATE TYPE photobook_status AS ENUM (
    'draft',
    'pending',
    'deleted',
    'permanently_deleted',
    'shared',
    'scheduled'
);

-- Convert column back to the expanded type
ALTER TABLE photobooks
    ALTER COLUMN status TYPE photobook_status
    USING status::text::photobook_status;

-- Drop old type
DROP TYPE photobook_status_old;

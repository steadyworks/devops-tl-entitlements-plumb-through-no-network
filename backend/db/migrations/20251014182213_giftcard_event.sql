-- migrate:up

-- enum for event kind
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'giftcard_event_kind') THEN
    CREATE TYPE public.giftcard_event_kind AS ENUM ('issue_attempt', 'issue_success', 'issue_failure', 'access_attempt', 'access_success', 'access_failure');
  END IF;
END$$;

-- table
CREATE TABLE IF NOT EXISTS public.giftcard_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  giftcard_id uuid NOT NULL REFERENCES public.giftcards(id) ON DELETE CASCADE,
  provider public.giftcard_provider NOT NULL,
  kind public.giftcard_event_kind NOT NULL,

  message text NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now()
);

-- indexes
CREATE INDEX IF NOT EXISTS giftcard_events_giftcard_id_idx ON public.giftcard_events (giftcard_id);
CREATE INDEX IF NOT EXISTS giftcard_events_created_at_idx ON public.giftcard_events (created_at);
CREATE INDEX IF NOT EXISTS giftcard_events_kind_idx ON public.giftcard_events (kind);


-- migrate:down
DROP TABLE IF EXISTS public.giftcard_events;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'giftcard_event_kind') THEN
    DROP TYPE public.giftcard_event_kind;
  END IF;
END$$;

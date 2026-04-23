-- migrate:up
-- migrate:up
ALTER TABLE public.payments
  ADD COLUMN fulfilled_at timestamptz NULL,
  ADD COLUMN fulfillment_last_error text NULL;

ALTER TABLE public.payment_events
  ADD COLUMN event_type text;

CREATE INDEX IF NOT EXISTS idx_payments_fulfilled_at
  ON public.payments(fulfilled_at DESC);

-- migrate:down
ALTER TABLE public.payments
  DROP COLUMN IF EXISTS fulfillment_last_error,
  DROP COLUMN IF EXISTS fulfilled_at;

ALTER TABLE public.payment_events
  DROP COLUMN IF EXISTS event_type;
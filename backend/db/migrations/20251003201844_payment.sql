-- migrate:up

-- 1) Enums
CREATE TYPE public.payment_purpose AS ENUM (
  'giftcard',
  'other'
);

CREATE TYPE public.payment_status AS ENUM (
  'requires_payment_method',
  'requires_confirmation',
  'requires_action',
  'processing',
  'requires_capture',
  'canceled',
  'succeeded',
  'failed'
);

CREATE TYPE public.payment_event_source AS ENUM ('stripe_webhook', 'system');

COMMENT ON TYPE public.payment_purpose IS 'Business intent for the payment (helps reporting and routing).';
COMMENT ON TYPE public.payment_status  IS 'Mirrors Stripe PaymentIntent.status; minimal, boring, reliable.';
COMMENT ON TYPE public.payment_event_source IS 'Origin of the event row: Stripe webhook vs internal/system.';

-- 2) payments (authoritative, one row per Stripe PaymentIntent)
CREATE TABLE public.payments (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,

  -- Business linkage (flexible, nullable to keep schema minimal)
  created_by_user_id uuid REFERENCES public.users(id) ON DELETE SET NULL,
  photobook_id uuid REFERENCES public.photobooks(id) ON DELETE SET NULL,

  purpose public.payment_purpose NOT NULL DEFAULT 'other',

  -- Money
  amount_total int NOT NULL,      -- smallest currency unit (e.g. cents)
  currency text NOT NULL,            -- lowercase ISO 4217, e.g. 'usd'

  -- Stripe identifiers for reconciliation
  stripe_payment_intent_id text UNIQUE,
  stripe_customer_id text,
  stripe_payment_method_id text,
  stripe_latest_charge_id text,

  -- Lifecycle
  status public.payment_status NOT NULL,
  description text,
  receipt_email text,

  -- Idempotency for our own create-intent calls (optional but recommended)
  idempotency_key text,

  -- Last error snapshot (for failed)
  failure_code text,
  failure_message text,

  -- Minimal rollups / misc
  refunded_amount int DEFAULT 0 NOT NULL,
  metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,

  -- Timestamps
  created_at timestamptz DEFAULT now() NOT NULL,
  updated_at timestamptz DEFAULT now() NOT NULL,

  -- Guards
  CONSTRAINT chk_payment_amount_positive CHECK (amount_total > 0),
  CONSTRAINT chk_payment_currency_lower  CHECK (currency = lower(currency))
);

COMMENT ON TABLE public.payments IS 'Authoritative record for each Stripe PaymentIntent and its lifecycle.';
COMMENT ON COLUMN public.payments.amount_total IS 'Amount in smallest currency unit (e.g., cents).';
COMMENT ON COLUMN public.payments.status IS '1:1 mapping to Stripe PaymentIntent.status.';
COMMENT ON COLUMN public.payments.idempotency_key IS 'App-level idempotency key used when creating the PaymentIntent.';
COMMENT ON COLUMN public.payments.refunded_amount IS 'Simple aggregate of refunds (add a refunds table later if needed).';

CREATE INDEX idx_payments_created_by ON public.payments(created_by_user_id, created_at DESC);
CREATE INDEX idx_payments_photobook ON public.payments(photobook_id, created_at DESC);
CREATE INDEX idx_payments_status ON public.payments(status);
CREATE UNIQUE INDEX uq_payments_idempotency_key
  ON public.payments(idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- 3) payment_events (append-only; stores webhook bodies; prevents double-apply)
CREATE TABLE public.payment_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  payment_id uuid REFERENCES public.payments(id) ON DELETE CASCADE,

  -- Stripe webhook reconciliation
  stripe_event_id text,               -- unique when source=stripe_webhook
  stripe_event_type text,             -- e.g. 'payment_intent.succeeded'
  source public.payment_event_source NOT NULL,
  payload jsonb NOT NULL,             -- full webhook body or internal snapshot
  signature_verified boolean,         -- for webhooks

  -- convenience mirror of the state we applied because of this event
  applied_status public.payment_status,

  created_at timestamptz DEFAULT now() NOT NULL
);

COMMENT ON TABLE public.payment_events IS 'Append-only audit of payment lifecycle events (webhooks + internal).';
COMMENT ON COLUMN public.payment_events.stripe_event_id IS 'Used to dedupe Stripe webhooks (unique per event).';

CREATE UNIQUE INDEX uq_payment_events_stripe_event_id
  ON public.payment_events(stripe_event_id)
  WHERE stripe_event_id IS NOT NULL;

CREATE INDEX idx_payment_events_payment_created
  ON public.payment_events(payment_id, created_at);

-- 4) shares_payments_rel (tiny junction to associate payments to shares)
CREATE TABLE public.shares_payments_rel (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  share_id uuid NOT NULL REFERENCES public.shares(id) ON DELETE CASCADE,
  payment_id uuid NOT NULL REFERENCES public.payments(id) ON DELETE CASCADE,
  created_at timestamptz DEFAULT now() NOT NULL,
  UNIQUE (share_id, payment_id)
);

COMMENT ON TABLE public.shares_payments_rel IS 'Associates a share with one or more payments without denormalizing.';
CREATE INDEX idx_share_payments_share ON public.shares_payments_rel(share_id);


-- migrate:down

-- Drop in reverse dependency order

DROP TABLE IF EXISTS public.shares_payments_rel;
DROP INDEX IF EXISTS uq_payment_events_stripe_event_id;
DROP INDEX IF EXISTS idx_payment_events_payment_created;
DROP TABLE IF EXISTS public.payment_events;

DROP INDEX IF EXISTS uq_payments_idempotency_key;
DROP INDEX IF EXISTS idx_payments_status;
DROP INDEX IF EXISTS idx_payments_photobook;
DROP INDEX IF EXISTS idx_payments_share;
DROP INDEX IF EXISTS idx_payments_created_by;
DROP TABLE IF EXISTS public.payments;

DROP TYPE IF EXISTS public.payment_event_source;
DROP TYPE IF EXISTS public.payment_status;
DROP TYPE IF EXISTS public.payment_purpose;

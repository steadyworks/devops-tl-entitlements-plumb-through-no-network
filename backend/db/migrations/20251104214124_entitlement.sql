-- migrate:up

-- 1) Drop table no longer used
DROP TABLE IF EXISTS public.subscriptions CASCADE;

-- 2) Rename entitlements.key -> product_id
ALTER TABLE public.entitlements
  RENAME COLUMN key TO product_id;

COMMENT ON COLUMN public.entitlements.product_id IS
  'RevenueCat product identifier currently granting access (e.g., com.memry.pro.monthly).';

-- 3) Add entitlement_id (RC entitlement identifier like "pro")
ALTER TABLE public.entitlements
  ADD COLUMN entitlement_id text;

COMMENT ON COLUMN public.entitlements.entitlement_id IS
  'RevenueCat entitlement identifier mapped to this row (e.g., "pro").';

-- 4) Event log for webhooks + internal updates (similar to payment_events)
-- Create a small source enum for origin of the row
DO $$
BEGIN
  CREATE TYPE public.subscription_event_source AS ENUM ('rc_webhook', 'system', 'client');
EXCEPTION WHEN duplicate_object THEN
  NULL;
END$$;

CREATE TABLE public.subscription_events (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Who the event pertains to (authoritative join key in our system)
  user_id               uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

  -- Lightweight denormalized pointers from the RC event body
  product_id            text,          -- e.g., "pro_monthly" or "subid:baseplan"
  entitlement_id        text,          -- e.g., "pro"

  -- RevenueCat webhook identity / type (for dedupe & quick filtering)
  rc_event_id           text,          -- RevenueCat 'event.id' (unique per event)
  rc_event_type         text,          -- RevenueCat 'event.type' (INITIAL_PURCHASE, RENEWAL, ...)

  -- Origin + raw payload
  source                public.subscription_event_source NOT NULL,
  payload               jsonb NOT NULL,  -- full webhook or internal snapshot

  -- Optional verification & state projection
  signature_verified    boolean,         -- HMAC verification result for RC webhook requests
  applied_status        public.subscription_status,  -- our projected status after applying this event

  -- Timestamps
  created_at            timestamptz NOT NULL DEFAULT now(),
  event_timestamp_ms    bigint            -- passthrough of RC 'event_timestamp_ms' if available
);

COMMENT ON TABLE public.subscription_events IS
  'Append-only audit of subscription lifecycle events (RevenueCat webhooks + internal signals).';

COMMENT ON COLUMN public.subscription_events.rc_event_id IS
  'RevenueCat event.id; used to dedupe webhook retries (unique when present).';

COMMENT ON COLUMN public.subscription_events.applied_status IS
  'Our effective subscription_status after handling this event (active/expired/cancelled/billing_issue).';

-- Helpful indexes
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscription_events_rc_event_id
  ON public.subscription_events (rc_event_id)
  WHERE rc_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_subscription_events_user_created
  ON public.subscription_events (user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_subscription_events_source
  ON public.subscription_events (source);



-- migrate:down

-- Drop events table + enum
DROP TABLE IF EXISTS public.subscription_events;

DROP TYPE IF EXISTS public.subscription_event_source;

-- Revert entitlements changes
ALTER TABLE public.entitlements
  DROP COLUMN IF EXISTS entitlement_id;

ALTER TABLE public.entitlements
  RENAME COLUMN product_id TO key;

COMMENT ON COLUMN public.entitlements.key IS
  'Entitlement key (e.g., pro).';

-- Recreate legacy public.subscriptions table (as previously defined)
CREATE TABLE public.subscriptions (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                   uuid NOT NULL,
  store                     text NOT NULL,
  product_id                text NOT NULL,
  status                    public.subscription_status NOT NULL,
  started_at                timestamptz NOT NULL,
  expires_at                timestamptz,
  original_transaction_id   text,
  updated_at                timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.subscriptions IS
  'RevenueCat/App Store purchase records mirrored for app logic and audits.';

COMMENT ON COLUMN public.subscriptions.store IS
  'Store source (app_store/play_store/stripe/amazon/mac_app_store/promotional/etc).';

COMMENT ON COLUMN public.subscriptions.status IS
  'Purchase lifecycle for app logic (active/expired/cancelled/billing_issue).';

ALTER TABLE public.subscriptions
  ADD CONSTRAINT subscriptions_user_fk
  FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

-- Recreate indexes that previously existed
CREATE INDEX idx_subscriptions_user_id    ON public.subscriptions (user_id);
CREATE INDEX idx_subscriptions_product_id ON public.subscriptions (product_id);
CREATE INDEX idx_subscriptions_status     ON public.subscriptions (status);

CREATE UNIQUE INDEX uq_subscriptions_original_txn
  ON public.subscriptions (store, original_transaction_id)
  WHERE original_transaction_id IS NOT NULL;


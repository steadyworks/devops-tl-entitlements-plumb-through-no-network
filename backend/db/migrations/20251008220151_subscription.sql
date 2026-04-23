-- migrate:up

-- Create enum for subscription status
DO $$ BEGIN
  CREATE TYPE public.subscription_status AS ENUM (
    'active',
    'expired',
    'cancelled',
    'billing_issue'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- Subscriptions: one row per purchase/renewal lifecycle state
CREATE TABLE public.subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    store TEXT NOT NULL, -- e.g. 'app_store', 'play_store', 'stripe', etc.
    product_id TEXT NOT NULL,
    status public.subscription_status NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    original_transaction_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.subscriptions IS 'RevenueCat/App Store purchase records mirrored for app logic and audits.';
COMMENT ON COLUMN public.subscriptions.store IS 'Store source (app_store/play_store/stripe/amazon/mac_app_store/promotional/etc).';
COMMENT ON COLUMN public.subscriptions.status IS 'Purchase lifecycle for app logic (active/expired/cancelled/billing_issue).';

-- FK to your existing users table (which itself references auth.users)
ALTER TABLE public.subscriptions
    ADD CONSTRAINT subscriptions_user_fk
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

-- Helpful indexes
CREATE INDEX idx_subscriptions_user_id ON public.subscriptions (user_id);
CREATE INDEX idx_subscriptions_status ON public.subscriptions (status);
CREATE INDEX idx_subscriptions_product_id ON public.subscriptions (product_id);

-- Deduplicate by original_transaction_id within a store when present
CREATE UNIQUE INDEX uq_subscriptions_original_txn
ON public.subscriptions (store, original_transaction_id)
WHERE original_transaction_id IS NOT NULL;


-- Entitlements: canonical per-user entitlement snapshot for gating
-- NOTE: matches your model (PRIMARY KEY on user_id). If you later want multiple
-- entitlements per user, switch PK to (user_id, key).
CREATE TABLE public.entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    key TEXT NOT NULL,          -- e.g. 'pro'
    active BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.entitlements IS 'Canonical entitlement state used by web gating and API.';
COMMENT ON COLUMN public.entitlements.key IS 'Entitlement key (e.g., pro).';

ALTER TABLE public.entitlements
    ADD CONSTRAINT entitlements_user_fk
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

-- For quick lookups by upcoming expirations, if needed later:
-- CREATE INDEX IF NOT EXISTS idx_entitlements_expires_at ON public.entitlements (expires_at);


-- migrate:down

-- Drop in reverse order of dependencies
DROP TABLE IF EXISTS public.entitlements;

DROP INDEX IF EXISTS uq_subscriptions_original_txn;
DROP INDEX IF EXISTS idx_subscriptions_product_id;
DROP INDEX IF EXISTS idx_subscriptions_status;
DROP INDEX IF EXISTS idx_subscriptions_user_id;

DROP TABLE IF EXISTS public.subscriptions;

-- Finally, drop the enum type
DROP TYPE IF EXISTS public.subscription_status;
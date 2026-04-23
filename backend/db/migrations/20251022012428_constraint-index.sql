-- migrate:up
-- Drop the existing table-level unique constraint
ALTER TABLE public.payments
DROP CONSTRAINT IF EXISTS payments_stripe_payment_intent_id_key;

-- Create a dedicated unique index instead (same semantics)
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_stripe_payment_intent_id_unique
    ON public.payments (stripe_payment_intent_id);

-- migrate:down
-- Rollback: drop the index and restore the table-level constraint
DROP INDEX IF EXISTS idx_payments_stripe_payment_intent_id_unique;

ALTER TABLE public.payments
    ADD CONSTRAINT payments_stripe_payment_intent_id_key
    UNIQUE (stripe_payment_intent_id);
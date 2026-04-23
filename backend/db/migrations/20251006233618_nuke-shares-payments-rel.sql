-- migrate:up

-- Drop the join table. Its indexes/constraints are owned by the table
-- and will be dropped automatically.
DROP TABLE IF EXISTS public.shares_payments_rel;

-- migrate:down

-- Ensure gen_random_uuid() exists (used by the table default).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Recreate the table exactly as before.
CREATE TABLE public.shares_payments_rel (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    share_id uuid NOT NULL,
    payment_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- Primary key
ALTER TABLE ONLY public.shares_payments_rel
    ADD CONSTRAINT shares_payments_rel_pkey PRIMARY KEY (id);

-- Unique pair (share_id, payment_id)
ALTER TABLE ONLY public.shares_payments_rel
    ADD CONSTRAINT shares_payments_rel_share_id_payment_id_key UNIQUE (share_id, payment_id);

-- Indexes
CREATE INDEX idx_share_payments_share
  ON public.shares_payments_rel USING btree (share_id);

-- Foreign keys
ALTER TABLE ONLY public.shares_payments_rel
    ADD CONSTRAINT shares_payments_rel_payment_id_fkey
    FOREIGN KEY (payment_id) REFERENCES public.payments(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.shares_payments_rel
    ADD CONSTRAINT shares_payments_rel_share_id_fkey
    FOREIGN KEY (share_id) REFERENCES public.shares(id) ON DELETE CASCADE;

-- Comment
COMMENT ON TABLE public.shares_payments_rel
    IS 'Associates a share with one or more payments without denormalizing.';

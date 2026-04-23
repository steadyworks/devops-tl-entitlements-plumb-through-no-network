-- migrate:up

-- 1) Enums for gift cards
CREATE TYPE public.giftcard_status AS ENUM (
  'granted',    -- logical grant (after PI create, before issuance)
  'issued',     -- code/asset created and ready to redeem
  'redeemed',   -- fully redeemed (or balance 0 if you later support partials)
  'canceled',   -- explicitly canceled by us
  'expired'     -- provider/app expiration reached
);

-- Optional: if you use a vendor, keep this generic for now (text would also work).
CREATE TYPE public.giftcard_provider AS ENUM ('acgod', 'giftbit', 'other');

COMMENT ON TYPE public.giftcard_status IS 'Gift card lifecycle.';
COMMENT ON TYPE public.giftcard_provider IS 'Issuance provider.';

-- 2) Gift cards table (1:1 with share)
CREATE TABLE public.giftcards (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  -- ownership / linkage
  share_id uuid NOT NULL REFERENCES public.shares(id) ON DELETE CASCADE,
  created_by_payment_id uuid REFERENCES public.payments(id) ON DELETE SET NULL,
  created_by_user_id uuid REFERENCES public.users(id) ON DELETE SET NULL,

  -- money
  amount_total int NOT NULL,        -- minimal currency unit (e.g. cents)
  currency text NOT NULL,

  -- issuance
  provider public.giftcard_provider,
  brand_code text,
  provider_giftcard_id text,              -- provider’s id (unique per provider)
  giftcard_code_explicit_override text,   -- if you manage codes (store hashed in prod if sensitive)
  idempotency_key text,                    -- to dedupe issuance requests

  -- lifecycle
  status public.giftcard_status NOT NULL DEFAULT 'granted'::public.giftcard_status,
  granted_at timestamptz DEFAULT now() NOT NULL,
  issued_at timestamptz,
  redeemed_at timestamptz,
  canceled_at timestamptz,
  expires_at timestamptz,

  -- misc
  description text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  -- guards
  CONSTRAINT chk_giftcard_amount_positive CHECK (amount_total > 0),
  CONSTRAINT chk_giftcard_currency_lower CHECK (currency = lower(currency))
);

COMMENT ON TABLE public.giftcards IS 'Lifecycle and issuance state for a gift card attached 1:1 to a share.';

-- 1:1 with share (enforced)
CREATE UNIQUE INDEX uq_giftcards_share ON public.giftcards(share_id);

-- Provider de-dupes / issuance safety
CREATE UNIQUE INDEX uq_giftcards_provider_id
  ON public.giftcards(provider, provider_giftcard_id)
  WHERE provider_giftcard_id IS NOT NULL;

CREATE UNIQUE INDEX uq_giftcards_giftcard_code_explicit_override
  ON public.giftcards(giftcard_code_explicit_override)
  WHERE giftcard_code_explicit_override IS NOT NULL;

CREATE UNIQUE INDEX uq_giftcards_idempotency
  ON public.giftcards(idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_giftcards_status ON public.giftcards(status);
CREATE INDEX idx_giftcards_payment ON public.giftcards(created_by_payment_id);

-- 3) Payments.recipients_json (snapshot used to create shares & channels later)
ALTER TABLE public.payments
  ADD COLUMN IF NOT EXISTS share_create_request jsonb;

COMMENT ON COLUMN public.payments.share_create_request
  IS 'Snapshot of intended ShareCreateRequest (recipients/channels), used for idempotent recovery in webhook.';


-- 4) (Recommended) Keep parity with your earlier Python model: payments.share_id
--    If you prefer only the junction table, you can skip this.
ALTER TABLE public.shares
  ADD COLUMN IF NOT EXISTS created_by_payment_id uuid;

ALTER TABLE public.shares
  ADD CONSTRAINT payment_shares_id_fkey
  FOREIGN KEY (created_by_payment_id) REFERENCES public.payments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_payments_share_id ON public.shares(created_by_payment_id);



-- migrate:down
-- Drop in reverse order of dependencies
ALTER TABLE IF EXISTS public.payments DROP CONSTRAINT IF EXISTS payment_shares_id_fkey;
ALTER TABLE IF EXISTS public.shares DROP COLUMN IF EXISTS created_by_payment_id;
ALTER TABLE IF EXISTS public.payments DROP COLUMN IF EXISTS share_create_request;

DROP INDEX IF EXISTS idx_giftcards_payment;
DROP INDEX IF EXISTS idx_giftcards_status;
DROP INDEX IF EXISTS uq_giftcards_idempotency;
DROP INDEX IF EXISTS uq_giftcards_giftcard_code_explicit_override;
DROP INDEX IF EXISTS uq_giftcards_provider_id;
DROP INDEX IF EXISTS uq_giftcards_share;

DROP TABLE IF EXISTS public.giftcards;

DROP TYPE IF EXISTS public.giftcard_provider;
DROP TYPE IF EXISTS public.giftcard_status;

-- migrate:up

ALTER TABLE public.giftcards
  ALTER COLUMN brand_code SET NOT NULL;

-- migrate:down

ALTER TABLE public.giftcards
  ALTER COLUMN brand_code DROP NOT NULL;
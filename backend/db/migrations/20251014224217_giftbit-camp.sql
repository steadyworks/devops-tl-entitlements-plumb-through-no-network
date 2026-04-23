-- migrate:up

ALTER TABLE public.giftcards
    ADD COLUMN giftbit_cached_gift_link text,
    ADD COLUMN giftbit_cached_campaign_uuid text;


-- migrate:down

ALTER TABLE public.giftcards
    DROP COLUMN IF EXISTS giftbit_cached_gift_link text,
    DROP COLUMN IF EXISTS giftbit_cached_campaign_uuid text;
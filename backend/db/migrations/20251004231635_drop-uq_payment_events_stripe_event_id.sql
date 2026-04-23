-- migrate:up
DROP INDEX IF EXISTS uq_payment_events_stripe_event_id;

-- migrate:down

CREATE UNIQUE INDEX uq_payment_events_stripe_event_id
    ON public.payment_events USING btree (stripe_event_id)
    WHERE stripe_event_id IS NOT NULL;

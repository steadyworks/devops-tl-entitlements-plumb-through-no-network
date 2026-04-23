--
-- PostgreSQL database dump
--

-- Dumped from database version 17.4
-- Dumped by pg_dump version 17.5 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: actor_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.actor_type AS ENUM (
    'user',
    'job_manager',
    'job_processor',
    'worker_process',
    'system'
);


--
-- Name: TYPE actor_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.actor_type IS 'Attribution source of job_events. Indicates which actor type triggered the event.';


--
-- Name: asset_upload_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.asset_upload_status AS ENUM (
    'pending',
    'processing',
    'ready',
    'invalid_mime',
    'processing_failed',
    'upload_failed',
    'upload_succeeded'
);


--
-- Name: background_theme_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.background_theme_enum AS ENUM (
    'thanksgiving',
    'christmas',
    'kid',
    'travel',
    'pet',
    'birthday',
    'neutral',
    'new_year',
    'halloween',
    'midautumn'
);


--
-- Name: background_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.background_type AS ENUM (
    'color',
    'staticimg'
);


--
-- Name: comment_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.comment_status AS ENUM (
    'visible',
    'hidden_by_author',
    'deleted_by_system'
);


--
-- Name: font_style; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.font_style AS ENUM (
    'unspecified',
    'playfair',
    'cinzel',
    'lora',
    'zilla_slab',
    'caveat',
    'caveat_brush',
    'fredoka',
    'grandstander'
);


--
-- Name: giftcard_event_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.giftcard_event_kind AS ENUM (
    'issue_attempt',
    'issue_success',
    'issue_failure',
    'access_attempt',
    'access_success',
    'access_failure'
);


--
-- Name: giftcard_provider; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.giftcard_provider AS ENUM (
    'agcod',
    'giftbit',
    'other'
);


--
-- Name: TYPE giftcard_provider; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.giftcard_provider IS 'Issuance provider.';


--
-- Name: giftcard_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.giftcard_status AS ENUM (
    'granted',
    'issued',
    'redeemed',
    'canceled',
    'expired'
);


--
-- Name: TYPE giftcard_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.giftcard_status IS 'Gift card lifecycle.';


--
-- Name: identity_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.identity_kind AS ENUM (
    'guest',
    'user'
);


--
-- Name: job_event_action; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_event_action AS ENUM (
    'job_queued',
    'job_dequeued',
    'attempt_started',
    'job_succeeded',
    'attempt_failed',
    'attempt_retry_scheduled',
    'attempt_retry_exhausted',
    'job_marked_dead',
    'manual_attempt_started',
    'job_enqueue_failed',
    'log_info',
    'log_warning',
    'log_exception'
);


--
-- Name: TYPE job_event_action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.job_event_action IS 'Describes lifecycle and diagnostic events for jobs. Used in job_events.';


--
-- Name: job_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.job_status AS ENUM (
    'queued',
    'dequeued',
    'processing',
    'done',
    'error',
    'dead',
    'enqueue_failed'
);


--
-- Name: TYPE job_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.job_status IS 'Used in jobs table: now extended with value `dead` to indicate terminal failed state.';


--
-- Name: notification_delivery_event; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_delivery_event AS ENUM (
    'processing',
    'sent',
    'failed'
);


--
-- Name: TYPE notification_delivery_event; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.notification_delivery_event IS 'Append-only timeline event from send/webhooks.';


--
-- Name: notification_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_status AS ENUM (
    'pending',
    'sent',
    'failed'
);


--
-- Name: notification_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_type AS ENUM (
    'comment',
    'share',
    'mention',
    'like',
    'system',
    'custom'
);


--
-- Name: open_confetti; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.open_confetti AS ENUM (
    'thanksgiving_pumpkin',
    'thanksgiving_gift',
    'thanksgiving_heart',
    'christmas_santa',
    'christmas_gift',
    'christmas_light',
    'color_only',
    'default'
);


--
-- Name: TYPE open_confetti; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.open_confetti IS 'Confetti style shown when opening a photobook.';


--
-- Name: open_style; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.open_style AS ENUM (
    'twod_envelope'
);


--
-- Name: page_layout; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.page_layout AS ENUM (
    'default',
    'polaroid',
    'masonry',
    'surrounding',
    'two_diagonal'
);


--
-- Name: payment_event_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.payment_event_source AS ENUM (
    'stripe_webhook',
    'system'
);


--
-- Name: TYPE payment_event_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.payment_event_source IS 'Origin of the event row: Stripe webhook vs internal/system.';


--
-- Name: payment_purpose; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.payment_purpose AS ENUM (
    'giftcard',
    'other'
);


--
-- Name: TYPE payment_purpose; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.payment_purpose IS 'Business intent for the payment (helps reporting and routing).';


--
-- Name: payment_status; Type: TYPE; Schema: public; Owner: -
--

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


--
-- Name: TYPE payment_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.payment_status IS 'Mirrors Stripe PaymentIntent.status; minimal, boring, reliable.';


--
-- Name: photobook_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.photobook_status AS ENUM (
    'draft',
    'pending',
    'deleted',
    'permanently_deleted',
    'shared'
);


--
-- Name: photobook_status_editor; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.photobook_status_editor AS ENUM (
    'user',
    'upload_pipeline',
    'generation_pipeline',
    'system'
);


--
-- Name: TYPE photobook_status_editor; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.photobook_status_editor IS 'Actor that triggered photobook status update.';


--
-- Name: share_access_policy; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_access_policy AS ENUM (
    'anyone_with_link',
    'recipient_must_auth',
    'revoked'
);


--
-- Name: TYPE share_access_policy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_access_policy IS 'Access model for a share link.';


--
-- Name: share_channel_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_channel_status AS ENUM (
    'pending',
    'scheduled',
    'sending',
    'sent',
    'failed',
    'canceled'
);


--
-- Name: TYPE share_channel_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_channel_status IS 'Per-channel delivery status (provider webhooks are source of truth).';


--
-- Name: share_channel_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_channel_type AS ENUM (
    'email',
    'sms',
    'apns'
);


--
-- Name: TYPE share_channel_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_channel_type IS 'Notification channel type.';


--
-- Name: share_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_kind AS ENUM (
    'public',
    'recipient'
);


--
-- Name: TYPE share_kind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_kind IS 'Share audience: public link (one per photobook) vs per-recipient share.';


--
-- Name: share_notification_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_notification_type AS ENUM (
    'shared_with_you'
);


--
-- Name: TYPE share_notification_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_notification_type IS 'Delivery-oriented notification kinds used by notification_outbox and notification_delivery_attempts.';


--
-- Name: share_provider; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_provider AS ENUM (
    'resend',
    'twilio',
    'apns'
);


--
-- Name: TYPE share_provider; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TYPE public.share_provider IS 'External provider for notifications.';


--
-- Name: share_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.share_role AS ENUM (
    'viewer',
    'editor',
    'owner'
);


--
-- Name: subscription_event_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.subscription_event_source AS ENUM (
    'rc_webhook',
    'system',
    'client'
);


--
-- Name: subscription_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.subscription_status AS ENUM (
    'active',
    'expired',
    'cancelled',
    'billing_issue'
);


--
-- Name: user_provided_occasion; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.user_provided_occasion AS ENUM (
    'wedding',
    'birthday',
    'anniversary',
    'other',
    'gift',
    'memory',
    'trip'
);


--
-- Name: handle_user_delete(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_user_delete() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    DELETE FROM public.users WHERE id = OLD.id;
    RETURN OLD;
END;
$$;


--
-- Name: handle_user_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_user_insert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  user_name       TEXT := (NEW.raw_user_meta_data->>'name');
  user_first_name TEXT := (NEW.raw_user_meta_data->>'first_name');
  user_last_name  TEXT := (NEW.raw_user_meta_data->>'last_name');
BEGIN
  INSERT INTO public.users (
      id,
      email,
      phone,
      email_confirmed_at,
      phone_confirmed_at,
      name,
      first_name,
      last_name,
      created_at,
      updated_at,
      confirmed_at,
      banned_until,
      deleted_at,
      is_anonymous
  )
  VALUES (
      NEW.id,
      NEW.email,
      NEW.phone,
      NEW.email_confirmed_at,
      NEW.phone_confirmed_at,
      user_name,
      user_first_name,
      user_last_name,
      NEW.created_at,
      NEW.updated_at,
      NEW.confirmed_at,
      NEW.banned_until,
      NEW.deleted_at,
      COALESCE(NEW.is_anonymous, false)
  )
  ON CONFLICT (id) DO UPDATE
  SET email               = EXCLUDED.email,
      phone               = EXCLUDED.phone,
      email_confirmed_at  = EXCLUDED.email_confirmed_at,
      phone_confirmed_at  = EXCLUDED.phone_confirmed_at,
      name                = EXCLUDED.name,
      first_name          = EXCLUDED.first_name,
      last_name           = EXCLUDED.last_name,
      created_at          = EXCLUDED.created_at,
      updated_at          = EXCLUDED.updated_at,
      confirmed_at        = EXCLUDED.confirmed_at,
      banned_until        = EXCLUDED.banned_until,
      deleted_at          = EXCLUDED.deleted_at,
      is_anonymous        = EXCLUDED.is_anonymous;
  RETURN NEW;
END;
$$;


--
-- Name: handle_user_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_user_update() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  user_name       TEXT := (NEW.raw_user_meta_data->>'name');
  user_first_name TEXT := (NEW.raw_user_meta_data->>'first_name');
  user_last_name  TEXT := (NEW.raw_user_meta_data->>'last_name');
BEGIN
  UPDATE public.users
  SET
      email               = NEW.email,
      phone               = NEW.phone,
      email_confirmed_at  = NEW.email_confirmed_at,
      phone_confirmed_at  = NEW.phone_confirmed_at,
      name                = user_name,
      first_name          = user_first_name,
      last_name           = user_last_name,
      created_at          = NEW.created_at,
      updated_at          = NEW.updated_at,
      confirmed_at        = NEW.confirmed_at,
      banned_until        = NEW.banned_until,
      deleted_at          = NEW.deleted_at,
      is_anonymous        = COALESCE(NEW.is_anonymous, false)
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    asset_key_original text,
    asset_key_display text,
    asset_key_llm text,
    metadata_json jsonb,
    created_at timestamp with time zone DEFAULT now(),
    original_photobook_id uuid,
    upload_status public.asset_upload_status DEFAULT 'pending'::public.asset_upload_status NOT NULL,
    original_filename text,
    exif jsonb,
    blur_data_url text,
    asset_key_thumbnail text,
    user_id uuid NOT NULL
);


--
-- Name: background_img_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.background_img_registry (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    pro boolean DEFAULT false NOT NULL,
    theme public.background_theme_enum
);


--
-- Name: TABLE background_img_registry; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.background_img_registry IS 'Registry of background images available to users.';


--
-- Name: COLUMN background_img_registry.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.background_img_registry.id IS 'Auto-generated UUID primary key.';


--
-- Name: COLUMN background_img_registry.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.background_img_registry.name IS 'hashed name of the background image. must be unique, and can be used to reference the image.';


--
-- Name: COLUMN background_img_registry.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.background_img_registry.description IS 'Optional longer description.';


--
-- Name: COLUMN background_img_registry.pro; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.background_img_registry.pro IS 'Whether this background is Pro-gated.';


--
-- Name: COLUMN background_img_registry.theme; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.background_img_registry.theme IS 'Theme for this background (enum): thanksgiving, christmas, kid, travel, pet, birthday, neutral, new_year';


--
-- Name: entitlements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entitlements (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    product_id text NOT NULL,
    active boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    entitlement_id text
);


--
-- Name: TABLE entitlements; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.entitlements IS 'Canonical entitlement state used by web gating and API.';


--
-- Name: COLUMN entitlements.product_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.entitlements.product_id IS 'RevenueCat product identifier currently granting access (e.g., com.memry.pro.monthly).';


--
-- Name: COLUMN entitlements.entitlement_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.entitlements.entitlement_id IS 'RevenueCat entitlement identifier mapped to this row (e.g., "pro").';


--
-- Name: giftcard_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.giftcard_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    giftcard_id uuid NOT NULL,
    provider public.giftcard_provider NOT NULL,
    kind public.giftcard_event_kind NOT NULL,
    message text,
    payload_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: giftcards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.giftcards (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    share_id uuid NOT NULL,
    created_by_payment_id uuid,
    created_by_user_id uuid,
    amount_total integer NOT NULL,
    currency text NOT NULL,
    provider public.giftcard_provider,
    brand_code text NOT NULL,
    giftcard_code_explicit_override text,
    status public.giftcard_status DEFAULT 'granted'::public.giftcard_status NOT NULL,
    granted_at timestamp with time zone DEFAULT now() NOT NULL,
    issued_at timestamp with time zone,
    redeemed_at timestamp with time zone,
    canceled_at timestamp with time zone,
    expires_at timestamp with time zone,
    description text,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_giftcard_id_internal_only uuid NOT NULL,
    giftbit_cached_gift_link text,
    giftbit_cached_campaign_uuid text,
    CONSTRAINT chk_giftcard_amount_positive CHECK ((amount_total > 0)),
    CONSTRAINT chk_giftcard_currency_lower CHECK ((currency = lower(currency)))
);


--
-- Name: TABLE giftcards; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.giftcards IS 'Lifecycle and issuance state for a gift card attached 1:1 to a share.';


--
-- Name: job_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_action public.job_event_action NOT NULL,
    message text,
    host text,
    retry_count integer DEFAULT 0,
    extra jsonb,
    actor_type public.actor_type NOT NULL,
    actor_id text,
    job_type text,
    photobook_id uuid
);


--
-- Name: TABLE job_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.job_events IS 'Immutable audit trail for job transitions, retries, errors, and debug logs.';


--
-- Name: COLUMN job_events.event_action; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.job_events.event_action IS 'Event type that occurred (e.g. retry_scheduled, log_warning).';


--
-- Name: COLUMN job_events.actor_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.job_events.actor_type IS 'Who performed the action: system, worker, user, etc.';


--
-- Name: COLUMN job_events.actor_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.job_events.actor_id IS 'ID of actor (e.g. user UUID, system ID, worker ID) if available.';


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_type text NOT NULL,
    status public.job_status DEFAULT 'queued'::public.job_status NOT NULL,
    input_payload jsonb,
    result_payload jsonb,
    error_message text,
    user_id uuid,
    photobook_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    last_attempted_at timestamp with time zone
);


--
-- Name: COLUMN jobs.retry_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.jobs.retry_count IS 'Number of retry attempts this job has made.';


--
-- Name: COLUMN jobs.max_retries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.jobs.max_retries IS 'Maximum retries allowed before job is marked dead.';


--
-- Name: COLUMN jobs.last_attempted_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.jobs.last_attempted_at IS 'Timestamp of the last job execution attempt.';


--
-- Name: notification_delivery_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_delivery_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    share_channel_id uuid NOT NULL,
    notification_type public.share_notification_type,
    channel_type public.share_channel_type NOT NULL,
    provider public.share_provider,
    event public.notification_delivery_event NOT NULL,
    payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    notification_outbox_id uuid
);


--
-- Name: TABLE notification_delivery_attempts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_delivery_attempts IS 'Append-only audit of send/webhook events for a share channel.';


--
-- Name: notification_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_outbox (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    share_id uuid NOT NULL,
    share_channel_id uuid NOT NULL,
    channel_type public.share_channel_type NOT NULL,
    provider public.share_provider,
    status public.share_channel_status DEFAULT 'pending'::public.share_channel_status NOT NULL,
    scheduled_for timestamp with time zone,
    last_error text,
    last_provider_message_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    notification_type public.share_notification_type DEFAULT 'shared_with_you'::public.share_notification_type NOT NULL,
    dispatch_token uuid,
    created_by_user_id uuid NOT NULL,
    dispatch_claimed_at timestamp with time zone,
    idempotency_key text,
    dispatch_lease_expires_at timestamp with time zone,
    dispatch_worker_id text,
    canceled_at timestamp with time zone,
    canceled_by_user_id uuid,
    scheduled_by_user_id uuid,
    last_scheduled_at timestamp with time zone
);


--
-- Name: TABLE notification_outbox; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.notification_outbox IS 'Authoritative, per-channel notification lifecycle: pending/scheduled/sending/sent/failed/canceled.';


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    recipient_id uuid NOT NULL,
    actor_id uuid,
    type public.notification_type NOT NULL,
    photobook_id uuid,
    comment_id uuid,
    share_id uuid,
    title text,
    body text,
    cta_url text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    group_key text,
    seen_at timestamp with time zone
);


--
-- Name: pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid,
    page_number integer NOT NULL,
    user_message text,
    layout public.page_layout,
    created_at timestamp with time zone DEFAULT now(),
    user_message_alternative_options jsonb,
    revision integer DEFAULT 1 NOT NULL,
    user_message_alternative_options_outdated boolean DEFAULT false NOT NULL,
    page_lightweight_title text
);


--
-- Name: pages_assets_rel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pages_assets_rel (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    page_id uuid,
    asset_id uuid,
    order_index integer,
    caption text
);


--
-- Name: payment_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    payment_id uuid,
    stripe_event_id text,
    stripe_event_type text,
    source public.payment_event_source NOT NULL,
    payload jsonb NOT NULL,
    signature_verified boolean,
    applied_status public.payment_status,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_type text
);


--
-- Name: TABLE payment_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.payment_events IS 'Append-only audit of payment lifecycle events (webhooks + internal).';


--
-- Name: COLUMN payment_events.stripe_event_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payment_events.stripe_event_id IS 'Used to dedupe Stripe webhooks (unique per event).';


--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_by_user_id uuid NOT NULL,
    photobook_id uuid NOT NULL,
    purpose public.payment_purpose DEFAULT 'other'::public.payment_purpose NOT NULL,
    amount_total integer NOT NULL,
    currency text NOT NULL,
    stripe_payment_intent_id text,
    stripe_customer_id text,
    stripe_payment_method_id text,
    stripe_latest_charge_id text,
    status public.payment_status NOT NULL,
    description text,
    receipt_email text,
    idempotency_key text,
    failure_code text,
    failure_message text,
    refunded_amount integer DEFAULT 0 NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    share_create_request jsonb,
    fulfilled_at timestamp with time zone,
    fulfillment_last_error text,
    CONSTRAINT chk_payment_amount_positive CHECK ((amount_total > 0)),
    CONSTRAINT chk_payment_currency_lower CHECK ((currency = lower(currency)))
);


--
-- Name: TABLE payments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.payments IS 'Authoritative record for each Stripe PaymentIntent and its lifecycle.';


--
-- Name: COLUMN payments.amount_total; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.amount_total IS 'Amount in smallest currency unit (e.g., cents).';


--
-- Name: COLUMN payments.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.status IS '1:1 mapping to Stripe PaymentIntent.status.';


--
-- Name: COLUMN payments.idempotency_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.idempotency_key IS 'App-level idempotency key used when creating the PaymentIntent.';


--
-- Name: COLUMN payments.refunded_amount; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.refunded_amount IS 'Simple aggregate of refunds (add a refunds table later if needed).';


--
-- Name: COLUMN payments.share_create_request; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.share_create_request IS 'Snapshot of intended ShareCreateRequest (recipients/channels), used for idempotent recovery in webhook.';


--
-- Name: photobook_bookmarks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobook_bookmarks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    photobook_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    source text
);


--
-- Name: photobook_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobook_comments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    user_id uuid,
    guest_name text,
    guest_email text,
    body text NOT NULL,
    status public.comment_status DEFAULT 'visible'::public.comment_status NOT NULL,
    notification_status public.notification_status DEFAULT 'pending'::public.notification_status NOT NULL,
    commenter_ip text,
    user_agent text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_updated_by uuid,
    CONSTRAINT photobook_comments_check CHECK ((((user_id IS NOT NULL) AND (guest_name IS NULL) AND (guest_email IS NULL)) OR ((user_id IS NULL) AND (guest_name IS NOT NULL))))
);


--
-- Name: photobook_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobook_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    main_style text,
    font public.font_style DEFAULT 'unspecified'::public.font_style NOT NULL,
    is_comment_enabled boolean DEFAULT false NOT NULL,
    is_allow_download_all_images_enabled boolean DEFAULT false NOT NULL,
    is_tipping_enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: photobook_share; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobook_share (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    email text,
    invited_user_id uuid,
    role public.share_role DEFAULT 'viewer'::public.share_role NOT NULL,
    email_notification_status public.notification_status DEFAULT 'pending'::public.notification_status,
    custom_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT email_or_user_check CHECK ((((email IS NOT NULL) AND (invited_user_id IS NULL)) OR ((email IS NULL) AND (invited_user_id IS NOT NULL))))
);


--
-- Name: photobooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobooks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    caption text,
    theme text,
    status public.photobook_status,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    user_provided_occasion public.user_provided_occasion,
    user_provided_occasion_custom_details text,
    user_provided_context text,
    thumbnail_asset_id uuid,
    deleted_at timestamp with time zone,
    status_last_edited_by public.photobook_status_editor DEFAULT 'user'::public.photobook_status_editor,
    background_color_palette text,
    user_gift_recipient text,
    suggested_overall_gift_message text,
    suggested_overall_gift_message_tone text,
    suggested_overall_gift_message_alternative_options jsonb,
    user_id uuid NOT NULL,
    background public.background_type NOT NULL,
    bg_img_name text,
    open_style public.open_style,
    open_param jsonb,
    open_confetti public.open_confetti,
    font public.font_style DEFAULT 'unspecified'::public.font_style NOT NULL
);


--
-- Name: COLUMN photobooks.status_last_edited_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.photobooks.status_last_edited_by IS 'Indicates which component last updated status.';


--
-- Name: COLUMN photobooks.open_confetti; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.photobooks.open_confetti IS 'Optional confetti theme to use on open (e.g., thanksgiving_pumpkin, thanksgiving_gift).';


--
-- Name: COLUMN photobooks.font; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.photobooks.font IS 'Primary display font for this photobook.';


--
-- Name: photobooks_assets_rel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photobooks_assets_rel (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    asset_id uuid NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: share_channels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.share_channels (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_share_id uuid NOT NULL,
    photobook_id uuid NOT NULL,
    channel_type public.share_channel_type NOT NULL,
    destination text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone
);


--
-- Name: TABLE share_channels; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.share_channels IS 'One row per delivery avenue under a RECIPIENT share. No delivery status here; see notification_outbox.';


--
-- Name: shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shares (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    created_by_user_id uuid,
    kind public.share_kind DEFAULT 'recipient'::public.share_kind NOT NULL,
    sender_display_name text,
    recipient_display_name text,
    recipient_user_id uuid,
    share_slug text NOT NULL,
    access_policy public.share_access_policy DEFAULT 'anyone_with_link'::public.share_access_policy NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by_user_id uuid,
    revoked_reason text,
    created_by_payment_id uuid,
    CONSTRAINT chk_shares_access_policy_by_kind CHECK ((((kind = 'public'::public.share_kind) AND (access_policy = ANY (ARRAY['anyone_with_link'::public.share_access_policy, 'revoked'::public.share_access_policy]))) OR (kind = 'recipient'::public.share_kind))),
    CONSTRAINT chk_shares_kind_fields CHECK ((((kind = 'public'::public.share_kind) AND (recipient_user_id IS NULL) AND (recipient_display_name IS NULL)) OR ((kind = 'recipient'::public.share_kind) AND ((recipient_user_id IS NOT NULL) OR (recipient_display_name IS NOT NULL)))))
);


--
-- Name: TABLE shares; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.shares IS 'Per-recipient (or public) share for a photobook. Public: one per photobook, no channels.';


--
-- Name: subscription_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscription_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    product_id text,
    entitlement_id text,
    rc_event_id text,
    rc_event_type text,
    source public.subscription_event_source NOT NULL,
    payload jsonb NOT NULL,
    signature_verified boolean,
    applied_status public.subscription_status,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_timestamp_ms bigint
);


--
-- Name: TABLE subscription_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.subscription_events IS 'Append-only audit of subscription lifecycle events (RevenueCat webhooks + internal signals).';


--
-- Name: COLUMN subscription_events.rc_event_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subscription_events.rc_event_id IS 'RevenueCat event.id; used to dedupe webhook retries (unique when present).';


--
-- Name: COLUMN subscription_events.applied_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subscription_events.applied_status IS 'Our effective subscription_status after handling this event (active/expired/cancelled/billing_issue).';


--
-- Name: user_recently_viewed_photobook; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_recently_viewed_photobook (
    user_id uuid NOT NULL,
    photobook_id uuid NOT NULL,
    viewed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    email text,
    phone text,
    email_confirmed_at timestamp with time zone,
    phone_confirmed_at timestamp with time zone,
    name text,
    role text DEFAULT 'user'::text NOT NULL,
    bmc_link text,
    updated_at timestamp with time zone,
    confirmed_at timestamp with time zone,
    banned_until timestamp with time zone,
    deleted_at timestamp with time zone,
    is_anonymous boolean DEFAULT false NOT NULL,
    seen_cover_guide boolean,
    seen_section_guide boolean,
    seen_page_content_guide boolean,
    profile_pic_asset_id uuid,
    first_name text,
    last_name text
);


--
-- Name: COLUMN users.seen_cover_guide; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.users.seen_cover_guide IS 'Has the user seen the cover editor onboarding/guide.';


--
-- Name: COLUMN users.seen_section_guide; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.users.seen_section_guide IS 'Has the user seen the section editor onboarding/guide.';


--
-- Name: COLUMN users.seen_page_content_guide; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.users.seen_page_content_guide IS 'Has the user seen the page content editor onboarding/guide.';


--
-- Name: COLUMN users.profile_pic_asset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.users.profile_pic_asset_id IS 'Optional reference to public.assets.id for the user’s profile picture.';


--
-- Name: assets assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_pkey PRIMARY KEY (id);


--
-- Name: background_img_registry background_img_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.background_img_registry
    ADD CONSTRAINT background_img_registry_pkey PRIMARY KEY (id);


--
-- Name: entitlements entitlements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entitlements
    ADD CONSTRAINT entitlements_pkey PRIMARY KEY (id);


--
-- Name: giftcard_events giftcard_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcard_events
    ADD CONSTRAINT giftcard_events_pkey PRIMARY KEY (id);


--
-- Name: giftcards giftcards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcards
    ADD CONSTRAINT giftcards_pkey PRIMARY KEY (id);


--
-- Name: job_events job_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: notification_delivery_attempts notification_delivery_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_delivery_attempts
    ADD CONSTRAINT notification_delivery_attempts_pkey PRIMARY KEY (id);


--
-- Name: notification_outbox notification_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_group_key_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_group_key_unique UNIQUE (recipient_id, type, group_key);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: pages_assets_rel pages_assets_rel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages_assets_rel
    ADD CONSTRAINT pages_assets_rel_pkey PRIMARY KEY (id);


--
-- Name: pages pages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_pkey PRIMARY KEY (id);


--
-- Name: payment_events payment_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_events
    ADD CONSTRAINT payment_events_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: photobook_bookmarks photobook_bookmarks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_bookmarks
    ADD CONSTRAINT photobook_bookmarks_pkey PRIMARY KEY (id);


--
-- Name: photobook_comments photobook_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_comments
    ADD CONSTRAINT photobook_comments_pkey PRIMARY KEY (id);


--
-- Name: photobook_settings photobook_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_settings
    ADD CONSTRAINT photobook_settings_pkey PRIMARY KEY (id);


--
-- Name: photobook_share photobook_share_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_share
    ADD CONSTRAINT photobook_share_pkey PRIMARY KEY (id);


--
-- Name: photobooks_assets_rel photobooks_assets_rel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks_assets_rel
    ADD CONSTRAINT photobooks_assets_rel_pkey PRIMARY KEY (id);


--
-- Name: photobooks_assets_rel photobooks_assets_rel_unique_pair; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks_assets_rel
    ADD CONSTRAINT photobooks_assets_rel_unique_pair UNIQUE (photobook_id, asset_id);


--
-- Name: photobooks photobooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks
    ADD CONSTRAINT photobooks_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: share_channels share_channels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.share_channels
    ADD CONSTRAINT share_channels_pkey PRIMARY KEY (id);


--
-- Name: shares shares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT shares_pkey PRIMARY KEY (id);


--
-- Name: shares shares_share_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT shares_share_slug_key UNIQUE (share_slug);


--
-- Name: subscription_events subscription_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscription_events
    ADD CONSTRAINT subscription_events_pkey PRIMARY KEY (id);


--
-- Name: photobook_share unique_share_per_target; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_share
    ADD CONSTRAINT unique_share_per_target UNIQUE (photobook_id, email, invited_user_id);


--
-- Name: photobook_bookmarks unique_user_photobook; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_bookmarks
    ADD CONSTRAINT unique_user_photobook UNIQUE (user_id, photobook_id);


--
-- Name: photobook_settings uq_photobook_settings_photobook_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_settings
    ADD CONSTRAINT uq_photobook_settings_photobook_id UNIQUE (photobook_id);


--
-- Name: share_channels uq_share_channels_unique_destination; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.share_channels
    ADD CONSTRAINT uq_share_channels_unique_destination UNIQUE (photobook_share_id, channel_type, destination);


--
-- Name: user_recently_viewed_photobook user_recently_viewed_photobook_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recently_viewed_photobook
    ADD CONSTRAINT user_recently_viewed_photobook_pkey PRIMARY KEY (user_id, photobook_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: giftcard_events_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX giftcard_events_created_at_idx ON public.giftcard_events USING btree (created_at);


--
-- Name: giftcard_events_giftcard_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX giftcard_events_giftcard_id_idx ON public.giftcard_events USING btree (giftcard_id);


--
-- Name: giftcard_events_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX giftcard_events_kind_idx ON public.giftcard_events USING btree (kind);


--
-- Name: idx_assets_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assets_user_id ON public.assets USING btree (user_id);


--
-- Name: idx_giftcards_payment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_giftcards_payment ON public.giftcards USING btree (created_by_payment_id);


--
-- Name: idx_giftcards_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_giftcards_status ON public.giftcards USING btree (status);


--
-- Name: idx_job_events_job_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_job_events_job_id_created_at ON public.job_events USING btree (job_id, created_at);


--
-- Name: idx_job_events_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_job_events_photobook_id ON public.job_events USING btree (photobook_id);


--
-- Name: idx_jobs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_created_at ON public.jobs USING btree (created_at);


--
-- Name: idx_jobs_job_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_job_type ON public.jobs USING btree (job_type);


--
-- Name: idx_jobs_last_attempted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_last_attempted_at ON public.jobs USING btree (last_attempted_at);


--
-- Name: idx_jobs_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_photobook_id ON public.jobs USING btree (photobook_id);


--
-- Name: idx_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_status ON public.jobs USING btree (status);


--
-- Name: idx_jobs_status_job_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_status_job_type ON public.jobs USING btree (status, job_type);


--
-- Name: idx_jobs_status_retry_count; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_status_retry_count ON public.jobs USING btree (status, retry_count);


--
-- Name: idx_notification_delivery_attempts_channel_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_delivery_attempts_channel_created ON public.notification_delivery_attempts USING btree (share_channel_id, created_at);


--
-- Name: idx_notification_outbox_claimed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_claimed_at ON public.notification_outbox USING btree (dispatch_claimed_at);


--
-- Name: idx_notification_outbox_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_created_by ON public.notification_outbox USING btree (created_by_user_id);


--
-- Name: idx_notification_outbox_dispatch_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_dispatch_token ON public.notification_outbox USING btree (dispatch_token);


--
-- Name: idx_notification_outbox_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_photobook_id ON public.notification_outbox USING btree (photobook_id);


--
-- Name: idx_notification_outbox_scheduled_for; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_scheduled_for ON public.notification_outbox USING btree (scheduled_for);


--
-- Name: idx_notification_outbox_share_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_share_channel ON public.notification_outbox USING btree (share_channel_id);


--
-- Name: idx_notification_outbox_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_outbox_status ON public.notification_outbox USING btree (status);


--
-- Name: idx_outbox_ready; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outbox_ready ON public.notification_outbox USING btree (status, scheduled_for, created_at) WHERE (status = ANY (ARRAY['pending'::public.share_channel_status, 'scheduled'::public.share_channel_status]));


--
-- Name: idx_pages_assets_rel_asset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pages_assets_rel_asset_id ON public.pages_assets_rel USING btree (asset_id);


--
-- Name: idx_pages_assets_rel_page_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pages_assets_rel_page_id ON public.pages_assets_rel USING btree (page_id);


--
-- Name: idx_pages_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pages_photobook_id ON public.pages USING btree (photobook_id);


--
-- Name: idx_payment_events_payment_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payment_events_payment_created ON public.payment_events USING btree (payment_id, created_at);


--
-- Name: idx_payments_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_created_by ON public.payments USING btree (created_by_user_id, created_at DESC);


--
-- Name: idx_payments_fulfilled_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_fulfilled_at ON public.payments USING btree (fulfilled_at DESC);


--
-- Name: idx_payments_photobook; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_photobook ON public.payments USING btree (photobook_id, created_at DESC);


--
-- Name: idx_payments_share_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_share_id ON public.shares USING btree (created_by_payment_id);


--
-- Name: idx_payments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_status ON public.payments USING btree (status);


--
-- Name: idx_payments_stripe_payment_intent_id_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_payments_stripe_payment_intent_id_unique ON public.payments USING btree (stripe_payment_intent_id);


--
-- Name: idx_photobook_bookmarks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_bookmarks_user_id ON public.photobook_bookmarks USING btree (user_id);


--
-- Name: idx_photobook_comments_pending_notifications; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_comments_pending_notifications ON public.photobook_comments USING btree (notification_status) WHERE (notification_status = 'pending'::public.notification_status);


--
-- Name: idx_photobook_comments_photobook_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_comments_photobook_id_created_at ON public.photobook_comments USING btree (photobook_id, created_at DESC);


--
-- Name: idx_photobook_comments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_comments_status ON public.photobook_comments USING btree (status) WHERE (status = ANY (ARRAY['hidden_by_author'::public.comment_status, 'deleted_by_system'::public.comment_status]));


--
-- Name: idx_photobook_comments_user_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_comments_user_id_created_at ON public.photobook_comments USING btree (user_id, created_at DESC);


--
-- Name: idx_photobook_settings_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_photobook_settings_photobook_id ON public.photobook_settings USING btree (photobook_id);


--
-- Name: idx_photobook_share_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_share_email ON public.photobook_share USING btree (email);


--
-- Name: idx_photobook_share_invited_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobook_share_invited_user_id ON public.photobook_share USING btree (invited_user_id);


--
-- Name: idx_photobooks_assets_rel_asset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobooks_assets_rel_asset_id ON public.photobooks_assets_rel USING btree (asset_id);


--
-- Name: idx_photobooks_assets_rel_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobooks_assets_rel_photobook_id ON public.photobooks_assets_rel USING btree (photobook_id);


--
-- Name: idx_photobooks_thumbnail_asset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobooks_thumbnail_asset_id ON public.photobooks USING btree (thumbnail_asset_id);


--
-- Name: idx_photobooks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_photobooks_user_id ON public.photobooks USING btree (user_id);


--
-- Name: idx_share_channels_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_share_channels_photobook_id ON public.share_channels USING btree (photobook_id);


--
-- Name: idx_share_channels_share_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_share_channels_share_id ON public.share_channels USING btree (photobook_share_id);


--
-- Name: idx_shares_access_policy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_access_policy ON public.shares USING btree (access_policy);


--
-- Name: idx_shares_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_kind ON public.shares USING btree (kind);


--
-- Name: idx_shares_photobook_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_photobook_id ON public.shares USING btree (photobook_id);


--
-- Name: idx_shares_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_revoked_at ON public.shares USING btree (revoked_at) WHERE (revoked_at IS NOT NULL);


--
-- Name: idx_subscription_events_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscription_events_source ON public.subscription_events USING btree (source);


--
-- Name: idx_subscription_events_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subscription_events_user_created ON public.subscription_events USING btree (user_id, created_at);


--
-- Name: idx_user_recently_viewed_photobook_user_viewed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_recently_viewed_photobook_user_viewed ON public.user_recently_viewed_photobook USING btree (user_id, viewed_at DESC);


--
-- Name: idx_users_profile_pic_asset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_profile_pic_asset_id ON public.users USING btree (profile_pic_asset_id);


--
-- Name: notifications_payload_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notifications_payload_gin_idx ON public.notifications USING gin (payload);


--
-- Name: notifications_recipient_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notifications_recipient_created_idx ON public.notifications USING btree (recipient_id, created_at DESC);


--
-- Name: notifications_recipient_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notifications_recipient_type_idx ON public.notifications USING btree (recipient_id, type);


--
-- Name: notifications_unseen_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notifications_unseen_idx ON public.notifications USING btree (recipient_id) WHERE (seen_at IS NULL);


--
-- Name: uq_background_img_registry_name_nocase; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_background_img_registry_name_nocase ON public.background_img_registry USING btree (lower(name));


--
-- Name: uq_giftcards_giftcard_code_explicit_override; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_giftcards_giftcard_code_explicit_override ON public.giftcards USING btree (giftcard_code_explicit_override) WHERE (giftcard_code_explicit_override IS NOT NULL);


--
-- Name: uq_giftcards_share; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_giftcards_share ON public.giftcards USING btree (share_id);


--
-- Name: uq_outbox_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_outbox_idempotency ON public.notification_outbox USING btree (share_channel_id, notification_type, idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: uq_outbox_live_per_channel_type; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_outbox_live_per_channel_type ON public.notification_outbox USING btree (share_channel_id, notification_type) WHERE (status = ANY (ARRAY['pending'::public.share_channel_status, 'scheduled'::public.share_channel_status, 'sending'::public.share_channel_status]));


--
-- Name: uq_payments_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_payments_idempotency_key ON public.payments USING btree (idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: uq_recipient_share_by_user; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_recipient_share_by_user ON public.shares USING btree (photobook_id, recipient_user_id) WHERE ((kind = 'recipient'::public.share_kind) AND (recipient_user_id IS NOT NULL));


--
-- Name: uq_share_channel_dest_per_photobook_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_share_channel_dest_per_photobook_active ON public.share_channels USING btree (photobook_id, channel_type, destination) WHERE (archived_at IS NULL);


--
-- Name: uq_single_public_share_per_photobook; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_single_public_share_per_photobook ON public.shares USING btree (photobook_id) WHERE (kind = 'public'::public.share_kind);


--
-- Name: uq_subscription_events_rc_event_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_subscription_events_rc_event_id ON public.subscription_events USING btree (rc_event_id) WHERE (rc_event_id IS NOT NULL);


--
-- Name: assets assets_original_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_original_photobook_id_fkey FOREIGN KEY (original_photobook_id) REFERENCES public.photobooks(id);


--
-- Name: assets assets_user_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assets
    ADD CONSTRAINT assets_user_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: entitlements entitlements_user_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entitlements
    ADD CONSTRAINT entitlements_user_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: photobook_bookmarks fk_bookmark_photobook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_bookmarks
    ADD CONSTRAINT fk_bookmark_photobook FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: photobook_bookmarks fk_bookmark_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_bookmarks
    ADD CONSTRAINT fk_bookmark_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: photobook_share fk_invited_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_share
    ADD CONSTRAINT fk_invited_user FOREIGN KEY (invited_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: photobook_settings fk_photobook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_settings
    ADD CONSTRAINT fk_photobook FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: photobook_share fk_photobook; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_share
    ADD CONSTRAINT fk_photobook FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: giftcard_events giftcard_events_giftcard_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcard_events
    ADD CONSTRAINT giftcard_events_giftcard_id_fkey FOREIGN KEY (giftcard_id) REFERENCES public.giftcards(id) ON DELETE CASCADE;


--
-- Name: giftcards giftcards_created_by_payment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcards
    ADD CONSTRAINT giftcards_created_by_payment_id_fkey FOREIGN KEY (created_by_payment_id) REFERENCES public.payments(id) ON DELETE SET NULL;


--
-- Name: giftcards giftcards_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcards
    ADD CONSTRAINT giftcards_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: giftcards giftcards_share_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giftcards
    ADD CONSTRAINT giftcards_share_id_fkey FOREIGN KEY (share_id) REFERENCES public.shares(id) ON DELETE CASCADE;


--
-- Name: job_events job_events_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: job_events job_events_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_events
    ADD CONSTRAINT job_events_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE SET NULL;


--
-- Name: jobs jobs_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id);


--
-- Name: notification_delivery_attempts notification_delivery_attempts_outbox_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_delivery_attempts
    ADD CONSTRAINT notification_delivery_attempts_outbox_id_fkey FOREIGN KEY (notification_outbox_id) REFERENCES public.notification_outbox(id) ON DELETE SET NULL;


--
-- Name: notification_delivery_attempts notification_delivery_attempts_share_channel_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_delivery_attempts
    ADD CONSTRAINT notification_delivery_attempts_share_channel_id_fkey FOREIGN KEY (share_channel_id) REFERENCES public.share_channels(id) ON DELETE CASCADE;


--
-- Name: notification_outbox notification_outbox_created_by_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_created_by_user_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: notification_outbox notification_outbox_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: notification_outbox notification_outbox_share_channel_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_share_channel_id_fkey FOREIGN KEY (share_channel_id) REFERENCES public.share_channels(id) ON DELETE CASCADE;


--
-- Name: notification_outbox notification_outbox_share_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_share_id_fkey FOREIGN KEY (share_id) REFERENCES public.shares(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: notifications notifications_comment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_comment_id_fkey FOREIGN KEY (comment_id) REFERENCES public.photobook_comments(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_recipient_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_recipient_id_fkey FOREIGN KEY (recipient_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_share_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_share_id_fkey FOREIGN KEY (share_id) REFERENCES public.photobook_share(id) ON DELETE CASCADE;


--
-- Name: pages_assets_rel pages_assets_rel_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages_assets_rel
    ADD CONSTRAINT pages_assets_rel_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(id);


--
-- Name: pages_assets_rel pages_assets_rel_page_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages_assets_rel
    ADD CONSTRAINT pages_assets_rel_page_id_fkey FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: pages pages_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pages_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id);


--
-- Name: payment_events payment_events_payment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_events
    ADD CONSTRAINT payment_events_payment_id_fkey FOREIGN KEY (payment_id) REFERENCES public.payments(id) ON DELETE CASCADE;


--
-- Name: shares payment_shares_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT payment_shares_id_fkey FOREIGN KEY (created_by_payment_id) REFERENCES public.payments(id) ON DELETE SET NULL;


--
-- Name: payments payments_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id);


--
-- Name: payments payments_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE RESTRICT;


--
-- Name: photobook_comments photobook_comments_last_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_comments
    ADD CONSTRAINT photobook_comments_last_updated_by_fkey FOREIGN KEY (last_updated_by) REFERENCES public.users(id);


--
-- Name: photobook_comments photobook_comments_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_comments
    ADD CONSTRAINT photobook_comments_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: photobook_comments photobook_comments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobook_comments
    ADD CONSTRAINT photobook_comments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: photobooks_assets_rel photobooks_assets_rel_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks_assets_rel
    ADD CONSTRAINT photobooks_assets_rel_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.assets(id) ON DELETE CASCADE;


--
-- Name: photobooks_assets_rel photobooks_assets_rel_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks_assets_rel
    ADD CONSTRAINT photobooks_assets_rel_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: photobooks photobooks_thumbnail_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks
    ADD CONSTRAINT photobooks_thumbnail_asset_id_fkey FOREIGN KEY (thumbnail_asset_id) REFERENCES public.assets(id) ON DELETE SET NULL;


--
-- Name: photobooks photobooks_user_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photobooks
    ADD CONSTRAINT photobooks_user_fk FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: share_channels share_channels_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.share_channels
    ADD CONSTRAINT share_channels_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: share_channels share_channels_photobook_share_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.share_channels
    ADD CONSTRAINT share_channels_photobook_share_id_fkey FOREIGN KEY (photobook_share_id) REFERENCES public.shares(id) ON DELETE CASCADE;


--
-- Name: shares shares_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT shares_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: shares shares_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT shares_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: shares shares_recipient_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shares
    ADD CONSTRAINT shares_recipient_user_id_fkey FOREIGN KEY (recipient_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: subscription_events subscription_events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscription_events
    ADD CONSTRAINT subscription_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_recently_viewed_photobook user_recently_viewed_photobook_photobook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recently_viewed_photobook
    ADD CONSTRAINT user_recently_viewed_photobook_photobook_id_fkey FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE;


--
-- Name: user_recently_viewed_photobook user_recently_viewed_photobook_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_recently_viewed_photobook
    ADD CONSTRAINT user_recently_viewed_photobook_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: users users_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: users users_profile_pic_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_profile_pic_asset_id_fkey FOREIGN KEY (profile_pic_asset_id) REFERENCES public.assets(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--


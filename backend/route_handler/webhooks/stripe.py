# mypy: disable-error-code="no-untyped-call"
# backend/route_handler/webhooks/stripe.py

import json
import logging
from typing import TYPE_CHECKING, Any, Optional, cast

import stripe
from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from backend.db.dal import (
    DALPaymentEvents,
    DALPayments,
    DAOPaymentEventsCreate,
    FilterOp,
    safe_transaction,
)
from backend.db.data_models import (
    PaymentEventSource,
    PaymentStatus,
)
from backend.env_loader import EnvLoader
from backend.lib.notifs.dispatch_service import claim_and_enqueue_one_outbox
from backend.lib.payments.fulfillment_service import fulfill_payment_success_if_needed
from backend.lib.payments.stripe.service import (
    StatusApplyContext,
    reconcile_and_apply_payment_status_in_txn,  # still used
)
from backend.lib.payments.stripe.utils import parse_payment_intent_obj
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
    unauthenticated_route,
)

if TYPE_CHECKING:
    from uuid import UUID


# --- Strict models for small I/O surfaces (we keep event payload as raw dict[str, Any]) ---


class WebhookAck(BaseModel):
    received: bool = True


# --- Stripe config helpers ---


def _load_active_webhook_secrets() -> set[str]:
    primary = EnvLoader.get("STRIPE_API_WH_SECRET")
    alt = EnvLoader.get_optional("STRIPE_API_WH_SECRET_ALT")
    if alt and primary != alt:
        return {primary, alt}
    return {primary}


class StripeWebhookAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route("/api/webhooks/stripe", "stripe_webhook", methods=["POST"])

    @unauthenticated_route
    @enforce_response_model
    async def stripe_webhook(self, request: Request) -> WebhookAck:
        # 1) raw body & signature
        raw_body: bytes = await request.body()
        if not raw_body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty body"
            )

        sig_header: Optional[str] = request.headers.get("stripe-signature")
        if not sig_header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe-Signature header",
            )

        # 2) verify signature (support rotation)
        event: stripe.Event | None = None
        last_err: Optional[Exception] = None
        for secret in _load_active_webhook_secrets():
            try:
                event = stripe.Webhook.construct_event(raw_body, sig_header, secret)  # pyright: ignore
                break
            except Exception as e:
                last_err = e
        if event is None:
            logging.warning(
                "Stripe webhook signature verification failed: %s", last_err
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
            )

        # 3) event type
        event_type: str = getattr(event, "type", "")
        if not event_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event.type"
            )

        # 4) raw payload snapshot for auditing
        try:
            payload_dict: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except Exception:
            payload_dict = {"_unparsed": True}

        # 5) de-dupe by stripe_event_id (append-only audit)
        async with self.app.db_session_factory.new_session() as session:
            async with safe_transaction(session, "stripe_webhook.event_dedupe"):
                dup = await DALPaymentEvents.list_all(
                    session,
                    filters={
                        "stripe_event_id": (FilterOp.EQ, getattr(event, "id", None))
                    },
                    limit=1,
                )
                if dup:
                    return WebhookAck()

                await DALPaymentEvents.create(
                    session,
                    DAOPaymentEventsCreate(
                        payment_id=None,
                        event_type="webhook.receieve",
                        stripe_event_id=getattr(event, "id", None),
                        stripe_event_type=event_type,
                        source=PaymentEventSource.STRIPE_WEBHOOK,
                        payload=payload_dict,
                        signature_verified=True,
                        applied_status=None,
                    ),
                )

            # 6) Ignore non-PI events early
            if not event_type.startswith("payment_intent."):
                return WebhookAck()

            # 7) Parse PI + find payment row
            pi = cast("stripe.PaymentIntent", event.data.object)
            pi_snapshot = parse_payment_intent_obj(pi)

            payment_row = None
            async with safe_transaction(
                session, "stripe_webhook.fetch_payment", raise_on_fail=False
            ):
                if pi_snapshot.id:
                    hits = await DALPayments.list_all(
                        session,
                        filters={
                            "stripe_payment_intent_id": (FilterOp.EQ, pi_snapshot.id)
                        },
                        limit=1,
                    )
                    payment_row = hits[0] if hits else None

                if payment_row is None and pi_snapshot.hinted_payment_id:
                    hits = await DALPayments.list_all(
                        session,
                        filters={"id": (FilterOp.EQ, pi_snapshot.hinted_payment_id)},
                        limit=1,
                    )
                    payment_row = hits[0] if hits else None

            if payment_row is None:
                logging.warning(
                    "[stripe_webhook] %s for unknown PaymentIntent (pi=%s, hinted=%s)",
                    event_type,
                    pi_snapshot.id,
                    pi_snapshot.hinted_payment_id,
                )
                return WebhookAck()

            # 8) Apply/advance payment status (idempotent)
            async with safe_transaction(session, "stripe_webhook.status_apply"):
                (
                    payment_row,
                    applied_status,
                    _,
                ) = await reconcile_and_apply_payment_status_in_txn(
                    session,
                    payment_row=payment_row,
                    pi_snapshot=pi_snapshot,
                    ctx=StatusApplyContext(
                        source=PaymentEventSource.SYSTEM,
                        event_type=event_type,
                        stripe_event_id=getattr(event, "id", None),
                        signature_verified=True,
                        extra_payload={"path": "webhook_status_apply"},
                    ),
                )

            # 9) Fulfill on SUCCEEDED (idempotent; safe to re-run)
            if applied_status == PaymentStatus.SUCCEEDED:
                (
                    share_resp,
                    _giftcard_ids,
                    did_fulfill,
                ) = await fulfill_payment_success_if_needed(
                    session,
                    payment_id=payment_row.id,
                    audit_source=PaymentEventSource.SYSTEM,  # or PaymentEventSource.STRIPE_WEBHOOK
                    audit_context={"path": "webhook"},
                )

                # Post-commit enqueue (once)
                if (
                    did_fulfill
                    and share_resp
                    and self.app.get_effect_mode(request) == "live"
                ):
                    job_ids: list[UUID] = []
                    for r in share_resp.recipients:
                        for ob in r.outbox_results:
                            job_id = await claim_and_enqueue_one_outbox(
                                session=session,
                                job_manager=self.app.remote_job_manager_io_bound,
                                outbox_id=ob.outbox_id,
                                worker_id="stripe-webhook",
                                lease_seconds=600,
                                user_id=payment_row.created_by_user_id,
                            )
                            if job_id is not None:
                                job_ids.append(job_id)

        return WebhookAck()

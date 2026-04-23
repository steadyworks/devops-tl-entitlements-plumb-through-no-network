# backend/route_handler/payment.py

import logging
from typing import Optional
from uuid import UUID

from fastapi import Query, Request
from pydantic import BaseModel

from backend.db.dal import (
    safe_transaction,
)
from backend.db.data_models import (
    PaymentEventSource,
    PaymentStatus,
)
from backend.db.externals import PaymentsOverviewResponse, PhotobooksOverviewResponse
from backend.lib.notifs.dispatch_service import claim_and_enqueue_one_outbox
from backend.lib.payments.fulfillment_service import fulfill_payment_success_if_needed
from backend.lib.payments.stripe.service import (
    StatusApplyContext,
    reconcile_and_apply_payment_status_in_txn,  # still used
)
from backend.lib.payments.stripe.utils import (
    StripePISnapshot,
    is_terminal_stripe_payment_status,
    parse_payment_intent_obj,
    recommended_poll_ms,
)
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
)


class PaymentStatusResponse(BaseModel):
    status: PaymentsOverviewResponse
    terminal: bool
    recommended_poll_after_ms: int
    photobook_overview_if_terminal: Optional[PhotobooksOverviewResponse]


class PaymentAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/payment/{payment_id}/status", "payment_status", methods=["GET"]
        )

    @enforce_response_model
    async def payment_status(
        self,
        request: Request,
        payment_id: UUID,
        eager: bool = Query(
            default=False,
            description="If true, proactively refresh from Stripe when non-terminal.",
        ),
    ) -> PaymentStatusResponse:
        """
        Returns a public-safe overview of the payment and polling hints.
        If eager=true and payment is non-terminal, best-effort retrieve the PI from Stripe
        and monotonically advance (append-only audit).

        Contract with client:
        When you get payment_bootstrap.payment_id, start polling:
        GET /api/payments/{payment_id}/status?eager=true every 1s for up to ~10s.
        Stop polling when terminal == true.
        If status == SUCCEEDED → proceed to success UI.
        If status == CANCELED or FAILED → show an error; optionally display failure_message.
        """
        async with self.app.db_session_factory.new_session() as session:
            # Authorization: only owner can view
            rcx = await self.get_request_context(request)
            current_user_id = rcx.user_id
            stripe_client = self.get_stripe_client_for_request(request)

            async with safe_transaction(
                session,
                "payment status initial fetch",
                raise_on_fail=True,
            ):
                dao = await self.get_payment_assert_owned_by(
                    session, payment_id, rcx.user_id
                )

            # Eager refresh path (optional)
            if (
                eager
                and not is_terminal_stripe_payment_status(dao.status)
                and dao.stripe_payment_intent_id
            ):
                # Try refreshing by directly calling Stripe
                try:
                    pi = await stripe_client.retrieve_payment_intent_async(
                        payment_intent_id=dao.stripe_payment_intent_id
                    )
                except Exception as _e:
                    pi = None

                # Parse refreshed result
                if pi is not None:
                    snap: StripePISnapshot = parse_payment_intent_obj(pi)

                    try:
                        async with safe_transaction(
                            session,
                            "payment status eager apply",
                            raise_on_fail=True,
                        ):
                            (
                                dao,
                                _applied_status,
                                _did_advance,
                            ) = await reconcile_and_apply_payment_status_in_txn(
                                session,
                                payment_row=dao,
                                pi_snapshot=snap,
                                ctx=StatusApplyContext(
                                    source=PaymentEventSource.SYSTEM,
                                    event_type="payment_intent.eager_poll",
                                    stripe_event_id=None,
                                    signature_verified=None,
                                    extra_payload={"path": "eager_status_poll"},
                                ),
                            )

                        if eager and dao.status == PaymentStatus.SUCCEEDED:
                            (
                                share_resp,
                                _giftcard_ids,
                                did_fulfill,
                            ) = await fulfill_payment_success_if_needed(
                                session,
                                payment_id=dao.id,
                                audit_source=PaymentEventSource.SYSTEM,
                                audit_context={"path": "eager_poll"},
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
                                            worker_id="payment-status",
                                            lease_seconds=600,
                                            user_id=(
                                                await self.get_request_context(request)
                                            ).user_id,
                                        )
                                        if job_id is not None:
                                            job_ids.append(job_id)

                    except Exception:
                        logging.exception(
                            "[payment_status] eager apply failed for %s", dao.id
                        )
                        # Fall through: client still gets current DB state

            # Build full overview, then convert to public
            pub_ov = PaymentsOverviewResponse.from_dao(dao)
            is_terminal = is_terminal_stripe_payment_status(pub_ov.status)

            photobook_ov = None
            if is_terminal:
                photobook_dao = await self.get_photobook_assert_owned_by(
                    session, pub_ov.photobook_id, rcx.user_id
                )
                photobook_ov = (
                    await PhotobooksOverviewResponse.rendered_from_daos(
                        [photobook_dao],
                        session,
                        self.app.asset_manager,
                        requesting_user_id=current_user_id,
                    )
                )[0]

            return PaymentStatusResponse(
                status=pub_ov,
                terminal=is_terminal,
                recommended_poll_after_ms=recommended_poll_ms(pub_ov.status),
                photobook_overview_if_terminal=photobook_ov,
            )

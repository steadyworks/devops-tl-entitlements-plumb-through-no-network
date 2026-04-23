# backend/lib/payments/fulfillment_service.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALGiftcards,
    DALPaymentEvents,
    DALPayments,
    DAOPaymentEventsCreate,
    DAOPaymentsUpdate,
    FilterOp,
    locked_row_by_id,
    safe_transaction,
)
from backend.db.data_models import (
    DAOPayments,
    PaymentEventSource,
    PaymentStatus,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.lib.giftcard.service import grant_giftcard_for_share_fulfilling_payment
from backend.lib.sharing.schemas import ShareCreateResponse
from backend.lib.sharing.service import initialize_shares_and_channels_in_txn
from backend.lib.utils.common import utcnow

from .logging_helper_mixins import PaymentEventLoggingHelperMixins


async def fulfill_payment_success_if_needed(
    session: AsyncSession,
    *,
    payment_id: UUID,
    audit_source: PaymentEventSource,
    audit_context: Optional[dict[str, str]] = None,
) -> Tuple[Optional[ShareCreateResponse], List[UUID], bool]:
    """
    Same contract, but:
    - ATTEMPT/SUCCESS/FAILURE logged via per-event mini txs
    - Core side effects remain atomic
    - On failure, fulfillment_last_error is persisted in its own mini tx
    """
    if session.in_transaction():
        raise RuntimeError(
            "[fulfill_payment_success_if_needed] Must be called with no active transaction on the session."
        )

    if audit_context is None:
        audit_context = {}

    share_resp: Optional[ShareCreateResponse] = None
    giftcard_ids: List[UUID] = []
    did_fulfill = False

    # Span: durable breadcrumbs irrespective of core tx outcome
    async with PaymentEventLoggingHelperMixins.payment_event_span(
        session,
        payment_id=payment_id,
        source=audit_source,
        attempt_event="fulfill.attempt",
        success_event="fulfill.success",
        failure_event="fulfill.failed",
        attempt_message="Payment fulfillment",
        attempt_payload={"context": audit_context},
    ) as success_payload:
        # ---- Core atomic work in one transaction ----
        try:
            async with safe_transaction(session, "payments.fulfill_success"):
                async with locked_row_by_id(
                    session, DAOPayments, payment_id
                ) as payment_row:
                    if payment_row.status != PaymentStatus.SUCCEEDED:
                        return None, [], False
                    if payment_row.fulfilled_at is not None:
                        return None, [], False
                    if not payment_row.share_create_request:
                        logging.error(
                            "[fulfill_success] No share_create_request snapshot on payment %s",
                            payment_row.id,
                        )
                        return None, [], False

                    already = await DALGiftcards.exists(
                        session,
                        filters={
                            "created_by_payment_id": (FilterOp.EQ, payment_row.id)
                        },
                    )
                    if already:
                        return None, [], False

                    req: ShareCreateRequest = ShareCreateRequest.deserialize(
                        payment_row.share_create_request
                    )

                    # 1) Shares/channels (+ outbox), tagged with payment
                    share_resp = await initialize_shares_and_channels_in_txn(
                        session=session,
                        user_id=payment_row.created_by_user_id,
                        photobook_id=payment_row.photobook_id,
                        req=req,
                        created_by_payment_id=payment_row.id,
                    )

                    # 2) UPSERT local giftcards per share (idempotent)
                    if req.giftcard_request is not None:
                        amt = req.giftcard_request.amount_per_share
                        ccy = req.giftcard_request.currency.lower().strip()
                        brand = req.giftcard_request.brand_code
                        for r in share_resp.recipients:
                            gc_id = await grant_giftcard_for_share_fulfilling_payment(
                                session=session,
                                share_id=r.share_id,
                                payment_id=payment_row.id,
                                user_id=payment_row.created_by_user_id,
                                amount=amt,
                                currency=ccy,
                                brand_code=brand,
                            )
                            if gc_id:
                                giftcard_ids.append(gc_id)

                    # 3) Append audit event INSIDE the atomic tx (optional)
                    await DALPaymentEvents.create(
                        session,
                        DAOPaymentEventsCreate(
                            payment_id=payment_row.id,
                            stripe_event_id=None,
                            event_type="fulfill.audit",
                            stripe_event_type=None,
                            source=audit_source,
                            payload={
                                "giftcard_ids": [str(x) for x in giftcard_ids],
                                **audit_context,
                            },
                            signature_verified=None,
                            applied_status=None,
                        ),
                    )

                    # 4) Mark fulfilled
                    await DALPayments.update_by_id(
                        session,
                        payment_row.id,
                        DAOPaymentsUpdate(
                            fulfilled_at=utcnow(),
                            fulfillment_last_error=None,
                        ),
                    )

                    did_fulfill = True

            # Populate success span payload (written in its OWN tiny tx)
            success_payload.update(
                {
                    "shares": [
                        {
                            "share_id": str(r.share_id),
                            "channels": [
                                {
                                    "share_channel_id": str(ch.share_channel_id),
                                    "channel_type": ch.channel_type.value,
                                    "destination": ch.destination,
                                }
                                for ch in r.share_channel_results
                            ],
                            "outbox": [str(ob.outbox_id) for ob in r.outbox_results],
                        }
                        for r in share_resp.recipients
                    ],
                    "giftcard_ids": [str(x) for x in giftcard_ids],
                }
            )

        except Exception as e:
            # Ensure error string is saved DURABLY in its own mini tx
            try:
                if session.in_transaction():
                    # Defensive: in case upstream changed safe_transaction behavior
                    # (Normally exiting ctx rolled back already.)
                    pass
                async with safe_transaction(
                    session, "payments.fulfill_error_persist", raise_on_fail=False
                ):
                    await DALPayments.update_by_id(
                        session,
                        payment_id,
                        DAOPaymentsUpdate(  # Do not attempt to override fulfilled_at
                            fulfillment_last_error=str(e),
                        ),
                    )
            except Exception:
                logging.exception(
                    "[fulfill_success] failed to persist fulfillment_last_error"
                )
            did_fulfill = False
            # Re-raise so the span logs FAILURE
            raise

    return share_resp, giftcard_ids, did_fulfill

# backend/lib/payments/stripe/service.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (  # ORM types
    DALPaymentEvents,
    DALPayments,
    DAOPaymentEventsCreate,
    DAOPayments,
    DAOPaymentsUpdate,
)
from backend.db.data_models import (
    PaymentEventSource,
    PaymentStatus,
)
from backend.lib.payments.stripe.utils import (
    StripePISnapshot,
    is_terminal_stripe_payment_status,
    map_pi_status,
    should_advance_payment_status,
)
from backend.lib.utils.common import none_throws


@dataclass(frozen=True)
class StatusApplyContext:
    """
    Describes the *audit event* we will write when attempting to reconcile/apply
    a new status snapshot.
    - `source`: where this DB-side effect conceptually originates (SYSTEM for eager poll,
      SYSTEM (or WEBHOOK if you prefer) for the state-change audit row inside webhook).
    - `event_type`: "payment_intent.*" for webhook, or "payment_intent.eager_poll" for eager.
    - `stripe_event_id`: Stripe event id if this comes from a webhook; None for eager.
    - `signature_verified`: True for verified webhook, None for eager or unknown.
    - `extra_payload`: optional opaque fields you want to keep in the audit payload.
    """

    source: PaymentEventSource
    event_type: str
    stripe_event_id: Optional[str] = None
    signature_verified: Optional[bool] = None
    extra_payload: dict[str, Any] = field(default_factory=dict[str, Any])


# --- Core reconciliation & persistence helper ----------------------------------


async def reconcile_and_apply_payment_status_in_txn(
    session: AsyncSession,
    *,
    payment_row: DAOPayments,
    pi_snapshot: StripePISnapshot,
    ctx: StatusApplyContext,
) -> Tuple[DAOPayments, PaymentStatus, bool]:
    """
    Given:
      - the current payment_row (DAO),
      - a StripePISnapshot (parsed from a PaymentIntent),
      - a StatusApplyContext (how to write the audit event),

    Decide whether to advance status, persist update if needed,
    write a single audit event row, and return:
        (fresh_payment_row, applied_status, did_advance)
    """
    if not session.in_transaction():
        raise RuntimeError(
            "[reconcile_and_apply_payment_status_in_txn] Must be called within an active transaction on the session."
        )

    old_status: PaymentStatus = payment_row.status
    new_status: PaymentStatus = map_pi_status(pi_snapshot.status_str)

    did_advance: bool = should_advance_payment_status(
        old_status,
        new_status,
        event_type=ctx.event_type,
        failure_code=pi_snapshot.failure_code,
        failure_message=pi_snapshot.failure_message,
    )

    applied_status: PaymentStatus = new_status if did_advance else old_status

    if did_advance:
        update = DAOPaymentsUpdate(
            status=new_status,
            stripe_latest_charge_id=pi_snapshot.latest_charge_id
            or payment_row.stripe_latest_charge_id,
            failure_code=pi_snapshot.failure_code
            if not is_terminal_stripe_payment_status(new_status)
            else None,
            failure_message=pi_snapshot.failure_message
            if not is_terminal_stripe_payment_status(new_status)
            else None,
            updated_at=datetime.now(timezone.utc),
        )
        await DALPayments.update_by_id(session, payment_row.id, update)
        # reload so caller returns accurate data
        payment_row = none_throws(await DALPayments.get_by_id(session, payment_row.id))

    # Always emit an audit event for the attempted reconciliation (uniform shape).
    await DALPaymentEvents.create(
        session,
        DAOPaymentEventsCreate(
            payment_id=payment_row.id,
            stripe_event_id=ctx.stripe_event_id,
            event_type="reconcile.complete",
            stripe_event_type=ctx.event_type,
            source=ctx.source,
            payload={
                "old": old_status.value,
                "new": new_status.value,
                "applied_status": applied_status.value,
                "stripe_payment_intent_id": pi_snapshot.id,
                "latest_charge_id": pi_snapshot.latest_charge_id,
                "failure_code": pi_snapshot.failure_code,
                "failure_message": pi_snapshot.failure_message,
                **(ctx.extra_payload or {}),
            },
            signature_verified=ctx.signature_verified,
            applied_status=applied_status,
        ),
    )

    # None-guard: DALPayments.get_by_id returns Optional
    assert payment_row is not None, "Payment row missing after update"

    return payment_row, applied_status, did_advance

# backend/lib/payments/stripe/utils.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Optional, cast

import stripe

from backend.db.data_models import PaymentStatus

# --- Stripe → internal status mapping (single source of truth) -----------------

STRIPE_PAYMENT_STATUS_MAP: Final[dict[str, PaymentStatus]] = {
    "requires_payment_method": PaymentStatus.REQUIRES_PAYMENT_METHOD,
    "requires_confirmation": PaymentStatus.REQUIRES_CONFIRMATION,
    "requires_action": PaymentStatus.REQUIRES_ACTION,
    "processing": PaymentStatus.PROCESSING,
    "requires_capture": PaymentStatus.REQUIRES_CAPTURE,
    "canceled": PaymentStatus.CANCELED,
    "succeeded": PaymentStatus.SUCCEEDED,
}


# --- Ordered lattice for monotonic progression --------------------------------

STATUS_ORDER: Final[dict[PaymentStatus, int]] = {
    PaymentStatus.REQUIRES_PAYMENT_METHOD: 0,
    PaymentStatus.REQUIRES_CONFIRMATION: 1,
    PaymentStatus.REQUIRES_ACTION: 2,
    PaymentStatus.PROCESSING: 3,
    PaymentStatus.REQUIRES_CAPTURE: 4,
    PaymentStatus.SUCCEEDED: 5,
    PaymentStatus.CANCELED: 5,  # terminal
    PaymentStatus.FAILED: 0,  # treat like lowest; can always advance past it
}


# --- Small helper dataclass for PI snapshots (typed, easy to pass around) ------


@dataclass(frozen=True)
class StripePISnapshot:
    id: Optional[str]
    status_str: Optional[str]
    latest_charge_id: Optional[str]
    failure_code: Optional[str]
    failure_message: Optional[str]
    metadata: dict[str, Any]

    @property
    def hinted_payment_id(self) -> Optional[str]:
        v = self.metadata.get("payment_id")
        return v if isinstance(v, str) else None


# --- Pure helpers ---------------------------------------------------------------


def map_pi_status(status_str: Optional[str]) -> PaymentStatus:
    """Map Stripe PI status string → internal PaymentStatus."""
    if not status_str:
        return PaymentStatus.FAILED
    return STRIPE_PAYMENT_STATUS_MAP.get(status_str, PaymentStatus.FAILED)


def should_advance_payment_status(
    old_status: PaymentStatus,
    new_status: PaymentStatus,
    *,
    event_type: str | None = None,
    failure_code: Optional[str] = None,
    failure_message: Optional[str] = None,
) -> bool:
    """
    Monotone progression by default, with a narrow exception:
    allow a downgrade to REQUIRES_PAYMENT_METHOD when it's a failure-like transition
    (e.g., payment_intent.payment_failed sets last_payment_error).
    """
    if STATUS_ORDER.get(new_status, 0) >= STATUS_ORDER.get(old_status, 0):
        return True

    if new_status == PaymentStatus.REQUIRES_PAYMENT_METHOD and (
        event_type == "payment_intent.payment_failed"
        or failure_code is not None
        or failure_message is not None
    ):
        return True

    return False


def is_terminal_stripe_payment_status(status: PaymentStatus) -> bool:
    return status in (PaymentStatus.SUCCEEDED, PaymentStatus.CANCELED)


def recommended_poll_ms(status: PaymentStatus) -> int:
    """Simple backoff suggestion for the client."""
    if is_terminal_stripe_payment_status(status):
        return 0
    if status in (PaymentStatus.PROCESSING, PaymentStatus.REQUIRES_ACTION):
        return 1000
    return 2000


def parse_payment_intent_obj(pi: stripe.PaymentIntent) -> StripePISnapshot:
    """
    Parse fields we care about from a typed stripe.PaymentIntent.
    (Use this in both webhook + eager polling code paths.)
    """
    lpe = getattr(pi, "last_payment_error", None)
    return StripePISnapshot(
        id=getattr(pi, "id", None),
        status_str=getattr(pi, "status", None),
        latest_charge_id=getattr(pi, "latest_charge", None),
        failure_code=getattr(lpe, "code", None) if lpe else None,
        failure_message=getattr(lpe, "message", None) if lpe else None,
        metadata=cast("dict[str, Any]", getattr(pi, "metadata", {}) or {}),
    )

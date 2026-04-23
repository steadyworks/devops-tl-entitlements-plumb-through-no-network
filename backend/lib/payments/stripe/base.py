# backend/lib/payments/stripe/base.py

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from stripe import PaymentIntent, StripeClient

from backend.db.data_models import (
    PaymentStatus,
)

from .utils import STRIPE_PAYMENT_STATUS_MAP


@dataclass(frozen=True)
class StripeCreatePaymentIntentResult:
    stripe_payment_intent_id: str
    client_secret: str
    latest_charge_id: Optional[str]
    status: PaymentStatus


class AbstractBaseStripeClient(ABC):
    _client: StripeClient

    @abstractmethod
    def __init__(self) -> None: ...

    async def create_stripe_payment_intent_async(
        self,
        *,
        amount: int,
        currency: str,
        description: Optional[str],
        idempotency_key: str,
        metadata: dict[str, str],
    ) -> StripeCreatePaymentIntentResult:
        try:
            pi = await self._client.payment_intents.create_async(
                {
                    "amount": amount,
                    "currency": currency,
                    "automatic_payment_methods": {"enabled": True},
                    "description": description or "",
                    "metadata": metadata or {},
                },
                {"idempotency_key": idempotency_key},
            )
        except Exception:
            logging.exception("[payments] Stripe PaymentIntent.create failed")
            raise

        status = STRIPE_PAYMENT_STATUS_MAP.get(
            getattr(pi, "status", "failed"), PaymentStatus.FAILED
        )
        stripe_payment_intent_id = getattr(pi, "id", "")
        client_secret = getattr(pi, "client_secret", "")
        latest_charge_id = getattr(pi, "latest_charge", None)

        if not stripe_payment_intent_id or not client_secret:
            raise RuntimeError("[payments] Stripe PI missing id/client_secret")

        return StripeCreatePaymentIntentResult(
            stripe_payment_intent_id=stripe_payment_intent_id,
            client_secret=client_secret,
            latest_charge_id=latest_charge_id,
            status=status,
        )

    async def try_cancel_stripe_payment_intent_async(
        self, *, stripe_payment_intent_id: str
    ) -> None:
        """
        Best-effort cancel to compensate if DB work fails after PI creation.
        Safe to call when PI is still in a cancellable state.
        """
        try:
            await self._client.payment_intents.cancel_async(stripe_payment_intent_id)
        except Exception:
            # Best-effort only; log and continue.
            logging.exception(
                "[payments] Failed to cancel Stripe PaymentIntent %s",
                stripe_payment_intent_id,
            )

    async def retrieve_payment_intent_async(
        self,
        *,
        payment_intent_id: str,
    ) -> PaymentIntent:
        return await self._client.payment_intents.retrieve_async(payment_intent_id)

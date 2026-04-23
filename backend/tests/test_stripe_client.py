# tests/test_payments_bootstrap.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, TypedDict

import pytest

from backend.db.data_models import (
    PaymentStatus,
)
from backend.lib.payments.stripe.base import (
    StripeCreatePaymentIntentResult,
)
from backend.lib.payments.stripe.sandbox import StripeClientSandbox

# -------------------------
# Helpers (typed)
# -------------------------


class _CreateOpts(TypedDict, total=False):
    idempotency_key: str


Payload = Dict[str, Any]
Opts = _CreateOpts


@dataclass(frozen=True)
class _FakeStripePI:
    id: str
    client_secret: str
    latest_charge: Optional[str]
    status: str


# -------------------------
# B1. Async wrapper uses a thread and maps fields correctly
# -------------------------


@pytest.mark.asyncio
async def test_B1_create_stripe_payment_intent_async_monkeypatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stripe import StripeClient

    captured: Dict[str, Any] = {}

    async def _fake_create(payload: Payload, opts: Opts) -> _FakeStripePI:
        captured["payload"] = payload
        captured["opts"] = opts
        return _FakeStripePI(
            id="pi_123",
            client_secret="cs_test_123",
            latest_charge="ch_123",
            status="requires_payment_method",
        )

    # Class-level patch: replace the whole payment_intents service with our fake
    class _FakePIService:
        async def create_async(self, payload: Payload, opts: Opts) -> _FakeStripePI:
            return await _fake_create(payload, opts)

    monkeypatch.setattr(StripeClient, "payment_intents", _FakePIService(), raising=True)

    res: StripeCreatePaymentIntentResult = (
        await StripeClientSandbox().create_stripe_payment_intent_async(
            amount=2000,
            currency="usd",
            description="Giftcard for Alice",
            idempotency_key="idem-xyz",
            metadata={"hello": "world"},
        )
    )

    assert isinstance(res, StripeCreatePaymentIntentResult)
    assert res.stripe_payment_intent_id == "pi_123"
    assert res.client_secret == "cs_test_123"
    assert res.latest_charge_id == "ch_123"
    assert res.status == PaymentStatus.REQUIRES_PAYMENT_METHOD

    payload = captured["payload"]
    opts = captured["opts"]
    assert payload["amount"] == 2000
    assert payload["currency"] == "usd"
    assert payload["automatic_payment_methods"] == {"enabled": True}
    assert payload["description"] == "Giftcard for Alice"
    assert payload["metadata"] == {"hello": "world"}
    assert opts["idempotency_key"] == "idem-xyz"


# -------------------------
# B4. Compensation: cancel is callable (unit-level)
# -------------------------


@pytest.mark.asyncio
async def test_B4_try_cancel_stripe_payment_intent_async_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stripe import StripeClient

    called: Dict[str, str] = {}

    async def _fake_cancel(pi_id: str) -> None:
        called["id"] = pi_id

    class _FakePIService:
        async def cancel_async(self, pi_id: str) -> None:
            await _fake_cancel(pi_id)

    monkeypatch.setattr(StripeClient, "payment_intents", _FakePIService(), raising=True)

    await StripeClientSandbox().try_cancel_stripe_payment_intent_async(
        stripe_payment_intent_id="pi_to_cancel_123"
    )
    assert called.get("id") == "pi_to_cancel_123"

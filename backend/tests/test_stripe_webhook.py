# mypy: disable-error-code="no-untyped-call"
# backend/tests/test_webhook_stripe.py

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Optional
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from backend.db.data_models import (
    DAOPaymentEvents,
    DAOPayments,
    PaymentEventSource,
    PaymentPurpose,
    PaymentStatus,
)
from backend.route_handler.webhooks.stripe import StripeWebhookAPIHandler

# -------------------------
# Small testing utilities
# -------------------------


def _make_request(body: dict[str, Any], *, signature: str = "t=1,v1=test") -> Request:
    """
    Build a Starlette Request with a raw JSON body and Stripe-Signature header.
    """
    body_bytes: bytes = json.dumps(body).encode("utf-8")

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/webhooks/stripe",
        "headers": [
            (b"content-type", b"application/json"),
            (b"stripe-signature", signature.encode("utf-8")),
        ],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
    }

    return Request(scope, _receive)


# ...


class _SessionFactory:
    """
    Minimal app.db_session_factory shim that returns an async context manager
    compatible with `async with ... as session:`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def new_session(self) -> AsyncGenerator[AsyncSession, None]:
        yield self._session


class _AppStub:
    def __init__(self, session: AsyncSession) -> None:
        self.db_session_factory = _SessionFactory(session)


# -------------------------
# Stripe event fakes
# -------------------------


class _FakeStripeEvent:
    """
    Minimal shape used by handler: event.id, event.type, event.data.object
    """

    def __init__(self, *, event_id: str, event_type: str, pi: SimpleNamespace) -> None:
        self.id = event_id
        self.type = event_type
        self.data = SimpleNamespace(object=pi)


def _pi_ns(
    *,
    pi_id: str,
    status: str,
    latest_charge: Optional[str] = None,
    last_error_code: Optional[str] = None,
    last_error_message: Optional[str] = None,
    metadata: Optional[dict[str, str]] = None,
) -> SimpleNamespace:
    lpe = None
    if last_error_code or last_error_message:
        lpe = SimpleNamespace(code=last_error_code, message=last_error_message)
    return SimpleNamespace(
        id=pi_id,
        status=status,
        latest_charge=latest_charge,
        last_payment_error=lpe,
        metadata=metadata or {},
    )


# -------------------------
# Fixtures
# -------------------------


@pytest.fixture
def handler(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> StripeWebhookAPIHandler:
    """
    Construct the webhook handler, bind an app stub, and stub EnvLoader secrets.
    """
    # Bind handler
    h = StripeWebhookAPIHandler(app=_AppStub(db_session))  # type: ignore[arg-type]

    # Ensure register_routes doesn't blow up if called in other contexts
    # (not strictly needed for unit calls to the method)
    try:
        h.register_routes()
    except Exception:
        pass

    # Stub EnvLoader used by _load_active_webhook_secrets()
    from backend.route_handler.webhooks import stripe as stripe_mod

    def env_returning_valid(k: str) -> str:
        return "whsec_test"

    def env_returning_none(k: str) -> str | None:
        return None

    monkeypatch.setattr(
        stripe_mod.EnvLoader,  # type: ignore[attr-defined]
        "get",
        staticmethod(env_returning_valid),
        raising=True,
    )

    if hasattr(stripe_mod.EnvLoader, "get_optional"):  # type: ignore[attr-defined]
        monkeypatch.setattr(
            stripe_mod.EnvLoader,  # type: ignore[attr-defined]
            "get_optional",
            staticmethod(env_returning_none),
            raising=True,
        )

    return h


# -------------------------
# Tests
# -------------------------


@pytest.mark.asyncio
async def test_WH1_signature_verification_failure_returns_400(
    handler: StripeWebhookAPIHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stripe

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise stripe.SignatureVerificationError(
            message="bad", http_body=b"", sig_header="h"
        )

    monkeypatch.setattr(
        stripe.Webhook, "construct_event", staticmethod(_raise), raising=True
    )

    req: Request = _make_request({"type": "payment_intent.succeeded"})
    with pytest.raises(Exception) as ei:
        await handler.stripe_webhook(req)
    # FastAPI raises HTTPException under the hood
    assert "Invalid signature" in str(ei.value)


@pytest.mark.asyncio
async def test_WH2_unknown_payment_records_snapshot_only(
    handler: StripeWebhookAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stripe

    event_id: str = "evt_test_unknown_1"
    pi = _pi_ns(pi_id="pi_no_row", status="succeeded", latest_charge="ch_1")
    fake = _FakeStripeEvent(
        event_id=event_id, event_type="payment_intent.succeeded", pi=pi
    )

    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda *a, **k: fake),
        raising=True,
    )

    req: Request = _make_request(
        {
            "id": event_id,
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_no_row",
                    "status": "succeeded",
                    "latest_charge": "ch_1",
                    "metadata": {},
                }
            },
        }
    )

    ack = await handler.stripe_webhook(req)
    assert ack.received is True

    # Snapshot persisted
    got = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    assert len(got) == 1
    assert got[0].source == PaymentEventSource.STRIPE_WEBHOOK
    assert got[0].stripe_event_id == event_id
    assert got[0].payment_id is None  # unknown payment → not linked


@pytest.mark.asyncio
async def test_WH3_known_payment_updates_status_and_appends_two_events(
    handler: StripeWebhookAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed a payment row that references a Stripe PI
    seed = DAOPayments(
        id=uuid4(),
        created_by_user_id=uuid4(),
        photobook_id=uuid4(),
        purpose=PaymentPurpose.GIFTCARD,
        amount_total=5000,
        currency="usd",
        stripe_payment_intent_id="pi_123",
        stripe_customer_id=None,
        stripe_payment_method_id=None,
        stripe_latest_charge_id=None,
        status=PaymentStatus.REQUIRES_CONFIRMATION,
        description=None,
        receipt_email=None,
        idempotency_key="idem-x",
        failure_code=None,
        failure_message=None,
        refunded_amount=0,
        metadata_json={},
    )
    db_session.add(seed)
    await db_session.commit()

    # Webhook: succeeded
    event_id: str = "evt_ok_1"
    pi = _pi_ns(pi_id="pi_123", status="succeeded", latest_charge="ch_ok_1")
    fake = _FakeStripeEvent(
        event_id=event_id, event_type="payment_intent.succeeded", pi=pi
    )

    import stripe as _stripe

    monkeypatch.setattr(
        _stripe.Webhook,
        "construct_event",
        staticmethod(lambda *a, **k: fake),
        raising=True,
    )

    req: Request = _make_request(
        {
            "id": event_id,
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_123",
                    "status": "succeeded",
                    "latest_charge": "ch_ok_1",
                    "metadata": {},
                }
            },
        }
    )

    ack = await handler.stripe_webhook(req)
    assert ack.received is True

    # Payment advanced
    updated = (
        await db_session.execute(
            select(DAOPayments).where(getattr(DAOPayments, "id") == seed.id)
        )
    ).scalar_one()
    assert updated.status == PaymentStatus.SUCCEEDED
    assert updated.stripe_latest_charge_id == "ch_ok_1"
    assert updated.failure_code is None and updated.failure_message is None

    # Events: snapshot + SYSTEM-applied + fulfill.attempt + fulfill.success
    evts = (
        (
            await db_session.execute(
                select(DAOPaymentEvents).order_by(
                    getattr(DAOPaymentEvents, "created_at")
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(evts) == 4
    # counts by source
    assert sum(1 for e in evts if e.source == PaymentEventSource.STRIPE_WEBHOOK) == 1
    assert sum(1 for e in evts if e.source == PaymentEventSource.SYSTEM) == 3
    # snapshot is linked to the stripe event id
    assert any(e.stripe_event_id == event_id for e in evts)
    # status apply recorded with SUCCEEDED
    assert any(e.applied_status == PaymentStatus.SUCCEEDED for e in evts)
    # fulfillment span (no snapshot provided in seed → no audit event)
    types = sorted(e.event_type or "" for e in evts)
    assert types.count("fulfill.attempt") == 1
    assert types.count("fulfill.success") == 1
    assert types.count("fulfill.audit") == 0


@pytest.mark.asyncio
async def test_WH4_idempotent_duplicate_event_no_double_apply(
    handler: StripeWebhookAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stripe

    # Seed payment
    pay = DAOPayments(
        id=uuid4(),
        created_by_user_id=uuid4(),
        photobook_id=uuid4(),
        purpose=PaymentPurpose.GIFTCARD,
        amount_total=1000,
        currency="usd",
        stripe_payment_intent_id="pi_dup",
        stripe_customer_id=None,
        stripe_payment_method_id=None,
        stripe_latest_charge_id=None,
        status=PaymentStatus.PROCESSING,
        description=None,
        receipt_email=None,
        idempotency_key="idem-dup",
        failure_code=None,
        failure_message=None,
        refunded_amount=0,
        metadata_json={},
    )
    db_session.add(pay)
    await db_session.commit()

    event_id: str = "evt_dup_1"
    pi = _pi_ns(pi_id="pi_dup", status="succeeded", latest_charge="ch_1")
    fake = _FakeStripeEvent(
        event_id=event_id, event_type="payment_intent.succeeded", pi=pi
    )
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda *a, **k: fake),
        raising=True,
    )

    req: Request = _make_request(
        {
            "id": event_id,
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_dup",
                    "status": "succeeded",
                    "latest_charge": "ch_1",
                    "metadata": {},
                }
            },
        }
    )

    # First delivery
    await handler.stripe_webhook(req)

    # Duplicate delivery with same event_id
    await handler.stripe_webhook(req)

    evts = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    # First call adds 4 rows (snapshot + applied + fulfill.attempt + fulfill.success).
    # Second call adds 0 rows due to idempotency check.
    assert len(evts) == 4
    # sanity: composition
    assert sum(1 for e in evts if e.source == PaymentEventSource.STRIPE_WEBHOOK) == 1
    assert sum(1 for e in evts if e.source == PaymentEventSource.SYSTEM) == 3
    types = sorted(e.event_type or "" for e in evts)
    assert types.count("fulfill.attempt") == 1
    assert types.count("fulfill.success") == 1

    row = (
        await db_session.execute(
            select(DAOPayments).where(getattr(DAOPayments, "id") == pay.id)
        )
    ).scalar_one()
    assert row.status == PaymentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_WH5_monotone_status_does_not_regress_from_succeeded(
    handler: StripeWebhookAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stripe

    # Seed succeeded payment
    pay = DAOPayments(
        id=uuid4(),
        created_by_user_id=uuid4(),
        photobook_id=uuid4(),
        purpose=PaymentPurpose.GIFTCARD,
        amount_total=3000,
        currency="usd",
        stripe_payment_intent_id="pi_done",
        stripe_customer_id=None,
        stripe_payment_method_id=None,
        stripe_latest_charge_id="ch_done",
        status=PaymentStatus.SUCCEEDED,
        description=None,
        receipt_email=None,
        idempotency_key="idem-done",
        failure_code=None,
        failure_message=None,
        refunded_amount=0,
        metadata_json={},
    )
    db_session.add(pay)
    await db_session.commit()

    # Send a "processing" after success
    event_id: str = "evt_late_processing"
    pi = _pi_ns(pi_id="pi_done", status="processing", latest_charge="ch_done")
    fake = _FakeStripeEvent(
        event_id=event_id, event_type="payment_intent.processing", pi=pi
    )
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda *a, **k: fake),
        raising=True,
    )

    req: Request = _make_request(
        {
            "id": event_id,
            "type": "payment_intent.processing",
            "data": {
                "object": {
                    "id": "pi_done",
                    "status": "processing",
                    "latest_charge": "ch_done",
                    "metadata": {},
                }
            },
        }
    )

    ack = await handler.stripe_webhook(req)
    assert ack.received is True

    # Status remains SUCCEEDED
    row = (
        await db_session.execute(
            select(DAOPayments).where(getattr(DAOPayments, "id") == pay.id)
        )
    ).scalar_one()
    assert row.status == PaymentStatus.SUCCEEDED

    # Two events were still appended for the new delivery
    # Events for this delivery: snapshot + applied(no-op, monotone) + fulfill.attempt + fulfill.success
    evts = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    assert len(evts) == 4
    # source composition
    assert sum(1 for e in evts if e.source == PaymentEventSource.STRIPE_WEBHOOK) == 1
    assert sum(1 for e in evts if e.source == PaymentEventSource.SYSTEM) == 3
    # fulfillment span present but no audit (no snapshot to fulfill)
    types = sorted(e.event_type or "" for e in evts)
    assert types.count("fulfill.attempt") == 1
    assert types.count("fulfill.success") == 1
    assert types.count("fulfill.audit") == 0


@pytest.mark.asyncio
async def test_WH6_failure_fields_populated_when_failed_like_state(
    handler: StripeWebhookAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stripe

    # Seed payment in confirmation
    pay = DAOPayments(
        id=uuid4(),
        created_by_user_id=uuid4(),
        photobook_id=uuid4(),
        purpose=PaymentPurpose.GIFTCARD,
        amount_total=4200,
        currency="usd",
        stripe_payment_intent_id="pi_fail",
        stripe_customer_id=None,
        stripe_payment_method_id=None,
        stripe_latest_charge_id=None,
        status=PaymentStatus.REQUIRES_CONFIRMATION,
        description=None,
        receipt_email=None,
        idempotency_key="idem-f",
        failure_code=None,
        failure_message=None,
        refunded_amount=0,
        metadata_json={},
    )
    db_session.add(pay)
    await db_session.commit()

    # Stripe sends payment_intent.payment_failed, PI often returns requires_payment_method after failure
    event_id: str = "evt_fail_1"
    pi = _pi_ns(
        pi_id="pi_fail",
        status="requires_payment_method",
        latest_charge=None,
        last_error_code="card_declined",
        last_error_message="Your card was declined.",
    )
    fake = _FakeStripeEvent(
        event_id=event_id, event_type="payment_intent.payment_failed", pi=pi
    )
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda *a, **k: fake),
        raising=True,
    )

    req: Request = _make_request(
        {
            "id": event_id,
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_fail",
                    "status": "requires_payment_method",
                    "latest_charge": None,
                    "last_payment_error": {
                        "code": "card_declined",
                        "message": "Your card was declined.",
                    },
                    "metadata": {},
                }
            },
        }
    )

    ack = await handler.stripe_webhook(req)
    assert ack.received is True

    row = (
        await db_session.execute(
            select(DAOPayments).where(getattr(DAOPayments, "id") == pay.id)
        )
    ).scalar_one()
    # Our map treats 'requires_payment_method' as a valid status (not FAILED),
    # but failure_code/message should be recorded for non-success/processing states.
    assert row.status == PaymentStatus.REQUIRES_PAYMENT_METHOD
    assert row.failure_code == "card_declined"
    assert row.failure_message == "Your card was declined."

    # Two audit rows
    evts = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    assert len(evts) == 2
    assert evts[0].source == PaymentEventSource.STRIPE_WEBHOOK
    assert evts[1].source == PaymentEventSource.SYSTEM

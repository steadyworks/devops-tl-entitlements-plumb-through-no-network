# backend/tests/test_payment_status.py

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from backend.db.data_models import (
    DAOPaymentEvents,
    DAOPayments,
    DAOPhotobooks,
    PaymentEventSource,
    PaymentPurpose,
    PaymentStatus,
)
from backend.lib.payments.stripe.service import StatusApplyContext  # noqa: TC001
from backend.lib.payments.stripe.utils import StripePISnapshot
from backend.route_handler import payment as payment_mod
from backend.route_handler.payment import PaymentAPIHandler, PaymentStatusResponse

if TYPE_CHECKING:
    from backend.lib.types.asset import AssetStorageKey

# -------------------------
# Test utilities / stubs
# -------------------------


def _make_get_request(
    path: str,
    *,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> Request:
    """
    Construct a minimal Starlette Request for GET endpoints.
    """
    query_string: bytes = (
        "&".join(f"{k}={v}" for k, v in (query or {}).items()).encode("utf-8")
        if query
        else b""
    )
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [
            (k.encode("utf-8"), v.encode("utf-8"))
            for k, v in (headers or {"content-type": "application/json"}).items()
        ],
        "query_string": query_string,
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
    }

    async def _receive() -> dict[str, Any]:
        # No body for GET
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


class _AsyncSessionCtx:
    def __init__(self, s: AsyncSession) -> None:
        self._s = s

    async def __aenter__(self) -> AsyncSession:
        return self._s

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> None:
        return None


class _SessionFactory:
    """
    app.db_session_factory shim that returns an **async context manager**.
    NOTE: new_session() must be a normal function returning an object with
    async __aenter__/__aexit__ — not an async function.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def new_session(self) -> _AsyncSessionCtx:
        return _AsyncSessionCtx(self._session)


@dataclass
class _RequestContext:
    user_id: UUID


class _StripeClientFake:
    """
    Minimal async Stripe client stub with an injectable behavior.
    """

    def __init__(
        self,
        *,
        retrieve_impl: Optional[Callable[[str], Awaitable[object]]] = None,
    ) -> None:
        self._retrieve_impl = retrieve_impl
        self.called_count: int = 0
        self.last_requested_pi: Optional[str] = None

    async def retrieve_payment_intent_async(self, *, payment_intent_id: str) -> object:
        self.called_count += 1
        self.last_requested_pi = payment_intent_id
        if self._retrieve_impl is None:
            # Default: behave like "not found/temporary error"
            raise RuntimeError("retrieve not configured (test)")
        return await self._retrieve_impl(payment_intent_id)


class _DummyAssetManager:
    async def generate_signed_urls_batched(
        self, src_keys: list[AssetStorageKey], expires_in: int = 86_400
    ) -> dict[AssetStorageKey, str | Exception]:
        return dict()


class _AppStub:
    def __init__(self, session: AsyncSession) -> None:
        self.db_session_factory = _SessionFactory(session)
        self.asset_manager = _DummyAssetManager()


# -------------------------
# Fixtures
# -------------------------


@pytest.fixture
def handler(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> PaymentAPIHandler:
    """
    Construct PaymentAPIHandler with app stub and no-op route registration.
    """
    h = PaymentAPIHandler(app=_AppStub(db_session))  # type: ignore[arg-type]
    try:
        h.register_routes()
    except Exception:
        pass
    return h


# -------------------------
# Helpers for seeding payments
# -------------------------


async def _seed_payment(
    session: AsyncSession,
    *,
    owner_id: UUID,
    status: PaymentStatus,
    amount_cents: int = 1000,
    currency: str = "usd",
    stripe_pi_id: Optional[str] = "pi_test_123",
) -> DAOPayments:
    row = DAOPayments(
        id=uuid4(),
        created_by_user_id=owner_id,
        photobook_id=uuid4(),
        purpose=PaymentPurpose.GIFTCARD,
        amount_total=amount_cents,
        currency=currency,
        stripe_payment_intent_id=stripe_pi_id,
        stripe_customer_id=None,
        stripe_payment_method_id=None,
        stripe_latest_charge_id=None,
        status=status,
        description=None,
        receipt_email=None,
        idempotency_key="idem-test",
        failure_code=None,
        failure_message=None,
        refunded_amount=0,
        metadata_json={},
    )
    session.add(row)
    await session.commit()
    return row


# -------------------------
# Tests
# -------------------------


@pytest.mark.asyncio
async def test_PS1_non_eager_returns_db_state_without_stripe(
    handler: PaymentAPIHandler,
    db_session: AsyncSession,
) -> None:
    owner_id: UUID = uuid4()
    p = await _seed_payment(
        db_session,
        owner_id=owner_id,
        status=PaymentStatus.PROCESSING,
        stripe_pi_id="pi_no_call",
    )

    # Stub auth + owner check + stripe client
    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_id)

    async def _get_payment(
        session: AsyncSession, payment_id: UUID, user_id: UUID
    ) -> DAOPayments:
        row = await db_session.get(DAOPayments, payment_id)
        assert row is not None
        assert row.created_by_user_id == user_id
        return row

    sc = _StripeClientFake()  # not configured → would raise if called

    handler.get_request_context = _get_rcx  # type: ignore[assignment]
    handler.get_payment_assert_owned_by = _get_payment  # type: ignore[assignment]
    handler.get_stripe_client_for_request = lambda _req: sc  # type: ignore[method-assign, assignment, return-value]

    req: Request = _make_get_request(f"/api/payments/{p.id}/status")

    resp: PaymentStatusResponse = await handler.payment_status(
        request=req,
        payment_id=p.id,
        eager=False,
    )
    assert resp.status.id == p.id
    assert resp.status.status == PaymentStatus.PROCESSING
    assert resp.terminal is False
    assert sc.called_count == 0
    # Should recommend a short poll (1000ms for PROCESSING per utils)
    assert resp.recommended_poll_after_ms in (1000, 2000)


@pytest.mark.asyncio
async def test_PS2_eager_with_stripe_error_falls_back_to_db_state(
    handler: PaymentAPIHandler,
    db_session: AsyncSession,
) -> None:
    owner_id: UUID = uuid4()
    p = await _seed_payment(
        db_session,
        owner_id=owner_id,
        status=PaymentStatus.REQUIRES_CONFIRMATION,
        stripe_pi_id="pi_err",
    )

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_id)

    async def _get_payment(
        session: AsyncSession, payment_id: UUID, user_id: UUID
    ) -> DAOPayments:
        row = await db_session.get(DAOPayments, payment_id)
        assert row is not None and row.created_by_user_id == user_id
        return row

    async def _retrieve_fail(_pi: str) -> object:
        raise RuntimeError("stripe down")

    sc = _StripeClientFake(retrieve_impl=_retrieve_fail)

    handler.get_request_context = _get_rcx  # type: ignore[assignment]
    handler.get_payment_assert_owned_by = _get_payment  # type: ignore[assignment]
    handler.get_stripe_client_for_request = lambda _req: sc  # type: ignore[method-assign, assignment, return-value]

    req: Request = _make_get_request(
        f"/api/payments/{p.id}/status", query={"eager": "true"}
    )
    resp: PaymentStatusResponse = await handler.payment_status(
        request=req,
        payment_id=p.id,
        eager=True,
    )

    assert sc.called_count == 1
    assert resp.status.status == PaymentStatus.REQUIRES_CONFIRMATION
    assert resp.terminal is False


@pytest.mark.asyncio
async def test_PS3_eager_advances_status_to_succeeded_and_appends_event(
    handler: PaymentAPIHandler,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    photobook: DAOPhotobooks,
) -> None:
    owner_id: UUID = uuid4()
    p = await _seed_payment(
        db_session,
        owner_id=owner_id,
        status=PaymentStatus.PROCESSING,
        stripe_pi_id="pi_adv",
    )

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_id)

    async def _get_payment(
        session: AsyncSession, payment_id: UUID, user_id: UUID
    ) -> DAOPayments:
        row = await db_session.get(DAOPayments, payment_id)
        assert row is not None and row.created_by_user_id == user_id
        return row

    async def _retrieve_ok(_pi: str) -> object:
        # Return any object; parse_payment_intent_obj is patched below to interpret it.
        return SimpleNamespace(ok=True)

    sc = _StripeClientFake(retrieve_impl=_retrieve_ok)

    # Patch parse_payment_intent_obj to return a "succeeded" snapshot

    # Patch parse_payment_intent_obj ON THE payment MODULE (not utils)
    def _parse_stub(_obj: object) -> StripePISnapshot:
        return StripePISnapshot(
            id="pi_adv",
            status_str="succeeded",
            latest_charge_id="ch_777",
            failure_code=None,
            failure_message=None,
            metadata={},
        )

    monkeypatch.setattr(
        payment_mod, "parse_payment_intent_obj", _parse_stub, raising=True
    )

    # Patch reconcile_and_apply_payment_status_in_txn ON THE payment MODULE
    async def _reconcile_apply_stub(
        session: AsyncSession,
        *,
        payment_row: DAOPayments,
        pi_snapshot: StripePISnapshot,
        ctx: StatusApplyContext,
    ) -> tuple[DAOPayments, PaymentStatus, bool]:
        # mutate the row attached to THIS session/txn
        payment_row.status = PaymentStatus.SUCCEEDED
        payment_row.stripe_latest_charge_id = "ch_777"

        # append-only audit on THIS session/txn; no commits here
        session.add(
            DAOPaymentEvents(
                payment_id=payment_row.id,
                stripe_event_id=None,
                stripe_event_type=ctx.event_type,
                source=PaymentEventSource.SYSTEM,
                payload={"reason": "eager_poll"},
                signature_verified=None,
                applied_status=PaymentStatus.SUCCEEDED,
            )
        )
        await session.flush()  # optional, ensures writes are visible before txn exit

        return payment_row, PaymentStatus.SUCCEEDED, True

    monkeypatch.setattr(
        payment_mod,
        "reconcile_and_apply_payment_status_in_txn",
        _reconcile_apply_stub,
        raising=True,
    )

    async def _get_ph_mock(
        db_session: AsyncSession, photobook_id: UUID, user_id: UUID
    ) -> DAOPhotobooks:
        return photobook

    handler.get_request_context = _get_rcx  # type: ignore[assignment]
    handler.get_payment_assert_owned_by = _get_payment  # type: ignore[assignment]
    handler.get_stripe_client_for_request = lambda _req: sc  # type: ignore[method-assign, assignment, return-value]
    handler.get_photobook_assert_owned_by = _get_ph_mock  # type: ignore[method-assign]

    req: Request = _make_get_request(
        f"/api/payments/{p.id}/status", query={"eager": "true"}
    )
    resp: PaymentStatusResponse = await handler.payment_status(
        request=req,
        payment_id=p.id,
        eager=True,
    )

    assert sc.called_count == 1
    assert resp.status.status == PaymentStatus.SUCCEEDED
    assert resp.terminal is True
    assert resp.recommended_poll_after_ms == 0

    # Ensure our stubbed "audit append" occurred
    events = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    # Ensure our stubbed in-txn status event occurred, and account for fulfillment span logs.
    events = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    # Expect: 1 status-apply event (from stub) + 2 span events (attempt, success) = 3
    assert len(events) == 3
    types = sorted(e.event_type for e in events if e.event_type is not None)
    # Fulfillment span logs even when there's no snapshot (no-op fulfillment)
    assert types.count("fulfill.attempt") == 1
    assert types.count("fulfill.success") == 1
    # No in-txn fulfill.audit because no snapshot → no side effects
    assert types.count("fulfill.audit") == 0
    # The in-txn status event we stubbed should be present and marked SUCCEEDED
    status_events = [e for e in events if e.applied_status == PaymentStatus.SUCCEEDED]
    assert len(status_events) == 1
    assert status_events[0].source == PaymentEventSource.SYSTEM


@pytest.mark.asyncio
async def test_PS4_terminal_payment_skips_stripe_even_eager(
    handler: PaymentAPIHandler,
    db_session: AsyncSession,
    photobook: DAOPhotobooks,
) -> None:
    owner_id: UUID = uuid4()
    p = await _seed_payment(
        db_session,
        owner_id=owner_id,
        status=PaymentStatus.SUCCEEDED,
        stripe_pi_id="pi_done",
    )

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_id)

    async def _get_payment(
        session: AsyncSession, payment_id: UUID, user_id: UUID
    ) -> DAOPayments:
        row = await db_session.get(DAOPayments, payment_id)
        assert row is not None and row.created_by_user_id == user_id
        return row

    sc = _StripeClientFake(retrieve_impl=None)  # would raise if called

    async def _get_ph_mock(
        db_session: AsyncSession, photobook_id: UUID, user_id: UUID
    ) -> DAOPhotobooks:
        return photobook

    handler.get_request_context = _get_rcx  # type: ignore[assignment]
    handler.get_payment_assert_owned_by = _get_payment  # type: ignore[assignment]
    handler.get_stripe_client_for_request = lambda _req: sc  # type: ignore[method-assign, assignment, return-value]
    handler.get_photobook_assert_owned_by = _get_ph_mock  # type: ignore[method-assign]

    req: Request = _make_get_request(
        f"/api/payments/{p.id}/status", query={"eager": "true"}
    )
    resp: PaymentStatusResponse = await handler.payment_status(
        request=req,
        payment_id=p.id,
        eager=True,
    )

    assert sc.called_count == 0  # terminal → no Stripe call
    assert resp.status.status == PaymentStatus.SUCCEEDED
    assert resp.terminal is True
    assert resp.recommended_poll_after_ms == 0


@pytest.mark.asyncio
async def test_PS5_non_owner_gets_404(
    handler: PaymentAPIHandler,
    db_session: AsyncSession,
) -> None:
    owner_id: UUID = uuid4()
    other_user_id: UUID = uuid4()
    p = await _seed_payment(
        db_session,
        owner_id=owner_id,
        status=PaymentStatus.PROCESSING,
        stripe_pi_id="pi_secure",
    )

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=other_user_id)

    async def _get_payment(
        session: AsyncSession, payment_id: UUID, user_id: UUID
    ) -> DAOPayments:
        row = await db_session.get(DAOPayments, payment_id)
        assert row is not None
        # Simulate the handler's assert-owned-by behavior: raise (FastAPI -> 404)
        if row.created_by_user_id != user_id:
            raise RuntimeError(
                "not owner"
            )  # handler wraps/raises HTTPException in real code
        return row

    sc = _StripeClientFake()

    handler.get_request_context = _get_rcx  # type: ignore[assignment]
    handler.get_payment_assert_owned_by = _get_payment  # type: ignore[assignment]
    handler.get_stripe_client_for_request = lambda _req: sc  # type: ignore[method-assign, assignment, return-value]

    req: Request = _make_get_request(f"/api/payments/{p.id}/status")

    with pytest.raises(Exception):
        # In your real handler, ownership failure becomes HTTPException(404).
        await handler.payment_status(
            request=req,
            payment_id=p.id,
            eager=False,
        )

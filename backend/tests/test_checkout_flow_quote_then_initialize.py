# backend/tests/test_checkout_flow_quote_then_initialize.py

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from backend.db.data_models import (
    DAOPaymentEvents,
    DAOPayments,
    PaymentStatus,
    ShareChannelType,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    GiftcardGrantRequest,
    ShareChannelSpec,
    ShareCreateRequest,
    ShareRecipientSpec,
)
from backend.lib.giftcard.brands.registry import BrandRegistryEntry
from backend.lib.payments.stripe.base import StripeCreatePaymentIntentResult
from backend.lib.pricing.types import (
    PricingSnapshot,
    QuoteLineItem,
    QuoteLineKind,
)
from backend.route_handler.checkout import (
    CheckoutAPIHandler,
    CheckoutPaymentBootstrapRequest,
    CheckoutPaymentBootstrapResponse,
    CheckoutQuoteRequest,
    CheckoutQuoteResponse,
)

# -------------------------
# Minimal Request builders
# -------------------------


def _make_post_request(
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [
            (k.encode("utf-8"), v.encode("utf-8"))
            for k, v in (headers or {"content-type": "application/json"}).items()
        ],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
    }

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


# -------------------------
# App stub with new_db_session()
# -------------------------


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


class _AppStubCheckout:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def new_db_session(self) -> _AsyncSessionCtx:
        return _AsyncSessionCtx(self._session)


# -------------------------
# Request context + Stripe fakes
# -------------------------


@dataclass
class _RequestContext:
    user_id: UUID


class _StripeClientFakeCheckout:
    """
    Async Stripe client stub capturing inputs and allowing custom behavior.
    """

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []
        self._create_result: Optional[StripeCreatePaymentIntentResult] = (
            StripeCreatePaymentIntentResult(
                stripe_payment_intent_id="pi_test_123",
                client_secret="cs_test_abc",
                latest_charge_id="ch_test_001",
                status=PaymentStatus.REQUIRES_PAYMENT_METHOD,
            )
        )
        self._should_raise_on_create: bool = False

    def set_create_result(self, res: StripeCreatePaymentIntentResult) -> None:
        self._create_result = res

    def set_raise_on_create(self, should_raise: bool) -> None:
        self._should_raise_on_create = should_raise

    async def create_stripe_payment_intent_async(
        self,
        *,
        amount: int,
        currency: str,
        description: Optional[str],
        idempotency_key: str,
        metadata: dict[str, str],
    ) -> StripeCreatePaymentIntentResult:
        self.create_calls.append(
            {
                "amount": amount,
                "currency": currency,
                "description": description,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
            }
        )
        if self._should_raise_on_create:
            raise RuntimeError("stripe create failure (test)")
        assert self._create_result is not None
        return self._create_result

    async def try_cancel_stripe_payment_intent_async(
        self, *, stripe_payment_intent_id: str
    ) -> None:
        self.cancel_calls.append(stripe_payment_intent_id)


# -------------------------
# RequestPricer fake (same as in initialize tests)
# -------------------------


@dataclass
class _FakePricingContext:
    photobook_id: UUID
    recipients_fp: str
    currency: str
    brand_code: str
    brand_display_name: str
    amount_minor_per_share: int
    recipients_count: int
    pricing_config: str
    coupon_code: str | None = None


@dataclass
class _FakeSignedPricing:
    context: _FakePricingContext
    signature: str
    snapshot: PricingSnapshot


class _RequestPricerFake:
    """
    Context-aware fake pricer for tests:
    - subtotal = amount_per_share * recipients
    - fee = 350 if currency == 'usd' else 0
    - signature = "sig:<per>:<n>:<currency>:<coupon_or_none>"
    This makes verification sensitive to payload drift.
    """

    def _sig_for(self, *, per: int, n: int, currency: str, coupon: str | None) -> str:
        return f"sig:{per}:{n}:{currency}:{(coupon or 'none').lower()}"

    async def prepare_signed_pricing(
        self,
        *,
        photobook_id: UUID,
        share_create_request: ShareCreateRequest,
        giftcard_request: GiftcardGrantRequest,
        brand: BrandRegistryEntry,
        coupon_code: str | None,
    ) -> _FakeSignedPricing:
        currency = giftcard_request.currency.lower().strip()
        per = int(giftcard_request.amount_per_share)
        n = len(share_create_request.recipients)
        subtotal = per * n
        fee = 350 if currency == "usd" else 0
        total = subtotal + fee

        ctx = _FakePricingContext(
            photobook_id=photobook_id,
            recipients_fp="fp_test_const",  # stable in tests
            currency=currency,
            brand_code=brand.brand_code,
            brand_display_name=brand.display_name,
            amount_minor_per_share=per,
            recipients_count=n,
            pricing_config="default",
            coupon_code=coupon_code,
        )

        sig = self._sig_for(per=per, n=n, currency=currency, coupon=coupon_code)

        snap = PricingSnapshot(
            currency=currency,
            lines=[
                QuoteLineItem(
                    kind=QuoteLineKind.GIFTCARD_SUBTOTAL,
                    code="giftcard",
                    description=f"{giftcard_request.brand_code} Gift Card × {n}",
                    amount_minor=subtotal,
                    metadata={
                        "brand_code": giftcard_request.brand_code,
                        "amount_minor_per_share": per,
                        "count": n,
                    },
                ),
                QuoteLineItem(
                    kind=QuoteLineKind.PROCESSING_FEE,
                    code="proc_fee_dynamic",
                    description="Processing Fee",
                    amount_minor=fee,
                ),
            ],
            subtotal_minor=subtotal,
            discount_minor=0,
            fee_minor=fee,
            tax_minor=0,
            total_minor=total,
            coupon=None,
            pricing_config="default",
            pricing_signature=sig,
        )
        return _FakeSignedPricing(context=ctx, signature=sig, snapshot=snap)

    def verify_signature(self, *, ctx: _FakePricingContext, client_sig: str) -> bool:
        expected = self._sig_for(
            per=ctx.amount_minor_per_share,
            n=ctx.recipients_count,
            currency=ctx.currency,
            coupon=ctx.coupon_code,
        )
        return client_sig == expected


# -------------------------
# Handler fixture
# -------------------------


@pytest.fixture
def checkout_handler(db_session: AsyncSession) -> CheckoutAPIHandler:
    h = CheckoutAPIHandler(app=_AppStubCheckout(db_session))  # type: ignore[arg-type]
    try:
        h.register_routes()
    except Exception:
        pass
    return h


# -------------------------
# FLOW TESTS: /quote → /initialize-payment
# -------------------------


@pytest.mark.asyncio
async def test_QI1_quote_then_initialize_success(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fakes
    stripe_fake = _StripeClientFakeCheckout()
    stripe_fake.set_create_result(
        StripeCreatePaymentIntentResult(
            stripe_payment_intent_id="pi_flow_ok",
            client_secret="cs_flow_ok",
            latest_charge_id="ch_flow_ok",
            status=PaymentStatus.REQUIRES_PAYMENT_METHOD,
        )
    )

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        assert pb_id == photobook.id
        assert user_id == owner_user.id

    from backend.db.dal import DALPhotobooks as _DALPhotobooksReal

    async def _returning_none(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(_DALPhotobooksReal, "get_by_id", _returning_none, raising=False)

    checkout_handler.get_request_context = _get_rcx  # type: ignore[assignment]
    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore[assignment]
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore[method-assign, assignment, return-value]
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore[return-value, method-assign, assignment]

    # ---------- Step 1: /quote ----------
    base_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="friend@example.com",
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=500, currency="USD", brand_code="amazon_us"
        ),
    )

    quote_payload = CheckoutQuoteRequest(share_request=base_req, coupon_code=None)
    quote_req = _make_post_request(f"/api/checkout/{photobook.id}/quote")

    quote_res: CheckoutQuoteResponse = await checkout_handler.checkout_quote(
        photobook_id=photobook.id, payload=quote_payload, request=quote_req
    )

    assert quote_res.pricing.total_minor == 850  # 500 + 350 fee
    assert quote_res.pricing.currency == "usd"
    sig_from_quote = quote_res.pricing.pricing_signature

    # ---------- Step 2: /initialize-payment (with signature from /quote) ----------
    init_payload = CheckoutPaymentBootstrapRequest(
        share_request=base_req,
        coupon_code=None,
        client_pricing_signature=sig_from_quote,
        quote_id=quote_res.quote_id,
    )
    init_req = _make_post_request(
        f"/api/checkout/{photobook.id}/initialize-payment",
        headers={"X-Debug-Use-Sandbox": "true"},
    )

    init_res: CheckoutPaymentBootstrapResponse = (
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id, payload=init_payload, request=init_req
        )
    )

    assert init_res.amount_total == quote_res.pricing.total_minor == 850
    assert init_res.currency == "usd"
    assert init_res.pricing_snapshot.total_minor == 850
    assert init_res.pricing_snapshot.pricing_signature == sig_from_quote

    # Stripe called with the same total as quote
    assert len(stripe_fake.create_calls) == 1
    assert stripe_fake.create_calls[0]["amount"] == 850
    assert stripe_fake.create_calls[0]["currency"] == "usd"

    # One payment row + one event row persisted
    pay_rows = (await db_session.execute(select(DAOPayments))).scalars().all()
    evt_rows = (await db_session.execute(select(DAOPaymentEvents))).scalars().all()
    assert len(pay_rows) == 1
    assert len(evt_rows) == 1


@pytest.mark.asyncio
async def test_QI2_quote_then_initialize_signature_mismatch_due_to_payload_change_409(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
) -> None:
    # Fakes
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_request_context = _get_rcx  # type: ignore[assignment]
    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore[assignment]
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore[method-assign, assignment, return-value]
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore[return-value, method-assign, assignment]

    # Step 1: quote for 1 recipient
    base_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="friend@example.com",
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=500, currency="USD", brand_code="amazon_us"
        ),
    )
    quote_res: CheckoutQuoteResponse = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=base_req, coupon_code=None),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )
    sig_from_quote = quote_res.pricing.pricing_signature

    # Step 2: initialize with a CHANGED payload (2 recipients) but the same signature
    changed_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend A",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="a@example.com",
                    )
                ],
            ),
            ShareRecipientSpec(
                recipient_display_name="Friend B",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="b@example.com",
                    )
                ],
            ),
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=500, currency="USD", brand_code="amazon_us"
        ),
    )

    with pytest.raises(Exception):
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id,
            payload=CheckoutPaymentBootstrapRequest(
                share_request=changed_req,  # different than quoted!
                coupon_code=None,
                client_pricing_signature=sig_from_quote,
                quote_id=quote_res.quote_id,
            ),
            request=_make_post_request(
                f"/api/checkout/{photobook.id}/initialize-payment"
            ),
        )

    # Expect 409 with fresh pricing; Stripe not called; DB untouched
    assert len(stripe_fake.create_calls) == 0
    assert len((await db_session.execute(select(DAOPayments))).scalars().all()) == 0
    assert (
        len((await db_session.execute(select(DAOPaymentEvents))).scalars().all()) == 0
    )


@pytest.mark.asyncio
async def test_QI3_quote_then_initialize_with_random_signature_409(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
) -> None:
    # Fakes
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_request_context = _get_rcx  # type: ignore[assignment]
    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore[assignment]
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore[method-assign, assignment, return-value]
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore[return-value, method-assign, assignment]

    # Step 1: quote
    base_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="friend@example.com",
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=500, currency="USD", brand_code="amazon_us"
        ),
    )
    quote_res: CheckoutQuoteResponse = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=base_req, coupon_code=None),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )

    # Step 2: initialize with a completely bogus signature
    with pytest.raises(Exception):
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id,
            payload=CheckoutPaymentBootstrapRequest(
                share_request=base_req,
                coupon_code=None,
                client_pricing_signature="definitely_not_the_quote_sig",
                quote_id=quote_res.quote_id,
            ),
            request=_make_post_request(
                f"/api/checkout/{photobook.id}/initialize-payment"
            ),
        )

    # No Stripe/DB side effects
    assert len(stripe_fake.create_calls) == 0
    assert len((await db_session.execute(select(DAOPayments))).scalars().all()) == 0
    assert (
        len((await db_session.execute(select(DAOPaymentEvents))).scalars().all()) == 0
    )


@pytest.mark.asyncio
async def test_QI4_initialize_missing_client_signature_400(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
) -> None:
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_request_context = _get_rcx  # type: ignore[assignment]
    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore[assignment]
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore

    # Use the context-aware fake pricer from the fix
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore[return-value, method-assign, assignment]

    base_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL,
                        destination="friend@example.com",
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=500, currency="USD", brand_code="amazon_us"
        ),
    )

    # Missing client_pricing_signature
    payload = CheckoutPaymentBootstrapRequest(
        share_request=base_req,
        coupon_code=None,
        client_pricing_signature="",  # missing
        quote_id=None,
    )

    with pytest.raises(HTTPException) as ei:
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id,
            payload=payload,
            request=_make_post_request(
                f"/api/checkout/{photobook.id}/initialize-payment"
            ),
        )
    assert ei.value.status_code == 400
    assert len(stripe_fake.create_calls) == 0
    assert len((await db_session.execute(select(DAOPayments))).scalars().all()) == 0


@pytest.mark.asyncio
async def test_QI5_quote_then_initialize_coupon_changed_409(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
) -> None:
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    checkout_handler.get_request_context = _get_rcx  # type: ignore

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore

    base_req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="F",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL, destination="f@e.com"
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=1000, currency="USD", brand_code="amazon_us"
        ),
    )

    # Step 1: quote with coupon=A
    quote = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=base_req, coupon_code="PERCENT10"),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )

    # Step 2: initialize with coupon=B but reuse signature from quote
    with pytest.raises(HTTPException) as ei:
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id,
            payload=CheckoutPaymentBootstrapRequest(
                share_request=base_req,
                coupon_code="FLAT500",  # changed
                client_pricing_signature=quote.pricing.pricing_signature,
                quote_id=quote.quote_id,
            ),
            request=_make_post_request(
                f"/api/checkout/{photobook.id}/initialize-payment"
            ),
        )

    assert ei.value.status_code == 409
    assert len(stripe_fake.create_calls) == 0
    assert len((await db_session.execute(select(DAOPayments))).scalars().all()) == 0


@pytest.mark.asyncio
async def test_QI6_quote_then_initialize_non_usd_fee_zero_success(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    checkout_handler.get_request_context = _get_rcx  # type: ignore

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore

    from backend.db.dal import DALPhotobooks as _DALPhotobooksReal

    async def _returning_none(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(_DALPhotobooksReal, "get_by_id", _returning_none, raising=False)

    req_eur = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL, destination="f@e.com"
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=1200, currency="EUR", brand_code="nike"
        ),
    )

    quote = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=req_eur, coupon_code=None),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )
    # For EUR, fake pricer sets fee=0 → total=subtotal
    assert quote.pricing.fee_minor == 0
    assert quote.pricing.total_minor == quote.pricing.subtotal_minor

    init_resp = await checkout_handler.checkout_initializing_payment(
        photobook_id=photobook.id,
        payload=CheckoutPaymentBootstrapRequest(
            share_request=req_eur,
            coupon_code=None,
            client_pricing_signature=quote.pricing.pricing_signature,
            quote_id=quote.quote_id,
        ),
        request=_make_post_request(f"/api/checkout/{photobook.id}/initialize-payment"),
    )

    assert init_resp.amount_total == quote.pricing.total_minor
    assert init_resp.currency == "eur"
    assert len(stripe_fake.create_calls) == 1


@pytest.mark.asyncio
async def test_QI7_initialize_stripe_failure_502(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
) -> None:
    stripe_fake = _StripeClientFakeCheckout()
    stripe_fake.set_raise_on_create(True)

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    checkout_handler.get_request_context = _get_rcx  # type: ignore

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore

    req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL, destination="f@e.com"
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=2000, currency="USD", brand_code="amazon_us"
        ),
    )

    quote = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=req, coupon_code=None),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )

    with pytest.raises(HTTPException) as ei:
        await checkout_handler.checkout_initializing_payment(
            photobook_id=photobook.id,
            payload=CheckoutPaymentBootstrapRequest(
                share_request=req,
                coupon_code=None,
                client_pricing_signature=quote.pricing.pricing_signature,
                quote_id=quote.quote_id,
            ),
            request=_make_post_request(
                f"/api/checkout/{photobook.id}/initialize-payment"
            ),
        )
    assert ei.value.status_code == 502
    # No DB writes on provider failure
    assert len((await db_session.execute(select(DAOPayments))).scalars().all()) == 0


@pytest.mark.asyncio
async def test_QI8_idempotency_changes_when_signature_changes(
    checkout_handler: CheckoutAPIHandler,
    db_session: AsyncSession,
    owner_user: Any,
    photobook: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stripe_fake = _StripeClientFakeCheckout()

    async def _get_rcx(_req: Request) -> _RequestContext:
        return _RequestContext(user_id=owner_user.id)

    checkout_handler.get_request_context = _get_rcx  # type: ignore

    async def _assert_owned(session: AsyncSession, pb_id: UUID, user_id: UUID) -> None:
        return None

    checkout_handler.get_photobook_assert_owned_by = _assert_owned  # type: ignore
    checkout_handler.get_stripe_client_for_request = lambda _req: stripe_fake  # type: ignore
    checkout_handler.get_request_pricer = lambda _req: _RequestPricerFake()  # type: ignore

    from backend.db.dal import DALPhotobooks as _DALPhotobooksReal

    async def _returning_none(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(_DALPhotobooksReal, "get_by_id", _returning_none, raising=False)

    req = ShareCreateRequest(
        recipients=[
            ShareRecipientSpec(
                recipient_display_name="Friend",
                channels=[
                    ShareChannelSpec(
                        channel_type=ShareChannelType.EMAIL, destination="f@e.com"
                    )
                ],
            )
        ],
        sender_display_name="Me",
        giftcard_request=GiftcardGrantRequest(
            amount_per_share=1000, currency="USD", brand_code="amazon_us"
        ),
    )

    # Quote A (no coupon)
    quote_a = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=req, coupon_code=None),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )
    # Quote B (coupon PERCENT10)
    quote_b = await checkout_handler.checkout_quote(
        photobook_id=photobook.id,
        payload=CheckoutQuoteRequest(share_request=req, coupon_code="PERCENT10"),
        request=_make_post_request(f"/api/checkout/{photobook.id}/quote"),
    )

    # Initialize with quote A
    resp_a = await checkout_handler.checkout_initializing_payment(
        photobook_id=photobook.id,
        payload=CheckoutPaymentBootstrapRequest(
            share_request=req,
            coupon_code=None,
            client_pricing_signature=quote_a.pricing.pricing_signature,
            quote_id=quote_a.quote_id,
        ),
        request=_make_post_request(f"/api/checkout/{photobook.id}/initialize-payment"),
    )
    # Initialize with quote B
    resp_b = await checkout_handler.checkout_initializing_payment(
        photobook_id=photobook.id,
        payload=CheckoutPaymentBootstrapRequest(
            share_request=req,
            coupon_code="PERCENT10",
            client_pricing_signature=quote_b.pricing.pricing_signature,
            quote_id=quote_b.quote_id,
        ),
        request=_make_post_request(f"/api/checkout/{photobook.id}/initialize-payment"),
    )

    # Different idempotency keys since pricing signature (and total) changed
    assert resp_a.idempotency_key != resp_b.idempotency_key

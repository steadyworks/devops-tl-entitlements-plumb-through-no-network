# backend/route_handler/checkout.py

import hashlib
import logging
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel

# DAL imports
from backend.db.dal import (
    DALPaymentEvents,
    DALPayments,
    DALPhotobooks,
    DAOPaymentEventsCreate,
    DAOPaymentsCreate,
    safe_transaction,
)
from backend.db.data_models import (
    PaymentEventSource,
    PaymentPurpose,
    PaymentStatus,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.db.externals import PhotobooksOverviewResponse
from backend.lib.giftcard.brands.registry import REGISTRY_SINGLETON
from backend.lib.pricing.types import PricingSnapshot
from backend.route_handler.base import RouteHandler, enforce_response_model

# -----------------------
# Response model
# -----------------------


class CheckoutQuoteRequest(BaseModel):
    share_request: ShareCreateRequest
    coupon_code: str | None = None


class CheckoutQuoteResponse(BaseModel):
    quote_id: UUID  # server-issued for UI caching/reference
    pricing: PricingSnapshot


class CheckoutPaymentBootstrapRequest(BaseModel):
    share_request: ShareCreateRequest
    coupon_code: str | None = None  # optional coupon typed by user
    client_pricing_signature: str
    quote_id: UUID | None = None  # echo from /quote (optional)


class CheckoutPaymentBootstrapResponse(BaseModel):
    payment_id: UUID
    stripe_payment_intent_id: str
    client_secret: str
    status: PaymentStatus
    amount_total: int
    currency: str
    idempotency_key: str
    pricing_snapshot: PricingSnapshot
    quote_id: UUID | None = None
    updated_photobook: PhotobooksOverviewResponse | None = None


# -----------------------
# Route handler
# -----------------------


class CheckoutAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/checkout/{photobook_id}/initialize-payment",
            "checkout_initializing_payment",
            methods=["POST"],
        )

        self.route(
            "/api/checkout/{photobook_id}/quote", "checkout_quote", methods=["POST"]
        )

    # ------------
    # Main handlers
    # ------------
    @enforce_response_model
    async def checkout_quote(
        self,
        photobook_id: UUID,
        payload: CheckoutQuoteRequest,
        request: Request,
    ) -> CheckoutQuoteResponse:
        async with self.app.new_db_session() as session:
            ctx = await self.get_request_context(request)
            await self.get_photobook_assert_owned_by(session, photobook_id, ctx.user_id)
            request_pricer = self.get_request_pricer(request)

            req = payload.share_request
            if not req.recipients:
                raise HTTPException(
                    status_code=400, detail="At least one recipient is required."
                )
            if req.giftcard_request is None:
                raise HTTPException(
                    status_code=400, detail="Giftcard request is required for quote."
                )
            if (
                int(req.giftcard_request.amount_per_share) <= 0
                or len(req.recipients) <= 0
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Amount per share and recipients must be > 0.",
                )

            brand_code = req.giftcard_request.brand_code
            brand = REGISTRY_SINGLETON.get_brand_by_code(brand_code)
            if brand is None:
                raise HTTPException(
                    status_code=400, detail=f"Brand code {brand_code} is invalid."
                )

            signed_pricing = await request_pricer.prepare_signed_pricing(
                photobook_id=photobook_id,
                share_create_request=req,
                giftcard_request=req.giftcard_request,
                brand=brand,
                coupon_code=payload.coupon_code,
            )
            resp = CheckoutQuoteResponse(
                quote_id=uuid4(),  # cache server-side if you plan to enforce TTL
                pricing=signed_pricing.snapshot,
            )
            return resp

    @enforce_response_model
    async def checkout_initializing_payment(
        self,
        photobook_id: UUID,
        payload: CheckoutPaymentBootstrapRequest,
        request: Request,
    ) -> CheckoutPaymentBootstrapResponse:
        async with self.app.new_db_session() as session:
            ctx = await self.get_request_context(request)
            current_user_id = ctx.user_id

            async with safe_transaction(session, context="auth photobook ownership"):
                await self.get_photobook_assert_owned_by(
                    session, photobook_id, current_user_id
                )

            request_pricer = self.get_request_pricer(request)

            req = payload.share_request
            if not req.recipients:
                raise HTTPException(
                    status_code=400, detail="At least one recipient is required."
                )
            if req.giftcard_request is None:
                raise HTTPException(
                    status_code=400,
                    detail="Giftcard request is required for paid checkout.",
                )
            if (
                int(req.giftcard_request.amount_per_share) <= 0
                or len(req.recipients) <= 0
            ):
                raise HTTPException(
                    status_code=400, detail="Invalid recipients or amount."
                )

            if not payload.client_pricing_signature:
                raise HTTPException(
                    status_code=400,
                    detail="Missing client_pricing_signature. Fetch /quote first.",
                )

            brand_code = req.giftcard_request.brand_code
            brand = REGISTRY_SINGLETON.get_brand_by_code(brand_code)
            if brand is None:
                raise HTTPException(
                    status_code=400, detail=f"Brand code {brand_code} is invalid."
                )

            # ---- Centralized pricing + signature
            # Build context from payload; compute signed pricing snapshot
            signed = await request_pricer.prepare_signed_pricing(
                photobook_id=photobook_id,
                share_create_request=req,
                giftcard_request=req.giftcard_request,
                brand=brand,
                coupon_code=payload.coupon_code,
            )
            # Verify client signature against *current* canonical message
            if not request_pricer.verify_signature(
                ctx=signed.context, client_sig=payload.client_pricing_signature
            ):
                # 409 with fresh quote for UI refresh
                raise HTTPException(
                    status_code=409,
                    detail={
                        "reason": "stale_or_tampered_quote",
                        "fresh_pricing": CheckoutQuoteResponse(
                            quote_id=uuid4(),
                            pricing=signed.snapshot,
                        ).model_dump(mode="json"),
                    },
                )

            server_total_minor = signed.snapshot.total_minor
            currency = signed.context.currency
            amount_minor_per_share = signed.context.amount_minor_per_share
            n = signed.context.recipients_count
            recipients_fp = signed.context.recipients_fp
            server_pricing_signature = signed.signature

            # ---- Stripe PI (idempotency includes signature/coupon to avoid collisions)
            stripe_client = self.get_stripe_client_for_request(request)
            idem_key = self._derive_idempotency_key(
                user_id=current_user_id,
                photobook_id=photobook_id,
                amount_total=server_total_minor,
                currency=currency,
                recipients_fingerprint=f"{recipients_fp}:{server_pricing_signature[-12:]}:{payload.coupon_code or ''}",
            )

            metadata = {
                "user_id": str(current_user_id),
                "photobook_id": str(photobook_id),
                "recipients_fp": recipients_fp,
                "purpose": "giftcard_grant",
                "pricing_sig_tail": server_pricing_signature[-16:],
                "coupon_code": (payload.coupon_code or ""),
            }
            description = self._build_pi_description(
                n_recipients=n,
                amount_per_share=amount_minor_per_share,
                currency=currency,
                photobook_id=photobook_id,
            )

            try:
                pi = await stripe_client.create_stripe_payment_intent_async(
                    amount=server_total_minor,
                    currency=currency,
                    description=description,
                    idempotency_key=idem_key,
                    metadata=metadata,
                )
            except Exception:
                raise HTTPException(
                    status_code=502,
                    detail="Unable to initialize payment with Stripe. Please try again.",
                )

            serialized_payload = req.serialize()

            # ---- Persist + event (+pricing snapshot)
            try:
                async with safe_transaction(
                    session, context="checkout initialize payment"
                ):
                    payment_row = await DALPayments.upsert_by_stripe_pi(
                        session,
                        DAOPaymentsCreate(
                            created_by_user_id=current_user_id,
                            photobook_id=photobook_id,
                            purpose=PaymentPurpose.GIFTCARD,
                            amount_total=server_total_minor,
                            currency=currency,
                            stripe_payment_intent_id=pi.stripe_payment_intent_id,
                            stripe_latest_charge_id=pi.latest_charge_id,
                            status=pi.status,
                            description=description,
                            idempotency_key=idem_key,
                            share_create_request=serialized_payload,
                            metadata_json={
                                "n_recipients": n,
                                "amount_per_share": amount_minor_per_share,
                                "brand_code": req.giftcard_request.brand_code,
                                "recipients_fp": recipients_fp,
                                "quote": {
                                    "lines": [
                                        li.model_dump(mode="json")
                                        for li in signed.snapshot.lines
                                    ],
                                    "subtotal_minor": signed.snapshot.subtotal_minor,
                                    "discount_minor": signed.snapshot.discount_minor,
                                    "fee_minor": signed.snapshot.fee_minor,
                                    "tax_minor": signed.snapshot.tax_minor,
                                    "total_minor": signed.snapshot.total_minor,
                                    "coupon": signed.snapshot.coupon.model_dump(
                                        mode="json"
                                    )
                                    if signed.snapshot.coupon
                                    else None,
                                    "pricing_config": signed.snapshot.pricing_config,
                                    "quote_id": str(payload.quote_id)
                                    if payload.quote_id
                                    else None,
                                    "server_pricing_signature": server_pricing_signature,
                                    "client_pricing_signature": payload.client_pricing_signature,
                                    "signature_verified": True,
                                },
                            },
                            refunded_amount=0,
                        ),
                    )

                    await DALPaymentEvents.create(
                        session,
                        DAOPaymentEventsCreate(
                            payment_id=payment_row.id,
                            stripe_event_id=None,
                            event_type="bootstrap.initialize",
                            stripe_event_type=None,
                            source=PaymentEventSource.SYSTEM,
                            payload={
                                "stripe_payment_intent_id": pi.stripe_payment_intent_id,
                                "idempotency_key": idem_key,
                                "status": pi.status.value,
                                "amount_total": server_total_minor,
                                "currency": currency,
                                "request_snapshot": serialized_payload,
                                "pricing_signature": server_pricing_signature,
                                "client_signature": payload.client_pricing_signature,
                                "signature_verified": True,
                            },
                            signature_verified=True,
                            applied_status=pi.status,
                        ),
                    )

                updated_photobook_resp = None
                async with safe_transaction(
                    session, context="rerender photobook", raise_on_fail=False
                ):
                    updated_photobook = await DALPhotobooks.get_by_id(
                        session,
                        photobook_id,
                    )
                    if updated_photobook:
                        updated_photobook_resp = (
                            await PhotobooksOverviewResponse.rendered_from_daos(
                                [updated_photobook],
                                session,
                                self.app.asset_manager,
                                requesting_user_id=current_user_id,
                            )
                        )[0]

                return CheckoutPaymentBootstrapResponse(
                    payment_id=payment_row.id,
                    stripe_payment_intent_id=pi.stripe_payment_intent_id,
                    client_secret=pi.client_secret,
                    status=pi.status,
                    amount_total=server_total_minor,
                    currency=currency,
                    idempotency_key=idem_key,
                    pricing_snapshot=signed.snapshot,
                    quote_id=payload.quote_id,
                    updated_photobook=updated_photobook_resp,
                )

            except Exception as db_exc:
                try:
                    await stripe_client.try_cancel_stripe_payment_intent_async(
                        stripe_payment_intent_id=pi.stripe_payment_intent_id
                    )
                except Exception:
                    pass
                logging.exception("[checkout] DB failure during initialize-payment")
                raise HTTPException(
                    status_code=500,
                    detail="Payment was initialized but failed to persist. Please retry.",
                ) from db_exc

    # -----------------------
    # Helpers
    # -----------------------

    def _build_pi_description(
        self,
        *,
        n_recipients: int,
        amount_per_share: int,
        currency: str,
        photobook_id: UUID,
    ) -> str:
        # Keep it short and deterministic (useful in dashboards)
        return (
            f"Giftcard x{n_recipients} · {amount_per_share / 100.0:.2f} {currency.upper()} each "
            f"(photobook {str(photobook_id)[:8]})"
        )

    def _derive_idempotency_key(
        self,
        *,
        user_id: UUID,
        photobook_id: UUID,
        amount_total: int,
        currency: str,
        recipients_fingerprint: str,
    ) -> str:
        """
        Stripe idempotency key (<=255 chars). Compose inputs, sha256, prefix for readability.
        """
        src = f"{user_id}|{photobook_id}|{amount_total}|{currency.lower()}|{recipients_fingerprint}"
        digest = hashlib.sha256(src.encode("utf-8")).hexdigest()
        return f"checkout:init:v1:{digest}"

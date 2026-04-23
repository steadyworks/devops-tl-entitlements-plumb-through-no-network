# backend/lib/pricing/pricer.py

import math
from uuid import UUID

from pydantic import BaseModel

from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    GiftcardGrantRequest,
    ShareCreateRequest,
)
from backend.lib.giftcard.brands.registry import BrandRegistryEntry

from .signer import PricingSigner
from .types import (
    CouponApplyResult,
    PricingSnapshot,
    QuoteLineItem,
    QuoteLineKind,
)
from .utils import fingerprint_share_request

# ---------- Strongly-typed containers (no tuples) ----------


class PricingContext(BaseModel):
    photobook_id: UUID
    recipients_fp: str
    currency: str
    brand_code: str
    brand_display_name: str
    amount_minor_per_share: int
    recipients_count: int
    pricing_config: str
    coupon_code: str | None = None


class PricingComputation(BaseModel):
    lines: list[QuoteLineItem]
    subtotal_minor: int
    discount_minor: int
    fee_minor: int
    tax_minor: int
    total_minor: int
    coupon: CouponApplyResult | None = None


class SignedPricing(BaseModel):
    context: PricingContext
    signature: str
    snapshot: PricingSnapshot


# ---------- Pricer ----------


class RequestPricer:
    """Single source of truth for pricing math, versioning, and signing."""

    QUOTE_TTL_MIN = 10

    def __init__(self) -> None:
        self._signer = PricingSigner()

    # Versioning / rollout knob (swap to flag/DB as needed)
    def _select_pricing_config(self) -> str:
        return "default"

    # Build a normalized context from request
    def _build_normalized_pricing_context(
        self,
        *,
        photobook_id: UUID,
        share_create_request: ShareCreateRequest,
        giftcard_request: GiftcardGrantRequest,
        brand: BrandRegistryEntry,
        coupon_code: str | None,
    ) -> PricingContext:
        currency = (giftcard_request.currency or "usd").lower().strip()
        amount_minor_per_share = int(giftcard_request.amount_per_share)
        brand_code = brand.brand_code
        n = len(share_create_request.recipients)
        recipients_fp = fingerprint_share_request(photobook_id, share_create_request)
        return PricingContext(
            photobook_id=photobook_id,
            recipients_fp=recipients_fp,
            currency=currency,
            brand_code=brand_code,
            brand_display_name=brand.display_name,
            amount_minor_per_share=amount_minor_per_share,
            recipients_count=n,
            pricing_config=self._select_pricing_config(),
            coupon_code=(coupon_code or None),
        )

    # Core pricing math (fees, coupon, tax) — DB/flag driven later
    async def compute(self, ctx: PricingContext) -> PricingComputation:
        amount_total_minor = ctx.amount_minor_per_share * ctx.recipients_count

        lines: list[QuoteLineItem] = [
            QuoteLineItem(
                kind=QuoteLineKind.GIFTCARD_SUBTOTAL,
                code="giftcard",
                description=f"{ctx.brand_display_name} Gift Card × {ctx.recipients_count}",
                amount_minor=amount_total_minor,
                metadata={
                    "brand_code": ctx.brand_code,
                    "amount_minor_per_share": ctx.amount_minor_per_share,
                    "count": ctx.recipients_count,
                },
            )
        ]

        # Processing fee (flat $3.50 USD by default)
        fee_minor = await self._compute_processing_fee_minor(
            currency=ctx.currency,
            amount_total_minor=amount_total_minor,
            brand_code=ctx.brand_code,
        )
        if fee_minor:
            lines.append(
                QuoteLineItem(
                    kind=QuoteLineKind.PROCESSING_FEE,
                    code="proc_fee_dynamic",
                    description="Processing Fee",
                    amount_minor=fee_minor,
                )
            )

        # Coupon
        coupon_result: CouponApplyResult | None = None
        if ctx.coupon_code:
            coupon_result = await self._apply_coupon(
                code=ctx.coupon_code,
                currency=ctx.currency,
                amount_total_minor=amount_total_minor,
                brand_code=ctx.brand_code,
                processing_fee_minor=fee_minor,
            )
            if coupon_result.accepted and (coupon_result.discount_minor or 0) != 0:
                lines.append(
                    QuoteLineItem(
                        kind=QuoteLineKind.COUPON_DISCOUNT,
                        code=f"coupon:{coupon_result.code}",
                        description=f"Coupon ({coupon_result.code})",
                        amount_minor=coupon_result.discount_minor,  # negative
                    )
                )

        # Tax (stub = 0)
        tax_minor = await self._compute_tax_minor(currency=ctx.currency, lines=lines)
        if tax_minor:
            lines.append(
                QuoteLineItem(
                    kind=QuoteLineKind.TAX,
                    code="tax",
                    description="Estimated tax",
                    amount_minor=tax_minor,
                )
            )

        subtotal = amount_total_minor
        discount = sum(li.amount_minor for li in lines if li.amount_minor < 0)
        fees = sum(
            li.amount_minor for li in lines if li.kind == QuoteLineKind.PROCESSING_FEE
        )
        taxes = sum(li.amount_minor for li in lines if li.kind == QuoteLineKind.TAX)
        total = sum(li.amount_minor for li in lines)

        return PricingComputation(
            lines=lines,
            subtotal_minor=subtotal,
            discount_minor=discount,
            fee_minor=fees,
            tax_minor=taxes,
            total_minor=total,
            coupon=coupon_result,
        )

    # Full signed snapshot (used by /quote and /initialize)
    async def prepare_signed_pricing(
        self,
        *,
        photobook_id: UUID,
        share_create_request: ShareCreateRequest,
        giftcard_request: GiftcardGrantRequest,
        brand: BrandRegistryEntry,
        coupon_code: str | None,
    ) -> SignedPricing:
        ctx = self._build_normalized_pricing_context(
            photobook_id=photobook_id,
            share_create_request=share_create_request,
            giftcard_request=giftcard_request,
            brand=brand,
            coupon_code=coupon_code,
        )
        comp = await self.compute(ctx)
        sig = self._signer.sign(
            self._signer.build_pricing_message(
                photobook_id=ctx.photobook_id,
                recipients_fingerprint=ctx.recipients_fp,
                giftcard_amount_per_share_minor=ctx.amount_minor_per_share,
                giftcard_currency=ctx.currency,
                giftcard_brand_code=brand.brand_code,
                coupon_code=ctx.coupon_code,
                pricing_config=ctx.pricing_config,
            )
        )
        snap = PricingSnapshot(
            currency=ctx.currency,
            lines=comp.lines,
            subtotal_minor=comp.subtotal_minor,
            discount_minor=comp.discount_minor,
            fee_minor=comp.fee_minor,
            tax_minor=comp.tax_minor,
            total_minor=comp.total_minor,
            coupon=comp.coupon,
            pricing_config=ctx.pricing_config,
            pricing_signature=sig,
        )
        return SignedPricing(context=ctx, signature=sig, snapshot=snap)

    # Verify a client-supplied signature against current canonical message
    def verify_signature(self, *, ctx: PricingContext, client_sig: str) -> bool:
        versioned_msg = self._signer.build_pricing_message(
            photobook_id=ctx.photobook_id,
            recipients_fingerprint=ctx.recipients_fp,
            giftcard_amount_per_share_minor=ctx.amount_minor_per_share,
            giftcard_currency=ctx.currency,
            giftcard_brand_code=ctx.brand_code,
            coupon_code=ctx.coupon_code,
            pricing_config=ctx.pricing_config,
        )
        return self._signer.verify(client_sig, versioned_msg)

    # ---- pluggable helpers----

    def _compute_stripe_cost_minor(self, amount_total_minor: int) -> int:
        """Stripe fees: 3% + $0.30, returned in minor units (rounded to nearest cent)."""
        amount = max(0.0, amount_total_minor / 100.0)
        stripe_fee = 0.0295 * amount + 0.30
        return int(round(stripe_fee * 100))

    def _round_up_to_charm(self, fee: float) -> float:
        """
        Monotone charm rounding:
        - If fee < $10: round UP to the next .49, then next .99 if needed.
        - If fee >= $10: round UP to the next .99.
        Guarantees no downward jumps when fee increases.
        """
        if fee < 10.0:
            fd = math.floor(fee)
            cand_49 = fd + 0.49
            if fee <= cand_49:
                return cand_49
            cand_99 = fd + 0.99
            if fee <= cand_99:
                return cand_99
            # go to next dollar .49
            return (fd + 1) + 0.49
        else:
            fd = math.floor(fee)
            cand_99 = fd + 0.99
            if fee <= cand_99:
                return cand_99
            # next dollar's .99
            return (fd + 1) + 0.99

    async def _compute_processing_fee_minor(
        self,
        *,
        currency: str,
        amount_total_minor: int,
        brand_code: str | None = None,
    ) -> int:
        """
        Tiered fee with monotone charm rounding:
        - Covers Stripe (3% + $0.30)
        - < $20 → fixed profit (~$1 after Stripe)
        - ≥ $20 → tiered % + base margin
        - Rounds UP to .49 / .99 (never down), ensuring monotone non-decreasing fees.
        """
        if currency.lower() != "usd":
            return 0

        amount = max(0.0, amount_total_minor / 100.0)  # dollars

        # Stripe baseline
        stripe_fee = 0.0295 * amount + 0.30
        fixed_profit = 0.75

        # Micro tier: fixed profit after Stripe
        if amount < 22:
            fee_dollars = stripe_fee + 1.00
        else:
            # Tiers (your current margins and anchors)
            if amount < 33:
                pct_margin, anchor_floor = 0.04, 1.49
            elif amount < 55:
                pct_margin, anchor_floor = 0.03, 1.99
            elif amount < 110:
                pct_margin, anchor_floor = 0.025, 2.49
            elif amount < 220:
                pct_margin, anchor_floor = 0.02, 3
            elif amount < 440:
                pct_margin, anchor_floor = 0.015, 3
            else:
                pct_margin, anchor_floor = 0.006, 3

            fee_raw = stripe_fee + (pct_margin * amount) + fixed_profit
            fee_dollars = max(fee_raw, anchor_floor)

        # **Monotone** behavioral rounding (ceil to charm)
        fee_dollars = self._round_up_to_charm(fee_dollars)

        return int(round(fee_dollars * 100))

    async def _apply_coupon(
        self,
        *,
        code: str,
        currency: str,
        amount_total_minor: int,
        brand_code: str,
        processing_fee_minor: int,
    ) -> CouponApplyResult:
        """
        FRIENDS25: waive *profit portion* of the processing fee.
        Customer still pays Stripe cost; your profit on fee → $0.

        Other examples remain:
        - PERCENT10: 10% off merchandise (subtotal)
        - FLAT500: $5 off (capped to merchandise)
        """
        normalized = (code or "").strip().upper()

        if amount_total_minor <= 0:
            return CouponApplyResult(
                code=normalized,
                accepted=False,
                reason="no_merchandise",
                discount_minor=0,
            )

        # 1) Profit waiver on fee (FRIENDS25)
        if normalized == "FRIENDS25":
            if currency.lower() != "usd":
                # Keep it simple for now; you can extend for other currencies later.
                return CouponApplyResult(
                    code=normalized,
                    accepted=False,
                    reason="unsupported_currency",
                    discount_minor=0,
                )
            stripe_only_minor = self._compute_stripe_cost_minor(amount_total_minor)
            # Profit portion of the fee (never negative)
            profit_portion_minor = max(0, processing_fee_minor - stripe_only_minor)
            if profit_portion_minor == 0:
                # Nothing to waive (e.g., your fee already equals Stripe fee)
                return CouponApplyResult(
                    code=normalized,
                    accepted=True,
                    reason="no_profit_to_waive",
                    discount_minor=0,
                )
            return CouponApplyResult(
                code=normalized,
                accepted=True,
                reason=None,
                discount_minor=-profit_portion_minor,  # negative line item
            )

        return CouponApplyResult(
            code=normalized,
            accepted=False,
            reason="invalid_coupon",
            discount_minor=0,
        )

    async def _compute_tax_minor(
        self, *, currency: str, lines: list[QuoteLineItem]
    ) -> int:
        return 0

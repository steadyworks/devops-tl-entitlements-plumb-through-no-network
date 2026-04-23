from enum import Enum
from typing import Any

from pydantic import BaseModel


class QuoteLineKind(str, Enum):
    GIFTCARD_SUBTOTAL = "giftcard_subtotal"
    PROCESSING_FEE = "processing_fee"
    COUPON_DISCOUNT = "coupon_discount"
    TAX = "tax"
    ROUNDING = "rounding"
    ADJUSTMENT = "adjustment"


class QuoteLineItem(BaseModel):
    kind: QuoteLineKind
    code: str  # e.g. "giftcard", "proc_fee_flat", "coupon:PROMO25"
    description: str  # human-readable
    amount_minor: int  # positive = charge, negative = discount
    metadata: dict[str, Any] | None = None


class CouponApplyResult(BaseModel):
    code: str
    accepted: bool
    reason: str | None = None  # e.g. "expired", "min_purchase_not_met"
    discount_minor: int  # negative value (e.g. -500)


class PricingSnapshot(BaseModel):
    currency: str
    lines: list[QuoteLineItem]
    subtotal_minor: int  # sum of item(s) you consider “merchandise”
    discount_minor: int  # sum of negative lines (<= 0)
    fee_minor: int  # sum of fees (>= 0)
    tax_minor: int  # taxes if applicable (>= 0)
    total_minor: int  # authoritative payable amount
    coupon: CouponApplyResult | None = None
    pricing_config: str | None = None
    pricing_signature: str  # HMAC over canonical pricing inputs

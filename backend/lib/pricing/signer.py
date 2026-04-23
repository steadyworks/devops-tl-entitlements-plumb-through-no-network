import base64
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from backend.env_loader import EnvLoader


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class PricingSigner:
    """Simple HMAC-SHA256 signer with optional fallback key for rotation."""

    def __init__(self) -> None:
        raw_primary = EnvLoader.get("PRICING_HMAC_KEY")
        self.key_primary = _b64url_decode(raw_primary)
        if len(self.key_primary) < 32:
            raise RuntimeError("Primary HMAC key too short; need ≥32 bytes")

        raw_alt = EnvLoader.get("PRICING_HMAC_KEY_ALT")
        self.key_alt = _b64url_decode(raw_alt) if raw_alt else None
        if self.key_alt and len(self.key_alt) < 32:
            raise RuntimeError("Alt HMAC key too short; need ≥32 bytes")

        # If alt == primary, ignore to avoid useless double-check
        if self.key_alt and self.key_alt == self.key_primary:
            self.key_alt = None

    def build_pricing_message(
        self,
        *,
        photobook_id: UUID,
        recipients_fingerprint: str,
        giftcard_amount_per_share_minor: int,
        giftcard_currency: str,
        giftcard_brand_code: str,
        coupon_code: str | None,
        pricing_config: str,
    ) -> bytes:
        canonical: dict[str, Any] = {
            "photobook_id": str(photobook_id),
            "recipients_fp": recipients_fingerprint,
            "amount_minor": int(giftcard_amount_per_share_minor),
            "currency": giftcard_currency.lower(),
            "brand_code": giftcard_brand_code,
            "coupon": (coupon_code or "").upper(),
            "pricing_config": pricing_config,
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def sign(self, message: bytes) -> str:
        # Always sign with PRIMARY (new signatures use the active key)
        mac = hmac.new(self.key_primary, message, hashlib.sha256).digest()
        return _b64url_encode(mac)

    def verify(self, signature: str, message: bytes) -> bool:
        try:
            sig_bytes = _b64url_decode(signature)
        except Exception:
            return False
        mac_primary = hmac.new(self.key_primary, message, hashlib.sha256).digest()
        if hmac.compare_digest(mac_primary, sig_bytes):
            return True
        if self.key_alt:
            mac_alt = hmac.new(self.key_alt, message, hashlib.sha256).digest()
            if hmac.compare_digest(mac_alt, sig_bytes):
                return True
        return False

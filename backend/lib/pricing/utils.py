# backend/route_handler/utils.py

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)

_MAX_STR = 512  # cap individual string fields to avoid gigantic payloads


def _safe_str(v: Any, *, max_len: int = _MAX_STR) -> str | None:
    if v is None:
        return None
    s = str(v)
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _json_dumps_deterministic(obj: Any) -> str:
    # Compact, deterministic JSON
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def fingerprint_share_request(photobook_id: UUID, req: ShareCreateRequest) -> str:
    """
    Generate a stable, collision-resistant fingerprint of the *semantic* share intent.
    This function is TOTAL: it never raises. On error, it falls back to a lossy digest
    that is still deterministic for the same inputs.

    Notes:
    - Bounds string sizes to avoid pathological memory usage.
    - Normalizes channel_type whether it's an Enum or already a string.
    """
    try:
        gc = req.giftcard_request
        canonical: dict[str, Any] = {
            "photobook_id": str(photobook_id),
            "scheduled_for": req.scheduled_for.isoformat()
            if req.scheduled_for
            else None,
            "giftcard": {
                "amount_per_share": gc.amount_per_share if gc else None,
                "currency": _safe_str((gc.currency.lower() if gc else None), max_len=16)
                if gc and gc.currency
                else None,
                "brand_code": _safe_str((gc.brand_code if gc else None), max_len=64),
            },
            "recipients": [],
        }

        # Deterministic recipients sort key (user_id first, then display name)
        rec_sorted = sorted(
            req.recipients,
            key=lambda r: (
                str(r.recipient_user_id) if r.recipient_user_id else "",
                r.recipient_display_name or "",
            ),
        )

        for r in rec_sorted:
            # Deterministic channels sort
            ch_sorted = sorted(
                r.channels,
                key=lambda c: (
                    str(getattr(c.channel_type, "value", c.channel_type)),
                    c.destination,
                ),
            )

            canonical_channels: list[dict[str, Any]] = []
            for c in ch_sorted:
                # Normalize channel_type to string
                ct = getattr(c.channel_type, "value", c.channel_type)
                canonical_channels.append(
                    {
                        "channel_type": _safe_str(ct, max_len=32),
                        "destination": _safe_str(c.destination, max_len=256),
                    }
                )

            canonical["recipients"].append(
                {
                    "recipient_user_id": str(r.recipient_user_id)
                    if r.recipient_user_id
                    else None,
                    "recipient_display_name": _safe_str(r.recipient_display_name),
                    "notes": _safe_str(r.notes),
                    "channels": canonical_channels,
                }
            )

        raw = _json_dumps_deterministic(canonical)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    except Exception:
        # Fallback: log and compute a *lossier* but deterministic digest
        logging.exception(
            "[checkout] fingerprint canonicalization failed; using fallback digest"
        )

        try:
            # Coarse, size-bounded fallback based on stable high-level signals
            fallback: dict[str, Any] = {
                "photobook_id": str(photobook_id),
                "n_recipients": len(req.recipients or []),
                "has_giftcard": bool(req.giftcard_request is not None),
                "giftcard_currency": _safe_str(
                    getattr(req.giftcard_request, "currency", None), max_len=16
                ),
                "amount_per_share": getattr(
                    req.giftcard_request, "amount_per_share", None
                ),
                # Heuristic identities: (user_id or display_name, and channel destinations only)
                "recipients_hint": [
                    {
                        "id": str(getattr(r, "recipient_user_id", None))
                        if getattr(r, "recipient_user_id", None)
                        else None,
                        "name": _safe_str(
                            getattr(r, "recipient_display_name", None), max_len=64
                        ),
                        "dests": [
                            _safe_str(getattr(c, "destination", ""), max_len=64)
                            for c in (getattr(r, "channels", []) or [])
                        ][:4],  # bound per-recipient channels considered
                    }
                    for r in (req.recipients or [])[
                        :20
                    ]  # bound number of recipients considered
                ],
            }
            raw = _json_dumps_deterministic(fallback)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            # Extremely defensive last resort: hash of photobook id only (still deterministic,
            # but idempotency becomes very coarse; better than throwing)
            logging.exception(
                "[checkout] fingerprint fallback failed; using photobook-only digest"
            )
            return hashlib.sha256(str(photobook_id).encode("utf-8")).hexdigest()

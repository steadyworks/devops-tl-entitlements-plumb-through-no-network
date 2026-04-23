from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALEntitlements,
    DALSubscriptionEvents,
    DAOEntitlements,
    DAOEntitlementsCreate,
    DAOEntitlementsUpdate,
    DAOSubscriptionEventsCreate,
    FilterOp,
)
from backend.db.data_models import (
    SubscriptionEventSource,
    SubscriptionStatus,
)
from backend.lib.utils.common import none_throws

# --------- Helpers & types ---------

UTC = timezone.utc
AWARE_MIN = datetime(1900, 1, 1, tzinfo=UTC)  # safe sentinel far in the past


def _ensure_aware_utc_optional(dt: datetime | None) -> datetime | None:
    """
    Normalize any datetime to tz-aware UTC.
    - None -> None
    - Naive -> assume UTC (common for legacy rows) and set tzinfo=UTC
    - Aware (any tz) -> convert to UTC
    """
    if dt is None:
        return None
    return _ensure_aware_utc(dt)


def _ensure_aware_utc(dt: datetime) -> datetime:
    """
    Normalize any datetime to tz-aware UTC.
    - None -> None
    - Naive -> assume UTC (common for legacy rows) and set tzinfo=UTC
    - Aware (any tz) -> convert to UTC
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    # Convert any non-UTC to UTC (handles rare cases)
    return dt.astimezone(UTC)


def _aware_or_min(dt: Optional[datetime]) -> datetime:
    return _ensure_aware_utc_optional(dt) or AWARE_MIN


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _ms_to_dt_optional(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    return _ms_to_dt(ms)


@dataclass(frozen=True)
class StatusApplyContext:
    """
    How we will audit the attempt to reconcile/apply RC state.
    """

    source: SubscriptionEventSource
    rc_event_type: str
    rc_event_id: Optional[str] = None
    signature_verified: Optional[bool] = None
    extra_payload: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class RCSubscriptionSnapshot:
    """
    Parsed, normalized view over RC webhook 'event'.
    """

    user_id: UUID
    product_id: str
    entitlement_id: Optional[str]
    event_type: str  # e.g. INITIAL_PURCHASE, RENEWAL, EXPIRATION
    event_id: Optional[str]
    event_timestamp_ms: Optional[int]
    purchased_at: Optional[datetime]
    expires_at: Optional[datetime]
    cancel_reason: Optional[str]


# --- Parsing & mapping ---------------------------------------------------------


def parse_rc_payload(
    payload: dict[str, Any],
) -> tuple[RCSubscriptionSnapshot, dict[str, Any]]:
    event: dict[str, Any] = (payload or {}).get("event", {})  # keep raw too

    # entitlement_ids (array) preferred over deprecated entitlement_id
    ent_ids: Optional[list[str]] = event.get("entitlement_ids")
    entitlement_id: Optional[str] = (
        ent_ids[0] if isinstance(ent_ids, list) and ent_ids else None
    )

    app_user_id = event.get("app_user_id")
    user_uuid = UUID(str(app_user_id))  # let caller catch if this fails

    snap = RCSubscriptionSnapshot(
        user_id=user_uuid,
        product_id=none_throws(event.get("product_id")),
        entitlement_id=entitlement_id,
        event_type=(event.get("type") or "").upper(),
        event_id=event.get("id"),
        event_timestamp_ms=event.get("event_timestamp_ms"),
        purchased_at=_ms_to_dt_optional(event.get("purchased_at_ms")),
        expires_at=_ms_to_dt_optional(event.get("expiration_at_ms")),
        cancel_reason=event.get("cancel_reason"),
    )
    return snap, event


def map_rc_event_to_status(
    event_type: str, cancel_reason: Optional[str]
) -> SubscriptionStatus:
    et = (event_type or "").upper()
    if et in {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"}:
        return SubscriptionStatus.ACTIVE
    if et == "BILLING_ISSUE":
        return SubscriptionStatus.BILLING_ISSUE
    if et == "CANCELLATION":
        # status is "cancelled" but access may last until expiration; we still reflect the lifecycle state
        return SubscriptionStatus.CANCELLED
    if et == "EXPIRATION":
        return SubscriptionStatus.EXPIRED
    # conservative default based on eventual access
    return SubscriptionStatus.ACTIVE


# --- FSM / advancement rules ---------------------------------------------------


@dataclass(frozen=True)
class ProposedEntitlement:
    active: bool
    expires_at: Optional[datetime]
    product_id: Optional[str]
    entitlement_id: Optional[str]
    applied_status: SubscriptionStatus


def _propose_entitlement_from_rc(snap: RCSubscriptionSnapshot) -> ProposedEntitlement:
    now: datetime = _ensure_aware_utc(_utcnow())
    exp: datetime | None = _ensure_aware_utc_optional(snap.expires_at)
    et = snap.event_type
    status = map_rc_event_to_status(et, snap.cancel_reason)

    if et in {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"}:
        return ProposedEntitlement(
            True, exp, snap.product_id, snap.entitlement_id, status
        )

    if et in {"BILLING_ISSUE", "CANCELLATION"}:
        return ProposedEntitlement(
            bool(exp and exp > now), exp, snap.product_id, snap.entitlement_id, status
        )

    if et == "EXPIRATION":
        return ProposedEntitlement(
            False, exp, snap.product_id, snap.entitlement_id, status
        )

    return ProposedEntitlement(
        bool(exp and exp > now), exp, snap.product_id, snap.entitlement_id, status
    )


# Precedence ranking to prevent regressions from out-of-order events.
_EVENT_PRECEDENCE: dict[str, int] = {
    # higher means stronger / more authoritative for current access window
    "RENEWAL": 100,
    "INITIAL_PURCHASE": 90,
    "UNCANCELLATION": 85,
    "PRODUCT_CHANGE": 80,
    "BILLING_ISSUE": 60,
    "CANCELLATION": 50,
    "EXPIRATION": 10,
}


def _precedence(evt_type: str) -> int:
    return _EVENT_PRECEDENCE.get(evt_type.upper(), 1)


def _should_advance_entitlement(
    current: Optional[DAOEntitlements],
    proposed: ProposedEntitlement,
    snap: RCSubscriptionSnapshot,
) -> bool:
    # ... (docstring unchanged)

    if current is None:
        return True

    cur_active = bool(current.active)

    # Normalize all datetimes we compare
    cur_expires = _ensure_aware_utc_optional(current.expires_at)
    prop_expires = _ensure_aware_utc_optional(proposed.expires_at)
    cur_updated = _ensure_aware_utc_optional(getattr(current, "updated_at", None))

    # 1) Prefer later expiration
    if (prop_expires or cur_expires) and _aware_or_min(prop_expires) > _aware_or_min(
        cur_expires
    ):
        return True

    # 2) Prefer ACTIVE if proposed isn’t expired
    if not cur_active and proposed.active:
        return True

    # 3) Event precedence (don’t shorten an already-later window)
    prop_prec = _precedence(snap.event_type)
    cur_prec = 0
    if prop_prec > cur_prec:
        if cur_expires and prop_expires and prop_expires < cur_expires and cur_active:
            return False
        return True

    # 4) Tiebreaker: event timestamp monotonicity vs current.updated_at (if present)
    if snap.event_timestamp_ms is not None:
        evt_ts = _ensure_aware_utc(_ms_to_dt(snap.event_timestamp_ms))
        # Only advance if we have no updated_at or this event is newer
        if evt_ts and (cur_updated is None or evt_ts > cur_updated):
            return True

    return False


# --- Public entrypoint (mirrors Stripe's reconcile_and_apply_* pattern) --------


async def reconcile_and_apply_subscription_status_in_txn(
    session: AsyncSession,
    *,
    user_id: UUID,
    snap: RCSubscriptionSnapshot,
    ctx: StatusApplyContext,
) -> Tuple[DAOEntitlements, SubscriptionStatus, bool]:
    """
    In one DB transaction:
      - select/create entitlement row for user
      - compute proposed snapshot from RC event
      - if advancement rules say yes, update entitlement (idempotent)
      - write a single audit event row recording applied_status and raw payload
    Returns: (fresh entitlement row, applied_status, did_advance)
    """
    if not session.in_transaction():
        raise RuntimeError(
            "[reconcile_and_apply_subscription_status_in_txn] must run inside an active transaction"
        )

    # Load current entitlement row; we keep a single row per user for "pro" (or first entitlement).
    ent_rows = await DALEntitlements.list_all(
        session,
        filters={"user_id": (FilterOp.EQ, user_id)},
        limit=1,
    )
    current = ent_rows[0] if ent_rows else None

    proposed = _propose_entitlement_from_rc(snap)
    applied_status = proposed.applied_status

    did_advance = _should_advance_entitlement(current, proposed, snap)

    if current is None:
        # create minimal row if missing, respecting proposal
        current = await DALEntitlements.create(
            session,
            DAOEntitlementsCreate(
                user_id=user_id,
                product_id=proposed.product_id or "",
                entitlement_id=proposed.entitlement_id,
                active=proposed.active,
                expires_at=proposed.expires_at,
            ),
        )
        did_advance = True
    elif did_advance:
        await DALEntitlements.update_by_id(
            session,
            current.id,
            DAOEntitlementsUpdate(
                product_id=proposed.product_id or current.product_id,
                entitlement_id=proposed.entitlement_id or current.entitlement_id,
                active=proposed.active,
                expires_at=proposed.expires_at,
                updated_at=_utcnow(),
            ),
        )
        # refresh
        refreshed = await DALEntitlements.get_by_id(session, current.id)
        assert refreshed is not None
        current = refreshed

    # Always append an audit event for the attempt (just like payments)
    await DALSubscriptionEvents.create(
        session,
        DAOSubscriptionEventsCreate(
            user_id=user_id,
            product_id=snap.product_id,
            entitlement_id=snap.entitlement_id,
            rc_event_id=snap.event_id,
            rc_event_type=snap.event_type,
            source=ctx.source,
            payload={
                "applied_status": applied_status.value,
                "proposed": {
                    "active": proposed.active,
                    "expires_at": proposed.expires_at.isoformat()
                    if proposed.expires_at
                    else None,
                    "product_id": proposed.product_id,
                    "entitlement_id": proposed.entitlement_id,
                },
                "current_after": {
                    "active": bool(current.active),
                    "expires_at": current.expires_at.isoformat()
                    if current.expires_at
                    else None,
                    "product_id": current.product_id,
                    "entitlement_id": current.entitlement_id,
                },
                **(ctx.extra_payload or {}),
            },
            signature_verified=ctx.signature_verified,
            applied_status=applied_status,
            event_timestamp_ms=snap.event_timestamp_ms,
        ),
    )

    return current, applied_status, did_advance

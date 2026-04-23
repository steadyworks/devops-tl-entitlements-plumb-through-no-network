from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import (
    DAOEntitlements,
    DAOSubscriptionEvents,
    SubscriptionEventSource,
    SubscriptionStatus,
)
from backend.lib.subscription.service import (
    RCSubscriptionSnapshot,
    StatusApplyContext,
    reconcile_and_apply_subscription_status_in_txn,
)

UTC = timezone.utc


def _ms(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def _snap(
    *,
    user_id: UUID,
    event_type: str,
    expires_at: datetime | None,
    product_id: str = "pro_yearly",
    entitlement_id: str | None = "pro",
    event_id: str | None = None,
    event_timestamp: datetime | None = None,
    cancel_reason: str | None = None,
) -> RCSubscriptionSnapshot:
    return RCSubscriptionSnapshot(
        user_id=user_id,
        product_id=product_id,
        entitlement_id=entitlement_id,
        event_type=event_type,
        event_id=event_id,
        event_timestamp_ms=_ms(event_timestamp or datetime.now(UTC)),
        purchased_at=None,
        expires_at=expires_at,
        cancel_reason=cancel_reason,
    )


def _ctx(
    *,
    et: str,
    rc_id: str | None = None,
    source: SubscriptionEventSource = SubscriptionEventSource.SYSTEM,
) -> StatusApplyContext:
    return StatusApplyContext(
        source=source,
        rc_event_type=et,
        rc_event_id=rc_id,
        signature_verified=True,
        extra_payload={"test": True},
    )


async def _fetch_ent(session: AsyncSession, user_id: UUID) -> DAOEntitlements | None:
    rows = (
        (
            await session.execute(
                select(DAOEntitlements).where(
                    getattr(DAOEntitlements, "user_id") == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return rows[0] if rows else None


async def _count(session: AsyncSession, model: Any) -> int:
    return len((await session.execute(select(model))).scalars().all())


@pytest.mark.asyncio
async def test_SF1_initial_purchase_creates_active_entitlement(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    exp = datetime.now(UTC) + timedelta(days=365)

    async with db_session.begin():
        ent_before = await _fetch_ent(db_session, user_id)
    assert ent_before is None

    async with db_session.begin():
        ent, status, advanced = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="INITIAL_PURCHASE",
                expires_at=exp,
                event_id="evt_1",
            ),
            ctx=_ctx(et="INITIAL_PURCHASE", rc_id="evt_1"),
        )

    assert advanced is True
    assert status == SubscriptionStatus.ACTIVE
    assert ent.active is True
    assert ent.expires_at == exp
    assert await _count(db_session, DAOSubscriptionEvents) == 1


@pytest.mark.asyncio
async def test_SF2_renewal_extends_expiration(db_session: AsyncSession) -> None:
    user_id = uuid4()
    exp1 = datetime.now(UTC) + timedelta(days=30)
    exp2 = exp1 + timedelta(days=30)

    # initial
    async with db_session.begin():
        await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="INITIAL_PURCHASE",
                expires_at=exp1,
                event_id="evt_a",
            ),
            ctx=_ctx(et="INITIAL_PURCHASE", rc_id="evt_a"),
        )
    # renewal with later expiration
    async with db_session.begin():
        ent, status, advanced = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id, event_type="RENEWAL", expires_at=exp2, event_id="evt_b"
            ),
            ctx=_ctx(et="RENEWAL", rc_id="evt_b"),
        )
    assert advanced is True
    assert status == SubscriptionStatus.ACTIVE
    assert ent.expires_at == exp2
    assert ent.active is True


@pytest.mark.asyncio
async def test_SF3_out_of_order_expiration_then_renewal_results_active(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    now = datetime.now(UTC)
    exp_old = now - timedelta(seconds=1)
    exp_new = now + timedelta(days=30)

    # 1) late EXPIRATION arrives first
    async with db_session.begin():
        ent1, status1, adv1 = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="EXPIRATION",
                expires_at=exp_old,
                event_id="evt_old",
            ),
            ctx=_ctx(et="EXPIRATION", rc_id="evt_old"),
        )
    assert ent1.active is False
    assert status1 == SubscriptionStatus.EXPIRED
    assert adv1 is True

    # 2) a newer RENEWAL with later expiry must win
    async with db_session.begin():
        ent2, status2, adv2 = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="RENEWAL",
                expires_at=exp_new,
                event_id="evt_new",
            ),
            ctx=_ctx(et="RENEWAL", rc_id="evt_new"),
        )
    assert adv2 is True
    assert status2 == SubscriptionStatus.ACTIVE
    assert ent2.active is True
    assert ent2.expires_at == exp_new


@pytest.mark.asyncio
async def test_SF4_late_expiration_should_not_regress_newer_active_state(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    exp_future = datetime.now(UTC) + timedelta(days=30)

    # Active from renewal
    async with db_session.begin():
        ent, status, _ = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="RENEWAL",
                expires_at=exp_future,
                event_id="evt_r",
            ),
            ctx=_ctx(et="RENEWAL", rc_id="evt_r"),
        )
    assert ent.active is True and status == SubscriptionStatus.ACTIVE

    # Out-of-order EXPIRATION with earlier expiry; should NOT advance
    async with db_session.begin():
        ent2, status2, advanced2 = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="EXPIRATION",
                expires_at=exp_future - timedelta(days=1),
                event_id="evt_e",
            ),
            ctx=_ctx(et="EXPIRATION", rc_id="evt_e"),
        )
    assert advanced2 is False
    assert status2 in (
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.EXPIRED,
    )  # applied_status reflects proposal, DB stays active
    assert ent2.active is True
    assert ent2.expires_at == exp_future


@pytest.mark.asyncio
async def test_SF5_cancellation_keeps_active_until_expiry_then_expiration_flips_inactive(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    exp_soon = datetime.now(UTC) + timedelta(minutes=5)

    # Cancellation sets "active until expires_at"
    async with db_session.begin():
        ent1, status1, _ = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="CANCELLATION",
                expires_at=exp_soon,
                event_id="evt_c",
            ),
            ctx=_ctx(et="CANCELLATION", rc_id="evt_c"),
        )
    assert status1 == SubscriptionStatus.CANCELLED
    assert ent1.active is True

    # Then EXPIRATION marks inactive
    async with db_session.begin():
        ent2, status2, _ = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="EXPIRATION",
                expires_at=exp_soon,
                event_id="evt_x",
            ),
            ctx=_ctx(et="EXPIRATION", rc_id="evt_x"),
        )
    assert status2 == SubscriptionStatus.EXPIRED
    assert ent2.active is False


@pytest.mark.asyncio
async def test_SF6_billing_issue_status_keeps_access_if_expiry_in_future(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    exp = datetime.now(UTC) + timedelta(days=7)

    async with db_session.begin():
        ent, status, _ = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="BILLING_ISSUE",
                expires_at=exp,
                event_id="evt_bi",
            ),
            ctx=_ctx(et="BILLING_ISSUE", rc_id="evt_bi"),
        )
    assert status == SubscriptionStatus.BILLING_ISSUE
    assert ent.active is True
    assert ent.expires_at == exp


@pytest.mark.asyncio
async def test_SF7_product_change_updates_product_and_stays_active(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    exp = datetime.now(UTC) + timedelta(days=90)

    # Start with baseline product
    async with db_session.begin():
        await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="INITIAL_PURCHASE",
                expires_at=exp,
                product_id="pro_monthly",
                event_id="evt_start",
            ),
            ctx=_ctx(et="INITIAL_PURCHASE", rc_id="evt_start"),
        )

    # Product change → switch to yearly
    async with db_session.begin():
        ent2, status2, adv2 = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="PRODUCT_CHANGE",
                expires_at=exp + timedelta(days=30),
                product_id="pro_yearly",
                event_id="evt_pc",
            ),
            ctx=_ctx(et="PRODUCT_CHANGE", rc_id="evt_pc"),
        )
    assert adv2 is True
    assert status2 == SubscriptionStatus.ACTIVE
    assert ent2.product_id == "pro_yearly"
    assert ent2.active is True


@pytest.mark.asyncio
async def test_SF8_recovery_after_expired_renewal_reactivates(
    db_session: AsyncSession,
) -> None:
    user_id = uuid4()
    now = datetime.now(UTC)
    exp_past = now - timedelta(days=1)
    exp_future = now + timedelta(days=29)

    # expired
    async with db_session.begin():
        await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="EXPIRATION",
                expires_at=exp_past,
                event_id="evt_exp",
            ),
            ctx=_ctx(et="EXPIRATION", rc_id="evt_exp"),
        )

    # later billing recovery → renewal
    async with db_session.begin():
        ent2, status2, adv2 = await reconcile_and_apply_subscription_status_in_txn(
            db_session,
            user_id=user_id,
            snap=_snap(
                user_id=user_id,
                event_type="RENEWAL",
                expires_at=exp_future,
                event_id="evt_rec",
            ),
            ctx=_ctx(et="RENEWAL", rc_id="evt_rec"),
        )
    assert adv2 is True
    assert status2 == SubscriptionStatus.ACTIVE
    assert ent2.active is True
    assert ent2.expires_at == exp_future

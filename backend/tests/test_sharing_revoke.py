# backend/tests/test_sharing_revoke.py

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShares,
    DAOUsers,
    ShareAccessPolicy,
    ShareChannelStatus,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.lib.sharing.service import (
    initialize_shares_and_channels_in_txn,
    revoke_share_in_txn,
)
from backend.lib.utils.common import utcnow

from .conftest import email_recipient

# -------------------------
# Small helpers
# -------------------------


async def _fetch_outbox(
    session: AsyncSession, outbox_id: UUID
) -> DAONotificationOutbox:
    row = (
        await session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    return row


async def _fetch_share(session: AsyncSession, share_id: UUID) -> DAOShares:
    row = (
        await session.execute(
            select(DAOShares).where(getattr(DAOShares, "id") == share_id)
        )
    ).scalar_one()
    return row


# -------------------------
# R1. Revoke cancels PENDING
# -------------------------


@pytest.mark.asyncio
async def test_R1_revoke_cancels_pending(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Create send-now (PENDING)
    req = ShareCreateRequest(
        recipients=[email_recipient("friend@example.com")],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id = resp.recipients[0].share_id
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    async with safe_transaction(db_session):
        ob_before = await _fetch_outbox(db_session, outbox_id)
        assert ob_before.status == ShareChannelStatus.PENDING

    # Revoke
    async with safe_transaction(db_session):
        revoke_resp = await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="no longer needed",
        )

    assert revoke_resp.share_id == share_id
    assert revoke_resp.photobook_id == photobook.id
    assert revoke_resp.canceled_outbox_count == 1
    assert revoke_resp.marked_cancel_intent_count == 0

    share_after = await _fetch_share(db_session, share_id)
    assert share_after.access_policy == ShareAccessPolicy.REVOKED
    assert share_after.revoked_by_user_id == owner_user.id
    assert share_after.revoked_at is not None
    assert share_after.revoked_reason == "no longer needed"

    ob_after = await _fetch_outbox(db_session, outbox_id)
    assert ob_after.status == ShareChannelStatus.CANCELED
    assert ob_after.canceled_at is not None
    assert ob_after.canceled_by_user_id == owner_user.id
    # claim fields cleared
    assert ob_after.dispatch_token is None
    assert ob_after.dispatch_worker_id is None
    assert ob_after.dispatch_claimed_at is None
    assert ob_after.dispatch_lease_expires_at is None


# -------------------------
# R2. Revoke cancels SCHEDULED
# -------------------------


@pytest.mark.asyncio
async def test_R2_revoke_cancels_scheduled(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    scheduled_for = utcnow() + timedelta(hours=2)
    req = ShareCreateRequest(
        recipients=[email_recipient("future@example.com")],
        sender_display_name="Owner",
        scheduled_for=scheduled_for,
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id = resp.recipients[0].share_id
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    async with safe_transaction(db_session):
        ob_before = await _fetch_outbox(db_session, outbox_id)
        assert ob_before.status == ShareChannelStatus.SCHEDULED

    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason=None,
        )

    async with safe_transaction(db_session):
        ob_after = await _fetch_outbox(db_session, outbox_id)
        assert ob_after.status == ShareChannelStatus.CANCELED
        assert ob_after.canceled_at is not None
        assert ob_after.canceled_by_user_id == owner_user.id


# -------------------------
# R3. Revoke cancels SENDING when lease expired
# -------------------------


@pytest.mark.asyncio
async def test_R3_revoke_cancels_sending_expired_lease(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    req = ShareCreateRequest(
        recipients=[email_recipient("send@example.com")],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id = resp.recipients[0].share_id
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Force SENDING with expired lease
    past = utcnow() - timedelta(minutes=10)
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=past,
            dispatch_lease_expires_at=past,  # expired
            dispatch_worker_id="w1",
        )
    )
    await db_session.commit()

    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="oops",
        )

    ob_after = await _fetch_outbox(db_session, outbox_id)
    assert ob_after.status == ShareChannelStatus.CANCELED
    assert ob_after.canceled_at is not None
    assert ob_after.canceled_by_user_id == owner_user.id
    # claim cleared
    assert ob_after.dispatch_token is None
    assert ob_after.dispatch_worker_id is None
    assert ob_after.dispatch_claimed_at is None
    assert ob_after.dispatch_lease_expires_at is None


# -------------------------
# R4. Revoke marks cancel intent for actively SENDING (lease active)
# -------------------------


@pytest.mark.asyncio
async def test_R4_revoke_marks_intent_for_active_sending(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    req = ShareCreateRequest(
        recipients=[email_recipient("active@example.com")],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id = resp.recipients[0].share_id
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    future = utcnow() + timedelta(minutes=10)
    now_ts = utcnow()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=now_ts,
            dispatch_lease_expires_at=future,  # still active
            dispatch_worker_id="w2",
        )
    )
    await db_session.commit()

    async with safe_transaction(db_session):
        resp_revoke = await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason=None,
        )

    assert resp_revoke.marked_cancel_intent_count >= 1

    ob_after = await _fetch_outbox(db_session, outbox_id)
    # status remains SENDING, but cancel intent is recorded
    assert ob_after.status == ShareChannelStatus.SENDING
    assert ob_after.canceled_at is not None
    assert ob_after.canceled_by_user_id == owner_user.id
    # claim remains for the worker to observe and bail
    assert ob_after.dispatch_worker_id == "w2"
    assert ob_after.dispatch_lease_expires_at == future


# -------------------------
# R5. Revoke is idempotent
# -------------------------


@pytest.mark.asyncio
async def test_R5_revoke_idempotent(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    req = ShareCreateRequest(
        recipients=[email_recipient("idem@example.com")],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id = resp.recipients[0].share_id

    # First revoke
    async with safe_transaction(db_session):
        r1 = await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="x",
        )
        # Second revoke should not error and should not increase canceled count further
        r2 = await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="x",
        )

    assert r1.share_id == r2.share_id
    assert r1.photobook_id == r2.photobook_id
    # After first call, outbox is canceled; second call should find nothing else to cancel.
    assert r2.canceled_outbox_count == 0
    # intent count also 0 on second time (nothing left SENDING with active lease)
    assert r2.marked_cancel_intent_count == 0

    # Verify share stays revoked
    share_after = await _fetch_share(db_session, share_id)
    assert share_after.access_policy == ShareAccessPolicy.REVOKED


@pytest.mark.asyncio
async def test_M6_revoke_cancels_or_marks_intent_based_on_lease(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    req: ShareCreateRequest = ShareCreateRequest(
        recipients=[email_recipient("r@example.com")], sender_display_name="Owner"
    )
    async with safe_transaction(db_session, "M6-a"):
        r = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    share_id: UUID = r.recipients[0].share_id
    ob_id: UUID = r.recipients[0].outbox_results[0].outbox_id

    # Make it SENDING with an *active* lease
    now = utcnow()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == ob_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=now,
            dispatch_lease_expires_at=now + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    async with safe_transaction(db_session, "M6-b"):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason=None,
        )

    # Row should still be SENDING but have cancel intent marked (canceled_at set)
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == ob_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.SENDING
    assert row.canceled_at is not None

    # Expire lease and revoke again → should fully cancel
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == ob_id)
        .values(dispatch_lease_expires_at=now - timedelta(minutes=1))
    )
    await db_session.commit()

    async with safe_transaction(db_session, "M6-c"):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason=None,
        )

    row2 = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == ob_id
            )
        )
    ).scalar_one()
    assert row2.status == ShareChannelStatus.CANCELED

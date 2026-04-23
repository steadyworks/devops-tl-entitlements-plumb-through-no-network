# tests/test_sharing_initialize.py

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShareChannels,
    DAOShares,
    DAOUsers,
    PhotobookStatus,
    ShareChannelStatus,
    ShareChannelType,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareChannelSpec,
    ShareCreateRequest,
    ShareRecipientSpec,
)
from backend.lib.sharing.service import (
    initialize_shares_and_channels_in_txn,
    revoke_share_in_txn,
)
from backend.lib.utils.common import utcnow

from .conftest import db_count, email_recipient

if TYPE_CHECKING:
    from uuid import UUID

# -------------------------
# A1. Create send-now
# -------------------------


@pytest.mark.asyncio
async def test_A1_create_send_now(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
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

    # shares: 1
    assert await db_count(db_session, DAOShares) == 1
    # share_channels: 1
    assert await db_count(db_session, DAOShareChannels) == 1
    # outbox: 1, status=PENDING
    assert await db_count(db_session, DAONotificationOutbox) == 1

    outbox_id = resp.recipients[0].outbox_results[0].outbox_id
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.PENDING
    assert row.scheduled_for is None
    assert row.created_by_user_id == owner_user.id


# -------------------------
# A2. Schedule future -> SCHEDULED
# -------------------------


@pytest.mark.asyncio
async def test_A2_schedule_future(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    scheduled_for = utcnow() + timedelta(hours=1)
    req = ShareCreateRequest(
        recipients=[email_recipient("friend@example.com")],
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

    outbox_id = resp.recipients[0].outbox_results[0].outbox_id
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()

    assert row.status == ShareChannelStatus.SCHEDULED
    assert row.scheduled_for == scheduled_for
    assert row.scheduled_by_user_id == owner_user.id
    assert row.last_scheduled_at is not None


# -------------------------
# A3. Idempotency key -> upsert (one row)
# -------------------------


@pytest.mark.asyncio
async def test_A3_idempotency_key_upsert(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    key = "idem-123"

    req1 = ShareCreateRequest(
        recipients=[email_recipient(email, idempotency_key=key)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req1,
        )
    ob1 = resp1.recipients[0].outbox_results[0].outbox_id

    # second call same channel + same idempotency key → should NOT create another row
    req2 = ShareCreateRequest(
        recipients=[email_recipient(email, idempotency_key=key)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req2,
        )
    ob2 = resp2.recipients[0].outbox_results[0].outbox_id

    assert ob1 == ob2  # same row
    # Ensure only one outbox row exists
    assert await db_count(db_session, DAONotificationOutbox) == 1


# -------------------------
# A4. No key: live outbox dedupe (pending/scheduled/sending)
# -------------------------


@pytest.mark.asyncio
async def test_A4_live_outbox_dedupe_without_key(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"

    req1 = ShareCreateRequest(
        recipients=[email_recipient(email)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req1,
        )
    ob1 = resp1.recipients[0].outbox_results[0].outbox_id

    # Call again WITHOUT idempotency key — should reuse the 'live' one (status=PENDING)
    req2 = ShareCreateRequest(
        recipients=[email_recipient(email)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req2,
        )
    ob2 = resp2.recipients[0].outbox_results[0].outbox_id

    assert ob2 == ob1
    assert await db_count(db_session, DAONotificationOutbox) == 1


# -------------------------
# A5. After terminal outbox -> new outbox next time
# -------------------------


@pytest.mark.asyncio
async def test_A5_after_terminal_status_inserts_new_outbox(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"

    # First time, create PENDING
    req1 = ShareCreateRequest(
        recipients=[email_recipient(email)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req1,
        )
    ob1 = resp1.recipients[0].outbox_results[0].outbox_id

    # Mark it SENT (terminal)
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == ob1)
        .values(status=ShareChannelStatus.SENT)
    )
    await db_session.commit()

    # Second call, no idempotency key — should create a NEW row now
    req2 = ShareCreateRequest(
        recipients=[email_recipient(email)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req2,
        )
    ob2 = resp2.recipients[0].outbox_results[0].outbox_id

    assert ob2 != ob1
    assert await db_count(db_session, DAONotificationOutbox) == 2


@pytest.mark.asyncio
async def test_M1_multiple_channels_create_multiple_outboxes(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    recipient: ShareRecipientSpec = ShareRecipientSpec(
        recipient_display_name="Friend",
        channels=[
            ShareChannelSpec(
                channel_type=ShareChannelType.EMAIL, destination="a@example.com"
            ),
            ShareChannelSpec(
                channel_type=ShareChannelType.SMS, destination="+15551230001"
            ),
        ],
    )
    req: ShareCreateRequest = ShareCreateRequest(
        recipients=[recipient],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session, "M1"):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )

    # 1 share, 2 channels, 2 outbox rows
    assert len(resp.recipients) == 1
    assert len(resp.recipients[0].share_channel_results) == 2
    assert len(resp.recipients[0].outbox_results) == 2

    # Both outboxes should be PENDING when send_now
    outbox_ids: list[UUID] = [ob.outbox_id for ob in resp.recipients[0].outbox_results]
    rows = (
        (
            await db_session.execute(
                select(DAONotificationOutbox).where(
                    getattr(DAONotificationOutbox, "id").in_(outbox_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(r.status == ShareChannelStatus.PENDING for r in rows)


@pytest.mark.asyncio
async def test_M2_recipient_user_id_upsert_unique_per_photobook(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Same recipient_user_id twice → upsert same share (unique index)
    recip: ShareRecipientSpec = ShareRecipientSpec(
        recipient_user_id=owner_user.id,  # just reuse owner id as a stand-in
        recipient_display_name="X",
        channels=[
            ShareChannelSpec(
                channel_type=ShareChannelType.EMAIL, destination="x@example.com"
            )
        ],
    )
    req: ShareCreateRequest = ShareCreateRequest(
        recipients=[recip], sender_display_name="Owner"
    )

    async with safe_transaction(db_session, "M2-a"):
        r1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    async with safe_transaction(db_session, "M2-b"):
        r2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )

    assert r1.recipients[0].share_id == r2.recipients[0].share_id
    # DB: one share total
    shares = (await db_session.execute(select(DAOShares))).scalars().all()
    assert len(shares) == 1


@pytest.mark.asyncio
async def test_M4_live_dedupe_when_existing_is_sending(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    # First call creates PENDING
    req: ShareCreateRequest = ShareCreateRequest(
        recipients=[email_recipient(email)],
        sender_display_name="Owner",
        scheduled_for=None,
    )
    async with safe_transaction(db_session, "M4-a"):
        r1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    ob1: UUID = r1.recipients[0].outbox_results[0].outbox_id

    # Flip to SENDING with an active lease to simulate in-flight
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == ob1)
        .values(status=ShareChannelStatus.SENDING)
    )
    await db_session.commit()

    # Second call: should reuse the live SENDING row (no duplicate)
    async with safe_transaction(db_session, "M4-b"):
        r2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    ob2: UUID = r2.recipients[0].outbox_results[0].outbox_id

    assert ob1 == ob2
    count = len(
        (await db_session.execute(select(DAONotificationOutbox))).scalars().all()
    )
    assert count == 1


@pytest.mark.asyncio
async def test_M5_status_recompute_shared_then_draft_after_revoke(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Initially status may be None; after share → SHARED
    req: ShareCreateRequest = ShareCreateRequest(
        recipients=[email_recipient("a@example.com")], sender_display_name="Owner"
    )
    async with safe_transaction(db_session, "M5-a"):
        r = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    pb = await db_session.get(DAOPhotobooks, photobook.id)
    assert pb is not None and pb.status == PhotobookStatus.SHARED

    # Revoke the only share → DRAFT
    share_id: UUID = r.recipients[0].share_id
    async with safe_transaction(db_session, "M5-b"):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="test",
        )
    pb2 = await db_session.get(DAOPhotobooks, photobook.id)
    assert pb2 is not None and pb2.status == PhotobookStatus.DRAFT

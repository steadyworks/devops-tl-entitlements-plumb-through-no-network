# backend/tests/test_idempotency_and_reclaimer.py

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOUsers,
    ShareChannelStatus,
    ShareChannelType,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareChannelSpec,
    ShareCreateRequest,
    ShareRecipientSpec,
)
from backend.lib.sharing.service import initialize_shares_and_channels_in_txn
from backend.lib.utils.common import utcnow

from .conftest import email_recipient


@pytest.mark.asyncio
async def test_I1_outbox_idempotency_key_merges_and_updates_status(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "idem@example.com"
    key = "k1"

    # initial scheduled
    async with safe_transaction(db_session):
        r1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    ShareRecipientSpec(
                        channels=[
                            ShareChannelSpec(
                                channel_type=ShareChannelType.EMAIL,
                                destination=email,
                                idempotency_key=key,
                            )
                        ],
                        recipient_display_name="A",
                    )
                ],
                sender_display_name="Owner",
                scheduled_for=utcnow() + timedelta(hours=1),
            ),
        )
    ob1 = r1.recipients[0].outbox_results[0].outbox_id

    async with safe_transaction(db_session):
        row1 = (
            await db_session.execute(
                select(DAONotificationOutbox).where(
                    getattr(DAONotificationOutbox, "id") == ob1
                )
            )
        ).scalar_one()

    assert row1.status == ShareChannelStatus.SCHEDULED

    # second call, send-now, same key -> update existing outbox
    async with safe_transaction(db_session):
        r2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    ShareRecipientSpec(
                        channels=[
                            ShareChannelSpec(
                                channel_type=ShareChannelType.EMAIL,
                                destination=email,
                                idempotency_key=key,
                            )
                        ],
                        recipient_display_name="A2",
                    )
                ],
                sender_display_name="Owner2",
                scheduled_for=None,
            ),
        )
    ob2 = r2.recipients[0].outbox_results[0].outbox_id
    assert ob2 == ob1  # same outbox row

    row2 = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == ob1
            )
        )
    ).scalar_one()
    # We reuse the *same* outbox row (idempotent merge), but we do not force a timing change here.
    # If the first call scheduled it, it can remain SCHEDULED; use the rescheduler to change timing.
    assert row2.status == ShareChannelStatus.SCHEDULED

    # Optional: prove we touched the row (idempotent UPDATE path)
    assert row2.updated_at >= row1.updated_at


# ------------------------------------------------------------
# I2: Idempotency must NOT resurrect terminal (SENT) rows
# ------------------------------------------------------------


@pytest.mark.asyncio
async def test_I2_idempotency_does_not_resurrect_terminal_sent(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    key = "idem-no-resurrect"
    email = "i2@example.com"

    # 1) Create outbox with idempotency key (send now or scheduled — doesn't matter)
    async with safe_transaction(db_session):
        r1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient(email, idempotency_key=key)],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    ob_id: UUID = r1.recipients[0].outbox_results[0].outbox_id

    async with safe_transaction(db_session):
        # Mark it SENT (terminal)
        await db_session.execute(
            update(DAONotificationOutbox)
            .where(getattr(DAONotificationOutbox, "id") == ob_id)
            .values(status=ShareChannelStatus.SENT)
        )

        # Snapshot for later comparison
        row_before = (
            await db_session.execute(
                select(DAONotificationOutbox).where(
                    getattr(DAONotificationOutbox, "id") == ob_id
                )
            )
        ).scalar_one()
        updated_at_before = row_before.updated_at

    # 2) Call initialize again with the SAME idempotency key, send-now
    #    (With the fix, ON CONFLICT should NOT update a terminal row)
    async with safe_transaction(db_session):
        _ = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient(email, idempotency_key=key)],
                sender_display_name="Owner2",
                scheduled_for=None,
            ),
        )

    async with safe_transaction(db_session):
        # 3) Verify the row is still SENT and was not mutated
        row_after = (
            await db_session.execute(
                select(DAONotificationOutbox).where(
                    getattr(DAONotificationOutbox, "id") == ob_id
                )
            )
        ).scalar_one()
    assert row_after.status == ShareChannelStatus.SENT
    # Defensive: ensure we didn't silently update timestamps on a terminal row
    assert row_after.updated_at == updated_at_before

    async with safe_transaction(db_session):
        # Also ensure no duplicate outbox rows exist for this channel+key
        rows_same_key = (
            (
                await db_session.execute(
                    select(DAONotificationOutbox).where(
                        getattr(DAONotificationOutbox, "share_channel_id")
                        == row_after.share_channel_id,
                        getattr(DAONotificationOutbox, "idempotency_key") == key,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows_same_key) == 1


# --------------------------------------------------------------------
# I3: Idempotency clears cancel/claim fields on non-terminal reuse
#     (row is SCHEDULED but has stray canceled/claim fields)
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_I3_idempotency_clears_cancel_and_claim_fields_on_update(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    key = "idem-clear-claim-cancel"
    email = "i3@example.com"

    # 1) Create as SCHEDULED (future) with idempotency key
    async with safe_transaction(db_session):
        r1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient(email, idempotency_key=key)],
                sender_display_name="Owner",
                scheduled_for=utcnow() + timedelta(hours=1),
            ),
        )
    ob_id = r1.recipients[0].outbox_results[0].outbox_id

    # 2) Manually put row into a "dirty" state while still non-terminal: SCHEDULED
    #    but with canceled_* and claim fields set. This simulates previous ops.
    now = utcnow()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == ob_id)
        .values(
            status=ShareChannelStatus.SCHEDULED,
            canceled_at=now,
            canceled_by_user_id=owner_user.id,
            dispatch_token=uuid4(),
            dispatch_worker_id="w",
            dispatch_claimed_at=now,
            dispatch_lease_expires_at=now + timedelta(minutes=5),
        )
    )
    await db_session.commit()

    # 3) Re-init with SAME key, send-now => should update the existing row to PENDING
    #    AND clear canceled/claim state (per the fix)
    async with safe_transaction(db_session):
        _ = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient(email, idempotency_key=key)],
                sender_display_name="Owner2",
                scheduled_for=None,  # send now
            ),
        )

    row_after = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == ob_id
            )
        )
    ).scalar_one()
    assert row_after.status == ShareChannelStatus.PENDING
    assert row_after.canceled_at is None
    assert row_after.canceled_by_user_id is None
    assert row_after.dispatch_token is None
    assert row_after.dispatch_worker_id is None
    assert row_after.dispatch_claimed_at is None
    assert row_after.dispatch_lease_expires_at is None

# backend/tests/test_scheduling.py
from datetime import timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShares,
    DAOUsers,
    ShareChannelStatus,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.lib.notifs.dispatch_service import claim_and_enqueue_one_outbox
from backend.lib.notifs.scheduling_service import reschedule_outbox_in_txn
from backend.lib.sharing.service import initialize_shares_and_channels_in_txn
from backend.lib.utils.common import utcnow

from .conftest import FakeJobManager, email_recipient


@pytest.mark.asyncio
async def test_B1_reschedule_future_from_pending(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # create send-now (PENDING)
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # reschedule to future
    target = utcnow() + timedelta(hours=2)
    async with safe_transaction(db_session):
        r = await reschedule_outbox_in_txn(
            session=db_session,
            outbox_id=outbox_id,
            user_id=owner_user.id,
            new_scheduled_for=target,
        )
    assert r.outbox_id == outbox_id
    assert r.status == ShareChannelStatus.SCHEDULED
    assert r.scheduled_for is not None

    # verify DB
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.SCHEDULED
    assert row.scheduled_for is not None
    assert row.scheduled_for.astimezone(timezone.utc) == target.astimezone(timezone.utc)
    assert row.scheduled_by_user_id == owner_user.id
    assert row.last_scheduled_at is not None
    assert row.dispatch_claimed_at is None
    assert row.dispatch_token is None


@pytest.mark.asyncio
async def test_B2_reschedule_to_now_makes_pending_due(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # start as SCHEDULED in the future
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

    # reschedule to NOW → becomes PENDING + due
    now_ts = utcnow()
    async with safe_transaction(db_session):
        r = await reschedule_outbox_in_txn(
            session=db_session,
            outbox_id=outbox_id,
            user_id=owner_user.id,
            new_scheduled_for=now_ts,
        )
    assert r.status == ShareChannelStatus.PENDING
    assert r.scheduled_for is not None  # your service sets scheduled_for=now for ASAP

    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.PENDING
    assert row.scheduled_for is not None
    assert row.scheduled_by_user_id == owner_user.id
    assert row.dispatch_claimed_at is None


@pytest.mark.asyncio
async def test_B3_reschedule_denied_if_inflight_claimed(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # create pending
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # simulate inflight: mark SENDING + claimed
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=utcnow(),
        )
    )
    await db_session.commit()

    with pytest.raises(RuntimeError, match="in-flight"):
        async with safe_transaction(db_session):
            await reschedule_outbox_in_txn(
                session=db_session,
                outbox_id=outbox_id,
                user_id=owner_user.id,
                new_scheduled_for=utcnow() + timedelta(minutes=5),
            )


@pytest.mark.asyncio
async def test_B4_reschedule_denied_if_terminal(
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # mark SENT
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(status=ShareChannelStatus.SENT)
    )
    await db_session.commit()

    with pytest.raises(RuntimeError, match="terminal"):
        async with safe_transaction(db_session):
            await reschedule_outbox_in_txn(
                session=db_session,
                outbox_id=outbox_id,
                user_id=owner_user.id,
                new_scheduled_for=utcnow() + timedelta(hours=1),
            )


@pytest.mark.asyncio
async def test_B5_reschedule_denied_if_share_revoked(
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # find the share row and revoke it
    outbox_row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    share_id = outbox_row.share_id

    await db_session.execute(
        update(DAOShares)
        .where(getattr(DAOShares, "id") == share_id)
        .values(access_policy="revoked")
    )
    await db_session.commit()

    with pytest.raises(RuntimeError, match="revoked"):
        async with safe_transaction(db_session):
            await reschedule_outbox_in_txn(
                session=db_session,
                outbox_id=outbox_id,
                user_id=owner_user.id,
                new_scheduled_for=utcnow() + timedelta(hours=2),
            )


@pytest.mark.asyncio
async def test_C1_send_now_reschedules_and_enqueues(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Start SCHEDULED in the future
    req = ShareCreateRequest(
        recipients=[email_recipient("friend@example.com")],
        sender_display_name="Owner",
        scheduled_for=utcnow() + timedelta(hours=1),
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
        outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Send now → reschedule to now (PENDING + due)
    async with safe_transaction(db_session):
        await reschedule_outbox_in_txn(
            session=db_session,
            outbox_id=outbox_id,
            user_id=owner_user.id,
            new_scheduled_for=utcnow(),
        )

    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-send-now",
        lease_seconds=600,
    )
    assert job_id is not None
    assert len(jm.enqueued) == 1

    # Row is claimed for delivery
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.SENDING
    assert row.dispatch_token is not None
    assert row.dispatch_claimed_at is not None
    assert row.dispatch_worker_id == "test-send-now"


@pytest.mark.asyncio
async def test_C2_claim_returns_none_when_not_due(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # SCHEDULED in the future
    req = ShareCreateRequest(
        recipients=[email_recipient("friend@example.com")],
        sender_display_name="Owner",
        scheduled_for=utcnow() + timedelta(hours=1),
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-worker",
        lease_seconds=600,
    )
    assert job_id is None  # not due yet
    assert len(jm.enqueued) == 0

    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.SCHEDULED
    assert row.dispatch_claimed_at is None


@pytest.mark.asyncio
async def test_C3_claim_returns_none_when_revoked(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # create pending (due)
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # revoke the parent share
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    share_id = row.share_id
    from sqlalchemy import update as sa_update

    from backend.db.data_models import (
        DAOShares,  # local import to avoid circulars in tests
    )

    await db_session.execute(
        sa_update(DAOShares)
        .where(getattr(DAOShares, "id") == share_id)
        .values(access_policy="revoked")
    )
    await db_session.commit()

    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-worker",
        lease_seconds=600,
    )
    assert job_id is None  # blocked by revoked share
    assert len(jm.enqueued) == 0

    # stays PENDING and unclaimed
    row2 = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row2.status == ShareChannelStatus.PENDING
    assert row2.dispatch_claimed_at is None


@pytest.mark.asyncio
async def test_C4_enqueue_failure_leaves_claimed_state(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # due PENDING
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
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # enqueue will raise; current implementation does NOT release claim (expected)
    jm = FakeJobManager(should_fail=True)

    with pytest.raises(RuntimeError, match="enqueue fail"):
        await claim_and_enqueue_one_outbox(
            session=db_session,
            job_manager=jm,
            outbox_id=outbox_id,
            user_id=owner_user.id,
            worker_id="test-worker",
            lease_seconds=600,
        )

    # verify row stayed claimed (SENDING) — a later reclaimer must handle it
    row = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert row.status == ShareChannelStatus.SENDING
    assert row.dispatch_token is not None
    assert row.dispatch_claimed_at is not None

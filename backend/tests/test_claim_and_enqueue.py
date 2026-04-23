# tests/test_claim_and_enqueue.py

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import (
    select,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    BackgroundType,
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShares,
    DAOUsers,
    FontStyle,
    ShareChannelStatus,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.lib.notifs.dispatch_service import (
    claim_and_enqueue_one_outbox,
    claim_and_enqueue_ready_batch,
)
from backend.lib.sharing.service import initialize_shares_and_channels_in_txn
from backend.lib.utils.common import utcnow
from backend.worker.job_processor.types import (
    DeliverNotificationInputPayload,
    JobType,
)

from .conftest import (
    FakeJobManager,
    FakeJobManagerBatch,
    async_fixture,
    email_recipient,
)

# -------------------------
# Seed helpers
# -------------------------


@async_fixture
async def owner_user(db_session: AsyncSession) -> DAOUsers:
    user = DAOUsers(id=uuid4(), email="owner@example.com", name="Owner")
    db_session.add(user)
    await db_session.commit()
    return user


@async_fixture
async def photobook(
    db_session: AsyncSession, owner_user: DAOUsers
) -> DAOPhotobooks:
    pb = DAOPhotobooks(
        id=uuid4(),
        title="Test Photobook",
        user_id=owner_user.id,
        status=None,
        background=BackgroundType.COLOR,
        status_last_edited_by=None,
        font=FontStyle.UNSPECIFIED,
    )
    db_session.add(pb)
    await db_session.commit()
    return pb


# -------------------------
# B. Claim & Enqueue (single)
# -------------------------


@pytest.mark.asyncio
async def test_B1_claim_and_enqueue_success(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # 1) Seed: create one PENDING, due-now outbox via initialize
    req = ShareCreateRequest(
        recipients=[email_recipient("friend@example.com")],
        sender_display_name="Owner",
        scheduled_for=None,  # due now
    )
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=req,
        )
        outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # 2) Claim + enqueue
    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-worker",
        lease_seconds=300,
    )
    assert job_id is not None

    # 3) DB assertions: SENDING + token + worker + claimed_at
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SENDING
    assert outbox.dispatch_token is not None
    assert outbox.dispatch_claimed_at is not None
    assert outbox.dispatch_worker_id == "test-worker"

    # 4) Enqueue payload correctness (expected_dispatch_token)
    assert len(jm.enqueued) == 1
    (jt, payload) = jm.enqueued[0]
    assert jt == JobType.REMOTE_DELIVER_NOTIFICATION
    assert isinstance(payload, DeliverNotificationInputPayload)
    assert payload.notification_outbox_id == outbox_id
    assert payload.expected_dispatch_token == outbox.dispatch_token
    assert payload.originating_photobook_id == outbox.photobook_id
    assert payload.user_id == owner_user.id


@pytest.mark.asyncio
async def test_B2_not_due_returns_none(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed a future-scheduled outbox
    req = ShareCreateRequest(
        recipients=[email_recipient("future@example.com")],
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
    )
    assert job_id is None

    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SCHEDULED
    assert outbox.dispatch_claimed_at is None
    assert outbox.dispatch_token is None
    assert len(jm.enqueued) == 0


@pytest.mark.asyncio
async def test_B3_already_claimed_returns_none(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed a due-now outbox
    req = ShareCreateRequest(
        recipients=[email_recipient("alreadyclaimed@example.com")],
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

    # Manually mark as already claimed
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=utcnow(),
            dispatch_token=uuid4(),
            dispatch_worker_id="someone-else",
        )
    )
    await db_session.commit()

    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-worker",
    )
    assert job_id is None
    assert len(jm.enqueued) == 0


@pytest.mark.asyncio
async def test_B4_revoked_share_cannot_be_claimed(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed due-now outbox
    req = ShareCreateRequest(
        recipients=[email_recipient("revoked@example.com")],
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

    # Find and revoke its share
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    await db_session.execute(
        update(DAOShares)
        .where(getattr(DAOShares, "id") == outbox.share_id)
        .values(
            access_policy="revoked"
        )  # enum cast via string ok in SQLAlchemy
    )
    await db_session.commit()

    jm = FakeJobManager()
    job_id = await claim_and_enqueue_one_outbox(
        session=db_session,
        job_manager=jm,
        outbox_id=outbox_id,
        user_id=owner_user.id,
        worker_id="test-worker",
    )
    assert job_id is None

    # Still unclaimed, still pending (or scheduled), not sending
    outbox_after = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox_after.dispatch_claimed_at is None
    assert outbox_after.status in (
        ShareChannelStatus.PENDING,
        ShareChannelStatus.SCHEDULED,
    )
    assert len(jm.enqueued) == 0


@pytest.mark.asyncio
async def test_B5_enqueue_failure_propagates_and_claim_is_kept(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # NOTE: This test reflects CURRENT behavior of claim function (no release-on-failure).
    # If you adopt the "release on enqueue failure" improvement later, flip the assertions below.

    # Seed due-now outbox
    req = ShareCreateRequest(
        recipients=[email_recipient("fail-enqueue@example.com")],
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

    jm = FakeJobManager(should_fail=True)

    with pytest.raises(RuntimeError, match="enqueue fail"):
        await claim_and_enqueue_one_outbox(
            session=db_session,
            job_manager=jm,
            outbox_id=outbox_id,
            user_id=owner_user.id,
            worker_id="test-worker",
        )

    # Current semantics: claim transaction committed; row remains SENDING with token
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SENDING
    assert outbox.dispatch_token is not None
    assert outbox.dispatch_claimed_at is not None


# -------------------------
# C. Batch claim & enqueue
# -------------------------


@pytest.mark.asyncio
async def test_C1_claim_ready_batch_respects_limit_and_due_only(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed: 3 due-now + 1 future-scheduled
    emails = [
        "a@example.com",
        "b@example.com",
        "c@example.com",
        "later@example.com",
    ]
    reqs = [
        ShareCreateRequest(
            recipients=[email_recipient(emails[i])],
            sender_display_name="Owner",
            scheduled_for=None if i < 3 else utcnow() + timedelta(hours=1),
        )
        for i in range(4)
    ]
    async with safe_transaction(db_session):
        for r in reqs:
            await initialize_shares_and_channels_in_txn(
                session=db_session,
                user_id=owner_user.id,
                photobook_id=photobook.id,
                req=r,
            )

    jm = FakeJobManagerBatch()
    job_ids = await claim_and_enqueue_ready_batch(
        session=db_session,
        job_manager=jm,
        user_id=owner_user.id,
        worker_id="batch-worker",
        limit=2,  # only pick two of the three due rows
    )
    assert len(job_ids) == 2
    assert len(jm.enqueued) == 2

    # Verify exactly 2 rows are SENDING (claimed), 1 still PENDING, and the future one SCHEDULED
    rows = (
        (await db_session.execute(select(DAONotificationOutbox)))
        .scalars()
        .all()
    )

    sending = [r for r in rows if r.status == ShareChannelStatus.SENDING]
    pending = [r for r in rows if r.status == ShareChannelStatus.PENDING]
    scheduled = [r for r in rows if r.status == ShareChannelStatus.SCHEDULED]

    assert len(sending) == 2
    assert len(pending) == 1
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_C2_batch_skips_already_claimed_rows(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed: 2 due-now
    async with safe_transaction(db_session):
        for email in ["x@example.com", "y@example.com"]:
            await initialize_shares_and_channels_in_txn(
                session=db_session,
                user_id=owner_user.id,
                photobook_id=photobook.id,
                req=ShareCreateRequest(
                    recipients=[email_recipient(email)],
                    sender_display_name="Owner",
                    scheduled_for=None,
                ),
            )

    # Manually pre-claim one outbox
    first = (
        (
            await db_session.execute(
                select(DAONotificationOutbox).order_by(
                    getattr(DAONotificationOutbox, "created_at").asc()
                )
            )
        )
        .scalars()
        .first()
    )
    assert first is not None
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == first.id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_claimed_at=utcnow(),
            dispatch_token=uuid4(),
            dispatch_worker_id="other-worker",
        )
    )
    await db_session.commit()

    jm = FakeJobManagerBatch()
    job_ids = await claim_and_enqueue_ready_batch(
        session=db_session,
        job_manager=jm,
        user_id=owner_user.id,
        worker_id="batch-worker",
        limit=10,
    )
    # Only the unclaimed one should be taken
    assert len(job_ids) == 1
    assert len(jm.enqueued) == 1


@pytest.mark.asyncio
async def test_C3_partial_enqueue_fail_releases_only_failed_claims(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed: 3 due-now
    async with safe_transaction(db_session):
        for email in ["p@example.com", "q@example.com", "r@example.com"]:
            await initialize_shares_and_channels_in_txn(
                session=db_session,
                user_id=owner_user.id,
                photobook_id=photobook.id,
                req=ShareCreateRequest(
                    recipients=[email_recipient(email)],
                    sender_display_name="Owner",
                    scheduled_for=None,
                ),
            )

    # Fail on the 2nd enqueue call
    jm = FakeJobManagerBatch(fail_on_index={2})
    job_ids = await claim_and_enqueue_ready_batch(
        session=db_session,
        job_manager=jm,
        user_id=owner_user.id,
        worker_id="batch-worker",
        limit=3,
    )
    # Two should succeed (1st and 3rd), middle fails and should be released
    assert len(job_ids) == 2
    # Re-fetch rows
    rows = (
        (await db_session.execute(select(DAONotificationOutbox)))
        .scalars()
        .all()
    )
    sending = [r for r in rows if r.status == ShareChannelStatus.SENDING]
    pending = [r for r in rows if r.status == ShareChannelStatus.PENDING]

    assert len(sending) == 2
    assert (
        len(pending) == 1
    )  # the failed one is released back to PENDING (token cleared)


@pytest.mark.asyncio
async def test_C4_revoked_are_never_claimed(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed a due-now row
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient("revoke_me@example.com")],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Revoke the share
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    await db_session.execute(
        update(DAOShares)
        .where(getattr(DAOShares, "id") == outbox.share_id)
        .values(access_policy="revoked")
    )
    await db_session.commit()

    jm = FakeJobManagerBatch()
    job_ids = await claim_and_enqueue_ready_batch(
        session=db_session,
        job_manager=jm,
        user_id=owner_user.id,
        worker_id="batch-worker",
        limit=10,
    )
    assert job_ids == []

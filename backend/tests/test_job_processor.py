# backend/tests/test_job_processor.py

from datetime import timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Optional, cast
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
    DAONotificationDeliveryAttempts,
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOUsers,
    NotificationDeliveryEvent,
    ShareChannelStatus,
    ShareChannelType,
    ShareProvider,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareChannelSpec,
    ShareCreateRequest,
    ShareRecipientSpec,
)
from backend.lib.notifs.email.types import EmailMessage, EmailSendResult
from backend.lib.sharing.service import initialize_shares_and_channels_in_txn
from backend.lib.types.asset import AssetStorageKey
from backend.lib.utils.common import utcnow
from backend.worker.job_processor.remote_deliver_notification import (
    RemoteDeliverNotificationJobProcessor,
)
from backend.worker.job_processor.types import (
    DeliverNotificationInputPayload,
)

if TYPE_CHECKING:
    from backend.db.session.factory import AsyncSessionFactory
    from backend.lib.asset_manager.base import AssetManager
    from backend.worker.process.types import (
        RemoteIOBoundWorkerProcessResources,
    )

from .conftest import (
    email_recipient,
)


class _DummyAssetManager:

    async def generate_signed_urls_batched(
        self, src_keys: list[AssetStorageKey], expires_in: int = 86_400
    ) -> dict[AssetStorageKey, str | Exception]:
        return {}


class _DummySessionFactory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def new_session(self) -> Any:
        s = self._session

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                return s

            async def __aexit__(
                self,
                exc_type: Optional[type[BaseException]],
                exc_val: Optional[BaseException],
                exc_tb: Optional[TracebackType],
            ) -> None:
                return None

        return _Ctx()


class _FakeEmailProviderClient:
    def get_share_provider(self) -> ShareProvider:
        return (
            ShareProvider.RESEND
        )  # import ShareProvider from your data_models

    async def send(self, msg: EmailMessage) -> EmailSendResult:
        return EmailSendResult(
            message_id="123",
            idempotency_key="456",
        )


class _DummyRemoteResources:
    def __init__(self, email_client: _FakeEmailProviderClient) -> None:
        self.email_provider_client = email_client


# -------------------------
# E. Processor behavior (ctor-friendly)
# -------------------------


@pytest.mark.asyncio
async def test_E1_email_success_marks_sent_and_logs_attempts(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed 1 email outbox (due-now)
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient("proc_success@example.com")],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Claim it (simulate dispatcher)
    token = uuid4()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_token=token,
            dispatch_claimed_at=utcnow(),
            dispatch_worker_id="proc",
        )
    )
    await db_session.commit()

    proc = RemoteDeliverNotificationJobProcessor(
        job_id=uuid4(),
        asset_manager=cast("AssetManager", _DummyAssetManager()),
        db_session_factory=cast(
            "AsyncSessionFactory", _DummySessionFactory(db_session)
        ),
        worker_process_resources=cast(
            "RemoteIOBoundWorkerProcessResources",
            _DummyRemoteResources(_FakeEmailProviderClient()),
        ),
    )

    payload = DeliverNotificationInputPayload(
        user_id=owner_user.id,
        originating_photobook_id=photobook.id,
        notification_outbox_id=outbox_id,
        expected_dispatch_token=token,
    )

    await proc.process(payload)

    # Outbox should be SENT with provider message id and cleared token
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SENT
    assert (
        outbox.last_provider_message_id == "123"
    )  # from EmailSendResult in processor
    assert outbox.provider == ShareProvider.RESEND
    assert outbox.dispatch_token is None

    # Attempts: PROCESSING + SENT
    attempts = (
        (
            await db_session.execute(
                select(DAONotificationDeliveryAttempts).where(
                    getattr(
                        DAONotificationDeliveryAttempts,
                        "notification_outbox_id",
                    )
                    == outbox_id
                )
            )
        )
        .scalars()
        .all()
    )
    events = [a.event for a in attempts]
    assert NotificationDeliveryEvent.PROCESSING in events
    assert NotificationDeliveryEvent.SENT in events
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_E2_wrong_token_noop(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient("proc_wrongtoken@example.com")],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Set token T1, but payload will carry T2
    token_db = uuid4()
    token_payload = uuid4()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_token=token_db,
            dispatch_claimed_at=utcnow(),
            dispatch_worker_id="proc",
        )
    )
    await db_session.commit()

    proc = RemoteDeliverNotificationJobProcessor(
        job_id=uuid4(),
        asset_manager=cast("AssetManager", _DummyAssetManager()),
        db_session_factory=cast(
            "AsyncSessionFactory", _DummySessionFactory(db_session)
        ),
        worker_process_resources=cast(
            "RemoteIOBoundWorkerProcessResources",
            _DummyRemoteResources(_FakeEmailProviderClient()),
        ),
    )

    payload = DeliverNotificationInputPayload(
        user_id=owner_user.id,
        originating_photobook_id=photobook.id,
        notification_outbox_id=outbox_id,
        expected_dispatch_token=token_payload,
    )
    await proc.process(payload)

    # Should remain SENDING with original token, and no attempts were written
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SENDING
    assert outbox.dispatch_token == token_db

    attempts = (
        (
            await db_session.execute(
                select(DAONotificationDeliveryAttempts).where(
                    getattr(
                        DAONotificationDeliveryAttempts,
                        "notification_outbox_id",
                    )
                    == outbox_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert attempts == []


@pytest.mark.asyncio
async def test_E3_lease_expired_noop(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed outbox
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient("lease_expired@example.com")],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id

    # Claim but set lease to past
    token = uuid4()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_token=token,
            dispatch_claimed_at=utcnow() - timedelta(hours=2),
            dispatch_lease_expires_at=utcnow() - timedelta(minutes=1),
            dispatch_worker_id="proc",
        )
    )
    await db_session.commit()

    proc = RemoteDeliverNotificationJobProcessor(
        job_id=uuid4(),
        asset_manager=cast("AssetManager", _DummyAssetManager()),
        db_session_factory=cast(
            "AsyncSessionFactory", _DummySessionFactory(db_session)
        ),
        worker_process_resources=cast(
            "RemoteIOBoundWorkerProcessResources",
            _DummyRemoteResources(_FakeEmailProviderClient()),
        ),
    )

    payload = DeliverNotificationInputPayload(
        user_id=owner_user.id,
        originating_photobook_id=photobook.id,
        notification_outbox_id=outbox_id,
        expected_dispatch_token=token,
    )
    await proc.process(payload)

    # No changes; still SENDING with same token; no attempts written
    outbox = (
        await db_session.execute(
            select(DAONotificationOutbox).where(
                getattr(DAONotificationOutbox, "id") == outbox_id
            )
        )
    ).scalar_one()
    assert outbox.status == ShareChannelStatus.SENDING
    assert outbox.dispatch_token == token
    attempts = (
        (
            await db_session.execute(
                select(DAONotificationDeliveryAttempts).where(
                    getattr(
                        DAONotificationDeliveryAttempts,
                        "notification_outbox_id",
                    )
                    == outbox_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert attempts == []


@pytest.mark.asyncio
async def test_E4_terminal_status_short_circuit(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    async with safe_transaction(db_session):
        resp = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[email_recipient("already_sent@example.com")],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    outbox_id = resp.recipients[0].outbox_results[0].outbox_id
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox_id)
        .values(status=ShareChannelStatus.SENT)
    )
    await db_session.commit()

    proc = RemoteDeliverNotificationJobProcessor(
        job_id=uuid4(),
        asset_manager=cast("AssetManager", _DummyAssetManager()),
        db_session_factory=cast(
            "AsyncSessionFactory", _DummySessionFactory(db_session)
        ),
        worker_process_resources=cast(
            "RemoteIOBoundWorkerProcessResources",
            _DummyRemoteResources(_FakeEmailProviderClient()),
        ),
    )

    payload = DeliverNotificationInputPayload(
        user_id=owner_user.id,
        originating_photobook_id=photobook.id,
        notification_outbox_id=outbox_id,
        expected_dispatch_token=uuid4(),
    )
    await proc.process(payload)

    # Still SENT, and no new attempts written
    attempts = (
        (
            await db_session.execute(
                select(DAONotificationDeliveryAttempts).where(
                    getattr(
                        DAONotificationDeliveryAttempts,
                        "notification_outbox_id",
                    )
                    == outbox_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert attempts == []


@pytest.mark.asyncio
async def test_E5_sms_raises_not_implemented_but_logs_processing_first(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed SMS channel
    async with safe_transaction(db_session):
        await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    ShareRecipientSpec(
                        channels=[
                            ShareChannelSpec(
                                channel_type=ShareChannelType.SMS,
                                destination="+15551234567",
                            )
                        ],
                        recipient_display_name="SMS Friend",
                    )
                ],
                sender_display_name="Owner",
                scheduled_for=None,
            ),
        )
    # Grab the outbox (only one)
    outbox = (
        (await db_session.execute(select(DAONotificationOutbox)))
        .scalars()
        .one()
    )
    # Claim it
    token = uuid4()
    await db_session.execute(
        update(DAONotificationOutbox)
        .where(getattr(DAONotificationOutbox, "id") == outbox.id)
        .values(
            status=ShareChannelStatus.SENDING,
            dispatch_token=token,
            dispatch_claimed_at=utcnow(),
            dispatch_worker_id="proc",
        )
    )
    await db_session.commit()

    proc = RemoteDeliverNotificationJobProcessor(
        job_id=uuid4(),
        asset_manager=cast("AssetManager", _DummyAssetManager()),
        db_session_factory=cast(
            "AsyncSessionFactory", _DummySessionFactory(db_session)
        ),
        worker_process_resources=cast(
            "RemoteIOBoundWorkerProcessResources",
            _DummyRemoteResources(_FakeEmailProviderClient()),
        ),
    )

    payload = DeliverNotificationInputPayload(
        user_id=owner_user.id,
        originating_photobook_id=photobook.id,
        notification_outbox_id=outbox.id,
        expected_dispatch_token=token,
    )
    with pytest.raises(NotImplementedError):
        await proc.process(payload)

    # PROCESSING attempt should exist even though channel isn't implemented
    attempts = (
        (
            await db_session.execute(
                select(DAONotificationDeliveryAttempts).where(
                    getattr(
                        DAONotificationDeliveryAttempts,
                        "notification_outbox_id",
                    )
                    == outbox.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].event == NotificationDeliveryEvent.PROCESSING

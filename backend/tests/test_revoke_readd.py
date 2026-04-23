# backend/tests/test_revoke_readd.py

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    BackgroundType,
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShareChannels,
    DAOShares,
    DAOUsers,
    FontStyle,
    ShareAccessPolicy,
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
from backend.lib.utils.common import none_throws

from .conftest import async_fixture

# -------------------------
# Local helpers
# -------------------------


def _recipient_with(
    email: str | None = None,
    sms: str | None = None,
    *,
    recipient_display_name: str = "Friend",
    notes: str | None = None,
) -> ShareRecipientSpec:
    channels: list[ShareChannelSpec] = []
    if email:
        channels.append(
            ShareChannelSpec(
                channel_type=ShareChannelType.EMAIL,
                destination=email,
            )
        )
    if sms:
        channels.append(
            ShareChannelSpec(
                channel_type=ShareChannelType.SMS,
                destination=sms,
            )
        )
    return ShareRecipientSpec(
        channels=channels,
        recipient_display_name=recipient_display_name,
        notes=notes,
    )


async def _list_outbox_for_share(
    session: AsyncSession, share_id: UUID
) -> list[DAONotificationOutbox]:
    rows = (
        (
            await session.execute(
                select(DAONotificationOutbox)
                .where(getattr(DAONotificationOutbox, "share_id") == share_id)
                .order_by(getattr(DAONotificationOutbox, "created_at").asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _get_share(session: AsyncSession, share_id: UUID) -> DAOShares:
    row = (
        await session.execute(
            select(DAOShares).where(getattr(DAOShares, "id") == share_id)
        )
    ).scalar_one()
    return row


async def _get_share_channel(
    session: AsyncSession,
    photobook_id: UUID,
    channel_type: ShareChannelType,
    destination: str,
) -> DAOShareChannels | None:
    sc = DAOShareChannels
    row = (
        await session.execute(
            select(sc)
            .where(
                getattr(sc, "photobook_id") == photobook_id,
                getattr(sc, "channel_type") == channel_type,
                getattr(sc, "destination") == destination,
                getattr(sc, "archived_at").is_(None),
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return row


# -------------------------
# Fixtures (uuid4 to avoid PK reuse)
# -------------------------


@async_fixture
async def owner_user(db_session: AsyncSession) -> DAOUsers:
    user = DAOUsers(id=uuid4(), email="owner@example.com", name="Owner")
    db_session.add(user)
    await db_session.commit()
    return user


@async_fixture
async def photobook(db_session: AsyncSession, owner_user: DAOUsers) -> DAOPhotobooks:
    pb = DAOPhotobooks(
        id=uuid4(),
        title="PB",
        user_id=owner_user.id,
        status=None,
        status_last_edited_by=None,
        background=BackgroundType.COLOR,
        font=FontStyle.UNSPECIFIED,
    )
    db_session.add(pb)
    await db_session.commit()
    return pb


# -------------------------
# R6. Revoke → add back ALL original channels
# -------------------------


@pytest.mark.asyncio
async def test_R6_revoke_then_add_back_all_channels_updates_metadata(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    phone = "+15555550101"

    # 1) Create initial share with EMAIL + SMS
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    _recipient_with(
                        email=email, sms=phone, recipient_display_name="A", notes="n1"
                    )
                ],
                sender_display_name="Owner V1",
                scheduled_for=None,
            ),
        )
        share_id = resp1.recipients[0].share_id

    # Sanity: two outbox rows (pending)
    async with safe_transaction(db_session):
        all_ob1 = await _list_outbox_for_share(db_session, share_id)
        assert len(all_ob1) == 2
        assert {o.status for o in all_ob1} == {ShareChannelStatus.PENDING}

    async with safe_transaction(db_session):
        # 2) Revoke the share
        r = await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="stop",
        )
        assert r.canceled_outbox_count == 2

    async with safe_transaction(db_session):
        # Confirm outboxes are canceled
        all_ob_after_revoke = await _list_outbox_for_share(db_session, share_id)
        assert {o.status for o in all_ob_after_revoke} == {ShareChannelStatus.CANCELED}

    # 3) Add back *all* original channels with updated metadata
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    _recipient_with(
                        email=email, sms=phone, recipient_display_name="B", notes="n2"
                    )
                ],
                sender_display_name="Owner V2",
                scheduled_for=None,
            ),
        )

    new_share_id = resp2.recipients[0].share_id
    assert new_share_id != share_id  # <-- CHANGED: new share epoch

    # Old share remains revoked
    old_share = await _get_share(db_session, share_id)
    assert old_share.access_policy == ShareAccessPolicy.REVOKED
    assert getattr(old_share, "revoked_at") is not None

    # New share is active and has updated metadata
    new_share = await _get_share(db_session, new_share_id)
    assert new_share.sender_display_name == "Owner V2"
    assert new_share.recipient_display_name == "B"
    assert new_share.notes == "n2"
    assert new_share.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
    assert getattr(new_share, "revoked_at") is None

    # Outboxes:
    # - old share has 2 canceled
    old_ob = await _list_outbox_for_share(db_session, share_id)
    assert len(old_ob) == 2 and {o.status for o in old_ob} == {
        ShareChannelStatus.CANCELED
    }

    # - new share has 2 pending
    new_ob = await _list_outbox_for_share(db_session, new_share_id)
    assert len(new_ob) == 2 and {o.status for o in new_ob} == {
        ShareChannelStatus.PENDING
    }

    # Active channels now point to the NEW share
    ch_email = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.EMAIL, email
    )
    ch_sms = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.SMS, phone
    )
    assert ch_email is not None and ch_sms is not None
    assert ch_email.photobook_share_id == new_share_id  # <-- CHANGED
    assert ch_sms.photobook_share_id == new_share_id  # <-- CHANGED

    # (Optional) verify archived versions exist pointing to the old share
    archived_email = (
        await db_session.execute(
            select(DAOShareChannels).where(
                getattr(DAOShareChannels, "photobook_id") == photobook.id,
                getattr(DAOShareChannels, "channel_type") == ShareChannelType.EMAIL,
                getattr(DAOShareChannels, "destination") == email,
                getattr(DAOShareChannels, "archived_at").is_not(None),
            )
        )
    ).scalar_one_or_none()
    assert archived_email is None


@pytest.mark.asyncio
async def test_R6A_readd_all_unarchives_channels_and_preserves_row_id(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    phone = "+15555550101"

    # seed
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
                                channel_type=ShareChannelType.EMAIL, destination=email
                            ),
                            ShareChannelSpec(
                                channel_type=ShareChannelType.SMS, destination=phone
                            ),
                        ],
                        recipient_display_name="A",
                    )
                ],
                sender_display_name="Owner V1",
                scheduled_for=None,
            ),
        )
    share1 = r1.recipients[0].share_id

    # capture channel ids
    async with safe_transaction(db_session):
        ch_email_before = none_throws(
            await _get_share_channel(
                session=db_session,
                photobook_id=photobook.id,
                channel_type=ShareChannelType.EMAIL,
                destination=email,
            )
        )
        ch_sms_before = none_throws(
            await _get_share_channel(
                session=db_session,
                photobook_id=photobook.id,
                channel_type=ShareChannelType.SMS,
                destination=phone,
            )
        )

    # revoke
    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share1,
            photobook_id=photobook.id,
            reason="stop",
        )

    # re-add SAME destinations
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
                                channel_type=ShareChannelType.EMAIL, destination=email
                            ),
                            ShareChannelSpec(
                                channel_type=ShareChannelType.SMS, destination=phone
                            ),
                        ],
                        recipient_display_name="B",
                    )
                ],
                sender_display_name="Owner V2",
                scheduled_for=None,
            ),
        )
    share2 = r2.recipients[0].share_id
    assert share2 != share1  # new share epoch

    async with safe_transaction(db_session):
        ch_email_after = none_throws(
            await _get_share_channel(
                session=db_session,
                photobook_id=photobook.id,
                channel_type=ShareChannelType.EMAIL,
                destination=email,
            )
        )
        ch_sms_after = none_throws(
            await _get_share_channel(
                session=db_session,
                photobook_id=photobook.id,
                channel_type=ShareChannelType.SMS,
                destination=phone,
            )
        )

    # same row ids reused, but repointed
    assert ch_email_after.id == ch_email_before.id
    assert ch_sms_after.id == ch_sms_before.id
    assert ch_email_after.photobook_share_id == share2
    assert ch_sms_after.photobook_share_id == share2


# -------------------------
# R7. Revoke → add back SUBSET of original channels
# -------------------------


@pytest.mark.asyncio
async def test_R7_revoke_then_add_back_subset_of_channels(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    phone = "+15555550101"

    # 1) Create initial share with EMAIL + SMS
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    _recipient_with(
                        email=email, sms=phone, recipient_display_name="A", notes="n1"
                    )
                ],
                sender_display_name="Owner V1",
                scheduled_for=None,
            ),
        )
        share_id = resp1.recipients[0].share_id

    # 2) Revoke
    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="stop",
        )

    # 3) Add back only EMAIL with updated metadata
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    _recipient_with(
                        email=email, sms=None, recipient_display_name="C", notes="n3"
                    )
                ],
                sender_display_name="Owner V3",
                scheduled_for=None,
            ),
        )

    # Share metadata updated AND auto-unrevoked
    new_share_id = resp2.recipients[0].share_id
    assert new_share_id != share_id  # <-- CHANGED

    # New share active + updated metadata
    new_share = await _get_share(db_session, new_share_id)
    assert new_share.sender_display_name == "Owner V3"
    assert new_share.recipient_display_name == "C"
    assert new_share.notes == "n3"
    assert new_share.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK

    # Old share remains revoked
    old_share = await _get_share(db_session, share_id)
    assert old_share.access_policy == ShareAccessPolicy.REVOKED

    # Outbox split: old=2 canceled, new=1 pending
    old_ob = await _list_outbox_for_share(db_session, share_id)
    new_ob = await _list_outbox_for_share(db_session, new_share_id)
    assert len([o for o in old_ob if o.status == ShareChannelStatus.CANCELED]) == 2
    assert len(new_ob) == 1 and new_ob[0].status == ShareChannelStatus.PENDING

    # Active email channel -> new share; SMS has no active channel record (only archived)
    ch_email = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.EMAIL, email
    )
    assert ch_email is not None and ch_email.photobook_share_id == new_share_id

    # Active SMS should not exist now (we added back only email)
    ch_sms_active = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.SMS, phone
    )
    assert ch_sms_active is None  # <-- CHANGED: only archived SMS exists

    # (Optional) check archived SMS points to old share
    archived_sms = (
        await db_session.execute(
            select(DAOShareChannels).where(
                getattr(DAOShareChannels, "photobook_id") == photobook.id,
                getattr(DAOShareChannels, "channel_type") == ShareChannelType.SMS,
                getattr(DAOShareChannels, "destination") == phone,
                getattr(DAOShareChannels, "archived_at").is_not(None),
            )
        )
    ).scalar_one_or_none()
    assert archived_sms is not None and archived_sms.photobook_share_id == share_id


@pytest.mark.asyncio
async def test_R7A_readd_subset_unarchives_only_requested_channel(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    email = "friend@example.com"
    phone = "+15555550101"

    # seed
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
                                channel_type=ShareChannelType.EMAIL, destination=email
                            ),
                            ShareChannelSpec(
                                channel_type=ShareChannelType.SMS, destination=phone
                            ),
                        ],
                        recipient_display_name="A",
                    )
                ],
                sender_display_name="Owner V1",
                scheduled_for=None,
            ),
        )
    share1 = r1.recipients[0].share_id

    async with safe_transaction(db_session):
        sc = DAOShareChannels
        ch_sms_before = (
            await db_session.execute(
                select(sc).where(
                    getattr(sc, "photobook_id") == photobook.id,
                    getattr(sc, "channel_type") == ShareChannelType.SMS,
                    getattr(sc, "destination") == phone,
                    getattr(sc, "archived_at").is_(None),
                )
            )
        ).scalar_one()

    # revoke
    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share1,
            photobook_id=photobook.id,
            reason="stop",
        )

    # re-add ONLY email
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
                                channel_type=ShareChannelType.EMAIL, destination=email
                            )
                        ],
                        recipient_display_name="C",
                    )
                ],
                sender_display_name="Owner V3",
                scheduled_for=None,
            ),
        )
    share2 = r2.recipients[0].share_id

    # email active, sms remains archived
    active_email = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.EMAIL, email
    )
    assert active_email is not None and active_email.photobook_share_id == share2

    active_sms = await _get_share_channel(
        db_session, photobook.id, ShareChannelType.SMS, phone
    )
    assert active_sms is None

    # sms archived row still exists and is the same row id as before
    archived_sms = (
        await db_session.execute(
            select(sc).where(
                getattr(sc, "photobook_id") == photobook.id,
                getattr(sc, "channel_type") == ShareChannelType.SMS,
                getattr(sc, "destination") == phone,
                getattr(sc, "archived_at").is_not(None),
            )
        )
    ).scalar_one()
    assert archived_sms.id == ch_sms_before.id


@pytest.mark.asyncio
async def test_R8_revoke_then_reinit_by_user_conflict_unrevokes_without_channels(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    target_user_id = uuid4()

    # 1) Create a share bound to recipient_user_id (no channels needed but include one to differ later)
    async with safe_transaction(db_session):
        resp1 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    ShareRecipientSpec(
                        recipient_user_id=target_user_id,
                        recipient_display_name="First",
                        channels=[],  # no channels initially is fine too
                    )
                ],
                sender_display_name="Owner V1",
                scheduled_for=None,
            ),
        )
        share_id = resp1.recipients[0].share_id

    # Revoke that share
    async with safe_transaction(db_session):
        await revoke_share_in_txn(
            session=db_session,
            actor_user_id=owner_user.id,
            share_id=share_id,
            photobook_id=photobook.id,
            reason="stop",
        )

    # 2) Re-init using the same recipient_user_id, *still with no channels* so we hit the conflict upsert path
    async with safe_transaction(db_session):
        resp2 = await initialize_shares_and_channels_in_txn(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            req=ShareCreateRequest(
                recipients=[
                    ShareRecipientSpec(
                        recipient_user_id=target_user_id,
                        recipient_display_name="Second",
                        channels=[],  # ensures we do not probe by channel
                    )
                ],
                sender_display_name="Owner V2",
                scheduled_for=None,
            ),
        )

    # Same share reused and un-revoked
    assert resp2.recipients[0].share_id == share_id
    share_after = await _get_share(db_session, share_id)
    assert share_after.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
    assert share_after.recipient_display_name == "Second"
    assert share_after.sender_display_name == "Owner V2"
    assert getattr(share_after, "revoked_at") is None
    assert getattr(share_after, "revoked_by_user_id") is None
    assert getattr(share_after, "revoked_reason") is None

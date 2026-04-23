# backend/tests/test_public_share.py

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.db.dal import safe_transaction
from backend.db.data_models import (
    DAOPhotobooks,
    DAOShares,
    DAOUsers,
    ShareAccessPolicy,
    ShareKind,
)
from backend.lib.sharing.service import ensure_public_share
from backend.lib.utils.common import utcnow

from .conftest import async_fixture

# ---------------------------------------------------------------------
# Ensure the partial unique index exists for these tests (session-scoped)
# ---------------------------------------------------------------------


@async_fixture(scope="session")
async def test__ensure_index_present(pg_engine: AsyncEngine) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_single_public_share_per_photobook
                ON shares (photobook_id) WHERE (kind = 'public');
            """)
        )


# Convenience: count shares for a photobook/kind
async def _count_shares(
    session: AsyncSession, *, photobook_id: UUID, kind: ShareKind
) -> int:
    s = DAOShares
    s_id = getattr(s, "id")
    s_pb = getattr(s, "photobook_id")
    s_kind = getattr(s, "kind")
    rows = await session.execute(
        select(s_id).where((s_pb == photobook_id) & (s_kind == kind))
    )
    return len(rows.scalars().all())


async def _fetch_public_share(
    session: AsyncSession, photobook_id: UUID
) -> DAOShares | None:
    s = DAOShares
    row = (
        await session.execute(
            select(s).where(
                getattr(s, "photobook_id") == photobook_id,
                getattr(s, "kind") == ShareKind.PUBLIC,
            )
        )
    ).scalar_one_or_none()
    return row


@pytest.mark.asyncio
async def test_P1_create_public_share_creates_one_row(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    share_id, slug = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
        sender_display_name="Owner",
        notes="hello",
    )
    await db_session.commit()

    # Validate
    s = DAOShares
    s_pb = getattr(s, "photobook_id")
    s_kind = getattr(s, "kind")

    row = (
        await db_session.execute(
            select(s).where((s_pb == photobook.id) & (s_kind == ShareKind.PUBLIC))
        )
    ).scalar_one()

    assert row.id == share_id
    assert row.share_slug == slug
    assert row.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
    assert row.sender_display_name == "Owner"
    assert row.notes == "hello"

    assert (
        await _count_shares(
            db_session, photobook_id=photobook.id, kind=ShareKind.PUBLIC
        )
        == 1
    )


@pytest.mark.asyncio
async def test_P2_idempotent_double_call_updates_fields_but_not_slug(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    first_id, first_slug = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
        sender_display_name="A",
        notes="first",
    )
    await db_session.commit()

    second_id, second_slug = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
        sender_display_name="B",  # should update
        notes="second",  # should update
    )
    await db_session.commit()

    assert first_id == second_id
    assert first_slug == second_slug
    assert (
        await _count_shares(
            db_session, photobook_id=photobook.id, kind=ShareKind.PUBLIC
        )
        == 1
    )

    s = DAOShares
    s_pb = getattr(s, "photobook_id")
    s_kind = getattr(s, "kind")

    row = (
        await db_session.execute(
            select(s).where((s_pb == photobook.id) & (s_kind == ShareKind.PUBLIC))
        )
    ).scalar_one()
    assert row.sender_display_name == "B"
    assert row.notes == "second"


@pytest.mark.asyncio
async def test_P3_concurrent_calls_create_exactly_one_public_share(
    pg_engine: AsyncEngine, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Two independent sessions to simulate concurrent callers
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

    async def _call(name: str) -> tuple[UUID, str]:
        async with Session() as s:
            sid, slug = await ensure_public_share(
                session=s,
                user_id=owner_user.id,
                photobook_id=photobook.id,
                sender_display_name=name,
                notes=f"note:{name}",
            )
            await s.commit()
            return sid, slug

    res1, res2 = await asyncio.gather(_call("C1"), _call("C2"))
    assert isinstance(res1[0], UUID) and isinstance(res2[0], UUID)
    # Both should refer to the same row
    assert res1[0] == res2[0]
    assert res1[1] == res2[1]

    # Verify exactly one public share exists
    async with Session() as check_s:
        count = await _count_shares(
            check_s, photobook_id=photobook.id, kind=ShareKind.PUBLIC
        )
        assert count == 1

        s = DAOShares
        s_pb = getattr(s, "photobook_id")
        s_kind = getattr(s, "kind")

        row = (
            await check_s.execute(
                select(s).where((s_pb == photobook.id) & (s_kind == ShareKind.PUBLIC))
            )
        ).scalar_one()
        assert (
            row.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
        )  # always normalized


@pytest.mark.asyncio
async def test_P4_revoked_public_is_restored_to_anyone_with_link_preserve_slug(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Create as normal
    sid, slug = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
        sender_display_name="Owner",
    )
    await db_session.commit()

    # Flip to revoked (simulate manual change)
    await db_session.execute(
        update(DAOShares)
        .where(getattr(DAOShares, "id") == sid)
        .values(access_policy=ShareAccessPolicy.REVOKED)
    )
    await db_session.commit()

    # Ensure again -> should restore to ANYONE_WITH_LINK; slug unchanged
    sid2, slug2 = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
        sender_display_name="Owner2",
    )
    await db_session.commit()

    assert sid2 == sid
    assert slug2 == slug

    row = (
        await db_session.execute(
            select(DAOShares).where(getattr(DAOShares, "id") == sid)
        )
    ).scalar_one()
    assert row.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK


@pytest.mark.asyncio
async def test_P5_does_not_affect_recipient_shares(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed a recipient share independently
    recipient_id = uuid4()
    now = utcnow()

    await db_session.execute(
        insert(DAOShares).values(
            id=recipient_id,
            photobook_id=photobook.id,
            created_by_user_id=owner_user.id,
            kind=ShareKind.RECIPIENT,
            recipient_display_name="Friend",
            recipient_user_id=None,
            share_slug="dummy-slug",
            access_policy=ShareAccessPolicy.ANYONE_WITH_LINK,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    # Ensure public share
    _, _ = await ensure_public_share(
        session=db_session,
        user_id=owner_user.id,
        photobook_id=photobook.id,
    )
    await db_session.commit()

    # Verify recipient share still exists and is untouched
    row_recipient = (
        await db_session.execute(
            select(DAOShares).where(getattr(DAOShares, "id") == recipient_id)
        )
    ).scalar_one()
    assert row_recipient.kind == ShareKind.RECIPIENT

    # Verify a single PUBLIC share exists as well
    count_public = await _count_shares(
        db_session, photobook_id=photobook.id, kind=ShareKind.PUBLIC
    )
    assert count_public == 1


@pytest.mark.asyncio
async def test_P1_first_call_creates_public_anyone_with_link(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    async with safe_transaction(db_session):
        share_id, slug = await ensure_public_share(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            sender_display_name="Owner",
            notes="hello",
        )
    assert share_id is not None and isinstance(slug, str) and len(slug) > 0

    pub = await _fetch_public_share(db_session, photobook.id)
    assert pub is not None
    assert pub.id == share_id
    assert pub.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
    assert pub.kind == ShareKind.PUBLIC
    assert pub.sender_display_name == "Owner"
    assert pub.notes == "hello"


@pytest.mark.asyncio
async def test_P2_idempotent_same_id_and_slug(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    async with safe_transaction(db_session):
        share_id1, slug1 = await ensure_public_share(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            sender_display_name="Owner A",
            notes="first",
        )
    async with safe_transaction(db_session):
        share_id2, slug2 = await ensure_public_share(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            sender_display_name="Owner B",  # should update metadata but keep same row
            notes="second",
        )
    assert share_id1 == share_id2
    assert slug1 == slug2

    pub = await _fetch_public_share(db_session, photobook.id)
    assert pub is not None
    assert pub.id == share_id1
    assert pub.share_slug == slug1
    # metadata updated
    assert pub.sender_display_name == "Owner B"
    assert pub.notes == "second"
    assert pub.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK


@pytest.mark.asyncio
async def test_P3_revoked_public_then_ensure_restores_anyone_with_link_and_clears_revoked(
    db_session: AsyncSession, owner_user: DAOUsers, photobook: DAOPhotobooks
) -> None:
    # Seed
    async with safe_transaction(db_session):
        share_id, _ = await ensure_public_share(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            sender_display_name="Owner",
            notes=None,
        )

    # Force revoke at DB level to simulate prior state
    s = DAOShares
    await db_session.execute(
        update(s)
        .where(getattr(s, "id") == share_id)
        .values(
            access_policy=ShareAccessPolicy.REVOKED,
            revoked_reason="manual",
        )
    )
    await db_session.commit()

    # Ensure again → should un-revoke + keep same row
    async with safe_transaction(db_session):
        share_id2, _ = await ensure_public_share(
            session=db_session,
            user_id=owner_user.id,
            photobook_id=photobook.id,
            sender_display_name="Owner2",
            notes="restored",
        )
    assert share_id2 == share_id

    pub = await _fetch_public_share(db_session, photobook.id)
    assert pub is not None
    assert pub.id == share_id
    assert pub.access_policy == ShareAccessPolicy.ANYONE_WITH_LINK
    assert pub.sender_display_name == "Owner2"
    assert pub.notes == "restored"
    assert getattr(pub, "revoked_at") is None
    assert getattr(pub, "revoked_by_user_id") is None
    assert getattr(pub, "revoked_reason") is None

# backend/tests/conftest.py

import os
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Optional,
    Protocol,
    TypeVar,
    cast,
    overload,
)
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import (
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from backend.db.data_models import (
    BackgroundType,
    DAOPhotobooks,
    DAOUsers,
    FontStyle,
    ShareChannelType,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareChannelSpec,
    ShareRecipientSpec,
)
from backend.worker.job_processor.types import (
    JobInputPayload,
    JobType,
)

F = TypeVar("F", bound=Callable[..., object])


class _AsyncFixtureDecorator(Protocol):
    @overload
    def __call__(self, func: F, /) -> F: ...
    @overload
    def __call__(
        self,
        *,
        scope: str | None = ...,
        autouse: bool | None = ...,
        name: str | None = ...,
    ) -> Callable[[F], F]: ...


# Tell the type checker that pytest_asyncio.fixture matches our decorator protocol
async_fixture = cast("_AsyncFixtureDecorator", pytest_asyncio.fixture)


@async_fixture(scope="session")
async def pg_engine() -> AsyncGenerator[AsyncEngine, None]:
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip(
            "Set TEST_DATABASE_URL=postgresql+asyncpg://... to run PG integration tests without Docker"
        )

    engine = create_async_engine(db_url, echo=False, future=True)

    async with engine.begin() as conn:
        # optional: make sure pgcrypto is available (safe if extension is missing)
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
        except Exception:
            # not fatal for tests since SQLModel defaults use uuid4()
            pass

        # clean slate for the test database
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

        # production-expected unique indexes used by our logic
        await conn.execute(
            text(
                """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_recipient_share_by_user
            ON shares (photobook_id, recipient_user_id)
            WHERE (kind = 'recipient' AND recipient_user_id IS NOT NULL);
        """
            )
        )

        await conn.execute(
            text(
                """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_single_public_share_per_photobook
            ON shares (photobook_id) WHERE (kind = 'public'::public.share_kind);
            """
            )
        )

        await conn.execute(
            text(
                """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_share_channel_dest_per_photobook
            ON share_channels (photobook_id, channel_type, destination);
        """
            )
        )

        await conn.execute(
            text(
                """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_idempotency
            ON notification_outbox (share_channel_id, notification_type, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
            )
        )

        await conn.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public' AND indexname = 'shares_share_slug_key'
                ) THEN
                    CREATE UNIQUE INDEX shares_share_slug_key ON shares (share_slug);
                END IF;
            END $$;
        """
            )
        )

        # Ensure ON CONFLICT works for payments.upsert_by_stripe_pi
        await conn.execute(
            text("""
            -- if a legacy table-level constraint exists in this DB, drop it (harmless if missing)
            DO $$
            BEGIN
            IF EXISTS (
                SELECT 1
                FROM   pg_constraint
                WHERE  conname = 'payments_stripe_payment_intent_id_key'
                AND conrelid = 'public.payments'::regclass
            ) THEN
                ALTER TABLE public.payments
                DROP CONSTRAINT payments_stripe_payment_intent_id_key;
            END IF;
            END $$;

            -- what the DAL expects (works with ON CONFLICT (stripe_payment_intent_id))
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_stripe_payment_intent_id_unique
            ON public.payments (stripe_payment_intent_id);
            """)
        )

        # Optional: assert it really exists (fail fast if migrations drift)
        await conn.execute(
            text("""
            DO $$
            BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'public'
                AND indexname = 'idx_payments_stripe_payment_intent_id_unique'
            ) THEN
                RAISE EXCEPTION 'missing idx_payments_stripe_payment_intent_id_unique';
            END IF;
            END $$;
            """)
        )

        await conn.run_sync(SQLModel.metadata.create_all)

        # Ensure the session defaults to UTC for deterministic tests
        await conn.execute(text("SET TIME ZONE 'UTC'"))

        # Make the outbox timestamps tz-aware like prod
        await conn.execute(
            text(
                """
            ALTER TABLE notification_outbox
            ALTER COLUMN scheduled_for TYPE timestamptz USING scheduled_for AT TIME ZONE 'UTC',
            ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'UTC',
            ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'UTC',
            ALTER COLUMN dispatch_claimed_at TYPE timestamptz USING dispatch_claimed_at AT TIME ZONE 'UTC',
            ALTER COLUMN dispatch_lease_expires_at TYPE timestamptz USING dispatch_lease_expires_at AT TIME ZONE 'UTC',
            ALTER COLUMN canceled_at TYPE timestamptz USING canceled_at AT TIME ZONE 'UTC',
            ALTER COLUMN last_scheduled_at TYPE timestamptz USING last_scheduled_at AT TIME ZONE 'UTC';
        """
            )
        )

        # (Optional) if your tests ever assert share/channel timestamps too:
        await conn.execute(
            text(
                """
            ALTER TABLE shares
            ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'UTC',
            ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'UTC';
        """
            )
        )
        await conn.execute(
            text(
                """
            ALTER TABLE share_channels
            ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'UTC',
            ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'UTC';
        """
            )
        )

        await conn.execute(text("SET TIME ZONE 'UTC'"))

        await conn.execute(
            text(
                """
            DO $$
            BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public'
                AND indexname = 'uq_single_public_share_per_photobook'
            ) THEN
                RAISE EXCEPTION 'missing uq_single_public_share_per_photobook';
            END IF;
            END $$;
            """
            )
        )

    try:
        yield engine
    finally:
        await engine.dispose()


@async_fixture(scope="function")
async def db_session(
    pg_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@async_fixture(autouse=True)
async def clean_share_tables(db_session: AsyncSession) -> None:
    # Order matters due to FKs; TRUNCATE … CASCADE is simplest/fastest.
    await db_session.execute(
        text(
            """
        TRUNCATE
            notification_delivery_attempts,
            notification_outbox,
            share_channels,
            shares,
            payment_events,
            payments
        RESTART IDENTITY CASCADE
        """
        )
    )
    await db_session.commit()


@pytest.fixture(autouse=True)
async def clean_subscription_tables(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("""
        TRUNCATE
            subscription_events,
            entitlements
        RESTART IDENTITY CASCADE
        """)
    )
    await db_session.commit()


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
async def photobook(db_session: AsyncSession, owner_user: DAOUsers) -> DAOPhotobooks:
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
# Test utilities
# -------------------------


def email_recipient(
    email: str, *, idempotency_key: str | None = None
) -> ShareRecipientSpec:
    return ShareRecipientSpec(
        channels=[
            ShareChannelSpec(
                channel_type=ShareChannelType.EMAIL,
                destination=email,
                idempotency_key=idempotency_key,
            )
        ],
        recipient_display_name="Friend",
    )


async def db_count(session: AsyncSession, model: Any) -> int:
    res = await session.execute(select(model))
    return len(res.scalars().all())


class FakeJobManager:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.enqueued: list[tuple[JobType, JobInputPayload]] = []

    async def enqueue(
        self,
        job_type: JobType,
        job_payload: JobInputPayload,
        max_retries: int,
        db_session: AsyncSession,
    ) -> UUID:
        if self.should_fail:
            raise RuntimeError("enqueue fail (test)")
        self.enqueued.append((job_type, job_payload))
        return uuid4()

    async def poll(self, timeout: int) -> Optional[UUID]:
        return None

    async def claim(
        self, job_id: UUID, db_session: AsyncSession
    ) -> tuple[JobType, JobInputPayload]:
        raise NotImplementedError


class FakeJobManagerBatch:
    """Deterministic batch-capable fake with optional failure on specific enqueue indexes."""

    def __init__(self, *, fail_on_index: set[int] | None = None) -> None:
        self.enqueued: list[tuple[JobType, JobInputPayload]] = []
        self._counter = 0
        self._fail_on_index = fail_on_index or set()

    async def enqueue(
        self,
        job_type: JobType,
        job_payload: JobInputPayload,
        max_retries: int,
        db_session: AsyncSession,
    ) -> UUID:
        self._counter += 1
        if self._counter in self._fail_on_index:
            raise RuntimeError(f"enqueue fail at index {self._counter}")
        self.enqueued.append((job_type, job_payload))
        return uuid4()

    async def poll(self, timeout: int) -> Optional[UUID]:
        return None

    async def claim(
        self, job_id: UUID, db_session: AsyncSession
    ) -> tuple[JobType, JobInputPayload]:
        raise NotImplementedError

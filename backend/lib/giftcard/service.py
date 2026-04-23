# backend/lib/giftcard/service.py


from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import (
    DAOGiftcards,
    GiftcardStatus,
)


async def grant_giftcard_for_share_fulfilling_payment(
    *,
    session: AsyncSession,
    share_id: UUID,
    payment_id: UUID,
    user_id: UUID,
    amount: int,
    currency: str,
    brand_code: Optional[str],
) -> Optional[UUID]:
    """
    Race-safe local grant using UNIQUE(share_id); no provider issuance. Sets linkage if NULL.
    """
    insert_stmt = pg_insert(DAOGiftcards).values(
        share_id=share_id,
        created_by_payment_id=payment_id,
        created_by_user_id=user_id,
        amount_total=amount,
        currency=currency,
        provider=None,
        brand_code=brand_code,
        provider_giftcard_id_internal_only=uuid4(),
        giftcard_code_explicit_override=None,
        status=GiftcardStatus.GRANTED,
        description="Granted via Stripe PI success",
        metadata_json={},
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[getattr(DAOGiftcards, "share_id")],
        set_={
            "created_by_payment_id": insert_stmt.excluded.created_by_payment_id,
            "updated_at": func.now(),
        },
        where=getattr(DAOGiftcards, "created_by_payment_id").is_(None),
    ).returning(getattr(DAOGiftcards, "id"))
    row = await session.execute(upsert_stmt)
    gc_id = row.scalar_one_or_none()
    if gc_id:
        return gc_id

    res = await session.execute(
        select(getattr(DAOGiftcards, "id"))
        .where(getattr(DAOGiftcards, "share_id") == share_id)
        .limit(1)
    )
    return res.scalar_one_or_none()

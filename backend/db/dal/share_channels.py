from typing import Optional
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import (
    DAOShareChannels,
    ShareChannelType,
)

from .base import (
    AsyncPostgreSQLDAL,
)
from .schemas import (
    DAOShareChannelsCreate,
    DAOShareChannelsUpdate,
)


class DALShareChannels(
    AsyncPostgreSQLDAL[
        DAOShareChannels,
        DAOShareChannelsCreate,
        DAOShareChannelsUpdate,
    ]
):
    model = DAOShareChannels

    @classmethod
    async def by_matching_user_id_or_email(
        cls,
        session: AsyncSession,
        user_id: Optional[UUID],
        email: Optional[str],
    ) -> list[DAOShareChannels]:
        conds: list[ColumnElement[bool]] = []
        if email is not None:
            conds.append(
                and_(
                    getattr(DAOShareChannels, "channel_type") == ShareChannelType.EMAIL,
                    getattr(DAOShareChannels, "destination") == email,
                )
            )
        if user_id is not None:
            conds.append(
                and_(
                    getattr(DAOShareChannels, "channel_type") == ShareChannelType.APNS,
                    getattr(DAOShareChannels, "destination") == str(user_id),
                )
            )

        stmt = select(DAOShareChannels).where(or_(*conds))
        return list((await session.execute(stmt)).scalars().all())

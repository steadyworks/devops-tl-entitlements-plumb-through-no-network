from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import CommentStatus, DAOPhotobookComments

from .base import AsyncPostgreSQLDAL
from .schemas import DAOPhotobookCommentsCreate, DAOPhotobookCommentsUpdate

if TYPE_CHECKING:
    from uuid import UUID


class DALPhotobookComments(
    AsyncPostgreSQLDAL[
        DAOPhotobookComments, DAOPhotobookCommentsCreate, DAOPhotobookCommentsUpdate
    ]
):
    model = DAOPhotobookComments

    @staticmethod
    async def count_grouped_by_photobook(
        session: AsyncSession,
        photobook_ids: Sequence[UUID],
        *,
        status: CommentStatus | None = CommentStatus.VISIBLE,
    ) -> dict[UUID, int]:
        """
        Returns a mapping of photobook_id -> comment_count in a single round-trip.
        By default counts only VISIBLE comments; pass status=None to count all.
        """
        if not photobook_ids:
            return {}

        stmt = (
            select(
                getattr(DAOPhotobookComments, "photobook_id"),
                func.count(getattr(DAOPhotobookComments, "id")),
            )
            .where(getattr(DAOPhotobookComments, "photobook_id").in_(photobook_ids))
            .group_by(getattr(DAOPhotobookComments, "photobook_id"))
        )

        if status is not None:
            stmt = stmt.where(getattr(DAOPhotobookComments, "status") == status)

        rows = (await session.execute(stmt)).all()
        # rows -> List[tuple[UUID, int]]
        return {photobook_id: int(cnt) for photobook_id, cnt in rows}

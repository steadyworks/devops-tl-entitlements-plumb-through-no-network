# backend/lib/giftcard/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALGiftcards,
    DAOGiftcardsUpdate,
    locked_row_by_id,
    safe_transaction,
)
from backend.db.data_models import (
    DAOGiftcards,
    GiftcardEventKind,
    GiftcardProvider,
    GiftcardStatus,
)
from backend.lib.types.exception import UUIDNotFoundError
from backend.lib.utils.common import utcnow

from .logging_helper_mixins import GiftcardEventLoggingHelperMixins


@dataclass(frozen=True)
class GiftcardIssueParams:
    giftcard_id: UUID
    provider_giftcard_id_internal_only: UUID
    amount_total_minor: int
    currency: str
    brand_code: str
    giftbit_cached_gift_link: Optional[str]


@dataclass(frozen=True)
class GiftcardPresentable:
    giftcard_code: Optional[str]
    giftcard_reveal_url: Optional[str]


@dataclass(frozen=True)
class GiftcardIssueResponse:
    presentable: Optional[GiftcardPresentable]
    changes_to_persist: Optional[DAOGiftcardsUpdate]


class AbstractBaseGiftcardClient(ABC, GiftcardEventLoggingHelperMixins):
    _GIFTCARD_PROVIDER: GiftcardProvider

    @abstractmethod
    async def _issue_giftcard_provider_impl_safe_and_idempotent(
        self,
        *,
        db_session: AsyncSession,
        giftcard_issue_params: GiftcardIssueParams,
    ) -> GiftcardIssueResponse: ...

    @final
    async def issue_giftcard(
        self,
        session: AsyncSession,
        giftcard_uuid: UUID,
    ) -> GiftcardPresentable:
        """
        If the giftcard is not found, CANCELED, EXPIRED or REDEEMED, raises.

        Issues giftcard per spec if the giftcard is in GRANTED / ISSUED state.
        Safe to call repeatedly.

        All ACCESS_* logs are emitted via `event_span`:
          - ATTEMPT is logged before any DB tx opens.
          - SUCCESS/FAILURE are logged after all tx blocks exit.
        """
        if session.in_transaction():
            raise RuntimeError(
                "[issue_giftcard] Must be called with no active transaction on the session. "
                "Commit/close the caller transaction first."
            )

        # Wrap the whole access flow in an ACCESS span so logs never happen in a tx.
        async with self.event_span(
            session,
            kind_attempt=GiftcardEventKind.ACCESS_ATTEMPT,
            kind_success=GiftcardEventKind.ACCESS_SUCCESS,
            kind_failure=GiftcardEventKind.ACCESS_FAILURE,
            giftcard_id=giftcard_uuid,
            provider=self._GIFTCARD_PROVIDER,
            attempt_message="Giftcard access",
        ) as access_success_payload:
            # 0) Existence & quick state (short transaction just for the read)
            async with safe_transaction(
                session, context="issue_giftcard/initial_check"
            ):
                dao: Optional[DAOGiftcards] = await DALGiftcards.get_by_id(
                    session, giftcard_uuid
                )
                if dao is None:
                    # Raising will be converted into ACCESS_FAILURE by the span
                    raise UUIDNotFoundError(giftcard_uuid)

            # Terminal states -> raise (span handles ACCESS_FAILURE)
            if dao.status in {
                GiftcardStatus.CANCELED,
                GiftcardStatus.EXPIRED,
                GiftcardStatus.REDEEMED,
            }:
                raise RuntimeError(
                    f"Giftcard {giftcard_uuid} is {dao.status}; cannot issue."
                )

            # Already issued with explicit override -> success and return
            if (
                dao.status == GiftcardStatus.ISSUED
                and dao.giftcard_code_explicit_override
            ):
                code_trimmed: str = dao.giftcard_code_explicit_override.strip()
                if code_trimmed:
                    access_success_payload.update(
                        {
                            "brand_code": dao.brand_code,
                            "amount_minor": dao.amount_total,
                            "currency": dao.currency,
                            "giftcard_code": "<SANITIZED>",
                            "first_time_issue": False,
                            "present_method": "code",
                        }
                    )
                    return GiftcardPresentable(
                        giftcard_code=code_trimmed, giftcard_reveal_url=None
                    )

            # 1) Provider call (idempotent). This function may use its own event_span for ISSUE_* logs.
            issue_resp: GiftcardIssueResponse = await self._issue_giftcard_provider_impl_safe_and_idempotent(
                db_session=session,
                giftcard_issue_params=GiftcardIssueParams(
                    giftcard_id=dao.id,
                    provider_giftcard_id_internal_only=dao.provider_giftcard_id_internal_only,
                    amount_total_minor=dao.amount_total,
                    currency=dao.currency,
                    brand_code=dao.brand_code,
                    giftbit_cached_gift_link=dao.giftbit_cached_gift_link,
                ),
            )

            presentable: Optional[GiftcardPresentable] = issue_resp.presentable
            if presentable is None or (
                presentable.giftcard_code is None
                and presentable.giftcard_reveal_url is None
            ):
                raise RuntimeError(
                    "Giftcard access attempt failed due to empty provider response."
                )

            # 2) Persist under lock, resolve races; no logging inside the tx.
            first_time_issue: bool = False
            present_method: str = "code" if presentable.giftcard_code else "url"

            async with safe_transaction(session, context="issue_giftcard/persist"):
                async with locked_row_by_id(
                    session, DAOGiftcards, giftcard_uuid
                ) as row:
                    # Re-check under lock
                    if row.status in {
                        GiftcardStatus.CANCELED,
                        GiftcardStatus.EXPIRED,
                        GiftcardStatus.REDEEMED,
                    }:
                        raise RuntimeError(
                            f"Giftcard {giftcard_uuid} moved to terminal state {row.status} during issuance."
                        )

                    # If DB already carries an explicit override and is ISSUED, prefer that immediate present
                    if (
                        row.status == GiftcardStatus.ISSUED
                        and row.giftcard_code_explicit_override
                    ):
                        code2: str = row.giftcard_code_explicit_override.strip()
                        if code2:
                            # Populate ACCESS_SUCCESS payload for the span and return
                            access_success_payload.update(
                                {
                                    "brand_code": row.brand_code,
                                    "amount_minor": row.amount_total,
                                    "currency": row.currency,
                                    "giftcard_code": "<SANITIZED>",
                                    "first_time_issue": False,
                                    "present_method": "code",
                                }
                            )
                            return GiftcardPresentable(
                                giftcard_code=code2, giftcard_reveal_url=None
                            )

                    # Normal path: flip to ISSUED if not already
                    if row.status != GiftcardStatus.ISSUED:
                        update_obj: DAOGiftcardsUpdate = (
                            issue_resp.changes_to_persist or DAOGiftcardsUpdate()
                        )
                        update_obj.status = GiftcardStatus.ISSUED
                        update_obj.issued_at = utcnow()
                        update_obj.provider = self._GIFTCARD_PROVIDER
                        # You can merge with existing metadata here if needed
                        update_obj.metadata_json = {"present_method": present_method}

                        await DALGiftcards.update_by_id(
                            session, giftcard_uuid, update_obj
                        )
                        first_time_issue = True

            # 3) At this point all transactions are closed; the span will log ACCESS_SUCCESS.
            access_success_payload.update(
                {
                    "brand_code": dao.brand_code,
                    "amount_minor": dao.amount_total,
                    "currency": dao.currency,
                    "present_method": present_method,
                    "first_time_issue": first_time_issue,
                }
            )

            # Guaranteed presentable here
            return presentable

    @abstractmethod
    async def close(self) -> None: ...

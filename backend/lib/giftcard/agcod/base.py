# backend/lib/giftcard/agcod/base.py

import math
from abc import abstractmethod
from typing import Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import GiftcardEventKind, GiftcardProvider
from backend.lib.giftcard.base import (
    AbstractBaseGiftcardClient,
    GiftcardIssueParams,
    GiftcardIssueResponse,
    GiftcardPresentable,
)

from .client import AGCODClient, CurrencyCode
from .client import StatusCode as AGCODStatusCode


class AbstractBaseAGCODGiftcardClient(AbstractBaseGiftcardClient):
    _GIFTCARD_PROVIDER: GiftcardProvider = GiftcardProvider.AGCOD
    _agcod_client: AGCODClient

    def __init__(self) -> None:
        self._agcod_client = self._init_agcod_client()

    async def close(self) -> None:
        await self._agcod_client.close()

    @abstractmethod
    def _init_agcod_client(self) -> AGCODClient: ...

    def _get_agcod_creation_id_from_internal_provider_id(
        self,
        internal_provider_id: UUID,
    ) -> str:
        partner_id: str = self._agcod_client.get_partner_id()
        creation_request_id_candidate: str = f"{partner_id}{internal_provider_id.hex}"
        assert len(creation_request_id_candidate) <= 40
        return creation_request_id_candidate

    def _get_agcod_amount(
        self,
        amount_total_minor_unit: int,
        currency: str,
    ) -> Tuple[int, CurrencyCode]:
        assert currency.upper().strip() == "USD", "Only USD is enabled"
        if amount_total_minor_unit % 100 != 0:
            raise ValueError("AGCOD requires whole-dollar amounts for USD.")
        return (
            math.floor(amount_total_minor_unit / 100.0),  # AGCOD integer dollars
            CurrencyCode(currency.upper()),
        )

    async def _issue_giftcard_provider_impl_safe_and_idempotent(
        self,
        *,
        db_session: AsyncSession,
        giftcard_issue_params: GiftcardIssueParams,
    ) -> GiftcardIssueResponse:
        """
        Performs an idempotent AGCOD create call.
        Uses `event_span` so ATTEMPT/SUCCESS/FAILURE logs are automatic and concise.
        """
        if db_session.in_transaction():
            raise RuntimeError(
                "[_issue_giftcard_provider_impl_safe_and_idempotent] Must be called with no active transaction on the session. "
                "Commit/close the caller transaction first."
            )

        creation_request_id: str = (
            self._get_agcod_creation_id_from_internal_provider_id(
                giftcard_issue_params.provider_giftcard_id_internal_only
            )
        )
        amount_agcod, currency = self._get_agcod_amount(
            giftcard_issue_params.amount_total_minor, giftcard_issue_params.currency
        )

        # event_span handles attempt/success/failure logging around the network call
        async with self.event_span(
            db_session,
            kind_attempt=GiftcardEventKind.ISSUE_ATTEMPT,
            kind_success=GiftcardEventKind.ISSUE_SUCCESS,
            kind_failure=GiftcardEventKind.ISSUE_FAILURE,
            giftcard_id=giftcard_issue_params.giftcard_id,
            provider=self._GIFTCARD_PROVIDER,
            attempt_message="AGCOD issue attempt",
            attempt_payload={
                "agcod_creation_request_id": creation_request_id,
                "provider_giftcard_id_internal_only": str(
                    giftcard_issue_params.provider_giftcard_id_internal_only
                ),
                "amount_agcod": amount_agcod,
                "currency_agcod": currency.value,
                "brand_code": giftcard_issue_params.brand_code,
            },
        ) as success_payload:
            # Idempotent network call (no DB lock held)
            agcod_resp = await self._agcod_client.create_gift_card(
                creation_request_id=creation_request_id,
                currency=currency,
                amount=amount_agcod,
            )

            # Validate AGCOD response
            if agcod_resp.status != AGCODStatusCode.SUCCESS:
                raise RuntimeError(
                    f"Network request succeeded but unexpected status code: {agcod_resp.status.value}"
                )
            cardInfo = agcod_resp.cardInfo
            if cardInfo.cardStatus.lower().strip() != "fulfilled":
                raise RuntimeError(
                    f"Network request succeeded but unexpected card status: "
                    f"{cardInfo.cardStatus} != Fulfilled"
                )
            if cardInfo.value.currencyCode != currency:
                raise RuntimeError(
                    "Network request succeeded but unmatched currency: "
                    f"received {cardInfo.value.currencyCode.value} != {currency.value}"
                )
            if cardInfo.value.amount != amount_agcod:
                raise RuntimeError(
                    "Network request succeeded but unmatched giftcard value: "
                    f"received {cardInfo.value.amount} != {amount_agcod}. "
                    "Likely bug in AGCOD processing code or we accepted a decimal giftcard amount."
                )

            agcod_resp_dump = agcod_resp.model_dump(mode="json")
            if "gcClaimCode" in agcod_resp_dump:
                agcod_resp_dump["gcClaimCode"] = "<SANITIZED>"
            # SUCCESS payload for the span
            success_payload.update(
                {
                    "agcod_creation_request_id": creation_request_id,
                    "provider_giftcard_id_internal_only": giftcard_issue_params.provider_giftcard_id_internal_only,
                    # We intentionally do NOT include raw claim code here.
                    "agcod_resp": agcod_resp_dump,
                }
            )

            # Return data for caller
            return GiftcardIssueResponse(
                presentable=GiftcardPresentable(
                    giftcard_code=agcod_resp.gcClaimCode,
                    giftcard_reveal_url=None,
                ),
                changes_to_persist=None,
            )

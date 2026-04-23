# backend/lib/giftcard/giftbit/base.py

from abc import abstractmethod
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import DAOGiftcardsUpdate
from backend.db.data_models import GiftcardEventKind, GiftcardProvider
from backend.lib.giftcard.base import (
    AbstractBaseGiftcardClient,
    GiftcardIssueParams,
    GiftcardIssueResponse,
    GiftcardPresentable,
)

from .client import (
    CreateEmbeddedResponse,
    GiftbitClient,
    GiftbitErrorCampaignInvalidIDError,
    ListGiftsResponse,
)


class AbstractBaseGiftbitGiftcardClient(AbstractBaseGiftcardClient):
    _GIFTCARD_PROVIDER: GiftcardProvider = GiftcardProvider.GIFTBIT
    _giftbit_client: GiftbitClient

    def __init__(self) -> None:
        self._giftbit_client = self._init_giftbit_client()

    async def close(self) -> None:
        await self._giftbit_client.close()

    @abstractmethod
    def _init_giftbit_client(self) -> GiftbitClient: ...

    def _get_giftbit_embed_request_id(
        self, internal_giftcard_id: UUID, *, prefix: str = "gb-"
    ) -> str:
        """
        Helper to derive a stable idempotency id from an internal UUID.
        Giftbit doesn't publish a max length; keep it reasonable.
        """
        return f"{prefix}{internal_giftcard_id.hex}"

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

        if (
            giftcard_issue_params.giftbit_cached_gift_link is not None
            and giftcard_issue_params.giftbit_cached_gift_link.strip()
        ):
            return GiftcardIssueResponse(
                presentable=GiftcardPresentable(
                    giftcard_code=None,
                    giftcard_reveal_url=giftcard_issue_params.giftbit_cached_gift_link.strip(),
                ),
                changes_to_persist=None,
            )

        giftbit_embed_request_id: str = self._get_giftbit_embed_request_id(
            giftcard_issue_params.provider_giftcard_id_internal_only
        )

        # event_span handles attempt/success/failure logging around the network call
        async with self.event_span(
            db_session,
            kind_attempt=GiftcardEventKind.ISSUE_ATTEMPT,
            kind_success=GiftcardEventKind.ISSUE_SUCCESS,
            kind_failure=GiftcardEventKind.ISSUE_FAILURE,
            giftcard_id=giftcard_issue_params.giftcard_id,
            provider=self._GIFTCARD_PROVIDER,
            attempt_message="Giftbit issue attempt",
            attempt_payload={
                "provider_giftcard_id_internal_only": str(
                    giftcard_issue_params.provider_giftcard_id_internal_only
                ),
                "giftbit_embed_request_id": giftbit_embed_request_id,
                "amount_gitbit": giftcard_issue_params.amount_total_minor,
                "currency_gitbit": giftcard_issue_params.currency,
                "brand_code": giftcard_issue_params.brand_code,
            },
        ) as success_payload:
            final_gift_link: Optional[str] = None
            final_campaign_uuid: Optional[str] = None
            giftbit_resp: Optional[CreateEmbeddedResponse] = None
            list_rewards_resp: Optional[ListGiftsResponse] = None
            try:
                giftbit_resp = await self._giftbit_client.create_embedded_reward(
                    brand_code=giftcard_issue_params.brand_code,
                    price_in_cents=giftcard_issue_params.amount_total_minor,
                    embed_request_id=giftbit_embed_request_id,
                )
                (final_gift_link, final_campaign_uuid) = (
                    giftbit_resp.gift_link,
                    giftbit_resp.campaign.uuid,
                )
            except GiftbitErrorCampaignInvalidIDError:
                # Duplicate creation request, we attempt to recover by listing the rewards.
                # If this still fails, surface the error
                list_rewards_resp = await self._giftbit_client.list_gifts(
                    campaign_id=giftbit_embed_request_id,
                    limit=1,
                )
                if not list_rewards_resp.gifts:
                    raise RuntimeError(
                        "Giftbit creation failed (likely created before), but listing rewards returned empty"
                    )
                gift = list_rewards_resp.gifts[0]
                if gift.campaign_uuid is None:
                    raise RuntimeError(
                        "Giftbit creation failed (likely created before), listing rewards returned non-empty, but campaign_uuid not found"
                    )
                (final_gift_link, final_campaign_uuid) = (
                    self._giftbit_client.render_giftbit_embed_link(gift.campaign_uuid),
                    gift.campaign_uuid,
                )

            success_payload.update(
                {
                    "giftbit_gift_link": final_gift_link,
                    "giftbit_campaign_uuid": final_campaign_uuid,
                    "giftbit_embed_request_id": giftbit_embed_request_id,
                    "provider_giftcard_id_internal_only": giftcard_issue_params.provider_giftcard_id_internal_only,
                    "create_embed_resp": None
                    if giftbit_resp is None
                    else giftbit_resp.model_dump(mode="json"),
                    "list_rewards_resp": None
                    if list_rewards_resp is None
                    else list_rewards_resp.model_dump(mode="json"),
                }
            )
            return GiftcardIssueResponse(
                presentable=GiftcardPresentable(
                    giftcard_code=None,
                    giftcard_reveal_url=final_gift_link,
                ),
                changes_to_persist=DAOGiftcardsUpdate(
                    giftbit_cached_gift_link=final_gift_link,
                    giftbit_cached_campaign_uuid=final_campaign_uuid,
                ),
            )

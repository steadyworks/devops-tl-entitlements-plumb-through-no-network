# backend/route_handler/share.py
from typing import Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

from backend.db.dal import (
    DALGiftcards,
    DALShareChannels,
    FilterOp,
    safe_transaction,
)
from backend.db.data_models import GiftcardStatus, ShareChannelType
from backend.db.externals import (
    GiftcardsOverviewResponse,
)
from backend.lib.utils.share_destination_normalizer import (
    normalize_email_throws,
    normalize_phone_e164_throws,
)
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
    unauthenticated_route,
)
from backend.route_handler.photobook import PhotobooksFullPublicResponse


class PhotobookByShareSlugRedeemResponse(BaseModel):
    photobook: PhotobooksFullPublicResponse
    giftcard: Optional[GiftcardsOverviewResponse]
    sender_display_name: Optional[str]
    allowed_emails: list[str]
    allowed_phones: list[str]


class GiftcardPresentableResponse(BaseModel):
    giftcard_code: Optional[str]
    giftcard_reveal_url: Optional[str]


class RedeemAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/redeem/slug/{share_slug}",
            "get_redeem_by_share_slug",
            methods=["GET"],
        )

        self.route(
            "/api/redeem/slug/{share_slug}/issue-giftcard",
            "issue_giftcard_by_share_slug",
            methods=["POST"],
        )

    @unauthenticated_route
    @enforce_response_model
    async def get_redeem_by_share_slug(
        self,
        share_slug: str,
    ) -> PhotobookByShareSlugRedeemResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            (
                share,
                photobook,
            ) = await self.get_share_and_photobook_by_slug_assert_not_revoked(
                db_session,
                share_slug,
            )
            share_channels = await DALShareChannels.list_all(
                db_session,
                {
                    "photobook_share_id": (FilterOp.EQ, share.id),
                    "archived_at": (FilterOp.IS_NULL, None),
                },
            )
            allowed_emails: set[str] = set()
            allowed_phones: set[str] = set()
            for ch in share_channels:
                if ch.channel_type == ShareChannelType.EMAIL:
                    allowed_emails.add(ch.destination)
                elif ch.channel_type == ShareChannelType.SMS:
                    allowed_phones.add(ch.destination)

            photobook_resp = await PhotobooksFullPublicResponse.rendered_from_dao(
                photobook, db_session, self.app.asset_manager
            )

            giftcards_if_any = await DALGiftcards.list_all(
                db_session,
                {
                    "share_id": (FilterOp.EQ, share.id),
                    "status": (FilterOp.NE, GiftcardStatus.CANCELED),
                },
                limit=1,
            )
            giftcard_resp = None
            if giftcards_if_any:
                giftcard_resp = GiftcardsOverviewResponse.from_dao(giftcards_if_any[0])

            return PhotobookByShareSlugRedeemResponse(
                photobook=photobook_resp,
                giftcard=giftcard_resp,
                sender_display_name=share.sender_display_name,
                allowed_emails=list(allowed_emails),
                allowed_phones=list(allowed_phones),
            )

    @enforce_response_model
    async def issue_giftcard_by_share_slug(
        self,
        request: Request,
        share_slug: str,
    ) -> GiftcardPresentableResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            async with safe_transaction(
                db_session, "redeem/issue_giftcard_by_share_slug/init_check"
            ):
                rcx = await self.get_request_context(request)
                if rcx.user is None:
                    raise HTTPException(status_code=401, detail="Not authorized")

                share = await self.get_share_by_slug_assert_not_revoked(
                    db_session, share_slug
                )
                share_channels = await DALShareChannels.list_all(
                    db_session,
                    {
                        "photobook_share_id": (FilterOp.EQ, share.id),
                        "archived_at": (FilterOp.IS_NULL, None),
                    },
                )
                allowed_emails: set[str] = set()
                allowed_phones: set[str] = set()
                for ch in share_channels:
                    if ch.channel_type == ShareChannelType.EMAIL:
                        allowed_emails.add(ch.destination)
                    elif ch.channel_type == ShareChannelType.SMS:
                        allowed_phones.add(ch.destination)

                can_access = False
                if rcx.user.email is not None:
                    if rcx.user.email in allowed_emails:
                        can_access = True
                    try:
                        if normalize_email_throws(rcx.user.email) in allowed_emails:
                            can_access = True
                    except Exception:
                        pass

                if rcx.user.phone is not None:
                    if rcx.user.phone in allowed_phones:
                        can_access = True
                    try:
                        if (
                            normalize_phone_e164_throws(rcx.user.phone)
                            in allowed_phones
                        ):
                            can_access = True
                    except Exception:
                        pass

                if not can_access:
                    raise HTTPException(status_code=401, detail="Not authorized")

                giftcards_if_any = await DALGiftcards.list_all(
                    db_session,
                    {
                        "share_id": (FilterOp.EQ, share.id),
                        "status": (FilterOp.NE, GiftcardStatus.CANCELED),
                    },
                    limit=1,
                )
                if not giftcards_if_any:
                    raise HTTPException(status_code=404, detail="Gift not found")
                giftcard_dao = giftcards_if_any[0]

            # Issue giftcard

            giftcard_brand_registry_entry = (
                self.app.giftcard_brand_registry.get_brand_by_code(
                    giftcard_dao.brand_code
                )
            )

            if giftcard_brand_registry_entry is None:
                raise HTTPException(
                    status_code=502,
                    detail=f"Brand code {giftcard_dao.brand_code} invalid",
                )

            try:
                giftcard_client = self.get_giftcard_client_for(
                    request=request,
                    giftcard_provider=giftcard_brand_registry_entry.preferred_giftcard_provider,
                )
                giftcard_presentable = await giftcard_client.issue_giftcard(
                    db_session, giftcard_dao.id
                )
                return GiftcardPresentableResponse(
                    giftcard_code=giftcard_presentable.giftcard_code,
                    giftcard_reveal_url=giftcard_presentable.giftcard_reveal_url,
                )
            except Exception:
                # Sanitize internal error message
                raise RuntimeError("Something went wrong. Please try again.")

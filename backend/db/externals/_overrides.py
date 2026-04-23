# pyright: reportPrivateUsage=false

import logging
from collections import defaultdict
from typing import Any, Iterable, Optional, Self
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALAssets,
    DALGiftcards,
    DALPayments,
    DALPhotobookBookmarks,
    DALPhotobookComments,
    DALShareChannels,
    DALShares,
    DALUsers,
    FilterOp,
    OrderDirection,
)
from backend.db.data_models import (
    CommentStatus,
    DAOAssets,
    DAOGiftcards,
    DAOPages,
    DAOPayments,
    DAOPhotobookComments,
    DAOPhotobooks,
    DAOShares,
    DAOUsers,
    GiftcardStatus,
    PaymentStatus,
    ShareAccessPolicy,
)
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    MessageOption,
    PageSchema,
    PhotobookSchema,
    ShareCreateRequest,
)
from backend.db.utils.common import retrieve_available_asset_key_in_order_of
from backend.lib.asset_manager.base import AssetManager
from backend.lib.giftcard.brands.registry import REGISTRY_SINGLETON
from backend.route_handler.share_v0 import (
    SharedWithUserAvatar,
)

from ._generated_DO_NOT_USE import (
    APIResponseModelConvertibleFromDAOMixin,
    ISO8601UTCDateTime,
    ShareChannelsOverviewResponse,
    _AssetsOverviewResponse,
    _PagesOverviewResponse,
    _PaymentsOverviewResponse,
    _PhotobookCommentsOverviewResponse,
    _PhotobooksOverviewResponse,
    _SharesOverviewResponse,
    _UsersOverviewResponse,
)
from .types import BrandPublicResponse


class PhotobookCommentsOverviewResponse(
    _PhotobookCommentsOverviewResponse,
):
    commenter_ip: Optional[str] = Field(default=None, exclude=True)
    user_agent: Optional[str] = Field(default=None, exclude=True)
    guest_name: Optional[str] = Field(default=None, exclude=True)
    guest_email: Optional[str] = Field(default=None, exclude=True)

    commentor_name: Optional[str] = None
    commentor_contact: Optional[str] = None
    asset_key_commentor_avatar: Optional[str] = None
    signed_url_commentor_avatar: Optional[str] = None

    @classmethod
    async def rendered_from_daos(
        cls,
        daos: list[DAOPhotobookComments],
        db_session: AsyncSession,
    ) -> list[Self]:
        users: list[DAOUsers] = await DALUsers.list_all(
            db_session,
            filters={"id": (FilterOp.IN, list(set(c.user_id for c in daos)))},
        )
        users_map_by_id = {u.id: u for u in users}
        resps: list[Self] = []

        for dao in daos:
            user = None
            if dao.user_id is not None:
                user = users_map_by_id.get(dao.user_id, None)
            resps.append(
                cls(
                    **dao.model_dump(),
                    commentor_name=dao.guest_name or (user.name if user else None),
                    commentor_contact=dao.guest_email or (user.email if user else None),
                    asset_key_commentor_avatar=None,
                    signed_url_commentor_avatar=None,  # TODO: implement user profile image URL retrieval
                )
            )
        return resps


class AssetsOverviewResponse(
    _AssetsOverviewResponse,
):
    asset_key_original: Optional[str] = Field(default=None, exclude=True)
    asset_key_display: Optional[str] = Field(default=None, exclude=True)
    asset_key_llm: Optional[str] = Field(default=None, exclude=True)
    asset_key_thumbnail: Optional[str] = Field(default=None, exclude=True)

    signed_asset_url: str
    signed_asset_url_thumbnail: str

    @classmethod
    async def rendered_from_daos(
        cls,
        daos: list[DAOAssets],
        asset_manager: AssetManager,
    ) -> list[Self]:
        uuid_asset_keys_map_display = {
            dao.id: retrieve_available_asset_key_in_order_of(
                dao,
                [
                    "asset_key_display",
                    "asset_key_original",
                    "asset_key_llm",
                ],
            )
            for dao in daos
        }
        uuid_asset_keys_map_thumbnail = {
            dao.id: retrieve_available_asset_key_in_order_of(
                dao,
                [
                    "asset_key_thumbnail",
                    "asset_key_llm",
                    "asset_key_display",
                    "asset_key_original",
                ],
            )
            for dao in daos
        }
        signed_urls = await asset_manager.generate_signed_urls_batched(
            list(uuid_asset_keys_map_display.values())
            + list(uuid_asset_keys_map_thumbnail.values())
        )
        resps: list[Self] = []
        for dao in daos:
            signed_asset_url_or_exception = signed_urls.get(
                uuid_asset_keys_map_display[dao.id]
            )
            signed_asset_url_thumbnail_or_exception = signed_urls.get(
                uuid_asset_keys_map_thumbnail[dao.id]
            )
            resps.append(
                cls(
                    **dao.model_dump(),
                    signed_asset_url=(
                        signed_asset_url_or_exception
                        if isinstance(signed_asset_url_or_exception, str)
                        else ""
                    ),
                    signed_asset_url_thumbnail=(
                        signed_asset_url_thumbnail_or_exception
                        if isinstance(signed_asset_url_thumbnail_or_exception, str)
                        else ""
                    ),
                )
            )

        return resps


class GiftcardsOverviewResponse(APIResponseModelConvertibleFromDAOMixin[DAOGiftcards]):
    id: UUID
    share_id: UUID
    created_by_user_id: Optional[UUID]
    amount_total: int
    currency: str
    brand_code: str
    status: GiftcardStatus
    granted_at: ISO8601UTCDateTime
    created_at: ISO8601UTCDateTime
    updated_at: ISO8601UTCDateTime

    giftcard_brand_response: Optional[BrandPublicResponse] = None

    @classmethod
    def from_dao(cls, dao: DAOGiftcards) -> Self:
        obj = super().from_dao(dao)
        brand_entry = REGISTRY_SINGLETON.get_brand_by_code(dao.brand_code)
        if brand_entry is not None:
            obj.giftcard_brand_response = BrandPublicResponse.from_entry(
                brand_entry, REGISTRY_SINGLETON
            )
        else:
            obj.giftcard_brand_response = None
        return obj


class SharesOverviewResponse(
    _SharesOverviewResponse,
):
    attached_giftcard: Optional[GiftcardsOverviewResponse] = None

    @classmethod
    async def rendered_from_daos(
        cls: type[Self],
        daos: Iterable[DAOShares],
        db_session: AsyncSession,
    ) -> list[Self]:
        dao_ids = [dao.id for dao in daos]
        giftcard_daos = await DALGiftcards.list_all(
            db_session, {"share_id": (FilterOp.IN, dao_ids)}
        )
        giftcard_daos_by_share_id = {gdao.share_id: gdao for gdao in giftcard_daos}

        resps: list[Self] = []
        for dao in daos:
            gdao = giftcard_daos_by_share_id.get(dao.id, None)
            resps.append(
                cls(
                    **dao.model_dump(),
                    attached_giftcard=None
                    if gdao is None
                    else GiftcardsOverviewResponse.from_dao(gdao),
                )
            )

        return resps


class PagesOverviewResponse(
    _PagesOverviewResponse, APIResponseModelConvertibleFromDAOMixin[DAOPages]
):
    user_message_alternative_options: Optional[dict[str, Any]] = Field(
        default=None, exclude=True
    )
    user_message_alternative_options_parsed: Optional[list[MessageOption]] = None

    @classmethod
    def from_dao(cls, dao: DAOPages) -> Self:
        return cls(
            **dao.model_dump(),
            user_message_alternative_options_parsed=PageSchema.deserialize_page_message_alternatives(
                dao.user_message_alternative_options
            ),
        )


class PaymentsOverviewResponse(
    _PaymentsOverviewResponse, APIResponseModelConvertibleFromDAOMixin[DAOPayments]
):
    stripe_customer_id: Optional[str] = Field(default=None, exclude=True)
    stripe_payment_method_id: Optional[str] = Field(default=None, exclude=True)
    stripe_latest_charge_id: Optional[str] = Field(default=None, exclude=True)
    receipt_email: Optional[str] = Field(default=None, exclude=True)
    idempotency_key: Optional[str] = Field(default=None, exclude=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, exclude=True)
    share_create_request: Optional[dict[str, Any]] = Field(default=None, exclude=True)

    share_create_recipient_names: list[str]

    @classmethod
    def from_dao(cls, dao: DAOPayments) -> Self:
        pending_fulfillment_recipient_names: list[str] = []

        try:
            if dao.share_create_request is not None:
                request = ShareCreateRequest.deserialize(dao.share_create_request)
                pending_fulfillment_recipient_names = [
                    recipient.recipient_display_name
                    for recipient in request.recipients
                    if recipient.recipient_display_name is not None
                ]
        except Exception:
            logging.warning(
                f"[PaymentsOverviewResponse.from_dao] invalid share_create_request for payment: {dao.id}"
            )

        return cls(
            **dao.model_dump(),
            share_create_recipient_names=pending_fulfillment_recipient_names,
        )


class UsersOverviewResponse(
    _UsersOverviewResponse,
):
    profile_pic_asset_signed_url: Optional[str]

    @classmethod
    async def rendered_from_daos(
        cls,
        daos: Iterable[DAOUsers],
        db_session: AsyncSession,
        asset_manager: AssetManager,
    ) -> list[Self]:
        # Step 1: fetch prerequisites (no concurrent use of the same session)
        profile_pic_asset_list = await DALAssets.get_by_ids(
            db_session,
            [
                dao.profile_pic_asset_id
                for dao in daos
                if dao.profile_pic_asset_id is not None
            ],
        )

        profile_pic_assets_by_ids = {
            asset.id: asset for asset in profile_pic_asset_list
        }
        uuid_asset_keys_map = {
            asset.id: retrieve_available_asset_key_in_order_of(
                asset,
                [
                    "asset_key_llm",
                    "asset_key_display",
                    "asset_key_original",
                ],
            )
            for asset in profile_pic_asset_list
        }
        signed_urls = await asset_manager.generate_signed_urls_batched(
            list(uuid_asset_keys_map.values())
        )

        resps: list[Self] = []
        for dao in daos:
            profile_pic_signed_url = None
            if dao.profile_pic_asset_id is not None:
                profile_pic_asset = profile_pic_assets_by_ids.get(
                    dao.profile_pic_asset_id
                )
                if profile_pic_asset is not None:
                    profile_pic_signed_url_or_exception = signed_urls.get(
                        uuid_asset_keys_map[profile_pic_asset.id]
                    )
                    if isinstance(profile_pic_signed_url_or_exception, str):
                        profile_pic_signed_url = profile_pic_signed_url_or_exception

            resps.append(
                cls(
                    **dao.model_dump(),
                    profile_pic_asset_signed_url=profile_pic_signed_url,
                )
            )
        return resps


UsersOverviewResponse_INTERNAL_ONLY = _UsersOverviewResponse


class PhotobooksOverviewResponse(
    _PhotobooksOverviewResponse,
):
    is_owner: Optional[bool]
    is_bookmarked: Optional[bool]
    thumbnail_asset_signed_url: Optional[str]
    thumbnail_asset_blur_data_url: Optional[str]
    num_comments: int
    shared_with: list[SharedWithUserAvatar]
    suggested_overall_gift_message_alternative_options: Optional[dict[str, Any]] = (
        Field(default=None, exclude=True)
    )
    suggested_overall_gift_message_alternative_options_parsed: Optional[
        list[MessageOption]
    ] = None
    shares: list[SharesOverviewResponse]
    share_channels: list[ShareChannelsOverviewResponse]
    unfulfilled_payments: list[PaymentsOverviewResponse]

    @classmethod
    async def rendered_from_daos(
        cls: type[Self],
        daos: Iterable[DAOPhotobooks],
        db_session: AsyncSession,
        asset_manager: AssetManager,
        *,
        requesting_user_id: Optional[UUID] = None,
    ) -> list[Self]:
        dao_ids = [dao.id for dao in daos]

        # Step 1: fetch prerequisites (no concurrent use of the same session)
        thumbnail_asset_list = await DALAssets.get_by_ids(
            db_session,
            [
                dao.thumbnail_asset_id
                for dao in daos
                if dao.thumbnail_asset_id is not None
            ],
        )

        share_daos = await DALShares.list_all(
            db_session,
            {
                "photobook_id": (FilterOp.IN, dao_ids),
                "access_policy": (FilterOp.NE, ShareAccessPolicy.REVOKED),
            },
            order_by=[
                ("kind", OrderDirection.DESC),
                ("created_at", OrderDirection.DESC),
                ("recipient_display_name", OrderDirection.ASC),
                ("id", OrderDirection.ASC),
            ],
        )

        share_channel_daos = await DALShareChannels.list_all(
            db_session,
            {
                "photobook_id": (FilterOp.IN, dao_ids),
                "archived_at": (FilterOp.IS_NULL, None),
            },
            order_by=[
                ("created_at", OrderDirection.DESC),
                ("id", OrderDirection.ASC),
            ],
        )

        unfulfilled_payment_daos = await DALPayments.list_all(
            db_session,
            {
                "status": (FilterOp.EQ, PaymentStatus.SUCCEEDED),
                "fulfilled_at": (FilterOp.IS_NULL, None),
                "photobook_id": (FilterOp.IN, dao_ids),
            },
        )

        # Assets
        thumbnail_assets_by_ids = {asset.id: asset for asset in thumbnail_asset_list}
        uuid_asset_keys_map = {
            asset.id: retrieve_available_asset_key_in_order_of(
                asset,
                [
                    "asset_key_llm",
                    "asset_key_display",
                    "asset_key_original",
                ],
            )
            for asset in thumbnail_asset_list
        }
        signed_urls = await asset_manager.generate_signed_urls_batched(
            list(uuid_asset_keys_map.values())
        )

        # Shares
        share_resps = await SharesOverviewResponse.rendered_from_daos(
            share_daos,
            db_session,
        )
        share_resps_map: dict[UUID, list[SharesOverviewResponse]] = defaultdict(list)
        share_channel_resps_map: dict[UUID, list[ShareChannelsOverviewResponse]] = (
            defaultdict(list)
        )

        for share_resp in share_resps:
            share_resps_map[share_resp.photobook_id].append(share_resp)

        for share_channel_dao in share_channel_daos:
            share_channel_resps_map[share_channel_dao.photobook_id].append(
                ShareChannelsOverviewResponse.from_dao(share_channel_dao)
            )

        # Payment
        unfulfilled_payments_map: dict[UUID, list[PaymentsOverviewResponse]] = (
            defaultdict(list)
        )
        for unfulfilled_payment_dao in unfulfilled_payment_daos:
            unfulfilled_payments_map[unfulfilled_payment_dao.photobook_id].append(
                PaymentsOverviewResponse.from_dao(unfulfilled_payment_dao)
            )

        # Comments
        comment_counts_by_pb_map = (
            await DALPhotobookComments.count_grouped_by_photobook(
                db_session, dao_ids, status=CommentStatus.VISIBLE
            )
        )

        # Bookmarks
        bookmark_daos = await DALPhotobookBookmarks.list_all(
            db_session,
            filters={
                "user_id": (FilterOp.EQ, requesting_user_id),
                "photobook_id": (FilterOp.IN, dao_ids),
            },
        )
        bookmark_state_by_pb_map: dict[UUID, bool] = dict()
        for bookmark_dao in bookmark_daos:
            bookmark_state_by_pb_map[bookmark_dao.photobook_id] = True

        rendered_resps: list[Self] = []
        for dao in daos:
            thumbnail_signed_url, thumbnail_asset_blur_data_url = None, None
            if dao.thumbnail_asset_id is not None:
                thumbnail_asset = thumbnail_assets_by_ids.get(dao.thumbnail_asset_id)
                if thumbnail_asset is not None:
                    thumbnail_asset_blur_data_url = thumbnail_asset.blur_data_url
                    thumbnail_signed_url_or_exception = signed_urls.get(
                        uuid_asset_keys_map[thumbnail_asset.id]
                    )
                    if isinstance(thumbnail_signed_url_or_exception, str):
                        thumbnail_signed_url = thumbnail_signed_url_or_exception

            resp = cls(
                **dao.model_dump(),
                thumbnail_asset_signed_url=thumbnail_signed_url,
                thumbnail_asset_blur_data_url=thumbnail_asset_blur_data_url,
                num_comments=comment_counts_by_pb_map.get(dao.id, 0),
                shared_with=[],
                suggested_overall_gift_message_alternative_options_parsed=PhotobookSchema.deserialize_overall_gift_message_alternatives(
                    dao.suggested_overall_gift_message_alternative_options
                ),
                shares=share_resps_map.get(dao.id, []),
                share_channels=share_channel_resps_map.get(dao.id, []),
                unfulfilled_payments=unfulfilled_payments_map.get(dao.id, []),
                is_owner=None
                if requesting_user_id is None
                else requesting_user_id == dao.user_id,
                is_bookmarked=None
                if requesting_user_id is None
                else bookmark_state_by_pb_map.get(dao.id, False),
            )
            rendered_resps.append(resp)
        return rendered_resps

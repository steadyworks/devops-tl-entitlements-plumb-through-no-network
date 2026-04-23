import logging
from typing import TYPE_CHECKING, Optional, Self
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel

from backend.db.dal import (
    DALAssets,
    DALEntitlements,
    DALNotifications,
    DALPhotobookBookmarks,
    DALPhotobooks,
    DALShareChannels,
    DALUsers,
    DAOPhotobookBookmarksCreate,
    DAOShareChannels,
    DAOUsers,
    DAOUsersUpdate,
    FilterOp,
    OrderDirection,
    safe_commit,
)
from backend.db.data_models import (
    DAONotifications,
    DAOPhotobookBookmarks,
    DAOPhotobooks,
    PhotobookStatus,
)
from backend.db.externals import (
    EntitlementsOverviewResponse,
    PhotobooksOverviewResponse,
    UsersOverviewResponse,
)
from backend.lib.asset_manager.service import handle_asset_upload_status_update
from backend.lib.utils.common import none_throws
from backend.lib.websocket.types import (
    AssetUploadStatusPayload,
)
from backend.route_handler.base import RouteHandler

from .base import enforce_response_model, unauthenticated_route

if TYPE_CHECKING:
    from backend.lib.request.context import RequestContext


class UserClientBootstrapResponse(BaseModel):
    photobooks: list[PhotobooksOverviewResponse]
    made_by_me: list[UUID]
    bookmarked: list[UUID]
    shared_with_me: list[UUID]
    user: UsersOverviewResponse
    entitlement: Optional[EntitlementsOverviewResponse]


class UserGetPhotobooksResponse(BaseModel):
    photobooks: list[PhotobooksOverviewResponse]


class UserBookmarkPhotobookDeleteResponse(BaseModel):
    success: bool
    error_message: Optional[str] = None


class NotificationsOverviewResponse(BaseModel):
    id: UUID
    type: str
    created_at: str
    is_seen: bool
    title: Optional[str]
    body: Optional[str]
    group_key: Optional[str] = None
    cta_url: Optional[str] = None

    @classmethod
    async def rendered_from_daos(
        cls,
        daos: list[DAONotifications],
    ) -> list[Self]:
        return [
            cls(
                id=dao.id,
                type=dao.type,
                created_at=dao.created_at.isoformat(),
                is_seen=dao.seen_at is not None,
                title=dao.title,
                body=dao.body,
                group_key=dao.group_key,
                cta_url=dao.cta_url,
            )
            for dao in daos
        ]


class UserDashboardResponse(BaseModel):
    username: Optional[str]
    bmc_link: Optional[str]
    notifications: list[NotificationsOverviewResponse]


class UserDashboardEditRequest(BaseModel):
    username: str
    bmc_link: Optional[str] = None


class UserEditUsernameResponse(BaseModel):
    success: bool
    error_message: Optional[str] = None
    username: Optional[str] = None
    bmc_link: Optional[str] = None


class UserGetBMCLink(BaseModel):
    # profile image later
    user_id: UUID
    username: Optional[str]
    bmc_link: Optional[str]


class UserGuideFlagsResponse(BaseModel):
    seen_cover_guide: Optional[bool] = None
    seen_section_guide: Optional[bool] = None
    seen_page_content_guide: Optional[bool] = None


class UserRegisterProfilePicAssetPayload(BaseModel):
    profile_pic_asset_id: UUID


class UserAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/user/client_bootstrap",
            "user_client_bootstrap",
            methods=["GET"],
        )
        self.route(
            "/api/user/photobooks",
            "user_get_photobooks",
            methods=["GET"],
        )
        self.route(
            "/api/user/photobooks/bookmark/{photobook_id}/new",
            "user_photobook_bookmark_new",
            methods=["POST"],
        )
        self.route(
            "/api/user/photobooks/bookmark/{photobook_id}/remove",
            "user_photobook_bookmark_remove",
            methods=["DELETE"],
        )
        self.route(
            "/api/user/dashboard",
            "get_dashboard",
            ["GET"],
        )
        self.route(
            "/api/user/edit",
            "user_edit_username",
            ["POST"],
        )
        self.route(
            "/api/user/bmc_link/{user_id}",
            "get_user_bmc_link",
            methods=["GET"],
        )
        self.route(
            "/api/me/guide_flags",
            "get_user_guide_flags",
            methods=["GET"],
        )
        self.route(
            "/api/me/register_profile_pic_asset",
            "user_register_profile_pic_asset",
            methods=["POST"],
        )

    @enforce_response_model
    async def user_get_photobooks(
        self,
        request: Request,
    ) -> UserGetPhotobooksResponse:
        request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
            photobooks: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                {
                    "user_id": (FilterOp.EQ, request_context.user_id),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
                order_by=[("updated_at", OrderDirection.DESC)],
            )
            resp = UserGetPhotobooksResponse(
                photobooks=await PhotobooksOverviewResponse.rendered_from_daos(
                    photobooks,
                    db_session,
                    self.app.asset_manager,
                    requesting_user_id=request_context.user_id,
                )
            )
            return resp

    @enforce_response_model
    async def user_client_bootstrap(
        self, request: Request
    ) -> UserClientBootstrapResponse:
        request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
            # User
            user_dao = await DALUsers.get_by_id(db_session, request_context.user_id)
            if user_dao is None:
                raise HTTPException(status_code=401, detail="Unauthorized access")
            user_resp = (
                await UsersOverviewResponse.rendered_from_daos(
                    [user_dao],
                    db_session,
                    self.app.asset_manager,
                )
            )[0]

            # Entitlement
            entitlement_daos = await DALEntitlements.list_all(
                db_session,
                filters={"user_id": (FilterOp.EQ, request_context.user_id)},
                limit=1,
            )
            entitlement_dao = entitlement_daos[0] if entitlement_daos else None
            entitlement_resp = (
                None
                if entitlement_dao is None
                else EntitlementsOverviewResponse.from_dao(entitlement_dao)
            )

            # Owned
            made_by_me: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                {
                    "user_id": (FilterOp.EQ, request_context.user_id),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
                order_by=[("updated_at", OrderDirection.DESC)],
            )

            # Bookmarked
            photobook_bookmarks: list[
                DAOPhotobookBookmarks
            ] = await DALPhotobookBookmarks.list_all(
                db_session,
                filters={"user_id": (FilterOp.EQ, request_context.user_id)},
                order_by=[("created_at", OrderDirection.DESC)],
            )
            bookmarked: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                filters={
                    "id": (
                        FilterOp.IN,
                        [bookmark.photobook_id for bookmark in photobook_bookmarks],
                    ),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
                order_by=[("updated_at", OrderDirection.DESC)],
            )

            # Shared (best effort implicated)
            share_channels: list[
                DAOShareChannels
            ] = await DALShareChannels.by_matching_user_id_or_email(
                db_session,
                request_context.user_id,
                request_context.email,
            )
            shared_with_me: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                filters={
                    "id": (
                        FilterOp.IN,
                        [
                            share_channel.photobook_id
                            for share_channel in share_channels
                        ],
                    ),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
                order_by=[("updated_at", OrderDirection.DESC)],
            )

            all_daos_to_render: dict[UUID, DAOPhotobooks] = dict()
            for dao in made_by_me + bookmarked + shared_with_me:
                if dao.id not in all_daos_to_render:
                    all_daos_to_render[dao.id] = dao

            all_resps = await PhotobooksOverviewResponse.rendered_from_daos(
                list(all_daos_to_render.values()),
                db_session,
                self.app.asset_manager,
                requesting_user_id=request_context.user_id,
            )
            all_resps_by_id = {resp.id: resp for resp in all_resps}

            return UserClientBootstrapResponse(
                photobooks=all_resps,
                made_by_me=[
                    dao.id
                    for dao in made_by_me
                    if all_resps_by_id.get(dao.id) is not None
                ],
                bookmarked=[
                    dao.id
                    for dao in bookmarked
                    if all_resps_by_id.get(dao.id) is not None
                ],
                shared_with_me=[
                    dao.id
                    for dao in shared_with_me
                    if all_resps_by_id.get(dao.id) is not None
                ],
                user=user_resp,
                entitlement=entitlement_resp,
            )

    @enforce_response_model
    async def user_photobook_bookmark_new(
        self,
        request: Request,
        photobook_id: UUID,
    ) -> PhotobooksOverviewResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        async with self.app.new_db_session() as db_session:
            photobook_dao = await DALPhotobooks.get_by_id(db_session, photobook_id)
            if photobook_dao is None:
                raise HTTPException(status_code=404, detail="Photobook not found")

            async with safe_commit(db_session):
                await DALPhotobookBookmarks.create(
                    db_session,
                    DAOPhotobookBookmarksCreate(
                        user_id=logged_in_user_id,
                        photobook_id=photobook_id,
                        source=None,
                    ),
                )

            return (
                await PhotobooksOverviewResponse.rendered_from_daos(
                    [photobook_dao],
                    db_session,
                    self.app.asset_manager,
                    requesting_user_id=logged_in_user_id,
                )
            )[0]

    @enforce_response_model
    async def user_photobook_bookmark_remove(
        self,
        request: Request,
        photobook_id: UUID,
    ) -> PhotobooksOverviewResponse:
        request_context = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        async with self.app.new_db_session() as db_session:
            photobook_dao = await DALPhotobooks.get_by_id(db_session, photobook_id)
            if photobook_dao is None:
                raise HTTPException(status_code=404, detail="Photobook not found")

            bookmarks = await DALPhotobookBookmarks.list_all(
                db_session,
                filters={
                    "user_id": (FilterOp.EQ, logged_in_user_id),
                    "photobook_id": (FilterOp.EQ, photobook_id),
                },
                limit=1,
            )

            if bookmarks:
                dao = bookmarks[0]
                async with safe_commit(db_session):
                    await DALPhotobookBookmarks.delete_by_id(db_session, dao.id)

            return (
                await PhotobooksOverviewResponse.rendered_from_daos(
                    [photobook_dao],
                    db_session,
                    self.app.asset_manager,
                    requesting_user_id=logged_in_user_id,
                )
            )[0]

    @enforce_response_model
    async def get_dashboard(self, request: Request) -> UserDashboardResponse:
        """
        Returns the current user's username and all notifications related to them.
        "Related" means addressed directly by user_id OR by email.
        """
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        async with self.app.new_db_session() as db_session:
            # Load current user
            current_user: DAOUsers = none_throws(
                await DALUsers.get_by_id(db_session, logged_in_user_id)
            )

            # Prefer explicit username; fall back gracefully

            # Gather notifications by user_id
            by_user_id: list[DAONotifications] = await DALNotifications.list_all(
                db_session,
                filters={"recipient_id": (FilterOp.EQ, current_user.id)},
                order_by=[("created_at", OrderDirection.DESC)],
            )

            # De-duplicate (keep newest first). Uses DAO id as the identity key.
            merged: list[DAONotifications] = []
            seen_ids: set[UUID] = set()
            for n in by_user_id:
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    merged.append(n)

            # Optionally, ensure final sort by created_at desc
            merged.sort(key=lambda n: n.created_at, reverse=True)

            return UserDashboardResponse(
                username=current_user.name,
                bmc_link=current_user.bmc_link,
                notifications=await NotificationsOverviewResponse.rendered_from_daos(
                    merged,  # db_session
                ),
            )

    @enforce_response_model
    async def user_edit_username(
        self,
        request: Request,
        edit_request: UserDashboardEditRequest,
    ) -> UserEditUsernameResponse:
        """
        Allows the current user to update their username.
        """
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        # Basic validation — adjust rules as needed
        if not edit_request.username or len(edit_request.username.strip()) < 3:
            return UserEditUsernameResponse(
                success=False,
                error_message="Username must be at least 3 characters long.",
            )

        async with self.app.new_db_session() as db_session:
            try:
                current_user: DAOUsers = none_throws(
                    await DALUsers.get_by_id(db_session, logged_in_user_id)
                )

                # Update username
                current_user.name = edit_request.username.strip()
                current_user.bmc_link = edit_request.bmc_link

                async with safe_commit(db_session):
                    db_session.add(current_user)

                return UserEditUsernameResponse(
                    success=True,
                    username=current_user.name,
                    bmc_link=current_user.bmc_link,
                )

            except Exception as e:
                logging.exception(f"Failed to update username: {e}")
                return UserEditUsernameResponse(
                    success=False,
                    error_message="An unexpected error occurred.",
                )

    @unauthenticated_route
    @enforce_response_model
    async def get_user_bmc_link(self, user_id: UUID) -> Optional[UserGetBMCLink]:
        """
        Public-ish user info endpoint used by the client to fetch creator metadata.
        Returns minimal fields: username (name) and bmc_link.
        """
        # If you need auth gating, keep get_request_context; otherwise it can be omitted.
        # request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
            user = await DALUsers.get_by_id(db_session, user_id)
            if user is None:
                return None

            return UserGetBMCLink(
                user_id=user.id,
                username=user.name,  # your schema uses `name` for display/username
                bmc_link=user.bmc_link,  # nullable
            )

    @enforce_response_model
    async def get_user_guide_flags(
        self,
        request: Request,
    ) -> UserGuideFlagsResponse:
        """
        Returns guide flags for the current user.
        """
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        async with self.app.new_db_session() as db_session:
            current_user: DAOUsers = none_throws(
                await DALUsers.get_by_id(db_session, logged_in_user_id)
            )

            return UserGuideFlagsResponse(
                seen_cover_guide=current_user.seen_cover_guide,
                seen_section_guide=current_user.seen_section_guide,
                seen_page_content_guide=current_user.seen_page_content_guide,
            )

    @enforce_response_model
    async def user_register_profile_pic_asset(
        self,
        request: Request,
        payload: UserRegisterProfilePicAssetPayload,
    ) -> UsersOverviewResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id

        async with self.app.new_db_session() as db_session:
            asset = await DALAssets.get_by_id(db_session, payload.profile_pic_asset_id)
            if asset is None:
                raise HTTPException(
                    status_code=404, detail="Specified asset ID does not exist"
                )

            async with safe_commit(db_session, "user profile pic asset ID update"):
                user_dao = await DALUsers.update_by_id(
                    db_session,
                    logged_in_user_id,
                    DAOUsersUpdate(profile_pic_asset_id=payload.profile_pic_asset_id),
                )

            try:
                # Insert job to post process user profile pic
                await handle_asset_upload_status_update(
                    logged_in_user_id,
                    AssetUploadStatusPayload(
                        associated_photobook_id=None,
                        succeeded=[payload.profile_pic_asset_id],
                        failed=[],
                    ),
                    db_session,
                    self.app.remote_job_manager_cpu_bound,
                )
            except Exception:
                logging.warning(
                    "[user_register_profile_pic_asset] failed to enqueue profile pic post processing job"
                )
                pass

            return (
                await UsersOverviewResponse.rendered_from_daos(
                    [user_dao], db_session, self.app.asset_manager
                )
            )[0]

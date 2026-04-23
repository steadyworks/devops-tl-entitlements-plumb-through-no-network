# backend/route_handler/share.py
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from backend.db.dal import (
    DALGiftcards,
    DALPhotobooks,
    DALShares,
    FilterOp,
    safe_transaction,
)
from backend.db.data_models import GiftcardStatus
from backend.db.data_models.types_ENSURE_BACKWARDS_COMPATIBILITY import (
    ShareCreateRequest,
)
from backend.db.externals import (
    GiftcardsOverviewResponse,
    PhotobooksOverviewResponse,
)
from backend.lib.notifs.dispatch_service import claim_and_enqueue_one_outbox
from backend.lib.notifs.scheduling_schemas import (
    RescheduleRequest,
)
from backend.lib.notifs.scheduling_service import (
    reschedule_outbox_in_txn,
)
from backend.lib.posthog import posthog_capture
from backend.lib.sharing.schemas import (
    RevokeShareRequest,
    ShareCreateResponse,
)
from backend.lib.sharing.service import (
    ensure_public_share,
    initialize_shares_and_channels_in_txn,
    revoke_share_in_txn,
)
from backend.lib.utils.common import utcnow
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
    unauthenticated_route,
)
from backend.route_handler.photobook import PhotobooksFullPublicResponse

from .photobook import (
    PhotobookByShareSlugResponse,
    PhotobookMetadataResponse,
)


class ShareInitializeResponse(BaseModel):
    photobook: PhotobooksOverviewResponse


class ShareAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/share/slug/{share_slug}",
            "get_photobook_by_share_slug",
            methods=["GET"],
        )
        self.route(
            "/api/share/slug/{share_slug}/metadata",
            "get_photobook_metadata_by_share_slug",
            methods=["GET"],
        )
        self.route(
            "/api/share/{photobook_id}/initialize-share",
            "share_photobook_initialize",
            methods=["POST"],
        )

        self.route(
            "/api/share/{share_id}/revoke",
            "share_revoke",
            methods=["POST"],
        )
        self.route(
            "/api/share/{photobook_id}/ensure-public",
            "share_ensure_public",
            methods=["POST"],
        )

        self.route(
            "/api/share/outbox/{outbox_id}/reschedule",
            "share_outbox_reschedule",
            methods=["POST"],
        )
        self.route(
            "/api/share/outbox/{outbox_id}/send-now",
            "share_outbox_send_now",
            methods=["POST"],
        )

    @unauthenticated_route
    @enforce_response_model
    @posthog_capture()
    async def get_photobook_by_share_slug(
        self,
        share_slug: str,
    ) -> PhotobookByShareSlugResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            (
                share,
                photobook,
            ) = await self.get_share_and_photobook_by_slug_assert_not_revoked(
                db_session,
                share_slug,
            )

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

            return PhotobookByShareSlugResponse(
                photobook=photobook_resp,
                giftcard=giftcard_resp,
                sender_display_name=share.sender_display_name,
            )

    @unauthenticated_route
    @enforce_response_model
    @posthog_capture()
    async def get_photobook_metadata_by_share_slug(
        self,
        share_slug: str,
    ) -> PhotobookMetadataResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            all_shares = await DALShares.list_all(
                db_session,
                {
                    "share_slug": (FilterOp.EQ, share_slug),
                },
                limit=1,
            )
            if not all_shares:
                raise HTTPException(status_code=404, detail="Share not found")
            share = all_shares[0]

            photobook = await DALPhotobooks.get_by_id(db_session, share.photobook_id)

            if photobook is None:
                raise HTTPException(status_code=404, detail="Photobook not found")
            return PhotobookMetadataResponse(title=photobook.title)

    @enforce_response_model
    @posthog_capture()
    async def share_photobook_initialize(
        self,
        photobook_id: UUID,
        payload: ShareCreateRequest,
        request: Request,
    ) -> ShareInitializeResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            request_context = await self.get_request_context(request)
            current_user_id = request_context.user_id
            share_resp: Optional[ShareCreateResponse] = None

            if payload.giftcard_request is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Giftcard request should be None for share_photobook_initialize.",
                )

            async with safe_transaction(
                db_session, "share_photobook_initialize", raise_on_fail=True
            ):
                # ownership check …
                _ = await self.get_photobook_assert_owned_by(
                    db_session, photobook_id, request_context.user_id
                )

                share_resp = await initialize_shares_and_channels_in_txn(
                    session=db_session,
                    user_id=request_context.user_id,
                    photobook_id=photobook_id,
                    req=payload,
                )

            if self.app.get_effect_mode(request) == "live":
                # Step 2: Enqueue outbox (no transaction needed)
                job_ids: list[UUID] = []
                for r in share_resp.recipients:
                    for ob in r.outbox_results:
                        job_id = await claim_and_enqueue_one_outbox(
                            session=db_session,
                            job_manager=self.app.remote_job_manager_io_bound,
                            outbox_id=ob.outbox_id,
                            worker_id="api-share-init",
                            lease_seconds=600,
                            user_id=request_context.user_id,
                        )
                        if job_id is not None:
                            job_ids.append(job_id)

            # Step 3: Render overview
            photobook_dao = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.user_id
            )
            resps = await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook_dao],
                db_session,
                self.app.asset_manager,
                requesting_user_id=current_user_id,
            )
            return ShareInitializeResponse(
                photobook=resps[0],
            )

    @enforce_response_model
    @posthog_capture()
    async def share_revoke(
        self,
        share_id: UUID,
        payload: RevokeShareRequest,
        request: Request,
    ) -> PhotobooksOverviewResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            request_context = await self.get_request_context(request)
            current_user_id = request_context.user_id
            async with safe_transaction(
                db_session, "revoke_share_in_txn", raise_on_fail=True
            ):
                (_, photobook_dao) = await self.get_share_and_photobook_assert_owned_by(
                    db_session, share_id, request_context.user_id
                )
                photobook_id = photobook_dao.id

                await revoke_share_in_txn(
                    session=db_session,
                    actor_user_id=request_context.user_id,
                    share_id=share_id,
                    photobook_id=photobook_id,
                    reason=payload.reason,
                )

            photobook_dao = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.user_id
            )
            resps = await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook_dao],
                db_session,
                self.app.asset_manager,
                requesting_user_id=current_user_id,
            )
            return resps[0]

    @enforce_response_model
    @posthog_capture()
    async def share_ensure_public(
        self,
        photobook_id: UUID,
        request: Request,
    ) -> PhotobooksOverviewResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            request_context = await self.get_request_context(request)

            # Verify ownership and ensure the public share under a transaction
            async with safe_transaction(
                db_session, "ensure_public_share", raise_on_fail=True
            ):
                # Ownership check
                photobook_dao = await self.get_photobook_assert_owned_by(
                    db_session, photobook_id, request_context.user_id
                )

                # Ensure there is exactly one PUBLIC share with ANYONE_WITH_LINK
                # (Idempotent and race-safe; preserves existing slug if present)
                _, _ = await ensure_public_share(
                    session=db_session,
                    user_id=request_context.user_id,
                    photobook_id=photobook_id,
                )

            # Return refreshed overview (mirrors other share endpoints)
            photobook_dao = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.user_id
            )
            resps = await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook_dao],
                db_session,
                self.app.asset_manager,
                requesting_user_id=request_context.user_id,
            )
            return resps[0]

    @enforce_response_model
    @posthog_capture()
    async def share_outbox_reschedule(
        self,
        outbox_id: UUID,
        payload: RescheduleRequest,
        request: Request,
    ) -> PhotobooksOverviewResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            request_context = await self.get_request_context(request)

            # Ownership check: find photobook_id for this outbox
            async with safe_transaction(
                db_session, "reschedule_ownership_check", raise_on_fail=True
            ):
                (
                    _,
                    photobook_dao,
                ) = await self.get_notification_outbox_row_and_photobook_assert_owned_by(
                    db_session, outbox_id, request_context.user_id
                )
                photobook_id = photobook_dao.id

            async with safe_transaction(
                db_session, "reschedule_outbox_in_txn", raise_on_fail=True
            ):
                try:
                    await reschedule_outbox_in_txn(
                        session=db_session,
                        outbox_id=outbox_id,
                        user_id=request_context.user_id,
                        new_scheduled_for=payload.scheduled_for,
                    )
                except RuntimeError as e:
                    # Map to 409 conflict for user-actionable states
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT, detail=str(e)
                    )

            photobook_dao = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.user_id
            )
            resps = await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook_dao],
                db_session,
                self.app.asset_manager,
                requesting_user_id=request_context.user_id,
            )
            return resps[0]

    @enforce_response_model
    @posthog_capture()
    async def share_outbox_send_now(
        self,
        outbox_id: UUID,
        request: Request,
    ) -> PhotobooksOverviewResponse:
        async with self.app.db_session_factory.new_session() as db_session:
            request_context = await self.get_request_context(request)

            # Ownership check
            async with safe_transaction(
                db_session, "reschedule_ownership_check", raise_on_fail=True
            ):
                (
                    _,
                    photobook_dao,
                ) = await self.get_notification_outbox_row_and_photobook_assert_owned_by(
                    db_session, outbox_id, request_context.user_id
                )
                photobook_id = photobook_dao.id

            async with safe_transaction(
                db_session, "reschedule_outbox_in_txn", raise_on_fail=True
            ):
                # 1) Reschedule to 'now'
                try:
                    _ = await reschedule_outbox_in_txn(
                        session=db_session,
                        outbox_id=outbox_id,
                        user_id=request_context.user_id,
                        new_scheduled_for=utcnow(),
                    )
                except RuntimeError as e:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT, detail=str(e)
                    )

            # 2) Try to claim + enqueue immediately (no-op if someone else beat us or it just got claimed by a sweeper)
            await claim_and_enqueue_one_outbox(
                session=db_session,
                job_manager=self.app.remote_job_manager_io_bound,
                outbox_id=outbox_id,
                user_id=request_context.user_id,
                worker_id="api-send-now",
                lease_seconds=600,
            )

            photobook_dao = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.user_id
            )
            resps = await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook_dao],
                db_session,
                self.app.asset_manager,
                requesting_user_id=request_context.user_id,
            )
            return resps[0]

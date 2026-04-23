import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALAssets,
    DALPhotobooksAssetsRel,
    DAOPhotobooksAssetsRelCreate,
    safe_commit,
)
from backend.db.data_models import AssetUploadStatus
from backend.lib.job_manager.protocol import JobManagerProtocol
from backend.lib.websocket.types import (
    AssetUploadStatusPayload,
)
from backend.worker.job_processor.types import (
    JobType,
    PostProcessUploadedAssetsInputPayload,
)


async def handle_asset_upload_status_update(
    user_id: UUID,
    payload: AssetUploadStatusPayload,
    db_session: AsyncSession,
    asset_processing_job_manager: JobManagerProtocol,
) -> None:
    succeeded_ids: set[UUID] = set(payload.succeeded)
    failed_map: dict[UUID, str] = {
        entry.asset_id: entry.error_msg for entry in payload.failed
    }

    if not succeeded_ids and not failed_map:
        logging.debug(
            f"[WS] Empty upload status payload for user_id={user_id}, skipping"
        )
        return

    db_changed_rows_succeeded: list[UUID] = []

    async with safe_commit(
        db_session,
        context="persist asset upload status",
        raise_on_fail=True,
    ):
        # Step 1: Mark successfully uploaded assets as SUCCEEDED (only if currently PENDING)
        if succeeded_ids:
            db_changed_rows_succeeded = (
                await DALAssets.bulk_update_status_where_pending(
                    session=db_session,
                    asset_ids=succeeded_ids,
                    user_id=user_id,
                    new_status=AssetUploadStatus.UPLOAD_SUCCEEDED,
                    current_matching_status=AssetUploadStatus.PENDING,
                )
            )
            if payload.associated_photobook_id:
                rels_to_create = [
                    DAOPhotobooksAssetsRelCreate(
                        photobook_id=payload.associated_photobook_id,
                        asset_id=asset_id,
                    )
                    for asset_id in db_changed_rows_succeeded
                ]
                if rels_to_create:
                    await DALPhotobooksAssetsRel.create_many(db_session, rels_to_create)
            logging.info(
                f"[WS] Marked {len(succeeded_ids)} assets as SUCCEEDED for user_id={user_id}"
            )

        # Step 2: Mark failed uploads as FAILED_CLIENT_UPLOAD (only if currently PENDING)
        if failed_map:
            failed_ids = set(failed_map.keys())
            await DALAssets.bulk_update_status_where_pending(
                session=db_session,
                asset_ids=failed_ids,
                user_id=user_id,
                new_status=AssetUploadStatus.UPLOAD_FAILED,
                current_matching_status=AssetUploadStatus.PENDING,
            )
            for asset_id, reason in failed_map.items():
                logging.warning(
                    f"[WS] Asset {asset_id} failed to upload for user_id={user_id}: {reason}"
                )

    # Enqueue asset background processing jobs
    if db_changed_rows_succeeded:
        await asset_processing_job_manager.enqueue(
            JobType.REMOTE_POST_PROCESS_UPLOADED_ASSETS,
            job_payload=PostProcessUploadedAssetsInputPayload(
                user_id=user_id,
                asset_ids=db_changed_rows_succeeded,
                originating_photobook_id=None,
            ),
            max_retries=2,
            db_session=db_session,
        )

# backend/worker/job_processor/remote_deliver_notification.py

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALNotificationDeliveryAttempts,
    DALNotificationOutbox,
    DALPhotobooks,
    DALShareChannels,
    DALShares,
    DAONotificationDeliveryAttemptsCreate,
    DAONotificationOutboxUpdate,
    locked_row_by_id,
    safe_commit,
    safe_transaction,
)
from backend.db.data_models import (
    DAONotificationOutbox,
    DAOPhotobooks,
    DAOShareChannels,
    DAOShares,
    NotificationDeliveryEvent,
    ShareAccessPolicy,
    ShareChannelStatus,
    ShareChannelType,
)
from backend.db.externals._overrides import PhotobooksOverviewResponse
from backend.lib.notifs.email.types import EmailAddress, EmailMessage
from backend.lib.utils.common import none_throws, utcnow
from backend.worker.process.types import RemoteIOBoundWorkerProcessResources

from .remote import RemoteJobProcessor
from .types import (
    DeliverNotificationInputPayload,
    DeliverNotificationOutputPayload,
)


class RemoteDeliverNotificationJobProcessor(
    RemoteJobProcessor[
        DeliverNotificationInputPayload,
        DeliverNotificationOutputPayload,
        RemoteIOBoundWorkerProcessResources,
    ]
):
    async def process(
        self, input_payload: DeliverNotificationInputPayload
    ) -> DeliverNotificationOutputPayload:
        now_ts = utcnow()
        async with self.db_session_factory.new_session() as db_session:
            # 1) Look up the outbox row (authoritative), plus its related records
            async with safe_transaction(db_session, "initial_check"):
                outbox = none_throws(
                    await DALNotificationOutbox.get_by_id(
                        db_session, input_payload.notification_outbox_id
                    ),
                    f"Invalid notification_outbox_id: {input_payload.notification_outbox_id}",
                )

                # Short-circuit if terminal (idempotency)
                if outbox.status in (
                    ShareChannelStatus.SENT,
                    ShareChannelStatus.CANCELED,
                ):
                    return DeliverNotificationOutputPayload(job_id=self.job_id)

                share_channel = none_throws(
                    await DALShareChannels.get_by_id(
                        db_session, outbox.share_channel_id
                    ),
                    f"Invalid share channel: {outbox.share_channel_id}",
                )
                share = none_throws(
                    await DALShares.get_by_id(db_session, outbox.share_id),
                    f"Invalid share: {outbox.share_id}",
                )
                photobook = none_throws(
                    await DALPhotobooks.get_by_id(db_session, outbox.photobook_id),
                    f"Invalid photobook: {outbox.photobook_id}",
                )

            # 2) Mark SENDING + log PROCESSING under lock
            #    (If another worker somehow got here, dispatch_token should have prevented it,
            #     but we still guard with a tiny transactional update.)
            email_provider = self.worker_process_resources.email_provider_client

            async with safe_transaction(db_session, "notif start -> SENDING"):
                async with locked_row_by_id(
                    db_session, DAONotificationOutbox, outbox.id
                ) as locked_outbox:
                    if locked_outbox.status in (
                        ShareChannelStatus.SENT,
                        ShareChannelStatus.CANCELED,
                    ):
                        # Someone else finished or it was canceled between reads
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    # defensive: if not claimed, do nothing (shouldn’t happen if enqueue only after claim)
                    if locked_outbox.dispatch_token is None:
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    if (
                        locked_outbox.dispatch_token
                        != input_payload.expected_dispatch_token
                    ):
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    if (
                        locked_outbox.dispatch_lease_expires_at
                        and locked_outbox.dispatch_lease_expires_at <= now_ts
                    ):
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    # bail if revoked post-claim
                    if share.access_policy == ShareAccessPolicy.REVOKED:
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    # bail if share channel is archived
                    if share_channel.archived_at is not None:
                        return DeliverNotificationOutputPayload(job_id=self.job_id)

                    # Move to SENDING and (optionally) record provider being used
                    await DALNotificationOutbox.update_by_id(
                        db_session,
                        locked_outbox.id,
                        DAONotificationOutboxUpdate(
                            status=ShareChannelStatus.SENDING,
                            provider=email_provider.get_share_provider(),
                            last_error=None,
                        ),
                    )

                    # Append processing attempt (with outbox linkage)
                    await DALNotificationDeliveryAttempts.create(
                        db_session,
                        DAONotificationDeliveryAttemptsCreate(
                            notification_outbox_id=locked_outbox.id,
                            share_channel_id=share_channel.id,
                            notification_type=locked_outbox.notification_type,
                            channel_type=locked_outbox.channel_type,
                            provider=email_provider.get_share_provider(),
                            event=NotificationDeliveryEvent.PROCESSING,
                        ),
                    )

            # 3) Deliver based on channel type
            if outbox.channel_type == ShareChannelType.EMAIL:
                await self._process_email_notif(
                    db_session=db_session,
                    outbox=outbox,
                    share_channel=share_channel,
                    share=share,
                    photobook=photobook,
                )
            elif outbox.channel_type == ShareChannelType.SMS:
                # TODO: implement SMS provider send + similar logging
                raise NotImplementedError("SMS delivery not yet implemented")
            elif outbox.channel_type == ShareChannelType.APNS:
                # TODO: implement APNS provider send + similar logging
                raise NotImplementedError("APNS delivery not yet implemented")
            else:
                raise RuntimeError(f"Unrecognized channel type: {outbox.channel_type}")

            return DeliverNotificationOutputPayload(job_id=self.job_id)

    async def _process_email_notif(
        self,
        *,
        db_session: AsyncSession,
        outbox: DAONotificationOutbox,
        share_channel: DAOShareChannels,
        share: DAOShares,
        photobook: DAOPhotobooks,
    ) -> None:
        provider_client = self.worker_process_resources.email_provider_client
        provider = provider_client.get_share_provider()

        rendered_photobook: PhotobooksOverviewResponse = (
            await PhotobooksOverviewResponse.rendered_from_daos(
                [photobook],
                db_session,
                self.asset_manager,
            )
        )[0]

        # Build message (keep idempotency key stable per (outbox, channel))
        msg = EmailMessage(
            subject=f"{photobook.title} from {share.sender_display_name or ''}",
            from_=EmailAddress(
                email="hello@snapgifts.app", name=share.sender_display_name
            ),
            to_=[
                EmailAddress(
                    email=share_channel.destination,
                    name=share.recipient_display_name,
                )
            ],
            html=(
                self._get_email_html(
                    photobook_title=photobook.title,
                    sender_name=f"{share.sender_display_name or 'A friend'} from Memry",
                    share_url=f"https://snapgifts.app/share/{share.share_slug}",
                    recipient_name=share.recipient_display_name or "",
                    cover_url=rendered_photobook.thumbnail_asset_signed_url,
                )
            ),
            idempotency_key=f"{outbox.notification_type.value}_{outbox.share_channel_id}_{outbox.id}",
        )

        try:
            # ACTUAL SEND with side effects!
            send_result = await provider_client.send(msg)
            # send_result = EmailSendResult(message_id="123", idempotency_key="456")

            # On success: mark SENT + store provider message id; append attempt=SENT
            async with safe_commit(db_session, "notif email SENT", raise_on_fail=True):
                await DALNotificationOutbox.update_by_id(
                    db_session,
                    outbox.id,
                    DAONotificationOutboxUpdate(
                        status=ShareChannelStatus.SENT,
                        last_provider_message_id=send_result.message_id,
                        provider=provider,
                        dispatch_token=None,
                    ),
                )
                await DALNotificationDeliveryAttempts.create(
                    db_session,
                    DAONotificationDeliveryAttemptsCreate(
                        notification_outbox_id=outbox.id,
                        share_channel_id=share_channel.id,
                        notification_type=outbox.notification_type,
                        channel_type=outbox.channel_type,
                        provider=provider,
                        event=NotificationDeliveryEvent.SENT,
                        payload={"result": send_result.model_dump(mode="json")},
                    ),
                )

        except Exception as e:
            # On failure: mark FAILED + record error; append attempt=FAILED
            async with safe_commit(
                db_session, "notif email FAILED", raise_on_fail=False
            ):
                await DALNotificationOutbox.update_by_id(
                    db_session,
                    outbox.id,
                    DAONotificationOutboxUpdate(
                        status=ShareChannelStatus.FAILED,
                        last_error=str(e),
                        provider=provider,
                        dispatch_token=None,
                    ),
                )
                await DALNotificationDeliveryAttempts.create(
                    db_session,
                    DAONotificationDeliveryAttemptsCreate(
                        notification_outbox_id=outbox.id,
                        share_channel_id=share_channel.id,
                        notification_type=outbox.notification_type,
                        channel_type=outbox.channel_type,
                        provider=provider,
                        event=NotificationDeliveryEvent.FAILED,
                        payload={"error": str(e)},
                    ),
                )
            # Re-raise so the job framework can mark the job attempt as failed
            raise

    def _get_email_html(
        self,
        photobook_title: str,
        sender_name: str,
        share_url: str,
        recipient_name: str,
        cover_url: str | None,
    ) -> str:
        cover_img_html = (
            f'<tr><td style="padding:0 24px 8px 24px;" align="center">'
            f'  <img src="{cover_url}" width="552" alt="{photobook_title}" style="border:0;outline:none;text-decoration:none;width:100%;max-width:552px;height:auto;border-radius:12px;display:block;" />'
            f"</td></tr>"
            if cover_url
            else ""
        )

        html = f"""\
            <!doctype html>
            <html lang="en" xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <meta charset="utf-8"/>
                <meta name="viewport" content="width=device-width"/>
                <meta http-equiv="x-ua-compatible" content="ie=edge"/>
                <title>{photobook_title} — Memry</title>
                <!-- Preheader (hidden) -->
                <style>
                .preheader {{
                    display:none !important; visibility:hidden; opacity:0; color:transparent; height:0; width:0; overflow:hidden;
                    mso-hide:all; line-height:0; font-size:0;
                }}
                @media (prefers-color-scheme: dark) {{
                    .dark-bg {{ background:#0b0b0c !important; }}
                    .dark-card {{ background:#1a1b1e !important; }}
                    .dark-text {{ color:#e5e7eb !important; }}
                    .dark-muted {{ color:#9ca3af !important; }}
                    .btn-primary {{ background:#16a34a !important; }}
                }}
                a[x-apple-data-detectors] {{ color:inherit !important; text-decoration:none !important; }}
                </style>
            </head>
            <body style="margin:0; padding:0; background:#f3f4f6;" class="dark-bg">
                <div class="preheader">You’ve received “{photobook_title}” from {sender_name}. Open your gift.</div>
                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f3f4f6;" class="dark-bg">
                <tr>
                    <td align="center" style="padding:32px 12px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px; background:#ffffff; border-radius:16px;"
                            class="dark-card">
                        <!-- Header -->
                        <tr>
                        <td align="left" style="padding:24px 24px 8px 24px;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td align="left">
                                <a href="https://mems.sh" style="text-decoration:none;">
                                    <img src="https://mems.sh/tl_logo.png" width="28" height="28" alt="Memry"
                                        style="display:block;border:0;outline:none;text-decoration:none;">
                                </a>
                                </td>
                                <td align="right" style="font:500 14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#6b7280;"
                                    class="dark-muted">
                                {sender_name}
                                </td>
                            </tr>
                            </table>
                        </td>
                        </tr>

                        <!-- Title -->
                        <tr>
                        <td style="padding:8px 24px 4px 24px; font:700 22px/1.2 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#111827;"
                            class="dark-text">
                            {photobook_title}
                        </td>
                        </tr>

                        <!-- Subheading -->
                        <tr>
                        <td style="padding:0 24px 16px 24px; font:400 15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#374151;"
                            class="dark-text">
                            {recipient_name and f"{recipient_name}," or ""} you’ve received a photo gift from <strong>{sender_name}</strong>.
                        </td>
                        </tr>

                        {cover_img_html}

                        <!-- Body copy -->
                        <tr>
                        <td style="padding:0 24px 20px 24px; font:400 15px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#374151;"
                            class="dark-text">
                            Open it to view the memories, leave a note, and save your favorites.
                        </td>
                        </tr>

                        <!-- Button (bulletproof) -->
                        <tr>
                        <td align="center" style="padding:0 24px 28px 24px;">
                            <table role="presentation" cellpadding="0" cellspacing="0">
                            <tr>
                                <td align="center" bgcolor="#22c55e" class="btn-primary"
                                    style="border-radius:999px; background:#22c55e;">
                                <a href="{share_url}" target="_blank"
                                    style="display:inline-block; padding:14px 24px; font:600 15px/1 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#ffffff; text-decoration:none; border-radius:999px;">
                                    Open Your Gift
                                </a>
                                </td>
                            </tr>
                            </table>
                        </td>
                        </tr>

                        <!-- Fallback URL -->
                        <tr>
                        <td style="padding:0 24px 24px 24px; font:400 12px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#6b7280;"
                            class="dark-muted">
                            If the button doesn’t work, copy and paste this link into your browser:<br>
                            <a href="{share_url}" style="color:#16a34a; text-decoration:underline;">{share_url}</a>
                        </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                        <td style="padding:16px 24px 24px 24px; font:400 12px/1.6 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:#9ca3af;"
                            align="center" class="dark-muted">
                            You’re receiving this because a friend shared a gift with you via Memry.
                            <br/>© {utcnow().year} Memry. All rights reserved.
                        </td>
                        </tr>
                    </table>

                    <!-- View in browser (optional) -->
                    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;">
                        <tr><td style="height:16px;">&nbsp;</td></tr>
                    </table>
                    </td>
                </tr>
                </table>
            </body>
            </html>
            """

        return html

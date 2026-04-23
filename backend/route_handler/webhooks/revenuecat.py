from typing import Any

from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from backend.db.dal import (
    DALSubscriptionEvents,
    FilterOp,
    safe_transaction,
)
from backend.db.data_models import SubscriptionEventSource
from backend.env_loader import EnvLoader
from backend.lib.subscription.service import (
    StatusApplyContext,
    parse_rc_payload,
    reconcile_and_apply_subscription_status_in_txn,
)
from backend.route_handler.base import (
    RouteHandler,
    enforce_response_model,
    unauthenticated_route,
)


class WebhookAck(BaseModel):
    received: bool = True


AUTH_HEADER_NAME = EnvLoader.get("REVENUECAT_WEBHOOK_AUTH_HEADER", "Authorization")
REVENUECAT_WEBHOOK_AUTH = EnvLoader.get("REVENUECAT_WEBHOOK_AUTH")


def verify_authorization(request: Request) -> None:
    incoming = request.headers.get(AUTH_HEADER_NAME, "")
    if not REVENUECAT_WEBHOOK_AUTH:
        raise HTTPException(status_code=500, detail="webhook auth not configured")
    if incoming.strip() != f"Bearer {REVENUECAT_WEBHOOK_AUTH}":
        raise HTTPException(status_code=401, detail="unauthorized webhook")


class RevenueCatWebhookAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route("/api/webhooks/revenuecat", "rc_webhook", methods=["POST"])

    @unauthenticated_route
    @enforce_response_model
    async def rc_webhook(self, request: Request) -> WebhookAck:
        verify_authorization(request)

        # 1) get payload
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
            )

        # 2) parse & basic validation
        try:
            snap, _ = parse_rc_payload(payload)
        except Exception:
            # Can't interpret; ack 200 to avoid retries but do nothing
            return WebhookAck()

        # 3) dedupe on rc_event_id (append-only audit)
        async with self.app.db_session_factory.new_session() as session:
            async with safe_transaction(session, "rc_webhook.event_dedupe"):
                if snap.event_id:
                    dup = await DALSubscriptionEvents.list_all(
                        session,
                        filters={"rc_event_id": (FilterOp.EQ, snap.event_id)},
                        limit=1,
                    )
                    if dup:
                        return WebhookAck()

            # 4) reconcile/apply (idempotent FSM)
            async with safe_transaction(session, "rc_webhook.status_apply"):
                # NOTE: our auth is a bearer secret, so we treat it as signature_verified=True
                (
                    _,
                    _applied_status,
                    _did_advance,
                ) = await reconcile_and_apply_subscription_status_in_txn(
                    session,
                    user_id=snap.user_id,
                    snap=snap,
                    ctx=StatusApplyContext(
                        source=SubscriptionEventSource.RC_WEBHOOK,
                        rc_event_type=snap.event_type,
                        rc_event_id=snap.event_id,
                        signature_verified=True,
                        extra_payload={"path": "webhook_status_apply"},
                    ),
                )

        return WebhookAck()

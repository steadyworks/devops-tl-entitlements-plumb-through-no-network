# backend/route_handler/entitlement.py

from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel

from backend.db.dal import DALEntitlements, safe_transaction
from backend.db.dal.base import FilterOp
from backend.lib.posthog import posthog_capture
from backend.route_handler.base import RouteHandler, enforce_response_model

if TYPE_CHECKING:
    from backend.db.data_models import DAOEntitlements

# ---------- Response models ----------


class EntitlementInfo(BaseModel):
    active: bool
    expires_at: Optional[datetime] = None


class EntitlementStatusResponse(BaseModel):
    active: bool  # overall gate (derived from "pro")
    plan: str  # "pro" | "free"
    entitlements: Dict[str, EntitlementInfo]


# ---------- Handler ----------


class EntitlementAPIHandler(RouteHandler):
    """
    Returns the canonical entitlement snapshot for the authenticated user.
    Web and native should reflect this value for gating (web relies on this as source of truth).
    """

    def register_routes(self) -> None:
        self.route("/api/me/entitlement", "me_entitlement", methods=["GET"])

    @enforce_response_model
    @posthog_capture()
    async def me_entitlement(self, request: Request) -> EntitlementStatusResponse:
        """
        Reads the 'pro' entitlement for the current user and returns a compact snapshot.

        Contract with client:
        - `active` mirrors entitlements['pro'].active
        - `plan` is "pro" if active else "free"
        - `expires_at` is present when known (subscriptions) else null
        """
        async with self.app.db_session_factory.new_session() as session:
            rcx = await self.get_request_context(
                request
            )  # provides rcx.user_id, role, etc.

            # Small transaction wrapper for consistent reads & easy extension
            async with safe_transaction(
                session, "read entitlement (pro)", raise_on_fail=True
            ):
                ents: List[DAOEntitlements] = await DALEntitlements.list_all(
                    session, filters={"user_id": (FilterOp.EQ, rcx.user_id)}
                )
                ent = ents[0] if ents else None

                # If expire, we should have a signal from RC and
                # is_active will be set to False in the webhook.
                is_active = bool(ent and ent.active)
                expires_at: Optional[datetime] = getattr(ent, "expires_at", None)

                return EntitlementStatusResponse(
                    active=is_active,
                    plan="pro" if is_active else "free",
                    entitlements={
                        "pro": EntitlementInfo(active=is_active, expires_at=expires_at)
                    },
                )

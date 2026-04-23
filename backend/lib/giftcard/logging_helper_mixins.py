import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncIterator, Optional, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALGiftcardEvents,
    DAOGiftcardEventsCreate,
    safe_transaction,
)
from backend.db.data_models import GiftcardEventKind, GiftcardProvider


def _json_sanitize(obj: Any) -> Any:
    """Recursively coerce common Python/typing objects into JSON-serializable forms."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value  # e.g., CurrencyCode.USD -> "USD"
    if isinstance(obj, dict):
        obj = cast("dict[str, Any]", obj)
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        obj = cast("list[Any]", obj)
        return [_json_sanitize(v) for v in obj]
    # Best-effort fallback
    try:
        return str(obj)
    except Exception:
        return "<UNSERIALIZABLE>"


class GiftcardEventLoggingHelperMixins:
    async def _log_giftcard_event(
        self,
        session: AsyncSession,
        *,
        kind: GiftcardEventKind,
        giftcard_id: UUID,
        provider: GiftcardProvider,
        message: Optional[str] = None,
        payload_json: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Fire-and-forget-ish logger: failures to write the event are logged but won't
        break the caller. Uses its own short transaction to ensure durability even
        if the caller rolls back later.

        IMPORTANT: Must be called when NO transaction is currently open on `session`.
        """
        if session.in_transaction():
            raise RuntimeError(
                "[log_giftcard_event] Must be called with no active transaction on the session. "
                "Commit/close the caller transaction first."
            )

        try:
            sanitized_payload = _json_sanitize(payload_json or {})
            async with safe_transaction(
                session, context=f"log_giftcard_event/{kind.value}", raise_on_fail=False
            ):
                await DALGiftcardEvents.create(
                    session,
                    DAOGiftcardEventsCreate(
                        giftcard_id=giftcard_id,
                        provider=provider,
                        kind=kind,
                        message=message,
                        payload_json=sanitized_payload,  # always safe JSON
                    ),
                )
        except Exception:
            logging.exception("[giftcard_events] failed to write event")
            # swallow; do not re-raise

    @asynccontextmanager
    async def event_span(
        self,
        session: AsyncSession,
        *,
        kind_attempt: GiftcardEventKind,
        kind_success: GiftcardEventKind,
        kind_failure: GiftcardEventKind,
        giftcard_id: UUID,
        provider: GiftcardProvider,
        attempt_message: str,
        attempt_payload: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Logs ATTEMPT on enter. On normal exit logs SUCCESS; on exception logs FAILURE and re-raises.
        Must be called with no active transaction (each log uses its own tiny tx).
        Yields a dict the caller can populate with fields to be included in SUCCESS payload.
        """
        await self._log_giftcard_event(
            session,
            kind=kind_attempt,
            giftcard_id=giftcard_id,
            provider=provider,
            message=attempt_message,
            payload_json=attempt_payload or {},
        )
        try:
            success_payload: dict[str, Any] = {}
            yield success_payload
            await self._log_giftcard_event(
                session,
                kind=kind_success,
                giftcard_id=giftcard_id,
                provider=provider,
                message=f"{attempt_message} succeeded",
                payload_json=success_payload,
            )
        except Exception as e:
            import traceback

            await self._log_giftcard_event(
                session,
                kind=kind_failure,
                giftcard_id=giftcard_id,
                provider=provider,
                message=f"{attempt_message} failed",
                payload_json={
                    "error_type": e.__class__.__name__,
                    "error_msg": str(e),
                    "error_tb": traceback.format_exc(),
                },
            )
            raise

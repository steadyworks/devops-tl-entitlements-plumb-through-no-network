# backend/lib/payments/payment_event_logging.py

import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncIterator, Optional, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALPaymentEvents,
    DAOPaymentEventsCreate,
    safe_transaction,
)
from backend.db.data_models import PaymentEventSource, PaymentStatus


def _json_sanitize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        obj = cast("dict[str, Any]", obj)
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        obj = cast("list[Any]", obj)
        return [_json_sanitize(v) for v in obj]
    try:
        return str(obj)
    except Exception:
        return "<UNSERIALIZABLE>"


class PaymentEventLoggingHelperMixins:
    @classmethod
    async def _log_payment_event(
        cls,
        session: AsyncSession,
        *,
        payment_id: UUID,
        source: PaymentEventSource,
        event_type: str,  # e.g., "fulfill.attempt" | "fulfill.success" | "fulfill.failed"
        message: Optional[str] = None,
        payload_json: Optional[dict[str, Any]] = None,
        applied_status: Optional[PaymentStatus] = None,
    ) -> None:
        """
        Fire-and-forget-ish logger: uses its own short transaction so the write
        survives caller rollback. MUST be called with NO active transaction.
        """
        if session.in_transaction():
            raise RuntimeError(
                "[_log_payment_event] Must be called with no active transaction on the session."
            )

        try:
            sanitized_payload = _json_sanitize(payload_json or {})
            async with safe_transaction(
                session, context=f"log_payment_event/{event_type}", raise_on_fail=False
            ):
                await DALPaymentEvents.create(
                    session,
                    DAOPaymentEventsCreate(
                        payment_id=payment_id,
                        stripe_event_id=None,
                        event_type=event_type,
                        stripe_event_type=None,
                        source=source,
                        payload=sanitized_payload,
                        signature_verified=None,
                        applied_status=applied_status,
                    ),
                )
        except Exception:
            logging.exception("[payment_events] failed to write event")

    @classmethod
    @asynccontextmanager
    async def payment_event_span(
        cls,
        session: AsyncSession,
        *,
        payment_id: UUID,
        source: PaymentEventSource,
        attempt_event: str,
        success_event: str,
        failure_event: str,
        attempt_message: str,
        attempt_payload: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        ATTEMPT on enter; SUCCESS on normal exit; FAILURE on exception.
        Each write uses its own tiny tx. Must be called with no active transaction.
        Yields a dict callers can add to; it will be merged into SUCCESS payload.
        """
        await cls._log_payment_event(
            session,
            payment_id=payment_id,
            source=source,
            event_type=attempt_event,
            message=attempt_message,
            payload_json=attempt_payload or {},
        )
        try:
            success_payload: dict[str, Any] = {}
            yield success_payload
            await cls._log_payment_event(
                session,
                payment_id=payment_id,
                source=source,
                event_type=success_event,
                message=f"{attempt_message} succeeded",
                payload_json=success_payload,
            )
        except Exception as e:
            import traceback

            await cls._log_payment_event(
                session,
                payment_id=payment_id,
                source=source,
                event_type=failure_event,
                message=f"{attempt_message} failed",
                payload_json={
                    "error_type": e.__class__.__name__,
                    "error_msg": str(e),
                    "error_tb": traceback.format_exc(),
                    **(attempt_payload or {}),
                },
            )
            raise

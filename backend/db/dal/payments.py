from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import (
    DAOPayments,
)
from backend.lib.utils.common import utcnow

from .base import (
    AsyncPostgreSQLDAL,
)
from .schemas import (
    DAOPaymentsCreate,
    DAOPaymentsUpdate,
)


class DALPayments(
    AsyncPostgreSQLDAL[
        DAOPayments,
        DAOPaymentsCreate,
        DAOPaymentsUpdate,
    ]
):
    ENSURE_JSON_SAFETY_FIELDS = {"metadata_json"}
    model = DAOPayments

    @staticmethod
    async def upsert_by_stripe_pi(
        session: AsyncSession,
        payload: DAOPaymentsCreate,
    ) -> DAOPayments:
        """
        Insert or update by UNIQUE (stripe_payment_intent_id).
        Returns the row after upsert.
        """
        now = utcnow()
        values: dict[str, Any] = {
            "id": payload.id,  # assuming your create payload sets an id; else let DB default
            "created_by_user_id": payload.created_by_user_id,
            "photobook_id": payload.photobook_id,
            "purpose": payload.purpose,
            "amount_total": payload.amount_total,
            "currency": payload.currency,
            "stripe_payment_intent_id": payload.stripe_payment_intent_id,
            "stripe_customer_id": payload.stripe_customer_id,
            "stripe_payment_method_id": payload.stripe_payment_method_id,
            "stripe_latest_charge_id": payload.stripe_latest_charge_id,
            "status": payload.status,
            "description": payload.description,
            "receipt_email": payload.receipt_email,
            "idempotency_key": payload.idempotency_key,
            "failure_code": payload.failure_code,
            "failure_message": payload.failure_message,
            "refunded_amount": payload.refunded_amount,
            "metadata_json": payload.metadata_json,
            "share_create_request": payload.share_create_request,
            # !!! intentionally omit fulfilled_at & fulfillment_last_error
            "created_at": now,  # will be ignored on conflict
            "updated_at": now,
        }

        stmt = (
            pg_insert(DAOPayments)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[getattr(DAOPayments, "stripe_payment_intent_id")],
                set_={
                    # “mutable” columns we want to refresh if we raced:
                    "stripe_latest_charge_id": values["stripe_latest_charge_id"],
                    # !!! intentionally omit fulfilled_at & fulfillment_last_error
                    "updated_at": values["updated_at"],
                },
            )
            .returning(DAOPayments)
        )

        res = await session.execute(stmt)
        row = res.scalar_one()
        return row

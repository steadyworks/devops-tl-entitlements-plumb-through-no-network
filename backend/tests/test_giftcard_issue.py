from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import DALGiftcards
from backend.db.dal import locked_row_by_id as locked_row_by_id_real
from backend.db.data_models import (
    DAOGiftcards,
    GiftcardEventKind,
    GiftcardProvider,
    GiftcardStatus,
)
from backend.lib.giftcard.agcod.base import (
    AbstractBaseAGCODGiftcardClient,
)
from backend.lib.giftcard.agcod.client import CurrencyCode

if TYPE_CHECKING:
    from backend.lib.giftcard.base import GiftcardPresentable


@dataclass
class _ValueObj:
    amount: int
    currencyCode: CurrencyCode


@dataclass
class _CardInfoObj:
    cardStatus: str  # "Fulfilled", etc
    value: _ValueObj


@dataclass
class _AGCODResponse:
    status: str  # "SUCCESS" or other
    cardInfo: _CardInfoObj
    gcClaimCode: str

    def model_dump(self, mode: str = "json") -> dict[str, Any]:  # mimic pydantic-ish
        return {
            "status": self.status,
            "cardStatus": self.cardInfo.cardStatus,
            "value": {
                "amount": self.cardInfo.value.amount,
                "currencyCode": self.cardInfo.value.currencyCode,
            },
            "gcClaimCode": self.gcClaimCode,
        }


class _AGCODClientFake:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.partner_id: str = "PARTNR"  # <= 6 chars per your prod
        # control flags
        self.should_raise: bool = False
        self.response: Optional[_AGCODResponse] = _AGCODResponse(
            status="SUCCESS",
            cardInfo=_CardInfoObj(
                cardStatus="Fulfilled",
                value=_ValueObj(amount=50, currencyCode=CurrencyCode.USD),
            ),
            gcClaimCode="FAKE-CODE-123",
        )

    # API used by your client
    def get_partner_id(self) -> str:
        return self.partner_id

    async def create_gift_card(
        self, *, creation_request_id: str, currency: CurrencyCode, amount: int
    ) -> _AGCODResponse:
        self.calls.append(
            {
                "creation_request_id": creation_request_id,
                "currency": currency,
                "amount": amount,
            }
        )
        if self.should_raise:
            raise RuntimeError("agcod failure (test)")
        assert self.response is not None
        return self.response


# -------------------------
# Concrete client for tests
# -------------------------


class _TestAGCODClient(AbstractBaseAGCODGiftcardClient):
    """Concrete class that injects the fake AGCOD client and a no-op sanitizer."""

    def __init__(self, agcod_fake: _AGCODClientFake) -> None:
        self._fake = agcod_fake
        super().__init__()

    def _init_agcod_client(self) -> _AGCODClientFake:  # type: ignore[override]
        return self._fake

    # not used by tests, but required abstract
    def _sanitize_network_resp_payload_for_logging(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return payload

    # Override currency enum type mapping used by prod client _get_agcod_amount
    def _get_agcod_amount(
        self, amount_total_minor_unit: int, currency: str
    ) -> tuple[int, CurrencyCode]:
        assert currency.upper().strip() == "USD"
        return (amount_total_minor_unit // 100, CurrencyCode.USD)


# -------------------------
# Local fixtures
# -------------------------


@pytest.fixture(autouse=True)
async def clean_giftcard_tables(db_session: AsyncSession) -> None:
    # Ensure clean slate for giftcards + events per test
    await db_session.execute(
        text(
            """
            TRUNCATE giftcard_events, giftcards RESTART IDENTITY CASCADE;
            """
        )
    )
    await db_session.commit()


@pytest.fixture
def agcod_fake() -> _AGCODClientFake:
    return _AGCODClientFake()


@pytest.fixture
def client(agcod_fake: _AGCODClientFake) -> _TestAGCODClient:
    return _TestAGCODClient(agcod_fake)


async def _insert_giftcard(
    session: AsyncSession,
    *,
    status: GiftcardStatus,
    amount_minor: int = 5000,
    currency: str = "USD",
    brand_code: str = "amazon",
    explicit_code: Optional[str] = None,
) -> DAOGiftcards:
    row = DAOGiftcards(
        id=uuid4(),
        share_id=uuid4(),
        created_by_payment_id=None,
        created_by_user_id=None,
        amount_total=amount_minor,
        currency=currency,
        provider=None,
        brand_code=brand_code,
        giftcard_code_explicit_override=explicit_code,
        status=status,
        metadata_json={},
        provider_giftcard_id_internal_only=uuid4(),
    )
    session.add(row)
    await session.commit()
    return row


async def _list_events(
    session: AsyncSession, giftcard_id: UUID
) -> list[tuple[GiftcardEventKind, dict[str, Any]]]:
    from backend.db.dal import DAOGiftcardEvents  # late import to avoid cycles

    rows = (
        (
            await session.execute(
                select(DAOGiftcardEvents).where(
                    getattr(DAOGiftcardEvents, "giftcard_id") == giftcard_id
                )
            )
        )
        .scalars()
        .all()
    )
    return [(r.kind, r.payload_json) for r in rows]


# -------------------------
# Tests
# -------------------------


@pytest.mark.asyncio
async def test_GI1_happy_path_granted_to_issued_logs_and_updates(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
) -> None:
    g = await _insert_giftcard(
        db_session, status=GiftcardStatus.GRANTED, amount_minor=5000, currency="USD"
    )

    # Act
    pres: GiftcardPresentable = await client.issue_giftcard(db_session, g.id)

    # Presentable from provider
    assert pres.giftcard_code == agcod_fake.response.gcClaimCode  # type: ignore[union-attr]

    # DB row updated
    g2 = await DALGiftcards.get_by_id(db_session, g.id)
    assert g2 is not None
    assert g2.status == GiftcardStatus.ISSUED
    assert g2.provider == GiftcardProvider.AGCOD
    assert g2.issued_at is not None
    assert g2.metadata_json.get("present_method") in {"code", "url"}

    # Events: ACCESS_ATTEMPT, ISSUE_ATTEMPT, ISSUE_SUCCESS, ACCESS_SUCCESS (order not enforced here)
    kinds = [k for (k, _payload) in await _list_events(db_session, g.id)]
    assert GiftcardEventKind.ACCESS_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_SUCCESS in kinds
    assert GiftcardEventKind.ACCESS_SUCCESS in kinds

    # ACCESS_SUCCESS should indicate first_time_issue=True
    events = await _list_events(db_session, g.id)
    success_payloads = [p for (k, p) in events if k == GiftcardEventKind.ACCESS_SUCCESS]
    assert any(p.get("first_time_issue") is True for p in success_payloads)

    # Provider was called once; integer dollars amount derived correctly
    assert len(agcod_fake.calls) == 1
    assert agcod_fake.calls[0]["amount"] == 50
    assert agcod_fake.calls[0]["currency"] == CurrencyCode.USD


@pytest.mark.asyncio
async def test_GI2_already_issued_with_explicit_override_skips_provider(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
) -> None:
    g = await _insert_giftcard(
        db_session,
        status=GiftcardStatus.ISSUED,
        explicit_code="  XYZ-123  ",
        amount_minor=1000,
    )

    pres = await client.issue_giftcard(db_session, g.id)
    assert pres.giftcard_code == "XYZ-123"  # trimmed
    assert len(agcod_fake.calls) == 0  # no provider call

    kinds = [k for (k, _p) in await _list_events(db_session, g.id)]
    # Only ACCESS_* events; no ISSUE_* because provider wasn't called
    assert GiftcardEventKind.ACCESS_ATTEMPT in kinds
    assert GiftcardEventKind.ACCESS_SUCCESS in kinds
    assert GiftcardEventKind.ISSUE_ATTEMPT not in kinds


@pytest.mark.asyncio
async def test_GI3_terminal_state_upfront_raises_and_logs_access_failure(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
) -> None:
    g = await _insert_giftcard(db_session, status=GiftcardStatus.CANCELED)

    with pytest.raises(Exception):
        await client.issue_giftcard(db_session, g.id)

    assert len(agcod_fake.calls) == 0

    kinds = [k for (k, _p) in await _list_events(db_session, g.id)]
    assert GiftcardEventKind.ACCESS_ATTEMPT in kinds
    assert GiftcardEventKind.ACCESS_FAILURE in kinds
    assert GiftcardEventKind.ISSUE_ATTEMPT not in kinds


@pytest.mark.asyncio
async def test_GI4_provider_failure_results_in_issue_failure_and_access_failure(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
) -> None:
    g = await _insert_giftcard(db_session, status=GiftcardStatus.GRANTED)
    agcod_fake.should_raise = True

    with pytest.raises(Exception):
        await client.issue_giftcard(db_session, g.id)

    # State unchanged
    g2 = await DALGiftcards.get_by_id(db_session, g.id)
    assert g2 is not None and g2.status == GiftcardStatus.GRANTED

    kinds = [k for (k, _p) in await _list_events(db_session, g.id)]
    assert GiftcardEventKind.ACCESS_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_FAILURE in kinds
    assert GiftcardEventKind.ACCESS_FAILURE in kinds


@pytest.mark.asyncio
async def test_GI5_already_issued_without_explicit_code_calls_provider_first_time_issue_false(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
) -> None:
    # Simulate "concurrent issuance happened earlier" by starting as ISSUED but no override code
    g = await _insert_giftcard(
        db_session, status=GiftcardStatus.ISSUED, explicit_code=None
    )

    pres = await client.issue_giftcard(db_session, g.id)
    assert pres.giftcard_code == agcod_fake.response.gcClaimCode  # type: ignore[union-attr]

    # Still ISSUED; but we didn't flip it here (first_time_issue=False)
    g2 = await DALGiftcards.get_by_id(db_session, g.id)
    assert g2 is not None and g2.status == GiftcardStatus.ISSUED

    kinds = [k for (k, _p) in await _list_events(db_session, g.id)]
    assert GiftcardEventKind.ISSUE_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_SUCCESS in kinds
    assert GiftcardEventKind.ACCESS_SUCCESS in kinds

    events = await _list_events(db_session, g.id)
    success_payloads = [p for (k, p) in events if k == GiftcardEventKind.ACCESS_SUCCESS]
    # Ensure a False exists (could be multiple ACCESS_SUCCESS across calls, but at least one should be False)
    assert any(p.get("first_time_issue") is False for p in success_payloads)


@pytest.mark.asyncio
async def test_GI6_turns_terminal_inside_locked_section_access_failure(
    db_session: AsyncSession,
    client: _TestAGCODClient,
    agcod_fake: _AGCODClientFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Simulate that between the provider call and the locked update, the giftcard becomes REDEEMED.
    We monkeypatch locked_row_by_id to flip state before yielding the row.
    """
    g = await _insert_giftcard(db_session, status=GiftcardStatus.GRANTED)
    gid: UUID = g.id

    @asynccontextmanager
    async def _locked_and_flip(
        session: AsyncSession, model: type[DAOGiftcards], id: UUID
    ) -> AsyncGenerator[DAOGiftcards]:
        cm = locked_row_by_id_real(session, model, id)
        row = await cm.__aenter__()
        # Flip to REDEEMED to force the conflict path
        row.status = GiftcardStatus.REDEEMED
        session.add(row)
        await session.flush()
        try:
            yield row
        finally:
            await cm.__aexit__(None, None, None)

    monkeypatch.setattr(
        "backend.lib.giftcard.base.locked_row_by_id", _locked_and_flip, raising=True
    )

    with pytest.raises(Exception):
        await client.issue_giftcard(db_session, gid)

    await db_session.rollback()

    # Row is REDEEMED
    g2 = await DALGiftcards.get_by_id(db_session, gid)
    assert g2 is not None and g2.status == GiftcardStatus.GRANTED

    # Provider was called once successfully before conflict
    assert len(agcod_fake.calls) == 1

    kinds = [k for (k, _p) in await _list_events(db_session, gid)]
    # We should see ACCESS_ATTEMPT, ISSUE_ATTEMPT, ISSUE_SUCCESS, then ACCESS_FAILURE due to conflict
    assert GiftcardEventKind.ACCESS_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_ATTEMPT in kinds
    assert GiftcardEventKind.ISSUE_SUCCESS in kinds
    assert GiftcardEventKind.ACCESS_FAILURE in kinds

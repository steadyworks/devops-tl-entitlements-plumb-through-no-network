import logging
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Optional, TypeVar
from uuid import UUID

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials as BotoCredentials
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from backend.lib.utils.retryable import retryable_with_backoff

TModel = TypeVar("TModel", bound=BaseModel)

# =========================
# Public Types & Schemas
# =========================


class AGCODEndpoint(Enum):
    """Amazon-provided base endpoints (host only)."""

    # Sandbox
    NA_SANDBOX = "agcod-v2-gamma.amazon.com"  # us-east-1
    # FE_SANDBOX = "agcod-v2-fe-gamma.amazon.com"  # us-west-2
    # EU_SANDBOX = "agcod-v2-eu-gamma.amazon.com"  # eu-west-1
    # Production
    NA_PROD = "agcod-v2.amazon.com"  # us-east-1
    # FE_PROD = "agcod-v2-fe.amazon.com"  # us-west-2
    # EU_PROD = "agcod-v2-eu.amazon.com"  # eu-west-1


class AWSRegion(Enum):
    US_EAST_1 = "us-east-1"
    # US_WEST_2 = "us-west-2"
    # EU_WEST_1 = "eu-west-1"


class ServiceName(str, Enum):
    AGCOD = "AGCODService"


class Operation(str, Enum):
    CREATE_GIFT_CARD = "CreateGiftCard"
    CANCEL_GIFT_CARD = "CancelGiftCard"
    GET_AVAILABLE_FUNDS = "GetAvailableFunds"


class StatusCode(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RESEND = "RESEND"


class ErrorClass(str, Enum):
    F100 = "F100"  # Internal
    F200 = "F200"  # Invalid request
    F300 = "F300"  # Account / Access / Onboarding
    F400 = "F400"  # Retryable (temporary)
    F500 = "F500"  # Unknown
    THROTTLED = "Throttled"


class CurrencyCode(str, Enum):
    # Note: include only markets your account is enabled for, add more as needed
    USD = "USD"
    # EUR = "EUR"
    # GBP = "GBP"
    # JPY = "JPY"
    # CAD = "CAD"
    # AUD = "AUD"
    # TRY = "TRY"
    # AED = "AED"
    # MXN = "MXN"
    # PLN = "PLN"
    # SEK = "SEK"
    # SGD = "SGD"
    # ZAR = "ZAR"
    # EGP = "EGP"


class GiftCardValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currencyCode: CurrencyCode
    amount: int

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount_whole_minor_units(cls, v: int | float | Any) -> Any:
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if not isfinite(v):
                raise TypeError("amount must be finite")
            # allow 2000.0 -> 2000, but reject 2000.5
            iv = round(v)
            if abs(v - iv) < 1e-7:
                return int(iv)
            raise ValueError("amount must be a whole number of minor units")
        raise TypeError("amount must be int or float")

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: int, info: ValidationInfo) -> int:
        if v <= 0:
            raise ValueError("amount must be > 0")
        if info.data.get("currencyCode") == CurrencyCode.USD and v > 2000:
            raise ValueError("amount must be <= 2000")
        return v


# ---------- CreateGiftCard ----------


class CreateGiftCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creationRequestId: str = Field(max_length=40)
    partnerId: str
    value: GiftCardValue
    externalReference: Optional[str] = Field(default=None, max_length=100)

    @field_validator("creationRequestId")
    @classmethod
    def _validate_creation_id(cls, v: str, info: ValidationInfo) -> str:
        partner_id: Optional[str] = None
        # info.data is Mapping[str, object] during validation
        raw = info.data.get("partnerId")
        if isinstance(raw, str):
            partner_id = raw

        if partner_id and not v.startswith(partner_id):
            raise ValueError("creationRequestId must start with partnerId")
        if not v.isalnum():
            raise ValueError("creationRequestId must be alphanumeric")
        return v

    @field_validator("partnerId")
    @classmethod
    def _validate_partner_case(cls, v: str) -> str:
        # Docs: first letter capitalized and next four lower-case (partnerId is case sensitive).
        # We don't forcibly transform; we validate minimum pattern (len>=5).
        if len(v) < 5:
            raise ValueError(
                "partnerId must be at least 5 characters (case sensitive per Amazon)"
            )
        return v


class AGCODCardInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cardStatus: str
    value: GiftCardValue


class CreateGiftCardResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cardInfo: AGCODCardInfo
    creationRequestId: str
    gcClaimCode: str
    gcId: str
    status: StatusCode


# ---------- CancelGiftCard ----------


class CancelGiftCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creationRequestId: str = Field(max_length=40)
    partnerId: str

    @field_validator("creationRequestId")
    @classmethod
    def _validate_creation_id(cls, v: str, info: ValidationInfo) -> str:
        partner_id: Optional[str] = None
        # info.data is Mapping[str, object] during validation
        raw = info.data.get("partnerId")
        if isinstance(raw, str):
            partner_id = raw

        if partner_id and not v.startswith(partner_id):
            raise ValueError("creationRequestId must start with partnerId")
        if not v.isalnum():
            raise ValueError("creationRequestId must be alphanumeric")
        return v


class CancelGiftCardResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    creationRequestId: str
    status: StatusCode


# ---------- GetAvailableFunds ----------


class GetAvailableFundsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partnerId: str


class AvailableFunds(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amount: float
    currencyCode: CurrencyCode


class GetAvailableFundsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    availableFunds: AvailableFunds
    status: StatusCode
    timestamp: str


# =========================
# Exceptions
# =========================


class AGCODError(Exception):
    """Base exception for AGCOD client errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


class AGCODHTTPError(AGCODError):
    def __init__(self, status_code: int, payload: str) -> None:
        super().__init__(f"HTTP {status_code}: {payload}")
        self.status_code: int = status_code
        self.payload: str = payload


class AGCODFailure(AGCODError):
    """AGCOD returned status=FAILURE with error metadata."""

    def __init__(
        self,
        status: StatusCode,
        error_code: Optional[str],
        message: Optional[str],
        raw: Mapping[str, object],
    ) -> None:
        msg: str = f"AGCOD failure ({status.value}) code={error_code or 'UNKNOWN'} message={message or ''}"
        super().__init__(msg)
        self.status: StatusCode = status
        self.error_code: Optional[str] = error_code
        self.raw: Mapping[str, object] = raw


class AGCODResend(AGCODError):
    """AGCOD returned status=RESEND (retryable). Raised to trigger retry policy."""

    def __init__(self, raw: Mapping[str, object]) -> None:
        super().__init__("AGCOD returned RESEND")
        self.raw: Mapping[str, object] = raw


class AGCODThrottled(AGCODError):
    """Throttling exception (HTTP 429 or known throttling response)."""

    pass


@dataclass(frozen=True)
class Credentials:
    access_key_id: str
    secret_access_key: str


class AGCODClient:
    """
    Strongly typed AGCOD client (CreateGiftCard, CancelGiftCard, GetAvailableFunds).
    """

    def __init__(
        self,
        *,
        partner_id: str,
        credentials: Credentials,
        endpoint: AGCODEndpoint,
        region: AWSRegion,
    ) -> None:
        self._partner_id: str = partner_id
        self._creds: Credentials = credentials
        self._endpoint: AGCODEndpoint = endpoint
        self._region: AWSRegion = region
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=3.0,  # quick fail for unreachable hosts
                read=10.0,  # wait time for response
                write=10.0,  # wait time for sending data
                pool=5.0,  # wait time for connection from pool
            ),
        )
        self._service: ServiceName = ServiceName.AGCOD

    # ---------- Public Operations ----------
    def get_partner_id(self) -> str:
        return self._partner_id

    async def create_gift_card(
        self,
        *,
        creation_request_id: str,
        currency: CurrencyCode,
        amount: int,
        external_reference: Optional[str] = None,
    ) -> CreateGiftCardResponse:
        payload = CreateGiftCardRequest(
            creationRequestId=creation_request_id,
            partnerId=self._partner_id,
            value=GiftCardValue(currencyCode=currency, amount=amount),
            externalReference=external_reference,
        )
        return await self._retried_post(
            op=Operation.CREATE_GIFT_CARD,
            payload=payload,
            response_model=CreateGiftCardResponse,
        )

    async def cancel_gift_card(
        self, *, creation_request_id: str
    ) -> CancelGiftCardResponse:
        payload = CancelGiftCardRequest(
            creationRequestId=creation_request_id,
            partnerId=self._partner_id,
        )
        return await self._retried_post(
            op=Operation.CANCEL_GIFT_CARD,
            payload=payload,
            response_model=CancelGiftCardResponse,
        )

    async def get_available_funds(self) -> GetAvailableFundsResponse:
        payload = GetAvailableFundsRequest(partnerId=self._partner_id)
        return await self._retried_post(
            op=Operation.GET_AVAILABLE_FUNDS,
            payload=payload,
            response_model=GetAvailableFundsResponse,
        )

    def get_creation_request_id(
        self,
        internal_giftcard_id: UUID,
    ) -> str:
        creation_request_id_candidate = f"{self._partner_id}{internal_giftcard_id.hex}"
        assert len(creation_request_id_candidate) <= 40
        return creation_request_id_candidate

    async def close(self) -> None:
        if not self._http.is_closed:
            await self._http.aclose()

    # ---------- Core Request Flow ----------
    async def _retried_post(
        self, *, op: Operation, payload: BaseModel, response_model: type[TModel]
    ) -> TModel:
        async def _post() -> TModel:
            try:
                resp = await self._signed_post_with_botocore(op=op, payload=payload)
                return response_model.model_validate(resp)
            except Exception as e:
                logging.warning(f"[agcod] exception: {str(e)}")
                raise

        return await retryable_with_backoff(
            _post,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteError,
                AGCODResend,
                AGCODThrottled,
            ),
            max_attempts=3,
            base_delay=0.5,
        )

    async def _signed_post_with_botocore(
        self, *, op: Operation, payload: BaseModel
    ) -> Mapping[str, object]:
        body: bytes = payload.model_dump_json(
            by_alias=False, exclude_none=True, exclude_unset=True
        ).encode("utf-8")
        # Build request
        path = f"/{op.value}"
        host = self._endpoint.value  # e.g., "agcod-v2.amazon.com"
        url = f"https://{host}{path}"

        # Required AGCOD headers (keep these exactly)
        headers = {
            "Content-Type": "application/json",  # If your integration requires x-amz-json-1.1, set it here
            "X-Amz-Target": f"com.amazonaws.agcod.{self._service.value}.{op.value}",  # AGCODService.{Operation}
            "Accept": "application/json",
        }

        # Prepare botocore request
        aws_req = AWSRequest(method="POST", url=url, data=body, headers=headers)

        # Sign with SigV4
        boto_creds = BotoCredentials(
            self._creds.access_key_id, self._creds.secret_access_key
        )
        SigV4Auth(boto_creds, self._service.value, self._region.value).add_auth(aws_req)
        signed_headers = dict(aws_req.headers.items())  # copy into a plain dict

        # Send with httpx
        r = await self._http.post(url, content=body, headers=signed_headers)
        if r.status_code == 429:
            raise AGCODThrottled("Rate exceeded")

        # Try to decode JSON regardless of status
        resp_text = r.text
        try:
            resp_json = r.json()
        except ValueError:
            # Non-JSON: raise with raw text
            raise AGCODHTTPError(r.status_code, resp_text)

        status_raw = _get_str(resp_json.get("status"))
        status = StatusCode(status_raw) if status_raw else StatusCode.FAILURE

        if r.is_error:
            # If AGCOD gave structured error details, surface them
            raise AGCODFailure(
                status=status,
                error_code=_get_str(resp_json.get("errorCode")),
                message=_get_str(resp_json.get("message")) or resp_text,
                raw=resp_json,
            )

        if status is StatusCode.RESEND:
            raise AGCODResend(resp_json)
        if status is StatusCode.FAILURE:
            raise AGCODFailure(
                status=status,
                error_code=_get_str(resp_json.get("errorCode")),
                message=_get_str(resp_json.get("message")),
                raw=resp_json,
            )

        return resp_json


def _get_str(value: object | None) -> Optional[str]:
    if isinstance(value, str):
        return value
    return None

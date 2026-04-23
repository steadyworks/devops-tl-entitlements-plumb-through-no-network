import logging
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Optional, TypeVar

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from backend.lib.utils.retryable import retryable_with_backoff

TModel = TypeVar("TModel", bound=BaseModel)

# =========================
# Public Types & Schemas
# =========================


class GiftbitEndpoint(str, Enum):
    TESTBED = "https://api-testbed.giftbit.com/papi/v1"
    PROD = "https://api.giftbit.com/papi/v1"


class GiftbitRootURL(str, Enum):
    TESTBED = "https://testbedapp.giftbit.com/embeddedRewards/index"
    PROD = "https://app.giftbit.com/embeddedRewards/index"


@dataclass(frozen=True)
class GiftbitAuth:
    """Simple bearer token auth."""

    api_token: str


# ---- Common response envelope bits ----


class GiftbitInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    name: Optional[str] = None
    message: Optional[str] = None


class GiftbitErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    name: Optional[str] = None
    message: Optional[str] = None


class GiftbitErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    error: GiftbitErrorBody
    status: int


# ---- POST /embedded ----


class CreateEmbeddedRequest(BaseModel):
    """
    Docs:
      - brand_code: string (e.g., "itunesus")
      - price_in_cents: number (int cents)
      - id: string (client-supplied, idempotency key)
    """

    model_config = ConfigDict(extra="forbid")

    brand_code: str
    price_in_cents: int
    id: str = Field(min_length=1, max_length=128)

    @field_validator("price_in_cents", mode="before")
    @classmethod
    def _coerce_cents(cls, v: int | float | Any) -> Any:
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if not isfinite(v):
                raise TypeError("price_in_cents must be finite")
            iv = round(v)
            if abs(v - iv) < 1e-7:
                return int(iv)
            raise ValueError("price_in_cents must be a whole number of cents")
        raise TypeError("price_in_cents must be int or float")

    @field_validator("price_in_cents")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("price_in_cents must be > 0")
        return v


class GiftbitCampaignFees(BaseModel):
    """You said we can ignore when parsing; keep as opaque for forward-compat."""

    model_config = ConfigDict(extra="allow")


class GiftbitCampaign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uuid: str
    id: str
    brand_code: str
    price_in_cents: int
    fees: Optional[GiftbitCampaignFees] = None


class CreateEmbeddedResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    info: GiftbitInfo
    status: int
    campaign: GiftbitCampaign
    gift_link: str


# ---- GET /gifts ----


class GiftSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    uuid: str
    campaign_uuid: Optional[str] = None
    delivery_status: Optional[str] = None
    status: Optional[str] = None
    management_dashboard_link: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "management_dashboard_link", "management_link_dashboard"
        ),
    )
    redelivery_count: Optional[int] = None
    campaign_id: Optional[str] = None
    price_in_cents: Optional[int] = None
    brand_code: Optional[str] = None
    created_date: Optional[str] = None
    delivery_date: Optional[str] = None
    redeemed_date: Optional[str] = None


class ListGiftsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    gifts: list[GiftSummary]
    number_of_results: int
    limit: int
    offset: int
    total_count: int
    info: GiftbitInfo
    status: int


# ---- GET /brands ----


class BrandSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    brand_code: str
    name: str
    image_url: str
    disclaimer: Optional[str] = None
    # Seen in sample payloads; keep optional/loose for forward-compat
    expiry_period: Optional[str] = None


class ListBrandsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    brands: list[BrandSummary]
    total_count: int
    info: GiftbitInfo
    number_of_results: int
    limit: int
    offset: int


# =========================
# Exceptions
# =========================


class GiftbitError(Exception):
    """Base exception for Giftbit client errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GiftbitHTTPError(GiftbitError):
    """Non-JSON or unexpected HTTP response payloads (primarily for diagnostics)."""

    def __init__(self, status_code: int, payload: str) -> None:
        super().__init__(f"HTTP {status_code}: {payload}")
        self.status_code = status_code
        self.payload = payload


class GiftbitAPIError(GiftbitError):
    """Giftbit JSON error envelope (non-200)."""

    def __init__(
        self,
        *,
        code: str,
        name: Optional[str],
        message: Optional[str],
        status: int,
        raw: Mapping[str, Any],
    ) -> None:
        msg = f"Giftbit error {status} [{code}] {name or ''}: {message or ''}".strip()
        super().__init__(msg)
        self.code = code
        self.name = name
        self.status = status
        self.raw = raw


class GiftbitThrottled(GiftbitError):
    """HTTP 429."""

    pass


class GiftbitErrorCampaignInvalidIDError(GiftbitError):
    """HTTP 422 + ERROR_CAMPAIGN_INVALID_ID -> likely more than once embed create request"""

    pass


class GiftbitServerError(GiftbitError):
    """HTTP 5xx with/without JSON body; retryable."""

    def __init__(self, status_code: int, payload: str) -> None:
        super().__init__(f"Giftbit server error {status_code}")
        self.status_code = status_code
        self.payload = payload


# =========================
# Client
# =========================


class GiftbitClient:
    """
    Strongly-typed Giftbit client mirroring your AGCOD ergonomics.
    - Bearer token auth
    - Retries 429 + network + 5xx with jitter backoff
    - Strict Pydantic models
    """

    def __init__(
        self,
        *,
        auth: GiftbitAuth,
        endpoint: GiftbitEndpoint,
        gift_link_endpoint: GiftbitRootURL,
        # Optional testing knob: pass SIMULATE-RATELIMIT=true in Testbed
        simulate_ratelimit: bool = False,
    ) -> None:
        self._auth = auth
        self._base_url = endpoint.value.rstrip("/")
        self._render_giftlink_base_url = gift_link_endpoint.value.rstrip("/")
        self._simulate_ratelimit = simulate_ratelimit

        # httpx client; tune as you like
        self._http = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=3.0,  # fail fast on DNS/conn
                read=15.0,  # Giftbit is generally quick; keep reasonable
                write=10.0,
                pool=5.0,
            ),
        )

    def render_giftbit_embed_link(self, campaign_uuid: str) -> str:
        return self._render_giftlink_base_url + "/" + campaign_uuid

    # ---- Helpers ----

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._auth.api_token}",
            "Content-Type": "application/json",
            # Giftbit recommends identity to simplify content handling
            "Accept-Encoding": "identity",
        }
        if self._simulate_ratelimit:
            h["SIMULATE-RATELIMIT"] = "true"
        return h

    # ---- Public operation: POST /embedded ----

    async def create_embedded_reward(
        self,
        *,
        brand_code: str,
        price_in_cents: int,
        embed_request_id: str,
    ) -> CreateEmbeddedResponse:
        payload = CreateEmbeddedRequest(
            brand_code=brand_code,
            price_in_cents=price_in_cents,
            id=embed_request_id,
        )
        return await self._retried_post_json(
            path="/embedded",
            payload=payload,
            response_model=CreateEmbeddedResponse,
        )

    # ---- Public operation: GET /gifts ----
    async def list_gifts(
        self,
        *,
        campaign_uuid: Optional[str] = None,
        campaign_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        # keep signature minimal per your ask; add more filters later if needed
    ) -> ListGiftsResponse:
        params: dict[str, str | int] = {}
        if campaign_uuid:
            params["campaign_uuid"] = campaign_uuid
        if campaign_id:
            params["campaign_id"] = campaign_id
        if isinstance(limit, int):
            params["limit"] = limit
        if isinstance(offset, int):
            params["offset"] = offset

        return await self._retried_get_json(
            path="/gifts",
            params=params,
            response_model=ListGiftsResponse,
        )

    # ---- Public operation: GET /brands ----
    async def list_brands(
        self,
        *,
        region: Optional[int] = None,
        max_price_in_cents: Optional[int] = None,
        min_price_in_cents: Optional[int] = None,
        currencyisocode: Optional[str] = None,  # e.g. "USD", "CAD", "AUD"
        search: Optional[str] = None,
        embeddable: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> ListBrandsResponse:
        params: dict[str, str | int] = {}

        if region is not None:
            params["region"] = region
        if max_price_in_cents is not None:
            params["max_price_in_cents"] = max_price_in_cents
        if min_price_in_cents is not None:
            params["min_price_in_cents"] = min_price_in_cents
        if currencyisocode:
            params["currencyisocode"] = currencyisocode
        if search:
            params["search"] = search
        if embeddable is not None:
            params["embeddable"] = "true" if embeddable else "false"
        if isinstance(limit, int):
            params["limit"] = limit
        if isinstance(offset, int):
            params["offset"] = offset

        return await self._retried_get_json(
            path="/brands",
            params=params,
            response_model=ListBrandsResponse,
        )

    async def _post_json(self, *, path: str, payload: BaseModel) -> Mapping[str, Any]:
        url = f"{self._base_url}{path}"
        body = payload.model_dump_json(
            by_alias=False, exclude_none=True, exclude_unset=True
        )
        r = await self._http.post(url, content=body, headers=self._headers())
        return self._decode_or_raise(r)

    async def _get_json(
        self, *, path: str, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        url = f"{self._base_url}{path}"
        r = await self._http.get(url, params=params, headers=self._headers())
        return self._decode_or_raise(r)

    # ---- Core flow (shared pattern with AGCOD client) ----

    async def _retried_post_json(
        self, *, path: str, payload: BaseModel, response_model: type[TModel]
    ) -> TModel:
        async def _post() -> TModel:
            try:
                resp_json = await self._post_json(path=path, payload=payload)
                return response_model.model_validate(resp_json)
            except Exception as e:
                logging.warning(f"[giftbit] exception: {e}")
                raise

        # Retry on transient/network + throttling + server errors.
        return await retryable_with_backoff(
            _post,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteError,
                GiftbitThrottled,
                GiftbitServerError,
            ),
            max_attempts=3,
            base_delay=0.5,
        )

    # ---- Core flow: GET (mirrors _retried_post_json/_post_json) ----
    async def _retried_get_json(
        self,
        *,
        path: str,
        params: Mapping[str, Any] | None,
        response_model: type[TModel],
    ) -> TModel:
        async def _get() -> TModel:
            try:
                resp_json = await self._get_json(path=path, params=params)
                return response_model.model_validate(resp_json)
            except Exception as e:
                logging.warning(f"[giftbit] exception: {e}")
                raise

        return await retryable_with_backoff(
            _get,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteError,
                GiftbitThrottled,
                GiftbitServerError,
            ),
            max_attempts=3,
            base_delay=0.5,
        )

    def _decode_or_raise(self, r: httpx.Response) -> Mapping[str, Any]:
        # 429: throttled
        if r.status_code == 429:
            raise GiftbitThrottled("Rate limited by Giftbit (429).")

        text = r.text
        try:
            data = r.json()
        except ValueError:
            # Non-JSON: 5xx is retryable; else generic HTTP error
            if 500 <= r.status_code < 600:
                raise GiftbitServerError(r.status_code, text)
            raise GiftbitHTTPError(r.status_code, text)

        if r.status_code == 200:
            return data

        # Try to parse structured error envelope
        try:
            env = GiftbitErrorEnvelope.model_validate(data)
        except Exception:
            if 500 <= r.status_code < 600:
                raise GiftbitServerError(r.status_code, text)
            raise GiftbitHTTPError(r.status_code, text)

        if 500 <= r.status_code < 600:
            raise GiftbitServerError(r.status_code, text)

        if r.status_code == 422 and env.error.code == "ERROR_CAMPAIGN_INVALID_ID":
            raise GiftbitErrorCampaignInvalidIDError(
                message=env.error.message or env.error.code
            )

        # 4xx (and other non-200) with structured envelope
        raise GiftbitAPIError(
            code=env.error.code,
            name=env.error.name,
            message=env.error.message,
            status=env.status,
            raw=data,
        )

    async def close(self) -> None:
        if not self._http.is_closed:
            await self._http.aclose()

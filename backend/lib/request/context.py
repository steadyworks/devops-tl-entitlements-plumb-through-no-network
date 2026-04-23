import logging
from enum import Enum
from typing import TYPE_CHECKING, Optional, Self
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, WebSocket, WebSocketException
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, EmailStr, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_401_UNAUTHORIZED, WS_1008_POLICY_VIOLATION

# App imports
from backend.env_loader import EnvLoader
from backend.lib.utils.share_destination_normalizer import (
    normalize_email_throws,
    normalize_phone_e164_throws,
)

if TYPE_CHECKING:
    from backend.db.externals import UsersOverviewResponse_INTERNAL_ONLY


# Supabase (GoTrue) JWT config
SUPABASE_JWT_SECRET = EnvLoader.get("SUPABASE_JWT_SECRET")
SUPABASE_JWT_ALGO = (
    "HS256"  # Supabase GoTrue default when validating with anon/service key
)

if not SUPABASE_JWT_SECRET:
    raise RuntimeError("Missing SUPABASE_JWT_SECRET env var")


class SupabaseJWTClaims(BaseModel):
    """
    Minimal claims we rely on. The 'sub' is the auth.users.id and equals public.users.id.
    """

    sub: str  # UUID as string
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: str
    iss: Optional[str] = None
    # Optionally: app_metadata / user_metadata if you need them later

    model_config = ConfigDict(extra="ignore")

    # --- Strongly-typed normalizers ---

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Optional[str]) -> Optional[str]:
        """
        Accepts '' or None and returns None; otherwise returns the original string.
        Pydantic will then validate/parse it into EmailStr when not None.
        """
        if v is None:
            return None
        if v.strip() == "":
            return None
        try:
            return normalize_email_throws(v)
        except Exception:
            return None

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        """
        Accepts '' or None and returns None; otherwise returns the original string.
        (Keep as str; add your own E.164 validation if desired.)
        """
        if v is None:
            return None
        if v.strip() == "":
            return None
        try:
            return normalize_phone_e164_throws(v)
        except Exception:
            return None


class AuthMode(str, Enum):
    USER = "user"  # Anon or regular Supabase users; both are "users" once signed in.


class RequestContext:
    """
    Minimal, single-source-of-truth context bound directly to a Supabase user.

    Key decisions:
    - No 'owner' abstraction. The canonical identity is user_id (auth.users/public.users).
    - "Guests" use Supabase Anonymous Auth, which still yields a user_id + JWT.
    """

    def __init__(
        self,
        *,
        mode: AuthMode,
        user_id: UUID,
        request_id: UUID = uuid4(),
        raw_token: Optional[str] = None,
        claims: Optional[SupabaseJWTClaims] = None,
        user_snapshot: Optional["UsersOverviewResponse_INTERNAL_ONLY"] = None,
    ) -> None:
        self._mode = mode
        self._user_id = user_id
        self._request_id = request_id
        self._raw_token = raw_token
        self._claims = claims
        self._user_snapshot = user_snapshot

    # -------------------- Properties --------------------

    @property
    def mode(self) -> AuthMode:
        return self._mode

    @property
    def user_id(self) -> UUID:
        return self._user_id

    @property
    def email(self) -> Optional[str]:
        if self._user_snapshot and self._user_snapshot.email:
            return self._user_snapshot.email
        return self._claims.email if self._claims else None

    @property
    def role(self) -> Optional[str]:
        if self._user_snapshot and getattr(self._user_snapshot, "role", None):
            return self._user_snapshot.role
        return self._claims.role if self._claims else None

    @property
    def name(self) -> Optional[str]:
        return self._user_snapshot.name if self._user_snapshot else None

    @property
    def user(self) -> Optional["UsersOverviewResponse_INTERNAL_ONLY"]:
        return self._user_snapshot

    @property
    def request_id(self) -> UUID:
        return self._request_id

    # ---------------- Factory: HTTP request ----------------

    @classmethod
    async def from_request(
        cls,
        request: Request,
        db_session: AsyncSession,
    ) -> Self:
        """
        Requires a Supabase JWT (regular or anonymous) via:
          - Authorization: Bearer <jwt>
        """
        # Per-request cache
        if hasattr(request.state, "ctx"):
            return request.state.ctx

        if not hasattr(request.state, "request_id"):
            request.state.request_id = uuid4()
        request_id: UUID = request.state.request_id

        token = _extract_bearer_token_from_headers(request.headers.get("authorization"))
        if not token:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization: Bearer <token>",
            )

        claims, user_id = _try_decode_supabase(token)
        if not user_id:
            logging.warning("JWT decode failed or invalid 'sub'")
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        # (Optional) Load profile row for convenience (role/name/email)
        from backend.db.dal import DALUsers  # avoid circular import
        from backend.db.externals import UsersOverviewResponse_INTERNAL_ONLY

        user_snapshot: Optional[UsersOverviewResponse_INTERNAL_ONLY] = None
        try:
            user_row = await DALUsers.get_by_id(db_session, user_id)
            if user_row is not None:
                user_snapshot = UsersOverviewResponse_INTERNAL_ONLY(
                    **user_row.model_dump()
                )
        except Exception:
            # If the trigger-based sync guarantees existence, treat absence as invalid
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Unknown user",
            )

        ctx = cls(
            mode=AuthMode.USER,
            user_id=user_id,
            request_id=request_id,
            raw_token=token,
            claims=claims,
            user_snapshot=user_snapshot,
        )
        request.state.ctx = ctx
        return ctx

    # ---------------- Factory: WebSocket ----------------

    @classmethod
    async def from_websocket(
        cls,
        websocket: WebSocket,
        db_session: AsyncSession,
    ) -> Self:
        """
        Accepts a Supabase JWT via:
          - token=<jwt> query param OR
          - Authorization: Bearer <jwt> header
        """
        request_id = uuid4()

        token = websocket.query_params.get("token")
        if not token:
            token = _extract_bearer_token_from_headers(
                websocket.headers.get("authorization")
            )

        if not token:
            logging.warning("[WS][%s] Missing credentials", request_id)
            raise WebSocketException(
                code=WS_1008_POLICY_VIOLATION,
                reason="Missing token (token query param or Authorization header)",
            )

        try:
            decoded = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=[SUPABASE_JWT_ALGO],
                audience="authenticated",
            )
            claims = SupabaseJWTClaims.model_validate(decoded)
            user_id = UUID(claims.sub)
        except (JWTError, ValidationError, ValueError) as e:
            logging.warning("[WS][%s] Invalid auth token: %s", request_id, e)
            raise WebSocketException(
                code=WS_1008_POLICY_VIOLATION, reason="Invalid authentication token"
            )

        from backend.db.dal import DALUsers  # avoid circular import
        from backend.db.externals import UsersOverviewResponse_INTERNAL_ONLY

        # (Optional) Load profile row for convenience (role/name/email)
        user_snapshot: Optional[UsersOverviewResponse_INTERNAL_ONLY] = None
        try:
            user_row = await DALUsers.get_by_id(db_session, user_id)
            if user_row is not None:
                user_snapshot = UsersOverviewResponse_INTERNAL_ONLY(
                    **user_row.model_dump()
                )
        except Exception:
            raise WebSocketException(
                code=WS_1008_POLICY_VIOLATION, reason="Unknown user"
            )

        return cls(
            mode=AuthMode.USER,
            user_id=user_id,
            request_id=request_id,
            raw_token=token,
            claims=claims,
            user_snapshot=user_snapshot,
        )


# ----------------------- Helpers -----------------------


def _extract_bearer_token_from_headers(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    lower = auth_header.lower()
    if not lower.startswith("bearer "):
        return None
    return auth_header[len("Bearer ") :].strip()


def _try_decode_supabase(
    token: str,
) -> tuple[Optional[SupabaseJWTClaims], Optional[UUID]]:
    try:
        decoded = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[SUPABASE_JWT_ALGO],
            audience="authenticated",
            options={"require_sub": True},
        )
        claims = SupabaseJWTClaims.model_validate(decoded)
        return claims, UUID(claims.sub)
    except (JWTError, ValidationError, ValueError) as e:
        logging.warning("Failed to decode supabase token: %s", e, exc_info=True)
        return None, None

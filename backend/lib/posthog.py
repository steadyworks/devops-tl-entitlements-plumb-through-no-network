import asyncio
import functools
import logging
import threading
import time
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Mapping,
    Optional,
    ParamSpec,
    TypedDict,
    TypeVar,
)

import httpx
from fastapi import Request

from backend.env_loader import EnvLoader

P = ParamSpec("P")
R = TypeVar("R")

_logger = logging.getLogger(__name__)
_logger.addHandler(logging.NullHandler())  # silent


@dataclass(frozen=True)
class _PosthogConfig:
    api_key: str
    host: str


_config_lock = threading.Lock()
_config: Optional[_PosthogConfig] = None
_config_initialized = False
_missing_config_logged = False


def _get_config() -> Optional[_PosthogConfig]:
    global _config_initialized, _config, _missing_config_logged

    if _config_initialized:
        return _config

    with _config_lock:
        if _config_initialized:
            return _config

        api_key = EnvLoader.get_optional("POSTHOG_API_KEY")
        host = EnvLoader.get_optional("POSTHOG_HOST")

        if api_key and host:
            normalized_host = host.rstrip("/")
            if not normalized_host.startswith(
                "http://"
            ) and not normalized_host.startswith("https://"):
                normalized_host = f"https://{normalized_host}"
            _config = _PosthogConfig(api_key=api_key, host=normalized_host)
        else:
            if not _missing_config_logged:
                _logger.debug(
                    "PostHog instrumentation disabled: missing POSTHOG_API_KEY or POSTHOG_HOST"
                )
                _missing_config_logged = True
            _config = None

        _config_initialized = True
        return _config


class PosthogPayload(TypedDict):
    api_key: str
    event: str
    distinct_id: str
    properties: Mapping[str, Any]


async def _capture_event(
    *,
    config: _PosthogConfig,
    event: str,
    distinct_id: str,
    properties: dict[str, Any],
) -> None:
    payload: PosthogPayload = {
        "api_key": config.api_key,
        "event": event,
        "distinct_id": distinct_id or "anonymous",
        "properties": properties,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            await client.post(f"{config.host}/capture/", json=payload)
    except Exception:
        _logger.debug(
            "Failed to send PostHog event '%s'", event, exc_info=True
        )


def _extract_request(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Optional[Request]:
    for value in args:
        if isinstance(value, Request):
            return value
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    return None


def _build_event_payload(
    func: Callable[..., Any],
    request: Optional[Request],
) -> tuple[str, dict[str, Any]]:
    distinct_id = "anonymous"
    properties: dict[str, Any] = {
        "handler": func.__qualname__,
    }

    if request is not None:
        url_path: str | None = None
        try:
            url_path = str(request.url.path)
        except Exception:
            url_path = str(request.scope.get("path"))

        properties.update(
            {
                "path": url_path,
                "method": request.method,
            }
        )

        if request.client:
            properties["client_host"] = request.client.host

        ctx = getattr(request.state, "ctx", None)
        if ctx is not None:
            user_id = getattr(ctx, "user_id", None)
            if user_id:
                distinct_id = str(user_id)
            request_id = getattr(ctx, "request_id", None)
            if request_id:
                properties["request_id"] = str(request_id)
            auth_mode = getattr(ctx, "mode", None)
            if auth_mode:
                properties["auth_mode"] = str(auth_mode)

    return distinct_id, properties


def _schedule_capture(
    *,
    event: str,
    distinct_id: str,
    properties: dict[str, Any],
) -> None:
    config = _get_config()
    if config is None:
        return

    async def runner() -> None:
        await _capture_event(
            config=config,
            event=event,
            distinct_id=distinct_id,
            properties=properties,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop: best-effort synchronous execution
        asyncio.run(runner())
    else:
        loop.create_task(runner())


def posthog_capture(
    event_name: Optional[str] = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Decorator that captures a PostHog event for the wrapped async API handler.

    Emits the event asynchronously and swallows all PostHog failures.
    """

    def decorator(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R]]:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(
                "posthog_capture decorator only supports async callables"
            )

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            request = _extract_request(args, kwargs)
            distinct_id, properties = _build_event_payload(func, request)
            start_time = time.perf_counter()
            success = False
            error_details: dict[str, Any] | None = None

            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception as exc:
                error_details = {
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc)[:256],
                }
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                properties.update(
                    {
                        "duration_ms": round(duration_ms, 2),
                        "success": success,
                    }
                )
                if not success and error_details:
                    properties.update(error_details)

                event = event_name or f"api.{func.__qualname__}"
                _schedule_capture(
                    event=event,
                    distinct_id=distinct_id,
                    properties=properties,
                )

        return wrapper

    return decorator

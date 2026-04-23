import json
import logging
from datetime import datetime
from typing import Any, cast


def json_sanitize(
    obj: Any,
    *,
    max_depth: int = 10,
    max_list: int = 200,
    max_str: int = 4000,
    _depth: int = 0,
) -> Any:
    """
    Make an object JSON-safe and bounded.
    - Truncates long strings and long lists
    - Recursively sanitizes dicts/lists
    - Converts unknown objects to str
    """
    if _depth >= max_depth:
        return "[[TRUNCATED_DEPTH]]"

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    if isinstance(obj, str):
        return obj if len(obj) <= max_str else (obj[:max_str] + "…")

    if isinstance(obj, dict):
        # Keep keys as str to be safe
        return {
            str(k): json_sanitize(
                v,
                max_depth=max_depth,
                max_list=max_list,
                max_str=max_str,
                _depth=_depth + 1,
            )
            for k, v in cast("dict[str, Any]", obj).items()
        }

    if isinstance(obj, list) or isinstance(obj, tuple):
        seq: list[Any] = list(cast("list[Any] | tuple[Any]", obj))
        if len(seq) > max_list:
            seq = seq[:max_list] + ["[[TRUNCATED_LIST]]"]
        return [
            json_sanitize(
                v,
                max_depth=max_depth,
                max_list=max_list,
                max_str=max_str,
                _depth=_depth + 1,
            )
            for v in seq
        ]

    if isinstance(obj, datetime):
        return obj.isoformat()

    # Fallback for UUID/Enum/datetime/custom objects, etc.
    try:
        return str(obj)
    except Exception:
        return "[[UNSERIALIZABLE_OBJECT]]"


def json_ensure_or_fallback(
    d: dict[str, Any], *, fallback_hint: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Try to ensure `d` is JSON-serializable. If that fails, return a minimal forensic stub.
    """
    try:
        json.dumps(d, separators=(",", ":"), ensure_ascii=False)
        return d
    except Exception:
        logging.exception("DAL JSON encode failed; returning minimal fallback")
        fh = fallback_hint or {}
        # Compact forensic breadcrumb; never raise
        return {
            "_error": "serialization_failed",
            "_hint": fh,
        }

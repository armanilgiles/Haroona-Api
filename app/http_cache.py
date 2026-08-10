from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder


REFERENCE_CACHE_CONTROL = "public, max-age=60, must-revalidate"


def _etag_matches(header_value: str | None, etag: str) -> bool:
    if not header_value:
        return False

    expected = etag.removeprefix("W/")
    for candidate in header_value.split(","):
        normalized = candidate.strip()
        if normalized == "*" or normalized.removeprefix("W/") == expected:
            return True
    return False


def apply_conditional_cache(
    *,
    request: Request,
    response: Response,
    payload: Any,
    cache_control: str = REFERENCE_CACHE_CONTROL,
) -> Response | None:
    """Attach stable cache headers and return a 304 response when possible."""

    encoded = json.dumps(
        jsonable_encoder(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    etag = f'"{hashlib.sha256(encoded).hexdigest()[:24]}"'
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
        "Vary": "Accept-Encoding",
    }

    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    response.headers.update(headers)
    return None

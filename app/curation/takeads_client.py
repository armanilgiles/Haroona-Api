from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


TAKEADS_RESOLVE_URL = "https://api.takeads.com/v1/product/monetize-api/v2/resolve"
TAKEADS_CONNECT_TIMEOUT_SECONDS = 5
TAKEADS_READ_TIMEOUT_SECONDS = 15
TAKEADS_REQUEST_TIMEOUT = (
    TAKEADS_CONNECT_TIMEOUT_SECONDS,
    TAKEADS_READ_TIMEOUT_SECONDS,
)


@dataclass(frozen=True)
class TakeadsResolveResult:
    tracking_link: str | None
    returned_iri: str | None
    no_eligible_offer: bool = False


class TakeadsClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _valid_http_url(value: str | None) -> bool:
    cleaned = _clean(value)
    if not cleaned:
        return False
    parsed = urlsplit(cleaned)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _normalized_iri(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not _valid_http_url(cleaned):
        return None

    parsed = urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def _error_for_status(status_code: int) -> TakeadsClientError:
    if status_code in {400, 404, 422}:
        return TakeadsClientError(
            "takeads_invalid_request",
            "Takeads could not process this product URL. Confirm the original product link and retry.",
            http_status=status_code,
        )
    if status_code == 401:
        return TakeadsClientError(
            "takeads_unauthorized",
            "Takeads rejected the server credentials. Ask an administrator to check the integration.",
            http_status=status_code,
        )
    if status_code == 403:
        return TakeadsClientError(
            "takeads_forbidden",
            "Takeads does not allow this account to monetize the product URL.",
            http_status=status_code,
        )
    if status_code == 429:
        return TakeadsClientError(
            "takeads_rate_limited",
            "Takeads is receiving too many requests. Wait briefly, then retry.",
            http_status=status_code,
        )
    if status_code >= 500:
        return TakeadsClientError(
            "takeads_unavailable",
            "Takeads is temporarily unavailable. Retry in a moment.",
            http_status=status_code,
        )
    return TakeadsClientError(
        "takeads_request_failed",
        "Takeads could not generate the affiliate link. Retry in a moment.",
        http_status=status_code,
    )


class TakeadsClient:
    def __init__(self, public_key: str | None = None) -> None:
        self._public_key = _clean(public_key) or _clean(
            os.getenv("TAKEADS_PUBLIC_KEY")
        )

    def resolve_product_url(
        self,
        *,
        product_url: str,
        sub_id: str,
    ) -> TakeadsResolveResult:
        if not self._public_key:
            raise TakeadsClientError(
                "takeads_not_configured",
                "Affiliate link generation is not configured on the server.",
            )

        try:
            response = requests.put(
                TAKEADS_RESOLVE_URL,
                headers={
                    "Authorization": f"Bearer {self._public_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "iris": [product_url],
                    "subId": sub_id,
                },
                timeout=TAKEADS_REQUEST_TIMEOUT,
            )
        except requests.Timeout as exc:
            raise TakeadsClientError(
                "takeads_timeout",
                "Takeads did not respond in time. Retry the affiliate link.",
            ) from exc
        except requests.RequestException as exc:
            raise TakeadsClientError(
                "takeads_unavailable",
                "Takeads could not be reached. Retry in a moment.",
            ) from exc

        if not 200 <= response.status_code < 300:
            raise _error_for_status(response.status_code)

        try:
            body = response.json()
        except ValueError as exc:
            raise TakeadsClientError(
                "takeads_invalid_response",
                "Takeads returned an unreadable response. Retry in a moment.",
                http_status=response.status_code,
            ) from exc

        if not isinstance(body, dict) or "data" not in body:
            raise TakeadsClientError(
                "takeads_invalid_response",
                "Takeads returned an incomplete response. Retry in a moment.",
                http_status=response.status_code,
            )

        data = body["data"]
        if not isinstance(data, list):
            raise TakeadsClientError(
                "takeads_invalid_response",
                "Takeads returned an incomplete response. Retry in a moment.",
                http_status=response.status_code,
            )
        if not data:
            return TakeadsResolveResult(
                tracking_link=None,
                returned_iri=None,
                no_eligible_offer=True,
            )

        matching_item = data[0]
        submitted_iri = _normalized_iri(product_url)
        if (
            not isinstance(matching_item, dict)
            or _normalized_iri(matching_item.get("iri")) != submitted_iri
        ):
            raise TakeadsClientError(
                "takeads_iri_mismatch",
                "Takeads returned a link for a different destination. Retry or inspect the original product URL.",
                http_status=response.status_code,
            )

        returned_iri = _clean(matching_item.get("iri"))
        tracking_link = _clean(matching_item.get("trackingLink"))
        if not _valid_http_url(tracking_link):
            raise TakeadsClientError(
                "takeads_missing_tracking_link",
                "Takeads did not return a usable affiliate link for this product.",
                http_status=response.status_code,
            )

        return TakeadsResolveResult(
            tracking_link=tracking_link,
            returned_iri=returned_iri,
        )

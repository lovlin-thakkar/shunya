"""Thin wrapper around the Shunya REST API."""
import json
import os
import httpx

# SHUNYA_BASE_URL is the canonical env var name (documented in CLAUDE.md).
# SHUNYA_API_URL is accepted as a legacy alias.
BASE_URL = (
    os.environ.get("SHUNYA_BASE_URL")
    or os.environ.get("SHUNYA_API_URL")
    or "http://localhost:8000"
)
API_KEY = os.environ.get("SHUNYA_API_KEY", "")
TENANT_HOST = os.environ.get("SHUNYA_TENANT_HOST", "demo.localhost")


class ShunyaError(Exception):
    """User-facing error — printed cleanly by the CLI without a traceback."""


def _headers() -> dict:
    if not API_KEY:
        raise ShunyaError("SHUNYA_API_KEY is not set. Run: export SHUNYA_API_KEY=<your-key>")
    return {
        "Authorization": f"Api-Key {API_KEY}",
        "Host": TENANT_HOST,
    }


def _raise_for_status(r: httpx.Response) -> None:
    if r.is_success:
        return
    # Surface the API's error detail when present, otherwise a concise message.
    detail = ""
    try:
        body = r.json()
        if isinstance(body, dict):
            detail = body.get("detail") or body.get("error") or ""
    except json.JSONDecodeError:
        detail = (r.text or "").strip()[:200]
    if r.status_code == 404:
        raise ShunyaError(detail or f"Not found: {r.request.url.path}")
    if r.status_code in (401, 403):
        raise ShunyaError(detail or "Unauthorized — check SHUNYA_API_KEY and SHUNYA_TENANT_HOST.")
    raise ShunyaError(detail or f"API error {r.status_code} for {r.request.url.path}")


def _request(method: str, path: str, *, params=None, json=None) -> httpx.Response:
    try:
        with httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=30) as c:
            r = c.request(method, path, params=params, json=json)
    except httpx.ConnectError:
        raise ShunyaError(f"Cannot reach the Shunya API at {BASE_URL}. Is the server running?")
    _raise_for_status(r)
    return r


def get(path: str, **params) -> dict:
    return _request("GET", path, params=params or None).json()


def get_bytes(path: str) -> bytes:
    """Authenticated binary download (e.g. WAV recordings)."""
    return _request("GET", path).content


def post(path: str, data: dict) -> dict:
    return _request("POST", path, json=data).json()


def put(path: str, data: dict) -> dict:
    return _request("PUT", path, json=data).json()


def delete(path: str) -> None:
    _request("DELETE", path)

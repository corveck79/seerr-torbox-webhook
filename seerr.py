import logging

import requests

import config
import settings as _settings

log = logging.getLogger(__name__)


def _seerr_url() -> str:
    """Resolve SEERR_URL from settings DB first, env/config fallback."""
    return (_settings.get("SEERR_URL", config.SEERR_URL) or "").strip()


def _seerr_api_key() -> str:
    return (_settings.get("SEERR_API_KEY", config.SEERR_API_KEY) or "").strip()


def is_configured() -> bool:
    """True when a Seerr URL is set (settings DB or env). SPA-only mode → False."""
    return bool(_seerr_url())


def _headers() -> dict[str, str]:
    key = _seerr_api_key()
    return {"X-Api-Key": key} if key else {}


def get_request(request_id: str | int, timeout: int = 10) -> dict:
    base = _seerr_url()
    if not base:
        raise RuntimeError("SEERR_URL is not configured")
    url = f"{base.rstrip('/')}/api/v1/request/{request_id}"
    log.info("Fetching Seerr request: %s", url)
    resp = requests.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json() or {}


def list_approved_requests(take: int = 20, skip: int = 0, timeout: int = 10) -> list[dict]:
    base = _seerr_url()
    if not base:
        raise RuntimeError("SEERR_URL is not configured")
    url = f"{base.rstrip('/')}/api/v1/request"
    params = {"filter": "approved", "take": take, "skip": skip}
    log.info("Fetching approved Seerr requests (take=%d skip=%d)", take, skip)
    resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
    resp.raise_for_status()
    return (resp.json() or {}).get("results", [])

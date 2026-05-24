"""Trakt.tv API wrapper — device auth, token management, watchlist sync, scrobble."""
from __future__ import annotations

import logging
import time

import requests as req_lib

import db
import settings

log = logging.getLogger(__name__)

_BASE = "https://api.trakt.tv"


def _client_id() -> str:
    return settings.get("TRAKT_CLIENT_ID", "") or ""


def _client_secret() -> str:
    return settings.get("TRAKT_CLIENT_SECRET", "") or ""


def _headers(access_token: str | None = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": _client_id(),
    }
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    return h


# ── Token storage ──────────────────────────────────────────────────────────────

def get_token(user_id: int) -> dict | None:
    with db._connect() as c:
        row = c.execute(
            "SELECT * FROM trakt_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def save_token(user_id: int, access_token: str, refresh_token: str,
               expires_at: int, trakt_username: str | None = None) -> None:
    with db._connect() as c:
        c.execute(
            """INSERT INTO trakt_tokens
                   (user_id, access_token, refresh_token, expires_at, trakt_username)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   access_token   = excluded.access_token,
                   refresh_token  = excluded.refresh_token,
                   expires_at     = excluded.expires_at,
                   trakt_username = COALESCE(excluded.trakt_username, trakt_username)""",
            (user_id, access_token, refresh_token, expires_at, trakt_username),
        )


def delete_token(user_id: int) -> None:
    with db._connect() as c:
        c.execute("DELETE FROM trakt_tokens WHERE user_id = ?", (user_id,))


def _mark_synced(user_id: int) -> None:
    with db._connect() as c:
        c.execute(
            "UPDATE trakt_tokens SET synced_at = datetime('now') WHERE user_id = ?",
            (user_id,),
        )


def _get_all_tokens() -> list[dict]:
    with db._connect() as c:
        rows = c.execute("SELECT * FROM trakt_tokens").fetchall()
        return [dict(r) for r in rows]


# ── Token refresh ──────────────────────────────────────────────────────────────

def refresh_if_needed(tok: dict) -> dict:
    if time.time() < tok["expires_at"] - 3600:
        return tok
    try:
        r = req_lib.post(f"{_BASE}/oauth/token", json={
            "refresh_token": tok["refresh_token"],
            "client_id":     _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
            "grant_type":    "refresh_token",
        }, timeout=15)
        r.raise_for_status()
        d = r.json()
        new_tok = {**tok,
                   "access_token":  d["access_token"],
                   "refresh_token": d["refresh_token"],
                   "expires_at":    int(time.time()) + d["expires_in"]}
        save_token(tok["user_id"], new_tok["access_token"],
                   new_tok["refresh_token"], new_tok["expires_at"])
        return new_tok
    except Exception as exc:
        log.warning("Trakt token refresh failed for user %d: %s", tok["user_id"], exc)
        return tok


# ── Device auth ────────────────────────────────────────────────────────────────

def start_device_auth() -> dict:
    """Returns {device_code, user_code, verification_url, expires_in, interval}."""
    cid = _client_id()
    if not cid:
        raise ValueError("TRAKT_CLIENT_ID not configured")
    r = req_lib.post(f"{_BASE}/oauth/device/code",
                     json={"client_id": cid}, timeout=15)
    r.raise_for_status()
    return r.json()


def poll_device_auth(device_code: str) -> dict | None:
    """Returns token dict on success, None if still pending, raises on error."""
    r = req_lib.post(f"{_BASE}/oauth/device/token", json={
        "code":          device_code,
        "client_id":     _client_id(),
        "client_secret": _client_secret(),
    }, timeout=15)
    if r.status_code == 400:
        return None   # still waiting
    if r.status_code == 404:
        raise ValueError("Invalid device code")
    if r.status_code == 409:
        raise ValueError("Code already used")
    if r.status_code == 410:
        raise ValueError("Code expired")
    if r.status_code == 418:
        raise ValueError("Access denied by user")
    r.raise_for_status()
    return r.json()


def revoke_token(access_token: str) -> None:
    try:
        req_lib.post(f"{_BASE}/oauth/revoke", json={
            "token":         access_token,
            "client_id":     _client_id(),
            "client_secret": _client_secret(),
        }, timeout=10)
    except Exception as exc:
        log.warning("Trakt revoke failed: %s", exc)


# ── Profile ────────────────────────────────────────────────────────────────────

def get_me(access_token: str) -> dict | None:
    try:
        r = req_lib.get(f"{_BASE}/users/me",
                        headers=_headers(access_token), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Trakt get_me failed: %s", exc)
        return None


# ── Watchlist sync ─────────────────────────────────────────────────────────────

def _fetch_watchlist(access_token: str, kind: str) -> list[dict]:
    try:
        r = req_lib.get(f"{_BASE}/users/me/watchlist/{kind}",
                        headers=_headers(access_token), timeout=30)
        r.raise_for_status()
        return r.json() or []
    except Exception as exc:
        log.warning("Trakt watchlist/%s fetch failed: %s", kind, exc)
        return []


def sync_user_watchlist(user_id: int, access_token: str) -> int:
    """Pulls Trakt watchlist into Mycelium watchlist. Returns count added."""
    added = 0

    for item in _fetch_watchlist(access_token, "movies"):
        m = item.get("movie", {})
        ids = m.get("ids", {})
        imdb_id = ids.get("imdb")
        if not imdb_id:
            continue
        try:
            db.add_to_watchlist(user_id, imdb_id, ids.get("tmdb"),
                                "movie", m.get("title") or "", None)
            added += 1
        except Exception:
            pass

    for item in _fetch_watchlist(access_token, "shows"):
        s = item.get("show", {})
        ids = s.get("ids", {})
        imdb_id = ids.get("imdb")
        if not imdb_id:
            continue
        try:
            db.add_to_watchlist(user_id, imdb_id, ids.get("tmdb"),
                                "tv", s.get("title") or "", None)
            added += 1
        except Exception:
            pass

    _mark_synced(user_id)
    return added


def sync_all_users() -> None:
    """Background job: sync watchlists for all connected users."""
    for tok in _get_all_tokens():
        try:
            tok = refresh_if_needed(tok)
            count = sync_user_watchlist(tok["user_id"], tok["access_token"])
            log.info("Trakt sync: user %d — %d items", tok["user_id"], count)
        except Exception as exc:
            log.warning("Trakt sync failed for user %d: %s", tok["user_id"], exc)


# ── Scrobble ───────────────────────────────────────────────────────────────────

def scrobble(access_token: str, action: str, media_type: str,
             imdb_id: str, progress: float,
             season: int | None = None, episode: int | None = None,
             title: str | None = None) -> bool:
    """action: 'start' | 'pause' | 'stop'"""
    if media_type == "movie":
        payload = {
            "movie":    {"ids": {"imdb": imdb_id}, "title": title or ""},
            "progress": progress,
        }
    else:
        payload = {
            "show":    {"ids": {"imdb": imdb_id}},
            "episode": {"season": season, "number": episode},
            "progress": progress,
        }
    try:
        r = req_lib.post(f"{_BASE}/scrobble/{action}",
                         json=payload, headers=_headers(access_token), timeout=10)
        r.raise_for_status()
        return True
    except Exception as exc:
        log.warning("Trakt scrobble/%s failed: %s", action, exc)
        return False

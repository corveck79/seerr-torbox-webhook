"""Continue Watching priority: query Jellyfin for in-progress series, find the
next unaired/missing episode, and bump it to the front of monitor's search queue.
"""
import logging

import requests

import config
import db
import monitor
import settings as _settings

log = logging.getLogger(__name__)


def _jellyfin_resume_items() -> list[dict]:
    """Items currently being watched across all users."""
    jellyfin_url = (_settings.get("JELLYFIN_URL", config.JELLYFIN_URL) or "").strip()
    jellyfin_key = (_settings.get("JELLYFIN_API_KEY", config.JELLYFIN_API_KEY) or "").strip()
    if not (jellyfin_url and jellyfin_key):
        return []
    try:
        r = requests.get(
            f"{jellyfin_url.rstrip('/')}/Users/Me/Items/Resume",
            params={"Limit": 50},
            headers={"X-Emby-Token": jellyfin_key},
            timeout=8,
        )
        r.raise_for_status()
        return (r.json() or {}).get("Items") or []
    except Exception as exc:
        log.debug("Jellyfin Resume fetch failed: %s", exc)
        return []


def prioritize_next_episodes() -> int:
    """For each in-progress series in Jellyfin, search for its next wanted episode."""
    items = _jellyfin_resume_items()
    if not items:
        return 0
    priorities = 0
    series_items = [i for i in items if i.get("Type") == "Episode"]
    # Use SeriesName to match our monitored series
    monitored = {s["title"]: s for s in db.get_all_monitored_series()}
    wanted = db.get_wanted_episodes()
    for it in series_items:
        series_name = it.get("SeriesName")
        if not series_name or series_name not in monitored:
            continue
        m = monitored[series_name]
        # Find lowest (season, episode) still wanted for this series
        ours = sorted(
            [w for w in wanted if w["imdb_id"] == m["imdb_id"]],
            key=lambda w: (w["season"], w["episode"]),
        )
        if not ours:
            continue
        next_ep = ours[0]
        log.info("ContinueWatching: prioritizing %s S%02dE%02d",
                 series_name, next_ep["season"], next_ep["episode"])
        try:
            monitor.search_episode_now(
                m["imdb_id"], series_name, next_ep["season"], next_ep["episode"],
            )
            priorities += 1
        except Exception as exc:
            log.warning("ContinueWatching: search failed for %s: %s", series_name, exc)
    return priorities

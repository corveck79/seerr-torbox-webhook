"""Pre-cache TMDB trending movies if cached on TorBox.

Background task: GET /trending/movie/week from TMDB, take top N, look up IMDB
IDs, search Zilean/Torrentio, filter to cached-only, add the best release.

Only fires for items not already in our request history.
"""
import logging

import db
import processor
import tmdb
from config import TRENDING_PRECACHE_COUNT
from webhook_parser import MediaRequest

log = logging.getLogger(__name__)


def run() -> int:
    if TRENDING_PRECACHE_COUNT <= 0:
        return 0
    log.info("Trending: pre-cache top %d", TRENDING_PRECACHE_COUNT)

    data = tmdb._get("/trending/movie/week")
    if not data:
        return 0
    results = (data.get("results") or [])[: TRENDING_PRECACHE_COUNT]
    if not results:
        return 0

    seen = {r["imdb_id"] for r in db.get_recent(2000)}
    added = 0
    for item in results:
        tmdb_id = item.get("id")
        title = item.get("title") or item.get("original_title") or ""
        if not tmdb_id or not title:
            continue
        imdb_id = tmdb.tmdb_to_imdb(tmdb_id, media_type="movie")
        if not imdb_id or imdb_id in seen:
            continue
        log.info("Trending: queueing %s (%s)", title, imdb_id)
        req = MediaRequest(title=title, media_type="movie", imdb_id=imdb_id, seasons=[])
        # Mark as trending-source so we can filter it out of stats later
        try:
            processor.process(req)
            added += 1
        except Exception as exc:
            log.warning("Trending: failed to process %s: %s", title, exc)
    log.info("Trending: %d new title(s) processed", added)
    return added

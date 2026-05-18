import logging
import time

import jellyfin
import torbox
import torrentio
from config import JELLYFIN_REFRESH_DELAY_SEC
from webhook_parser import MediaRequest

log = logging.getLogger(__name__)


def _add_best_from(candidates: list, label: str) -> bool:
    """Try each ranked candidate in order; return True on first success."""
    for stream in candidates:
        try:
            torbox.add_magnet(stream.magnet)
            torbox.wait_until_ready(stream.info_hash)
            return True
        except Exception as exc:
            log.warning(
                "Failed to add %s (hash=%s quality=%s): %s — trying next candidate",
                label, stream.info_hash, stream.quality, exc,
            )
    log.error("All %d candidate(s) failed for %s", len(candidates), label)
    return False


def _process_movie(req: MediaRequest) -> bool:
    streams = torrentio.fetch_streams("movie", req.imdb_id)
    candidates = torrentio.rank_streams(streams)
    if not candidates:
        log.error("No suitable stream for movie %s (%s)", req.title, req.imdb_id)
        return False
    log.info("Trying %d candidate(s) for %s", len(candidates), req.title)
    return _add_best_from(candidates, req.title)


def _process_season(req: MediaRequest, season: int) -> bool:
    streams = torrentio.fetch_streams("series", req.imdb_id, season=season, episode=1)
    pack_candidates = torrentio.rank_streams(streams, prefer_season_pack=True)

    if pack_candidates and pack_candidates[0].is_season_pack:
        log.info("Trying season pack(s) for %s S%02d", req.title, season)
        if _add_best_from(
            [s for s in pack_candidates if s.is_season_pack],
            f"{req.title} S{season:02d} pack",
        ):
            return True
        log.info("Season pack(s) failed; falling back to per-episode")

    log.info("No season pack for %s S%02d; going per-episode", req.title, season)
    added = 0
    episode = 1
    while True:
        ep_streams = (
            streams
            if episode == 1
            else torrentio.fetch_streams("series", req.imdb_id, season=season, episode=episode)
        )
        if not ep_streams:
            log.info("No more episodes returned at S%02dE%02d", season, episode)
            break
        ep_candidates = torrentio.rank_streams(ep_streams)
        if ep_candidates:
            if _add_best_from(ep_candidates, f"{req.title} S{season:02d}E{episode:02d}"):
                added += 1
        episode += 1
        if episode > 50:
            log.warning("Episode cap (50) reached for %s S%02d", req.title, season)
            break
    return added > 0


def process(req: MediaRequest) -> bool:
    log.info("Processing request: %s [%s] %s", req.title, req.media_type, req.imdb_id)
    success = False
    try:
        if req.is_movie:
            success = _process_movie(req)
        else:
            for season in req.seasons:
                if _process_season(req, season):
                    success = True
    finally:
        if success:
            if JELLYFIN_REFRESH_DELAY_SEC > 0:
                log.info("Waiting %ds before triggering Jellyfin refresh", JELLYFIN_REFRESH_DELAY_SEC)
                time.sleep(JELLYFIN_REFRESH_DELAY_SEC)
            jellyfin.refresh_library()
        else:
            log.warning("No content added; skipping Jellyfin refresh for %s", req.title)
    return success

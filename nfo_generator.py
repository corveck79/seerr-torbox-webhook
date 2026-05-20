"""Generate Kodi/Jellyfin-compatible NFO sidecar files alongside .strm files.

Movies: movies/Title (Year)/Title (Year).nfo
Series: series/Title/tvshow.nfo

Jellyfin reads these to get the exact IMDb ID, so it can fetch metadata and
posters without guessing from the folder name.  When multiple folders exist
for the same series (different torrent sources), writing the same IMDb ID in
all tvshow.nfo files allows Jellyfin to merge them into a single library entry.
"""
import logging
import re
import time
from pathlib import Path

import db
import tmdb
from config import MEDIA_PATH

log = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\((\d{4})\)$")
_SEASON_TRAIL_RE = re.compile(r'\s+(?:S\d{1,2}(?:E\d+)?|Season\s+\d+).*$', re.IGNORECASE)
_YEAR_TRAIL_RE = re.compile(r'\s+\d{4}$')
_PREFIX_RE = re.compile(
    r'^(\[[^\]]+\]\s*|www[\s.][\w.\-]+(?:[\s.][\w.\-]+)*\s*-\s*|www\s+\w+\s+\w+\s*-\s*'
    r'|rutor\.?\s*info\s*|\[?DEVIL-TORRENTS[^\]]*\]?\s*|HIDRATORRENTS[^\s]*\s*(?:MKV)?\s*-?(?:LEGENDADO)?-?\s*'
    r'|superseed\s+\S+\s*|\[BEST-TORRENTS[^\]]*\]\s*|\[XTORRENTY[^\]]*\]\s*)+',
    re.IGNORECASE,
)


def _clean_for_tmdb(raw: str) -> str:
    s = _PREFIX_RE.sub("", raw).strip()
    s = _SEASON_TRAIL_RE.sub("", s).strip()
    s = _YEAR_TRAIL_RE.sub("", s).strip()
    s = re.sub(r"[\[\(\{\s\-]+$", "", s).strip()
    return s


def _movie_nfo(title: str, year: int | None, imdb_id: str) -> str:
    year_tag = f"\n  <year>{year}</year>" if year else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<movie>\n"
        f"  <title>{title}</title>{year_tag}\n"
        f'  <uniqueid type="imdb" default="true">{imdb_id}</uniqueid>\n'
        "</movie>\n"
    )


def _tvshow_nfo(title: str, imdb_id: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<tvshow>\n"
        f"  <title>{title}</title>\n"
        f'  <uniqueid type="imdb" default="true">{imdb_id}</uniqueid>\n'
        "</tvshow>\n"
    )


def _write(path: Path, content: str) -> bool:
    if path.exists():
        return False
    try:
        path.write_text(content, encoding="utf-8")
        log.info("Wrote NFO: %s", path)
        return True
    except Exception as exc:
        log.warning("Could not write NFO %s: %s", path, exc)
        return False


def generate_all() -> dict:
    """Write missing NFO files for all movies and series using IMDb IDs from DB.

    For series folders not found in the DB (messy torrent names), a TMDB lookup
    is attempted so that duplicate series folders get the same IMDb ID in their
    tvshow.nfo — Jellyfin then merges them into a single library entry.
    """
    media = Path(MEDIA_PATH)
    items_by_title = {m["title"]: m["imdb_id"] for m in db.get_media_items()}
    # Secondary lookup: imdb_id → title (canonical)
    monitored_by_imdb = {s["imdb_id"]: s["title"] for s in db.get_all_monitored_series()}

    movies = series = 0

    movies_dir = media / "movies"
    if movies_dir.is_dir():
        for folder in movies_dir.iterdir():
            if not folder.is_dir():
                continue
            nfo_path = folder / f"{folder.name}.nfo"
            if nfo_path.exists():
                continue
            imdb_id = items_by_title.get(folder.name)
            if not imdb_id or imdb_id.startswith("unknown_"):
                # Not in DB — try TMDB lookup so metadata + posters are fetched
                clean = _clean_for_tmdb(folder.name)
                if not clean:
                    continue
                m_yr = _YEAR_RE.search(folder.name)
                year_hint = int(m_yr.group(1)) if m_yr else None
                try:
                    imdb_id = tmdb.search_movie(clean, year_hint)
                    time.sleep(0.2)
                except Exception:
                    imdb_id = None
                if not imdb_id:
                    continue
            m = _YEAR_RE.search(folder.name)
            year = int(m.group(1)) if m else None
            title = _YEAR_RE.sub("", folder.name).strip() if m else folder.name
            if _write(nfo_path, _movie_nfo(title, year, imdb_id)):
                movies += 1

    series_dir = media / "series"
    if series_dir.is_dir():
        for folder in series_dir.iterdir():
            if not folder.is_dir():
                continue
            nfo_path = folder / "tvshow.nfo"
            if nfo_path.exists():
                continue

            imdb_id = items_by_title.get(folder.name)
            if not imdb_id or imdb_id.startswith("unknown_"):
                # Not in DB — try TMDB lookup so duplicate folders get the right ID
                clean = _clean_for_tmdb(folder.name)
                if not clean:
                    continue
                try:
                    imdb_id = tmdb.search_tv(clean)
                    time.sleep(0.2)
                except Exception:
                    imdb_id = None
                if not imdb_id:
                    continue

            # Use canonical title from monitored_series if available
            display_title = monitored_by_imdb.get(imdb_id, _clean_for_tmdb(folder.name) or folder.name)
            if _write(nfo_path, _tvshow_nfo(display_title, imdb_id)):
                series += 1

    log.info("NFO generation complete: %d movie(s), %d series", movies, series)
    return {"movies": movies, "series": series}

import logging
import re
from pathlib import Path

import requests as req_lib

import db
import jellyfin
import settings
import torbox as torbox_mod
from config import MEDIA_PATH, TORBOX_BASE_URL

log = logging.getLogger(__name__)

_VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.ts', '.m2ts', '.webm'}

_EP_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,2})', re.IGNORECASE)
_YEAR_RE = re.compile(r'(?<!\d)((?:19|20)\d{2})(?!\d)')
# Strip leading site/group prefixes from torrent names before parsing:
#   [DEVIL-TORRENTS PL]  /  rutor.info  /  www.UIndex.org  /  HIDRATORRENTS.ORG  etc.
_SITE_PREFIX_RE = re.compile(
    r'^(?:\[[^\]]*\]\s*|(?:www\.|https?://)\S+\s*|'
    r'(?:rutor|hidratorrents|warmachine|xtorrenty|superseed|byethost\d*|'
    r'uindex|devil-torrents)\s*[\.\-]?\s*(?:info|org|pl|com|net)?\s*[-–—\s]*)+'
    , re.IGNORECASE,
)
# Strip leading Cyrillic block (keeps Latin title when torrent has both)
_CYRILLIC_PREFIX_RE = re.compile(r'^[Ѐ-ӿ\s\(\)\[\]\.,\-–—«»]+')
_JUNK_RE = re.compile(
    r'\s*\b(?:2160[pi]?|4K|UHD|1080[pi]?|720[pi]?|480[pi]?|HDTV|WEB[-.]?DL|WEBRip|WEB\b|'
    r'BluRay|BDRip|DVDRip|REMUX|HEVC|x\.?265|x\.?264|AVC|H\.?26[45]|'
    r'AAC\d*|DTS(?:-HD)?|AC3|EAC3|Atmos|TrueHD|HDR(?:10)?|DV|DoVi|SDR|10[Bb]it|8[Bb]it|'
    r'PROPER|REPACK|EXTENDED|DC|THEATRICAL|UNRATED|IMAX|'
    r'YIFY|YTS|NTb|SPARKS|FGT|RARBG|ettv|eztv)\b.*$',
    re.IGNORECASE,
)
_SAFE_RE = re.compile(r'[/\\:*?"<>|]')
_TRAILER_RE = re.compile(
    r'\b(trailer|sample|extras?|featurette|bonus|deleted[. _-]?scenes?|'
    r'behind[. _-]the[. _-]scenes|making[. _-]of|promo|teaser)\b',
    re.IGNORECASE,
)
_MIN_MOVIE_SIZE = 200 * 1024 * 1024  # 200 MB — anything smaller is likely a trailer/sample


def _is_video(name: str) -> bool:
    return Path(name).suffix.lower() in _VIDEO_EXTS


def _is_trailer(file: dict) -> bool:
    return bool(_TRAILER_RE.search(file.get('name') or ''))


def _pick_main_movie_file(files: list[dict]) -> dict | None:
    """Return the best video file for a movie torrent: largest non-trailer file."""
    videos = [f for f in files if _is_video(f.get('name') or '')]
    if not videos:
        return None
    non_trailer = [f for f in videos if not _is_trailer(f)]
    if not non_trailer:
        return None
    big = [f for f in non_trailer if (f.get('size') or 0) >= _MIN_MOVIE_SIZE]
    return max(big or non_trailer, key=lambda f: f.get('size') or 0)


def _clean_torrent_name(name: str) -> str:
    """Strip site prefixes and Cyrillic blocks from a raw torrent name."""
    s = _SITE_PREFIX_RE.sub('', name).strip()
    s = _CYRILLIC_PREFIX_RE.sub('', s).strip()
    # Also strip anything left in leading square brackets
    s = re.sub(r'^\[[^\]]*\]\s*', '', s).strip()
    return s or name  # fall back to original if everything got stripped


def _clean(s: str) -> str:
    return re.sub(r'[._]', ' ', s).strip()


def _strip_junk(s: str) -> str:
    return _JUNK_RE.sub('', s).strip(' .-_ ')


def _safe(s: str) -> str:
    return _SAFE_RE.sub('', s).strip().rstrip('([{ -')


def _parse_info(torrent_name: str, file_name: str) -> dict | None:
    """Extract title/year/season/episode from torrent and file names."""
    torrent_name = _clean_torrent_name(torrent_name)
    file_base = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', file_name)

    # Episode: try file name first (most reliable for season packs)
    for source in (_clean(file_base), _clean(torrent_name)):
        ep_m = _EP_RE.search(source)
        if ep_m:
            season = int(ep_m.group(1))
            episode = int(ep_m.group(2))
            title = _safe(_strip_junk(source[:ep_m.start()]).strip())
            return {'type': 'episode', 'title': title or 'Unknown', 'season': season, 'episode': episode}

    # Movie: find year
    for source in (_clean(torrent_name), _clean(file_base)):
        yr_m = _YEAR_RE.search(source)
        if yr_m:
            year = int(yr_m.group(1))
            title = _safe(_strip_junk(source[:yr_m.start()]).strip())
            return {'type': 'movie', 'title': title or 'Unknown', 'year': year}

    # Fallback: cleaned torrent name as untitled movie
    title = _safe(_strip_junk(_clean(torrent_name)).strip())
    return {'type': 'movie', 'title': title} if title else None


def _strm_path(info: dict) -> Path:
    media = Path(MEDIA_PATH)
    if info['type'] == 'movie':
        year = info.get('year')
        folder = f"{info['title']} ({year})" if year else info['title']
        return media / 'movies' / folder / f"{folder}.strm"
    title = info['title']
    s, e = info['season'], info['episode']
    return media / 'series' / title / f"Season {s:02d}" / f"{title} S{s:02d}E{e:02d}.strm"


def _get_stream_url(torrent_id: int, file_id: int) -> str | None:
    url = f"{TORBOX_BASE_URL.rstrip('/')}/torrents/requestdl"
    params = {
        "token": settings.get("TORBOX_API_KEY", ""),
        "torrent_id": torrent_id,
        "file_id": file_id,
        "zip_link": "false",
    }
    try:
        resp = req_lib.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json() or {}
        return data.get("data") or None
    except Exception as exc:
        log.warning("requestdl failed torrent=%s file=%s: %s", torrent_id, file_id, exc)
        return None


def _extract_year(name: str) -> int | None:
    m = _YEAR_RE.search(name or "")
    return int(m.group(1)) if m else None


def _write_nfo(strm_path: Path, imdb_id: str | None, tmdb_id: int | None = None,
               media_type: str = "movie") -> None:
    """Write a Kodi/Jellyfin NFO sidecar next to a .strm file.
    Jellyfin reads the IMDb/TMDB uniqueid to fetch metadata + posters directly,
    bypassing unreliable name-matching against the folder name."""
    if not imdb_id and not tmdb_id:
        return
    nfo_path = strm_path.with_suffix(".nfo")
    if nfo_path.exists():
        return
    m = _YEAR_RE.search(strm_path.parent.name)
    year = int(m.group(1)) if m else None
    title = _YEAR_RE.sub("", strm_path.parent.name).strip() if m else strm_path.parent.name

    if media_type == "movie":
        year_tag = f"\n  <year>{year}</year>" if year else ""
        uid_tags = ""
        if imdb_id:
            uid_tags += f'  <uniqueid type="imdb" default="true">{imdb_id}</uniqueid>\n'
        if tmdb_id:
            uid_tags += f'  <uniqueid type="tmdb">{tmdb_id}</uniqueid>\n'
        content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f"<movie>\n  <title>{title}</title>{year_tag}\n{uid_tags}</movie>\n"
        )
    else:
        uid_tags = ""
        if imdb_id:
            uid_tags += f'  <uniqueid type="imdb" default="true">{imdb_id}</uniqueid>\n'
        if tmdb_id:
            uid_tags += f'  <uniqueid type="tmdb">{tmdb_id}</uniqueid>\n'
        content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f"<tvshow>\n  <title>{title}</title>\n{uid_tags}</tvshow>\n"
        )
    try:
        nfo_path.write_text(content, encoding="utf-8")
        log.info("Wrote NFO: %s", nfo_path)
    except Exception as exc:
        log.warning("Could not write NFO %s: %s", nfo_path, exc)


def create_lazy_movie_strm(info_hash: str, magnet: str, title: str,
                            year: int | None, imdb_id: str | None = None,
                            tmdb_id: int | None = None) -> bool:
    """Write a Catbox virtual movie .strm WITHOUT adding the torrent to TorBox.
    createtorrent is deferred until first playback (see catbox.materialize).
    Returns True if a new .strm was written."""
    import catbox
    folder = _safe(f"{title} ({year})") if year else _safe(title)
    if not folder:
        return False
    path = Path(MEDIA_PATH) / "movies" / folder / f"{folder}.strm"
    token = catbox.register(
        info_hash=(info_hash or "").lower(),
        magnet=magnet,
        title=folder,
        media_type="movie",
        torbox_id=None,   # ← deferred: no createtorrent yet
        file_id=None,
        strm_path=str(path),
    )
    written = _write_strm(path, catbox.proxy_url(token))
    if written and (imdb_id or tmdb_id):
        _write_nfo(path, imdb_id, tmdb_id)
    return written


def _norm_title(s: str) -> str:
    """Normalize a folder/title string for fuzzy duplicate detection.
    Strips year in parens, leading articles, punctuation, and lowercases."""
    s = re.sub(r'\(\d{4}\)', '', s)           # remove (year)
    s = re.sub(r'^(the|a|an)\s+', '', s, flags=re.IGNORECASE)  # strip leading article
    return re.sub(r'[^a-z0-9]', '', s.lower())  # alphanumeric only


def _write_strm(path: Path, url: str) -> bool:
    """Write .strm file only if it doesn't exist. Returns True if a new file was written."""
    if path.exists():
        return False
    # Fuzzy duplicate check: skip if any existing sibling folder normalizes to the same title.
    # Catches "The Minecraft Movie (2025)" vs "Minecraft Movie The (2025)", case differences, etc.
    parent = path.parent.parent  # movies/ or series/
    norm = _norm_title(path.parent.name)
    if parent.is_dir():
        for existing in parent.iterdir():
            if existing.is_dir() and existing != path.parent and _norm_title(existing.name) == norm:
                log.info("Skipping duplicate strm %s — already have %s", path.parent.name, existing.name)
                return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(url, encoding='utf-8')
        log.info("Created .strm: %s", path)
        return True
    except Exception as exc:
        log.warning("Could not write %s: %s", path, exc)
        return False


def _resolve_url(item: dict, file_id: int, file_name: str, info: dict, media_type: str) -> str | None:
    """Return the URL to write into a .strm file.
    In Catbox mode this is a proxy URL pointing at /stream/<token>.
    Otherwise it is the direct TorBox CDN URL.
    """
    torrent_id = item.get("id")
    if settings.get("CATBOX_MODE", False):
        import catbox
        magnet = item.get("magnet") or f"magnet:?xt=urn:btih:{item.get('hash')}"
        title = f"{info.get('title','')} ({info['year']})" if info.get("year") else info.get("title", file_name)
        token = catbox.register(
            info_hash=(item.get("hash") or "").lower(),
            magnet=magnet,
            title=title,
            media_type=media_type,
            torbox_id=torrent_id,
            file_id=file_id,
        )
        return catbox.proxy_url(token)
    return _get_stream_url(torrent_id, file_id)


def process_torrent(item: dict) -> int:
    """Create .strm files for all video files in a ready torrent. Returns new file count."""
    torrent_id = item.get('id')
    torrent_name = _clean_torrent_name(item.get('name') or '')
    files = item.get('files') or []

    if not torbox_mod._is_ready(item):
        return 0

    # In Catbox mode: if this hash is already registered and the strm still exists on disk,
    # skip entirely — avoids creating a second folder with the torrent-parsed title
    # when the movie was originally added with the TMDB title.
    if settings.get("CATBOX_MODE", False):
        info_hash = (item.get('hash') or '').lower()
        if info_hash:
            existing = db.get_virtual_item_by_hash(info_hash)
            if existing and existing.get('strm_path') and Path(existing['strm_path']).exists():
                log.debug("process_torrent: %s already has strm at %s — skipping",
                          torrent_name, existing['strm_path'])
                return 0

    is_series = bool(_EP_RE.search(_clean(torrent_name)) or
                     re.search(r'\bS\d{1,2}\b', torrent_name, re.IGNORECASE))
    if not is_series and _TRAILER_RE.search(_clean(torrent_name)):
        log.debug("Skipping trailer torrent %s (%s)", torrent_id, torrent_name)
        return 0
    if is_series:
        video_files = [f for f in files if _is_video(f.get('name') or '') and not _is_trailer(f)]
    else:
        main_file = _pick_main_movie_file(files)
        video_files = [main_file] if main_file else []

    if not video_files:
        log.debug("No suitable video files in torrent %s (%s)", torrent_id, torrent_name)
        return 0

    written = 0
    for f in video_files:
        file_id = f.get('id')
        file_name = f.get('name') or ''
        info = _parse_info(torrent_name, file_name)
        if info is None:
            log.warning("Cannot determine placement: torrent=%r file=%r", torrent_name, file_name)
            continue
        path = _strm_path(info)
        if path.exists():
            continue
        url = _resolve_url(item, file_id, file_name, info, info['type'] if info['type'] == 'movie' else 'series')
        if not url:
            continue
        if _write_strm(path, url):
            written += 1

    return written


def create_strm_for_torrent(torrent_id: int, title: str, media_type: str,
                             imdb_id: str | None = None, tmdb_id: int | None = None) -> int:
    """
    Immediately create .strm file(s) for a just-added torrent.
    For movies: uses file_id=0 (fast, ~1 API call).
    For series: fetches the torrent's file list from mylist and creates per-episode .strm files.
    Returns count of new files written.
    """
    item = torbox_mod.find_by_id(torrent_id)
    if not item:
        log.warning("Torrent %s not found in mylist for strm creation", torrent_id)
        return 0

    if media_type == 'movie':
        main_file = _pick_main_movie_file(item.get('files') or [])
        if not main_file:
            log.warning("No suitable video file in torrent %s", torrent_id)
            return 0
        yr = _YEAR_RE.search(title)
        year = int(yr.group(1)) if yr else None
        clean_title = _safe(title[:yr.start()].strip() if yr else title)
        folder = f"{clean_title} ({year})" if year else clean_title
        path = Path(MEDIA_PATH) / 'movies' / folder / f"{folder}.strm"
        info = {'type': 'movie', 'title': clean_title, 'year': year}
        url = _resolve_url(item, main_file['id'], main_file.get('name', ''), info, 'movie')
        if not url:
            return 0
        written = _write_strm(path, url)
        if written and (imdb_id or tmdb_id):
            _write_nfo(path, imdb_id, tmdb_id)
        return 1 if written else 0

    return process_torrent(item)


def create_series_strms_from_files(torrent_name: str, files_with_urls: list) -> int:
    """For a season-pack torrent on any debrid provider, write per-episode .strm
    files. files_with_urls is a list of (file_dict_with_path_and_size, direct_url).
    Returns count of new files written."""
    written = 0
    for f, url in files_with_urls:
        file_name = (f.get("path") or f.get("name") or "").lstrip("/").split("/")[-1]
        info = _parse_info(torrent_name, file_name)
        if not info or info["type"] != "episode":
            log.debug("Skip non-episode file: %s", file_name)
            continue
        path = _strm_path(info)
        if path.exists():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(url, encoding="utf-8")
            log.info("Created series .strm: %s", path)
            written += 1
        except Exception as exc:
            log.warning("Could not write series .strm %s: %s", path, exc)
    return written


def create_episode_strm_from_url(title: str, season: int, episode: int,
                                   url: str) -> Path | None:
    """Write a single-episode .strm at series/{Title}/Season XX/{Title} SnnEmm.strm."""
    if not url:
        return None
    clean_title = _safe(title)
    if not clean_title:
        return None
    season_folder = f"Season {season:02d}"
    file_name = f"{clean_title} S{season:02d}E{episode:02d}.strm"
    path = Path(MEDIA_PATH) / "series" / clean_title / season_folder / file_name
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(url, encoding="utf-8")
        log.info("Created episode .strm: %s", path)
        return path
    except Exception as exc:
        log.warning("Could not write episode .strm %s: %s", path, exc)
        return None


def create_movie_strm_from_url(title: str, url: str) -> Path | None:
    """Write a movie .strm pointing at a direct CDN URL (e.g. RealDebrid).
    Parses year from the title and builds the standard movies/Title (Year)/Title (Year).strm
    path. Returns the written path, or None on failure."""
    if not url:
        return None
    yr = _YEAR_RE.search(title)
    year = int(yr.group(1)) if yr else None
    clean_title = _safe(title[:yr.start()].strip() if yr else title)
    folder = f"{clean_title} ({year})" if year else clean_title
    path = Path(MEDIA_PATH) / "movies" / folder / f"{folder}.strm"
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(url, encoding="utf-8")
        log.info("Created RD .strm: %s", path)
        return path
    except Exception as exc:
        log.warning("Could not write RD .strm %s: %s", path, exc)
        return None


def run_once() -> int:
    """Scan entire TorBox mylist and create any missing .strm files. Returns new file count."""
    log.info("strm_generator: scanning TorBox mylist")
    try:
        torrents = torbox_mod.list_torrents()
    except Exception as exc:
        log.error("strm_generator: mylist failed: %s", exc)
        return 0
    total = sum(process_torrent(t) for t in torrents)
    log.info("strm_generator: %d new .strm file(s) created", total)
    return total


def run_and_refresh() -> None:
    """Run strm generation and trigger Jellyfin scan if any new files were created."""
    new_files = run_once()
    import nfo_generator
    nfo_generator.generate_all()
    if new_files > 0:
        jellyfin.refresh_library()
    # Self-healing: proactive health probe of a small sample of existing strms.
    try:
        _self_heal_sample()
    except Exception as exc:
        log.debug("Self-heal sample failed: %s", exc)


def _self_heal_sample(sample_size: int = 10) -> None:
    """HEAD-check a random sample of existing .strm files. If a high fraction
    fail, log a warning and let the next cleanup cycle do the heavy lifting."""
    import random
    media = Path(MEDIA_PATH)
    if not media.is_dir():
        return
    strms: list[Path] = []
    for sub in ("movies", "series"):
        d = media / sub
        if d.is_dir():
            strms.extend(d.rglob("*.strm"))
    if len(strms) <= 5:
        return
    sample = random.sample(strms, min(sample_size, len(strms)))
    bad = 0
    for s in sample:
        try:
            url = s.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        # Catbox proxy URLs always work — skip the probe
        if "/stream/" in url and url.startswith("http://"):
            continue
        try:
            r = req_lib.head(url, timeout=5, allow_redirects=True)
            if r.status_code >= 400:
                bad += 1
        except Exception:
            bad += 1
    if bad and bad / len(sample) >= 0.3:
        log.warning("Self-heal probe: %d/%d sampled strms failed; cleanup will repair",
                    bad, len(sample))

import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db
import strm_generator
import tmdb
import torbox
import torrentio
import zilean
import settings as _settings
from config import MEDIA_PATH
from torrentio import TorrentioStream

log = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\((\d{4})\)$")
_TORRENT_ID_RE = re.compile(r"torrent_id[=:](\d+)", re.IGNORECASE)
_FILE_ID_RE = re.compile(r"file_id[=:](\d+)", re.IGNORECASE)
_EP_FILENAME_RE = re.compile(r"S(\d{1,2})E(\d{1,2})", re.IGNORECASE)


def _extract_file_id(strm_url: str) -> str | None:
    m = _FILE_ID_RE.search(strm_url)
    return m.group(1) if m else None


def _normalize_title(s: str) -> str:
    s = re.sub(r"[^\w\s]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _extract_torrent_id(strm_url: str) -> str | None:
    m = _TORRENT_ID_RE.search(strm_url)
    if m:
        return m.group(1)
    try:
        qs = parse_qs(urlparse(strm_url).query)
        for key in ("torrent_id", "TorrentId", "id"):
            if key in qs:
                return qs[key][0]
    except Exception:
        pass
    return None


def _parse_folder_name(folder: str) -> tuple[str, int | None]:
    """Return (title, year) from a folder like 'Movie Title (2022)'."""
    m = _YEAR_RE.search(folder.strip())
    if m:
        year = int(m.group(1))
        title = folder[: m.start()].strip()
        return title, year
    return folder.strip(), None


def _collect_strm_files() -> list[Path]:
    media = Path(MEDIA_PATH)
    strm_files: list[Path] = []
    for subdir in ("movies", "series"):
        base = media / subdir
        if base.is_dir():
            strm_files.extend(base.rglob("*.strm"))
    return strm_files


def _is_available_in_mylist(torrent_id: str, mylist: list[dict]) -> bool:
    for item in mylist:
        if str(item.get("id") or "") == torrent_id:
            return True
    return False


def _resolve_imdb(title: str, year: int | None, media_type: str) -> str | None:
    if media_type == "movie":
        return tmdb.search_movie(title, year=year)
    return tmdb.search_tv(title)


def _fetch_candidates(imdb_id: str, title: str, media_type: str) -> list:
    if media_type == "movie":
        if _settings.get("ZILEAN_ENABLED", False):
            streams = zilean.fetch_streams(imdb_id)
            candidates = torrentio.rank_streams(streams)
            if candidates:
                return candidates
        streams = torrentio.fetch_streams("movie", imdb_id)
        return torrentio.rank_streams(streams)
    else:
        if _settings.get("ZILEAN_ENABLED", False):
            streams = zilean.fetch_streams(imdb_id, season=1, episode=1)
            candidates = torrentio.rank_streams(streams, prefer_season_pack=True)
            if candidates:
                return candidates
        streams = torrentio.fetch_streams("series", imdb_id, season=1, episode=1)
        return torrentio.rank_streams(streams, prefer_season_pack=True)


def _repair_strm(path: Path, run_id: int, mylist: list[dict]) -> str:
    """
    Attempt to repair a single .strm file.
    Returns one of: 'ok' (still valid), 'repaired', 'deleted', 'unfixable'.
    """
    try:
        url = path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        db.insert_repair_item(run_id, str(path), None, None, None, None,
                              "unfixable", f"unreadable: {exc}")
        return "unfixable"

    torrent_id = _extract_torrent_id(url)

    # Determine media type from path structure
    rel = path.relative_to(MEDIA_PATH) if path.is_relative_to(MEDIA_PATH) else path
    parts = rel.parts
    media_type = "series" if (len(parts) > 0 and parts[0] == "series") else "movie"

    # Non-TorBox URLs (e.g. RealDebrid direct links, Catbox proxy) have a different
    # lifecycle and cleanup logic doesn't apply.
    if "real-debrid.com" in url or "/d/" in url or "/stream/" in url:
        return "ok"

    if torrent_id and _is_available_in_mylist(torrent_id, mylist):
        log.debug("strm OK (torrent_id=%s): %s", torrent_id, path.name)
        return "ok"

    # Torrent gone — try to repair
    folder_name = path.parent.name
    title, year = _parse_folder_name(folder_name)
    log.info("Broken strm: %s (torrent_id=%s) — searching replacement for '%s'",
             path.name, torrent_id, title)

    imdb_id = _resolve_imdb(title, year, media_type)
    if not imdb_id:
        log.warning("Could not resolve IMDB ID for '%s'; marking unfixable", title)
        try:
            path.unlink()
        except Exception:
            pass
        db.insert_repair_item(run_id, str(path), title, media_type, torrent_id, None,
                              "unfixable", "IMDB ID not found")
        return "unfixable"

    candidates = _fetch_candidates(imdb_id, title, media_type)
    if not candidates:
        log.warning("No replacement candidates for '%s' (%s); deleting strm", title, imdb_id)
        try:
            path.unlink()
        except Exception:
            pass
        db.insert_repair_item(run_id, str(path), title, media_type, torrent_id, None,
                              "unfixable", "no candidates found")
        return "unfixable"

    cached_hashes = torbox.check_cached([s.info_hash for s in candidates])
    cached = [s for s in candidates if s.info_hash in cached_hashes]
    to_try = cached or candidates[:1]

    winner: TorrentioStream | None = None
    for stream in to_try:
        try:
            torbox.add_magnet(stream.magnet)
            torbox.wait_until_ready(stream.info_hash)
            winner = stream
            break
        except Exception as exc:
            log.warning("Failed to add replacement for '%s' (hash=%s): %s", title, stream.info_hash, exc)

    if winner:
        try:
            path.unlink()
        except Exception:
            pass
        log.info("Repaired '%s': deleted strm, added new torrent %s", title, winner.info_hash)
        db.insert_repair_item(run_id, str(path), title, media_type, torrent_id,
                              winner.info_hash, "repaired", None)
        return "repaired"

    log.warning("All replacement candidates failed for '%s'; marking unfixable", title)
    try:
        path.unlink()
    except Exception:
        pass
    db.insert_repair_item(run_id, str(path), title, media_type, torrent_id, None,
                          "unfixable", "all replacement candidates failed")
    return "unfixable"


def _remove_duplicates(strm_files: list[Path], run_id: int) -> tuple[int, list[Path]]:
    """Group .strm files by normalized title/year/episode and remove duplicates.
    Returns (removed_count, remaining_paths)."""
    groups: dict[tuple, list[Path]] = {}
    for path in strm_files:
        try:
            rel = path.relative_to(MEDIA_PATH)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 2:
            continue
        kind = parts[0]
        if kind == "movies":
            title, year = _parse_folder_name(parts[1])
            key = ("movie", _normalize_title(title), year)
        elif kind == "series" and len(parts) >= 4:
            title = parts[1]
            m = _EP_FILENAME_RE.search(parts[3])
            if not m:
                continue
            key = ("episode", _normalize_title(title), int(m.group(1)), int(m.group(2)))
        else:
            continue
        groups.setdefault(key, []).append(path)

    removed = 0
    survivors: list[Path] = []
    for key, paths in groups.items():
        if len(paths) == 1:
            survivors.append(paths[0])
            continue
        # Keep the path with a year (more metadata) or longest folder name
        paths_sorted = sorted(paths, key=lambda p: (len(str(p)), str(p)), reverse=True)
        keeper = paths_sorted[0]
        survivors.append(keeper)
        for dup in paths_sorted[1:]:
            try:
                dup.unlink()
                log.info("Duplicate removed: %s (kept %s)", dup, keeper.name)
                try:
                    dup.parent.rmdir()
                except OSError:
                    pass
                db.insert_repair_item(
                    run_id, str(dup), keeper.parent.name, key[0], None, None,
                    "deleted", f"duplicate of {keeper.name}",
                )
                removed += 1
            except Exception as exc:
                log.warning("Could not remove duplicate %s: %s", dup, exc)
                survivors.append(dup)
    return removed, survivors


def _regenerate_wrong_files(strm_files: list[Path], mylist: list[dict], run_id: int) -> int:
    """For movies, detect .strm files pointing to non-main file (e.g. trailer) and regenerate."""
    import strm_generator

    mylist_by_id = {str(item.get("id")): item for item in mylist}
    regenerated = 0
    for path in strm_files:
        try:
            rel = path.relative_to(MEDIA_PATH)
        except ValueError:
            continue
        if not rel.parts or rel.parts[0] != "movies":
            continue
        try:
            url = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        torrent_id = _extract_torrent_id(url)
        file_id = _extract_file_id(url)
        if not torrent_id or not file_id:
            continue
        item = mylist_by_id.get(torrent_id)
        if not item:
            continue
        main = strm_generator._pick_main_movie_file(item.get("files") or [])
        if not main or str(main.get("id")) == file_id:
            continue
        # Current strm points to a wrong/smaller file (likely trailer) — regenerate
        log.info("Wrong file detected: %s (file_id=%s, should be %s) — regenerating",
                 path.name, file_id, main.get("id"))
        new_url = strm_generator._get_stream_url(int(torrent_id), main["id"])
        if not new_url:
            continue
        try:
            path.write_text(new_url, encoding="utf-8")
            db.insert_repair_item(
                run_id, str(path), path.parent.name, "movie", file_id,
                str(main.get("id")), "repaired", "regenerated wrong file (was trailer/sample)",
            )
            regenerated += 1
        except Exception as exc:
            log.warning("Could not rewrite %s: %s", path, exc)
    return regenerated


def run_cleanup() -> None:
    log.info("Cleanup: starting strm scan in %s", MEDIA_PATH)
    run_id = db.insert_cleanup_run()
    scanned = repaired = deleted = unfixable = 0

    strm_files = _collect_strm_files()
    scanned = len(strm_files)
    log.info("Cleanup: found %d .strm files", scanned)

    if not strm_files:
        db.update_cleanup_run(run_id, 0, 0, 0, 0)
        return

    try:
        mylist = torbox.list_torrents()
    except Exception as exc:
        log.error("Cleanup: could not fetch TorBox mylist: %s — aborting", exc)
        db.update_cleanup_run(run_id, scanned, 0, 0, 0)
        return

    # 1. Remove duplicate .strm files first (same title/episode in multiple folders)
    dup_removed, strm_files = _remove_duplicates(strm_files, run_id)
    if dup_removed:
        log.info("Cleanup: removed %d duplicate .strm file(s)", dup_removed)
    deleted += dup_removed

    # 2. Regenerate movie .strm files that point to a trailer/wrong file
    fixed_files = _regenerate_wrong_files(strm_files, mylist, run_id)
    if fixed_files:
        log.info("Cleanup: regenerated %d wrong .strm file(s)", fixed_files)
    repaired += fixed_files

    # 3. Repair broken .strm files (torrent no longer in TorBox mylist)
    changed = False
    for path in strm_files:
        result = _repair_strm(path, run_id, mylist)
        if result == "repaired":
            repaired += 1
            changed = True
        elif result == "deleted":
            deleted += 1
            changed = True
        elif result == "unfixable":
            unfixable += 1

    if dup_removed or fixed_files:
        changed = True

    db.update_cleanup_run(run_id, scanned, repaired, deleted, unfixable)
    log.info("Cleanup done: scanned=%d repaired=%d deleted=%d unfixable=%d",
             scanned, repaired, deleted, unfixable)

    if changed:
        strm_generator.run_and_refresh()

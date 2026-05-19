"""Library synchronisation between disk and DB.

orphans(): returns counts of inconsistencies — strm-without-DB and DB-without-strm.
import_existing(): walk the media folder and insert any .strm files that have no
corresponding media_items entry, so DB-loss recoveries can be self-healing.
"""
import logging
import re
from pathlib import Path

import db
from config import MEDIA_PATH

log = logging.getLogger(__name__)

_FOLDER_YEAR_RE = re.compile(r"\((\d{4})\)$")


def _strm_files() -> list[Path]:
    media = Path(MEDIA_PATH)
    if not media.is_dir():
        return []
    files: list[Path] = []
    for sub in ("movies", "series"):
        d = media / sub
        if d.is_dir():
            files.extend(d.rglob("*.strm"))
    return files


def orphans() -> dict:
    """Count strm files with no DB entry and DB entries with no strm file."""
    files = _strm_files()
    folder_names = {p.parent.name for p in files}

    media_items = db.get_media_items()
    db_titles = {m["title"] for m in media_items}

    strm_without_db = sum(1 for name in folder_names if name not in db_titles)
    db_without_strm = sum(1 for t in db_titles if t not in folder_names)

    return {
        "strm_count": len(files),
        "db_count": len(media_items),
        "strm_without_db": strm_without_db,
        "db_without_strm": db_without_strm,
    }


def import_existing() -> dict:
    """For each .strm file with no DB entry, insert a placeholder media_items row."""
    files = _strm_files()
    if not files:
        return {"scanned": 0, "imported": 0}

    existing_titles = {m["title"] for m in db.get_media_items()}
    imported = 0
    for path in files:
        # Folder name is the canonical title: "Title (Year)" or "Series Title".
        folder = path.parent.name
        # For series, walk one level up (path is series/Title/Season XX/file.strm)
        try:
            rel = path.relative_to(MEDIA_PATH)
            if rel.parts[0] == "series" and len(rel.parts) >= 4:
                folder = rel.parts[1]
        except ValueError:
            pass

        if folder in existing_titles:
            continue

        # Try to extract a fake imdb id from a strm URL if present, else use folder hash
        try:
            url = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        m = re.search(r"tt\d{6,10}", url)
        fake_imdb = m.group(0) if m else f"unknown_{abs(hash(folder)) % 10**8}"

        media_type = "series" if folder != path.parent.name else "movie"
        try:
            db.upsert_media_item(fake_imdb, folder, media_type)
            db.update_media_item_status(fake_imdb, media_type, "imported", strm_found=True)
            imported += 1
            existing_titles.add(folder)
        except Exception as exc:
            log.debug("Import skip %s: %s", folder, exc)

    log.info("Library import: scanned %d strm files, imported %d new items",
             len(files), imported)
    return {"scanned": len(files), "imported": imported}

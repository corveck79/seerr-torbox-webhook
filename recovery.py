"""Recovery wizard: one button that runs a battery of repair tasks and
reports a summary. Safe to run any time — every step is idempotent.
"""
import logging

import cleanup
import db
import library_sync
import strm_generator

log = logging.getLogger(__name__)


def run() -> dict:
    result: dict = {}

    # 1. DB health
    result["integrity_ok"] = db.integrity_check()

    # 2. Library orphan stats
    result["orphans_before"] = library_sync.orphans()

    # 3. Cleanup (broken strms + duplicates + wrong-file fixes)
    try:
        cleanup.run_cleanup()
        result["cleanup"] = "done"
    except Exception as exc:
        log.exception("Recovery: cleanup failed")
        result["cleanup"] = f"failed: {exc}"

    # 4. Library import (DB self-heal from disk)
    try:
        result["import"] = library_sync.import_existing()
    except Exception as exc:
        log.exception("Recovery: import failed")
        result["import"] = f"failed: {exc}"

    # 5. strm_generator pass (catch-up for anything new in TorBox)
    try:
        result["strm_new"] = strm_generator.run_once()
    except Exception as exc:
        log.exception("Recovery: strm scan failed")
        result["strm_new"] = f"failed: {exc}"

    # 6. Final orphan stats
    result["orphans_after"] = library_sync.orphans()

    # 7. Prune old volatile rows (90d retention)
    try:
        result["pruned"] = db.prune_old(90)
    except Exception as exc:
        result["pruned"] = f"failed: {exc}"

    db.log_activity("recovery", "Recovery wizard", "completed", success=True)
    return result

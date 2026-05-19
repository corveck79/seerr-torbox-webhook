"""Smart retry queue with exponential backoff.

Failed requests are enqueued for retry at increasing intervals
(RETRY_BACKOFF_MINUTES). A scheduler picks up due items every
RETRY_QUEUE_INTERVAL_MINUTES and re-runs processor.process for them.
"""
import logging
import threading

import db
from config import RETRY_BACKOFF_MINUTES
from webhook_parser import MediaRequest

log = logging.getLogger(__name__)


def schedule(req: MediaRequest, attempt: int) -> None:
    """Enqueue a failed request for retry at the next backoff interval."""
    if attempt >= len(RETRY_BACKOFF_MINUTES):
        log.info("Retry: giving up on %s after %d attempts", req.title, attempt)
        return
    delay = RETRY_BACKOFF_MINUTES[attempt] * 60
    db.enqueue_retry(req.imdb_id, req.title, req.media_type, req.seasons, attempt + 1, delay)
    log.info("Retry: queued %s for attempt %d in %dmin",
             req.title, attempt + 1, RETRY_BACKOFF_MINUTES[attempt])


def run_due() -> int:
    """Process all retries whose next_retry_at is now in the past."""
    import processor  # local import to avoid cycle
    due = db.get_due_retries()
    if not due:
        return 0
    log.info("Retry: processing %d due retries", len(due))
    try:
        import metrics_prom
        metrics_prom.retry_attempts_total.inc(len(due))
    except Exception:
        pass
    for row in due:
        seasons = [int(s) for s in (row.get("seasons") or "").split(",") if s.strip().isdigit()]
        req = MediaRequest(
            title=row["title"], media_type=row["media_type"],
            imdb_id=row["imdb_id"], seasons=seasons,
        )
        db.remove_retry(row["id"])
        threading.Thread(
            target=processor.process,
            args=(req,),
            kwargs={"_retry_attempt": row["attempt"]},
            name=f"retry-{row['imdb_id']}-{row['attempt']}",
            daemon=True,
        ).start()
    return len(due)

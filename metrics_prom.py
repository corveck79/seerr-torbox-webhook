"""Prometheus metrics for Mycelium.

All metrics live in the default registry under the `mycelium_` prefix.
Counters and histograms are incremented inline (processor / retry / etc).
Gauges that reflect current state (queue depth, library size, TorBox usage)
are refreshed on each /metrics scrape via refresh_gauges().

Single-worker gunicorn means no multiproc gymnastics needed.
"""
import logging

from prometheus_client import Counter, Gauge, Histogram

log = logging.getLogger(__name__)

# ── Counters (monotonically increasing) ───────────────────────────────────────
requests_total = Counter(
    "mycelium_requests_total",
    "Total processed media requests",
    ["media_type", "status"],
)
quality_added_total = Counter(
    "mycelium_quality_added_total",
    "Quality bucket of successfully added releases",
    ["quality"],
)
source_wins_total = Counter(
    "mycelium_source_wins_total",
    "Source provider that won candidate selection",
    ["source"],
)
blacklist_failures_total = Counter(
    "mycelium_blacklist_failures_total",
    "Hash add failures recorded",
)
catbox_stream_total = Counter(
    "mycelium_catbox_stream_total",
    "Catbox /stream/<token> resolutions",
    ["result"],  # ok | rematerialized | failed
)
retry_attempts_total = Counter(
    "mycelium_retry_attempts_total",
    "Requests picked up from the retry queue",
)

# ── Histograms ────────────────────────────────────────────────────────────────
request_duration_seconds = Histogram(
    "mycelium_request_duration_seconds",
    "End-to-end processor latency per request",
    ["media_type"],
    buckets=(1, 5, 10, 20, 30, 60, 120, 300, 600),
)

# ── Gauges (refreshed on scrape) ──────────────────────────────────────────────
torbox_torrent_count = Gauge(
    "mycelium_torbox_torrent_count",
    "Number of torrents currently in the TorBox mylist",
)
torbox_total_bytes = Gauge(
    "mycelium_torbox_total_bytes",
    "Total size of torrents in the TorBox mylist (bytes)",
)
library_strm_files = Gauge(
    "mycelium_library_strm_files",
    "Number of .strm files in the library",
    ["kind"],  # movies | series
)
catbox_virtual_items = Gauge(
    "mycelium_catbox_virtual_items",
    "Total Catbox virtual items",
)
catbox_active_in_torbox = Gauge(
    "mycelium_catbox_active_in_torbox",
    "Catbox items currently materialised in TorBox",
)
retry_queue_depth = Gauge(
    "mycelium_retry_queue_depth",
    "Pending retry queue entries",
)
blacklist_size = Gauge(
    "mycelium_blacklist_size",
    "Hashes currently above the blacklist threshold",
)
wanted_episodes = Gauge(
    "mycelium_wanted_episodes",
    "Wanted episodes by status",
    ["status"],
)
service_up = Gauge(
    "mycelium_service_up",
    "External service reachability (1=up, 0=down)",
    ["service"],
)
last_success_age_hours = Gauge(
    "mycelium_last_success_age_hours",
    "Hours since the last successful add (deadman-style)",
)


def refresh_gauges() -> None:
    """Update all gauges. Called by the /metrics endpoint on each scrape."""
    import db
    import settings
    from pathlib import Path
    from datetime import datetime

    # TorBox usage
    try:
        import torbox
        summary = torbox.get_usage_summary()
        torbox_torrent_count.set(summary["torrent_count"])
        torbox_total_bytes.set(summary["total_bytes"])
    except Exception as exc:
        log.debug("metrics: torbox usage failed: %s", exc)

    # Library .strm counts
    try:
        media = Path(settings.get("MEDIA_PATH", "/data/media"))
        for kind in ("movies", "series"):
            d = media / kind
            count = sum(1 for _ in d.rglob("*.strm")) if d.is_dir() else 0
            library_strm_files.labels(kind=kind).set(count)
    except Exception:
        pass

    # Catbox
    try:
        items = db.get_all_virtual_items()
        catbox_virtual_items.set(len(items))
        catbox_active_in_torbox.set(sum(1 for i in items if i.get("torbox_id")))
    except Exception:
        pass

    # Retry queue
    try:
        retry_queue_depth.set(len(db.get_pending_retries()))
    except Exception:
        pass

    # Blacklist
    try:
        threshold = settings.get("BLACKLIST_FAIL_THRESHOLD", 3)
        blacklist_size.set(len(db.get_blacklisted_hashes(threshold)))
    except Exception:
        pass

    # Wanted episodes by status
    try:
        wanted = db.get_all_wanted_episodes()
        by_status: dict[str, int] = {}
        for w in wanted:
            by_status[w.get("status") or "unknown"] = by_status.get(w.get("status") or "unknown", 0) + 1
        for status, count in by_status.items():
            wanted_episodes.labels(status=status).set(count)
    except Exception:
        pass

    # Service health
    try:
        import health_cache
        service_up.labels(service="zilean").set(1 if health_cache.is_up("zilean") else 0)
        service_up.labels(service="torrentio").set(1 if health_cache.is_up("torrentio") else 0)
    except Exception:
        pass

    # Last success age
    try:
        for ev in db.get_activity(50):
            if ev.get("success") and ev.get("event") in ("added", "upgraded"):
                ts = ev.get("created_at")
                if ts:
                    t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                    age = (datetime.utcnow() - t).total_seconds() / 3600
                    last_success_age_hours.set(age)
                    break
        else:
            last_success_age_hours.set(-1)
    except Exception:
        pass

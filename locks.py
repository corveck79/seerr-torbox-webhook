"""Concurrency primitives.

Per-imdb mutex so the same item never enters processor.process() twice
in parallel (de-dupes against a webhook retry firing while a manual
trigger is already running). Cheap and fully in-memory.
"""
import logging
import threading

log = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def _get(key: str) -> threading.Lock:
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


class imdb_mutex:
    """Context manager that yields True if acquired, False if already held."""
    def __init__(self, imdb_id: str, blocking: bool = False, timeout: float = 0.0):
        self.key = imdb_id
        self.blocking = blocking
        self.timeout = timeout
        self.lock = _get(imdb_id)
        self.held = False

    def __enter__(self) -> bool:
        if self.blocking and self.timeout > 0:
            self.held = self.lock.acquire(timeout=self.timeout)
        else:
            self.held = self.lock.acquire(blocking=self.blocking)
        if not self.held:
            log.warning("imdb mutex busy for %s — another worker holds it", self.key)
        return self.held

    def __exit__(self, *exc) -> None:
        if self.held:
            self.lock.release()

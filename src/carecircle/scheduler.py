"""Background loop: monitor -> dispatch, on a fixed interval."""

from __future__ import annotations

import logging
import threading

from .services import Services
from .services.dispatcher import DispatchReport

log = logging.getLogger("carecircle.scheduler")


class Scheduler:
    def __init__(self, services: Services, interval_seconds: float | None = None) -> None:
        self._s = services
        self._interval = float(interval_seconds or services.settings.tick_seconds)
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def tick(self) -> DispatchReport:
        """One idempotent pass. Safe to call manually (the demo UI does)."""
        with self._lock:
            return self._s.dispatcher.dispatch(self._s.monitor.run())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._halt.clear()
        self._thread = threading.Thread(target=self._loop, name="carecircle-scheduler", daemon=True)
        self._thread.start()
        log.info("Scheduler started (every %.0fs)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Scheduler tick failed")
            self._halt.wait(self._interval)

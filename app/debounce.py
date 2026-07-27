from __future__ import annotations

import threading


class Debounce:
    """Coalesce a burst of calls into a single delayed one.

    The timer handle is guarded by a lock, but the callback always runs
    *outside* it: firing under the lock deadlocked the immediate path
    (schedule → cancel → fire → re-acquire the same non-reentrant lock),
    which froze the window-close handler and left the app unable to exit.

    Lives in its own flet-free module so the no-deadlock guarantee stays
    testable on a headless machine.
    """

    def __init__(self, delay: float, fn):
        self.delay = delay
        self.fn = fn
        self._lock = threading.Lock()
        self._handle = None

    def _fire(self):
        with self._lock:
            self._handle = None
        self.fn()

    def schedule(self, immediate: bool = False) -> None:
        """Run fn after `delay`, restarting the countdown on every call.

        With immediate=True the pending call is cancelled and fn runs now.
        """
        with self._lock:
            if self._handle is not None:
                self._handle.cancel()
                self._handle = None
            if not immediate:
                timer = threading.Timer(self.delay, self._fire)
                timer.daemon = True
                self._handle = timer
                timer.start()
        if immediate:
            self._fire()

    def cancel(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.cancel()
                self._handle = None

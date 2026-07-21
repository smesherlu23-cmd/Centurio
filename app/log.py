"""Centurio logging.

Quiet by default (nothing is written). Pass ``--debug`` on the command line or
set ``CENTURIO_DEBUG=1`` to turn on a rotating log file next to the data file
(``centurio.log``) plus echo to stderr — so a user can reproduce an issue and
send the log instead of the errors being silently swallowed.

Everything here is best-effort: if the log file can't be opened, logging simply
stays off and the app keeps running.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER = logging.getLogger("centurio")
_LOGGER.addHandler(logging.NullHandler())
_configured = False


def is_debug() -> bool:
    return "--debug" in sys.argv or os.environ.get("CENTURIO_DEBUG") == "1"


def _default_dir() -> Path:
    from .store import default_data_path
    return default_data_path().parent


def setup(debug: bool | None = None, log_dir: str | Path | None = None) -> logging.Logger:
    """Configure logging once. Safe to call more than once (later calls no-op)."""
    global _configured
    if _configured:
        return _LOGGER
    if debug is None:
        debug = is_debug()

    _LOGGER.setLevel(logging.DEBUG if debug else logging.WARNING)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if debug:
        try:
            d = Path(log_dir) if log_dir else _default_dir()
            d.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(d / "centurio.log", maxBytes=512 * 1024,
                                     backupCount=3, encoding="utf-8")
            fh.setFormatter(fmt)
            _LOGGER.addHandler(fh)
        except Exception:
            pass
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        _LOGGER.addHandler(sh)
        _LOGGER.debug("logging started (log dir: %s)", log_dir or "<default>")

    _configured = True
    return _LOGGER


# Module-level convenience wrappers so call sites read `from . import log;
# log.exception(...)` without grabbing the logger object.
def debug(msg, *args, **kw):
    _LOGGER.debug(msg, *args, **kw)


def info(msg, *args, **kw):
    _LOGGER.info(msg, *args, **kw)


def warning(msg, *args, **kw):
    _LOGGER.warning(msg, *args, **kw)


def error(msg, *args, **kw):
    _LOGGER.error(msg, *args, **kw)


def exception(msg, *args, **kw):
    """Log an exception with traceback — use inside an `except` block instead of
    swallowing the error with `pass`."""
    _LOGGER.exception(msg, *args, **kw)

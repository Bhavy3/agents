from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.logging.formatters import JsonFormatter, CompactConsoleFormatter

_CONFIGURED = False


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that tolerates Windows/OneDrive file locks.

    On Windows, OneDrive (and antivirus) can hold open file handles that
    prevent ``os.rename()`` during log rollover.  Python's logging framework
    catches the resulting ``PermissionError`` *twice*: once inside
    ``doRollover`` and once in ``emit → handleError``, printing a full
    traceback to stderr each time.  We suppress both paths here.
    """

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            pass

    def handleError(self, record: logging.LogRecord) -> None:
        """Suppress PermissionError stderr noise from log rotation."""
        t = sys.exc_info()[1]
        if isinstance(t, PermissionError):
            return  # Silently swallow rotation-related PermissionErrors
        super().handleError(record)


def configure_logging(
    log_dir: Path,
    level: int | str = logging.INFO,
    json_logging: bool = True,
    console_level: int | str = logging.WARNING,
) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    root.setLevel(level)
    root.handlers.clear()

    json_formatter = JsonFormatter()
    console_handler = logging.StreamHandler()
    if isinstance(console_level, str):
        console_level = logging.getLevelName(console_level.upper())
    console_handler.setLevel(console_level)
    console_handler.setFormatter(CompactConsoleFormatter())

    file_handler = SafeRotatingFileHandler(
        log_dir / "friday.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)

    error_handler = SafeRotatingFileHandler(
        log_dir / "friday-errors.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    root.addHandler(console_handler)
    if json_logging:
        root.addHandler(file_handler)
        root.addHandler(error_handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"friday.{name}")


def shutdown_logging() -> None:
    global _CONFIGURED
    logging.shutdown()
    _CONFIGURED = False

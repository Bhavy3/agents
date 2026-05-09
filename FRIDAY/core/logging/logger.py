from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.logging.formatters import JsonFormatter, CompactConsoleFormatter

_CONFIGURED = False


def configure_logging(log_dir: Path, level: int | str = logging.INFO, json_logging: bool = True) -> None:
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
    console_handler.setFormatter(CompactConsoleFormatter())

    file_handler = RotatingFileHandler(
        log_dir / "friday.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)

    error_handler = RotatingFileHandler(
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

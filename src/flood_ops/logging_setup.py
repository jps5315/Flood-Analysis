from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_dir: Path, run_id: str, arcpy_messages=None) -> logging.Logger:
    """File + console logging. Optionally mirrors INFO+ to ArcPy tool messages."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flood_ops")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_dir / f"{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if arcpy_messages is not None:
        logger.addHandler(_ArcPyHandler(arcpy_messages, formatter))

    logger.propagate = False
    return logger


class _ArcPyHandler(logging.Handler):
    def __init__(self, messages, formatter: logging.Formatter):
        super().__init__(level=logging.INFO)
        self.messages = messages
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        text = self.format(record)
        try:
            if record.levelno >= logging.ERROR:
                self.messages.addErrorMessage(text)
            elif record.levelno >= logging.WARNING:
                self.messages.addWarningMessage(text)
            else:
                self.messages.addMessage(text)
        except Exception:
            pass

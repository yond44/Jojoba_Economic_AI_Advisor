"""
Logger — stdout-first, file logging opt-in and rotated.

Default: log ONLY to stdout. In Docker that's the right sink — the daemon
captures it (`docker logs`, `docker compose logs`) and rotation is handled by
the logging driver, so the container's disk never fills with .log files.

Set LOG_TO_FILE=true to also write logs/app.log, capped by rotation
(LOG_FILE_MAX_MB per file × LOG_FILE_BACKUPS files, ~15 MB worst case by
default) so it can never grow unbounded like the old plain FileHandler.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_level: str = "INFO"):
    """Configure root logging: stdout always; rotated file only if opted in."""
    handlers = [logging.StreamHandler(sys.stdout)]

    if os.getenv("LOG_TO_FILE", "false").lower() in ("1", "true", "yes"):
        Path("logs").mkdir(exist_ok=True)
        max_mb = int(os.getenv("LOG_FILE_MAX_MB", "5"))
        backups = int(os.getenv("LOG_FILE_BACKUPS", "2"))
        handlers.append(
            RotatingFileHandler(
                "logs/app.log",
                maxBytes=max_mb * 1024 * 1024,
                backupCount=backups,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("llama_index").setLevel(logging.WARNING)

    return logging.getLogger(__name__)

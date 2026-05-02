import logging
import logging.config
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO", retention_days: int = 30) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "detailed": {
                "format": "%(asctime)s | %(levelname)-7s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "app_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_dir / "app.log"),
                "when": "midnight",
                "backupCount": retention_days,
                "encoding": "utf-8",
                "formatter": "standard",
            },
            "error_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_dir / "error.log"),
                "when": "midnight",
                "backupCount": retention_days * 2,
                "encoding": "utf-8",
                "level": "ERROR",
                "formatter": "detailed",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "app_file", "error_file"],
        },
        "loggers": {
            # suppress uvicorn access log — RequestLoggerMiddleware already covers HTTP logging
            "uvicorn.access": {"level": "WARNING", "propagate": True},
        },
    }
    logging.config.dictConfig(config)

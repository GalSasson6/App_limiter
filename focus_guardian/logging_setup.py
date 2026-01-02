import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR, LOG_FILE
from .utils import ensure_dir


def setup_logger() -> logging.Logger:
    ensure_dir(LOG_DIR)
    logger = logging.getLogger("FocusGuardian")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    return logger

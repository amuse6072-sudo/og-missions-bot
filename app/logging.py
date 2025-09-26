from __future__ import annotations
import os
from loguru import logger


def setup_logging() -> None:
    """
    Универсальная настройка логгера (loguru).
    Уровень настраивается через LOG_LEVEL (INFO/DEBUG/WARNING/ERROR).
    """
    level = os.getenv("LOG_LEVEL", "INFO")
    # Чистим дефолтные хендлеры, чтобы не плодить дубликаты при повторных стартах
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=level,
        backtrace=True,
        diagnose=False,
        colorize=True,
        enqueue=False,
    )


def get_logger():
    return logger

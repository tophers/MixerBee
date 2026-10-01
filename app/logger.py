"""
app/logger.py - Centralized logging utility
"""

import logging
import sys

_loggers = []

def get_logger(name: str) -> logging.Logger:
    """Retrieves or creates a logger configured to bypass Uvicorn swallowing."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(levelname)s: [%(name)s] %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.propagate = False
        _loggers.append(logger)

    # A subsystem logger created after startup -- the first time its module is imported
    # mid-request, for instance -- must still reach the live log viewer. Imported here
    # rather than at module scope: log_buffer reads registered_loggers() from this module.
    from app.log_buffer import capture
    capture.attach(logger)

    refresh_logger_level(logger)
    return logger

def registered_loggers():
    """Every named logger this factory has created, for handler attachment."""
    return tuple(_loggers)

def refresh_logger_level(target_logger: logging.Logger = None):
    """Updates the logging level based on the global VERBOSE_LOGGING toggle."""
    import app_state

    level = logging.INFO if getattr(app_state, "VERBOSE_LOGGING", False) else logging.WARNING

    if target_logger:
        target_logger.setLevel(level)
    else:
        for l in _loggers:
            l.setLevel(level)

        logging.getLogger('apscheduler').setLevel(level)

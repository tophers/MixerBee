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
    
    refresh_logger_level(logger)
    return logger

def refresh_logger_level(target_logger: logging.Logger = None):
    """Updates the logging level based on the global VERBOSE_LOGGING toggle."""
    import app_state
    
    level = logging.INFO if app_state.VERBOSE_LOGGING else logging.WARNING
    
    if target_logger:
        target_logger.setLevel(level)
    else:
        for l in _loggers:
            l.setLevel(level)
            
        logging.getLogger('apscheduler').setLevel(level)
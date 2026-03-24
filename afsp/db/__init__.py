"""Database module for AFSP."""

import json
import logging

logger = logging.getLogger("afsp")


def safe_json_loads(raw: str | None, default=None):
    """Parse JSON from a database column, returning default on failure."""
    if raw is None:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt JSON in database: %r", raw)
        return default if default is not None else []

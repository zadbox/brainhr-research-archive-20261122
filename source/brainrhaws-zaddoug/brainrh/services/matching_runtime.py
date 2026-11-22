"""
Lazy runtime for the matching engine.

The matching engine loads heavy dependencies and embedding models. Keep that
initialization out of FastAPI module import so the backend can start cleanly.
"""

from functools import lru_cache
from typing import Any, Dict


def _load_matching_config() -> Dict[str, Any]:
    try:
        from config_loader import get_config

        config = get_config()
        return getattr(config, "_config", {}) or {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_matching_engine():
    from matching_engine import MatchingEngine

    return MatchingEngine(_load_matching_config())


def reset_matching_engine() -> None:
    get_matching_engine.cache_clear()

"""Contract constants: version and visibility levels."""

from __future__ import annotations

CONTRACT_VERSION = 1

# Ordered from least to most: what a hub may read
LEVELS = ("health", "statistics", "full")

# Minimum level per admin section
SECTION_LEVEL = {"overview": "health", "usage": "statistics", "audit": "full", "users": "full"}


def allows(level: str, needed: str) -> bool:
    """True when `level` is at least `needed`. Unknown levels allow nothing."""
    if level not in LEVELS or needed not in LEVELS:
        return False
    return LEVELS.index(level) >= LEVELS.index(needed)

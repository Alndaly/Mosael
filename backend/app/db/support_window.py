"""The rolling support window for persisted-data upgrades.

The oldest supported Release is exactly eight stable Release versions behind the version
being released. This is the only source of truth used by the release-time check; the
fixture and schema baseline must be regenerated from `OLDEST_SUPPORTED_RELEASE` when this
moves.
"""

from __future__ import annotations

OLDEST_SUPPORTED_RELEASE = "v2.0.0"
MAX_RELEASES_BEHIND = 8

__all__ = ["MAX_RELEASES_BEHIND", "OLDEST_SUPPORTED_RELEASE"]

"""Shared secret between the backend and the local publish worker.

The worker is an Electron process with no user session, so its channel was left unauthenticated
on the reasoning that the backend only listens on 127.0.0.1. That is not a boundary a browser
respects: any page the user happens to be visiting can POST to 127.0.0.1:8800, and those routes
required no credential at all — so a web page could claim publish tasks across every workspace,
read account proxy strings with credentials in them, and mark accounts as needing re-login.

Narrowing CORS stopped such a page READING the reply, but a simple cross-origin POST still
reaches the handler, so the side effects remained. What actually distinguishes the worker from a
web page is that the worker can read the local filesystem. So: mint a secret at startup, write
it to the data directory with owner-only permissions, and require it on every worker request. A
page cannot read the file, and therefore cannot forge the header.

Regenerated per process. A worker that outlives a backend restart re-reads the file, and a
stale secret fails closed rather than silently continuing to work.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Header the worker sends it in. Custom (not Authorization) so it can never be confused with a
#: user session — and, usefully, a custom header forces a CORS preflight, which a cross-origin
#: page then fails.
WORKER_KEY_HEADER = "X-Mibu-Worker-Key"

_KEY_FILENAME = "publish-worker.key"
_key: str | None = None


def key_path():
    return settings.data_dir / _KEY_FILENAME


def issue_worker_key() -> str:
    """Mint this process's key and write it where only the local user can read it."""
    global _key
    _key = secrets.token_hex(32)
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then chmod, and open with 0600 from the start — writing world-readable and
    # tightening afterwards leaves a window where any local process can read it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as handle:
        handle.write(_key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # in case the file already existed
    except OSError:
        logger.warning("could not tighten permissions on %s", path)
    return _key


def current_worker_key() -> str | None:
    return _key


def verify_worker_key(candidate: str | None) -> bool:
    if not _key or not candidate:
        return False
    return secrets.compare_digest(candidate, _key)

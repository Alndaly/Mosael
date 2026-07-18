"""Workspace role ladder + permission model (ported from mibu-video's core/workspaces.py).

A member has one **role** (owner > admin > editor > viewer). Each role grants a default
set of **perms**; an admin can additionally set per-member overrides (WorkspaceMemberPerm)
that flip a single perm on/off. Owner always has every perm — overrides can't lock the
last owner out. Enforcement lives in app/core/permissions.py; this module is pure logic
(no DB, no FastAPI) so it's trivially unit-testable.
"""
from __future__ import annotations

ROLES = ("owner", "admin", "editor", "viewer")
_RANK = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}

# Every capability the UI/permission-gate can check. Keep in sync with the frontend's
# perm labels. New perms slot in here without a migration (overrides are relational).
PERMS = ("upload", "edit", "delete", "export", "ai", "credentials", "schedule", "members", "publish")

# Role → default perm set. Editor gets everything except member management; viewer is
# read-only; owner/admin get everything (admin can be trimmed per-member via overrides).
_ROLE_DEFAULTS: dict[str, dict[str, bool]] = {
    "owner": {perm: True for perm in PERMS},
    "admin": {perm: True for perm in PERMS},
    "editor": {perm: perm != "members" for perm in PERMS},
    "viewer": {perm: False for perm in PERMS},
}


def role_rank(role: str) -> int:
    return _RANK.get(role, -1)


def role_at_least(role: str, minimum: str) -> bool:
    return role_rank(role) >= role_rank(minimum)


def role_defaults(role: str) -> dict[str, bool]:
    return dict(_ROLE_DEFAULTS.get(role, _ROLE_DEFAULTS["viewer"]))


def effective_perms(role: str, overrides: dict[str, bool] | None = None) -> dict[str, bool]:
    """Role defaults merged with per-member overrides. Owner ignores overrides (always
    full) so the last owner can never be locked out of their own workspace."""
    if role == "owner":
        return {perm: True for perm in PERMS}
    perms = role_defaults(role)
    for perm, allowed in (overrides or {}).items():
        if perm in perms:
            perms[perm] = allowed
    return perms


def has_perm(role: str, overrides: dict[str, bool] | None, perm: str) -> bool:
    return effective_perms(role, overrides).get(perm, False)

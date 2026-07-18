from __future__ import annotations

from app.core.roles import PERMS, effective_perms, has_perm, role_at_least, role_rank


def test_role_ladder() -> None:
    assert role_rank("owner") > role_rank("admin") > role_rank("editor") > role_rank("viewer")
    assert role_at_least("admin", "editor")
    assert role_at_least("editor", "editor")
    assert not role_at_least("editor", "admin")
    assert role_rank("bogus") == -1


def test_role_defaults() -> None:
    owner = effective_perms("owner")
    assert all(owner.values())  # owner can do everything
    editor = effective_perms("editor")
    assert editor["edit"] and editor["upload"] and not editor["members"]  # editor: all but members
    viewer = effective_perms("viewer")
    assert not any(viewer.values())  # viewer: read-only


def test_overrides_flip_a_single_perm() -> None:
    # Grant a viewer just `edit`; everything else stays denied.
    perms = effective_perms("viewer", {"edit": True})
    assert perms["edit"] and not perms["delete"]
    # Revoke `credentials` from an editor.
    perms = effective_perms("editor", {"credentials": False})
    assert not perms["credentials"] and perms["edit"]


def test_owner_ignores_overrides() -> None:
    # An override must never lock the last owner out.
    perms = effective_perms("owner", {"members": False, "edit": False})
    assert perms["members"] and perms["edit"]


def test_has_perm_matches_effective() -> None:
    assert has_perm("editor", None, "edit")
    assert not has_perm("editor", None, "members")
    assert has_perm("editor", {"members": True}, "members")
    assert set(effective_perms("admin").keys()) == set(PERMS)

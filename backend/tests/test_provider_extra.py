"""Adapter-specific provider configuration beyond a single api_key shape.

火山 is the reason: its speech v3 API Key, the podcast appid + access token, and the account
AK/SK for listing voices are three unrelated credentials from three different consoles. They
are exposed through backend-declared field specs, and the rules about what leaves the server
and what a blank field means are the whole risk surface — get them wrong and a working config disappears
on an unrelated save.
"""

from __future__ import annotations

from tests.util import fresh_client


def _admin_client():
    """Provider profiles are instance settings, gated on owning a workspace somewhere."""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _create(client, vendor: str, extra: dict) -> dict:
    config = {"api_key": "sk-abcd1234", **extra}
    res = client.post(
        "/api/settings/providers",
        json={"name": "t", "vendor": vendor, "config": config},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_a_secret_extra_never_leaves_the_server_in_full() -> None:
    """Same rule as api_key: the browser gets a hint, not the credential."""
    client = _admin_client()
    out = _create(client, "volcano", {"ak": "AKLTsecret", "sk": "SKsupersecret"})
    assert out["extra"]["ak"] == "…cret"
    assert "AKLTsecret" not in str(out)
    assert "SKsupersecret" not in str(out)


def _my_secrets(db, profile_id: str) -> dict:
    """当前这个部署里那个人在这条连接上的密字段。"""
    from app.db.models import ProviderCredential, User

    me = db.query(User).order_by(User.created_at).first()
    row = db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": me.id})
    return dict(row.secrets or {}) if row is not None else {}


def test_a_non_secret_extra_comes_back_verbatim() -> None:
    """An App ID is an identifier, and the form has to show it back to be editable."""
    client = _admin_client()
    out = _create(client, "volcano-podcast", {"appid": "1234567890"})
    assert out["extra"]["appid"] == "1234567890"


def test_saving_the_form_without_a_secret_keeps_the_stored_one() -> None:
    """The browser was never given the AK, so a blank AK on save means "unchanged". Treating
    it as "clear" would destroy a working credential on any unrelated edit."""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = _admin_client()
    created = _create(client, "volcano", {"ak": "AKLTsecret", "sk": "SKsupersecret"})

    res = client.patch(
        f"/api/settings/providers/{created['id']}",
        json={"name": "renamed", "config": {"ak": "", "sk": ""}},
    )
    assert res.status_code == 200, res.text

    with SessionLocal() as db:
        stored = db.get(ProviderProfile, created["id"])
        assert stored.name == "renamed"
        # 密的附加字段跟着**钥匙**走(见 domain/provider_credentials);「空 = 不变」这条规则
        # 没变,变的只是它存在哪。
        assert _my_secrets(db, created["id"]) == {"ak": "AKLTsecret", "sk": "SKsupersecret"}


def test_blanking_a_required_visible_field_is_rejected() -> None:
    """The user can see the App ID, but podcast cannot run without it."""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = _admin_client()
    created = _create(client, "volcano-podcast", {"appid": "1234567890"})
    res = client.patch(f"/api/settings/providers/{created['id']}", json={"config": {"appid": ""}})
    assert res.status_code == 422

    with SessionLocal() as db:
        assert db.get(ProviderProfile, created["id"]).extra == {"appid": "1234567890"}


def test_an_untouched_extra_survives_an_unrelated_patch() -> None:
    """A patch that does not mention extra at all must not replace it with {}."""
    from app.core.db import SessionLocal

    client = _admin_client()
    created = _create(client, "volcano", {"ak": "AKLTsecret"})
    client.patch(f"/api/settings/providers/{created['id']}", json={"enabled": False})

    with SessionLocal() as db:
        assert _my_secrets(db, created["id"]) == {"ak": "AKLTsecret"}


def test_the_form_spec_is_served_with_the_vendor() -> None:
    """The settings form renders from this, so adding a vendor stays one dict entry."""
    client = _admin_client()
    vendors = {item["vendor"]: item for item in client.get("/api/settings/provider-vendors").json()}

    assert [f["key"] for f in vendors["volcano"]["fields"]] == ["api_key", "ak", "sk"]
    assert all(f["secret"] for f in vendors["volcano"]["fields"])
    podcast = vendors["volcano-podcast"]["fields"]
    assert [f["key"] for f in podcast] == ["api_key", "appid"]
    assert podcast[0]["label"] == "Access Token"
    assert podcast[0]["secret"] is True
    assert podcast[1]["secret"] is False
    # Every vendor answers with the exact adapter fields the settings form should render.
    assert [f["storage"] for f in vendors["openai"]["fields"]] == ["api_key", "base_url", "default_model"]


def test_resolved_connection_contains_visible_options() -> None:
    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain.providers import resolve_connection

    client = _admin_client()
    _create(client, "volcano-podcast", {"appid": "1234567890"})
    with SessionLocal() as db:
        user_id = db.query(User.id).order_by(User.created_at).scalar()
        resolved = resolve_connection(db, "volcano-podcast", user_id=user_id)
        assert resolved is not None
        assert resolved.extra["appid"] == "1234567890"
        assert resolve_connection(db, "no-such-vendor", user_id=user_id) is None

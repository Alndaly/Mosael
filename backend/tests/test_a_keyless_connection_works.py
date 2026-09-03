"""有的供应商本来就不需要钥匙 —— 别逼人编一个。

ComfyUI 跑在本机(或局域网那台 GPU 机器)上,预设里写得清清楚楚"免密钥",字段里也确实没有
api_key。但整条钥匙链的判据是「有没有一份带秘密的凭据」:

    pick() 要求 _has_secret(...)  →  没有就 None
    resolve() 拿不到凭据          →  返回 None
    调用方                        →  「请先配置」

于是这条连接**根本用不了**:界面上一行红字「未配置你的密钥」,而它压根没有密钥可配。用户唯一
的出路是随便敲几个字符骗过 `_has_secret` —— 那既不是配置,也不是安全,只是一道过不去的门。

判据本身没错(空凭据不算配过),错在它对所有 vendor 一视同仁。**"要不要钥匙"是 vendor 的属性**,
由预设声明,而不是从"有没有填"反推。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from app.domain import provider_credentials
from app.domain.provider_presets import provider_definition
from tests.util import fresh_client


def _comfy(client) -> str:
    created = client.post(
        "/api/settings/providers",
        json={"name": "ComfyUI", "vendor": "comfyui", "config": {"base_url": "http://127.0.0.1:8188"}},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_the_preset_says_it_needs_no_key() -> None:
    """免密钥是 vendor 的属性,写在预设里 —— 不是从"用户填没填"猜出来的。"""
    comfyui = provider_definition("comfyui")
    assert comfyui is not None
    assert comfyui.keyless is True


def test_it_resolves_without_any_credential() -> None:
    """没有凭据行也要解析得出来,否则这条连接一次都用不了。"""
    client = fresh_client()
    profile_id = _comfy(client)

    with SessionLocal() as db:
        user_id = db.execute(__import__("sqlalchemy").text("SELECT id FROM users LIMIT 1")).scalar_one()
        resolved = provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), user_id)

    assert resolved is not None, "免密钥的连接被当成「没配钥匙」挡下了"
    assert resolved.base_url == "http://127.0.0.1:8188"
    assert resolved.api_key == ""


def test_the_ui_is_not_told_to_ask_for_a_key() -> None:
    """界面据此决定要不要显示那行红字 —— 判据由后端给,前端不该按 vendor 名字硬编。"""
    client = fresh_client()
    _comfy(client)

    row = next(item for item in client.get("/api/settings/providers").json() if item["vendor"] == "comfyui")

    assert row["needs_key"] is False


def test_a_normal_vendor_still_needs_one() -> None:
    """这不是把闸放开:要钥匙的照旧要,没有就解析不出来。"""
    client = fresh_client()
    created = client.post(
        "/api/settings/providers",
        json={
            "name": "某端点",
            "vendor": "openai-compatible",
            "config": {"base_url": "https://x.example/v1", "default_model": "m", "api_key": "k"},
        },
    )
    profile_id = created.json()["id"]
    row = next(item for item in client.get("/api/settings/providers").json() if item["id"] == profile_id)
    assert row["needs_key"] is True

    client.delete(f"/api/settings/providers/{profile_id}/credential")
    with SessionLocal() as db:
        user_id = db.execute(__import__("sqlalchemy").text("SELECT id FROM users LIMIT 1")).scalar_one()
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), user_id) is None


def test_someone_elses_keyless_connection_is_still_not_mine() -> None:
    """免密钥不等于免归属:它仍然是**他的**连接,别人看不到,也别想拿它去跑。"""
    from tests.util import second_client

    client = fresh_client()
    profile_id = _comfy(client)
    mate = second_client("mate")

    assert mate.get("/api/settings/providers").json() == []
    assert mate.get(f"/api/settings/providers/{profile_id}/models").status_code == 404
    with SessionLocal() as db:
        from app.db.models import User

        mate_id = db.query(User).filter(User.username == "mate").one().id
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), mate_id) is None

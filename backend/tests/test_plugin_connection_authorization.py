"""连接的授权状态:没授权过 / 授权过 / 需要重新授权。

插件页上「去授权」是连接级别的动作,连接卡片上就该看得出这个连接授权到哪一步。后端能在**不碰令牌本身**
的前提下知道两件事:

· 授权会写的那几格(清单 `oauth.stores` 指向的)**填没填** —— 分出「没授权过」和「授权过」;
· 插件上一次调用时**说了对方不再接受已存的令牌**(失败响应里的 `reauthorize: true`)—— 格子非空不等于
  令牌还有效,而这一点只有真去调过一次的插件知道。

这里钉的是:状态按这两件事算对了;「被拒」由插件明说才记(别的失败不算),换了令牌或一次调用成功就清掉;
没声明 oauth 的插件不谈授权;界面拿得到「哪几格由授权填」,好把它们收进「手动填写」。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.core.i18n import tr
from app.db.models import PluginInstance, PluginPackage, User
from app.domain.plugins import instances as inst
from app.domain.plugins.manifest import Field, OAuthSpec
from app.domain.plugins.oauth import AUTHORIZED, REJECTED, UNAUTHORIZED, authorization_state, fills
from app.domain.plugins.runtime import PluginRuntimeError, _final_response
from app.domain.plugins.tools import invoke
from tests.util import fresh_client

SPEC = OAuthSpec(
    authorize_url="https://x.test/authorize",
    token_url="https://x.test/token",
    client_id_field="APP_KEY",
    client_secret_field="SECRET_KEY",
    stores={"refresh_token": "REFRESH_TOKEN", "access_token": "ACCESS_TOKEN"},
)
CREDENTIALS = [
    Field(key="APP_KEY", label="AppKey", required=True),
    Field(key="SECRET_KEY", label="SecretKey", required=True),
    Field(key="REFRESH_TOKEN", label="Refresh Token", required=True),
    Field(key="ACCESS_TOKEN", label="Access Token", required=False),
]


class Test状态怎么算:
    def test_授权会写的格子按清单先后列出来(self) -> None:
        assert [one.key for one in fills(SPEC, CREDENTIALS)] == ["REFRESH_TOKEN", "ACCESS_TOKEN"]

    def test_必填的令牌空着就是没授权(self) -> None:
        # AppKey 填了不算:那是注册应用拿的,授权还没走。
        assert authorization_state(SPEC, CREDENTIALS, {"APP_KEY", "SECRET_KEY"}, rejected=False) == UNAUTHORIZED
        # 只有可以空着的 Access Token 也不算:插件要的是 Refresh Token。
        assert authorization_state(SPEC, CREDENTIALS, {"ACCESS_TOKEN"}, rejected=False) == UNAUTHORIZED

    def test_必填的令牌填了就是授权过(self) -> None:
        assert authorization_state(SPEC, CREDENTIALS, {"REFRESH_TOKEN"}, rejected=False) == AUTHORIZED

    def test_填着但插件说对方不认了(self) -> None:
        assert authorization_state(SPEC, CREDENTIALS, {"REFRESH_TOKEN"}, rejected=True) == REJECTED

    def test_格子空着时不说被拒_先得授权(self) -> None:
        assert authorization_state(SPEC, CREDENTIALS, set(), rejected=True) == UNAUTHORIZED

    def test_授权写的格子一个都不必填时填了任意一格就算(self) -> None:
        optional = [Field(key=one.key, label=one.label, required=False) for one in CREDENTIALS]
        assert authorization_state(SPEC, optional, set(), rejected=False) == UNAUTHORIZED
        assert authorization_state(SPEC, optional, {"ACCESS_TOKEN"}, rejected=False) == AUTHORIZED


class Test插件怎么说被拒:
    def test_失败响应里的_reauthorize_true(self) -> None:
        with pytest.raises(PluginRuntimeError) as error:
            _final_response({"ok": False, "error": "refresh_token 已作废", "reauthorize": True})
        assert error.value.reauthorize is True

    @pytest.mark.parametrize("value", [None, False, "true", 1])
    def test_只认字面的_true(self, value) -> None:
        """一个随手写成 "true" 字符串的插件不该把连接标成要重新授权 —— 那会让人去重走一遍授权,而问题不在那儿。"""
        response = {"ok": False, "error": "x"}
        if value is not None:
            response["reauthorize"] = value
        with pytest.raises(PluginRuntimeError) as error:
            _final_response(response)
        assert error.value.reauthorize is False


MANIFEST = {
    "id": "auth-demo",
    "name": "授权演示",
    "version": "0.1.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {
        "credentials": [
            {"key": "APP_KEY", "label": "AppKey", "required": True},
            {"key": "REFRESH_TOKEN", "label": "Refresh Token", "required": True},
            {"key": "ACCESS_TOKEN", "label": "Access Token", "required": False},
        ],
        "oauth": {
            "authorize_url": "https://x.test/authorize",
            "token_url": "https://x.test/token",
            "client_id_field": "APP_KEY",
            "stores": {"refresh_token": "REFRESH_TOKEN", "access_token": "ACCESS_TOKEN"},
        },
    },
    "tools": {"expose": "all", "declare": [{"name": "go", "description": "跑一下"}]},
}

#: 令牌是 "revoked" 时说对方不认了;是 "missing-file" 时报一个与令牌无关的失败;别的都成功。
PLUGIN = """
    import json, os, sys
    sys.stdin.read()
    token = os.environ.get("REFRESH_TOKEN", "")
    if token == "revoked":
        print(json.dumps({"ok": False, "error": "对方不认这个令牌了", "reauthorize": True}))
    elif token == "missing-file":
        print(json.dumps({"ok": False, "error": "文件不存在"}))
    else:
        print(json.dumps({"ok": True, "output": {"done": True}}))
"""


#: 最近一次 install 登录的那个客户端(查接口用)。
CLIENT: list = [None]


def install(tmp_path: Path, manifest: dict = MANIFEST) -> tuple[str, str]:
    """装一个插件并给测试账号接一次,返回 (workspace_id, instance_id)。"""
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(PLUGIN), encoding="utf-8")
    client = fresh_client()
    CLIENT[0] = client
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        package = PluginPackage(
            id=manifest["id"], name=manifest["name"], version="0.1.0", manifest={**manifest, "_path": str(plugin_dir)}
        )
        db.add(package)
        db.flush()
        instance = PluginInstance(package_id=package.id, name=manifest["name"], enabled=True, owner_user_id=me.id)
        db.add(instance)
        db.commit()
        return ws, instance.id


def state_of(instance_id: str) -> str:
    with SessionLocal() as db:
        return inst.authorization_state(db, db.get(PluginInstance, instance_id))


class Test连接上的状态:
    def test_从没授权到授权过(self, tmp_path) -> None:
        _, instance_id = install(tmp_path)
        assert state_of(instance_id) == UNAUTHORIZED
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            inst.set_credentials(db, instance, {"APP_KEY": "k"}, notify=False)
            assert inst.authorization_state(db, instance) == UNAUTHORIZED
            inst.set_credentials(db, instance, {"REFRESH_TOKEN": "good"}, notify=False)
            assert inst.authorization_state(db, instance) == AUTHORIZED

    def test_缺的正好是授权会填的格子时说还没授权(self, tmp_path) -> None:
        """否则连接的说明写着「缺少凭据:Refresh Token」,而那一格收在「手动填写」里 —— 该点的是「去授权」。"""
        _, instance_id = install(tmp_path)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            # AppKey 也缺的时候照旧点名缺哪几格:那一格授权替代不了。
            assert inst.blocked_reason(db, instance) == tr(
                "pluginBlocked_missingCredentials", names=tr("punct_listSep").join(["AppKey", "Refresh Token"])
            )
            inst.set_credentials(db, instance, {"APP_KEY": "k"}, notify=False)
            assert inst.blocked_reason(db, instance) == tr("pluginBlocked_unauthorized")

    def test_插件说被拒就记下_成功一次就清掉(self, tmp_path) -> None:
        ws, instance_id = install(tmp_path)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            inst.set_credentials(db, instance, {"APP_KEY": "k", "REFRESH_TOKEN": "revoked"}, notify=False)
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "failed"
        assert state_of(instance_id) == REJECTED

        with SessionLocal() as db:
            # 令牌在别处被修好了(比如插件自己续上了),这里不经 set_credentials 直接换掉那一格的值,
            # 只看「成功一次」这一条路能不能清掉。
            from app.db.models import PluginCredential

            db.get(PluginCredential, {"instance_id": instance_id, "key": "REFRESH_TOKEN"}).value = "good"
            db.commit()
            assert db.get(PluginInstance, instance_id).authorization_rejected_at is not None
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "succeeded"
        assert state_of(instance_id) == AUTHORIZED

    def test_与令牌无关的失败不算被拒(self, tmp_path) -> None:
        """文件不存在不说明令牌好坏 —— 把它当被拒,会让人去重走一遍授权,而问题不在那儿。"""
        ws, instance_id = install(tmp_path)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            inst.set_credentials(db, instance, {"APP_KEY": "k", "REFRESH_TOKEN": "missing-file"}, notify=False)
            assert invoke(db, instance_id, "go", {}, workspace_id=ws).status == "failed"
        assert state_of(instance_id) == AUTHORIZED

    def test_换了授权写的格子就清掉_换别的不清(self, tmp_path) -> None:
        ws, instance_id = install(tmp_path)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            inst.set_credentials(db, instance, {"APP_KEY": "k", "REFRESH_TOKEN": "revoked"}, notify=False)
            invoke(db, instance_id, "go", {}, workspace_id=ws)
            # 改 AppKey 不说明令牌换过了。
            inst.set_credentials(db, instance, {"APP_KEY": "k2"}, notify=False)
            assert inst.authorization_state(db, instance) == REJECTED
            # 掩码原样交回 = 那一格没改,也不算。
            inst.set_credentials(db, instance, {"REFRESH_TOKEN": inst.MASK}, notify=False)
            assert inst.authorization_state(db, instance) == REJECTED
            # 重新授权(或手动贴了新令牌)写的正是这一格。
            inst.set_credentials(db, instance, {"REFRESH_TOKEN": "fresh"}, notify=False)
            assert inst.authorization_state(db, instance) == AUTHORIZED

    def test_没声明_oauth_的插件不谈授权(self, tmp_path) -> None:
        manifest = {**MANIFEST, "id": "no-oauth", "instance": {**MANIFEST["instance"]}}
        del manifest["instance"]["oauth"]
        ws, instance_id = install(tmp_path, manifest)
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            inst.set_credentials(db, instance, {"APP_KEY": "k", "REFRESH_TOKEN": "revoked"}, notify=False)
            invoke(db, instance_id, "go", {}, workspace_id=ws)
            # 它说了 reauthorize 也没有「去授权」可点,记下来就再也清不掉。
            assert db.get(PluginInstance, instance_id).authorization_rejected_at is None
            assert inst.authorization_state(db, instance) == ""


def test_插件列表带着哪几格由授权填_和每个连接的状态(tmp_path) -> None:
    """界面据前者把令牌格收进「手动填写」,据后者在连接抬头下面标状态、决定按钮写「去授权」还是「重新授权」。"""
    install(tmp_path)
    listing = CLIENT[0].get("/api/plugins").json()
    package = next(one for one in listing if one["id"] == "auth-demo")
    # 端点、client_id 这些是后端拼链接用的,不往外给。
    assert package["oauth"] == {"fills": ["REFRESH_TOKEN", "ACCESS_TOKEN"]}
    assert [one["authorization"] for one in package["instances"]] == [UNAUTHORIZED]

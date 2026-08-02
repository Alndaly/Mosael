"""插件体系:包 → 实例 → 能力。

设计与取舍见 docs/PLUGIN_ARCHITECTURE.md 与 docs/adr/0005-*。这些测试钉住的是那份设计里
最容易被改回去的几条:能力默认不暴露、名字跟着配置走、配置与凭据分开、隔离边界不变。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.plugins import packages as pkg
from tests.util import fresh_client


def plugins_root() -> Path:
    """真实的插件目录(测试数据目录下,fresh_client 保证它是一次性的)。

    **不能用 tmp_path 顶替**:卸载走的是路由,而路由读的是 settings.plugins_dir。两边不一致
    的话,「不在插件目录里的路径不跑 rmtree」那道闸会在每个用例上误触发,于是测试全绿而它测的
    东西一次都没发生。
    """
    return settings.plugins_dir


ENV_ENTRY = """
import json, os, sys
req = json.loads(sys.stdin.read())
text = str(req["input"].get("text", ""))
json.dump({"ok": True, "output": {
    "loud": text.upper(), "length": len(text), "env": dict(os.environ), "echo": req["input"],
}}, sys.stdout)
"""

#: 无配置无凭据的包 —— 装上就能用,应该自动得到一个默认实例。
SIMPLE = {
    "id": "dev.simple",
    "name": "简单工具",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {
                "name": "shout",
                "description": "把文本变大写。",
                "read_only": True,
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "要处理的文本"}},
                    "required": ["text"],
                },
            }
        ],
    },
}

#: 有配置 + 凭据的包,而且允许接多次 —— TikHub 那一类。
KEYED = {
    "id": "dev.keyed",
    "name": "多端点服务",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "permissions": ["network:demo"],
    "instance": {
        "multiple": True,
        "name_template": "多端点服务 · {platform:label}",
        "config": [
            {
                "key": "platform",
                "label": "平台",
                "type": "enum",
                "required": True,
                "options": [
                    {"value": "bilibili", "label": "哔哩哔哩"},
                    {"value": "douyin", "label": "抖音"},
                ],
            }
        ],
        "credentials": [{"key": "api_key", "label": "API Key"}],
    },
    "tools": {
        "recommended": ["shout"],
        "declare": [
            {"name": "shout", "description": "大写。", "read_only": True,
             "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "noisy", "description": "另一个工具。",
             "input_schema": {"type": "object", "properties": {}}},
        ],
    },
}


def install(*manifests: dict, entry: str = ENV_ENTRY):
    """建库 + 登录 + 把这些包写进插件目录并扫描。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 插件的管理端点要求实例管理员
    shutil.rmtree(plugins_root(), ignore_errors=True)
    for manifest in manifests:
        directory = plugins_root() / manifest["id"].rsplit(".", 1)[-1]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "open-studio.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "main.py").write_text(entry, encoding="utf-8")
    with SessionLocal() as db:
        pkg.scan(db, plugins_root())
    return client


def packages(client) -> dict[str, dict]:
    return {item["id"]: item for item in client.get("/api/plugins").json()}


# --- 包与实例 -----------------------------------------------------------

def test_无配置的包装上就自动有一个默认连接() -> None:
    """text-toolkit 这种装上就能用的东西,不该逼用户先去"新建一个连接"。"""
    client = install(SIMPLE)
    package = packages(client)["dev.simple"]
    assert package["multiple"] is False
    assert [i["name"] for i in package["instances"]] == ["简单工具"]
    assert package["instances"][0]["enabled"] is False  # 装上不等于启用


def test_有配置的包不自动建连接_建了名字跟着配置走() -> None:
    """回归:此前包名是常量而平台是配置,用户配了 bilibili、面板上仍然写着「抖音」。
    名字跟不上身份,比没有名字更坏。"""
    client = install(KEYED)
    assert packages(client)["dev.keyed"]["instances"] == []

    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    assert created["name"] == "多端点服务 · 哔哩哔哩"

    # 改配置,名字跟着改。
    updated = client.patch(
        f"/api/plugins/instances/{created['id']}", json={"config": {"platform": "douyin"}}
    ).json()
    assert updated["name"] == "多端点服务 · 抖音"


def test_用户改过的名字不会被配置覆盖回去() -> None:
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}", json={"name": "我的B站号"})
    updated = client.patch(
        f"/api/plugins/instances/{created['id']}", json={"config": {"platform": "douyin"}}
    ).json()
    assert updated["name"] == "我的B站号"


def test_一个包可以接多次_各有各的凭据() -> None:
    """要同时用 bilibili 和 douyin,以前得把目录复制一份、手改 id —— 于是同一个包变成两份
    各自升级的副本。"""
    client = install(KEYED)
    a = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    b = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "douyin"}}).json()
    assert a["id"] != b["id"]
    assert len(packages(client)["dev.keyed"]["instances"]) == 2

    client.patch(f"/api/plugins/instances/{a['id']}/credentials", json={"values": {"api_key": "key-a"}})
    client.patch(f"/api/plugins/instances/{b['id']}/credentials", json={"values": {"api_key": "key-b"}})
    for instance_id, expected in ((a["id"], "key-a"), (b["id"], "key-b")):
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": {"network:demo": True}})
        client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
        out = client.post(
            f"/api/plugins/instances/{instance_id}/tools/shout/invoke", json={"input": {"text": "hi"}}
        ).json()
        assert out["output"]["env"]["API_KEY"] == expected


def test_只能有一个连接的包拒绝第二个() -> None:
    client = install(SIMPLE)
    res = client.post("/api/plugins/dev.simple/instances", json={})
    assert res.status_code == 422 and "只能有一个" in res.json()["detail"]


# --- 配置 / 凭据 ---------------------------------------------------------

def test_配置有类型有选项_凭据才是密码框() -> None:
    """`platform` 本质是个枚举,以前和 API Key 挤在同一张表、同一个密码框旁边 ——
    没有选项、没有校验,改了也不会改名字。"""
    client = install(KEYED)
    package = packages(client)["dev.keyed"]
    config_field = package["config_fields"][0]
    assert config_field["type"] == "enum" and config_field["secret"] is False
    assert [o["label"] for o in config_field["options"]] == ["哔哩哔哩", "抖音"]
    assert package["credential_fields"][0]["secret"] is True


def test_枚举收到不认识的值退回空_而不是静默连到不存在的端点() -> None:
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "weibo"}}).json()
    assert created["config"]["platform"] == ""
    enabled = client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True}).json()
    assert "缺少配置" in enabled["blocked_reason"]


def test_密文凭据回显是掩码_原样提交不覆盖() -> None:
    from app.domain.plugins.instances import MASK

    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k-123"}})

    listed = client.get(f"/api/plugins/instances/{created['id']}/credentials").json()
    assert listed[0]["value"] == MASK and listed[0]["filled"] is True

    # 掩码原样回传 = 这项没改。用户改别的字段时不该把 key 洗成一串星号。
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": MASK}})
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
    out = client.post(
        f"/api/plugins/instances/{created['id']}/tools/shout/invoke", json={"input": {"text": "x"}}
    ).json()
    assert out["output"]["env"]["API_KEY"] == "k-123"


def test_未声明的键被拒绝() -> None:
    """声明先行:这两张表不是人人可写的通用键值库。"""
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={}).json()
    assert client.patch(
        f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"OTHER": "x"}}
    ).status_code == 422
    assert client.patch(
        f"/api/plugins/instances/{created['id']}", json={"config": {"other": "x"}}
    ).status_code == 422


def test_插件只拿到自己的凭据_拿不到应用的(monkeypatch) -> None:
    """隔离边界。插件运行时不透传应用凭据是这套设计的地基 —— 否则"插件绕不过确认卡"
    这句话就不成立了。"""
    monkeypatch.setenv("OPENAI_API_KEY", "应用自己的密钥-不该出现在插件里")
    client = install(SIMPLE)
    instance = packages(client)["dev.simple"]["instances"][0]
    client.patch(f"/api/plugins/instances/{instance['id']}", json={"enabled": True})
    env = client.post(
        f"/api/plugins/instances/{instance['id']}/tools/shout/invoke", json={"input": {"text": "hi"}}
    ).json()["output"]["env"]
    assert "OPENAI_API_KEY" not in env
    # 我们**主动**给的就这几个;别的都是操作系统塞进子进程的(macOS 的
    # __CF_USER_TEXT_ENCODING 之类),不是我们透传的应用状态。
    assert set(env) & {"PATH", "HOME", "LANG", "OPEN_STUDIO_PLUGIN"} == {"PATH", "HOME", "LANG", "OPEN_STUDIO_PLUGIN"}
    assert not any(key.endswith("_API_KEY") or key.endswith("_TOKEN") for key in env)


# --- 能力开关 -----------------------------------------------------------

def test_能力默认不暴露_只开_manifest_推荐的() -> None:
    """一个 MCP 端点报几十个工具(TikHub 的 bilibili 报了 41 个)。全量涌进节点面板和智能体
    工具表,面板要人从四十行里找一行,而要人挑出该关的三十七个没有人会做。"""
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k"}})
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
    enabled = client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True}).json()

    assert {t["name"]: t["exposed"] for t in enabled["tools"]} == {"shout": True, "noisy": False}
    assert [t["name"] for t in client.get("/api/plugins/tools").json()] == ["shout"]


def test_expose_all_的包全开() -> None:
    """工具本来就少的包,让用户逐个勾是无谓的仪式。"""
    client = install(SIMPLE)
    instance = packages(client)["dev.simple"]["instances"][0]
    client.patch(f"/api/plugins/instances/{instance['id']}", json={"enabled": True})
    assert [t["name"] for t in client.get("/api/plugins/tools").json()] == ["shout"]


def test_能力开关可以逐个改() -> None:
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "bilibili"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k"}})
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})

    client.patch(
        f"/api/plugins/instances/{created['id']}/capabilities", json={"tools": {"noisy": True, "shout": False}}
    )
    assert [t["name"] for t in client.get("/api/plugins/tools").json()] == ["noisy"]


# --- 四道门 -------------------------------------------------------------

def test_不可用的原因一句话说清() -> None:
    """启用 / 配置 / 凭据 / 授权四道门收成一句话:界面和智能体报错都用它,免得同一件事在
    三处各写一句不一样的话。"""
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={}).json()
    assert created["blocked_reason"] == "未启用"

    def reason() -> str:
        package = packages(client)["dev.keyed"]
        return package["instances"][0]["blocked_reason"]

    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
    assert "缺少配置: 平台" == reason()
    client.patch(f"/api/plugins/instances/{created['id']}", json={"config": {"platform": "douyin"}})
    assert "缺少凭据: API Key" == reason()
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k"}})
    assert "权限未授予" == reason()
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
    assert "" == reason()
    # 不可用的实例一个工具都不出:让智能体去调一个必定失败的工具,只会烧掉一轮对话。
    assert client.get("/api/plugins/tools").json() != []


# --- 智能体 -------------------------------------------------------------

def test_插件工具在智能体清单里是一等公民_且按连接区分() -> None:
    """元工具意味着模型要先"想到"可能有插件能帮忙,再花一轮列清单才知道参数长什么样 ——
    它想不到的时候,用户装的插件就等于不存在。而两个连接是两套工具,模型要能分辨。"""
    client = install(KEYED)
    ids = []
    for platform in ("bilibili", "douyin"):
        created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": platform}}).json()
        client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k"}})
        client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
        client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
        ids.append(created["id"])

    specs = {t["name"]: t for t in client.get("/api/agent/tools").json()}
    names = [n for n in specs if n.startswith("plugin__")]
    assert len(names) == 2, "两个连接应当是两个工具"
    assert any("哔哩哔哩" in specs[n]["description"] for n in names)
    assert any("抖音" in specs[n]["description"] for n in names)
    # 元工具让位给展开后的一等公民,不再在这份清单里重复同一个能力。
    assert "invoke_plugin_tool" not in specs and "list_plugin_tools" not in specs

    result = client.post(f"/api/agent/tools/{names[0]}", json={"arguments": {"text": "hi"}})
    assert result.status_code == 200, result.text
    assert result.json()["result"]["loud"] == "HI"


def test_停用后智能体那条路径立刻关上() -> None:
    client = install(SIMPLE)
    instance = packages(client)["dev.simple"]["instances"][0]
    client.patch(f"/api/plugins/instances/{instance['id']}", json={"enabled": True})
    name = next(t["name"] for t in client.get("/api/agent/tools").json() if t["name"].startswith("plugin__"))
    assert client.post(f"/api/agent/tools/{name}", json={"arguments": {"text": "x"}}).status_code == 200

    client.patch(f"/api/plugins/instances/{instance['id']}", json={"enabled": False})
    blocked = client.post(f"/api/agent/tools/{name}", json={"arguments": {"text": "x"}})
    assert blocked.status_code == 404 and "未启用" in blocked.json()["detail"]


def test_插件工具默认不是只读_子智能体因此拿不到() -> None:
    """内置工具的只读判据是"没有确认门";插件工具没有确认门也照样能发请求、写文件。"""
    client = install(KEYED)
    created = client.post("/api/plugins/dev.keyed/instances", json={"config": {"platform": "douyin"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}/credentials", json={"values": {"api_key": "k"}})
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:demo": True}})
    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
    client.patch(f"/api/plugins/instances/{created['id']}/capabilities", json={"tools": {"noisy": True}})

    specs = {t["name"]: t for t in client.get("/api/agent/tools").json()}
    plugin_specs = {n.split("__")[-1]: s for n, s in specs.items() if n.startswith("plugin__")}
    assert plugin_specs["shout"]["read_only"] is True
    assert plugin_specs["noisy"]["read_only"] is False
    # 内置工具的只读仍然等价于"没有确认门",这条改动不该动到它们。
    assert specs["search_kb"]["read_only"] is True
    assert specs["render_sequence"]["read_only"] is False


# --- 兼容与清理 ---------------------------------------------------------

LEGACY = {
    "id": "dev.legacy",
    "name": "老写法插件",
    "version": "0.1.0",
    "entry": "main.py",
    "credentials": [{"key": "OLD_KEY", "label": "旧密钥", "required": False}],
    "tools": [{"name": "shout", "description": "大写。", "read_only": True,
               "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}}}],
}


def test_旧写法的清单在扫描时就地迁移成新写法() -> None:
    """兼容负担只在升级那一刻付一次:磁盘上的文件被改写成新形状,读取代码里不留分支。

    和 core/db.py 那串 _migrate_* 同一个思路 —— 读取路径里的 `if 老写法 elif 新写法` 是永久
    的税,而两条分支里总有一条平时没人走、坏了也没人发现。
    """
    from app.domain.plugins.migrations import MANIFEST_VERSION

    client = install(LEGACY)
    directory = plugins_root() / "legacy"
    migrated = json.loads((directory / "open-studio.plugin.json").read_text(encoding="utf-8"))

    assert migrated["manifest_version"] == MANIFEST_VERSION
    assert migrated["runtime"] == {"kind": "process", "entry": "main.py"}      # 顶层 kind/entry 收进 runtime
    assert migrated["instance"]["credentials"][0]["key"] == "OLD_KEY"          # 顶层 credentials 进 instance
    assert migrated["tools"]["expose"] == "all"                                # 数组形态此前就是全暴露
    assert [t["name"] for t in migrated["tools"]["declare"]] == ["shout"]
    assert migrated["tools"]["overrides"]["shout"]["read_only"] is True
    assert "kind" not in migrated and "credentials" not in migrated            # 老字段清干净

    # 原文件留一份备份,并且不再作为清单被认出来。
    assert (directory / "open-studio.plugin.json.bak").exists() or (directory / "mibu.plugin.json.bak").exists()

    # 迁移完照样能用,而且工具没被悄悄关掉。
    package = packages(client)["dev.legacy"]
    assert package["credential_fields"][0]["key"] == "OLD_KEY"
    created = client.post("/api/plugins/dev.legacy/instances", json={}).json()
    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
    assert [t["name"] for t in client.get("/api/plugins/tools").json()] == ["shout"]


def test_迁移是幂等的_跑第二次不再改动() -> None:
    client = install(LEGACY)
    path = plugins_root() / "legacy" / "open-studio.plugin.json"
    first = path.read_text(encoding="utf-8")
    with SessionLocal() as db:
        pkg.scan(db, plugins_root())
    assert path.read_text(encoding="utf-8") == first
    assert client is not None


def test_更名前的文件名被改成规范名() -> None:
    """`mibu.plugin.json` 是更名前的写法。以前是读的时候多认一个名字,现在是扫的时候改掉它 ——
    一个目录一份清单,一个名字。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    shutil.rmtree(plugins_root(), ignore_errors=True)
    directory = plugins_root() / "old-name"
    directory.mkdir(parents=True)
    (directory / "mibu.plugin.json").write_text(json.dumps(LEGACY), encoding="utf-8")
    (directory / "main.py").write_text(ENV_ENTRY, encoding="utf-8")
    with SessionLocal() as db:
        pkg.scan(db, plugins_root())

    assert (directory / "open-studio.plugin.json").exists()
    assert not (directory / "mibu.plugin.json").exists()
    assert (directory / "mibu.plugin.json.bak").exists()
    assert "dev.legacy" in packages(client)


def test_目录被手动删掉后_扫描顺手清掉那条记录() -> None:
    client = install(SIMPLE, KEYED)
    assert set(packages(client)) == {"dev.simple", "dev.keyed"}

    shutil.rmtree(plugins_root() / "keyed")
    with SessionLocal() as db:
        pkg.scan(db, plugins_root())
    assert set(packages(client)) == {"dev.simple"}


def test_插件目录整体不见时不做任何清理() -> None:
    """外挂盘没挂上、权限没了 —— 这时候把用户的全部配置和凭据抹掉是最糟的反应。"""
    from app.domain.plugins.packages import _prune

    client = install(SIMPLE)
    shutil.rmtree(plugins_root())
    with SessionLocal() as db:
        _prune(db, plugins_root())  # 不走 scan(它会 mkdir 把目录变出来)
        db.commit()
    assert set(packages(client)) == {"dev.simple"}


def test_卸载连目录一起删_否则下次扫描又装回来() -> None:
    client = install(SIMPLE)
    assert client.delete("/api/plugins/dev.simple").status_code == 204
    assert not (plugins_root() / "simple").exists()
    with SessionLocal() as db:
        pkg.scan(db, plugins_root())
    assert packages(client) == {}

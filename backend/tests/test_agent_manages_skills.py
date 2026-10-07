"""智能体自己管技能(ADR 0043):list_skills 和六件写的事 —— 新建、改、复制成我的、开关、删、从链接导入。

每件写的事都开一张确认卡,批了才落地;卡**每一次都要人点头**(本会话始终允许、放行准则、bypass 都放不过);
在用某个技能时提出的,卡上写明是哪几个。工具都经智能体的工具通道调(带这次对话的 turn 令牌,和 sidecar 发的是同一个请求)。
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from app.core import outbound_guard
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage, ToolConfirmation, User, Workspace
from app.domain.agent import rules, stream
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.domain.agent.skills import catalog, store
from mosael_formats.agent_skill import MAX_FILE_BYTES, MAX_SKILL_MD_BYTES, SkillDoc
from tests.util import fresh_client, second_client

WRITE_TOOLS = ("create_skill", "update_skill", "copy_skill", "set_skill_enabled", "delete_skill", "import_skill")


class Chat:
    """一个工作区、一次对话,和这次对话的 turn 令牌 —— 智能体调工具用的就是它。"""

    def __init__(self) -> None:
        self.client = fresh_client()
        self.workspace_id = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        self.session_id = self.client.post(
            "/api/agent/sessions", json={"workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            self.user_id = user.id
            self.token = mint_service_session(db, user.id, agent_session_id=self.session_id)
            db.commit()

    def tool(self, tool_name: str, /, **arguments) -> dict:
        response = self.client.post(
            f"/api/agent/tools/{tool_name}", json={"arguments": arguments, "requested_by": "pi"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def card(self, tool_name: str, /, **arguments) -> dict:
        """调一个写技能的工具,回它开的那张卡(接口出口那一份)。"""
        out = self.tool(tool_name, **arguments)
        assert "result" in out, out
        card_id = out["result"]["confirmation_id"]
        wait_for_idle_autopilot()
        return self.client.get(f"/api/confirmations/{card_id}").json()

    def error(self, tool_name: str, /, **arguments) -> str:
        out = self.tool(tool_name, **arguments)
        assert "error" in out, out
        return out["error"]

    def approve(self, card: dict, **choices: bool) -> dict:
        response = self.client.post(f"/api/confirmations/{card['id']}/approve", json={"choices": choices} if choices else None)
        assert response.status_code == 200, response.text
        return response.json()

    def skills(self) -> dict[str, catalog.Skill]:
        with SessionLocal() as db:
            return {one.ref: one for one in catalog.list_skills(db, self.workspace_id)}

    def mine(self, name: str, body: str = "1. 第一步\n2. 第二步\n3. 第三步\n", files: dict[str, bytes] | None = None) -> None:
        with SessionLocal() as db:
            doc = SkillDoc(name=name, description="做一件事", body=body).with_title("我的做法")
            store.create(db, self.workspace_id, doc, origin="created", user_id=self.user_id, files=files)
            db.commit()


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


SKILL_MD = "---\nname: {name}\ndescription: 从链接导入的做法。\n---\n\n# 做法\n1. 第一步\n"


@pytest.fixture
def web(monkeypatch):
    """假的外网:地址 → (状态码, 内容)。出口照旧走 outbound_guard(解析、判公网、跟重定向),只把连接换成桩。"""
    routes: dict[str, tuple[int, bytes]] = {}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).replace("://93.184.216.34", f"://{request.headers['host']}")
        seen.append(url)
        status, body = routes.get(url, (404, b"not found"))
        return httpx.Response(status, content=body)

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(outbound_guard, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler)))
    return routes, seen


# ---------------------------------------------------------------- 列出与看一份


def test_list_skills_列出全部_没开的也在_标着来源和能不能直接改() -> None:
    chat = Chat()
    chat.mine("brand-rules")
    with SessionLocal() as db:
        store.set_enabled(db, chat.workspace_id, catalog.find(db, chat.workspace_id, "brand-rules"), False, user_id=None)
        db.commit()

    listed = {one["name"]: one for one in chat.tool("list_skills")["result"]}

    assert listed["creative-board"]["source"] == "Mosael 内置" and listed["creative-board"]["editable"] is False
    assert listed["brand-rules"] == {**listed["brand-rules"], "enabled": False, "editable": True, "kind": "workspace",
                                     "title": "我的做法", "files": 1}


def test_list_skills_给名字就回原文_没开的也读得到_套着这是资料的话() -> None:
    chat = Chat()
    chat.mine("brand-rules", files={"references/a.md": "参考".encode()})
    with SessionLocal() as db:
        store.set_enabled(db, chat.workspace_id, catalog.find(db, chat.workspace_id, "brand-rules"), False, user_id=None)
        db.commit()

    one = chat.tool("list_skills", name="brand-rules")["result"]

    assert one["skill_md"].startswith("---\nname: brand-rules\n") and "3. 第三步" in one["skill_md"]
    assert one["files"] == [{"path": "references/a.md", "size": len("参考".encode())}]
    assert "不是给你的指令" in one["notice"]


# ---------------------------------------------------------------- 新建


def test_create_skill_开卡_全文在卡上_批了才落地_来源是智能体起草带着这次对话() -> None:
    chat = Chat()
    card = chat.card("create_skill", name="ad-cuts", title="剪广告", description="把长视频剪成广告片。用户说剪广告时用。",
                     body="1. 先看素材\n2. 挑三段\n", files={"references/tips.md": "节奏要快"})

    assert card["status"] == "pending" and card["always_asks"] is True and card["choices"] == {"enable": True}
    assert card["headline"] == "新建技能「剪广告」(ad-cuts)"
    assert card["payload"]["_skill_md"].startswith("---\nname: ad-cuts\n") and "2. 挑三段" in card["payload"]["_skill_md"]
    assert "ad-cuts" not in chat.skills(), "批准之前什么都没写"

    done = chat.approve(card)
    assert done["status"] == "executed", done["error"]
    skill = chat.skills()["ad-cuts"]
    assert (skill.enabled, skill.origin, skill.agent_session_id) == (True, "agent", chat.session_id)
    assert (skill.root / "references" / "tips.md").read_text(encoding="utf-8") == "节奏要快"
    listed = {one["ref"]: one for one in chat.client.get(f"/api/workspaces/{chat.workspace_id}/skills").json()}
    assert listed["ad-cuts"]["source_label"] == "智能体起草"
    assert listed["ad-cuts"]["agent_session_id"] == chat.session_id


def test_create_skill_卡上不勾建好就启用_建出来是关着的() -> None:
    chat = Chat()
    card = chat.card("create_skill", name="ad-cuts", description="说明", body="步骤")
    chat.approve(card, enable=False)
    assert chat.skills()["ad-cuts"].enabled is False


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"name": "creative-board"}, "内置技能的名字"),
        ({"name": "Bad Name"}, "Bad Name"),
        ({"body": "长" * MAX_SKILL_MD_BYTES}, "64"),
        ({"files": {"big.md": "x" * (MAX_FILE_BYTES + 1)}}, "big.md"),
        ({"files": {"../escape.md": "x"}}, "../escape.md"),
        ({"files": {"/etc/passwd": "x"}}, "/etc/passwd"),
        ({"files": {"a.bin": "x\u0000y"}}, "文本"),
        ({"files": {"SKILL.md": "x"}}, "SKILL.md"),
    ],
)
def test_create_skill_说不通的在开卡之前就拒(arguments: dict, expected: str) -> None:
    chat = Chat()
    error = chat.error("create_skill", **{"name": "ok-name", "description": "说明", "body": "步骤", **arguments})
    assert expected in error
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).count() == 0, "没开卡"


# ---------------------------------------------------------------- 改


def test_update_skill_卡上是改之前到改之后_批了落地_开关和来历不动() -> None:
    chat = Chat()
    chat.mine("brand-rules", files={"references/old.md": "旧的".encode()})
    card = chat.card("update_skill", name="brand-rules", body="1. 第一步\n2. 第二步\n3. 改过的第三步\n",
                     files={"references/new.md": "新的", "references/old.md": None})

    changes = {one["path"]: one for one in card["payload"]["_changes"]}
    assert set(changes) == {"SKILL.md", "references/new.md", "references/old.md"}
    assert "3. 第三步" in changes["SKILL.md"]["before"] and "3. 改过的第三步" in changes["SKILL.md"]["after"]
    assert changes["references/old.md"] == {"path": "references/old.md", "before": "旧的", "after": None}
    assert card["headline"].startswith("修改技能「我的做法」:3 个文件有改动")
    assert "改过的" not in (chat.skills()["brand-rules"].root / "SKILL.md").read_text(encoding="utf-8")

    assert chat.approve(card)["status"] == "executed"
    skill = chat.skills()["brand-rules"]
    assert "3. 改过的第三步" in skill.doc.body and skill.title == "我的做法"
    assert (skill.enabled, skill.origin) == (True, "created")
    assert sorted(one.path for one in catalog.files_of(skill)) == ["SKILL.md", "references/new.md"]


def test_update_skill_开卡之后有人改过_批准失败_什么都没写() -> None:
    chat = Chat()
    chat.mine("brand-rules")
    card = chat.card("update_skill", name="brand-rules", description="新的说明")
    (chat.skills()["brand-rules"].root / "notes.md").write_text("别人刚加的", encoding="utf-8")

    done = chat.approve(card)

    assert done["status"] == "failed" and "开卡之后" in done["error"]
    assert chat.skills()["brand-rules"].description == "做一件事"


@pytest.mark.parametrize("tool", ["update_skill", "delete_skill"])
def test_内置的不能直接改也不能删_告诉智能体先复制(tool: str) -> None:
    chat = Chat()
    arguments = {"name": "creative-board", **({"description": "改"} if tool == "update_skill" else {})}
    error = chat.error(tool, **arguments)
    assert ("copy_skill" in error) if tool == "update_skill" else ("set_skill_enabled" in error)


def test_插件带的技能也不能直接改(monkeypatch, tmp_path) -> None:
    chat = Chat()
    plugin = tmp_path / "skills" / "tips"
    plugin.mkdir(parents=True)
    (plugin / "SKILL.md").write_text("---\nname: tips\ndescription: 插件的做法\n---\n步骤\n", encoding="utf-8")
    monkeypatch.setattr(catalog, "plugin_roots", lambda db: [("dev.example.p", "示例插件", tmp_path / "skills")])

    assert "copy_skill" in chat.error("update_skill", name="dev.example.p:tips", body="改")
    card = chat.card("copy_skill", name="dev.example.p:tips", new_name="my-tips")
    assert card["payload"]["_source_label"] == "插件「示例插件」"


def test_update_skill_没给要改的_不开卡() -> None:
    chat = Chat()
    chat.mine("brand-rules")
    assert "没有要改的地方" in chat.error("update_skill", name="brand-rules")


# ---------------------------------------------------------------- 复制成我的


def test_copy_skill_内置的复制成我的_顺带改说明_卡上是新的全文() -> None:
    chat = Chat()
    card = chat.card("copy_skill", name="creative-board", new_name="my-board", description="我们自己的画板做法")

    assert card["choices"] == {"enable": True} and card["always_asks"] is True
    assert "name: my-board" in card["payload"]["_skill_md"] and "我们自己的画板做法" in card["payload"]["_skill_md"]
    assert card["payload"]["_source_title"] == "创意画板"
    assert chat.approve(card)["status"] == "executed"
    copied = chat.skills()["my-board"]
    assert (copied.origin, copied.imported_from, copied.agent_session_id) == ("agent", "creative-board", chat.session_id)
    assert copied.description == "我们自己的画板做法"
    assert chat.skills()["creative-board"].description != "我们自己的画板做法", "原来那份不动"


def test_copy_skill_已经是我的就叫它直接改() -> None:
    chat = Chat()
    chat.mine("brand-rules")
    assert "update_skill" in chat.error("copy_skill", name="brand-rules", new_name="brand-rules-2")


# ---------------------------------------------------------------- 开关、删


def test_set_skill_enabled_关是一句话_开要记下批的是哪一版() -> None:
    chat = Chat()
    off = chat.card("set_skill_enabled", name="creative-board", enabled=False)
    assert off["headline"] == "关掉技能「创意画板」" and "_digest" not in off["payload"]
    assert chat.approve(off)["status"] == "executed"
    assert chat.skills()["creative-board"].enabled is False

    on = chat.card("set_skill_enabled", name="creative-board", enabled=True)
    assert on["payload"]["_digest"] and on["headline"].startswith("启用技能「创意画板」")
    assert chat.approve(on)["status"] == "executed"
    assert chat.skills()["creative-board"].enabled is True
    assert "已经开着" in chat.error("set_skill_enabled", name="creative-board", enabled=True)


def test_delete_skill_撤不回的那一档_批了文件夹一起没() -> None:
    chat = Chat()
    chat.mine("brand-rules")
    root = chat.skills()["brand-rules"].root
    card = chat.card("delete_skill", name="brand-rules")

    assert card["permission"] == "destroy" and card["payload"]["_files"] == 1
    assert chat.approve(card)["status"] == "executed"
    assert "brand-rules" not in chat.skills() and not root.exists()


# ---------------------------------------------------------------- 从链接导入


def test_import_skill_github_文件夹_卡上照设置页那份审阅_批了才装_默认不开(web) -> None:
    routes, seen = web
    chat = Chat()
    api = "https://api.github.com/repos/acme/skills/contents"
    raw = "https://raw.githubusercontent.com/acme/skills/main/skills/pdf"
    routes[f"{api}/skills/pdf?ref=main"] = (200, (
        '[{"type": "file", "path": "skills/pdf/SKILL.md", "size": 70, "download_url": "' + raw + '/SKILL.md"},'
        ' {"type": "dir", "path": "skills/pdf/scripts"}]').encode())
    routes[f"{api}/skills/pdf/scripts?ref=main"] = (200, (
        '[{"type": "file", "path": "skills/pdf/scripts/run.py", "size": 10, "download_url": "' + raw + '/scripts/run.py"}]'
    ).encode())
    routes[f"{raw}/SKILL.md"] = (200, SKILL_MD.format(name="pdf").encode())
    routes[f"{raw}/scripts/run.py"] = (200, b"print('x')")

    card = chat.card("import_skill", url="https://github.com/acme/skills/tree/main/skills/pdf")

    assert card["choices"] == {"enable": False} and card["always_asks"] is True
    assert card["payload"]["_skills"] == [{"name": "pdf", "title": "", "conflict": "", "files": 2}]
    assert card["headline"] == "从 github.com/acme/skills/tree/main/skills/pdf 导入 1 个技能:pdf"
    preview = chat.client.get(f"/api/workspaces/{chat.workspace_id}/skill-imports/{card['payload']['import_id']}").json()
    files = {one["path"]: one for one in preview["skills"][0]["files"]}
    assert files["scripts/run.py"]["script"] is True and files["SKILL.md"]["text"].startswith("---\nname: pdf")
    assert "pdf" not in chat.skills()

    assert chat.approve(card)["status"] == "executed"
    skill = chat.skills()["pdf"]
    assert (skill.enabled, skill.origin, skill.agent_session_id) == (False, "imported", chat.session_id)
    assert skill.imported_from == "github.com/acme/skills/tree/main/skills/pdf"
    assert all("93.184.216.34" not in one for one in seen)


def test_import_skill_zip_链接_勾上启用就装好开着(web) -> None:
    routes, _ = web
    chat = Chat()
    routes["https://example.com/pack.zip"] = (200, _zip({"pack/a/SKILL.md": SKILL_MD.format(name="a").encode(),
                                                          "pack/b/SKILL.md": SKILL_MD.format(name="b").encode()}))
    card = chat.card("import_skill", url="https://example.com/pack.zip", skills=["b"])
    assert [one["name"] for one in card["payload"]["_skills"]] == ["b"]
    assert chat.approve(card, enable=True)["status"] == "executed"
    assert chat.skills()["b"].enabled is True and "a" not in chat.skills()


@pytest.mark.parametrize(
    "url,body,expected",
    [
        ("http://example.com/pack.zip", None, "https"),
        ("https://example.com/page.html", None, "认不出这个链接"),
        ("https://github.com/acme", None, "认不出这个链接"),
        ("https://example.com/fake.zip", b"<html>not a zip</html>", ".zip"),
        ("https://example.com/empty.zip", _zip({"readme.txt": b"hi"}), "SKILL.md"),
        ("https://example.com/missing.zip", "404", "404"),
        ("https://github.com/acme/skills/tree/main/nope", "404", "404"),
    ],
)
def test_import_skill_链接不对或者拿到的不是技能_不开卡(web, url: str, body, expected: str) -> None:
    routes, _ = web
    chat = Chat()
    if isinstance(body, bytes):
        routes[url] = (200, body)
    error = chat.error("import_skill", url=url)
    assert expected in error, error
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).count() == 0


def test_import_skill_文件夹里有超大的文件_不下就拒(web) -> None:
    routes, seen = web
    chat = Chat()
    routes["https://api.github.com/repos/acme/skills/contents/big?ref=main"] = (200, (
        '[{"type": "file", "path": "big/SKILL.md", "size": ' + str(MAX_FILE_BYTES + 1)
        + ', "download_url": "https://raw.githubusercontent.com/acme/skills/main/big/SKILL.md"}]').encode())
    assert "2" in chat.error("import_skill", url="https://github.com/acme/skills/tree/main/big")
    assert not any("raw.githubusercontent.com" in one for one in seen), "看到大小超了就不下"


def test_出口按上限边收边数_超了就停_不整个读进内存(web) -> None:
    """链接是模型写的:对面说多大不算数,收到上限就停(outbound_guard.send 的 max_bytes)。"""
    routes, _ = web
    routes["https://example.com/huge.bin"] = (200, b"x" * 4096)
    with pytest.raises(outbound_guard.ResponseTooLarge):
        outbound_guard.send("GET", "https://example.com/huge.bin", timeout=5, max_bytes=1024)
    small = outbound_guard.send("GET", "https://example.com/huge.bin", timeout=5, max_bytes=8192)
    assert small.response.content == b"x" * 4096 and small.response.headers["content-length"] == "4096"


def test_import_skill_和已有的同名_要说明替换才开卡(web) -> None:
    routes, _ = web
    chat = Chat()
    chat.mine("brand-rules")
    routes["https://example.com/b.zip"] = (200, _zip({"brand-rules/SKILL.md": SKILL_MD.format(name="brand-rules").encode()}))
    assert "replace=true" in chat.error("import_skill", url="https://example.com/b.zip")
    card = chat.card("import_skill", url="https://example.com/b.zip", replace=True)
    assert card["payload"]["_skills"][0]["conflict"] == "workspace"
    assert chat.approve(card)["status"] == "executed"
    assert chat.skills()["brand-rules"].description == "从链接导入的做法。"


# ---------------------------------------------------------------- 权限


@pytest.mark.parametrize("tool,arguments", [
    ("create_skill", {"name": "x-skill", "description": "说明", "body": "步骤"}),
    ("update_skill", {"name": "brand-rules", "body": "改"}),
    ("copy_skill", {"name": "creative-board", "new_name": "my-board"}),
    ("set_skill_enabled", {"name": "creative-board", "enabled": False}),
    ("delete_skill", {"name": "brand-rules"}),
    ("import_skill", {"url": "https://example.com/pack.zip"}),
])
def test_看的人能列不能改(tool: str, arguments: dict) -> None:
    chat = Chat()
    chat.mine("brand-rules")
    viewer = second_client("viewer-x")
    chat.client.post(f"/api/workspaces/{chat.workspace_id}/invitations", json={"username": "viewer-x", "role": "viewer"})
    invitation = viewer.get("/api/invitations").json()["invitations"][0]
    viewer.post(f"/api/invitations/{invitation['id']}/accept")

    listed = viewer.post("/api/agent/tools/list_skills", json={"arguments": {"workspace_id": chat.workspace_id}}).json()
    assert "brand-rules" in {one["name"] for one in listed["result"]}
    out = viewer.post(f"/api/agent/tools/{tool}", json={"arguments": {**arguments, "workspace_id": chat.workspace_id}}).json()
    assert "error" in out and "denied" in out["error"].lower(), out
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).count() == 0


# ---------------------------------------------------------------- 每次都问


def _open_one_of_each(chat: Chat, web) -> list[dict]:
    routes, _ = web
    chat.mine("brand-rules")
    chat.mine("old-rules")
    routes["https://example.com/pack.zip"] = (200, _zip({"pack/SKILL.md": SKILL_MD.format(name="pack").encode()}))
    return [
        chat.card("create_skill", name="ad-cuts", description="说明", body="步骤"),
        chat.card("update_skill", name="brand-rules", body="改过的"),
        chat.card("copy_skill", name="creative-board", new_name="my-board"),
        chat.card("set_skill_enabled", name="workflow-canvas", enabled=False),
        chat.card("delete_skill", name="old-rules"),
        chat.card("import_skill", url="https://example.com/pack.zip"),
    ]


def test_bypass_档和放行准则都放不过改技能的卡(web) -> None:
    chat = Chat()
    assert chat.client.patch(f"/api/agent/sessions/{chat.session_id}", json={"permission_mode": "bypass"}).status_code == 200
    with SessionLocal() as db:
        db.get(Workspace, chat.workspace_id).autopilot_rules = {key: "always" for key in rules.gates()}
        db.commit()

    cards = _open_one_of_each(chat, web)

    assert [card["tool"] for card in cards] == list(WRITE_TOOLS)
    assert all(card["status"] == "pending" and card["decision_mode"] == "manual" for card in cards)
    assert all(rules.evaluate(tool, {}, {key: "always" for key in rules.gates()}).denied for tool in WRITE_TOOLS)


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_本会话始终允许加不进改技能的卡(tool: str) -> None:
    chat = Chat()
    refused = chat.client.patch(f"/api/agent/sessions/{chat.session_id}", json={"auto_allow_tools": [{"tool": tool, "permission": "edit"}]})
    assert refused.status_code == 422, refused.text


def test_auto_档也放不过_edit_档的改技能卡(web) -> None:
    chat = Chat()
    assert chat.client.patch(f"/api/agent/sessions/{chat.session_id}", json={"permission_mode": "auto"}).status_code == 200
    cards = _open_one_of_each(chat, web)
    assert all(card["status"] == "pending" for card in cards)


# ---------------------------------------------------------------- 在用技能时提出的


def _running_turn_that_used(chat: Chat, *calls: tuple[str, dict, str]) -> None:
    """一轮正在跑、里面调过这些工具:(工具名, 参数, 结局)。和 sidecar 报给流的事件同一个形状。"""
    stream._stream_reset(chat.session_id)
    for index, (name, args, status) in enumerate(calls):
        stream._stream_tool_event(chat.session_id, {"type": "tool_start", "toolCallId": f"c{index}", "name": name, "args": args})
        stream._stream_tool_event(chat.session_id, {"type": "tool_end", "toolCallId": f"c{index}", "isError": status == "error"})


def test_这一轮_use_skill_读过的技能_卡上写明是在用它时提出的() -> None:
    chat = Chat()
    _running_turn_that_used(chat, ("use_skill", {"name": "creative-board"}, "done"), ("use_skill", {"name": "3d-scene"}, "error"))

    card = chat.card("create_skill", name="ad-cuts", description="说明", body="步骤")

    assert card["warning"] == "这是在用技能『创意画板』时提出的"
    assert card["payload"]["_skills_in_use"] == [{"ref": "creative-board", "title": "创意画板"}]
    assert "⚠️ 这是在用技能『创意画板』时提出的" in card["summary"], "一行字的出口(飞书、MCP)也带着"


def test_斜杠点名的技能也算_排着队的那条不算() -> None:
    chat = Chat()
    _running_turn_that_used(chat)
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=chat.session_id, role="user", content="改改", payload={"skills": ["workflow-canvas"]}))
        db.add(AgentMessage(session_id=chat.session_id, role="user", content="下一句",
                            payload={"queued": True, "skills": ["3d-scene"]}))
        db.commit()

    card = chat.card("set_skill_enabled", name="workflow-canvas", enabled=False)

    assert card["payload"]["_skills_in_use"] == [{"ref": "workflow-canvas", "title": "搭工作流"}]


def test_只是看一份技能_或者这一轮已经结束_不算在用() -> None:
    chat = Chat()
    _running_turn_that_used(chat, ("list_skills", {"name": "creative-board"}, "done"))
    assert chat.card("create_skill", name="a-skill", description="说明", body="步骤")["warning"] == ""

    _running_turn_that_used(chat, ("use_skill", {"name": "creative-board"}, "done"))
    stream._stream_finish(chat.session_id, "")
    assert chat.card("create_skill", name="b-skill", description="说明", body="步骤")["warning"] == ""

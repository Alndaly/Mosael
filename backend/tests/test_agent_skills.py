"""智能体技能的运行时(ADR 0040 §2–§6):三个来源、系统提示里的目录、两个只读工具、「/」点名、路径与来源。

设置页那一半(新建编辑、导入导出、存成技能的接口)在 test_agent_skills_settings.py。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import mcp_server
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import PluginPackage
from app.domain.agent import host
from app.domain.agent import prompt as agent_prompt
from app.domain.agent.host import TurnResult
from app.domain.agent.skills import catalog, runtime, store
from app.domain.plugins.manifest import PATH_KEY
from mosael_formats.agent_skill import SkillDoc
from tests.util import add_provider, fresh_client

BUILTINS = ("3d-scene", "creative-board", "workflow-canvas")
REPO = Path(__file__).resolve().parents[2]


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _create(workspace_id: str, name: str, description: str = "做一件事", body: str = "步骤一\n", title: str = "",
            files: dict[str, bytes] | None = None) -> None:
    with SessionLocal() as db:
        doc = SkillDoc(name=name, description=description, body=body).with_title(title)
        store.create(db, workspace_id, doc, origin="created", user_id=None, files=files)
        db.commit()


def _enable(workspace_id: str, ref: str, enabled: bool) -> None:
    with SessionLocal() as db:
        store.set_enabled(db, workspace_id, catalog.find(db, workspace_id, ref), enabled, user_id=None)
        db.commit()


def _skills(workspace_id: str) -> dict[str, catalog.Skill]:
    with SessionLocal() as db:
        return {one.ref: one for one in catalog.list_skills(db, workspace_id)}


def _tool(client, tool_name: str, **arguments):
    response = client.post(f"/api/agent/tools/{tool_name}", json={"arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()


def _system_prompt(workspace_id: str) -> str:
    with SessionLocal() as db:
        return runtime.skills_prompt(db, workspace_id)


# ---------------------------------------------------------------- 内置技能与系统提示


def test_内置技能都合规范_默认开着_按名字排() -> None:
    client = fresh_client()
    ws = _workspace(client)
    listed = client.get(f"/api/workspaces/{ws}/skills").json()
    assert [one["ref"] for one in listed[:3]] == list(BUILTINS)
    assert all(one["enabled"] and not one["problem"] for one in listed[:3])
    assert {one["title"] for one in listed[:3]} == {"3D 场景与建模", "创意画板", "搭工作流"}
    assert {one["source_label"] for one in listed[:3]} == {"Mosael 内置"}
    builtin = [one for one in _skills(ws).values() if one.source == catalog.BUILTIN]
    assert all(not one.editable and one.doc and one.doc.name == one.name for one in builtin), "文件夹名就是 name"


def test_内置技能随后端一起打包() -> None:
    """冻结之后读的是解包目录里的 builtin_skills —— 打包命令得真的把它带上,否则打包版一个内置技能都没有。"""
    build = (REPO / "package.json").read_text(encoding="utf-8")
    command = next(line for line in build.splitlines() if '"build:backend"' in line)
    assert "--add-data app/domain/agent/builtin_skills:app/domain/agent/builtin_skills" in command


def test_系统提示里有技能目录_关掉的不列_都关了整段消失() -> None:
    client = fresh_client()
    ws = _workspace(client)
    text = _system_prompt(ws)
    assert text.startswith("\n\n【技能】") and "use_skill" in text
    assert "- creative-board(创意画板):" in text
    assert text.index("3d-scene") < text.index("creative-board") < text.index("workflow-canvas"), "顺序固定"
    assert "list_board_producers" not in text, "目录只有说明,正文要用 use_skill 读"

    _enable(ws, "creative-board", False)
    assert "creative-board" not in _system_prompt(ws)
    for name in BUILTINS:
        _enable(ws, name, False)
    assert _system_prompt(ws) == "", "没有启用的技能就不留空标题"


def test_目录封顶_每条说明截断_放不下的只列名字() -> None:
    client = fresh_client()
    ws = _workspace(client)
    for index in range(30):
        _create(ws, f"skill-{index:02d}", "长" * 900)
    text = _system_prompt(ws)
    assert len(text) <= runtime.MAX_LISTING_CHARS
    assert "长" * runtime.MAX_LISTED_DESCRIPTION_CHARS not in text, "单条说明截断"
    assert "另有" in text and "skill-29" in text


def test_系统提示瘦身_搬走的做法在内置技能里() -> None:
    """ADR 0040 §5:只在做某件事时才用得上的长段落搬进技能,系统提示里只留「先读哪个技能」。"""
    template = agent_prompt.SYSTEM_PROMPT_TEMPLATE
    assert len(template) < 5000
    for name in BUILTINS:
        assert f'use_skill("{name}")' in template
    board = (catalog.BUILTIN_ROOT / "creative-board" / "SKILL.md").read_text(encoding="utf-8")
    assert "list_board_producers" in board and "时间线格" in board and "空槽" in board
    assert "list_board_producers" not in template
    scene = (catalog.BUILTIN_ROOT / "3d-scene" / "SKILL.md").read_text(encoding="utf-8")
    assert "blender_look" in scene and "view_scene" in scene
    assert "blender_look" not in template


def test_每轮的系统提示带上目录() -> None:
    client = fresh_client()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    from app.db.models import AgentSession

    with SessionLocal() as db:
        text = agent_prompt.build_system_prompt(db, db.get(AgentSession, session["id"]))
    assert "【技能】" in text and "creative-board" in text


# ---------------------------------------------------------------- 两个工具


def test_两个工具都是只读_子智能体拿得到() -> None:
    assert {"use_skill", "read_skill_file"} <= mcp_server.READ_ONLY_TOOLS
    client = fresh_client()
    manifest = {one["name"]: one for one in client.get("/api/agent/tools").json()}
    assert manifest["use_skill"]["read_only"] and not manifest["use_skill"]["confirmation"]
    assert manifest["read_skill_file"]["read_only"]


def test_use_skill_给正文和来源说明_关着的和不存在的说清楚() -> None:
    client = fresh_client()
    ws = _workspace(client)
    result = _tool(client, "use_skill", name="creative-board", workspace_id=ws)["result"]
    assert result["title"] == "创意画板" and "list_board_producers" in result["instructions"]
    assert "不能替代用户的授权" in result["notice"] and "Mosael 内置" in result["notice"]

    _enable(ws, "creative-board", False)
    assert "没有启用" in _tool(client, "use_skill", name="creative-board", workspace_id=ws)["error"]
    assert "没有叫" in _tool(client, "use_skill", name="nope", workspace_id=ws)["error"]


def test_别的工作区的技能读不到() -> None:
    client = fresh_client()
    mine, other = _workspace(client), _workspace(client)
    _create(other, "secret-method", "别处的做法")
    assert "没有叫" in _tool(client, "use_skill", name="secret-method", workspace_id=mine)["error"]


def test_read_skill_file_分段读_二进制只给大小_脚本标明不执行() -> None:
    client = fresh_client()
    ws = _workspace(client)
    long_text = "字" * (catalog.READ_CHUNK_CHARS + 10)
    _create(ws, "refs", files={
        "references/long.md": long_text.encode(), "assets/a.png": b"\x89PNG\x00\x01", "scripts/run.py": b"print(1)",
    })

    listed = _tool(client, "use_skill", name="refs", workspace_id=ws)["result"]
    assert {one["path"] for one in listed["files"]} == {"references/long.md", "assets/a.png", "scripts/run.py"}
    assert "不执行" in listed["files_note"]
    first = _tool(client, "read_skill_file", name="refs", path="references/long.md", workspace_id=ws)["result"]
    assert len(first["content"]) == catalog.READ_CHUNK_CHARS and first["next_offset"] == catalog.READ_CHUNK_CHARS
    rest = _tool(client, "read_skill_file", name="refs", path="references/long.md", offset=first["next_offset"],
                 workspace_id=ws)["result"]
    assert rest["content"] == "字" * 10 and rest["next_offset"] is None
    image = _tool(client, "read_skill_file", name="refs", path="assets/a.png", workspace_id=ws)["result"]
    assert image["binary"] and image["size"] == 6 and "content" not in image
    script = _tool(client, "read_skill_file", name="refs", path="scripts/run.py", workspace_id=ws)["result"]
    assert script["content"] == "print(1)" and "不执行" in script["note"]


@pytest.mark.parametrize("path", ["../../mosael.db", "/etc/passwd", "references/../../x", "a\\b", "escape/secret.txt"])
def test_read_skill_file_出不了技能文件夹(path: str, tmp_path: Path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    _create(ws, "guarded")
    outside = tmp_path / "secret.txt"
    outside.write_text("机密", encoding="utf-8")
    os.symlink(tmp_path, catalog.workspace_dir(ws) / "guarded" / "escape")
    result = _tool(client, "read_skill_file", name="guarded", path=path, workspace_id=ws)
    assert "error" in result and "机密" not in json.dumps(result, ensure_ascii=False)


def test_文件夹里的符号链接技能不认(tmp_path: Path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    real = tmp_path / "evil"
    real.mkdir()
    (real / "SKILL.md").write_text("---\nname: evil\ndescription: x\n---\n", encoding="utf-8")
    catalog.workspace_dir(ws).mkdir(parents=True, exist_ok=True)
    os.symlink(real, catalog.workspace_dir(ws) / "evil")
    assert "evil" not in _skills(ws)


# ---------------------------------------------------------------- 来源与默认开关


def test_扔进文件夹的技能_列出来但关着_读不了的带原因开不了() -> None:
    client = fresh_client()
    ws = _workspace(client)
    folder = catalog.workspace_dir(ws)
    (folder / "dropped").mkdir(parents=True)
    (folder / "dropped" / "SKILL.md").write_text("---\nname: dropped\ndescription: 别人给的\n---\n正文\n", encoding="utf-8")
    (folder / "broken").mkdir()
    (folder / "broken" / "SKILL.md").write_text("---\nname: other-name\ndescription: x\n---\n", encoding="utf-8")
    skills = _skills(ws)
    assert not skills["dropped"].enabled and skills["dropped"].origin == "folder"
    assert "dropped" not in _system_prompt(ws), "没看过全文的不进系统提示"
    assert skills["broken"].problem
    with pytest.raises(catalog.SkillDomainError):
        _enable(ws, "broken", True)
    _enable(ws, "dropped", True)
    assert "dropped" in _system_prompt(ws)


def test_工作区技能不能占内置的名字() -> None:
    client = fresh_client()
    ws = _workspace(client)
    with pytest.raises(catalog.SkillDomainError) as caught:
        _create(ws, "creative-board")
    assert caught.value.key == "skillErr_reservedName"


def test_插件的技能带前缀_默认关_开了才进目录(tmp_path: Path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    root = tmp_path / "dev.example.tips"
    (root / "skills" / "tips").mkdir(parents=True)
    (root / "skills" / "tips" / "SKILL.md").write_text(
        "---\nname: tips\ndescription: 插件带的做法\nmetadata:\n  mosael-title: 小窍门\n---\n正文\n", encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.example.tips", name="Tips", version="1.0.0",
                             manifest={"id": "dev.example.tips", "name": "Tips", "version": "1.0.0", "manifest_version": 7,
                                       "runtime": {"kind": "process", "entry": "m.py"}, PATH_KEY: str(root)}))
        db.commit()
    tip = _skills(ws)["dev.example.tips:tips"]
    assert tip.source == "plugin" and not tip.enabled and not tip.editable
    assert catalog.source_label(tip) == "插件「Tips」"
    assert "dev.example.tips:tips" not in _system_prompt(ws)
    _enable(ws, "dev.example.tips:tips", True)
    assert "- dev.example.tips:tips(小窍门):插件带的做法" in _system_prompt(ws)
    assert _tool(client, "use_skill", name="dev.example.tips:tips", workspace_id=ws)["result"]["instructions"] == "正文\n"


def test_删工作区连技能文件夹一起删() -> None:
    client = fresh_client()
    ws = _workspace(client)
    _create(ws, "gone")
    assert catalog.workspace_dir(ws).exists()
    assert client.delete(f"/api/workspaces/{ws}").status_code == 204
    assert not catalog.workspace_dir(ws).exists()


def test_文件夹没了的索引行在列出设置页时清掉() -> None:
    import shutil

    client = fresh_client()
    ws = _workspace(client)
    _create(ws, "vanishing")
    shutil.rmtree(catalog.workspace_dir(ws) / "vanishing")
    client.get(f"/api/workspaces/{ws}/skills")
    from app.db.models import AgentSkill

    with SessionLocal() as db:
        assert not db.query(AgentSkill).filter(AgentSkill.workspace_id == ws, AgentSkill.name == "vanishing").count()


# ---------------------------------------------------------------- 「/」点名


def _configured() -> None:
    with SessionLocal() as db:
        add_provider(db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
                     api_key="k", model="m", capability_ids=["chat"])
        db.commit()


def test_斜杠点名的技能全文挂到这一轮_落库带着名字(monkeypatch) -> None:
    seen: dict = {}

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, on_delta=None, **_):
        seen["prompt"] = prompt
        return TurnResult(text="好")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)
    client = fresh_client()
    _configured()
    ws = _workspace(client)
    _create(ws, "ads", "带货", "## 三段卖点\n先看商品图\n", title="做带货短视频")
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    sent = client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "做一条", "skills": ["ads", "nope"]})
    assert sent.status_code == 200, sent.text
    assert sent.json()["payload"]["skills"] == ["ads", "nope"]
    assert host.wait_for_idle_turns()
    assert "【用户点名用技能:ads】" in seen["prompt"] and "先看商品图" in seen["prompt"]
    assert "不能替代用户的授权" in seen["prompt"]
    assert "「nope」现在用不了" in seen["prompt"]
    assert seen["prompt"].endswith("做一条"), "用户那句话原样在最后"
    too_many = client.post(f"/api/agent/sessions/{session['id']}/messages",
                           json={"content": "x", "skills": ["a", "b", "c", "d"]})
    assert too_many.status_code == 422


# ---------------------------------------------------------------- YAML 子集对着 PyYAML


@pytest.mark.parametrize(
    "head",
    [
        "name: a\ndescription: plain text here\n",
        "name: a\ndescription: >-\n  folded line one\n  line two\n\n  para\n",
        "name: a\ndescription: |\n  keep\n   indented\n  end\n",
        "name: a\ndescription: \"esc \\\" \\\\ \\n \\t \\u4e2d\"\n",
        "name: a\ndescription: 'single ''q'' here'\n",
        "name: a\ndescription: \"multi\n  line\n\n  quoted\"\n",
        "name: a\nmetadata:\n  author: x\n  version: \"1.0\"\n  mosael-title: 中文\n",
        "name: a\nallowed-tools: [Read, \"Bash(git:*)\", Grep]\n",
        "name: a\nallowed-tools:\n  - Read\n  - Grep\n",
        "name: a\nhooks:\n  - matcher: Bash\n    command: echo hi\n  - matcher: Edit\n",
        "name: a # comment\ndescription: x\n# whole-line comment\nlicense: MIT\n",
        "name: a\ndescription: plain that\n  continues on\n  three lines\n",
    ],
)
def test_YAML子集读出来和PyYAML一样(head: str) -> None:
    import yaml

    from mosael_formats.agent_skill import load_frontmatter

    def as_strings(value):
        if isinstance(value, dict):
            return {str(key): as_strings(item) for key, item in value.items()}
        if isinstance(value, list):
            return [as_strings(item) for item in value]
        return "" if value is None else str(value)

    ours, _ = load_frontmatter(head)
    assert ours == as_strings(yaml.safe_load(head))


def test_计时不出问题() -> None:
    """列技能每轮都要做一遍:几十个技能也该是毫秒级(解析按修改时间缓存)。"""
    client = fresh_client()
    ws = _workspace(client)
    for index in range(20):
        _create(ws, f"fast-{index:02d}")
    _system_prompt(ws)
    started = time.perf_counter()
    for _ in range(10):
        _system_prompt(ws)
    assert (time.perf_counter() - started) / 10 < 0.2
    assert settings.data_dir in catalog.workspace_dir(ws).parents

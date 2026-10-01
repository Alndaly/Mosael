"""插件数组里每一项是一块结构(Manim 讲解视频的「讲解步骤」):节点表单一项一张卡,按每一项声明的几格填;
那几格的名字和顶层字段一样跟着界面语言走;表单存的文字由运行时按 input_schema 逐格转回数、布尔。

用户截图:「讲解步骤」是一个 JSON 框,框里一个字面的 `""`;同一张表单里「副标题」「讲解步骤」「要点回顾」
显示成 Subtitle / Steps / Summary。后者查下来不在宿主的翻译路径上 —— 那一版装着的清单里这几格**没写 title**
(Manim 0.3.1 才补上,见 995f4064),宿主只能拿键名兜底。所以这里把「写了双语 title 的,表单上就按界面语言叫」
钉在请求的语言上(Accept-Language)、钉在仓库里的每一份清单上,嵌套的格子也算。

装一个真的进程插件跑,不把 invoke / 执行器换掉。
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from typing import Any

from app.core.db import SessionLocal
from app.core.i18n import set_current_locale
from app.db.models import Job, PluginInstance, PluginPackage
from app.domain.plugins.manifest import parse, text_of
from app.domain.plugins.nodes import node_meta
from app.domain.plugins.tools import refresh_tools
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.node_catalog import describe_node_types
from tests.util import fresh_client, user_id

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "dev.test.lesson"
ENTRY = """
    import json, sys
    request = json.loads(sys.stdin.read())
    # 原样写成一段 JSON 文字交回:任务结果里的上下文会把深层的结构摘要掉,文字不会
    print(json.dumps({"ok": True, "output": {"got": json.dumps(request["input"], ensure_ascii=False)}}))
"""


def _zh_en(zh: str, en: str) -> dict[str, str]:
    return {"zh": zh, "en": en}


STEP = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "title": _zh_en("标题", "Title"), "description": _zh_en("这一步的标题。", "Step title.")},
        "narration": {"type": "string", "title": _zh_en("旁白", "Narration"), "x-multiline": True},
        "bullets": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "title": _zh_en("要点", "Bullet points")},
        "plot": {
            "type": "object",
            "title": _zh_en("函数图像", "Function plot"),
            "properties": {
                "expression": {"type": "string", "title": _zh_en("算式", "Expression")},
                "x_min": {"type": "number", "title": _zh_en("x 最小值", "x min")},
                "deep": {"type": "object", "properties": {"a": {"type": "string"}}},
            },
            "required": ["expression"],
        },
        "theme": {"type": "string", "enum": ["dark", "light"]},
        "show": {"type": "boolean"},
        "seconds": {"type": "number", "title": _zh_en("时长(秒)", "Duration (s)")},
        "free": {"type": "object"},
    },
    "required": ["title"],
}
TOOL = {
    "name": "lesson",
    "label": _zh_en("讲一课", "Teach a lesson"),
    "input_schema": {"type": "object", "properties": {
        "subtitle": {"type": "string", "title": _zh_en("副标题", "Subtitle"), "description": _zh_en("一句话。", "One line.")},
        "steps": {"type": "array", "items": STEP, "minItems": 1, "maxItems": 20, "title": _zh_en("讲解步骤", "Steps")},
        "summary": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "title": _zh_en("要点回顾", "Summary")},
        "blobs": {"type": "array", "items": {"type": "object"}},
    }, "required": ["steps"]},
    "node": {"outputs": ["got"]},
}


def _manifest(plugin_dir: Path) -> dict[str, Any]:
    return {"id": PACKAGE, "name": _zh_en("讲课", "Lessons"), "version": "0.1.0", "default_locale": "zh",
            "runtime": {"kind": "process", "entry": "main.py"},
            "tools": {"expose": "all", "declare": [TOOL]}, "_path": str(plugin_dir)}


def _install(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "lesson"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="讲课", version="0.1.0", manifest=_manifest(plugin_dir)))
        db.flush()
        instance = PluginInstance(package_id=PACKAGE, name="讲课", enabled=True, owner_user_id=user_id())
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()


def _config(locale: str) -> dict[str, Any]:
    set_current_locale(locale)
    tool = parse(_manifest(Path("/tmp/lesson")), "x").declared_tools[0]
    return describe_node_types({"p": node_meta(tool)}, locale)[0]["config"]


# ---------- 表单 ----------


def test_每一项是一块结构的数组_一项一张卡_按声明的几格填() -> None:
    steps = _config("zh")["steps"]
    assert steps["type"] == "list" and steps["editor"] == "items"
    assert (steps["min_items"], steps["max_items"]) == (1, 20)
    fields = steps["fields"]
    assert fields["title"] == {"type": "text", "required": True, "label": "标题", "description": "这一步的标题。"}
    assert fields["narration"]["type"] == "text" and fields["narration"]["multiline"] is True
    assert fields["bullets"] == {"type": "list", "max_items": 6, "label": "要点"}
    assert fields["seconds"]["type"] == "number"
    # 下拉:枚举照原值;开关给「是 / 否」,名字按语言翻(和顶层同一套 option_labels)
    assert fields["theme"]["options"] == ["dark", "light"]
    assert fields["show"]["options"] == ["true", "false"] and fields["show"]["option_labels"]["true"] == "是"
    # 再往里一层的对象照样摊开;第三层、没写 properties 的,一个 JSON 小框
    plot = fields["plot"]
    assert plot["type"] == "object" and plot["editor"] == "fields" and plot["label"] == "函数图像"
    assert plot["fields"]["expression"] == {"type": "text", "required": True, "label": "算式"}
    assert plot["fields"]["deep"]["editor"] == "json"
    assert fields["free"] == {"type": "object", "editor": "json", "label": "Free"}
    # 一串字符串:一行一项,最多几项也带上
    assert _config("zh")["summary"]["max_items"] == 6 and "editor" not in _config("zh")["summary"]
    # 每一项是对象、却说不清有哪几格的:才退回写数组的 JSON 框
    assert _config("zh")["blobs"]["editor"] == "json" and "fields" not in _config("zh")["blobs"]


def test_字段名跟着请求的语言走_一项里的那几格也是(tmp_path) -> None:
    client = fresh_client()
    _install(tmp_path)

    def config(language: str) -> dict[str, Any]:
        rows = client.get("/api/workflows/node-types", headers={"Accept-Language": language}).json()
        return next(row for row in rows if row["type"] == f"plugin.{PACKAGE}.lesson")["config"]

    zh, en = config("zh-CN"), config("en-US")
    assert [zh[key]["label"] for key in ("subtitle", "steps", "summary")] == ["副标题", "讲解步骤", "要点回顾"]
    assert [en[key]["label"] for key in ("subtitle", "steps", "summary")] == ["Subtitle", "Steps", "Summary"]
    assert zh["subtitle"]["description"] == "一句话。" and en["subtitle"]["description"] == "One line."
    assert zh["steps"]["fields"]["title"]["label"] == "标题" and en["steps"]["fields"]["title"]["label"] == "Title"
    assert zh["steps"]["fields"]["plot"]["fields"]["x_min"]["label"] == "x 最小值"
    assert en["steps"]["fields"]["plot"]["fields"]["x_min"]["label"] == "x min"


def _titled(properties: dict[str, Any], config: dict[str, Any], locale: str, where: str) -> list[str]:
    """清单里写了 title 的每一格(含一项里、对象里嵌着的),表单上叫的是不是那种语言的 title。→ 对不上的。"""
    wrong: list[str] = []
    for key, spec in properties.items():
        field = config.get(key) or {}
        if spec.get("title") and field.get("label") != text_of(spec["title"], locale):
            wrong.append(f"{where}{key}: {field.get('label')!r}")
        items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        nested = items.get("properties") if spec.get("type") == "array" else spec.get("properties")
        if isinstance(nested, dict) and isinstance(field.get("fields"), dict):
            wrong += _titled(nested, field["fields"], locale, f"{where}{key}.")
    return wrong


def test_仓库里的插件_节点表单上每一格都按界面语言叫() -> None:
    """Manim 讲解视频那张表单上中英混杂(Subtitle / Steps / Summary)是装着的旧清单没写 title;仓库里的九份清单
    都写了(mosael-formats 的棘轮),这里钉的是宿主这一侧:写了的,节点表单上一格不差地按界面语言叫,嵌套的也是。"""
    wrong: list[str] = []
    checked = 0
    paths = sorted((ROOT / "plugins").glob("*/*/mosael.plugin.json"))
    assert len(paths) >= 9
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for locale in ("zh", "en"):
            set_current_locale(locale)
            for tool in parse(raw, str(path)).declared_tools:
                config = describe_node_types({"p": node_meta(tool)}, locale)[0]["config"]
                original = next(one for one in raw["tools"]["declare"] if one["name"] == tool["name"])
                properties = (original.get("input_schema") or {}).get("properties") or {}
                wrong += _titled(properties, config, locale, f"{path.parent.name} · {tool['name']} [{locale}]: ")
                checked += len(properties)
    assert checked > 100
    assert wrong == [], "这些格子在表单上没按界面语言叫:\n" + "\n".join(wrong)


# ---------- 运行时 ----------


def _run(ws: str, config: dict[str, Any]) -> tuple[str, dict, str | None]:
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}},
                       {"id": "l", "type": f"plugin.{PACKAGE}.lesson", "config": config}],
             "edges": [{"id": "e1", "source": "start", "target": "l"}]}
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="讲课", graph=graph, created_by=user_id())
        db.commit()
        job_id = start_workflow_job(db, workflow, created_by=user_id()).id
        db.commit()  # 测试是入口:任务在提交之后才派发(jobs.dispatch_job)
    for _ in range(200):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job.status, job.result or {}, job.error
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def test_卡片里存的文字_交给插件前按每一格的声明转回来(tmp_path) -> None:
    """表单每一格只存文字(前端 ItemsField):时长、x 最小值是数,开关是布尔,要点是一串;数 / 布尔格的空文字当没填。
    声明之外的格子原样交过去。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path)
    status, result, error = _run(ws, {"steps": [
        {"title": "勾股定理", "seconds": "4.5", "show": "false", "bullets": ["a", "", "b"],
         "plot": {"expression": "x^2", "x_min": "-3", "deep": {"a": "1"}}, "extra": "原样"},
        {"title": "第二步", "seconds": "", "plot": {"x_min": " "}},
    ]})
    assert status == "succeeded", error
    assert json.loads(result["context"]["l"]["got"])["steps"] == [
        {"title": "勾股定理", "seconds": 4.5, "show": False, "bullets": ["a", "b"],
         "plot": {"expression": "x^2", "x_min": -3, "deep": {"a": "1"}}, "extra": "原样"},
        {"title": "第二步", "plot": {}},
    ]


def test_一串结构的格子是空串_当没填(tmp_path) -> None:
    """接上游再断开,那一格存的是 `""`(前端 withDataInputBound 清字面量的写法)。运行时当没填 —— 去掉这一格,
    不交一个 `""` 给要数组的插件;表单上按空列表显示(前端 ItemsField / JsonField)。所以库里存着 `""` 的数组格
    不需要迁移。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path)
    status, result, error = _run(ws, {"steps": [{"title": "一"}], "summary": "", "blobs": ""})
    assert status == "succeeded", error
    assert json.loads(result["context"]["l"]["got"]) == {"steps": [{"title": "一"}]}

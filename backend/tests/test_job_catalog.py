"""任务种类目录(ADR-0018)。

1. 代码里每个 `create_job(kind=...)` 的种类都在目录里 —— 漏了,任务中心上它就叫「任务」,
   做完要不要说、刷新什么也只能猜;
2. 定时任务能排的种类也都在目录里;
3. 目录里的每一条都有两种语言的名字,指向的页面前端确实有;
4. 接口按请求方的语言发下去。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.domain.jobs.catalog import FALLBACK_LABEL_KEY, JOB_KINDS
from tests.util import fresh_client

APP = Path(__file__).resolve().parents[1] / "app"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """模块级 `NAME = "字面量"`。种类的写法有两种:当场写死,或者提成常量再引用。

    第二种此前在扫描里**等于不存在** —— `kind=JOB_KIND` 是个 Name,`isinstance(..., ast.Constant)`
    放它过去,于是那个种类既不用进目录、也不会被「目录里没有用不到的种类」抓到。拆镜头那个
    `shot_breakdown` 就是这么漏的:它在代码里建任务,目录里却没有对应的一行。
    """
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


def _kind_of(node: ast.Call, strings: dict[str, str]) -> str:
    for keyword in node.keywords:
        if keyword.arg != "kind":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Name):
            return strings.get(value.id, "")
    return ""


def _created_kinds() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        strings = _module_strings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "create_job"):
                continue
            kind = _kind_of(node, strings)
            if kind:
                found[kind] = f"{path.relative_to(APP)}:{node.lineno}"
    return found


def test_代码里建的每种任务都在目录里() -> None:
    created = _created_kinds()
    assert len(created) >= 10, "扫描没扫到东西,多半是 create_job 改了名字"
    missing = {kind: where for kind, where in created.items() if kind not in JOB_KINDS}
    assert not missing, f"这些任务种类不在 app/domain/jobs/catalog.py 里:{missing}"


def test_目录里没有用不到的种类() -> None:
    """前端那张表曾列着一个后端从不创建的 `scheduled`。"""
    from app.domain.scheduler.executors import SCHEDULED_EXECUTORS as SCHEDULABLE_KINDS

    used = set(_created_kinds()) | set(SCHEDULABLE_KINDS)
    assert set(JOB_KINDS) <= used, f"没人创建的种类:{set(JOB_KINDS) - used}"


def test_定时任务能排的种类都在目录里() -> None:
    from app.domain.scheduler.executors import SCHEDULED_EXECUTORS as SCHEDULABLE_KINDS

    assert set(SCHEDULABLE_KINDS) <= set(JOB_KINDS)


def test_名字齐全_页面存在() -> None:
    from app.core.i18n import MESSAGES
    from mosael_formats.i18n import LOCALES

    for key in [entry.label_key for entry in JOB_KINDS.values()] + [FALLBACK_LABEL_KEY]:
        assert key in MESSAGES and all(MESSAGES[key].get(locale) for locale in LOCALES), key
    nav = (FRONTEND / "components" / "layout" / "navLabels.ts").read_text(encoding="utf-8")
    for entry in JOB_KINDS.values():
        if entry.view:
            assert f'"{entry.view}"' in nav, f"{entry.kind} 指向的页面 {entry.view} 前端没有"
        assert (entry.view is None) <= (entry.record_field is None), entry.kind


def test_前端每种任务都有图标() -> None:
    icons = (FRONTEND / "components" / "jobs" / "jobKinds.tsx").read_text(encoding="utf-8")
    block = icons.split("JOB_KIND_ICONS", 1)[1].split("};", 1)[0]
    declared = set(re.findall(r"^\s*([a-z_]+):", block, re.M))
    assert declared == set(JOB_KINDS), {"缺图标": set(JOB_KINDS) - declared, "多余": declared - set(JOB_KINDS)}


def test_接口按语言发下去() -> None:
    client = fresh_client()
    zh = client.get("/api/jobs/kinds", headers={"Accept-Language": "zh-CN"}).json()
    en = client.get("/api/jobs/kinds", headers={"Accept-Language": "en-US"}).json()
    by_kind = {item["kind"]: item for item in zh["kinds"]}
    assert by_kind["proxy"]["announce"] == "failures"
    assert by_kind["workflow"] == {
        "kind": "workflow", "label": "工作流", "announce": "always",
        "affects": ["assets", "sequences", "workflows"], "view": "workflows", "record_field": "workflow_id",
    }
    assert {item["kind"]: item["label"] for item in en["kinds"]}["tts"] == "Speech"
    assert zh["fallback"]["label"] == "任务" and en["fallback"]["label"] == "Task"

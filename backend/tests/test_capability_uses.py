"""「用在哪」现算(ADR 0032 §4):插件页、设置页列出一项宿主能力用在哪 —— 不手写。

此前插件页上 MinerU 下面那行「设置 / 重新解析 / 工作流 / 智能体」是写死的文案(用户截图:「为何这个能力的
列表不是动态的」)。现在:宿主界面入口各自登记,工作流节点按字段声明扫、智能体工具按工具声明扫。
"""

from __future__ import annotations

import pytest

import app.main  # noqa: F401 —— 组装根:登记能力表和「用在哪」
from app.core.i18n import MESSAGES, t
from app.domain import capabilities


def _rendered(name: str) -> list[tuple[str, str]]:
    return [(use.kind, t(use.label["__key"], "zh", **{k: (t(v["__key"], "zh") if isinstance(v, dict) else v)
                                                       for k, v in use.label["params"].items()}))
            for use in capabilities.uses_of(name)]


def test_文档解析用在哪_设置_文档详情_工作流节点_智能体工具() -> None:
    uses = _rendered("document_parse")
    kinds = [kind for kind, _ in uses]
    assert kinds[0] == "app" and "设成默认" in uses[0][1]
    assert any(kind == "app" and "重新解析" in text for kind, text in uses)
    assert any(kind == "workflow" and "文档转 Markdown" in text and "解析方式" in text for kind, text in uses)
    assert any(kind == "agent" and "reparse_document" in text for kind, text in uses)


def test_新节点声明了_providers_字段就自动出现_不用登记(monkeypatch) -> None:
    from app.domain import workflows

    monkeypatch.setitem(workflows.NODE_TYPES, "demo_denoise", {
        "label": "wfNode_document_to_markdown",
        "config": {"engine": {"type": "string", "options_from": "providers.document_parse", "label": "wfField_parser"}},
    })
    assert sum(1 for kind, _ in _rendered("document_parse") if kind == "workflow") == 2


def test_通用选项来源_认得登记过的能力_认不出的说清楚() -> None:
    from app.domain.workflows.field_options import FieldOptionsError, OptionContext, field_options

    ctx = OptionContext(workspace_id="w", user_id=None, parent="", locale="zh")
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        local = field_options(db, "providers.document_parse", ctx)
        assert [one["value"] for one in local] == ["builtin:local"]
        with pytest.raises(FieldOptionsError):
            field_options(db, "providers.no_such_capability", ctx)
    assert "capUse_workflowField" in MESSAGES


def test_插件能写的每一项能力都叫得出名字_说得出用在哪() -> None:
    """插件市场按能力筛、插件页说它替宿主做什么,都照这一份词表 —— 此前前端手写了两项(素材外链、文档解析),
    别的能力在市场里只显示原词。"""
    from app.domain.plugins.manifest import CLAIMED_CAPABILITIES
    from tests.util import fresh_client

    client = fresh_client()
    terms = {one["name"]: one for one in client.get("/api/plugins/capabilities").json()}
    assert set(CLAIMED_CAPABILITIES) | {"public_url"} <= set(terms), "清单里能写的词,每一个都要在词表里"
    for name, term in terms.items():
        assert term["label"] and term["label"] != name, f"{name} 没有给人看的名字"
        assert term["used_by"], f"{name} 说不出装上之后用在哪"
    speech = [use["label"] for use in terms["speech"]["used_by"]]
    assert not any("设成默认" in label for label in speech), "配音没有默认,不该叫人去设置里设成默认"

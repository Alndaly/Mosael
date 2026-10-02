"""面向用户的节点说明和占位里**不摆模板写法**(`{{…}}`)。

引用在界面上是「节点标题 · 输出 · 子路径」的标签(前端 nodeForms/RefToken):人从下拉里挑、在编辑器里敲 @ 插,
从来不用手写 `{{节点.输出}}`。可节点说明里此前摆着「如 {{llm-1.text}}」「子流程内用 {{loop.item}}」,用户照着
屏幕上的标签找不到对应关系,还以为要手敲这串 —— 用户明确不想再在界面上看到这种写法。

管的是界面上出现的那几样:节点名和说明、字段名和说明、选项名、占位(字段的默认值)、输出名,以及节点目录那张
文案表。给智能体看的写法不在这里 —— 它在智能体自己的工具说明和系统提示里(mcp_server 的 edit_workflow、
domain/workflows/ai_edit)。前端界面文案表同一条见 frontend/src/app/messages.noTemplateSyntax.test.ts。
"""

from __future__ import annotations

RATCHET = True

from collections.abc import Iterator

from app.core.messages.node_catalog import MESSAGES as NODE_CATALOG_MESSAGES
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.node_catalog import describe_node_types

#: 字段声明里会显示出来的几格(default 是输入框的占位)。
SHOWN_SPEC_KEYS = ("label", "description", "default", "option_labels")


def _texts(value: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, one in value.items():
            yield from _texts(one, f"{path}.{key}")
    elif isinstance(value, list):
        for index, one in enumerate(value):
            yield from _texts(one, f"{path}[{index}]")


def test_节点目录里面向用户的说明和占位没有模板写法() -> None:
    offenders: list[str] = []
    for locale in ("zh", "en"):
        for item in describe_node_types(NODE_TYPES, locale):
            for key in ("label", "description", "output_labels"):
                offenders += [f"{locale} {at}" for at, text in _texts(item.get(key), f"{item['type']}.{key}") if "{{" in text]
            for field, spec in item["config"].items():
                for key in SHOWN_SPEC_KEYS:
                    where = f"{item['type']}.{field}.{key}"
                    offenders += [f"{locale} {at}" for at, text in _texts(spec.get(key), where) if "{{" in text]
    assert offenders == [], "这些面向用户的说明里还摆着模板写法:\n" + "\n".join(offenders)


def test_节点目录的文案表没有模板写法() -> None:
    offenders = [
        f"{key}.{locale}" for key, entry in NODE_CATALOG_MESSAGES.items() for locale, text in entry.items() if "{{" in text
    ]
    assert offenders == [], offenders

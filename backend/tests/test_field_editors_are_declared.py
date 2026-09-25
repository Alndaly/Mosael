"""字段用哪种专用控件,由**字段声明**点名(`editor`),不由界面按「节点类型 + 字段名」认。

笔记读取节点的 note_id 此前就是这么被认出来的:检查器里写着 `node.type === "note_read" &&
key === "note_id"`。那是一张手抄表 —— 插件节点永远进不去,改个字段名也不会有任何东西报错。
"""

from __future__ import annotations

from app.domain.workflows import NODE_TYPES
from tests.util import fresh_client

RATCHET = True

#: 界面认得的控件名(frontend/src/features/workflows/WorkflowsView.tsx 的 renderField)。
#: 在这里多一个名字,界面那边就要多一个分支 —— 否则那个字段会悄悄退回普通输入框。
KNOWN_EDITORS = {"map", "json", "scene_models", "note_ref"}


def test_笔记读取的_note_id_声明用笔记选择器() -> None:
    rows = {row["type"]: row for row in fresh_client().get("/api/workflows/node-types").json()}
    assert rows["note_read"]["config"]["note_id"]["editor"] == "note_ref"


def test_声明的控件界面都认得() -> None:
    declared = {
        str(spec["editor"])
        for meta in NODE_TYPES.values()
        for spec in meta["config"].values()
        if isinstance(spec, dict) and spec.get("editor")
    }
    assert declared <= KNOWN_EDITORS, declared - KNOWN_EDITORS

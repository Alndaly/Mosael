"""字段用哪种专用控件,由**字段声明**点名(`editor`),不由界面按「节点类型 + 字段名」认。

笔记读取节点的 note_id 此前就是这么被认出来的:检查器里写着 `node.type === "note_read" &&
key === "note_id"`。那是一张手抄表 —— 插件节点永远进不去,改个字段名也不会有任何东西报错。
"""

from __future__ import annotations

from app.domain.workflows import NODE_TYPES
from tests.util import fresh_client

RATCHET = True

#: 界面认得的控件名(frontend/src/features/nodeForms/NodeConfigForm.tsx 的 renderField)。
#: 在这里多一个名字,界面那边就要多一个分支 —— 否则那个字段会悄悄退回普通输入框。
#: start_params:开始节点的启动参数(一行一个:名字、默认值、必填),见 StartParamsField。
#: asset_grid:一串图片素材的紧凑格子(从素材库多选 + 本地上传 + 拖动排序),见 AssetGridField。
#: publish_options:发布节点的平台选项 —— 按所选账号的平台把发布页那一排控件画出来,见 PublishOptionsField。
KNOWN_EDITORS = {
    "map", "json", "scene_models", "note_ref", "id_list", "items", "start_params", "asset_grid",
    "publish_options",
}


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

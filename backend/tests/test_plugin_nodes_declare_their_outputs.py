"""我们自己发的插件:节点的输出口说到做到。

没写 `node.outputs` 时,宿主把整份返回装进一个叫 `output` 的口子(见 plugins/nodes.node_meta)。于是:

- 写了 `output_labels` / `output_types` / `board_outputs` 却没写 `outputs` 的,那些名字**全部落空** ——
  Text Toolkit 和 Remotion 都这么写过:标签对着不存在的口子,下游接不到 `{{n1.asset_id}}`,
  画板上是一张大 JSON 便签;
- 交出文件的工具要有一个 `asset` 类型的口子,否则画板认不出它是素材、工作流连不上下一个吃素材的节点。

这条棘轮扫 plugins/examples 与 plugins/bundled 里所有**写死在清单里**的工具。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "plugins"
MANIFESTS = sorted([*ROOT.glob("examples/*/mosael.plugin.json"), *ROOT.glob("bundled/*/mosael.plugin.json")])
#: 交出文件的工具(返回里有 artifact / artifacts)。新加一个交文件的工具就加进来。
PRODUCES_FILES = {
    ("dev.mosael.remotion", "remotion_explainer"), ("dev.mosael.remotion", "remotion_animation"),
    ("dev.mosael.manim", "manim_explainer"), ("dev.mosael.manim", "manim_animation"), ("dev.mosael.manim", "manim_still"),
}


#: 还欠着的:对象存储四家同样只写了 output_labels 没写 outputs。它们在另一处一起改(storage.py 四份字节相同),
#: 改完删掉这一行 —— 这张表只许变短。
NOT_YET = {"dev.mosael.aliyun-oss", "dev.mosael.aws-s3", "dev.mosael.tencent-cos", "dev.mosael.volcengine-tos"}


def _tools() -> list[tuple[str, dict]]:
    out = []
    for path in MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["id"] in NOT_YET:
            continue
        out += [(manifest["id"], tool) for tool in (manifest.get("tools") or {}).get("declare") or []]
    return out


@pytest.mark.parametrize(("package", "tool"), _tools(), ids=lambda value: value if isinstance(value, str) else value["name"])
def test_输出的标签类型和画板点名都对得上口子(package: str, tool: dict) -> None:
    node = tool.get("node") or {}
    outputs = node.get("outputs")
    named = {*(node.get("output_labels") or {}), *(node.get("output_types") or {}), *(node.get("board_outputs") or [])}
    if named:
        assert isinstance(outputs, list) and outputs, f"{package}.{tool['name']} 给 {sorted(named)} 起了名字,却没写 outputs"
        assert named <= set(outputs), f"{package}.{tool['name']}:{sorted(named - set(outputs))} 不是声明过的输出"
    if (package, tool["name"]) in PRODUCES_FILES:
        assert (node.get("output_types") or {}).get("asset_id") == "asset", f"{package}.{tool['name']} 交文件,却没有 asset 口子"

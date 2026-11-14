"""长片和数字人可以超分到 2K / 4K:时间线画布和每段超分按同一张表取尺寸。

## 现场

H3 两遍采样直出 1728×960,模板的时间线写死 1920×1080、导出只降不升 —— ComfyUI 那边就算超分出了 2K,导出也还是
1080p。超分不能放进生成那张图里(整段 2K 画面要 11 GB 内存),所以是每段上时间线前单独一步。

## 钉的是什么

- 配了超分工作流(有 `6.width` / `6.height`)时,第一段和后面每一段都先超分再上时间线,时间线画布读查表的结果;
- 尺寸表按 1080p 等比放大:16:9 的 2K 是 2560×1440、4K 是 3840×2160,宽高都是偶数;
- 没配超分工作流时图和以前一样:没有这几个节点,画布 1920×1080。
"""

from __future__ import annotations

from app.domain.workflows.templates.long_take import long_take_video_graph
from app.domain.workflows.templates.long_talk import long_talk_video_graph
from app.domain.workflows.templates.model_choice import ModelChoice
from app.domain.workflows.templates.upscale import UPSCALE_HEIGHT, UPSCALE_WIDTH, frame_table

UPSCALE = ModelChoice("profile", "plugin:dev.mosael.comfyui", "seedvr2_upscale_batched.json")
CHAT = ModelChoice("chat", "openai", "gpt")
OPEN = ModelChoice("profile", "plugin:dev.mosael.comfyui", "minimax_h3_open.json")
CONTINUE = ModelChoice("profile", "plugin:dev.mosael.comfyui", "minimax_h3_continue.json")


def _nodes(graph: dict) -> dict[str, dict]:
    return {node["id"]: node for node in graph["nodes"]}


def _body(graph: dict, loop_id: str) -> dict[str, dict]:
    return {node["id"]: node for node in _nodes(graph)[loop_id]["config"]["body"]["nodes"]}


def _fed_by(edges: list[dict], target: str, field: str) -> str:
    """`target` 的 `field` 由哪个节点的产出喂进来(规整后引用变成数据边,节点上那一格留空)。"""
    return next(edge["source"] for edge in edges
                if edge.get("kind") == "data" and edge["target"] == target and edge["target_input"] == field)


def test_尺寸表按_1080p_等比放大_宽高是偶数():
    table = frame_table()
    assert table["16:9"]["1440p"] == {"width": 2560, "height": 1440}
    assert table["16:9"]["2160p"] == {"width": 3840, "height": 2160}
    assert table["9:16"]["2160p"] == {"width": 2160, "height": 3840}
    assert all(size["width"] % 2 == 0 and size["height"] % 2 == 0 for sizes in table.values() for size in sizes.values())


def _assert_upscaled(graph: dict) -> None:
    nodes = _nodes(graph)
    assert nodes["video_project"]["config"]["width"] == "{{frame_plan.value.width}}", "画布按选的清晰度来,导出就是这个尺寸"
    assert nodes["start"]["config"]["params"]["output_resolution"] == "1440p"
    opening = nodes["upscale_opening"]["config"]
    assert opening["source_assets"] == ["{{opening.asset_id}}:source_video"]
    assert opening["parameters"] == {UPSCALE_WIDTH: "{{frame_plan.value.width}}", UPSCALE_HEIGHT: "{{frame_plan.value.height}}"}
    assert _fed_by(graph["edges"], "append_opening", "asset_id") == "upscale_opening", "第一段上时间线的是超分后的那一份"
    body = _body(graph, "assemble")
    assert body["upscale"]["config"]["source_assets"] == ["{{loop.item}}:source_video"]
    assert _fed_by(_nodes(graph)["assemble"]["config"]["body"]["edges"], "append_segment", "asset_id") == "upscale", "后面每一段也是"


def test_长片配了超分工作流_每段先超分再上时间线():
    _assert_upscaled(long_take_video_graph(chat=CHAT, opening=OPEN, video=CONTINUE, upscale=UPSCALE))


def test_数字人配了超分工作流_每段先超分再上时间线():
    _assert_upscaled(long_talk_video_graph(opening=OPEN, video=CONTINUE, upscale=UPSCALE))


def test_没配超分工作流_图和以前一样():
    for graph in (long_take_video_graph(chat=CHAT, opening=OPEN, video=CONTINUE),
                  long_talk_video_graph(opening=OPEN, video=CONTINUE)):
        nodes = _nodes(graph)
        assert "upscale_opening" not in nodes and "frame_plan" not in nodes
        assert nodes["video_project"]["config"]["width"] == 1920
        assert "upscale" not in _body(graph, "assemble")

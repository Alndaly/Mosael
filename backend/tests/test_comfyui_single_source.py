"""插件内部的「单一份」不变量(`backend/tests/test_comfyui_plugin_agent.py` 的对门)。

**这些不进 `contracts/`**:契约管的是**两份实现必须逐字一致**的语义,而这里管的是**一个运行时内部的重复**。
`contracts/README.md` 的「契约钉不住什么:同一个实现,两个调用方」那一节说的正是这一类 —— 修法不是
「加一条比较两者的测试」,而是**让第二份不存在**,再加一条结构性测试钉住「只有它」。

两件事:

1. **四种上传标记**(`image_upload` / `video_upload` / `audio_upload` / `animated_image_upload`)。
   ComfyUI 给「这个下拉是让人传文件的」打的就是这四种,而它们此前写在三个文件里:`graph.py` 是
   四元组到素材类型的映射、`diagnose.py` 是完整四元组、`convert.py` 是三元组加一个单独的 audio 分支
   (它把「传文件」和「音频节点多一个播放器」分开是对的,只是表本身另抄了一份)。
   三份**已经漂移**:`convert` 那份少了 `audio_upload`。现在全集只有 `graph.UPLOAD_MEDIA_FLAGS` 一处,
   `diagnose` 直接取它,`convert` 因为 `graph` import 着它(不能反向 import)而自带两个名字,由下面钉住关系。

2. **子图能套几层**(`MAX_DEPTH`)。`subgraphs.MAX_DEPTH = 16` 与 `convert._MAX_DEPTH = 32` 此前是
   **两份独立实现量同一件事** —— 而两份值不同时不会有任何报错:`subgraphs` 在 16 层停(画布摘要、应用表单、
   `12:5:3…` 的路径判据都跟着它,ADR 0042 §6),`convert` 走到 32,于是 17 层往里的定义转换照样展开发给
   ComfyUI,而画布上根本叫不出那些节点。现在 `convert.MAX_DEPTH` 就是 `subgraphs.MAX_DEPTH`。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
_MODULES = ("graph", "convert", "diagnose", "canvas", "labels", "subgraphs", "lines", "workflow_library")


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把插件的 `tools/` 挂上 sys.path —— 和 `test_comfyui_plugin_agent.py` 同一个办法。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        yield
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


# --- 一、四种上传标记 -------------------------------------------------------------------------


def test_上传标记只有一份表_三处的并集正好是它(tools: None) -> None:
    import convert
    import diagnose
    import graph

    flags = tuple(graph.UPLOAD_MEDIA_FLAGS)
    assert len(flags) == 4, f"ComfyUI 给的上传标记是四种,这张表里有 {flags}"
    assert tuple(graph.UPLOAD_FLAGS) == flags, "UPLOAD_FLAGS 就是那张表的键,别各排一遍序"

    assert tuple(diagnose._UPLOADS) == flags, (  # noqa: SLF001 — 这一条要的就是那一处
        "diagnose 不是从 graph 取那张表 —— 它又会漂移"
    )

    merged = (*convert._UPLOAD_BUTTON_OPTIONS, convert._AUDIO_UPLOAD)  # noqa: SLF001
    assert set(merged) == set(flags), (
        f"convert 那两处合起来是 {sorted(set(merged))},而全集的表是 {sorted(flags)} —— 又少了一个"
    )
    assert convert._AUDIO_UPLOAD not in convert._UPLOAD_BUTTON_OPTIONS, (  # noqa: SLF001
        "音频那一个应当**只**在 _AUDIO_UPLOAD 里:它在前端是播放器 widget 而不是上传按钮,"
        "两个名字分开写就是为了让这个区别留在代码里"
    )


def test_四种标记各自说的是哪种素材(tools: None) -> None:
    """`graph.UPLOAD_MEDIA_FLAGS` 的值(素材类型)也要对得上:动画图算 image,音频算 audio。"""
    import graph

    assert graph.UPLOAD_MEDIA_FLAGS["animated_image_upload"] == "image"
    assert graph.UPLOAD_MEDIA_FLAGS["audio_upload"] == "audio"
    assert set(graph.UPLOAD_MEDIA_FLAGS.values()) == {"image", "video", "audio"}


def test_读素材的判定真的走那三个分支(tools: None) -> None:
    """结构对上了还要**行为**对上:`_upload_media` / `_uploads` 拿四种标记各问一遍。"""
    import convert
    import graph

    planner = object.__new__(convert._Converter)  # noqa: SLF001 — 只借那个静态方法,不构造整台转换器

    for flag, media in graph.UPLOAD_MEDIA_FLAGS.items():
        definition = ["COMBO", {flag: True}]
        assert graph._upload_media(definition) == media, f"{flag} 该认出 {media}"  # noqa: SLF001
        assert convert._Converter._uploads(planner, definition) is True, f"{flag} 该算「在读文件」"  # noqa: SLF001

    assert graph._upload_media(["COMBO", {"not_a_flag": True}]) == ""  # noqa: SLF001
    assert convert._Converter._uploads(planner, ["COMBO", {"not_a_flag": True}]) is False  # noqa: SLF001


# --- 二、子图能套几层 -------------------------------------------------------------------------


def _nested(levels: int) -> dict:
    """**真嵌套**的图:第 N 层的定义里再带一份 `definitions.subgraphs`(不是平铺在根上)。

    坏文件可能是这样(一个子图里又放了它自己),而「往下走几层」就是这两个 `MAX_DEPTH` 量的事。
    """
    inner: dict[str, Any] = {"id": f"leaf{levels}", "nodes": [{"id": 1, "type": "KSampler", "widgets_values": [1]}], "links": []}
    for depth in range(levels - 1, -1, -1):
        inner = {"id": f"n{depth}", "nodes": [{"id": 7, "type": inner["id"]}],
                 "definitions": {"subgraphs": [inner]}, "links": []}
    return {"nodes": [{"id": 3, "type": inner["id"]}], "links": [],
            "definitions": {"subgraphs": [inner]}, "extra": {}}


def test_子图深度只有一份上限(tools: None) -> None:
    """`convert.MAX_DEPTH` 就是 `subgraphs.MAX_DEPTH`,不是一个恰好也像的数字。"""
    import convert
    import subgraphs

    assert convert.MAX_DEPTH == subgraphs.MAX_DEPTH, (
        "两处上限又分开了 —— 它们量的是同一件事(子图定义往下能走几层)"
    )
    assert subgraphs.MAX_DEPTH == 16, "16 是 ADR 0042 §6 与三处路径判据认下来的那个上限"


@pytest.mark.parametrize("levels", [2, 16, 17, 18, 33, 40])
def test_两份采集在同一个上限上停(levels: int, tools: None) -> None:
    """同一个上限的可执行那一半:**同一张图**,`convert` 采集到的定义和 `subgraphs` 采集到的完全一样。

    这一条在 `convert._MAX_DEPTH = 32` 时是红的(17 层那张图上两者差一份定义)——「不会有任何报错」
    的那类不一致,只有把两份结果摆在一起才看得见。
    """
    import convert
    import subgraphs

    graph = _nested(levels)
    mine = set(convert._Converter(graph, {}, "zh").definitions)  # noqa: SLF001
    theirs = set(subgraphs.definitions(graph))
    assert mine == theirs, (
        f"{levels} 层的图:convert 采集到 {len(mine)} 份定义、subgraphs 采集到 {len(theirs)} 份 —— "
        f"只在 convert 里的:{sorted(mine - theirs)[:5]}"
    )
    assert len(theirs) <= subgraphs.MAX_DEPTH + 1, "采到的定义数不该超过上限加一(根那一份)"

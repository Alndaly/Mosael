"""画板、截取、标记的报错跟着读者的语言走,不是写死的中文。

这些错误走三条路出去:画板路由的 `detail`、智能体编辑画板时的工具返回、截取任务的失败原因。
三条都是「领域给 key + 参数,出口按当时的语言翻」—— 所以这里在领域那一层断言 key 渲染成英文,
再走一次真实接口确认 Accept-Language: en 拿到的是英文。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.i18n import t
from app.domain.boards import BoardDomainError, BoardRevisionConflict, normalize_canvas
from app.domain.boards.ops import apply_board_ops
from app.domain.boards.trim import TrimError, start_trim
from app.domain.markers import MarkerError, normalize_shortcut
from tests.util import fresh_client


def _en(exc: BaseException) -> str:
    return t(exc.key, "en", **exc.params)  # type: ignore[attr-defined]


def test_non_finite_coordinate_names_the_item_in_english() -> None:
    with pytest.raises(BoardDomainError) as info:
        normalize_canvas({"items": [{"id": "a", "kind": "note", "x": float("nan"), "y": 0}], "edges": []})
    assert _en(info.value) == "Board item a: x must be a finite number, but got nan."
    # 中文仍是原句 —— 缺省语言下的读者看到的不变。
    assert str(info.value) == "画板项 a 的 x 必须是有限的数字,收到 nan"


def test_missing_item_id_is_its_own_sentence_not_a_chinese_placeholder() -> None:
    """没给 id 时此前把「(空)」填进句子里 —— 英文界面里会夹着一个中文括号。"""
    with pytest.raises(BoardDomainError) as info:
        apply_board_ops({"items": [], "edges": []}, [{"kind": "set_text", "item_id": "", "text": "x"}])
    assert _en(info.value) == "No board item was given — pass an item id."
    with pytest.raises(BoardDomainError) as info:
        apply_board_ops({"items": [], "edges": []}, [{"kind": "remove_item", "item_id": "ghost"}])
    assert _en(info.value) == "There's no item ghost on this board."


def test_marker_error_keeps_its_key_when_the_board_wraps_it() -> None:
    """画板把标记的错误转手成自己的错误 —— 转手时带着 key,而不是冻成转手那一刻的中文。"""
    canvas = {
        "items": [],
        "edges": [],
        "markers": [
            {"id": "a", "name": "Intro", "x": 0, "y": 0, "shortcut": "Mod+1"},
            {"id": "b", "name": "Outro", "x": 1, "y": 1, "shortcut": "ctrl+1"},
        ],
    }
    with pytest.raises(BoardDomainError) as info:
        normalize_canvas(canvas)
    assert isinstance(info.value.__cause__, MarkerError)
    assert info.value.key == "markerErr_shortcutTaken"
    assert _en(info.value) == "The shortcut Mod+1 is already bound to the marker “Intro”. Pick another key."


def test_marker_shortcut_error_in_english() -> None:
    with pytest.raises(MarkerError) as info:
        normalize_shortcut("Hyper+K")
    assert _en(info.value) == "Unknown modifier key in the shortcut: Hyper"
    # 仍是 ValueError:老的 except 照样接得住。
    assert isinstance(info.value, ValueError)


def test_revision_conflict_keeps_its_numbers() -> None:
    exc = BoardRevisionConflict(3, 5)
    assert (exc.base_revision, exc.current_revision) == (3, 5)
    assert _en(exc).startswith("This board was changed somewhere else (yours is v3, the latest is v5).")


def test_trim_range_error_in_english() -> None:
    asset = SimpleNamespace(kind="video", file_key="k", workspace_id="w", id="a", name="clip")
    with pytest.raises(TrimError) as info:
        start_trim(None, asset=asset, start=5, end=2, created_by=None)  # type: ignore[arg-type]
    assert _en(info.value) == "The end time must be after the start time."
    assert isinstance(info.value, ValueError)


def test_board_route_answers_in_the_readers_language() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": ws}).json()
    bad = {"items": [{"id": "a", "kind": "sticker", "x": 0, "y": 0}], "edges": []}

    en = client.patch(
        f"/api/boards/{board['id']}",
        json={"workspace_id": ws, "base_revision": board["revision"], "canvas": bad},
        headers={"Accept-Language": "en"},
    )
    assert en.status_code == 400
    assert en.json()["detail"] == (
        "Unknown board item type: sticker. Use one of: note, image, video, audio, frame, scene, document, action."
    )

    zh = client.patch(
        f"/api/boards/{board['id']}",
        json={"workspace_id": ws, "base_revision": board["revision"], "canvas": bad},
        headers={"Accept-Language": "zh-CN"},
    )
    assert zh.json()["detail"].startswith("未知的画板项类型:sticker")

    # 冲突那一条是结构化的:数字原样、message 按读者语言。
    client.patch(f"/api/boards/{board['id']}", json={"workspace_id": ws, "base_revision": board["revision"], "name": "v2"})
    stale = client.patch(
        f"/api/boards/{board['id']}",
        json={"workspace_id": ws, "base_revision": 1, "name": "stale"},
        headers={"Accept-Language": "en"},
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert (detail["base_revision"], detail["current_revision"]) == (1, 2)
    assert detail["message"].startswith("This board was changed somewhere else")

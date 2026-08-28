"""创意画板:一张无限画布,用来攒想法。

除了和智能体对话之外的另一条路 —— 对话是线性的,而想法不是。画板让人把碎片摊开、挪动、
连起来,先看见结构再决定做什么。

## 这一层负责什么

**画布的形状**。数据库那边只有一列 JSON(见 db/models.Board),什么算合法的画布由这里说了算。
校验放在领域层而不是路由:画板将来会有第二个入口(智能体往板上贴东西、工作流产出落到板上),
放在路由里就意味着那些入口各自再写一遍,而漏掉的那一遍不会报错 —— 只会存进一张打不开的板。

## 为什么校验得这么紧

存进去的东西下一次是**要渲染**的。一个坐标是字符串、一个 kind 拼错了,前端拿到的是一张
渲染到一半崩掉的画布,而错误发生在几天前的某一次保存里。所以宁可在写入时就拒绝:
拒绝的那一刻用户还知道自己刚做了什么。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Board


class BoardDomainError(ValueError):
    pass


#: 画板上能放什么。
#:
#: `note` 便签(文字)、`image` 图片、`video` 视频、`frame` 分组框(把一堆东西圈起来命名)。
#:
#: 图片和视频**分开两种而不是合成一个 media**:它们在画板上的样子和操作都不同 ——
#: 图片是一张静止的参考,视频要能就地播;而"从这张图生成视频"是图片才有的动作,
#: 反过来"抽一帧"是视频才有的。合成一种的话每处都要先分辨一次它到底是哪个。
ITEM_KINDS = ("note", "image", "video", "frame")

#: 必须指向素材库一份的那几种。空着的话存得下、打开却是个空白框。
_NEEDS_ASSET = ("image", "video")

#: 一个 item 至少要有的东西。坐标必须是数,否则画布渲染不出来。
_REQUIRED = ("id", "kind", "x", "y")

#: 便签的颜色。给一组预设而不是任意色值:随手挑的颜色凑在一起会很难看,而且**颜色要能表达
#: 分类** —— 一组固定的色板才让"黄色是待办、蓝色是参考"这种约定成立。
NOTE_COLORS = ("yellow", "blue", "green", "pink", "purple", "gray")

MAX_ITEMS = 2000
MAX_TEXT_CHARS = 20_000


def _number(value: Any, field: str, item_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoardDomainError(f"画板项 {item_id} 的 {field} 必须是数字,收到 {value!r}")
    return float(value)


def normalize_canvas(raw: Any) -> dict[str, Any]:
    """把外面传进来的画布校验并归一成存得下、读得回的形状。

    宽进严出:少写的字段补默认(新画板、旧版本存的都能读),而**写错的字段一律拒绝** ——
    补一个默认值等于替用户猜,而猜错的表现是他的东西挪了位置或者变了颜色。
    """
    if raw is None:
        return {"items": [], "edges": []}
    if not isinstance(raw, dict):
        raise BoardDomainError("画布必须是一个对象")

    raw_items = raw.get("items") or []
    if not isinstance(raw_items, list):
        raise BoardDomainError("画布的 items 必须是数组")
    if len(raw_items) > MAX_ITEMS:
        raise BoardDomainError(f"一张画板最多 {MAX_ITEMS} 项,收到 {len(raw_items)} 项")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise BoardDomainError("画板项必须是对象")
        for field in _REQUIRED:
            if field not in entry:
                raise BoardDomainError(f"画板项缺少 {field}")
        item_id = str(entry["id"]).strip()
        if not item_id:
            raise BoardDomainError("画板项的 id 不能为空")
        # id 重了的话前端按 id 索引会**默默丢掉一个** —— 用户看到的是"我刚加的东西没了"。
        if item_id in seen:
            raise BoardDomainError(f"画板项 id 重复:{item_id}")
        seen.add(item_id)

        kind = str(entry["kind"]).strip()
        if kind not in ITEM_KINDS:
            raise BoardDomainError(f"未知的画板项类型:{kind};可用的是 {'、'.join(ITEM_KINDS)}")

        item: dict[str, Any] = {
            "id": item_id,
            "kind": kind,
            "x": _number(entry["x"], "x", item_id),
            "y": _number(entry["y"], "y", item_id),
        }
        for field in ("width", "height"):
            if entry.get(field) is not None:
                size = _number(entry[field], field, item_id)
                if size <= 0:
                    raise BoardDomainError(f"画板项 {item_id} 的 {field} 必须大于 0")
                item[field] = size

        text = entry.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise BoardDomainError(f"画板项 {item_id} 的 text 必须是字符串")
            if len(text) > MAX_TEXT_CHARS:
                raise BoardDomainError(f"画板项 {item_id} 的文字超过 {MAX_TEXT_CHARS} 字")
            item["text"] = text

        color = entry.get("color")
        if color is not None:
            if color not in NOTE_COLORS:
                raise BoardDomainError(f"未知的颜色:{color};可用的是 {'、'.join(NOTE_COLORS)}")
            item["color"] = color

        asset_id = entry.get("asset_id")
        if asset_id is not None:
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise BoardDomainError(f"画板项 {item_id} 的 asset_id 不合法")
            item["asset_id"] = asset_id.strip()
        # 没有素材就是一个空白框 —— 存得下、打开却什么都没有,不如当场说。
        if kind in _NEEDS_ASSET and "asset_id" not in item:
            raise BoardDomainError(f"{item_id} 必须指向一份素材")

        items.append(item)

    raw_edges = raw.get("edges") or []
    if not isinstance(raw_edges, list):
        raise BoardDomainError("画布的 edges 必须是数组")
    edges: list[dict[str, Any]] = []
    for entry in raw_edges:
        if not isinstance(entry, dict):
            raise BoardDomainError("连线必须是对象")
        source = str(entry.get("source") or "").strip()
        target = str(entry.get("target") or "").strip()
        # 连到不存在的项上,渲染时是一根悬空的线。存之前就把它挡住。
        if source not in seen or target not in seen:
            raise BoardDomainError(f"连线两端必须都是画板上的项:{source} → {target}")
        edge: dict[str, Any] = {"id": str(entry.get("id") or f"{source}->{target}"), "source": source, "target": target}
        label = entry.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise BoardDomainError("连线的 label 必须是字符串")
            edge["label"] = label[:200]
        edges.append(edge)

    return {"items": items, "edges": edges}


def list_boards(db: Session, workspace_id: str) -> list[Board]:
    return list(
        db.scalars(
            select(Board).where(Board.workspace_id == workspace_id).order_by(Board.updated_at.desc())
        )
    )


def get_board(db: Session, workspace_id: str, board_id: str) -> Board:
    board = db.get(Board, board_id)
    # 按工作区再验一次:拿到别的工作区的 id 也不该读得出来。
    if board is None or board.workspace_id != workspace_id:
        raise BoardDomainError("画板不存在")
    return board


def create_board(db: Session, *, workspace_id: str, name: str, canvas: Any = None) -> Board:
    board = Board(
        workspace_id=workspace_id,
        name=(name or "").strip() or "新画板",
        canvas=normalize_canvas(canvas),
    )
    db.add(board)
    db.commit()
    db.refresh(board)
    return board


def update_board(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    name: str | None = None,
    canvas: Any = None,
) -> Board:
    """改名和改画布是同一个入口,因为它们都是"这张板变了"。

    **两者都可以单独传**:自动保存只发 canvas,重命名只发 name —— 各发各的那一半,
    另一半不该被 None 覆盖掉。
    """
    board = get_board(db, workspace_id, board_id)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BoardDomainError("画板名不能为空")
        board.name = cleaned
    if canvas is not None:
        board.canvas = normalize_canvas(canvas)
    db.commit()
    db.refresh(board)
    return board


def delete_board(db: Session, workspace_id: str, board_id: str) -> None:
    board = get_board(db, workspace_id, board_id)
    db.delete(board)
    db.commit()

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

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Board


logger = logging.getLogger(__name__)


class BoardDomainError(ValueError):
    pass


#: 画板上能放什么。
#:
#: `note` 便签(文字)、`image` 图片、`video` 视频、`audio` 音频、`frame` 分组框(圈起来命名)。
#:
#: 图片和视频**分开两种而不是合成一个 media**:它们在画板上的样子和操作都不同 ——
#: 图片是一张静止的参考,视频要能就地播;而"从这张图生成视频"是图片才有的动作,
#: 反过来"抽一帧"是视频才有的。合成一种的话每处都要先分辨一次它到底是哪个。
ITEM_KINDS = ("note", "image", "video", "audio", "frame")

#: 必须指向素材库一份的那几种。空着的话存得下、打开却是个空白框。
_NEEDS_ASSET = ("image", "video", "audio")

#: 一个 item 至少要有的东西。坐标必须是数,否则画布渲染不出来。
_REQUIRED = ("id", "kind", "x", "y")

#: 便签的颜色。给一组预设而不是任意色值:随手挑的颜色凑在一起会很难看,而且**颜色要能表达
#: 分类** —— 一组固定的色板才让"黄色是待办、蓝色是参考"这种约定成立。
NOTE_COLORS = ("yellow", "blue", "green", "pink", "purple", "gray")

MAX_ITEMS = 2000
MAX_TEXT_CHARS = 20_000
RUN_STATUSES = ("idle", "queued", "running", "succeeded", "failed", "cancelled")


def _number(value: Any, field: str, item_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoardDomainError(f"画板项 {item_id} 的 {field} 必须是数字,收到 {value!r}")
    return float(value)


def _normalize_form(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验并保留**属于节点自己的表单**。

    表单是用户可继续编辑的事实；生成器为了调用供应商临时补上的文件名图例、签名参数等都
    不属于它。这里有意允许不同节点放不同字段，但把 JSON 的基本形状钉住，避免下一次打开
    节点时拿到一个无法渲染的值。
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError(f"画板项 {item_id} 的 form 必须是对象")
    form = dict(value)
    prompt = form.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str):
            raise BoardDomainError(f"画板项 {item_id} 的 form.prompt 必须是字符串")
        if len(prompt) > MAX_TEXT_CHARS:
            raise BoardDomainError(f"画板项 {item_id} 的提示词超过 {MAX_TEXT_CHARS} 字")
    for field in ("provider", "provider_profile_id", "model", "mode", "voice_id"):
        if form.get(field) is not None and not isinstance(form[field], str):
            raise BoardDomainError(f"画板项 {item_id} 的 form.{field} 必须是字符串")
    if form.get("parameters") is not None and not isinstance(form["parameters"], dict):
        raise BoardDomainError(f"画板项 {item_id} 的 form.parameters 必须是对象")
    sources = form.get("source_assets")
    if sources is not None:
        if not isinstance(sources, list) or any(not isinstance(one, dict) for one in sources):
            raise BoardDomainError(f"画板项 {item_id} 的 form.source_assets 必须是对象数组")
        form["source_assets"] = [
            {"asset_id": str(one.get("asset_id") or "").strip(), "role": str(one.get("role") or "").strip()}
            for one in sources
            if str(one.get("asset_id") or "").strip() and str(one.get("role") or "").strip()
        ]
    mentioned = form.get("mentioned_asset_ids")
    if mentioned is not None:
        if not isinstance(mentioned, list):
            raise BoardDomainError(f"画板项 {item_id} 的 form.mentioned_asset_ids 必须是数组")
        form["mentioned_asset_ids"] = [str(one).strip() for one in mentioned if str(one).strip()]
    prompt_document = form.get("prompt_document")
    if prompt_document is not None:
        if not isinstance(prompt_document, dict) or prompt_document.get("type") != "doc":
            raise BoardDomainError(f"画板项 {item_id} 的 form.prompt_document 必须是 TipTap doc 对象")
        if len(json.dumps(prompt_document, ensure_ascii=False)) > MAX_TEXT_CHARS * 8:
            raise BoardDomainError(f"画板项 {item_id} 的 form.prompt_document 过大")
    return form


def _normalize_run(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验节点自己的运行态。终态不允许再携带 job_id，避免 UI 永久转圈。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError(f"画板项 {item_id} 的 run 必须是对象")
    status = str(value.get("status") or "idle").strip()
    if status not in RUN_STATUSES:
        raise BoardDomainError(f"画板项 {item_id} 的 run.status 不合法:{status}")
    run: dict[str, Any] = {"status": status}
    job_id = value.get("job_id")
    if job_id is not None:
        if status not in ("queued", "running"):
            raise BoardDomainError(f"画板项 {item_id} 已结束却仍带有 job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise BoardDomainError(f"画板项 {item_id} 的 run.job_id 不合法")
        run["job_id"] = job_id.strip()
    error = value.get("error")
    if error is not None:
        if not isinstance(error, str):
            raise BoardDomainError(f"画板项 {item_id} 的 run.error 必须是字符串")
        if error.strip():
            run["error"] = error.strip()[:300]
    return run


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
        if "job_id" in entry or "error" in entry:
            raise BoardDomainError(f"画板项 {item_id} 使用了已停用的顶层运行态；请改用 run.status/run.job_id/run.error")

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

        form = _normalize_form(entry.get("form"), item_id)
        if form is not None:
            item["form"] = form

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

        # 分组框「联动拖动」:开着的时候,拖动这个框会把框里的东西一起带走。
        #
        # **存下来而不是每次现开** —— 它是这个框的性质(「这一组是一个整体」),而不是一次
        # 操作的临时状态;重进画板时该还是那样。只有分组框有意义,别的类型给了就是写错了。
        move_children = entry.get("move_children")
        if move_children is not None:
            if not isinstance(move_children, bool):
                raise BoardDomainError(f"画板项 {item_id} 的 move_children 必须是布尔值")
            if kind != "frame":
                raise BoardDomainError(f"只有分组框有 move_children,{kind} 没有")
            item["move_children"] = move_children

        # 正在生成的那一项:还没有素材,但有一个任务在跑。任务落终态时由回执把 asset_id
        # 填回来(见 deliver_generated)。**这是"还没有"和"不该有"的区别** —— 前者要占着位置
        # 让用户看见"这儿在生成",后者才是错误。
        run = _normalize_run(entry.get("run"), item_id)
        if run is not None:
            item["run"] = run

        # **空槽是合法的。** 一个图片/视频项有四种状态,缺一不可:
        #   · 空槽(都没有)   —— 刚放下,底下挂着提示词面板等你写;
        #   · 生成中(run.running) —— 提交了,等回执把 asset_id 填回来;
        #   · 跑挂了(run.failed)  —— 提示词还在,可以改一改再来一次;
        #   · 有产出(有 asset_id)。
        # 前两种此前都被当成错误拒掉了 —— 而"节点本身就是生成单元"这件事,正要从空槽开始。

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
        board.canvas = _keep_arrived_results(board.canvas, normalize_canvas(canvas))
    db.commit()
    db.refresh(board)
    return board


def _keep_arrived_results(stored: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """**客户端不该覆盖它还不知道的产出。**

    这是一个必然的竞态,不是偶发:画板自动保存,而生成是异步的 ——
      t1 客户端存了一份带占位(run 里有 job_id、没 asset_id)的画布;
      t2 任务跑完,回执把 asset_id 填进那一项;
      t3 用户又拖了一下,客户端把**它手上那份**存回来 —— 那份里还是占位。
    产出就这么没了,而且不报错:那一项看着还在转圈,可任务早就结束了。

    所以服务端在这一处做主:一项如果库里已经有 asset_id,而传来的那份还是占位,
    保留库里那个。客户端下一次拉到的就是填好的。
    """
    have = {
        str(item.get("id")): item
        for item in ((stored or {}).get("items") or [])
        if item.get("asset_id") or (item.get("run") or {}).get("status") in ("succeeded", "failed", "cancelled")
    }
    if not have:
        return incoming
    items = []
    for item in incoming["items"]:
        settled = have.get(str(item.get("id")))
        incoming_running = (item.get("run") or {}).get("status") in ("queued", "running")
        if settled and not item.get("asset_id") and settled.get("asset_id"):
            items.append({**item, "asset_id": settled["asset_id"], "run": settled.get("run", {"status": "succeeded"})})
        elif settled and incoming_running and (settled.get("run") or {}).get("status") in (
            "succeeded",
            "failed",
            "cancelled",
        ):
            # 任务结束后的下一次自动保存，客户端手里往往还是提交前的 running 快照。终态必须
            # 赢，否则它会把节点重新写活，界面就永远 loading。
            kept = {**item, "run": settled["run"]}
            # 同步便签写作没有 asset_id 可以充当「结果已到」的证据。服务端已经落下正文和
            # 清空后的表单时，晚到的 running 自动保存不能把三者一起覆盖回旧快照。
            if (settled.get("run") or {}).get("status") == "succeeded" and settled.get("kind") == "note":
                kept["text"] = settled.get("text", "")
                kept["form"] = settled.get("form", {})
            items.append(kept)
        else:
            items.append(item)
    return {**incoming, "items": items}


def delete_board(db: Session, workspace_id: str, board_id: str) -> None:
    board = get_board(db, workspace_id, board_id)
    db.delete(board)
    db.commit()


# ── 在画板上生成 ────────────────────────────────────────────────────────────
#
# 画板是生成能力的**第五个入口**(前四个:AI 工作台、定时任务、工作流节点、智能体)。
# 它不自己实现一遍生成 —— 照样汇进 create_generation_job 那条漏斗,于是描述符校验、
# 能力探测、计量记账、任务中心全都白拿。这一层只回答画板自己的那个问题:
# **产出该落回哪儿**。

#: 回执的种类名。任务落终态时,jobs 那边按这个名字找到下面的 deliver_generated。
RECEIPT_KIND = "board_item"


def receipt_to_item(board_id: str, item_id: str) -> dict[str, Any]:
    """建任务时写进 payload 的那一小块:这次的产出属于哪张板的哪一项。"""
    return {"kind": RECEIPT_KIND, "board_id": board_id, "item_id": item_id}


def place_pending(db: Session, *, workspace_id: str, board_id: str, item: dict[str, Any]) -> Board:
    """把某一项的「正在生成」状态放到画布上,再去起任务。

    **顺序是这样的原因**:生成要几十秒,而用户点完就在看画布。先放一个占位,他立刻看得见
    "这儿在生成";等回执把 asset_id 填回来,占位就地变成图片/视频。反过来(先起任务、
    等成功再放)的话,这几十秒里画布上什么都没有,用户会以为自己没点中。

    **按 id 就地更新,不存在才追加。** 画板上的生成有两个入口:工具条上「放一个空槽去
    生成」是新建一项,而在已有的空槽里写完提示词点生成,那一项**早就在画布上**了 ——
    无脑追加会撞上同 id 的自己,用户只是点了生成,却收到一句「画板项 id 重复」。

    就地更新时**保留它已有的位置和大小**:调用方只知道「它开始生成了」,不知道用户把它
    拖到哪儿、拉多大 —— 拿请求里的默认坐标覆盖,会让节点自己跳回左上角。
    """
    board = get_board(db, workspace_id, board_id)
    canvas = dict(board.canvas or {"items": [], "edges": []})
    items = [dict(one) for one in (canvas.get("items") or [])]

    index = next((i for i, one in enumerate(items) if one.get("id") == item.get("id")), None)
    if index is None:
        items.append(item)
    else:
        #: 位置和大小、表单归画布(用户编辑出来的),状态归这里(任务起来了)。
        keep = {k: v for k, v in item.items() if k not in ("x", "y", "width", "height")}
        merged = {**items[index], **keep}
        #: 四个状态两两互斥 —— 重新生成时旧产出、上一次的失败都让位给这次的占位。
        #: 不清的话,一个项会同时带着 run.running 和 asset_id(画布不知道该画哪个),
        #: 或者一边转圈一边挂着上次的报错(用户以为这次也挂了)。
        merged.pop("asset_id", None)
        items[index] = merged

    board.canvas = normalize_canvas({**canvas, "items": items})
    db.commit()
    db.refresh(board)
    return board


def set_text_write_run(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item_id: str,
    status: str,
    error: str = "",
) -> Board:
    """同步便签写作的运行态也落在节点内；失败时不碰表单，用户可以原样重试。"""
    if status not in ("running", "failed"):
        raise BoardDomainError(f"便签写作状态不合法:{status}")
    board = get_board(db, workspace_id, board_id)
    canvas = dict(board.canvas or {"items": [], "edges": []})
    items = [dict(one) for one in (canvas.get("items") or [])]
    index = next((i for i, one in enumerate(items) if one.get("id") == item_id), None)
    if index is None:
        raise BoardDomainError(f"画板项不存在:{item_id or '(空)'}")
    run = {"status": status}
    if error.strip():
        run["error"] = error.strip()[:300]
    items[index] = {**items[index], "run": run}
    board.canvas = normalize_canvas({**canvas, "items": items})
    db.commit()
    db.refresh(board)
    return board


def write_text(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item_id: str,
    text: str,
    reset_form: bool = False,
    completed_form: dict[str, Any] | None = None,
) -> Board:
    """把一段写好的文字放进某一项。

    **就地改,不新建** —— 调用方要写的那张便签是用户在画布上摆好的,位置、颜色、大小都归他。
    """
    board = get_board(db, workspace_id, board_id)
    canvas = dict(board.canvas or {"items": [], "edges": []})
    items = [dict(one) for one in (canvas.get("items") or [])]
    index = next((i for i, one in enumerate(items) if one.get("id") == item_id), None)
    if index is None:
        raise BoardDomainError(f"画板项不存在:{item_id or '(空)'}")
    updated = {**items[index], "text": text}
    if reset_form:
        form = dict(completed_form if completed_form is not None else updated.get("form") or {})
        form["prompt"] = ""
        form["mentioned_asset_ids"] = []
        form.pop("prompt_document", None)
        updated["form"] = form
        updated["run"] = {"status": "succeeded"}
    items[index] = updated
    board.canvas = normalize_canvas({**canvas, "items": items})
    db.commit()
    db.refresh(board)
    return board


def deliver_generated(db: Session, job: Any, receipt: dict[str, Any]) -> None:
    """任务落终态 → 把产出填进画板上那一项。

    **成功和失败都要处理。** 只处理成功的话,失败时画布上会永远留着一个转圈的占位 ——
    用户不知道它是还在跑还是已经死了,而这两件事的下一步完全不同。失败就把占位摘掉,
    任务中心那条失败记录才是讲原因的地方。

    **一次可能出多张。** 图像接口的 n 选了几就回几张:第一张落进占位,其余的挨着它往右
    摆开。只填第一张的话,用户按 4 张付了钱,画布上只多出一张 —— 而另外三张确实在素材库里,
    只是他不知道。
    """
    board = db.get(Board, str(receipt.get("board_id") or ""))
    item_id = str(receipt.get("item_id") or "")
    if board is None or not item_id:
        return

    canvas = board.canvas or {"items": [], "edges": []}
    items = list(canvas.get("items") or [])
    #: **两种形状都要读。** 生成任务一次可能出多张,给的是 asset_ids;语音合成一次只出一段,
    #: 给的是 asset_id —— 这不是新旧兼容,是两种任务本来就不同。只认一种的话,另一种落终态
    #: 时占位会被当成失败摘掉:用户看到音频「生成完就没了」。
    result = (job.result or {}) if job.status == "succeeded" else {}
    asset_ids = [str(one) for one in (result.get("asset_ids") or []) if one]
    if not asset_ids and result.get("asset_id"):
        asset_ids = [str(result["asset_id"])]

    kept: list[dict[str, Any]] = []
    for item in items:
        if item.get("id") != item_id:
            kept.append(item)
            continue
        if not asset_ids:
            # 失败/被取消:结束 run.running,留下这一项和它的提示词,并把原因写在上面。
            #
            # 此前是整项删掉。那让画布上的框凭空消失,连同用户刚写的提示词 —— 而他要做的
            # 下一件事十有八九是"改一个字再来一次"。留着才能重来;原因写在上面,他也不必
            # 去任务中心翻一遍才知道为什么。
            kept.append(
                {
                    **item,
                    "run": {
                        "status": "cancelled" if str(job.status) == "cancelled" else "failed",
                        #: 「生成失败」这句话由界面说；这里只存真正原因。
                        "error": str(getattr(job, "error", "") or "")[:300] or str(job.status),
                    },
                }
            )
            continue
        settled = dict(item)
        # 成功结束一次编辑周期：提示词和引用素材已经被消费，保留模型/参数方便继续同风格创作。
        # 失败/取消不走这里，因此原输入仍完整保留给重试。
        if isinstance(settled.get("form"), dict):
            form = dict(settled["form"])
            form["prompt"] = ""
            form["source_assets"] = []
            form["mentioned_asset_ids"] = []
            form.pop("prompt_document", None)
            settled["form"] = form
        settled["run"] = {"status": "succeeded"}
        kept.append({**settled, "asset_id": asset_ids[0]})
        #: 多出来的那几张挨着它往右排。宽度按这一项自己的宽 —— 用户可能已经把它拉大了,
        #: 用一个写死的间距会让它们叠在一起。
        step = float(settled.get("width") or 260) + 24
        for offset, extra in enumerate(asset_ids[1:], start=1):
            kept.append(
                {
                    **settled,
                    "id": f"{item_id}-{offset + 1}",
                    "x": float(settled.get("x") or 0) + step * offset,
                    "asset_id": extra,
                }
            )

    # 连线可能指着刚被摘掉的那一项 —— normalize 会拒绝悬空的线,所以先把它们去掉。
    alive = {item["id"] for item in kept}
    edges = [edge for edge in (canvas.get("edges") or []) if edge.get("source") in alive and edge.get("target") in alive]
    board.canvas = normalize_canvas({"items": kept, "edges": edges})
    db.commit()
    logger.info("board %s item %s -> %s", board.id, item_id, ", ".join(asset_ids) or "(dropped)")


def install() -> None:
    """把画板的回执登记进任务总线。

    **方向是反的**:任务不认识画板,是画板认识任务 —— 和智能体那条回执同一个做法
    (见 domain/agent/receipts 开头那段)。登记在组合层(app/main._wire_seams)的**导入期**,
    不在 lifespan 里:不跑 lifespan 的入口(TestClient、脚本)照样要能把产出填回画布。
    """
    from app.domain.jobs import register_receipt_deliverer

    register_receipt_deliverer(RECEIPT_KIND, deliver_generated)

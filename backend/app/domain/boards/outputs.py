"""任务交回的产出怎么落到画布上:归一产出(`outputs_of`)、派生新格的摆法、把一封回执合进画布。

都是纯函数 —— 比较并交换冲突时可以重读最新画布再合一遍,不重放任何副作用。"""

from __future__ import annotations

import json
import math
from typing import Any

from app.core.i18n import tr
from app.domain.boards.producer_ids import (
    NOTE_PRODUCER,
    SCENE_PRODUCER,
    ability_of,
    derives_outputs,
    node_type_of,
)
from app.domain.boards.run_state import live_job
from app.domain.boards.shape import _MEDIA_KINDS, DEFAULT_SIZE, MAX_TEXT_CHARS, RUN_ERROR_DETAIL_CHARS


#: 一次运行的产出是哪几种。和工作流的输出类型词表对得上的那一半(见 boards.tools.board_outputs)。
#: `note`:一篇笔记的一版(文档格上写字交回的,见 actions._write_note)。
#: `scene`:一个 3D 场景(「按文字搭 3D 场景」交回的),落成一格 3D 场景格。
#: `layout`:不是一格,是这一轮怎么摆(`columns`:按几列排)—— 宫格切分交回的几张照原来的宫格摆,不竖成一列。
OUTPUT_TYPES = ("asset", "text", "json", "note", "scene", "layout")


def outputs_of(job: Any) -> list[dict[str, Any]]:
    """一个任务交回了什么,归一成画板认的一种形状:
    `[{"type": "asset", "asset_id"}, {"type": "text", "text"}, {"type": "json", "value"}]`。

    **画板读任务结果只经过这一处。** 各种任务的结果本来就长得不一样 —— 生成一次可能出多张
    (`asset_ids`),念字、截取一次出一份(`asset_id`),便签上写字交回一段正文(`text`),画板上
    跑一个节点交回的已经是这个形状(`outputs`,见 boards.tools)。这是四种任务各自现行的结果约定,
    不是新旧几版:没有哪种旧形状要在这里兼容。回执只在任务落终态那一刻读一次(见 deliver_generated /
    _deliver_if_already_settled),读完不再回头看。

    没成功的任务没有产出(空列表)。
    """
    if str(getattr(job, "status", "")) != "succeeded":
        return []
    result = getattr(job, "result", None) or {}
    if not isinstance(result, dict):
        return []
    if isinstance(result.get("outputs"), list):
        return [one for one in result["outputs"] if isinstance(one, dict) and one.get("type") in OUTPUT_TYPES]
    ids = [str(one) for one in (result.get("asset_ids") or []) if one]
    if not ids and result.get("asset_id"):
        ids = [str(result["asset_id"])]
    outputs: list[dict[str, Any]] = [{"type": "asset", "asset_id": one} for one in ids]
    if isinstance(result.get("text"), str):
        outputs.append({"type": "text", "text": result["text"]})
    return outputs


#: 一次运行最多在画布上新建几格。插件的输出没声明类型时是按值猜的,一个列表可能有几百项 ——
#: 全摊开的话画布被一次运行淹没。超出的那些合进最后一张 JSON 便签,一样不丢。
MAX_DERIVED_ITEMS = 12

#: 派生出来的几格离宿主多远、彼此隔多远(画布坐标)。上下留得宽一点:每一格的名字挂在框外正上方。
_DERIVED_GAP_X = 80.0
_DERIVED_GAP_Y = 48.0
#: 排成一片(宫格)时:每一格多宽、左右两格之间多远。上下之间仍是 _DERIVED_GAP_Y —— 每一格头上有一行
#: 标签(「图片」),行距小了标签就压在上一张图上。
_GRID_TILE_WIDTH = 200.0
_GRID_GAP_IN_ROW = 24.0


def _derived_item(output: dict[str, Any], assets: dict[str, tuple[str, str]]) -> dict[str, Any] | None:
    """一份产出 → 画布上新的一格(还没有 id 和位置)。素材不在这个工作区里的(查不到)不落。

    素材按它自己的种类落:图片、视频、音频各是那一种格子;别的文件(文档、压缩包……)画板上没有
    对应的格子,落成一张写着素材名的便签。文字落成便签;结构化数据落成按 JSON 排版的便签。
    落成的便签和手放的一样写明产出者(写字)—— 选中它照样能让 AI 改。
    """
    note_form = {"producer": NOTE_PRODUCER}
    kind = output.get("type")
    if kind == "asset":
        found = assets.get(str(output.get("asset_id") or ""))
        if found is None:
            return None
        asset_kind, name = found
        if asset_kind in _MEDIA_KINDS:
            return {"kind": asset_kind, "asset_id": str(output["asset_id"])}
        return {"kind": "note", "text": _clip(name), "form": note_form}
    if kind == "text":
        return {"kind": "note", "text": _clip(str(output.get("text") or "")), "form": note_form}
    if kind == "json":
        return {"kind": "note", "text": _clip(_json_text(output.get("value"))), "text_format": "json", "form": note_form}
    if kind == "scene" and output.get("scene_id"):
        #: 挂上渲白模 —— 选中它就能挑镜头渲首尾帧或运镜视频。
        return {"kind": "scene", "scene_id": str(output["scene_id"]), "text": str(output.get("name") or ""),
                "form": {"producer": SCENE_PRODUCER}}
    if kind == "note" and output.get("note_id"):
        return {"kind": "document", "note_id": str(output["note_id"]), "note_revision": output.get("revision"),
                "text": str(output.get("title") or ""), "form": note_form}
    return None


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _clip(text: str) -> str:
    """便签正文有上限(MAX_TEXT_CHARS)。超了就截,并在末尾说一声 —— 整次回执因为一张便签太长
    被 normalize 拒掉的话,宿主会一直停在「在跑」。"""
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…"


def _overflow_value(output: dict[str, Any], assets: dict[str, tuple[str, str]]) -> Any:
    """超出上限的那几份产出合进一张 JSON 便签时,每一份写成什么。"""
    if output.get("type") == "asset":
        _, name = assets.get(str(output.get("asset_id") or ""), ("", ""))
        return {"asset_id": output.get("asset_id"), "name": name}
    if output.get("type") == "text":
        return output.get("text")
    return output.get("value")


def _grid_tile_size(host: dict[str, Any], columns: int, rows: int) -> tuple[float, float]:
    """宫格切出的每一张在画布上多大:宽定一档,高照「宿主那张图的比例 × 行列」算 —— 九宫格切出的是
    和原图一样比例的小图的话,每张就是原图宽的 1/列、高的 1/行。

    高度不能用图片格的缺省(那是一张横图的比例):界面拿到图会按真实比例把格子拉高,排好的下一行
    就被压住了(用户截图:切出的九张挤成一团,标签盖在上一张图上)。宿主没有尺寸就当它是方的。
    """
    width = float(host.get("width") or 0)
    height = float(host.get("height") or 0)
    ratio = (width / columns) / (height / rows) if width > 0 and height > 0 else 1.0
    return _GRID_TILE_WIDTH, round(_GRID_TILE_WIDTH / max(ratio, 0.1), 1)


def _derive(
    host: dict[str, Any],
    outputs: list[dict[str, Any]],
    assets: dict[str, tuple[str, str]],
    items: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """宿主(跑了一项能力的内容格、3D 场景格,或空格子就地填完之后多出来的那几份)这一轮的产出 →
    新建的几格和连向它们的线。

    **每一轮都是新的一列,不覆盖上一轮。** 摆在宿主右边、再往右避开**它此前派生出来的**那几格(`{宿主}-out-N`,
    见下面起 id 的那一段);一列里从上往下排。上一轮的产出是用户可能已经拿去用的东西(连到了别处、改过字),重跑把它们
    换掉的话,下游悄悄变了。

    只避开派生出来的,不避开宿主连出去的每一格:人自己连到远处的一格(比如画板另一头的一张便签)也算的话,新的一列
    会落到视野外面老远的地方,看着像什么都没出来。

    产出里带着 `layout`(节点声明了 `board_columns`,见 boards.tools.board_outputs)时按那么多列排成一片:
    九宫格切出的九张摆回 3×3,一眼对得上原图里的位置。
    """
    landed = [output for output in outputs if _derived_item(output, assets)]
    made = [one for one in (_derived_item(output, assets) for output in landed) if one]
    if len(made) > MAX_DERIVED_ITEMS:
        rest = landed[MAX_DERIVED_ITEMS - 1 :]
        made = made[: MAX_DERIVED_ITEMS - 1] + [{
            "kind": "note",
            "text": _clip(_json_text([_overflow_value(one, assets) for one in rest])),
            "text_format": "json",
            "form": {"producer": NOTE_PRODUCER},
        }]
    if not made:
        return [], []

    host_id = str(host["id"])
    by_id = {str(one.get("id")): one for one in items}
    derived_prefix = f"{host_id}-out-"
    earlier = [by_id[str(edge.get("target"))] for edge in edges
               if edge.get("source") == host_id and str(edge.get("target")) in by_id
               and str(edge.get("target")).startswith(derived_prefix)]
    right = max(
        [float(host.get("x") or 0) + float(host.get("width") or DEFAULT_SIZE.get(str(host.get("kind")), (0, 0))[0])]
        + [float(one.get("x") or 0) + float(one.get("width") or DEFAULT_SIZE.get(str(one.get("kind")), (0, 0))[0])
           for one in earlier]
    )
    left = right + _DERIVED_GAP_X
    top = float(host.get("y") or 0)
    layout = next((one for one in outputs if one.get("type") == "layout"), None)
    columns = max(1, min(len(made), int((layout or {}).get("columns") or 1)))
    tile = _grid_tile_size(host, columns, math.ceil(len(made) / columns)) if layout else None
    taken = {str(one.get("id")) for one in items}
    new_items: list[dict[str, Any]] = []
    new_edges: list[dict[str, Any]] = []
    suffix = 0
    x, y, row_height = left, top, 0.0
    for index, one in enumerate(made):
        if index and index % columns == 0:
            x, y, row_height = left, y + row_height + _DERIVED_GAP_Y, 0.0
        suffix += 1
        while f"{host_id}-out-{suffix}" in taken:
            suffix += 1
        item_id = f"{host_id}-out-{suffix}"
        taken.add(item_id)
        width, height = tile if tile and one["kind"] == "image" else DEFAULT_SIZE[one["kind"]]
        new_items.append({"id": item_id, **one, "x": x, "y": y, "width": float(width), "height": float(height)})
        new_edges.append({"id": f"{host_id}->{item_id}", "source": host_id, "target": item_id})
        x += width + _GRID_GAP_IN_ROW
        row_height = max(row_height, float(height))
    return new_items, new_edges


#: 一次出多份时,第 2 份起往右排:这一格自己的宽(用户可能拉大了)加一道缝;没量过宽的按这个算。
_SLOT_WIDTH = 260.0
_SLOT_GAP = 24.0


def _beside(slot: dict[str, Any], taken: set[str]):
    """这一格右边的下一格:`({格子}-{n}, x)`,n 避开整张板上已有的 id(同一格再出一次多张时,上一轮的 `-2` 还在板上),
    位置跟着序号走(第 n 格在第 n-1 列),于是也不会正好叠在上一轮那一格上。摆占位和回执往右排的是同一串位置。"""
    step = float(slot.get("width") or _SLOT_WIDTH) + _SLOT_GAP
    suffix = 1
    while True:
        suffix += 1
        while f"{slot['id']}-{suffix}" in taken:
            suffix += 1
        one = f"{slot['id']}-{suffix}"
        taken.add(one)
        yield one, float(slot.get("x") or 0) + step * (suffix - 1)


def sibling_placeholders(slot: dict[str, Any], count: int, taken: set[str]) -> list[dict[str, Any]]:
    """一次会交回不止一份时,第 2 份起的占位:和这一格一样(种类、表单、大小、在跑的同一个任务),摆在它右边。
    回执按先后把产出填进去(见 _canvas_with_delivered_result)。`taken` 是板上已有的 id,会被占上。"""
    places = _beside(slot, taken)
    return [{**{key: value for key, value in slot.items() if key != "asset_id"}, "id": one, "x": x}
            for one, x in (next(places) for _ in range(count))]


def _consumed(item: dict[str, Any], *, text: str | None, note: dict[str, Any] | None) -> dict[str, Any]:
    """一格就地收下这一轮的产出之后的样子(素材另填):运行态成功,一次性的表单用掉了。"""
    settled = dict(item)
    # 成功结束一次编辑周期：提示词和引用素材已经被消费，保留模型/参数方便继续同风格创作。
    # 失败/取消不走这里，因此原输入仍完整保留给重试。
    if isinstance(settled.get("form"), dict):
        form = dict(settled["form"])
        form["prompt"] = ""
        form["source_assets"] = []
        form["mentioned_asset_ids"] = []
        #: @ 到的资产随提示词一起被消费了;用过它这件事记在生成记录里(request.entities)。
        if form.get("mentioned_entity_ids"):
            form["mentioned_entity_ids"] = []
        form.pop("prompt_document", None)
        #: 自动填进来的那段也一起用掉了:下一轮面板照上游重新填。
        form.pop("prefilled", None)
        settled["form"] = form
    settled["run"] = {"status": "succeeded"}
    if text is not None:
        settled["text"] = text
    if note is not None and settled.get("kind") == "document":
        #: 文档格钉到写出来的那篇笔记上,引用着的那份文件摘掉:note_id 和 asset_id 二选一,两样都有的话整封回执被
        #: normalize 拒掉,那一格永远在跑(开跑前 producers._admits_write 已经拒了这种格子,这里兜住开跑之后才换上的)。
        settled.pop("asset_id", None)
        settled["note_id"], settled["note_revision"] = str(note["note_id"]), note.get("revision")
    return settled


def _canvas_with_delivered_result(
    canvas: dict[str, Any],
    *,
    item_id: str,
    job_id: str,
    outputs: list[dict[str, Any]],
    reason: str,
    cancelled: bool,
    succeeded: bool = False,
    assets: dict[str, tuple[str, str]] | None = None,
    detail: str = "",
    hint: str = "",
) -> dict[str, Any]:
    """Merge one asynchronous receipt into the newest board projection.

    The merge is deliberately pure so a compare-and-swap conflict can reload the latest canvas
    and retry without replaying any task side effects.

    **只收它自己那一轮**:那一格此刻跑的不是这个任务(占位还没落下、或已经是别的一轮),原样不动。
    占位与回执于是谁先谁后都一样 —— 先到的回执被放过,占位落下时补送(见 place_pending)。

    三种落法(ADR 0021 的「落点」):

    · **就地**:宿主是一个等着产出的槽(图片/视频/音频/便签)。产出(见 outputs_of)是素材
      (生成/念/截)或一段正文(便签上写字),第一份填进这一格,多出来的往右排;两样都没有就是没做成。
    · **就地填、其余派生**:宿主是空格子,挂着一个节点产出者(插件的生成器,见 producer_ids.node_type_of)。
      第一份**对得上这种格子**的产出(图片格要一张图、便签要一段字)填进它,别的几份新建在右边、连线 ——
      节点交回的常常不止一种东西(一张图 + 一段说明),说明塞进图片格的 text 就是错位。表单不清:
      它就是这一格上次怎么被填的。
    · **派生**:这一轮跑的是宿主的一项能力(`run.ability`),或宿主挂着派生产出者(3D 场景格渲白模,见
      producer_ids.derives_outputs)。它自己不放产出,每一份产出都新建一格、连一条线(见 _derive);
      任务成功就算做成 —— 交回的东西落不成任何一格(全是空值)也是成功,只是右边没有新东西。
      表单(能力的设置)**不清空**:再点一次那一项,还是上次的样子。

    `assets`:产出里那些素材的种类和名字(回执那一侧从库里查好)—— 派生时靠它决定落成哪种格子。

    **一起摆的占位**(同一个任务、在跑的别的几格,见 sibling_placeholders):就地那种按先后收下第 2 份起的素材;
    交回的少了,没收到的那几格摘掉;多了,多出来的照旧往右排;没做成(失败、取消、什么都没交回)就一起摘掉 ——
    重试照这一格来。这一格已经不是这一轮了(被换成了别的),它们按先后收下全部素材。
    """
    asset_ids = [str(one["asset_id"]) for one in outputs if one.get("type") == "asset"]
    text = next((str(one["text"]) for one in outputs if one.get("type") == "text"), None)
    #: 文档格上写出来的那篇笔记(那一版):就地钉上去,标题当这一格的字。
    note = next((one for one in outputs if one.get("type") == "note" and one.get("note_id")), None)
    if note is not None and text is None:
        text = str(note.get("title") or "")
    items = list(canvas.get("items") or [])
    edges = list(canvas.get("edges") or [])
    siblings = [one for one in items if job_id and one.get("id") != item_id and live_job(one) == job_id]
    waiting = {str(one.get("id")) for one in siblings}
    #: 这一格是不是这一轮:是的话一起摆的占位跟着它定(收下第 2 份起的素材,或一起摘掉)。
    this_round = False
    kept: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("id")) in waiting:
            continue  # 一起摆的占位:收下几份、摘掉哪几格,等这一格定了再说(见循环后面)
        if item.get("id") != item_id or live_job(item) != job_id:
            kept.append(item)
            continue
        this_round = True
        derives = derives_outputs(item)
        #: 这一轮跑的是哪一项能力:终态里也留着,界面照它说「转写失败」、把那一项的面板找回来。
        ability = ability_of(item)
        marker = {"ability": ability} if ability else {}
        fills = not derives and node_type_of(str((item.get("form") or {}).get("producer") or "")) is not None
        if ((derives or fills) and not succeeded) or (not derives and not fills and not asset_ids and text is None):
            # 失败/被取消:结束 run.running,留下这一项和它的提示词,并把原因写在上面。
            #
            # 此前是整项删掉。那让画布上的框凭空消失,连同用户刚写的提示词 —— 而他要做的
            # 下一件事十有八九是"改一个字再来一次"。留着才能重来;原因写在上面,他也不必
            # 去任务中心翻一遍才知道为什么。
            #: 「生成失败」这句话由界面说;这里只存**真正的原因**,没有就不写。此前没原因时拿任务
            #: 状态顶上 —— 一个成功结束却没交回产出的任务,格子上的失败原因就成了「succeeded」。
            run = {"status": "cancelled" if cancelled else "failed"}
            if reason.strip():
                run["error"] = reason.strip()[:300]
            #: 原文(`reason` 是从它摘出来的那一句,见 domain/failure_summary):格子上「查看原始错误」里给。和那一句一样就不存。
            if detail.strip() and detail.strip() != reason.strip():
                run["error_detail"] = detail.strip()[:RUN_ERROR_DETAIL_CHARS]
            #: 认得出的原因:该去哪修(插件说的,见 domain/failure_summary.hint_of)。格子上收在「详情」的悬停里,不撑大格子。
            if hint.strip():
                run["error_hint"] = hint.strip()[:RUN_ERROR_DETAIL_CHARS]
            kept.append({**item, "run": {**run, **marker}})
            continue
        if derives:
            kept.append({**item, "run": {"status": "succeeded", **marker}})
            new_items, new_edges = _derive(item, outputs, assets or {}, items, edges)
            kept.extend(new_items)
            edges.extend(new_edges)
            continue
        if fills:
            fit = next((one for one in outputs if _fits(one, str(item.get("kind")), assets or {})), None)
            rest = [one for one in outputs if one is not fit]
            if fit is None and not any(_derived_item(one, assets or {}) for one in rest):
                kept.append({**item, "run": {"status": "failed", "error": tr("boardErr_noOutput")}})
                continue
            filled = {**item, "run": {"status": "succeeded"}}
            if fit is not None and fit.get("type") == "asset":
                filled["asset_id"] = str(fit["asset_id"])
            elif fit is not None and fit.get("type") == "note":
                #: 文档格钉到笔记上,引用着的那份文件摘掉(note_id 和 asset_id 二选一,两样都有整封回执被拒)。
                filled.pop("asset_id", None)
                filled.update(note_id=str(fit["note_id"]), note_revision=fit.get("revision"), text=str(fit.get("title") or ""))
            elif fit is not None and fit.get("type") == "scene":
                #: 按剧本搭出的是一个**新场景**,换进这一格;原来那个还在「3D 场景」里。渲白模上挑过的镜头是旧场景的,
                #: 摘掉 —— 留着的话面板拿着一个新场景里没有的镜头 id(用户截图:镜头那一格只剩一个箭头)。
                filled.update(scene_id=str(fit["scene_id"]), text=str(fit.get("name") or ""))
                form = filled.get("form")
                if isinstance(form, dict) and isinstance(form.get("config"), dict) and "shot_id" in form["config"]:
                    filled["form"] = {**form, "config": {k: v for k, v in form["config"].items() if k != "shot_id"}}
            elif fit is not None:
                filled["text"] = _clip(str(fit.get("text") or ""))
            kept.append(filled)
            new_items, new_edges = _derive(filled, rest, assets or {}, items, edges)
            kept.extend(new_items)
            edges.extend(new_edges)
            continue
        settled = _consumed(item, text=text, note=note)
        if not asset_ids:
            kept.append(settled)
            continue
        kept.append({**settled, "asset_id": asset_ids[0]})
        #: 第 2 份起:先填一起摆好的占位(按先后),多出来的挨着往右排。宽度按这一项自己的宽 —— 用户可能已经把它
        #: 拉大了,用一个写死的间距会让它们叠在一起。新格子的 id 要避开**整张板上已有的**,否则整次回执被 normalize
        #: 拒掉,产出一张都落不回来,这一格永远在转圈(见 _beside)。
        rest = asset_ids[1:]
        for sibling, extra in zip(siblings, rest):
            kept.append({**_consumed(sibling, text=None, note=None), "asset_id": extra})
        places = _beside(settled, {str(one.get("id")) for one in items})
        for extra in rest[len(siblings):]:
            extra_id, x = next(places)
            kept.append({**settled, "id": extra_id, "x": x, "asset_id": extra})

    #: 这一格不是这一轮(被换掉了):一起摆的占位按先后收下全部素材;没做成就摘掉。
    if not this_round and succeeded:
        for sibling, extra in zip(siblings, asset_ids):
            kept.append({**_consumed(sibling, text=None, note=None), "asset_id": extra})

    # 连线可能指着刚被摘掉的那一项 —— normalize 会拒绝悬空的线,所以先把它们去掉。
    alive = {item["id"] for item in kept}
    edges = [edge for edge in edges if edge.get("source") in alive and edge.get("target") in alive]
    #: 只换 items 和 edges,**画布上别的层原样带着**(标记)。此前这里从零拼一个新字典,
    #: 于是每落回一次产出,用户放的标记就被 normalize 当成「没给」清空。
    return {**canvas, "items": kept, "edges": edges}


def _fits(output: dict[str, Any], kind: str, assets: dict[str, tuple[str, str]]) -> bool:
    """这一份产出能不能**填进** `kind` 这种空格子:便签收一段字,文档格收一篇笔记,图片 / 视频 / 音频格收同一种素材。"""
    if kind == "note":
        return output.get("type") == "text"
    if kind == "document":
        return output.get("type") == "note" and bool(output.get("note_id"))
    if kind == "scene":
        return output.get("type") == "scene" and bool(output.get("scene_id"))
    found = assets.get(str(output.get("asset_id") or "")) if output.get("type") == "asset" else None
    return found is not None and found[0] == kind

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
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import Board, now
from app.domain.boards.producer_ids import NOTE_PRODUCER, is_producer_id, missing_slot_producer


logger = logging.getLogger(__name__)


class BoardDomainError(LocalizedError, ValueError):
    pass


class BoardNotFound(BoardDomainError):
    """这个工作区里没有这张板(或这一项)。"""


class BoardRevisionConflict(BoardDomainError):
    """The caller edited a projection older than the server's current board."""

    def __init__(self, base_revision: int, current_revision: int):
        self.base_revision = base_revision
        self.current_revision = current_revision
        super().__init__("boardErr_revisionConflict", base=base_revision, current=current_revision)


def item_not_found(item_id: str) -> BoardNotFound:
    """「画板项不存在」。没给 id 是另一句话 —— 把「(空)」当成 id 填进去就翻不动了。"""
    return BoardNotFound("boardErr_itemNotFound", item_id=item_id) if item_id else BoardNotFound("boardErr_itemIdMissing")


def _field_error(item_key: str, bare_key: str, field: str, item_id: str, **params: object) -> BoardDomainError:
    """坐标 / 尺寸不合法。带不带「画板项 xx 的」是两句话,不是往前面拼一截。"""
    if item_id:
        return BoardDomainError(item_key, item_id=item_id, field=field, **params)
    return BoardDomainError(bare_key, field=field, **params)


#: 画板上能放什么。
#:
#: `note` 便签(文字)、`image` 图片、`video` 视频、`audio` 音频、`frame` 分组框(圈起来命名)。
#:
#: 图片和视频**分开两种而不是合成一个 media**:它们在画板上的样子和操作都不同 ——
#: 图片是一张静止的参考,视频要能就地播;而"从这张图生成视频"是图片才有的动作,
#: 反过来"抽一帧"是视频才有的。合成一种的话每处都要先分辨一次它到底是哪个。
#:
#: `action` 工具格:跑一个工作流节点(插件工具、挑过的内置节点,见 boards.producers)。它自己没有
#: 产出可放 —— 每跑一次,产出都**新建**成右边的几格并连上线(见 _canvas_with_delivered_result)。
ITEM_KINDS = ("note", "image", "video", "audio", "frame", "scene", "document", "action")

#: 便签正文的格式。只有一种非默认的:工具格交回的结构化数据(JSON)落成的便签,界面按代码排版。
TEXT_FORMATS = ("json",)

#: 新建时的默认大小。**和前端 DEFAULT_SIZE 是同一组数** —— 智能体加的项不该比手动加的
#: 小一圈,那看起来像两种不同的东西;工具格派生出来的几格也按它摆(见 _derive)。
DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "note": (220, 140),
    "image": (260, 180),
    "video": (320, 200),
    "audio": (280, 72),
    "frame": (420, 300),
    "scene": (320, 220),
    "document": (320, 300),
    "action": (280, 150),
}

#: 素材在画板上**有自己那种格子**的几种:一份图片 / 视频 / 音频素材放进同名的格子里。工具格交回的素材按它
#: 落成同种格子,别的文件落成写着名字的便签(见 _derived_item)。它们不是「必须带素材」:没有素材的
#: 是空槽,合法(见 normalize_canvas 里「空槽是合法的」那一段)。
_MEDIA_KINDS = ("image", "video", "audio")

#: 一种格子的 `asset_id` 必须是哪种素材(见 _validate_asset_references)。3D 场景借它放缩略图,是一张图。
#: 不在表里的种类只问「是不是这个工作区的」。
_ASSET_KIND_OF_ITEM: dict[str, str] = {**{kind: kind for kind in _MEDIA_KINDS}, "scene": "image"}

#: 一个 item 至少要有的东西。坐标必须是数,否则画布渲染不出来。
_REQUIRED = ("id", "kind", "x", "y")

#: 便签的颜色。给一组预设而不是任意色值:随手挑的颜色凑在一起会很难看,而且**颜色要能表达
#: 分类** —— 一组固定的色板才让"黄色是待办、蓝色是参考"这种约定成立。
NOTE_COLORS = ("yellow", "blue", "green", "pink", "purple", "gray")

MAX_ITEMS = 2000
MAX_TEXT_CHARS = 20_000
#: 一格的名字(`title`)最长多少字。它挂在节点上方那一行、查找列表的一行里,是个**名字**不是一段话。
MAX_TITLE_CHARS = 120
RUN_STATUSES = ("idle", "queued", "running", "succeeded", "failed", "cancelled")


def finite_number(value: Any, field: str, item_id: str = "") -> float:
    """画布上的一个坐标或尺寸。**算子那一侧共用这一个** —— 两份各写各的必然漂,而漂的那
    一半就是没挡住的那条路。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _field_error("boardErr_itemFieldNotNumber", "boardErr_fieldNotNumber", field, item_id, value=repr(value))
    # NaN / Infinity 是合法的 Python float,`json.dumps` 也照写不误 —— 而写出来的
    # `{"x": NaN}` **不是合法 JSON**,浏览器 `JSON.parse` 直接抛。一张画板只要混进一个,
    # 它就再也打不开了:用户看到的是"画板坏了",而库里那份数据其实完好。
    #
    # 不是只有恶意客户端造得出:前端算坐标时一次除以零(缩放为 0、宽度为 0)就是 NaN,
    # 而它会一路存进去、不报错。一个瞬时的计算失误换一张永久打不开的画板,不成比例。
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise _field_error("boardErr_itemFieldNotFinite", "boardErr_fieldNotFinite", field, item_id, value=repr(value))
    return number


def _normalize_form(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验并保留**属于节点自己的表单**。

    表单是用户可继续编辑的事实；生成器为了调用供应商临时补上的文件名图例、签名参数等都
    不属于它。这里有意允许不同节点放不同字段，但把 JSON 的基本形状钉住，避免下一次打开
    节点时拿到一个无法渲染的值。
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form")
    form = dict(value)
    #: 这张表单是哪个产出者的(见 boards.producers)。**只认名字** —— 不问它此刻能不能跑,
    #: 一张板在某个产出者不可用时也得能开能存。
    producer = form.get("producer")
    if producer is not None:
        if not is_producer_id(producer):
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="form.producer")
    prompt = form.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="form.prompt")
        if len(prompt) > MAX_TEXT_CHARS:
            raise BoardDomainError("boardErr_promptTooLong", item_id=item_id, limit=MAX_TEXT_CHARS)
    for field in ("provider", "provider_profile_id", "model", "mode", "voice_id"):
        if form.get(field) is not None and not isinstance(form[field], str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field=f"form.{field}")
    if form.get("parameters") is not None and not isinstance(form["parameters"], dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.parameters")
    sources = form.get("source_assets")
    if sources is not None:
        if not isinstance(sources, list) or any(not isinstance(one, dict) for one in sources):
            raise BoardDomainError("boardErr_sourceAssetsNotObjects", item_id=item_id)
        form["source_assets"] = [one for one in map(_normalize_source, sources) if one]
    mentioned = form.get("mentioned_asset_ids")
    if mentioned is not None:
        if not isinstance(mentioned, list):
            raise BoardDomainError("boardErr_itemFieldNotArray", item_id=item_id, field="form.mentioned_asset_ids")
        form["mentioned_asset_ids"] = [str(one).strip() for one in mentioned if str(one).strip()]
    trim = form.get("trim")
    if trim is not None:
        form["trim"] = _normalize_trim(trim, item_id)
    prompt_document = form.get("prompt_document")
    if prompt_document is not None:
        if not isinstance(prompt_document, dict) or prompt_document.get("type") != "doc":
            raise BoardDomainError("boardErr_promptDocumentNotDoc", item_id=item_id)
        if len(json.dumps(prompt_document, ensure_ascii=False)) > MAX_TEXT_CHARS * 8:
            raise BoardDomainError("boardErr_promptDocumentTooLarge", item_id=item_id)
    #: 工具格的节点配置(键就是那个节点声明的字段)。**形状只钉到「是个对象、不太大」** —— 哪些
    #: 键合法由节点自己的声明说了算,而插件节点是运行时才知道的;字段错了在运行时由执行器报。
    config = form.get("config")
    if config is not None:
        if not isinstance(config, dict):
            raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.config")
        try:
            #: 和坐标同一条(见 finite_number):NaN / Infinity 写得进去、读不回来 —— 整张板打不开。
            size = len(json.dumps(config, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="form.config") from exc
        if size > MAX_TEXT_CHARS * 8:
            raise BoardDomainError("boardErr_formConfigTooLarge", item_id=item_id)
    bindings = form.get("bindings")
    if bindings is not None:
        form["bindings"] = _normalize_bindings(bindings, item_id)
    return form


def _normalize_bindings(value: Any, item_id: str) -> dict[str, list[dict[str, str]]]:
    """工具格上「这个字段的值从上游哪几格来」:`{字段: [{"from": 上游那一格的 id}, …]}`。

    值不存在这里 —— 运行时由服务端照当时的画布去取(便签的字、文档的正文、图片的素材……),
    所以上游改了字,下一次运行就跟着变。顺序按用户挑的;同一格挑两次只算一次。
    线断了的那几条在 _drop_detached_bindings 里摘掉。
    """
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.bindings")
    out: dict[str, list[dict[str, str]]] = {}
    for field, refs in value.items():
        if not isinstance(field, str) or not field.strip():
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="form.bindings")
        if not isinstance(refs, list) or any(not isinstance(one, dict) for one in refs):
            raise BoardDomainError("boardErr_bindingsNotRefs", item_id=item_id, field=field)
        seen: list[str] = []
        for ref in refs:
            origin = ref.get("from")
            if not isinstance(origin, str) or not origin.strip():
                raise BoardDomainError("boardErr_bindingsNotRefs", item_id=item_id, field=field)
            if origin.strip() not in seen:
                seen.append(origin.strip())
        out[field] = [{"from": one} for one in seen]
    return out


def _normalize_title(value: Any, item_id: str) -> str:
    """一格的名字:一行字。空白(连同换行、制表符)收成单个空格,首尾去掉;空的就是没起名。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="title")
    title = " ".join(value.split())
    if len(title) > MAX_TITLE_CHARS:
        raise BoardDomainError("boardErr_titleTooLong", item_id=item_id, limit=MAX_TITLE_CHARS)
    return title


def _normalize_source(value: dict[str, Any]) -> dict[str, str] | None:
    """槽位里挂的一份素材。`from`:它是**顺着哪一格连过来的线**挂上的(手动挂的没有)——
    见 _drop_detached_bindings。缺素材或角色的是空位,不算。"""
    asset_id = str(value.get("asset_id") or "").strip()
    role = str(value.get("role") or "").strip()
    if not asset_id or not role:
        return None
    source = {"asset_id": asset_id, "role": role}
    origin = value.get("from")
    if isinstance(origin, str) and origin.strip():
        source["from"] = origin.strip()
    return source


def _drop_detached_bindings(items: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """**顺着线接上的东西,活得和那根线一样长。** 画板上「哪一份是从上游来的」只有这一处规则。

    两种「从上游来」走的是同一条:

    · 槽位里记着 `from` 的那一份素材(`form.source_assets`),是面板照上游那一格的产出挂上的。
      线没了(删了线、删了上游那一格)、或上游换了一份素材,它就不再是从上游来的 —— 留着的话,
      下次打开面板它还挂在首帧上,点生成照样发出去,而画布上早就没有那条线了。手动挂的(没有
      `from`)不动。
    · 工具格的绑定(`form.bindings`):字段的值从哪几格来。线没了、上游那一格没了,那一条就摘掉;
      **工具格不能当上游**(它自己没有产出,产出是它右边新建的那几格),接到它上面的也摘掉。

    放在 normalize 里,因为画布的**每一次写入**都过这一道:客户端自动保存、智能体改画板
    (edit_board 删掉上游那一格)、服务端对单格的合并。判据只看这一份画布自己 —— 不拿「上一次」
    去比,所以旧快照存回来、同一份再存一遍,结果都一样。前端不另写一份,收服务端存下的那份。
    """
    by_id = {item["id"]: item for item in items}
    wired = {(edge["source"], edge["target"]) for edge in edges}
    for item in items:
        form = item.get("form") or {}
        sources = form.get("source_assets")
        if sources:
            kept = [
                one
                for one in sources
                if "from" not in one
                or ((one["from"], item["id"]) in wired and (by_id.get(one["from"]) or {}).get("asset_id") == one["asset_id"])
            ]
            if len(kept) != len(sources):
                form = item["form"] = {**form, "source_assets": kept}
        bindings = form.get("bindings")
        if bindings:
            attached = {
                field: [
                    ref
                    for ref in refs
                    if (ref["from"], item["id"]) in wired and (by_id.get(ref["from"]) or {}).get("kind") not in (None, "action")
                ]
                for field, refs in bindings.items()
            }
            #: 一个字段的线全断了,这个字段就不再是「接上游」的 —— 整个字段摘掉,不留一个空列表。
            attached = {field: refs for field, refs in attached.items() if refs}
            if attached != bindings:
                item["form"] = {**form, "bindings": attached}


def _normalize_trim(value: Any, item_id: str) -> dict[str, Any]:
    """这一格是**从哪份素材截的哪一段**(见 actions.trim_on_board)。

    截出来的那一格和生成出来的同是视频/音频,光看种类分不出它该挂哪块面板;截挂了回来重试时,
    还得知道截的是哪一份 —— 所以截取把自己的来历记在表单上,而不是塞进生成参数里。
    """
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.trim")
    asset_id = value.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="form.trim.asset_id")
    mute = value.get("mute", False)
    if not isinstance(mute, bool):
        raise BoardDomainError("boardErr_itemFieldNotBool", item_id=item_id, field="form.trim.mute")
    return {
        "asset_id": asset_id.strip(),
        "start": finite_number(value.get("start"), "form.trim.start", item_id),
        "end": finite_number(value.get("end"), "form.trim.end", item_id),
        "mute": mute,
    }


def _normalize_run(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验节点自己的运行态。终态不允许再携带 job_id，避免 UI 永久转圈。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="run")
    status = str(value.get("status") or "idle").strip()
    if status not in RUN_STATUSES:
        raise BoardDomainError("boardErr_runStatusInvalid", item_id=item_id, status=status)
    run: dict[str, Any] = {"status": status}
    job_id = value.get("job_id")
    if job_id is not None:
        if status not in ("queued", "running"):
            raise BoardDomainError("boardErr_finishedRunHasJob", item_id=item_id)
        if not isinstance(job_id, str) or not job_id.strip():
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="run.job_id")
        run["job_id"] = job_id.strip()
    error = value.get("error")
    if error is not None:
        if not isinstance(error, str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="run.error")
        if error.strip():
            run["error"] = error.strip()[:300]
    return run


def normalize_canvas(raw: Any) -> dict[str, Any]:
    """把外面传进来的画布校验并归一成存得下、读得回的形状。

    宽进严出:少写的字段补默认(新画板、旧版本存的都能读),而**写错的字段一律拒绝** ——
    补一个默认值等于替用户猜,而猜错的表现是他的东西挪了位置或者变了颜色。
    """
    if raw is None:
        return {"items": [], "edges": [], "markers": []}
    if not isinstance(raw, dict):
        raise BoardDomainError("boardErr_canvasNotObject")

    raw_items = raw.get("items") or []
    if not isinstance(raw_items, list):
        raise BoardDomainError("boardErr_canvasFieldNotArray", field="items")
    if len(raw_items) > MAX_ITEMS:
        raise BoardDomainError("boardErr_tooManyItems", limit=MAX_ITEMS, count=len(raw_items))

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise BoardDomainError("boardErr_itemNotObject")
        for field in _REQUIRED:
            if field not in entry:
                raise BoardDomainError("boardErr_itemMissingField", field=field)
        item_id = str(entry["id"]).strip()
        if not item_id:
            raise BoardDomainError("boardErr_itemIdEmpty")
        # id 重了的话前端按 id 索引会**默默丢掉一个** —— 用户看到的是"我刚加的东西没了"。
        if item_id in seen:
            raise BoardDomainError("boardErr_duplicateItemId", item_id=item_id)
        seen.add(item_id)

        kind = str(entry["kind"]).strip()
        if kind not in ITEM_KINDS:
            raise BoardDomainError("boardErr_unknownItemKind", kind=kind, kinds=", ".join(ITEM_KINDS))
        if "job_id" in entry or "error" in entry:
            raise BoardDomainError("boardErr_legacyRunFields", item_id=item_id)

        item: dict[str, Any] = {
            "id": item_id,
            "kind": kind,
            "x": finite_number(entry["x"], "x", item_id),
            "y": finite_number(entry["y"], "y", item_id),
        }
        for field in ("width", "height"):
            if entry.get(field) is not None:
                size = finite_number(entry[field], field, item_id)
                if size <= 0:
                    raise BoardDomainError("boardErr_itemSizeNotPositive", item_id=item_id, field=field)
                item[field] = size

        # **名字是每一格都有的一个字段,不分种类。** 节点上方那行标签、查找节点、智能体认格子
        # 都读它;没起名(没有这个字段)就显示种类名 —— 那是「默认」的定义,不是缺了什么。
        # 分组框的名字此前住在 `text` 里(见迁移 migrate-board-frame-names-become-titles),
        # 一个名字两处放,读的人就得先分辨这格是不是分组框。
        title = _normalize_title(entry.get("title"), item_id)
        if title:
            item["title"] = title

        text = entry.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="text")
            if len(text) > MAX_TEXT_CHARS:
                raise BoardDomainError("boardErr_textTooLong", item_id=item_id, limit=MAX_TEXT_CHARS)
            #: 分组框没有正文 —— 它的名字在 title。还往 text 里写的是没跟上的写入方,拒掉比
            #: 存一份没人读的字好:存下来的话,用户改的名字在画布上不出现,也不报错。
            if kind == "frame":
                raise BoardDomainError("boardErr_frameHasNoText", item_id=item_id)
            item["text"] = text

        #: 正文按什么格式显示。只有便签有正文格式;缺省(没有这个字段)是纯文字。
        text_format = entry.get("text_format")
        if text_format is not None:
            if text_format not in TEXT_FORMATS:
                raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="text_format")
            if kind != "note":
                raise BoardDomainError("boardErr_textFormatNoteOnly", kind=kind)
            item["text_format"] = text_format

        form = _normalize_form(entry.get("form"), item_id)
        if form is not None:
            item["form"] = form

        color = entry.get("color")
        if color is not None:
            if color not in NOTE_COLORS:
                raise BoardDomainError("boardErr_unknownColor", color=color, colors=", ".join(NOTE_COLORS))
            item["color"] = color

        if kind == "document":
            note_id, revision = entry.get("note_id"), entry.get("note_revision")
            if note_id is not None or revision is not None:
                if not isinstance(note_id, str) or not note_id.strip() or len(note_id) > 64:
                    raise BoardDomainError("boardErr_documentNeedsNote")
                if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                    raise BoardDomainError("boardErr_documentNeedsRevision")
                item["note_id"], item["note_revision"] = note_id.strip(), revision

        if kind == "scene":
            scene_id = entry.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                raise BoardDomainError("boardErr_sceneNeedsId")
            item["scene_id"] = scene_id.strip()

        asset_id = entry.get("asset_id")
        if asset_id is not None:
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="asset_id")
            item["asset_id"] = asset_id.strip()

        # 分组框「联动拖动」:开着的时候,拖动这个框会把框里的东西一起带走。
        #
        # **存下来而不是每次现开** —— 它是这个框的性质(「这一组是一个整体」),而不是一次
        # 操作的临时状态;重进画板时该还是那样。只有分组框有意义,别的类型给了就是写错了。
        move_children = entry.get("move_children")
        if move_children is not None:
            if not isinstance(move_children, bool):
                raise BoardDomainError("boardErr_itemFieldNotBool", item_id=item_id, field="move_children")
            if kind != "frame":
                raise BoardDomainError("boardErr_moveChildrenFrameOnly", kind=kind)
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
        #
        # **能产出、还没产出的一格一定写明产出者**(面板照 `form.producer` 挂,没有它就什么都不挂)。
        # 这里是这条规则唯一的一处:新建一格的路不止一条(画布的「添加」、智能体的 add_item、3D 场景页
        # 建的画板……),各自记得写的话,漏写的那一条造出来的格子选中了也没有面板,而且不报错。
        # 缺了按 producer_ids.SLOT_PRODUCERS 补;已经写明的不动。不是「猜」:它是新建时的缺省,
        # 和手动放下的一格得到的是同一个值。
        producer = missing_slot_producer(item)
        if producer is not None:
            item["form"] = {**item.get("form", {}), "producer": producer}

        items.append(item)

    raw_edges = raw.get("edges") or []
    if not isinstance(raw_edges, list):
        raise BoardDomainError("boardErr_canvasFieldNotArray", field="edges")
    edges: list[dict[str, Any]] = []
    for entry in raw_edges:
        if not isinstance(entry, dict):
            raise BoardDomainError("boardErr_edgeNotObject")
        source = str(entry.get("source") or "").strip()
        target = str(entry.get("target") or "").strip()
        # 连到不存在的项上,渲染时是一根悬空的线。存之前就把它挡住。
        if source not in seen or target not in seen:
            raise BoardDomainError("boardErr_edgeDangling", source=source, target=target)
        edge: dict[str, Any] = {"id": str(entry.get("id") or f"{source}->{target}"), "source": source, "target": target}
        label = entry.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise BoardDomainError("boardErr_edgeLabelNotString")
            edge["label"] = label[:200]
        edges.append(edge)
    _drop_detached_bindings(items, edges)

    # 标记和 items 平级,不混进去 —— 它不是画板项(没有素材、不生成、连不了线),
    # 混进去的话每一处遍历 items 的地方都要先分辨一次"这个是不是标记"。规则见 domain/markers。
    from app.domain.markers import MarkerError, normalize_markers

    try:
        markers = normalize_markers(raw.get("markers"))
    except MarkerError as exc:
        # 带着 key/params 转手,不 str(exc):那会把句子冻成转手这一刻的语言。
        raise BoardDomainError(exc.key, **exc.params) from exc

    return {"items": items, "edges": edges, "markers": markers}


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
        raise BoardNotFound("boardErr_notFound")
    return board


def ensure_revision(board: Board, base_revision: int | None) -> None:
    """调用方看到的是不是最新的这张板。**起任务之前**就要问 —— 等占位落地时才发现冲突,
    任务已经起了、钱已经花了,而产出没有地方放。"""
    if base_revision is not None and base_revision != board.revision:
        raise BoardRevisionConflict(base_revision, board.revision)


def _validate_references(
    db: Session, workspace_id: str, canvas: dict, existing: dict | None = None, *, assets: bool = True
) -> None:
    """画布上指向别处的东西在不在、对不对:3D 场景、文档,以及(`assets`)素材。

    `assets=False`:这一次写入是服务端自己落产出(回执)。那几份素材是产出者刚交回的,由回执那一侧
    按工作区查过(见 _asset_facts);在这里再拒一次的话,整封回执落不下,那一格就永远在转圈。
    """
    from app.db.models import Scene3D
    ids = {item['scene_id'] for item in canvas['items'] if item.get('scene_id')}
    if ids:
        owned = set(db.scalars(select(Scene3D.id).where(Scene3D.workspace_id == workspace_id, Scene3D.id.in_(ids))))
        if owned != ids:
            raise BoardDomainError("boardErr_sceneNotInWorkspace")

    from app.domain.notes import NoteDomainError, read_reference
    # 板上已经有的引用不再重新校验:源文档删掉之后,坏掉的引用照样能挪、能删、能复制。
    # **按「引用的是哪篇的哪一版」认,不按格子的 id 认** —— 画布上复制出来的那一格、副本里的
    # 那一格,和原来那格是同一份引用;按 id 认的话它们被当成新引用去校验,整张板存不下、复制不出。
    retained = {(item.get("note_id"), item.get("note_revision"))
                for item in (existing or {}).get("items", []) if item["kind"] == "document"}
    for item in canvas["items"]:
        if item["kind"] != "document" or not item.get("note_id"):
            continue
        if (item["note_id"], item["note_revision"]) in retained:
            continue
        try:
            ref = read_reference(db, workspace_id, item["note_id"], item["note_revision"])
            item["text"] = ref["title"]
        except NoteDomainError as exc:
            # 领域到领域的翻译:引用的文档有问题,对调用方来说是"这块画板存不下"。
            raise BoardDomainError(str(exc)) from exc

    if assets:
        _validate_asset_references(db, workspace_id, canvas, existing)


def _validate_asset_references(db: Session, workspace_id: str, canvas: dict, existing: dict | None) -> None:
    """一格的 `asset_id` 指着这个工作区里的一份素材,而且种类对得上格子(图片格放图片 —— 一段音频放进
    图片格,存得下、画出来却是一张裂图,生成时还会被当成参考图发出去)。

    **只查新引入的**,和文档同一条:板上已经有的「这种格子放这份素材」不再重新校验 —— 素材从库里删掉之后,
    那一格照样能挪、能删、能复制。按「哪种格子放哪份素材」认,不按格子的 id 认(复制出来的那一格是同一份引用)。
    """
    from app.db.models import Asset

    retained = {(item.get("kind"), item.get("asset_id"))
                for item in (existing or {}).get("items", []) if item.get("asset_id")}
    fresh = [item for item in canvas["items"]
             if item.get("asset_id") and (item["kind"], item["asset_id"]) not in retained]
    if not fresh:
        return
    ids = {item["asset_id"] for item in fresh}
    rows = db.execute(select(Asset.id, Asset.kind).where(Asset.workspace_id == workspace_id, Asset.id.in_(ids)))
    kinds = {str(asset_id): str(kind) for asset_id, kind in rows}
    for item in fresh:
        asset_kind = kinds.get(item["asset_id"])
        if asset_kind is None:
            raise BoardDomainError("boardErr_itemAssetNotInWorkspace", item_id=item["id"], asset_id=item["asset_id"])
        wanted = _ASSET_KIND_OF_ITEM.get(item["kind"])
        if wanted is not None and asset_kind != wanted:
            raise BoardDomainError("boardErr_itemAssetKindMismatch", item_id=item["id"], asset_id=item["asset_id"],
                                   kind=item["kind"], asset_kind=asset_kind)


def check_canvas(db: Session, workspace_id: str, raw: Any, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """一份画布存不存得下:形状(normalize_canvas)+ 引用(文档在不在、3D 场景和素材是不是这个工作区的、
    素材的种类对不对得上格子)。

    **落库和干跑共用这一道。** 智能体改画板时开卡前先干跑一遍,为的是写坏的算子在批准之前就失败;
    干跑只过形状的话,引用坏了要等用户点了同意才报错。`existing` 是这张板现在的样子(见
    _validate_references 里「已知引用」那一条)。
    """
    canvas = normalize_canvas(raw)
    _validate_references(db, workspace_id, canvas, existing)
    return canvas


def create_board(
    db: Session,
    *,
    workspace_id: str,
    name: str,
    canvas: Any = None,
    actor_id: str | None = None,
    copied_from: dict[str, Any] | None = None,
) -> Board:
    """`copied_from`:这张板照着哪份画布复制来的。那份上已有的引用算已知(见 _validate_references)。"""
    board = Board(
        workspace_id=workspace_id,
        name=(name or "").strip() or "新画板",
        canvas=check_canvas(db, workspace_id, canvas, copied_from),
    )
    db.add(board)
    db.flush()
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.created",
        subject_type="board",
        subject_id=board.id,
        summary="创建了无限画布",
        payload={"revision": board.revision},
    )
    db.commit()
    db.refresh(board)
    return board


def duplicate_board(
    db: Session, *, workspace_id: str, board_id: str, name: str = "", actor_id: str | None = None
) -> Board:
    """复制一张画板:同样的项、连线和标记,落成新的一张。

    **在跑的那几格不带过去。** 生成任务的回执认的是原板(见 receipt_to_item,board_id 写死在
    任务的 payload 里),便签写作也只写回原板那一格;副本里留着「在跑」的话,那一格永远等不到
    结束 —— 框里一直转圈,底下的提交键一直按不动。判据是**状态**(排队/运行中),不是有没有
    job_id:客户端的快照里在跑的那一格不一定带着 job_id,照样只落回原件。它们在副本里退回空槽:提示词和参数都还在,
    想要的话再点一次。前端「复制选中项」是同一条规则(boardItemState.copiedItem)。

    评论不跟着走:它们是对**那一张**的讨论,挂在原板的 subject_id 上。名字由调用方给(「× 副本」
    是界面语言里的一句话,这一层不替它挑语言);没给就沿用原名。
    """
    source = get_board(db, workspace_id, board_id)
    canvas = json.loads(json.dumps(source.canvas or {}))
    for item in canvas.get("items") or []:
        run = item.get("run")
        if isinstance(run, dict) and run.get("status") in ("queued", "running"):
            item.pop("run")
    return create_board(
        db,
        workspace_id=workspace_id,
        name=(name or "").strip() or source.name,
        canvas=canvas,
        actor_id=actor_id,
        copied_from=source.canvas,
    )


def update_board(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    name: str | None = None,
    canvas: Any = None,
    base_revision: int | None = None,
    actor_id: str | None = None,
    server_write: bool = False,
) -> Board:
    """改名和改画布是同一个入口,因为它们都是"这张板变了"。

    **两者都可以单独传**:自动保存只发 canvas,重命名只发 name —— 各发各的那一半,
    另一半不该被 None 覆盖掉。

    `server_write`:这一次写入是服务端**自己对某一格的合并**(摆生成占位、便签开始写、回执),
    不是客户端存回来的快照。那种写入不过 `_keep_server_owned_state` —— 那道闸防的是客户端
    拿着旧快照改动运行态,而服务端这几种写入本来就是在改运行态:重新生成时库里正好是上一轮的
    终态,新一轮的 running 会被当成旧快照打回去(后端新任务照常跑、照常扣钱,画布上却还挂着
    上次的失败);回执要把 running 收成终态,同样不能被「运行态归服务端」挡住。
    """
    board = get_board(db, workspace_id, board_id)
    expected = board.revision if base_revision is None else base_revision
    if expected != board.revision:
        raise BoardRevisionConflict(expected, board.revision)
    next_name = board.name
    next_canvas = board.canvas
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BoardDomainError("boardErr_nameEmpty")
        next_name = cleaned
    if canvas is not None:
        normalized = normalize_canvas(canvas)
        next_canvas = normalized if server_write else _keep_server_owned_state(board.canvas, normalized)
        _validate_references(db, workspace_id, next_canvas, board.canvas, assets=not server_write)
    if next_name == board.name and next_canvas == board.canvas:
        return board
    result = db.execute(
        update(Board)
        .where(
            Board.id == board_id,
            Board.workspace_id == workspace_id,
            Board.revision == expected,
        )
        .values(name=next_name, canvas=next_canvas, revision=Board.revision + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        db.rollback()
        current = get_board(db, workspace_id, board_id)
        raise BoardRevisionConflict(expected, current.revision)
    from app.domain.collaboration import record_activity

    action = "board.renamed" if name is not None and canvas is None else "board.updated"
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        subject_type="board",
        subject_id=board_id,
        summary="重命名了无限画布" if action == "board.renamed" else "编辑了无限画布",
        payload={"base_revision": expected, "revision": expected + 1},
    )
    db.commit()
    db.expire_all()
    return get_board(db, workspace_id, board_id)


def live_job(item: dict[str, Any] | None) -> str | None:
    """这一格正在跑的任务(排队或运行中、有 job_id)。没有就是 None。"""
    run = (item or {}).get("run") or {}
    if run.get("status") in ("queued", "running") and run.get("job_id"):
        return str(run["job_id"])
    return None


def _keep_server_owned_state(stored: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """**运行态和产出归服务端,客户端的快照改不动它们。**

    画板自动保存,而生成是异步的,客户端手上那份永远可能落后于服务端刚做的事:

    · **产出已经到了**,客户端存回来的还是占位 ——
        t1 客户端存了一份带占位(run 里有 job_id、没 asset_id)的画布;
        t2 任务跑完,回执把 asset_id 填进那一项;
        t3 用户又拖了一下,客户端把**它手上那份**存回来 —— 那份里还是占位。
      产出就这么没了,而且不报错:那一项看着还在转圈,可任务早就结束了。
    · **任务还在跑**,客户端存回来的是开跑之前的样子(撤销一步就是这样)—— 任务照跑、钱照花,
      画布上却成了一个能再点一次生成的空槽,于是第二份钱也花出去了。

    所以一项在库里已经有了产出或终态,而传来的那份还是占位,保留库里那个;一项在库里正跑着
    任务,传来的那份不是这一轮,保留这一轮。别的字段(位置、表单、文字)照客户端的来。
    客户端下一次拉到的就是服务端这份。
    """
    by_id = {str(item.get("id")): item for item in ((stored or {}).get("items") or [])}
    if not by_id:
        return incoming
    items = []
    for item in incoming["items"]:
        settled = by_id.get(str(item.get("id")))
        settled_run = (settled or {}).get("run") or {}
        live = live_job(settled)
        incoming_running = (item.get("run") or {}).get("status") in ("queued", "running")
        if live and live_job(item) != live:
            kept = {**item, "run": settled_run}
            kept.pop("asset_id", None)
            items.append(kept)
        elif settled and not item.get("asset_id") and settled.get("asset_id"):
            items.append({**item, "asset_id": settled["asset_id"], "run": settled.get("run", {"status": "succeeded"})})
        elif settled and incoming_running and settled_run.get("status") in ("succeeded", "failed", "cancelled"):
            # 任务结束后的下一次自动保存，客户端手里往往还是提交前的 running 快照。终态必须
            # 赢，否则它会把节点重新写活，界面就永远 loading。
            kept = {**item, "run": settled_run}
            # 便签上写字的产出是正文,没有 asset_id 可以充当「结果已到」的证据。服务端已经落下
            # 正文和清空后的表单时，晚到的 running 自动保存不能把三者一起覆盖回旧快照。
            if settled_run.get("status") == "succeeded" and settled.get("kind") == "note":
                kept["text"] = settled.get("text", "")
                kept["form"] = settled.get("form", {})
            items.append(kept)
        else:
            items.append(item)
    return {**incoming, "items": items}


def delete_board(db: Session, workspace_id: str, board_id: str, *, actor_id: str | None = None) -> None:
    board = get_board(db, workspace_id, board_id)
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.deleted",
        subject_type="board",
        subject_id=board_id,
        summary="删除了无限画布",
        payload={"name": board.name, "revision": board.revision},
    )
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


#: 服务端对**某一格**的合并(摆占位、写字、回执)在撞上并发写入时重试几次。
_MERGE_ATTEMPTS = 4


def _merge_into_latest(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    merge: Callable[[dict[str, Any]], dict[str, Any]],
    actor_id: str | None = None,
) -> Board:
    """把服务端的一次单格改动**合到最新的画布上**,冲突就重读再合。

    客户端存回来的是整份快照,它不知道别人刚改了什么,所以按 base_revision 挡回去是对的。
    服务端这几种写入不一样:它们只改自己那一格,从最新画布出发重做一遍 `merge` 就不会覆盖
    任何人。此前它们各自带着调用方的 base_revision 去 CAS —— 于是任务已经建好(钱已经在路上)
    之后,同一个人的一次自动保存恰好先落库,占位就撞 409:任务永远排着队,画布上什么都没有。
    版本该在**花钱之前**问(见 ensure_revision),花了之后只剩「把结果放对地方」。
    """
    for attempt in range(_MERGE_ATTEMPTS):
        board = get_board(db, workspace_id, board_id)
        db.refresh(board)
        canvas = merge(dict(board.canvas or {"items": [], "edges": []}))
        try:
            return update_board(
                db,
                workspace_id=workspace_id,
                board_id=board_id,
                canvas=canvas,
                base_revision=board.revision,
                actor_id=actor_id,
                server_write=True,
            )
        except BoardRevisionConflict:
            if attempt == _MERGE_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def place_pending(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item: dict[str, Any],
    actor_id: str | None = None,
) -> Board:
    """把某一项的「正在生成」状态放到画布上,再去起任务。

    **顺序是这样的原因**:生成要几十秒,而用户点完就在看画布。先放一个占位,他立刻看得见
    "这儿在生成";等回执把 asset_id 填回来,占位就地变成图片/视频。反过来(先起任务、
    等成功再放)的话,这几十秒里画布上什么都没有,用户会以为自己没点中。

    **按 id 就地更新,不存在才追加。** 画板上的生成有两个入口:工具条上「放一个空槽去
    生成」是新建一项,而在已有的空槽里写完提示词点生成,那一项**早就在画布上**了 ——
    无脑追加会撞上同 id 的自己,用户只是点了生成,却收到一句「画板项 id 重复」。

    就地更新时**保留它已有的位置和大小**:调用方只知道「它开始生成了」,不知道用户把它
    拖到哪儿、拉多大 —— 拿请求里的默认坐标覆盖,会让节点自己跳回左上角。

    **不收 base_revision。** 调用方在建任务之前已经问过版本(ensure_revision);到这里任务
    已经建好,只剩把占位合到最新画布上(见 _merge_into_latest)。
    """

    def merge(canvas: dict[str, Any]) -> dict[str, Any]:
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
        return {**canvas, "items": items}

    board = _merge_into_latest(db, workspace_id=workspace_id, board_id=board_id, merge=merge, actor_id=actor_id)
    return _deliver_if_already_settled(db, board, item)


def _deliver_if_already_settled(db: Session, board: Board, item: dict[str, Any]) -> Board:
    """占位落下时,它等的那个任务若已经结束,当场补送回执。

    念字、截取是「建任务即派发」:任务线程和摆占位的请求赛跑。很短的合成、源文件已经不在的截取,
    会在占位落下之前就落终态 —— 那封回执到的时候这一格还不是这一轮,被放过了(见
    _canvas_with_delivered_result),而这个任务不会再有第二封。不补的话那一格永远转圈。
    和正常送到的那封撞在一起也没关系:先落库的收掉这一轮,后到的那封就不再是「这一轮」了。
    """
    from app.db.models import Job
    from app.domain.jobs import TERMINAL_STATUSES

    job_id = live_job(item)
    job = db.get(Job, job_id) if job_id else None
    if job is None:
        return board
    db.refresh(job)
    if job.status not in TERMINAL_STATUSES:
        return board
    deliver_generated(db, job, receipt_to_item(board.id, str(item.get("id"))))
    return get_board(db, board.workspace_id, board.id)


#: 一次运行的产出是哪几种。和工作流的输出类型词表对得上的那一半(见 boards.tools.board_outputs)。
OUTPUT_TYPES = ("asset", "text", "json")


def outputs_of(job: Any) -> list[dict[str, Any]]:
    """一个任务交回了什么,归一成画板认的一种形状:
    `[{"type": "asset", "asset_id"}, {"type": "text", "text"}, {"type": "json", "value"}]`。

    **画板读任务结果只经过这一处。** 各种任务的结果本来就长得不一样 —— 生成一次可能出多张
    (`asset_ids`),念字、截取一次出一份(`asset_id`),便签上写字交回一段正文(`text`),工具格
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


#: 工具格跑一次最多在画布上新建几格。插件的输出没声明类型时是按值猜的,一个列表可能有几百项 ——
#: 全摊开的话画布被一次运行淹没。超出的那些合进最后一张 JSON 便签,一样不丢。
MAX_DERIVED_ITEMS = 12

#: 派生出来的几格离工具格多远、彼此隔多远(画布坐标)。上下留得宽一点:每一格的名字挂在框外正上方。
_DERIVED_GAP_X = 80.0
_DERIVED_GAP_Y = 48.0


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
    return None


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _clip(text: str) -> str:
    """便签正文有上限(MAX_TEXT_CHARS)。超了就截,并在末尾说一声 —— 整次回执因为一张便签太长
    被 normalize 拒掉的话,工具格会一直停在「在跑」。"""
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…"


def _overflow_value(output: dict[str, Any], assets: dict[str, tuple[str, str]]) -> Any:
    """超出上限的那几份产出合进一张 JSON 便签时,每一份写成什么。"""
    if output.get("type") == "asset":
        _, name = assets.get(str(output.get("asset_id") or ""), ("", ""))
        return {"asset_id": output.get("asset_id"), "name": name}
    if output.get("type") == "text":
        return output.get("text")
    return output.get("value")


def _derive(
    action: dict[str, Any],
    outputs: list[dict[str, Any]],
    assets: dict[str, tuple[str, str]],
    items: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """工具格这一轮的产出 → 新建的几格和连向它们的线。

    **每一轮都是新的一列,不覆盖上一轮。** 摆在工具格右边、再往右避开它此前产出的那几列;一列里
    从上往下排。上一轮的产出是用户可能已经拿去用的东西(连到了别处、改过字),重跑把它们换掉的话,
    下游悄悄变了。
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

    action_id = str(action["id"])
    by_id = {str(one.get("id")): one for one in items}
    earlier = [by_id[str(edge.get("target"))] for edge in edges
               if edge.get("source") == action_id and str(edge.get("target")) in by_id]
    right = max(
        [float(action.get("x") or 0) + float(action.get("width") or DEFAULT_SIZE["action"][0])]
        + [float(one.get("x") or 0) + float(one.get("width") or DEFAULT_SIZE.get(str(one.get("kind")), (0, 0))[0])
           for one in earlier]
    )
    x = right + _DERIVED_GAP_X
    y = float(action.get("y") or 0)
    taken = {str(one.get("id")) for one in items}
    new_items: list[dict[str, Any]] = []
    new_edges: list[dict[str, Any]] = []
    suffix = 0
    for one in made:
        suffix += 1
        while f"{action_id}-out-{suffix}" in taken:
            suffix += 1
        item_id = f"{action_id}-out-{suffix}"
        taken.add(item_id)
        width, height = DEFAULT_SIZE[one["kind"]]
        new_items.append({"id": item_id, **one, "x": x, "y": y, "width": float(width), "height": float(height)})
        new_edges.append({"id": f"{action_id}->{item_id}", "source": action_id, "target": item_id})
        y += height + _DERIVED_GAP_Y
    return new_items, new_edges


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
) -> dict[str, Any]:
    """Merge one asynchronous receipt into the newest board projection.

    The merge is deliberately pure so a compare-and-swap conflict can reload the latest canvas
    and retry without replaying any task side effects.

    **只收它自己那一轮**:那一格此刻跑的不是这个任务(占位还没落下、或已经是别的一轮),原样不动。
    占位与回执于是谁先谁后都一样 —— 先到的回执被放过,占位落下时补送(见 place_pending)。

    两种落法(ADR 0021 的「落点」):

    · **就地**:宿主是一个等着产出的槽(图片/视频/音频/便签)。产出(见 outputs_of)是素材
      (生成/念/截)或一段正文(便签上写字),第一份填进这一格,多出来的往右排;两样都没有就是没做成。
    · **派生**:宿主是工具格(`action`)。它自己不放产出,每一份产出都新建一格、连一条线(见 _derive);
      任务成功就算做成 —— 交回的东西落不成任何一格(全是空值)也是成功,只是右边没有新东西。
      表单(节点配置、绑定)**不清空**:工具格就是一份可以反复跑的配置。

    `assets`:产出里那些素材的种类和名字(回执那一侧从库里查好)—— 派生时靠它决定落成哪种格子。
    """
    asset_ids = [str(one["asset_id"]) for one in outputs if one.get("type") == "asset"]
    text = next((str(one["text"]) for one in outputs if one.get("type") == "text"), None)
    items = list(canvas.get("items") or [])
    edges = list(canvas.get("edges") or [])
    kept: list[dict[str, Any]] = []
    for item in items:
        if item.get("id") != item_id or live_job(item) != job_id:
            kept.append(item)
            continue
        derives = item.get("kind") == "action"
        if (derives and not succeeded) or (not derives and not asset_ids and text is None):
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
            kept.append({**item, "run": run})
            continue
        if derives:
            kept.append({**item, "run": {"status": "succeeded"}})
            new_items, new_edges = _derive(item, outputs, assets or {}, items, edges)
            kept.extend(new_items)
            edges.extend(new_edges)
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
        if text is not None:
            settled["text"] = text
        if not asset_ids:
            kept.append(settled)
            continue
        kept.append({**settled, "asset_id": asset_ids[0]})
        #: 多出来的那几张挨着它往右排。宽度按这一项自己的宽 —— 用户可能已经把它拉大了,
        #: 用一个写死的间距会让它们叠在一起。
        step = float(settled.get("width") or 260) + 24
        #: 新格子的 id 要避开**整张板上已有的**:同一格再出一次多张时,上一轮的 `-2` 还在板上,
        #: 照序号直接拼会撞上它 —— 整次回执被 normalize 拒掉,产出一张都落不回来,这一格永远在转圈。
        #: 位置跟着序号走(第 n 格在第 n-1 列),于是也不会正好叠在上一轮那一格上。
        taken = {str(one.get("id")) for one in items}
        suffix = 1
        for extra in asset_ids[1:]:
            suffix += 1
            while f"{item_id}-{suffix}" in taken:
                suffix += 1
            extra_id = f"{item_id}-{suffix}"
            taken.add(extra_id)
            kept.append(
                {
                    **settled,
                    "id": extra_id,
                    "x": float(settled.get("x") or 0) + step * (suffix - 1),
                    "asset_id": extra,
                }
            )

    # 连线可能指着刚被摘掉的那一项 —— normalize 会拒绝悬空的线,所以先把它们去掉。
    alive = {item["id"] for item in kept}
    edges = [edge for edge in edges if edge.get("source") in alive and edge.get("target") in alive]
    #: 只换 items 和 edges,**画布上别的层原样带着**(标记)。此前这里从零拼一个新字典,
    #: 于是每落回一次产出,用户放的标记就被 normalize 当成「没给」清空。
    return {**canvas, "items": kept, "edges": edges}


def _asset_facts(db: Session, workspace_id: str, outputs: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """产出里那些素材的种类和名字。**只认这个工作区里的** —— 别处的 id 当它不存在,不落到画布上。"""
    from app.db.models import Asset

    ids = {str(one.get("asset_id")) for one in outputs if one.get("type") == "asset" and one.get("asset_id")}
    if not ids:
        return {}
    rows = db.scalars(select(Asset).where(Asset.id.in_(ids), Asset.workspace_id == workspace_id))
    return {row.id: (str(row.kind or ""), str(row.name or row.id)) for row in rows}


def deliver_generated(db: Session, job: Any, receipt: dict[str, Any]) -> None:
    """任务落终态 → 把产出填进画板上那一项(工具格:新建成右边的几格,见 _canvas_with_delivered_result)。

    **成功和失败都要处理。** 失败时保留可重试的节点并结束转圈状态。

    **一次可能出多张。** 第一张落进占位，其余产出挨着它向右排列。

    **回执也遵守乐观并发。** 用户可能在任务完成的同一刻移动节点；冲突时重新读取最新画布，
    只把任务终态合并进去再 CAS，既不覆盖用户编辑，也不让已完成的结果丢失。
    """
    from app.domain.jobs import was_cancelled

    board_id = str(receipt.get("board_id") or "")
    item_id = str(receipt.get("item_id") or "")
    if not board_id or not item_id:
        return

    job_status = str(job.status)
    actor_id = getattr(job, "created_by", None)
    outputs = outputs_of(job)
    #: 这一格为什么没拿到产出。任务成功结束却什么都没交回,原因就是这句话本身 —— 任务那一侧
    #: 没有 error 可给;失败/取消用任务自己记下的原因。
    reason = tr("boardErr_noOutput") if job_status == "succeeded" else str(getattr(job, "error", "") or "")

    board = db.get(Board, board_id)
    if board is None:
        return
    assets = _asset_facts(db, board.workspace_id, outputs)
    _merge_into_latest(
        db,
        workspace_id=board.workspace_id,
        board_id=board.id,
        merge=lambda canvas: _canvas_with_delivered_result(
            canvas, item_id=item_id, job_id=str(job.id), outputs=outputs, reason=reason,
            cancelled=was_cancelled(job), succeeded=job_status == "succeeded", assets=assets,
        ),
        actor_id=actor_id,
    )
    logger.info("board %s item %s -> %s", board_id, item_id,
                ", ".join(one.get("asset_id") or f"({one['type']})" for one in outputs) or "(failed)")


def install() -> None:
    """把画板的回执登记进任务总线。

    **方向是反的**:任务不认识画板,是画板认识任务 —— 和智能体那条回执同一个做法
    (见 domain/agent/receipts 开头那段)。登记在组合层(app/main._wire_seams)的**导入期**,
    不在 lifespan 里:不跑 lifespan 的入口(TestClient、脚本)照样要能把产出填回画布。
    """
    from app.domain.jobs import register_receipt_deliverer

    register_receipt_deliverer(RECEIPT_KIND, deliver_generated)

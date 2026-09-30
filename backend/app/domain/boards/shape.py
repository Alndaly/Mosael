"""画布的形状:能放什么、上限多少、`normalize_canvas` 把外面传进来的画布校验并归一。

不碰数据库 —— 引用在不在由 validation 查,读写由 persistence 做。"""

from __future__ import annotations

import json
from typing import Any

from app.domain.boards.errors import BoardDomainError, _field_error
from app.domain.boards.producer_ids import is_producer_id, missing_slot_producer


#: 画板上能放什么。
#:
#: `note` 便签(文字)、`image` 图片、`video` 视频、`audio` 音频、`frame` 分组框(圈起来命名)。
#:
#: 图片和视频**分开两种而不是合成一个 media**:它们在画板上的样子和操作都不同 ——
#: 图片是一张静止的参考,视频要能就地播;而"从这张图生成视频"是图片才有的动作,
#: 反过来"抽一帧"是视频才有的。合成一种的话每处都要先分辨一次它到底是哪个。
#:
#: **没有单独的工具格。** 把内容变成新内容的工具(转写、翻译、分离人声、ComfyUI 的一张工作流……)是内容格
#: 自己的**能力**(`form.abilities`,见 _normalize_abilities),产出新建成宿主右边的几格;凭空出图出片的生成器是
#: 空格子的一种填法(`form.producer`)。此前的 `action` 格由迁移 migrate-board-tool-cells-become-abilities
#: 搬到了它接着的内容格上(ADR 0025 修订「能力住在内容格上」)。
#:
#: **资产格**(`entity`,ADR 0027):引用资产库里的一个人物 / 场景 / 道具(`entity_id`),显示封面、名字和种类。
#: 它能当生成格的上游 —— 连进去就和在提示词里 `@` 它一样(见 actions.generate_on_board)。它自己不产出东西;
#: 「补全多角度」「生成表情」这类能力是阶段 4 的事,到时照内容格能力的做法挂在它身上(`form.abilities`)。
ITEM_KINDS = ("note", "image", "video", "audio", "frame", "scene", "document", "entity", "sequence")

#: 便签正文的格式。只有一种非默认的:能力交回的结构化数据(JSON)落成的便签,界面按代码排版。
TEXT_FORMATS = ("json",)

#: 新建时的默认大小。**和前端 DEFAULT_SIZE 是同一组数** —— 智能体加的项不该比手动加的
#: 小一圈,那看起来像两种不同的东西;能力派生出来的几格也按它摆(见 _derive)。
DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "note": (220, 140),
    "image": (260, 180),
    "video": (320, 200),
    "audio": (280, 72),
    "frame": (420, 300),
    "scene": (320, 220),
    "document": (320, 300),
    "entity": (220, 280),
    #: 时间线格(ADR 0030):上半预览、下半一条缩略图条。
    "sequence": (560, 400),
}

#: 素材在画板上**有自己那种格子**的几种:一份图片 / 视频 / 音频素材放进同名的格子里。能力交回的素材按它
#: 落成同种格子,别的文件落成写着名字的便签(见 _derived_item)。它们不是「必须带素材」:没有素材的
#: 是空槽,合法(见 normalize_canvas 里「空槽是合法的」那一段)。
_MEDIA_KINDS = ("image", "video", "audio")


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
    #: 上一次自动填进提示词的那段上游文字(面板照它认「提示词还是自动填的,上游改了就跟着换」)。
    #: 存在表单上而不是面板里:重新选中这一格时面板是新挂的,记在面板里的话一挂就忘了。
    prefilled = form.get("prefilled")
    if prefilled is not None:
        if not isinstance(prefilled, str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="form.prefilled")
        if len(prefilled) > MAX_TEXT_CHARS:
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
    #: 提示词里 `@` 到的资产(ADR 0027):生成时展开成提示词描述和参考图(见 domain/entities/mentions)。
    entities = form.get("mentioned_entity_ids")
    if entities is not None:
        if not isinstance(entities, list):
            raise BoardDomainError("boardErr_itemFieldNotArray", item_id=item_id, field="form.mentioned_entity_ids")
        form["mentioned_entity_ids"] = list(dict.fromkeys(str(one).strip() for one in entities if str(one).strip()))
    #: 连进来的 3D 场景怎么用(ADR 0029 §2):镜头、用法。和生成表单(producers.SceneReferenceForm)同形。
    reference = form.get("scene_reference")
    if reference is not None:
        if (not isinstance(reference, dict) or set(reference) - {"shot_id", "use"}
                or not isinstance(reference.get("shot_id", ""), str)
                or reference.get("use", "composition") not in ("composition", "frames", "motion")):
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="form.scene_reference")
        form["scene_reference"] = {"shot_id": str(reference.get("shot_id") or "").strip()[:128],
                                   "use": str(reference.get("use") or "composition")}
    trim = form.get("trim")
    if trim is not None:
        form["trim"] = _normalize_trim(trim, item_id)
    prompt_document = form.get("prompt_document")
    if prompt_document is not None:
        if not isinstance(prompt_document, dict) or prompt_document.get("type") != "doc":
            raise BoardDomainError("boardErr_promptDocumentNotDoc", item_id=item_id)
        if len(json.dumps(prompt_document, ensure_ascii=False)) > MAX_TEXT_CHARS * 8:
            raise BoardDomainError("boardErr_promptDocumentTooLarge", item_id=item_id)
    #: 这一格自己的节点产出者(空格子上的生成器、3D 场景格渲白模)的配置和绑定。
    if form.get("config") is not None:
        _check_config(form["config"], item_id, "form.config")
    bindings = form.get("bindings")
    if bindings is not None:
        form["bindings"] = _normalize_bindings(bindings, item_id)
    abilities = form.get("abilities")
    if abilities is not None:
        form["abilities"] = _normalize_abilities(abilities, item_id)
    return form


def _check_config(config: Any, item_id: str, field: str) -> None:
    """一份节点配置(键就是那个节点声明的字段)。**形状只钉到「是个对象、不太大」** —— 哪些
    键合法由节点自己的声明说了算,而插件节点是运行时才知道的;字段错了在运行时由执行器报。"""
    if not isinstance(config, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field=field)
    try:
        #: 和坐标同一条(见 finite_number):NaN / Infinity 写得进去、读不回来 —— 整张板打不开。
        size = len(json.dumps(config, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field=field) from exc
    if size > MAX_TEXT_CHARS * 8:
        raise BoardDomainError("boardErr_formConfigTooLarge", item_id=item_id)


#: 一项能力存在宿主上的那一份设置里有的键(和 producers.NodeForm 同形)。
_ABILITY_KEYS = frozenset({"config", "bindings"})


def _normalize_abilities(value: Any, item_id: str) -> dict[str, dict[str, Any]]:
    """这一格的**能力**上次用的设置:`{产出者: {"config": {…}, "bindings": {字段: [{"from": 上游}]}}}`。

    能力是内容格自己会做的事(音频格转写、便签翻译,见 boards.transforms 的 `ability`),每一项的设置存在
    宿主这一格上、按产出者分开放 —— 再打开那一项时还是上次的样子;宿主自己那一份表单(它空着时怎么被填、
    写字的提示词)不动,两份不混。**只认名字** —— 和 `form.producer` 同一条:插件卸了,设置照样存得下、
    读得回,只是那一项此刻不在操作条上。绑定只能接连进这一格的上游(断了的在 _drop_detached_bindings 摘掉);
    宿主自己的内容不是绑定 —— 它就是宿主。
    """
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.abilities")
    out: dict[str, dict[str, Any]] = {}
    for producer, entry in value.items():
        field = f"form.abilities.{producer}"
        if not is_producer_id(producer):
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field=field)
        if not isinstance(entry, dict) or set(entry) - _ABILITY_KEYS:
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field=field)
        normalized: dict[str, Any] = {}
        if entry.get("config") is not None:
            _check_config(entry["config"], item_id, f"{field}.config")
            normalized["config"] = dict(entry["config"])
        if entry.get("bindings") is not None:
            normalized["bindings"] = _normalize_bindings(entry["bindings"], item_id)
        out[producer] = normalized
    return out


def _normalize_bindings(value: Any, item_id: str) -> dict[str, list[dict[str, str]]]:
    """节点产出者(能力、空格子上的生成器)「这个字段的值从上游哪几格来」:`{字段: [{"from": 上游那一格的 id}, …]}`。

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
    · 节点产出者的绑定:空格子上生成器的(`form.bindings`)和每一项能力的(`form.abilities[…].bindings`),
      字段的值从哪几格来。线没了、上游那一格没了,那一条就摘掉。

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
            attached = _attached(bindings, item["id"], wired, by_id)
            if attached != bindings:
                form = item["form"] = {**form, "bindings": attached}
        abilities = form.get("abilities")
        if abilities:
            kept = {
                producer: {**entry, "bindings": _attached(entry["bindings"], item["id"], wired, by_id)}
                if entry.get("bindings") else entry
                for producer, entry in abilities.items()
            }
            if kept != abilities:
                item["form"] = {**form, "abilities": kept}


def _attached(
    bindings: dict[str, list[dict[str, str]]],
    item_id: str,
    wired: set[tuple[str, str]],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    """一份绑定里线还在、上游那一格也还在的那几条。一个字段的线全断了,这个字段就不再是「接上游」的 ——
    整个字段摘掉,不留一个空列表。"""
    attached = {
        field: [ref for ref in refs if (ref["from"], item_id) in wired and ref["from"] in by_id]
        for field, refs in bindings.items()
    }
    return {field: refs for field, refs in attached.items() if refs}


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
    #: 这一轮跑的是这一格的哪一项能力(见 producer_ids.ability_of)。没有就是它自己的产出者。
    ability = value.get("ability")
    if ability is not None:
        if not is_producer_id(ability):
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="run.ability")
        run["ability"] = ability
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
            #: 文档格引用**一篇笔记或一份文档素材**,二选一:笔记能让 AI 写,素材是只读的来源(PDF / PPT 原件)。
            if note_id is not None and entry.get("asset_id") is not None:
                raise BoardDomainError("boardErr_documentNoteOrAsset", item_id=item_id)

        if kind == "scene":
            #: 3D 场景格可以先空着:放下一格,连一段剧本进来按剧本搭(scene_from_text 是空场景格的一种填法)。
            #: 写了就得是一个正经的 id。
            scene_id = entry.get("scene_id")
            if scene_id is not None:
                if not isinstance(scene_id, str) or not scene_id.strip():
                    raise BoardDomainError("boardErr_sceneNeedsId")
                item["scene_id"] = scene_id.strip()

        if kind == "sequence":
            #: 时间线格背后是一条正常的 Mosael 时间线(ADR 0030):放下时就建好了,所以一定带着 id。
            sequence_id = entry.get("sequence_id")
            if not isinstance(sequence_id, str) or not sequence_id.strip() or len(sequence_id) > 64:
                raise BoardDomainError("boardErr_sequenceNeedsId")
            item["sequence_id"] = sequence_id.strip()

        if kind == "entity":
            entity_id = entry.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id.strip() or len(entity_id) > 64:
                raise BoardDomainError("boardErr_entityNeedsId")
            item["entity_id"] = entity_id.strip()

        asset_id = entry.get("asset_id")
        #: 3D 场景格**就是一个场景**,不存图(ADR 0029 §1):格子上画的是场景的全景白模(现渲),连到下游时给的是
        #: 场景,不是某一帧。此前它存着编辑器里导出过的一帧,格子上看到的和喂给下游的不是一张,还会过期。
        if kind == "scene" and asset_id is not None:
            raise BoardDomainError("boardErr_sceneHasNoAsset", item_id=item_id)
        if kind == "sequence" and asset_id is not None:
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="asset_id")
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

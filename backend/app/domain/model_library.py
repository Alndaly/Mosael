"""模型库(ADR 0034):认领 `model_library` 的连接上有哪些模型文件 —— 宿主这一侧。

插件回答四件事(`op`):列出全部模型文件、一个文件的完整元数据、一个链接指的是什么、把它下到那台服务器上。宿主做的是
插件做不了、也不该做的那几样:

- **规整**:插件报的每一条都过一遍(没有目录或名字的丢掉、长文本截断、只认 http(s) 的声明地址),界面拿到的形状只有一种;
- **预览图**:插件给的是那台服务器上的地址(连同取它要带的头),在 Civitai 上对上了版本的还有几张示例图的地址。宿主按
  这个连接的出站决定去取、记进磁盘缓存,再交给界面(见 model_previews)—— 和插件交回 `url` 的产出同一个规矩;那一头的
  地址和凭据不进给界面的回答;
- **NSFW**:插件交的依据、库里记着的手动标记合成一个判断(ADR 0038 §9);
- **下载**:一个后台任务(`model_download`),进度、取消走流式协议;下完让这个连接的目录重新拉一遍,生成表单里选模型的
  下拉马上有它。

**这里不认识 ComfyUI**:任何认领 `model_library` 的连接,插件页上都有一行「模型库」。列表不存库(每次现问插件,插件自己
记着逐个读的元数据);宿主只在内存里记着「哪个文件的预览图在哪」,重启后界面直接要预览图时先替它列一遍。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, fragment
from app.core.unit_of_work import unit_of_work
from app.db.models import Job, ModelFileMark, PluginInstance, User
from app.domain import capabilities, model_nsfw_local, model_previews
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say
from app.domain.permissions import ensure_workspace_perm
from app.domain.plugins import egress as plugin_egress
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import MODEL_LIBRARY
from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
from app.domain.plugins.tools import MAX_GENERATION_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

#: 下载任务的种类(见 job_catalog)。
KIND = "model_download"
#: 列一遍最多等多久。第一次要逐个读文件头(530 个文件、一次约 40ms),插件记下之后第二次只读目录。
LIBRARY_TIMEOUT_SECONDS = 600
#: 读一个文件的元数据、解析一个链接:一两个请求的事。
QUICK_TIMEOUT_SECONDS = 120
#: 模型库里列出最近几条下载(在跑的总在里面)。
RECENT_DOWNLOADS = 10

_MAX_MODELS = 20000
_MAX_LIST = 50
_MAX_TRIGGERS = 30
_MAX_METADATA_KEYS = 400
_MAX_METADATA_VALUE = 4000
_MAX_TAGS = 100


class ModelLibraryError(LocalizedError, ValueError):
    """模型库这一侧说不行(这个连接不提供模型库、文件名不对、链接不是 http(s))。带文案 key(`modelLibErr_*`)。"""


@dataclass
class _Snapshot:
    """最近一次列出来的:每个文件的预览图在那台服务器上的哪儿、取它要带的头,别处(Civitai)的几张示例图,插件交的 NSFW
    依据(手动标记改了之后重算判断用,不用再让插件列一遍),来源和对上 Civitai 的方式。只在内存里。"""

    previews: dict[tuple[str, str], str] = field(default_factory=dict)
    #: 那台服务器上模型旁边的几处(预览视频、带 [ ] 的文件名的图),预览接口没有时按名字直接读
    sidecars: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    #: 那台服务器上预览图的原文件(预览接口给的是现转的有损 WebP):本机识别看它
    originals: dict[tuple[str, str], str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    signals: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    elsewhere: dict[tuple[str, str], list[model_previews.Elsewhere]] = field(default_factory=dict)
    how: dict[tuple[str, str], str] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)

    def files(self) -> list[tuple[str, str]]:
        """列出来的全部文件(目录, 名字)。"""
        return list(self.elsewhere)


_lock = threading.Lock()
_snapshots: dict[str, _Snapshot] = {}
#: 一个连接一把:记着的地址没了时,同时到的几十个预览请求只让插件列一遍,别的等它列完。
_listing_locks: dict[str, threading.Lock] = {}


def forget(instance_id: str | None = None) -> None:
    """忘掉记着的预览图地址(一个连接,或全部)。连接变了(换了服务器)时调;测试用它模拟重启。"""
    with _lock:
        if instance_id is None:
            _snapshots.clear()
        else:
            _snapshots.pop(instance_id, None)
    model_previews.forget(instance_id)


def drop_cache(instance_id: str) -> None:
    """连接删掉了:记着的地址和磁盘上的预览图一起清掉。"""
    forget(instance_id)
    model_previews.drop_cache(instance_id)


def _require(db: Session, instance: PluginInstance) -> None:
    if MODEL_LIBRARY not in inst.manifest_for(db, instance).provides:
        raise ModelLibraryError("modelLibErr_notProvided", name=instance.name)


def _text(value: Any, limit: int = 500) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _http(url: Any) -> str:
    """只认 http(s) 的地址;别的(`file://`、相对路径)当没给。"""
    text = _text(url, 4000)
    return text if urlsplit(text).scheme in ("http", "https") and urlsplit(text).hostname else ""


def _refs(value: Any) -> list[dict[str, str]]:
    """「哪几张工作流」:`[{id, label}]`。"""
    out: list[dict[str, str]] = []
    for one in value if isinstance(value, list) else []:
        if isinstance(one, dict) and _text(one.get("id")):
            out.append({"id": _text(one.get("id")), "label": _text(one.get("label")) or _text(one.get("id"))})
    return out[:_MAX_LIST]


def _sidecars(value: Any, base: str) -> list[str]:
    """插件列的「模型旁边的文件」(相对 `sidecar_base` 的一段,或整个地址)→ 取它们的地址。只认 http(s)。"""
    out = [_http(urljoin(base, one) if base else one) for one in value if isinstance(one, str)] if isinstance(value, list) else []
    return [one for one in out if one][:12]


def _model(raw: Any, base: str = "") -> tuple[dict[str, Any], str] | None:
    """插件报的一条模型文件 → 给界面的那一份,外加它的预览图地址(不交给界面)。"""
    if not isinstance(raw, dict):
        return None
    folder, name = _text(raw.get("folder"), 200), _text(raw.get("name"), 1000)
    if not folder or not name:
        return None
    size = _number(raw.get("size"))
    triggers = [_text(one, 200) for one in raw.get("triggers") or [] if _text(one, 200)][:_MAX_TRIGGERS]
    # 预览地址可以是相对 `preview_base` 的一段(几千个文件时省下回答的体积,插件的一次回答有上限)。
    preview = _http(urljoin(base, raw["preview"]) if base and isinstance(raw.get("preview"), str) else raw.get("preview"))
    return {
        "nsfw_signals": _signals(raw.get("nsfw_signals")),
        "elsewhere": model_previews.elsewhere(raw.get("remote_previews")),
        "source": _source(raw.get("source")),
        "folder": folder,
        "name": name,
        "size": int(size) if size is not None else None,
        "modified": _number(raw.get("modified")),
        "family": _text(raw.get("family"), 80),
        "family_source": _text(raw.get("family_source"), 40),
        "encoder": _encoder(raw.get("encoder")),
        "triggers": triggers,
        "triggers_source": _text(raw.get("triggers_source"), 40) if triggers else "",
        "title": _text(raw.get("title"), 300),
        "has_preview": bool(preview),
        "used_by": _refs(raw.get("used_by")),
    }, preview


#: 文本编码器的种类、工作台的 type 都是插件起的短名(`t5_xxl`、`qwen3vl_4b`、`stable_diffusion`)。
_KIND = re.compile(r"[a-z0-9_]{1,40}")
#: 一个文本编码器最多列几种常配的底模。
_MAX_PAIRS = 24


def _kinds(value: Any) -> list[str]:
    return [one for one in value if isinstance(one, str) and _KIND.fullmatch(one)][:64] if isinstance(value, list) else []


def _encoder(value: Any) -> dict[str, Any] | None:
    """文本编码器那一格:`kind`(哪一种,认不出是空串 —— 仍是文本编码器)、`label`(给人看的名字)、`source`(`weights`
    从权重认出 / `filename` 按文件名猜的)、`pairs`(常配哪几种底模,家族名)。不是文本编码器的文件没有这一格(None)。"""
    if not isinstance(value, dict):
        return None
    kind = _text(value.get("kind"), 40)
    if not _KIND.fullmatch(kind):
        return {"kind": "", "label": "", "source": "", "pairs": []}
    source = _text(value.get("source"), 20)
    pairs = [_text(one, 80) for one in value.get("pairs") or [] if _text(one, 80)] if isinstance(value.get("pairs"), list) else []
    return {"kind": kind, "label": _text(value.get("label"), 80) or kind,
            "source": source if source in ("weights", "filename") else "", "pairs": pairs[:_MAX_PAIRS]}


#: 一种节点最多认几种 type(ComfyUI 0.39 的 CLIPLoader 列着 40 来种)。
_MAX_TYPES = 200
#: 节点上一格的名字(ComfyUI 的输入名:`type`、`clip_name1`……)。
_WIDGET = re.compile(r"[A-Za-z0-9_.-]{1,200}")


def _node_encoders(value: Any) -> dict[str, Any] | None:
    """工作台里选文本编码器的那一格:节点上选 type 的那一格(`type_widget`;没有 type 可选的是 None)和每一种 type 的配方
    (`by_type`:在配方里的几种 `fits`、ComfyUI 不看 type 的几种 `any_type`)。不像种类名的 type、没有一种合用的配方丢掉;
    一项都不剩、或者没有 type 可选却不止一项,整格不要。不是这种格子是 None。"""
    if not isinstance(value, dict):
        return None
    widget = value.get("type_widget")
    if widget is not None and not (isinstance(widget, str) and _WIDGET.fullmatch(widget)):
        return None
    raw = value.get("by_type") if isinstance(value.get("by_type"), dict) else {}
    by_type: dict[str, dict[str, list[str]]] = {}
    for kind, recipe in list(raw.items())[:_MAX_TYPES]:
        fits = _kinds(recipe.get("fits")) if isinstance(recipe, dict) else []
        if isinstance(kind, str) and _KIND.fullmatch(kind) and fits:
            by_type[kind] = {"fits": fits, "any_type": _kinds(recipe.get("any_type"))}
    if not by_type or (widget is None and len(by_type) != 1):
        return None
    return {"type_widget": widget, "by_type": by_type}


def _source(value: Any) -> dict[str, str] | None:
    """这个文件的出处:`page`(原站上那一页,只认 http(s))、`site`、`how`(怎么知道的:`download` 经 Mosael 下载时记下的、
    `sha256` 按文件哈希对上的、`filename` 按文件名和大小对上的、`metadata` 文件自带的)。没有页就是 None —— 不猜。"""
    if not isinstance(value, dict) or not _http(value.get("page")):
        return None
    return {"page": _http(value.get("page")), "site": _text(value.get("site"), 40), "how": _text(value.get("how"), 40)}


def _preview_tools(value: Any) -> dict[str, Any]:
    """这台服务器上找预览图、写回预览图的路:`lookup`(`sha256` 能按哈希找 / `filename` 只能按文件名和大小找),`save`
    (能不能写回),`save_note`(写不回时说缺什么)。"""
    raw = value if isinstance(value, dict) else {}
    lookup = _text(raw.get("lookup"), 20)
    return {"lookup": lookup if lookup in ("sha256", "filename") else "", "save": bool(raw.get("save")),
            "save_note": _text(raw.get("save_note"), 1000)}


def _preview_fields(instance_id: str, model: dict[str, Any], server: str, choices: list[model_previews.Elsewhere],
                    pick: str) -> tuple[dict[str, Any], model_previews.Elsewhere | None]:
    """给界面的预览图那几格:有没有(`has_preview`)、显示的是哪儿的(`preview_origin`:`server` 那台服务器上的、
    `civitai` 这类别处的示例图,还没取过、说不准是空串)。那台服务器上取过、说没有,才换成别处的那张。"""
    chosen = model_previews.pick(choices, pick)
    status = model_previews.server_status(instance_id, model["folder"], model["name"])
    origin = "server" if status == "found" else (chosen.site or "elsewhere") if chosen and (status == "absent" or not server) else ""
    shown = chosen if origin and origin != "server" else None
    kind = model_previews.server_kind(instance_id, model["folder"], model["name"]) if origin == "server" else \
        shown.kind if shown else ""
    return {"has_preview": bool(server or chosen), "preview_origin": origin, "preview_kind": kind or "image"}, shown


def library(db: Session, instance: PluginInstance, pick: str = "safest") -> dict[str, Any]:
    """现问插件:这个连接上的全部模型文件,规整好交给界面;顺手记下每个文件的预览图在哪。`pick`:别处的示例图挑哪一张
    (界面按「NSFW 预览」那组设置要,见 model_previews.pick),预览图从哪来和 NSFW 的判断都照它。"""
    _require(db, instance)
    # 不留调用记录:打开模型库、下完一个文件都会列一遍,每次一行会把插件页真正的调用淹掉(和目录指纹同一个理由)。
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "library"},
                               timeout=LIBRARY_TIMEOUT_SECONDS, record=False)
    models: list[dict[str, Any]] = []
    snapshot = _Snapshot(headers={str(k): str(v) for k, v in (output.get("preview_headers") or {}).items()},
                         tools=_preview_tools(output.get("preview_tools")))
    marks = _marks(db, instance.id)
    route: list[plugin_egress.Egress] = []

    def lossless(url: str) -> model_previews.Media | None:
        """原文件那一处(取它走这个连接的出站,只问一次出站)。"""
        if not url:
            return None
        if not route:
            route.append(plugin_egress.resolve(db, instance, inst.manifest_for(db, instance)))
        return model_previews.Media(url, dict(snapshot.headers), server=True)

    for raw in (output.get("models") or [])[:_MAX_MODELS]:
        found = _model(raw, _http(output.get("preview_base")))
        if found is None:
            continue
        model, preview = found
        key = (model["folder"], model["name"])
        sidecars = _sidecars(raw.get("sidecars"), _http(output.get("sidecar_base")))
        original = next(iter(_sidecars([raw.get("preview_file")], _http(output.get("sidecar_base")))), "")
        choices = model.pop("elsewhere")
        fields, shown = _preview_fields(instance.id, model, preview or (sidecars[0] if sidecars else ""), choices, pick)
        model.update(fields)
        signals = with_elsewhere_signal(model.pop("nsfw_signals"), shown)
        # 本机识别:显示着的那张(别处的那张,或那台服务器上先后试的那几处里已经取回来的),按缓存里那份原样记结果;
        # 那台服务器上的有原文件就看原文件(不看 ComfyUI 现转的有损 WebP)
        cached = model_previews.cached_original(
            instance.id, [shown.url] if shown else [one for one in (preview, *sidecars) if one])
        local = model_nsfw_local.signal(model_nsfw_local.Source(
            cached[0], cached[1], instance.id, None if shown else lossless(original), route[0] if route else None,
        )) if cached else None
        if local:
            signals = [*signals, local]
        model["nsfw"] = nsfw_verdict(marks.get((model["folder"], _norm(model["name"]))), signals)
        models.append(model)
        snapshot.signals[(model["folder"], _norm(model["name"]))] = signals
        snapshot.elsewhere[key] = choices
        snapshot.how[key] = (model["source"] or {}).get("how", "")
        if preview:
            snapshot.previews[key] = preview
        if sidecars:
            snapshot.sidecars[key] = sidecars
        if original:
            snapshot.originals[key] = original
    with _lock:
        _snapshots[instance.id] = snapshot
    folders = [
        {"name": _text(one.get("name"), 200), "count": int(_number(one.get("count")) or 0)}
        for one in output.get("folders") or [] if isinstance(one, dict) and _text(one.get("name"), 200)
    ]
    missing = [
        {"folder": _text(one.get("folder"), 200), "name": _text(one.get("name"), 1000), "url": _http(one.get("url")),
         "workflows": _refs(one.get("workflows"))}
        for one in output.get("missing") or [] if isinstance(one, dict)
    ]
    route = output.get("download") if isinstance(output.get("download"), dict) else {}
    return {
        "folders": folders,
        "models": models,
        "missing": [one for one in missing if one["folder"] and one["name"] and one["url"]][:_MAX_LIST * 4],
        "download": {"route": _text(route.get("route"), 40) or "none", "note": _text(route.get("note"), 2000)},
        "downloads": downloads(db, instance),
        "preview_tools": snapshot.tools,
    }


# --- NSFW:几种依据合成一个判断(ADR 0038 §9) ---------------------------------
#
# 依据有四种:**手动标记**(这里记在库里,两头都能标)、**元数据推断**和 **Civitai 的标记**(插件交的,见插件的
# nsfw.py)、**本机识别预览图**。手动标了就听手动的;没标时任何一种自动的说「是」就算是 —— 这个判断是拿来
# 「当众打开时先藏起来」的,宁可多藏一张(点开、悬停、改标记都能看),不放过一张。界面上悬停看得到每一条依据。

#: 依据从哪来,界面按这个顺序列。
NSFW_SOURCES = ("civitai", "local", "metadata")
_MAX_NSFW_WORDS = 8


def _norm(name: str) -> str:
    """Windows 上 ComfyUI 报的相对路径是反斜杠:记标记、找标记前统一成正斜杠。"""
    return name.replace("\\", "/").strip()


def _words(value: Any) -> list[str]:
    return [_text(one, 80) for one in value if _text(one, 80)][:_MAX_NSFW_WORDS] if isinstance(value, list) else []


def _signals(value: Any) -> list[dict[str, Any]]:
    """插件交的 NSFW 依据规整成一种形状:`{source, nsfw, tags?, words?, level?}`。来源只认插件说得出的那两种。"""
    out: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or raw.get("source") not in ("metadata", "civitai") or \
                not isinstance(raw.get("nsfw"), bool):
            continue
        entry: dict[str, Any] = {"source": raw["source"], "nsfw": raw["nsfw"]}
        for key in ("tags", "words"):
            if _words(raw.get(key)):
                entry[key] = _words(raw.get(key))
        level = _number(raw.get("level"))
        if level is not None:
            entry["level"] = int(level)
        if all(one["source"] != entry["source"] for one in out):
            out.append(entry)
    return out


def with_elsewhere_signal(signals: list[dict[str, Any]],
                          shown: model_previews.Elsewhere | None) -> list[dict[str, Any]]:
    """显示的是别处的那张示例图时,它自己的分级就是关于**这张图**最直接的依据:换下插件交的那一条同来源的(说的是模型),
    换成这张图的(`level`)。"""
    if shown is None:
        return signals
    own = {"source": shown.site, "nsfw": shown.nsfw, "level": shown.level}
    return [one for one in signals if one["source"] != shown.site] + [own] if shown.site in NSFW_SOURCES else signals


def nsfw_verdict(manual: bool | None, signals: list[dict[str, Any]]) -> dict[str, Any]:
    """合成的判断:`flagged`(按 NSFW 那组设置处理)、`manual`(手动标的,没标是 None)、`reasons`(每一种自动依据,
    按 NSFW_SOURCES 排)。手动标了就听手动的;没标时任一种自动依据说是就算是。"""
    reasons = sorted(signals, key=lambda one: NSFW_SOURCES.index(one["source"]) if one["source"] in NSFW_SOURCES else 99)
    flagged = manual if manual is not None else any(one["nsfw"] for one in reasons)
    return {"flagged": flagged, "manual": manual, "reasons": reasons}


def _marks(db: Session, instance_id: str) -> dict[tuple[str, str], bool]:
    """这个连接上手动标过的文件:(目录, 名字) → 是不是 NSFW。"""
    rows = db.scalars(select(ModelFileMark).where(ModelFileMark.instance_id == instance_id))
    return {(row.folder, row.name): row.nsfw for row in rows}


def mark_nsfw(db: Session, user: User, instance: PluginInstance, folder: str, name: str,
              nsfw: bool | None) -> dict[str, Any]:
    """手动标一个文件的预览图是不是 NSFW(`None` 是去掉标记,回到自动判断)。回新的判断。

    自动的那几条依据用最近一次列出来时插件交的(在内存里);重启后还没列过时先替它列一遍。"""
    _require(db, instance)
    folder, name = _text(folder, 200), _norm(_text(name, 1000))
    if not folder or not name:
        raise ModelLibraryError("modelLibErr_badFilename", name=name)
    row = db.get(ModelFileMark, (instance.id, folder, name))
    if nsfw is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ModelFileMark(instance_id=instance.id, folder=folder, name=name, nsfw=nsfw, marked_by=user.id))
    else:
        row.nsfw, row.marked_by = nsfw, user.id
    db.flush()
    snapshot = _snapshot_for(db, instance)
    signals = snapshot.signals.get((folder, name), []) if snapshot else []
    return nsfw_verdict(nsfw, signals)


def preview_source(db: Session, instance: PluginInstance, folder: str, name: str,
                   pick: str = "safest") -> model_previews.PreviewSource | None:
    """这个文件的预览图从哪儿取:那台服务器上的(插件给的地址),再是别处的那张示例图(按 `pick` 挑,见
    model_previews.pick);两样都没有就是 None。**读库的只有这一步**:拿到它之后取图、缩图都不碰数据库 —— 调用方(路由)
    接着就把连接交还,再去等(见 PreviewSource)。"""
    _require(db, instance)
    snapshot = _snapshot_for(db, instance)
    if snapshot is None:
        return None
    key = (folder, name)
    candidates: list[model_previews.Media] = []
    if snapshot.previews.get(key):
        candidates.append(model_previews.Media(snapshot.previews[key], dict(snapshot.headers), server=True))
    # 预览接口没有的:模型旁边的预览视频、文件名带 [ ] 的那张图(ComfyUI 按通配符找不到),按名字直接读
    candidates += [model_previews.Media(url, dict(snapshot.headers), server=True) for url in snapshot.sidecars.get(key, [])]
    chosen = model_previews.pick(snapshot.elsewhere.get(key, []), pick)
    if chosen is not None:
        # 别处的不带那台服务器的头(访问凭据只给它自己)
        candidates.append(model_previews.Media(chosen.url, {}, server=False))
    if not candidates:
        return None
    route = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
    original = snapshot.originals.get(key)
    lossless = model_previews.Media(original, dict(snapshot.headers), server=True) if original else None

    def offer(path: Path, kind: str, server: bool) -> None:
        """卡片第一次露面:本机识别排进队(那台服务器上的那张有原文件就看原文件,见 model_nsfw_local)。"""
        model_nsfw_local.offer(model_nsfw_local.Source(path, kind, instance.id, lossless if server else None, route))

    return model_previews.PreviewSource(instance.id, folder, name, tuple(candidates), route, offer)


def _snapshot_for(db: Session, instance: PluginInstance) -> _Snapshot | None:
    """记着的预览图地址;没有(重启了)就先列一遍。一屏的预览请求是同时到的:只有第一个去列,别的等它。"""
    with _lock:
        snapshot = _snapshots.get(instance.id)
        gate = _listing_locks.setdefault(instance.id, threading.Lock())
    if snapshot is not None:
        return snapshot
    with gate:
        with _lock:
            snapshot = _snapshots.get(instance.id)
        if snapshot is None:
            library(db, instance)
            with _lock:
                snapshot = _snapshots.get(instance.id)
    return snapshot


def detail(db: Session, instance: PluginInstance, folder: str, name: str) -> dict[str, Any]:
    """一个文件的完整元数据:文件头里的全部标量(值截断)和训练标签(按出现次数)。"""
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "detail", "folder": folder, "name": name},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    raw = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
    metadata = {
        str(key)[:200]: (value if isinstance(value, str) else str(value))[:_MAX_METADATA_VALUE]
        for key, value in list(raw.items())[:_MAX_METADATA_KEYS]
        if isinstance(value, (str, int, float, bool))
    }
    tags = [
        {"tag": _text(one.get("tag"), 200), "count": int(_number(one.get("count")) or 0)}
        for one in output.get("tags") or [] if isinstance(one, dict) and _text(one.get("tag"), 200)
    ][:_MAX_TAGS]
    return {"folder": folder, "name": name, "metadata": metadata, "tags": tags}


def resolve(db: Session, instance: PluginInstance, url: str) -> dict[str, Any]:
    """一个链接指的是什么:直链、文件名、大小、建议的目录、同名文件在不在。认不出的由插件说原因。"""
    _require(db, instance)
    if not _http(url):
        raise ModelLibraryError("modelLibErr_badUrl")
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "resolve", "url": url.strip()},
                               timeout=QUICK_TIMEOUT_SECONDS)
    size = _number(output.get("size"))
    return {
        "source": _text(output.get("source"), 40),
        "url": _http(output.get("url")) or url.strip(),
        "page": _http(output.get("page")),
        "filename": _text(output.get("filename"), 300),
        "size": int(size) if size is not None else None,
        "folder": _text(output.get("folder"), 200),
        "family": _text(output.get("family"), 80),
        "triggers": [_text(one, 200) for one in output.get("triggers") or [] if _text(one, 200)][:_MAX_TRIGGERS],
        "title": _text(output.get("title"), 300),
        "exists": bool(output.get("exists")),
        "uses_token": bool(output.get("uses_token")),
        "note": _text(output.get("note"), 2000),
    }


#: 「找下载地址」最多交给界面几个候选、几条失败。
_MAX_CANDIDATES = 20
_MAX_FAILED = 10


def search_sources(db: Session, instance: PluginInstance, filename: str, folder: str = "") -> dict[str, Any]:
    """按文件名去模型站上找下载地址(工作台「缺失项」里工作流没写地址的模型):插件去搜,交回候选(同名的在前)和搜不了的
    站。每个候选的 `url` 是插件自己的 `resolve` 认得、正好解析到那个文件的链接 —— 界面点了就拿它去解析、再下载。
    宿主只规整:没有 http(s) 地址或文件名的候选丢掉,长文本截断。"""
    _require(db, instance)
    name = _text(filename, 300)
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY,
                               {"op": "search_sources", "filename": name, "folder": _text(folder, 200)},
                               timeout=QUICK_TIMEOUT_SECONDS)
    candidates = []
    for one in output.get("candidates") or []:
        if not isinstance(one, dict) or not _http(one.get("url")) or not _text(one.get("filename"), 300):
            continue
        size = _number(one.get("size"))
        candidates.append({
            "source": _text(one.get("source"), 40),
            "repo": _text(one.get("repo"), 300),
            "title": _text(one.get("title"), 300),
            "filename": _text(one.get("filename"), 300),
            "url": _http(one.get("url")),
            "page": _http(one.get("page")),
            "size": int(size) if size is not None else None,
            "base_model": _text(one.get("base_model"), 120),
            "exact": bool(one.get("exact")),
        })
    failed = [
        {"source": _text(one.get("source"), 40), "message": _text(one.get("message"), 500)}
        for one in output.get("failed") or [] if isinstance(one, dict) and _text(one.get("message"), 500)
    ]
    return {"filename": _text(output.get("filename"), 300) or name, "candidates": candidates[:_MAX_CANDIDATES],
            "failed": failed[:_MAX_FAILED]}


#: 工作台一次最多问几格(和插件那一侧同一个数)。
MAX_NODE_FOLDERS = 64


def node_folders(db: Session, instance: PluginInstance, nodes: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """工作台的「模型库」面板(ADR 0038 §6):画布上选中的节点那几格(节点类型 + 输入名)各选的是哪个模型目录的文件 ——
    面板据此只列那个目录的模型,点一个填进那一格。不是选模型文件的格子是空串。选文本编码器的那一格另有 `encoders`:
    这种节点每一种 type 配哪几种(面板照节点现在的 type 挑,把合用的排前面、标出不合的);插件不说就是 None。答案只看
    节点类型和输入名。插件只查表,不问 ComfyUI。"""
    _require(db, instance)
    if len(nodes) > MAX_NODE_FOLDERS:
        raise ModelLibraryError("modelLibErr_tooManyNodes", n=str(MAX_NODE_FOLDERS))
    asked = [{"class_type": _text(one.get("class_type"), 200), "input": _text(one.get("input"), 200)} for one in nodes]
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "node_folders", "nodes": asked},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    folders = output.get("folders")
    if not isinstance(folders, list) or len(folders) != len(asked):
        raise ModelLibraryError("modelLibErr_badAnswer", name=instance.name)
    recipes = output.get("encoders")
    recipes = recipes if isinstance(recipes, list) and len(recipes) == len(asked) else [None] * len(asked)
    return {"folders": [one if isinstance(one, str) and _MODEL_FOLDER.fullmatch(one) else "" for one in folders],
            "encoders": [_node_encoders(one) for one in recipes]}


#: 一个模型目录的名字(ComfyUI 的 folder_paths 名:loras、checkpoints、unet_gguf……)。
_MODEL_FOLDER = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _plain_name(value: str, *, key: str) -> str:
    """文件名、目录名只能是一段:不带路径分隔符、不是 `.` / `..`、没有控制字符。"""
    text = (value or "").strip()
    if not text or text in (".", "..") or any(mark in text for mark in ("/", "\\", ":", "\x00")) or \
            any(ord(char) < 32 for char in text):
        raise ModelLibraryError(key, name=text)
    return text


def start_download(
    db: Session, user: User, instance: PluginInstance, *, workspace_id: str, url: str, folder: str, filename: str
) -> Job:
    """把一个模型下到这个连接的那台服务器上:一个后台任务。名字、目录、链接在这里先过一遍,不交给插件猜。"""
    _require(db, instance)
    if not _http(url):
        raise ModelLibraryError("modelLibErr_badUrl")
    folder = _plain_name(folder, key="modelLibErr_badFolder")
    filename = _plain_name(filename, key="modelLibErr_badFilename")
    ensure_workspace_perm(db, user, workspace_id, "edit")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="model_download",  # 和 KIND 同一个;任务目录的测试按字面量扫
        created_by=user.id,
        payload={"instance_id": instance.id, "url": url.strip(), "folder": folder, "filename": filename,
                 "subject": filename},
        message="jobMsg_modelDownloadQueued",
        message_params={"name": filename},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _download(job_id), what="模型下载"))
    return job


def _cancelled(job_id: str) -> bool:
    from app.core.db import SessionLocal
    from app.domain.jobs import was_cancelled

    #: 取消的任务在库里是 failed + jobErr_cancelled(见 jobs.was_cancelled)。
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job is None or was_cancelled(job) or job.status not in ("queued", "running")


def _download(job_id: str) -> None:
    """下载任务的身子。每一步一个短的 unit_of_work(在跑、每次进度、失败、刷新目录、成功):下载要跑几分钟到几小时,
    不攥着一个事务;状态都经 finish_job 写,中途的取消不会被盖掉。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        instance = db.get(PluginInstance, str(payload.get("instance_id") or ""))
        if instance is None:
            if finish_job(db, job, status="failed", error="", error_key="modelLibErr_instanceGone", error_params={}):
                say(job, "jobMsg_modelDownloadFailed", name=payload.get("filename", ""))
            return
        if not finish_job(db, job, status="running", progress=0.01):
            return
        say(job, "jobMsg_modelDownloadRunning", name=payload.get("filename", ""))
        emit_job_event(db, job.id, "job.running", {})
        instance_id = instance.id

    def on_progress(fraction: float, message: str) -> None:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or not finish_job(db, job, status="running"):
                return
            job.progress = min(0.99, max(float(job.progress or 0.0), float(fraction)))
            if message:
                say(job, message[:200])

    hooks = StreamHooks(on_progress=on_progress, on_task=lambda _receipt: None, is_cancelled=lambda: _cancelled(job_id))
    request = {"op": "download", "url": payload["url"], "folder": payload["folder"], "filename": payload["filename"]}
    try:
        with unit_of_work() as db:
            output = tools.invoke_host(db, instance_id, MODEL_LIBRARY, request, hooks=hooks,
                                       timeout=MAX_GENERATION_TIMEOUT_SECONDS)
    except (PluginDomainError, PluginRuntimeError) as exc:
        from app.domain.jobs import blame

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_modelDownloadFailed", name=payload["filename"])
                emit_job_event(db, job.id, "job.failed", {})
        return
    size = _number(output.get("size"))
    result = {
        "folder": _text(output.get("folder"), 200) or payload["folder"],
        "name": _text(output.get("name"), 1000) or payload["filename"],
        "size": int(size) if size is not None else None,
        "route": _text(output.get("route"), 40),
    }
    # 先让这个连接的目录(模型、工具)重新问一遍插件,再说「下完了」:任务说能选的时候,生成表单的下拉里就该有它。
    # 刷新失败只记在目录自己的状态里(插件页看得到),不把一次下成了的下载判失败。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or not finish_job(db, job, status="running"):
            return
        say(job, "jobMsg_modelDownloadRefreshing", name=result["name"])
    with unit_of_work() as db:
        instance = db.get(PluginInstance, instance_id)
        if instance is not None:
            host_capabilities.notify(db, instance, refresh=True)
    # 新下的文件那台服务器上多半没有预览图(只下了模型):先问一次,模型库一打开就知道该显示 Civitai 的示例图、标上「来自」
    try:
        _probe_server(instance_id, result["folder"], result["name"])
    except (ModelLibraryError, PluginDomainError, PluginRuntimeError):
        logger.info("新下的模型的预览图这次没问到(连接 %s)", instance_id)
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_modelDownloadDone", name=result["name"], folder=result["folder"])
            emit_job_event(db, job.id, "job.succeeded", dict(result))


# --- 模型信息:在 Civitai 上找、存回预览图(ADR 0038 §9) ---------------------------
#
# 「在 Civitai 上找」和「为缺预览图的模型补图」是一个后台任务(`model_previews`):按哈希找要那台服务器把整个文件读一遍,
# 一个大模型要几分钟,一批要更久 —— 任务中心里看得到进度、能取消。「存为预览图」一张图一两秒,当场做。
# 写回那台服务器的只有这两处,每次都是用户点的(确认框写明写到哪台服务器、哪个文件旁边)。

#: 找、补预览图任务的种类(见 job_catalog)。
INFO_KIND = "model_previews"
#: 按哈希找一个文件最多等多久:那台机器把整个文件读进来再算,几十 GB 的视频模型在机械盘上要好几分钟。
LOOKUP_TIMEOUT_SECONDS = 1200
#: 写回一张预览图:传一张图、拷一份。
SAVE_TIMEOUT_SECONDS = 120
#: 一次最多找几个文件。
MAX_LOOKUP_FILES = 5000


def _picked(value: str) -> str:
    return value if value in model_previews.PICKS else "safest"


def start_lookup(
    db: Session, user: User, instance: PluginInstance, *, workspace_id: str, files: list[dict[str, str]] | None,
    save: bool, pick: str = "safest", refresh: bool = False,
) -> Job:
    """在 Civitai 上找这几个文件(`files`;给 None 是「这台服务器上没有预览图的全部」),`save` 时找到的顺手存成预览图。
    一个后台任务。"""
    _require(db, instance)
    ensure_workspace_perm(db, user, workspace_id, "edit")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    snapshot = _snapshot_for(db, instance)
    if snapshot is None:
        raise ModelLibraryError("modelLibErr_badAnswer", name=instance.name)
    if save and not snapshot.tools.get("save"):
        raise ModelLibraryError("modelLibErr_cantSavePreview", note=snapshot.tools.get("save_note") or "")
    if files is None:
        # 「缺预览图的」:那台服务器上取过、说没有的,和还没取过的(任务里先问一次)
        wanted = [{"folder": folder, "name": name} for folder, name in snapshot.files()
                  if model_previews.server_status(instance.id, folder, name) != "found"]
    else:
        known = set(snapshot.files())
        wanted = [{"folder": _text(one.get("folder"), 200), "name": _text(one.get("name"), 1000)} for one in files]
        wanted = [one for one in wanted if (one["folder"], one["name"]) in known]
    if not wanted:
        raise ModelLibraryError("modelLibErr_nothingToLookUp")
    wanted = wanted[:MAX_LOOKUP_FILES]
    subject = wanted[0]["name"] if len(wanted) == 1 else str(len(wanted))
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="model_previews",  # 和 INFO_KIND 同一个;任务目录的测试按字面量扫
        created_by=user.id,
        payload={"instance_id": instance.id, "files": wanted, "save": save, "pick": _picked(pick), "refresh": refresh,
                 "subject": subject},
        message="jobMsg_modelPreviewsQueued",
        message_params={"n": str(len(wanted))},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _lookups(job_id), what="模型信息"))
    return job


def lookup_job(db: Session, user: User, instance: PluginInstance, job_id: str) -> dict[str, Any]:
    """一个找、补预览图任务现在怎样(界面轮询它):任务本身,做完了带上它交回的(对上的那几条现在的样子在 `found` 里)。
    不是这个连接的找图任务一律当没有。"""
    _require(db, instance)
    job = db.get(Job, job_id)
    if job is None or job.kind != INFO_KIND or (job.payload or {}).get("instance_id") != instance.id:
        raise ModelLibraryError("modelLibErr_noSuchLookup")
    ensure_workspace_perm(db, user, job.workspace_id, "view")
    return {"job": job, "result": dict(job.result or {}) if job.status == "succeeded" else None}


def _probe_server(instance_id: str, folder: str, name: str) -> str:
    """那台服务器上有没有这个文件的预览图;没取过就取一次(顺手落进缓存)。回 `found` / `absent` / ``(这次没取到)。"""
    status = model_previews.server_status(instance_id, folder, name)
    if status:
        return status
    with unit_of_work() as db:
        instance = db.get(PluginInstance, instance_id)
        snapshot = _snapshot_for(db, instance) if instance is not None else None
        servers = ([snapshot.previews[(folder, name)]] if snapshot and snapshot.previews.get((folder, name)) else []) + \
            (snapshot.sidecars.get((folder, name), []) if snapshot else [])
        if instance is None or snapshot is None or not servers:
            return "absent" if instance is not None else ""
        route = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
        source = model_previews.PreviewSource(
            instance_id, folder, name, tuple(model_previews.Media(url, dict(snapshot.headers), server=True) for url in servers),
            route)
    source.original()
    return model_previews.server_status(instance_id, folder, name)


def _lookups(job_id: str) -> None:
    """找、补预览图任务的身子。一个文件一步:先看那台服务器上有没有预览图(补图时有了就跳过),再让插件在 Civitai 上找,
    补图时按哈希对上的(和经 Mosael 从 Civitai 下的)顺手存回;按文件名对上的不替人存,列在结果里请他一个个确认。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        if db.get(PluginInstance, str(payload.get("instance_id") or "")) is None:
            if finish_job(db, job, status="failed", error="", error_key="modelLibErr_instanceGone", error_params={}):
                say(job, "jobMsg_modelPreviewsFailed")
            return
        if not finish_job(db, job, status="running", progress=0.01):
            return
        emit_job_event(db, job.id, "job.running", {})
    instance_id = str(payload["instance_id"])
    files = [one for one in payload.get("files") or [] if isinstance(one, dict)]
    save, pick, refresh = bool(payload.get("save")), _picked(str(payload.get("pick") or "")), bool(payload.get("refresh"))
    result: dict[str, Any] = {"looked": 0, "matched": 0, "saved": 0, "had_preview": 0, "confirm": [], "failed": [],
                              "found": []}
    for index, one in enumerate(files):
        if _cancelled(job_id):
            return
        folder, name = str(one.get("folder") or ""), str(one.get("name") or "")
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or not finish_job(db, job, status="running"):
                return
            job.progress = max(0.01, min(0.99, index / max(len(files), 1)))
            say(job, "jobMsg_modelPreviewsLooking", name=name.replace("\\", "/").rsplit("/", 1)[-1],
                at=str(index + 1), n=str(len(files)))
        try:
            # 先问一次那台服务器上有没有预览图(顺手落进缓存):补图时有了就跳过;只找不存时,列表据此马上知道该不该显示
            # 找来的那张、标上「来自 Civitai」
            if _probe_server(instance_id, folder, name) == "found" and save:
                result["had_preview"] += 1
                continue
            with unit_of_work() as db:
                output = tools.invoke_host(db, instance_id, MODEL_LIBRARY,
                                           {"op": "lookup", "folder": folder, "name": name, "refresh": refresh},
                                           timeout=LOOKUP_TIMEOUT_SECONDS, record=False)
            result["looked"] += 1
            match = _text(output.get("match"), 20)
            if match not in ("sha256", "filename", "download"):
                continue
            result["matched"] += 1
            # 对上的马上记进宿主记着的那份列表(示例图、怎么对上的),再交给界面这一条现在的样子(原链接、预览图从哪来、
            # NSFW):详情里的「原链接」和 Civitai 那张示例图当场就有,不等整份重列 —— 一台几百个模型的服务器重列要好几秒
            with unit_of_work() as db:
                instance = db.get(PluginInstance, instance_id)
                if instance is None:
                    return
                found = _remember_lookup(db, instance, folder, name, output, pick)
                if found is not None:
                    result["found"].append(found)
                if not save:
                    continue
                if match == "filename":
                    result["confirm"].append({"folder": folder, "name": name})
                    continue
                _save_preview(db, instance, folder, name, pick)
                if found is not None:
                    found.update(has_preview=True, preview_origin="server",
                                 preview_kind=model_previews.server_kind(instance_id, folder, name) or "image")
            result["saved"] += 1
        except (ModelLibraryError, PluginDomainError, PluginRuntimeError) as exc:
            result["failed"].append({"folder": folder, "name": name, "error": str(exc)[:500]})
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_modelPreviewsDone", looked=str(result["looked"]), matched=str(result["matched"]),
                saved=str(result["saved"]))
            emit_job_event(db, job.id, "job.succeeded", {"saved": result["saved"]})


def _remember_lookup(db: Session, instance: PluginInstance, folder: str, name: str, output: dict[str, Any],
                     pick: str) -> dict[str, Any] | None:
    """插件刚在 Civitai 上找到的(示例图、怎么对上的)记进宿主记着的那份列表 —— 取预览图、存回都照它,不必为一个文件让插件
    再列一遍 —— 并回这一条在界面上现在该是什么样(`folder` / `name` / `match` / `source` / 预览图那几格 / `nsfw`):界面拿它
    当场改模型库里那一条。记着的列表里没有这个文件(这期间换了服务器)回 None。"""
    snapshot = _snapshot_for(db, instance)
    key = (folder, name)
    if snapshot is None or key not in snapshot.elsewhere:
        return None
    choices = model_previews.elsewhere(output.get("remote_previews"))
    match = _text(output.get("match"), 20)
    server = snapshot.previews.get(key) or next(iter(snapshot.sidecars.get(key, [])), "")
    fields, shown = _preview_fields(instance.id, {"folder": folder, "name": name}, server, choices, pick)
    signals = with_elsewhere_signal([one for one in snapshot.signals.get((folder, _norm(name)), [])], shown)
    with _lock:
        snapshot.elsewhere[key] = choices
        snapshot.how[key] = match
        snapshot.signals[(folder, _norm(name))] = signals
    return {"folder": folder, "name": name, "match": match, "source": _source(output.get("source")), **fields,
            "nsfw": nsfw_verdict(_marks(db, instance.id).get((folder, _norm(name))), signals)}


def save_preview(db: Session, instance: PluginInstance, folder: str, name: str, *, pick: str = "safest",
                 confirmed: bool = False) -> dict[str, Any]:
    """把 Mosael 里显示的那张别处的示例图存成这个文件在那台服务器上的预览图(写到模型旁边)。按文件名对上的要用户确认过
    (`confirmed`)。那台服务器上已经有预览图的不写(写回那条路会覆盖同名的)。"""
    _require(db, instance)
    snapshot = _snapshot_for(db, instance)
    key = (folder, name)
    if snapshot is None or key not in snapshot.elsewhere:
        raise ModelLibraryError("modelLibErr_noElsewherePreview")
    if snapshot.how.get(key) == "filename" and not confirmed:
        raise ModelLibraryError("modelLibErr_confirmFilenameMatch")
    return _save_preview(db, instance, folder, name, _picked(pick))


def _save_preview(db: Session, instance: PluginInstance, folder: str, name: str, pick: str) -> dict[str, Any]:
    snapshot = _snapshot_for(db, instance)
    if snapshot is None:
        raise ModelLibraryError("modelLibErr_badAnswer", name=instance.name)
    if not snapshot.tools.get("save"):
        raise ModelLibraryError("modelLibErr_cantSavePreview", note=snapshot.tools.get("save_note") or "")
    chosen = model_previews.pick(snapshot.elsewhere.get((folder, name), []), pick)
    if chosen is None:
        raise ModelLibraryError("modelLibErr_noElsewherePreview")
    if model_previews.server_status(instance.id, folder, name) == "found":
        raise ModelLibraryError("modelLibErr_alreadyHasPreview")
    route = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
    fetched = model_previews.PreviewSource(instance.id, folder, name, (model_previews.Media(chosen.url, {}, server=False),),
                                           route).original()
    if fetched is None:
        raise ModelLibraryError("modelLibErr_elsewhereUnreachable")
    data, suffix = model_previews.save_ready(fetched)

    def prepare(scratch):
        target = scratch / f"preview{suffix}"
        target.write_bytes(data)
        return {"op": "save_preview", "folder": folder, "name": name, "path": str(target)}

    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "save_preview", "folder": folder, "name": name},
                               prepare=prepare, timeout=SAVE_TIMEOUT_SECONDS)
    # 那台服务器上现在有了:它自己的那张取代别处的这张(列表马上标成「那台服务器上的」,取图时去问它)
    model_previews.note_server(instance.id, folder, name, "found", "video" if suffix == ".mp4" else "image")
    return {"folder": folder, "name": name, "saved": _text(output.get("saved"), 1000)}


def downloads(db: Session, instance: PluginInstance) -> list[Job]:
    """这个连接最近的下载任务(在跑的总在里面),新的在前。"""
    rows = db.scalars(select(Job).where(Job.kind == KIND).order_by(Job.created_at.desc()).limit(200))
    mine = [job for job in rows if (job.payload or {}).get("instance_id") == instance.id]
    active = [job for job in mine if job.status in ("queued", "running")]
    finished = [job for job in mine if job.status not in ("queued", "running")]
    return active + finished[: max(0, RECENT_DOWNLOADS - len(active))]


def _on_instance_change(_db: Session, instance: PluginInstance, refresh: bool) -> None:
    """连接变了(换了服务器、刷新):记着的预览图地址作废,下一次列的时候重记。磁盘缓存按地址记,不用清。"""
    if refresh:
        forget(instance.id)


#: 能力表里的 `model_library`(ADR 0034):不走能力表的挑法(每个连接各有各的模型文件),登记它是为了叫得出名字、
#: 说得出用在哪,连接变了时作废记着的预览图地址。
CAPABILITY = capabilities.Capability(
    name=MODEL_LIBRARY,
    label_key="capability_model_library",
    description_key="capability_model_library",
    pickable=False,
    on_instance_change=_on_instance_change,
)


def register_uses() -> None:
    capabilities.register_use(capabilities.Use(MODEL_LIBRARY, "app", fragment("capUse_modelLibrary")))


__all__ = [
    "CAPABILITY",
    "KIND",
    "ModelLibraryError",
    "detail",
    "downloads",
    "drop_cache",
    "forget",
    "library",
    "mark_nsfw",
    "nsfw_verdict",
    "preview_source",
    "register_uses",
    "resolve",
    "save_preview",
    "search_sources",
    "start_download",
    "start_lookup",
]

"""工作流库的导入与补齐(ADR 0035 §5):认出要导入的那份东西、换成界面格式、预览;存进 workflows/;经 ComfyUI-Manager
装缺的节点包、重启 ComfyUI。

宿主按 `op` 问(见 main._generation):

    {"op": "inspect_import", "text" | "data"+"filename" | "url"}  → 认出来的工作流(界面格式)+ 预览(图摘要、识别出的参数、
                                                                   缺的节点和节点包、缺的模型)+ 建议的路径 + 说明
    {"op": "save_workflow", "path", "content"(JSON 原文)}          → 存进 workflows/(不覆盖,撞名回建议名)
    {"op": "install_nodes", "packs"}                               → 流式:经 Manager 装节点包,装完说要重启
    {"op": "reboot"}                                               → 经 Manager 重启 ComfyUI,等它停下再起来

**认得什么**:界面里「保存 / 导出」的 JSON(`nodes` / `links`)、「导出 (API)」的 JSON(节点 id → `class_type` /
`inputs`);ComfyUI 存出来的 PNG(tEXt / iTXt 的 `workflow`、`prompt`)和 WebP(EXIF 里 Make = `workflow:…`、
Model = `prompt:…`),界面格式优先;压缩包里的第一张;链接只取 HuggingFace、Civitai、ModelScope 和这台 ComfyUI 自己的地址
—— 插件声明过的网络权限就这几处,别的站说清楚、让人下载下来拖进来。

**API 格式没有布局**:按 object_info 把值排回 `widgets_values`(顺序和 convert 读它时同一套,含 seed 后面「生成后怎样」那一格、
读素材节点的上传按钮)、按连线重建 `links` 和每个节点的输入 / 输出口、按依赖分层从左往右排位置 —— ComfyUI 的侧栏才打得开、
插件才认得。转回 API(convert.to_api)和原来一样。

**装节点包从不在测试里碰真机器**(见测试的假 Manager)。Manager 的安全等级:装节点包要 `middle+`(ComfyUI 只监听本机、或
`network_mode = personal_cloud` 才放行),重启要 `middle`;被拒时说人话和下一步。
"""

from __future__ import annotations

import base64
import binascii
import copy
import io
import json
import re
import struct
import time
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib import error, parse

import convert
import sources
from comfy_http import Comfy
from install import MANAGER_CLIENT, MANAGER_LOST_SECONDS, MANAGER_POLL_SECONDS, _cancelled, _log_cursor, _log_reason, \
    manager_version
from lines import ComfyError, say
from run import Emit
from workflow_library import _BAD_SEGMENT, _free_name, _layout, _taken, check_path, describe, model_options

#: 要导入的东西最大多大(图片里嵌着工作流的 PNG 也就几 MB;压缩包放宽一点)。
MAX_BYTES = 30 * 1024 * 1024
#: 压缩包里最多看几项。
MAX_ZIP_ENTRIES = 200
#: 跟跳转最多几跳(HuggingFace / Civitai 都会跳到自己的 CDN)。
MAX_HOPS = 6
#: 重启:多久问一次、最多等多久;这么久都没见它停下,就当它已经起来了(Manager 回了 200)。
REBOOT_POLL_SECONDS = 1.0
REBOOT_WAIT_SECONDS = 240.0
REBOOT_DOWN_GRACE_SECONDS = 30.0
#: 自动排位置:一列多宽、节点多宽、上下隔多少。
_COLUMN = 440.0
_NODE_WIDTH = 320.0
_GAP = 40.0
_PNG = b"\x89PNG\r\n\x1a\n"
#: EXIF 里 ASCII 类型的项。
_ASCII = 2


@dataclass
class _Found:
    """认出来的一份:图本身、哪种格式、从哪儿来的、建议的名字、要告诉人的话。"""

    graph: dict[str, Any]
    format: str
    source: str
    name: str
    notes: list[str] = field(default_factory=list)


# --- 认格式 -------------------------------------------------------------------------

def _graph_of(text: str | bytes) -> tuple[dict[str, Any], str] | None:
    """一段 JSON → (图, "ui" / "api");不是工作流 → None。外面包了一层 `{"workflow": …}` 的也认。"""
    try:
        value = json.loads(text.decode("utf-8-sig") if isinstance(text, bytes) else text)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(value, dict) and isinstance(value.get("nodes"), list):
        return value, "ui"
    if convert.is_api_graph(value):
        return value, "api"
    if isinstance(value, dict) and isinstance(value.get("workflow"), (dict, str)):
        inner = value["workflow"]
        return _graph_of(inner if isinstance(inner, str) else json.dumps(inner))
    return None


def png_texts(data: bytes) -> dict[str, str]:
    """PNG 里的文字段(tEXt、zTXt、iTXt):关键字 → 文字。ComfyUI 存图时把 `workflow`、`prompt` 写在这里。"""
    out: dict[str, str] = {}
    offset = len(_PNG)
    while offset + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        try:
            if kind == b"tEXt":
                key, _, value = body.partition(b"\x00")
                out[key.decode("latin-1")] = value.decode("latin-1")
            elif kind == b"zTXt":
                key, _, rest = body.partition(b"\x00")
                out[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
            elif kind == b"iTXt":
                key, _, rest = body.partition(b"\x00")
                compressed, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _translated, _, text = rest.partition(b"\x00")
                out[key.decode("latin-1")] = (zlib.decompress(text) if compressed else text).decode("utf-8")
            elif kind == b"IEND":
                break
        except (zlib.error, UnicodeDecodeError, IndexError):
            continue
    return out


def _tiff_strings(tiff: bytes) -> list[str]:
    """TIFF(EXIF 的身子)第一个目录里 ASCII 类型的项。"""
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return []
    order = "<" if tiff[:2] == b"II" else ">"
    (start,) = struct.unpack(order + "I", tiff[4:8])
    if start + 2 > len(tiff):
        return []
    (count,) = struct.unpack(order + "H", tiff[start:start + 2])
    found: list[str] = []
    for index in range(min(count, 64)):
        entry = tiff[start + 2 + index * 12:start + 14 + index * 12]
        if len(entry) < 12:
            break
        _tag, kind, length = struct.unpack(order + "HHI", entry[:8])
        if kind != _ASCII:
            continue
        raw = entry[8:8 + length] if length <= 4 else tiff[struct.unpack(order + "I", entry[8:12])[0]:][:length]
        found.append(raw.rstrip(b"\x00").decode("utf-8", "replace"))
    return found


def webp_texts(data: bytes) -> dict[str, str]:
    """WebP 的 EXIF 里 `键:值` 写法的那几项。ComfyUI 存 WebP 时 Make = `workflow:<JSON>`、Model = `prompt:<JSON>`。"""
    out: dict[str, str] = {}
    offset = 12
    while offset + 8 <= len(data):
        kind, length = data[offset:offset + 4], struct.unpack("<I", data[offset + 4:offset + 8])[0]
        body = data[offset + 8:offset + 8 + length]
        offset += 8 + length + (length % 2)
        if kind != b"EXIF":
            continue
        tiff = body[6:] if body.startswith(b"Exif\x00\x00") else body
        for text in _tiff_strings(tiff):
            key, sep, value = text.partition(":")
            if sep and key in ("workflow", "prompt"):
                out[key] = value
    return out


def _from_texts(texts: dict[str, str]) -> tuple[dict[str, Any], str] | None:
    """图片里的那几段:界面格式的 `workflow` 优先(带布局),只有 `prompt` 时按 API 格式。"""
    for key in ("workflow", "prompt"):
        if texts.get(key):
            found = _graph_of(texts[key])
            if found:
                return found
    return None


def _stem(name: str) -> str:
    last = re.split(r"[\\/]", name.strip())[-1]
    return last.rsplit(".", 1)[0] if "." in last else last


def _from_bytes(data: bytes, filename: str, source: str, locale: str) -> _Found | None:
    if data.startswith(_PNG):
        found = _from_texts(png_texts(data))
        return _Found(found[0], found[1], "png" if source == "file" else source, _stem(filename)) if found else None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        found = _from_texts(webp_texts(data))
        return _Found(found[0], found[1], "webp" if source == "file" else source, _stem(filename)) if found else None
    if data[:4] == b"PK\x03\x04":
        return _from_zip(data, source, locale)
    found = _graph_of(data)
    return _Found(found[0], found[1], "json" if source == "file" else source, _stem(filename)) if found else None


def _from_zip(data: bytes, source: str, locale: str) -> _Found | None:
    """压缩包:按包里的顺序找第一张工作流(JSON 或带工作流的图),另外几张写进说明。"""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    hits: list[_Found] = []
    for info in archive.infolist()[:MAX_ZIP_ENTRIES]:
        name = info.filename
        if info.is_dir() or name.startswith("__MACOSX/") or _stem(name).startswith("."):
            continue
        if not name.lower().endswith((".json", ".png", ".webp")) or info.file_size > MAX_BYTES:
            continue
        found = _from_bytes(archive.read(info), name, "file", locale)
        if found:
            hits.append(_Found(found.graph, found.format, "zip" if source == "file" else source, found.name,
                               [re.split(r"[\\/]", name)[-1]]))
    if not hits:
        return None
    first = hits[0]
    others = [hit.notes[0] for hit in hits[1:]]
    notes = [say(locale, f"压缩包里还有 {'、'.join(others)},这次只导入了 {first.notes[0]}(要别的那几张,解压后一张张拖进来)",
                 f"The archive also has {', '.join(others)}; only {first.notes[0]} is imported this time (unzip it and "
                 "drop the others in one by one)")] if others else []
    return _Found(first.graph, first.format, first.source, first.name, notes)


# --- 链接 ---------------------------------------------------------------------------

def _allowed_site(url: str, comfy: Comfy) -> str:
    """这个地址插件去不去取:HuggingFace / Civitai / ModelScope(插件本来就声明了这几处网络权限)→ "site";
    这台 ComfyUI 自己的地址 → "comfy";别的 → ""。"""
    if url.startswith(comfy.base + "/"):
        return "comfy"
    host = sources._host(url)  # noqa: SLF001
    if host in sources.HF_HOSTS | sources.CIVITAI_HOSTS | sources.MODELSCOPE_HOSTS:
        return "site"
    return ""


def _direct(url: str) -> str:
    """HuggingFace 的 `blob`(网页)换成 `resolve`(文件本身);别名域名换成规范的。"""
    url = sources.canonical_url(url)
    parts = parse.urlsplit(url)
    if (parts.hostname or "").lower() in sources.HF_HOSTS and "/blob/" in parts.path:
        return parse.urlunsplit(parts._replace(path=parts.path.replace("/blob/", "/resolve/", 1)))
    return url


def _read(response: Any, locale: str) -> bytes:
    data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ComfyError(say(locale, f"这个文件超过 {MAX_BYTES // (1024 * 1024)} MB,不像一张工作流",
                             f"This file is over {MAX_BYTES // (1024 * 1024)} MB, too big to be a workflow"))
    return data


def _page(content_type: str, locale: str) -> None:
    if "text/html" in content_type.lower():
        raise ComfyError(say(locale, "这个地址是一个网页,不是文件:在网页上点下载,把下好的文件拖进来;或者贴文件本身的链接",
                             "This link is a web page, not a file. Download it from the page and drop the file in, "
                             "or paste a direct link to the file"))


def _fetch(url: str, comfy: Comfy, locale: str) -> tuple[bytes, str]:
    """取回链接指着的文件(内容、文件名)。只去认得的站;跳转跟到底,每一跳只带那一跳的站自己的令牌。"""
    url = _direct(url.strip())
    site = _allowed_site(url, comfy)
    if not site:
        host = sources._host(url) or url  # noqa: SLF001
        raise ComfyError(say(
            locale,
            f"{host} 上的东西 Mosael 不替你去取(只取 HuggingFace、Civitai、ModelScope 和这台 ComfyUI 自己的地址):"
            "在浏览器里下载下来拖进来",
            f"Mosael doesn't fetch from {host} (only HuggingFace, Civitai, ModelScope and this ComfyUI itself). "
            "Download the file in your browser and drop it in",
        ))
    name = parse.unquote(parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    if site == "comfy":
        path = url[len(comfy.base):]
        try:
            with comfy._open("GET", path) as response:  # noqa: SLF001 — 带着这个连接的访问凭据
                _page(response.headers.get("Content-Type") or "", locale)
                return _read(response, locale), name
        except error.HTTPError as exc:
            raise ComfyError(say(locale, f"这台 ComfyUI 回了 HTTP {exc.code}:这个地址取不到东西",
                                 f"This ComfyUI answered HTTP {exc.code}: nothing to fetch there")) from exc
    current = url
    for _ in range(MAX_HOPS):
        response = sources.open_url(current, headers=sources.auth_for(current), timeout=60)
        try:
            status = int(getattr(response, "status", None) or getattr(response, "code", 0))
            location = response.headers.get("Location")
            if status in (301, 302, 303, 307, 308) and location:
                current = parse.urljoin(current, location)
                continue
            if status >= 400:
                raise ComfyError(say(locale, f"{sources._host(current)} 回了 HTTP {status}:这个链接取不到文件",  # noqa: SLF001
                                     f"{sources._host(current)} answered HTTP {status}: the link gave no file"))  # noqa: SLF001
            _page(response.headers.get("Content-Type") or "", locale)
            disposition = sources._disposition_name({k.lower(): v for k, v in response.headers.items()})  # noqa: SLF001
            return _read(response, locale), disposition or name
        finally:
            response.close()
    raise ComfyError(say(locale, "跳转太多次,没取到文件", "Too many redirects; no file came back"))


def _found(payload: dict[str, Any], comfy: Comfy, locale: str) -> _Found:
    text = str(payload.get("text") or "").strip()
    url = str(payload.get("url") or "").strip() or (text if re.match(r"^https?://\S+$", text) else "")
    if url:
        data, name = _fetch(url, comfy, locale)
        found = _from_bytes(data, name, "url", locale)
    elif payload.get("data"):
        try:
            data = base64.b64decode(str(payload["data"]), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ComfyError(say(locale, "文件没传过来(内容坏了)", "The file didn't come through intact")) from exc
        if len(data) > MAX_BYTES:
            raise ComfyError(say(locale, f"这个文件超过 {MAX_BYTES // (1024 * 1024)} MB,不像一张工作流",
                                 f"This file is over {MAX_BYTES // (1024 * 1024)} MB, too big to be a workflow"))
        found = _from_bytes(data, str(payload.get("filename") or ""), "file", locale)
    elif text:
        graph_found = _graph_of(text)
        found = _Found(graph_found[0], graph_found[1], "json", _stem(str(payload.get("filename") or ""))) \
            if graph_found else None
    else:
        raise ComfyError(say(locale, "没给要导入的东西", "Nothing to import"))
    if found is None:
        raise ComfyError(say(
            locale,
            "认不出这是一张 ComfyUI 工作流:要导入的是 ComfyUI 界面里「保存 / 导出」的 JSON、「导出 (API)」的 JSON,"
            "或者 ComfyUI 存出来的、带着工作流的 PNG / WebP(别的软件出的图里没有工作流)",
            "This doesn't look like a ComfyUI workflow. Import the JSON from ComfyUI's Save / Export or Export (API), "
            "or a PNG / WebP saved by ComfyUI with the workflow inside (images from other tools don't carry one)",
        ))
    return found


# --- API 格式 → 界面格式 --------------------------------------------------------------

def _is_link(value: Any, api: dict[str, Any]) -> bool:
    return isinstance(value, list) and len(value) == 2 and str(value[0]) in api and isinstance(value[1], int)


def _literal(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or (isinstance(value, dict) and set(value) == {"__value__"})


def _type_of(definition: Any) -> str:
    if isinstance(definition, list) and definition:
        kind = definition[0]
        return "COMBO" if isinstance(kind, list) else str(kind)
    return "*"


def _unwrap(value: Any) -> Any:
    return value["__value__"] if isinstance(value, dict) and set(value) == {"__value__"} else value


def _declared(spec: dict[str, Any]) -> list[tuple[str, Any]]:
    """节点定义里的输入,按前端建它们的顺序(有 `input_order` 就按它;和 convert._widget_specs 同一套)。"""
    declared = spec.get("input") if isinstance(spec.get("input"), dict) else {}
    order = spec.get("input_order") if isinstance(spec.get("input_order"), dict) else {}
    out: list[tuple[str, Any]] = []
    for section in ("required", "optional"):
        defs = declared.get(section) or {}
        if not isinstance(defs, dict):
            continue
        names = [one for one in (order.get(section) or []) if one in defs] or list(defs)
        names += [one for one in defs if one not in names]
        out += [(name, defs[name]) for name in names]
    return out


def _numbered(keys: list[str]) -> dict[str, int]:
    """API 图的节点 id → 界面图的节点 id(数字)。本来就是数字的照旧,别的(子图展开的 `5:3` 这类)往后编。"""
    out: dict[str, int] = {}
    used: set[int] = set()
    for key in keys:
        if key.isdigit() and int(key) not in used:
            out[key] = int(key)
            used.add(int(key))
    number = 1
    for key in keys:
        if key not in out:
            while number in used:
                number += 1
            out[key] = number
            used.add(number)
    return out


def _height(entries: list[dict[str, Any]], outputs: list[dict[str, Any]], widgets: list[tuple[str, Any, int]]) -> float:
    rows = max(len(entries), len(outputs))
    tall = 0.0
    for name, definition, _extra in widgets:
        options = definition[1] if isinstance(definition, list) and len(definition) > 1 and isinstance(definition[1], dict) else {}
        tall += 110.0 if options.get("multiline") else 60.0 if name == "audioUI" else 26.0
    return 36.0 + 22.0 * rows + tall


def api_to_ui(api: dict[str, Any], object_info: dict[str, Any], locale: str) -> dict[str, Any]:
    """API 格式 → 界面格式(见模块说明)。"""
    api = {str(key): value for key, value in api.items() if isinstance(value, dict)}
    keys = list(api)
    ids = _numbered(keys)
    converter = convert._Converter({}, object_info, locale)  # noqa: SLF001 — widget 的排法只在那里写一份
    scope = convert._Scope({}, (), None)  # noqa: SLF001
    built: dict[str, dict[str, Any]] = {}
    consumers: dict[str, int] = {}
    for key in keys:
        for value in (api[key].get("inputs") or {}).values():
            if _is_link(value, api):
                consumers[str(value[0])] = max(consumers.get(str(value[0]), 0), int(value[1]) + 1)
    for key in keys:
        node = api[key]
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        spec = object_info.get(class_type) if isinstance(object_info.get(class_type), dict) else None
        entries: list[dict[str, Any]] = []
        known: set[str] = set()
        for name, definition in _declared(spec) if spec else []:
            known.add(name)
            value = inputs.get(name)
            if converter._is_widget(definition):  # noqa: SLF001
                if _is_link(value, api):
                    entries.append({"name": name, "type": _type_of(definition), "widget": {"name": name}, "link": None,
                                    "_from": value})
            elif _literal(value):
                # 定义里不是常见 widget 类型、API 里却是一个值(新版的 COMFY_DYNAMICCOMBO_V3、自定义 widget):前端给它建的是
                # widget —— 标成 widget,值才排得进 widgets_values
                entries.append({"name": name, "type": _type_of(definition), "widget": {"name": name}, "link": None})
            else:
                entries.append({"name": name, "type": _type_of(definition), "link": None,
                                "_from": value if _is_link(value, api) else None})
        for name, value in inputs.items():
            if name in known:
                continue
            # 定义里没有的(节点没装、或动态加出来的输入):接了线的是输入口,别的当 widget(值按出现的顺序存)
            if _is_link(value, api):
                entries.append({"name": name, "type": "*", "link": None, "_from": value})
            else:
                entries.append({"name": name, "type": "*", "widget": {"name": name}, "link": None})
        widgets = converter._widget_specs(convert._Node(scope, {"type": class_type, "inputs": entries}))  # noqa: SLF001
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        controls = meta.get(convert.CONTROLS) if isinstance(meta.get(convert.CONTROLS), dict) else {}
        values: list[Any] = []
        for name, definition, extra in widgets:
            if name == "upload":
                values.append("image")
                continue
            if name == "audioUI":
                values.append("")
                continue
            raw = inputs.get(name)
            if raw is None or _is_link(raw, api):
                present, raw = converter._default(definition)  # noqa: SLF001
                raw = raw if present else None
            values.append(_unwrap(raw))
            if extra:
                values.append(str(controls.get(name) or "fixed"))
        types = spec.get("output") if spec and isinstance(spec.get("output"), list) else []
        names = spec.get("output_name") if spec and isinstance(spec.get("output_name"), list) else []
        outputs = [{"name": str(names[index]) if index < len(names) else _type_of([kind]), "type": _type_of([kind]),
                    "links": []} for index, kind in enumerate(types)]
        while len(outputs) < consumers.get(key, 0):
            outputs.append({"name": f"output {len(outputs)}", "type": "*", "links": []})
        title = str(meta.get("title") or "")
        display = str(spec.get("display_name") or class_type) if spec else class_type
        built[key] = {"id": ids[key], "type": class_type, "inputs": entries, "outputs": outputs,
                      "widgets_values": values, "_widgets": widgets,
                      **({"title": title} if title and title not in (class_type, display) else {})}
    links: list[list[Any]] = []
    for key in keys:
        for slot, entry in enumerate(built[key]["inputs"]):
            source = entry.pop("_from", None)
            if not source:
                continue
            origin = built[str(source[0])]
            index = int(source[1])
            output = origin["outputs"][index]
            kind = output["type"] if output["type"] != "*" else entry["type"]
            links.append([len(links) + 1, origin["id"], index, built[key]["id"], slot, kind])
            entry["link"] = len(links)
            output["links"].append(len(links))
    edges = [(str(value[0]), key) for key in keys for value in (api[key].get("inputs") or {}).values()
             if _is_link(value, api)]
    rough = _layout(keys, edges)
    columns: dict[int, list[str]] = {}
    for key in sorted(keys, key=lambda one: (rough[one][0], rough[one][1])):
        columns.setdefault(int(rough[key][0] // 380.0), []).append(key)
    nodes: list[dict[str, Any]] = []
    for column in sorted(columns):
        top = 0.0
        for key in columns[column]:
            node = built[key]
            widgets = node.pop("_widgets")
            height = _height(node["inputs"], node["outputs"], widgets)
            nodes.append({**node, "pos": [column * _COLUMN, top], "size": [_NODE_WIDTH, height], "flags": {},
                          "order": len(nodes), "mode": 0, "properties": {"Node name for S&R": node["type"]}})
            top += height + _GAP
    return {"id": str(uuid.uuid4()), "revision": 0, "last_node_id": max(ids.values(), default=0),
            "last_link_id": len(links), "nodes": nodes, "links": links, "groups": [], "config": {},
            "extra": {"ds": {"scale": 0.8, "offset": [40, 40]}}, "version": 0.4}


# --- op -------------------------------------------------------------------------------

def _suggested(name: str, comfy: Comfy, locale: str) -> str:
    """一个能用、不撞名的路径:名字里 Windows 不收的字符换成空格,去掉开头的点;空了就用「导入的工作流」。"""
    cleaned = re.sub(r"\s+", " ", _BAD_SEGMENT.sub(" ", name.replace("/", " "))).strip().lstrip(".").strip()[:100]
    wanted = f"{cleaned or say(locale, '导入的工作流', 'Imported workflow')}.json"
    taken = _taken(comfy)
    return wanted if wanted not in taken else _free_name(wanted, taken)


def inspect_import(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    found = _found(payload, comfy, locale)
    object_info = comfy.object_info()
    notes = list(found.notes)
    if found.format == "api":
        workflow = api_to_ui(found.graph, object_info, locale)
        notes.insert(0, say(locale, "这份是 API 格式,没有布局:节点的位置是按依赖自动排的,存进去以后可以在 ComfyUI 里挪",
                            "This is the API format, which has no layout: nodes are placed automatically by dependency; "
                            "you can rearrange them in ComfyUI after saving"))
    else:
        workflow = copy.deepcopy(found.graph)
        # 存进去是一张新的图:换一个图 id(两张同 id 的图,插件给它们起的工具名会撞)
        workflow["id"] = str(uuid.uuid4())
    path = _suggested(found.name, comfy, locale)
    row: dict[str, Any] = {"path": path, "problem": ""}
    described = describe(row, workflow, object_info, model_options(object_info), comfy, locale)
    return {"format": found.format, "source": found.source, "workflow": workflow, "suggested_path": path,
            "notes": notes, **{key: value for key, value in described.items() if key != "path"}}


def save_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """存进 workflows/:只新建、不覆盖;撞名回建议名。`content` 是工作流的 JSON 原文(宿主以字符串交来:调用记录里只留
    截断的一段,不把整张图存进记录)。"""
    path = check_path(payload.get("path"), locale)
    graph_found = _graph_of(str(payload.get("content") or ""))
    content = graph_found[0] if graph_found and graph_found[1] == "ui" else None
    if content is None:
        raise ComfyError(say(locale, "要存的不是一张界面格式的工作流", "What's being saved is not a UI-format workflow"))
    if not comfy.write_userdata(f"workflows/{path}", content):
        taken = _taken(comfy)
        return {"conflict": True, "suggestion": _free_name(path, taken)}
    return {"path": path}


def _install_params(pack: str) -> dict[str, Any]:
    """一个节点包交给 Manager 的安装参数。Manager 的映射里,registry 上有的是包名(按 `latest` 装),只在 git 上的是仓库
    地址(Manager 按仓库名认它、版本 `unknown` = 按 git 装)。"""
    if pack.startswith(("http://", "https://")):
        name = pack.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        return {"id": name, "version": "unknown", "selected_version": "unknown", "mode": "cache", "channel": "default"}
    return {"id": pack, "version": "latest", "selected_version": "latest", "mode": "cache", "channel": "default"}


def _node_policy_steps(locale: str) -> str:
    return say(
        locale,
        "这台 ComfyUI 的 ComfyUI-Manager 不让经网络装节点包(它的安全策略:ComfyUI 监听的不是本机地址时,要 network_mode 是 "
        "personal_cloud 才放行)。要用这条路:在那台机器上打开 ComfyUI/user/__manager/config.ini(旧版在 "
        "ComfyUI/user/default/ComfyUI-Manager/config.ini),把 network_mode 改成 personal_cloud、security_level 保持 normal,"
        "然后重启 ComfyUI。也可以在那台机器上自己装:在它的 Manager 界面里装,或者把节点包放进 ComfyUI/custom_nodes 再重启。",
        "This ComfyUI's ComfyUI-Manager won't install node packs over the network (its security policy: when ComfyUI listens "
        "on a non-local address, network_mode must be personal_cloud). To use it: on that machine open "
        "ComfyUI/user/__manager/config.ini (older versions: ComfyUI/user/default/ComfyUI-Manager/config.ini), set "
        "network_mode to personal_cloud, keep security_level at normal, and restart ComfyUI. Or install them on that "
        "machine yourself: from its Manager, or by putting the pack into ComfyUI/custom_nodes and restarting.",
    )


def install_nodes(payload: dict[str, Any], comfy: Comfy, locale: str, emit: Emit) -> dict[str, Any]:
    """经 ComfyUI-Manager 一个个装节点包(排队 → 开始 → 等它的历史出结果)。装好的要重启 ComfyUI 才加载。"""
    packs = [str(one).strip() for one in payload.get("packs") or [] if str(one).strip()][:10]
    if not packs:
        raise ComfyError(say(locale, "没说装哪个节点包", "No node pack was named"))
    if not manager_version(comfy):
        raise ComfyError(say(
            locale,
            f"这台 ComfyUI 没装 ComfyUI-Manager(V4),Mosael 没法替它装节点包:在那台机器上装好 Manager 再来,或者自己把 "
            f"{'、'.join(packs)} 放进 ComfyUI/custom_nodes 再重启",
            f"This ComfyUI has no ComfyUI-Manager (V4), so Mosael can't install node packs on it. Install the Manager there "
            f"first, or put {', '.join(packs)} into ComfyUI/custom_nodes yourself and restart",
        ))
    installed: list[str] = []
    for number, pack in enumerate(packs, start=1):
        ui_id = f"mosael-{uuid.uuid4().hex[:8]}"
        cursor = _log_cursor(comfy)
        comfy.post("/v2/manager/queue/task", {"ui_id": ui_id, "client_id": MANAGER_CLIENT, "kind": "install",
                                              "params": _install_params(pack)})
        comfy.post("/v2/manager/queue/start", {})
        emit({"event": "progress", "progress": round(0.05 + 0.85 * (number - 1) / len(packs), 4),
              "message": say(locale, f"ComfyUI-Manager 正在装 {pack}({number}/{len(packs)})",
                             f"ComfyUI-Manager is installing {pack} ({number}/{len(packs)})")})
        entry = _wait_for(comfy, ui_id, locale)
        ok = entry.get("result") == "success" or (entry.get("status") or {}).get("status_str") == "success"
        if not ok:
            reason = _log_reason(comfy, cursor)
            done = say(locale, f"(前面的 {'、'.join(installed)} 已经装好,重启后生效)",
                       f" ({', '.join(installed)} installed already; restart to load them)") if installed else ""
            if "security_level" in reason or "network_mode" in reason:
                raise ComfyError(_node_policy_steps(locale) + done)
            detail = reason or str(entry.get("result") or "") or "failed"
            raise ComfyError(say(locale, f"ComfyUI-Manager 没装成 {pack}:{detail}{done}",
                                 f"ComfyUI-Manager didn't install {pack}: {detail}{done}"))
        installed.append(pack)
    emit({"event": "progress", "progress": 1.0,
          "message": say(locale, "装好了:重启 ComfyUI 之后才加载", "Installed. Restart ComfyUI to load them")})
    return {"installed": installed, "restart": True}


def _wait_for(comfy: Comfy, ui_id: str, locale: str) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        found = comfy.get("/v2/manager/queue/history", {"ui_id": ui_id})
        entry = found.get("history") if isinstance(found, dict) else None
        if isinstance(entry, dict) and entry.get("result"):
            return entry
        if _cancelled():
            raise ComfyError(say(locale, "已停止等待。ComfyUI-Manager 没有停下单个安装的接口,那台机器上会继续装完",
                                 "Stopped waiting. ComfyUI-Manager can't stop a single install, so it finishes on that machine"))
        if time.monotonic() - started > MANAGER_LOST_SECONDS:
            status = comfy.get("/v2/manager/queue/status") or {}
            if not status.get("is_processing") and not status.get("pending_count"):
                raise ComfyError(say(locale, "ComfyUI-Manager 的队列里找不到这次安装了(它可能重启过):刷新工作流库看看节点到了没有",
                                     "ComfyUI-Manager no longer has this install (it may have restarted). Refresh the "
                                     "workflow library to see whether the nodes arrived"))
        time.sleep(MANAGER_POLL_SECONDS)


def _up(comfy: Comfy) -> bool:
    try:
        comfy.system_stats()
    except ComfyError:
        return False
    return True


def reboot(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """经 ComfyUI-Manager 重启 ComfyUI,等它停下再起来(最多几分钟)。正在跑的任务会中断 —— 界面上确认过。"""
    if not manager_version(comfy):
        raise ComfyError(say(locale, "这台 ComfyUI 没装 ComfyUI-Manager,Mosael 没法替它重启:在那台机器上手动重启",
                             "This ComfyUI has no ComfyUI-Manager, so Mosael can't restart it. Restart it on that machine"))
    try:
        comfy.post("/v2/manager/reboot", {})
    except ComfyError as exc:
        if exc.status == 403:
            raise ComfyError(say(
                locale,
                "ComfyUI-Manager 不让重启(它的 security_level 比 normal 严):在那台机器上手动重启 ComfyUI,或者把 "
                "config.ini 里的 security_level 改成 normal",
                "ComfyUI-Manager won't restart (its security_level is stricter than normal). Restart ComfyUI on that "
                "machine, or set security_level to normal in its config.ini",
            )) from exc
        if exc.status:
            raise
        # 连接在回话之前就断了:它已经在重启
    started = time.monotonic()
    went_down = False
    while time.monotonic() - started < REBOOT_WAIT_SECONDS:
        time.sleep(REBOOT_POLL_SECONDS)
        if not _up(comfy):
            went_down = True
            continue
        if went_down or time.monotonic() - started > REBOOT_DOWN_GRACE_SECONDS:
            return {"back": True}
    raise ComfyError(say(locale, "等了 4 分钟,ComfyUI 还没起来:去那台机器上看看它的控制台",
                         "Waited 4 minutes and ComfyUI isn't back. Check its console on that machine"))


__all__ = ["api_to_ui", "inspect_import", "install_nodes", "png_texts", "reboot", "save_workflow", "webp_texts"]

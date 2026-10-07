"""读这台 ComfyUI 的模型目录(模型库的几处共用):有哪些目录、在磁盘上的哪儿、里面有哪些文件、文件头里的元数据和张量表。

用的是 ComfyUI 0.3x 起的 `/experiment/models*` 与 `/view_metadata/*`(见 ADR 0034 的表),文件头按段读走
ComfyUI-Custom-Scripts 的 `/pysssss/view/*`(见 HeaderRoute)。
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import parse

from comfy_http import Comfy
from lines import ComfyError

#: 不是模型的目录:自定义节点的代码、模型配置文件(yaml)。
SKIPPED_FOLDERS = frozenset({"custom_nodes", "configs"})


def norm(name: str) -> str:
    """ComfyUI 在 Windows 上报的相对路径用反斜杠,工作流里存的有时是正斜杠:比较前统一。"""
    return name.replace("\\", "/").strip()


def folder_info(comfy: Comfy) -> dict[str, list[str]] | None:
    """目录名 → 它在磁盘上的位置(可能几处)。老版本没有这个接口 → None。"""
    try:
        found = comfy.get("/experiment/models")
    except ComfyError as exc:
        if exc.status == 404:
            return None
        raise
    out: dict[str, list[str]] = {}
    for one in found if isinstance(found, list) else []:
        if isinstance(one, dict) and isinstance(one.get("name"), str) and one["name"] not in SKIPPED_FOLDERS:
            out[one["name"]] = [str(path) for path in one.get("folders") or [] if isinstance(path, str)]
    return out


def files_in(comfy: Comfy, folder: str) -> list[dict[str, Any]]:
    """一个目录里的文件:`name`(相对路径)、`pathIndex`、`size`、`modified`。"""
    try:
        found = comfy.get(f"/experiment/models/{parse.quote(folder, safe='')}")
    except ComfyError as exc:
        if exc.status == 404:
            return []
        raise
    return [one for one in found if isinstance(one, dict) and isinstance(one.get("name"), str)] \
        if isinstance(found, list) else []


def names_in(comfy: Comfy, folder: str) -> set[str]:
    """一个目录里的文件名(统一成正斜杠),判「同名文件在不在」用。"""
    return {norm(str(item["name"])) for item in files_in(comfy, folder)}


def metadata_of(comfy: Comfy, folder: str, name: str) -> dict[str, Any] | None:
    """文件头里的 `__metadata__`。不是 safetensors、没有元数据 → None(ComfyUI 回 404)。"""
    if not name.lower().endswith(".safetensors"):
        return None
    try:
        found = comfy.get(f"/view_metadata/{parse.quote(folder, safe='')}", {"filename": name})
    except ComfyError as exc:
        if exc.status in (400, 404):
            return None
        raise
    return found if isinstance(found, dict) else None


# --- 文件头:元数据 + 张量表 -----------------------------------------------------

#: 文件头最多读多少(safetensors 的 JSON、GGUF 的键值和张量表)。实测 safetensors 的头 30–365 KB;再大的多半是元数据里
#: 塞了大图,不读了 —— 元数据退回 /view_metadata 拿,权重结构不认。
HEADER_LIMIT = 8 * 1024 * 1024
#: 第一次读多少:LoRA 的头大多在这里面,一次就够;不够再补读剩下的。
FIRST_READ = 64 * 1024
#: 有文件头可读的格式(.sft 是 safetensors 的另一个扩展名)
HEADER_SUFFIXES = (".safetensors", ".sft", ".gguf")


@dataclass(frozen=True)
class Header:
    """一个文件的头。`meta` 是 safetensors 的 `__metadata__`(GGUF 没有,是空的;头读不了时是 None,元数据得另外问);
    `tensors` 是张量名 → 形状;`architecture` 是 GGUF 的 `general.architecture`;`sizes` 是 GGUF 键值里写的那一架构的尺寸
    (`embedding_length`、`feed_forward_length`、`block_count`)和词表大小(`vocab`,`tokenizer.ggml.tokens` 有几项)。"""

    meta: dict[str, Any] | None
    tensors: dict[str, list[int]]
    architecture: str = ""
    sizes: dict[str, int] = field(default_factory=dict)


#: 地址在、这个文件的头却读不了(太大、太短、不是它说的格式):元数据另外问,权重结构不认
UNREADABLE = Header(None, {})


class HeaderRoute:
    """读文件头走的地址:ComfyUI-Custom-Scripts(pysssss)的 `/pysssss/view/{目录}/{名字}` 把模型文件原样交出、认 Range,
    只取开头几十 KB 到几百 KB,不下整个文件。

    没装它的 ComfyUI 回 404;不认 Range 的(回 200、要把整个文件发过来)也当没有 —— 发现一次就记下(`usable`),这一趟
    剩下的文件不再试,退回 `/view_metadata` 只拿元数据。几个线程一起用。"""

    def __init__(self, comfy: Comfy) -> None:
        self.comfy = comfy
        self.usable = True

    def read(self, folder: str, name: str, *, tensors: bool = True) -> Header | None:
        """None:这台没有能用的读头地址(`usable` 随之变 False);UNREADABLE:地址在、这个文件读不了。`tensors=False`:GGUF 只要
        开头那一段的键值(架构名、尺寸、词表有几项),不往后读张量表 —— 文本编码器的张量表前面是整张词表,几 MB。"""
        if not self.usable:
            return None
        path = "/pysssss/view/" + parse.quote(f"{folder}/{name}", safe="")
        try:
            first = self.comfy.get_range(path, 0, FIRST_READ - 1)
        except ComfyError:
            return UNREADABLE
        if first is None:
            self.usable = False
            return None
        try:
            if name.lower().endswith(".gguf"):
                return _gguf(self.comfy, path, first, tensors=tensors)
            return _safetensors(self.comfy, path, first)
        except (ComfyError, ValueError, UnicodeDecodeError, struct.error):
            return UNREADABLE


def _safetensors(comfy: Comfy, path: str, first: bytes) -> Header:
    """开头 8 个字节是头的长度(小端 u64),后面就是那段 JSON:`__metadata__` 和每个张量的 dtype / shape / 偏移。"""
    if len(first) < 8:
        return UNREADABLE
    size = struct.unpack("<Q", first[:8])[0]
    if size < 2 or size > HEADER_LIMIT:
        return UNREADABLE
    raw = first[8:8 + size]
    if len(raw) < size:
        if len(first) < FIRST_READ:
            return UNREADABLE  # 整个文件都读到了,还没它说的头长:不是 safetensors
        rest = comfy.get_range(path, len(first), 8 + size - 1)
        raw += rest or b""
        if len(raw) < size:
            return UNREADABLE
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        return UNREADABLE
    meta = parsed.pop("__metadata__", None)
    tensors = {str(key): [int(one) for one in value.get("shape") or [] if isinstance(one, int)]
               for key, value in parsed.items() if isinstance(value, dict)}
    return Header(meta if isinstance(meta, dict) else {}, tensors)


class _Short(Exception):
    """读到的还不够,要再往后读。"""


#: GGUF 键值的类型 → 定长标量的格式(8 是字符串、9 是数组,另算)
_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


class _Cursor:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.at + count > len(self.data):
            raise _Short
        out = self.data[self.at:self.at + count]
        self.at += count
        return out

    def number(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self) -> str:
        return self.take(self.number("<Q")).decode("utf-8", "replace")

    def skip(self, kind: int) -> None:
        if kind in _GGUF_SCALARS:
            self.take(struct.calcsize(_GGUF_SCALARS[kind]))
        elif kind == 8:
            self.take(self.number("<Q"))
        elif kind == 9:
            item, count = self.number("<I"), self.number("<Q")
            if item in _GGUF_SCALARS:
                self.take(struct.calcsize(_GGUF_SCALARS[item]) * count)
            else:
                for _ in range(count):
                    self.skip(item)
        else:
            raise ValueError(f"GGUF value type {kind}")


#: GGUF 键值里记下的尺寸(`{架构}.` 后面那一截):文本编码器靠它认是哪一种(encoders.kind_of_gguf)
_GGUF_SIZES = ("embedding_length", "feed_forward_length", "block_count")
#: 整数的键值类型(u8 … i64)
_GGUF_INTEGERS = (0, 1, 2, 3, 4, 5, 10, 11)


def _parse_gguf(data: bytes, found: dict[str, Any]) -> dict[str, list[int]]:
    """GGUF(v2 起):魔数、版本、张量数、键值数,然后是键值(架构名在 `general.architecture`),再是张量表(名字、维数、
    各维长度 —— 最里面的一维在前,和 PyTorch 的形状倒着 —— 类型、偏移)。读到就记进 `found`(读到一半不够了,已经记下的
    还在):架构名、那一架构的尺寸(`sizes`)、词表有几项(`tokenizer.ggml.tokens` 这个数组的长度,跳过它的内容之前就知道)。"""
    cursor = _Cursor(data)
    if cursor.take(4) != b"GGUF" or cursor.number("<I") < 2:
        raise ValueError("not GGUF v2+")
    count, pairs = cursor.number("<Q"), cursor.number("<Q")
    if count > 1_000_000 or pairs > 1_000_000:
        raise ValueError("GGUF counts out of range")
    sizes: dict[str, int] = found.setdefault("sizes", {})
    for _ in range(pairs):
        key, kind = cursor.text(), cursor.number("<I")
        prefix, _dot, tail = key.rpartition(".")
        if key == "general.architecture" and kind == 8:
            found["architecture"] = cursor.text()
        elif kind in _GGUF_INTEGERS and tail in _GGUF_SIZES and prefix == found.get("architecture"):
            sizes[tail] = int(cursor.number(_GGUF_SCALARS[kind]))
        elif key == "tokenizer.ggml.tokens" and kind == 9:
            start = cursor.at
            cursor.number("<I")
            sizes["vocab"] = int(cursor.number("<Q"))
            cursor.at = start
            cursor.skip(kind)
        else:
            cursor.skip(kind)
    tensors: dict[str, list[int]] = {}
    for _ in range(count):
        name, dims = cursor.text(), cursor.number("<I")
        if dims > 8:
            raise ValueError("GGUF tensor rank out of range")
        shape = [cursor.number("<Q") for _ in range(dims)]
        cursor.take(12)  # 类型(u32)、数据偏移(u64)
        tensors[name] = shape[::-1]
    return tensors


def _gguf(comfy: Comfy, path: str, first: bytes, *, tensors: bool = True) -> Header:
    """不够就往后再读(每次四倍,到 HEADER_LIMIT 为止)。张量表读不全时只交出架构名和尺寸 —— 半张表拿来认,可能认成别的。
    `tensors=False` 时不往后读:开头那一段里的键值就够了。"""
    data, wanted = first, FIRST_READ
    while True:
        found: dict[str, Any] = {}
        try:
            return Header({}, _parse_gguf(data, found), found.get("architecture", ""), found.get("sizes", {}))
        except _Short:
            if not tensors or len(data) < wanted or wanted >= HEADER_LIMIT:
                return Header({}, {}, found.get("architecture", ""), found.get("sizes", {}))  # 够用了、文件到头了,或到上限了
        wanted = min(wanted * 4, HEADER_LIMIT)
        data += comfy.get_range(path, len(data), wanted - 1) or b""


def plain(value: str) -> bool:
    """文件名、目录名只能是一段:不带路径分隔符、不是 `.` / `..`、没有控制字符。"""
    text = (value or "").strip()
    return bool(text) and text not in (".", "..") and not any(mark in text for mark in ("/", "\\", ":", "\x00")) \
        and all(ord(char) >= 32 for char in text)


def data_file(comfy: Comfy, kind: str) -> Path | None:
    """插件持久目录里这台服务器的一份记录(按服务器地址分开:几台 ComfyUI 记在一个文件里会互相覆盖)。"""
    root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    if not root:
        return None
    return Path(root) / f"{kind}-{hashlib.sha1(comfy.base.encode()).hexdigest()[:12]}.json"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def save_json(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
    except OSError:
        pass  # 记不下就下次再读一遍,不该让列表失败

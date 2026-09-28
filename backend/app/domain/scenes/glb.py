"""GLB(二进制 glTF 2.0)的容器格式:12 字节文件头,后面是若干块 —— 先一块 JSON(文档),再可选一块
二进制(顶点、贴图这些资源)。规格见 glTF 2.0 §4.4「GLB File Format Specification」。

这个格式有三处要读写:导入模型时校验(只读文件头和 JSON 块,资源一个字节都不碰)、白模渲染读网格
(整份读)、发往 Blender 时把场景写成 GLB。此前三处各写一遍,魔数和块类型散在两个文件里,对「文件头
声明的长度」的口径也不一样 —— 导入时核对它和文件大小,渲染读取时不看。现在只有这一份。

这里只懂格式,不懂业务:错误是不带文案的 `GlbError`,由调用方翻成自己领域的话。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import BinaryIO

MAGIC = b"glTF"
VERSION = 2
JSON_CHUNK = 0x4E4F534A  # "JSON"
BIN_CHUNK = 0x004E4942  # "BIN\0"
#: 文件头 12 字节(魔数、版本、总长)+ 第一块的块头 8 字节(长度、类型)。
_HEAD = struct.Struct("<4sIIII")
_CHUNK_HEAD = struct.Struct("<II")


class GlbError(ValueError):
    """不是一份合法的 GLB。`reason`:`version`(不是 2.0)、`layout`(长度或块对不上)、`no_json`(没有 JSON 块)。"""

    def __init__(self, reason: str, **params: object) -> None:
        super().__init__(reason)
        self.reason = reason
        self.params = params


def is_glb(head: bytes) -> bool:
    """看开头几个字节就够:GLB 以 `glTF` 开头,内嵌 glTF 是一份 JSON 文本。"""
    return head[:4] == MAGIC


def peek_is_glb(source: BinaryIO) -> bool:
    """看头 4 个字节判格式,再把位置放回去。"""
    where = source.tell()
    head = source.read(4)
    source.seek(where)
    return is_glb(head)


def read_document(stream: BinaryIO, size: int) -> dict:
    """只读文件头和 JSON 块,返回 glTF 文档。`size` 是整份文件的字节数,用来核对头里声明的总长。

    一份 500 MB 的模型,这里读进来的通常是几百 KB —— 资源都在后面的二进制块里,不读。
    """
    try:
        magic, version, length, chunk_size, chunk_type = _HEAD.unpack(stream.read(_HEAD.size))
    except struct.error as exc:
        raise GlbError("layout") from exc
    if magic != MAGIC:
        raise GlbError("layout")
    if version != VERSION:
        raise GlbError("version", version=version)
    if length != size or chunk_type != JSON_CHUNK or chunk_size > size - _HEAD.size:
        raise GlbError("layout")
    return json.loads(stream.read(chunk_size))


def read(raw: bytes) -> tuple[dict, bytes | None]:
    """整份读:→ (glTF 文档, 二进制块;没有就是 None)。"""
    try:
        magic, version, length = struct.unpack_from("<4sII", raw, 0)
    except struct.error as exc:
        raise GlbError("layout") from exc
    if magic != MAGIC or length != len(raw):
        raise GlbError("layout")
    if version != VERSION:
        raise GlbError("version", version=version)
    document: dict | None = None
    blob: bytes | None = None
    offset = 12
    while offset + _CHUNK_HEAD.size <= len(raw):
        chunk_size, chunk_type = _CHUNK_HEAD.unpack_from(raw, offset)
        body = raw[offset + _CHUNK_HEAD.size:offset + _CHUNK_HEAD.size + chunk_size]
        if chunk_type == JSON_CHUNK:
            document = json.loads(body.decode("utf-8"))
        elif chunk_type == BIN_CHUNK:
            blob = body
        offset += _CHUNK_HEAD.size + chunk_size
    if document is None:
        raise GlbError("no_json")
    return document, blob


def write(target: Path, document: dict, blob: bytes) -> None:
    """写一份 GLB。两块都按规格补齐到 4 字节:JSON 用空格,二进制用 0。空的二进制块不写。"""
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    length = 12 + _CHUNK_HEAD.size + len(payload) + (_CHUNK_HEAD.size + len(blob) if blob else 0)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        out.write(struct.pack("<4sII", MAGIC, VERSION, length))
        out.write(_CHUNK_HEAD.pack(len(payload), JSON_CHUNK))
        out.write(payload)
        if blob:
            out.write(_CHUNK_HEAD.pack(len(blob), BIN_CHUNK))
            out.write(blob)

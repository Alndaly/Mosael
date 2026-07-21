"""模型输出清洗:重组 llama.cpp 系 byte-fallback token。

本地推理服务(Ollama / LM Studio 等 llama.cpp 系)对 tokenizer 词表外的字符
(常见于 emoji)会走 byte-fallback:模型逐字节输出 `<0xF0>` 这样的 token,
某些版本 detokenize 时把它们**按字面文本**吐出,于是 UI 看到
`<0xF0><0x9F><0x97><0x84>`(实为 🗄 的 UTF-8 四字节)。这不是 Mibu 的解析问题
——文本到达时就已是这些字面字符。这里把连续的 `<0xXX>` 串重组回 UTF-8;
解不出合法 UTF-8 的串原样保留(宁可显示原文,不可吞内容)。
"""

from __future__ import annotations

import re

_BYTE_RUN = re.compile(r"(?:<0[xX][0-9a-fA-F]{2}>)+")
_BYTE = re.compile(r"<0[xX]([0-9a-fA-F]{2})>")


def decode_byte_fallback(text: str) -> str:
    if "<0x" not in text and "<0X" not in text:
        return text

    def _decode(match: re.Match[str]) -> str:
        raw = bytes(int(byte, 16) for byte in _BYTE.findall(match.group(0)))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return match.group(0)

    return _BYTE_RUN.sub(_decode, text)

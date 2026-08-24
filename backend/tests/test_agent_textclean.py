"""byte-fallback 重组:本地推理服务把 emoji 吐成 <0xF0> 字面 token 的兜底。"""

from __future__ import annotations

from app.domain.agent.textclean import decode_byte_fallback


def test_reassembles_the_exact_run_from_the_bug_report() -> None:
    assert decode_byte_fallback("3. <0xF0><0x9F><0x97><0x84> 什么时候用哪个工具?") == "3. 🗄 什么时候用哪个工具?"


def test_multiple_runs_in_one_text() -> None:
    assert decode_byte_fallback("<0xE2><0x9C><0x85> 完成 <0xF0><0x9F><0x8E><0xAC>") == "✅ 完成 🎬"


def test_invalid_utf8_run_is_left_verbatim() -> None:
    # 宁可显示原文,不可吞内容或产生替换符。
    assert decode_byte_fallback("坏串 <0xF0><0x28>") == "坏串 <0xF0><0x28>"


def test_plain_text_passes_through() -> None:
    text = "普通文本,包含 <code> 与 0x1F 但没有字节 token"
    assert decode_byte_fallback(text) is text

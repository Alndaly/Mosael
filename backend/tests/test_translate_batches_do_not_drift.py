"""前端的分批大小不能超过后端的上限。

真机反馈:「翻译最多只能翻译 500 条 超出就会报错」。500 是这个接口的安全阀,而分批放在了
前端的 `translateTexts`(唯一出口)。两个数字分处两个仓目录,谁也不认识谁 —— 后端哪天把上限
调小,前端仍按老数字切,于是又变回「超过就报错」,而且只在长字幕轨上才现形。

所以这里把两边钉在一起。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.api.schemas import TranslateRequest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "client.ts"


def _backend_cap() -> int:
    field = TranslateRequest.model_fields["texts"]
    caps = [m.max_length for m in field.metadata if getattr(m, "max_length", None) is not None]
    assert caps, "TranslateRequest.texts 不再有条数上限?那这条约束要跟着改"
    return caps[0]


def _frontend_batch() -> int:
    text = FRONTEND.read_text(encoding="utf-8")
    match = re.search(r"const TRANSLATE_BATCH = (\d+);", text)
    assert match, "前端不再有 TRANSLATE_BATCH —— 分批没了的话长字幕轨又会 422"
    return int(match.group(1))


def test_the_frontend_batch_fits_inside_the_backend_cap() -> None:
    backend, frontend = _backend_cap(), _frontend_batch()
    assert frontend <= backend, (
        f"前端一次送 {frontend} 条,而后端只收 {backend} 条 —— 长字幕轨会 422"
    )


def test_the_batch_is_not_pointlessly_small() -> None:
    """切得太碎就是把一次往返变成几十次,而每一批后端内部本来就并发。"""
    assert _frontend_batch() >= _backend_cap() // 4

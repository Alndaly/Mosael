"""「找不到」是 404,跟请求用什么语言无关。

时间线和转写两处曾经靠 `"not found" in str(exc)` 决定回 404 还是 422 —— 而 `str(exc)` 是按请求语言
翻过的:中文请求拿到「找不到这条时间线」,里面没有 "not found",于是同一件事中文回 422、英文回 404。
现在状态码由错误类型自己带(同场景、资产库、笔记的做法),边界照着翻。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.sequences import _respond
from app.core.i18n import get_current_locale, set_current_locale
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.transcripts.operations import TranscriptAssetNotFound, TranscriptDomainError


@pytest.fixture
def chinese():
    before = get_current_locale()
    set_current_locale("zh")
    yield
    set_current_locale(before)


def _raise(exc: Exception):
    def operation() -> None:
        raise exc

    return operation


def test_中文请求里时间线不存在也是_404(chinese) -> None:
    with pytest.raises(HTTPException) as caught:
        _respond(None, None, "s", _raise(SequenceNotFound("seqErr_sequenceNotFound")))
    assert caught.value.status_code == 404
    assert "not found" not in str(caught.value.detail).lower()  # 真的是中文那句


def test_其余时间线错误仍是_422(chinese) -> None:
    with pytest.raises(HTTPException) as caught:
        _respond(None, None, "s", _raise(SequenceDomainError("seqErr_assetHasNoLength")))
    assert caught.value.status_code == 422


def test_转写找不到素材的状态码由类型给() -> None:
    assert TranscriptAssetNotFound("x").status == 404
    assert TranscriptDomainError("x").status == 422

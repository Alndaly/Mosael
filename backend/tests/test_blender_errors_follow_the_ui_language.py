"""Blender 互通的报错跟着界面语言走,上游原文放进翻好的句子里。

此前是写死的中文句子,英文界面里弹出来的是中文,中间还夹着 Blender MCP 原样透传的英文
(「Blender 未完成同步:Error executing code: Could not connect to Blender…」)。最常见的
「Add-on 没开」认出来,给一句照着做就行的话。
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.i18n import MESSAGES, set_current_locale
from app.domain.blender.bridge import BlenderNotFound, upstream_failure
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def _reset_locale():
    yield
    set_current_locale("zh")


def test_the_same_error_reads_in_the_current_language() -> None:
    error = BlenderNotFound("blenderErr_noConnection")
    set_current_locale("en")
    assert str(error).startswith("Blender isn't connected yet")
    set_current_locale("zh")
    assert str(error).startswith("还没有连接 Blender")


def test_addon_not_running_becomes_an_actionable_sentence() -> None:
    raw = "Error executing code: Could not connect to Blender. Make sure the Blender addon is running."
    assert upstream_failure(raw, "blenderErr_syncFailedNoDetail").key == "blenderErr_addonNotRunning"


def test_other_upstream_text_is_framed_not_translated() -> None:
    error = upstream_failure("Traceback: KeyError 'foo'", "blenderErr_syncFailedNoDetail")
    set_current_locale("en")
    assert str(error) == "Blender didn't finish syncing: Traceback: KeyError 'foo'"
    assert upstream_failure("", "blenderErr_unresponsive").key == "blenderErr_unresponsive"


def test_every_blender_message_has_both_languages() -> None:
    keys = [key for key in MESSAGES if key.startswith("blenderErr_")]
    assert keys
    for key in keys:
        assert MESSAGES[key].get("zh") and MESSAGES[key].get("en"), key


def test_the_api_answers_in_the_requested_language(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "local_desktop", True)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    en = client.post(f"/api/scenes/blender/pull?workspace_id={ws['id']}&instance_id=", headers={"Accept-Language": "en-US"})
    assert en.status_code == 404
    assert en.json()["detail"] == "This Blender connection wasn't found."
    zh = client.post(f"/api/scenes/blender/pull?workspace_id={ws['id']}&instance_id=", headers={"Accept-Language": "zh-CN"})
    assert zh.json()["detail"] == "找不到这个 Blender 连接。"

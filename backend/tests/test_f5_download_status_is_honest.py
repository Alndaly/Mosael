"""语言包下载的状态要能落到一个**说得清**的样子。

维护者截图:配音面板里点「下载这个模型」,先是「下载中 0% · 0 MB / 5.4 GB」一动不动,过一会儿
那一行回到「下载这个模型」—— 既没说失败,也没说原因。

这里钉的是后端这一半:

- 正在下:字节 / 总量 / 速度都要报;总量还没量到就是 **None**,不是 0(0 会被界面当分母,
  画出一条"从来没动过"的 0%);
- 失败:原因要是一个能翻的 key(我们自己抛的)或第三方库的原话 —— 不能只剩一个空 message;
- 连不上下载源:说清楚是哪个源、并且下一次该换源 —— 那才是用户能做的动作;
- 重试:上一次的字节 / 总量 / 失败原因不能留在记录上,否则第一眼看到的是上一次的进度。

**不下载任何东西**:下载请求、大小查询都打桩,盘上只动 tmp_path。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.runtime import f5_models
from app.ai.runtime.download_state import DownloadProgress
from app.core.i18n import translate_fields

_JA = f5_models._BY_ID["ja"]


def _row(model: f5_models.F5Model = _JA) -> dict:
    return f5_models.status(model)


def _forget_failed_at() -> None:
    """`_failed_at` 是这次修复新加的。回退到旧代码验证"先红"时它不存在 —— 清理动作不该因此
    让整条用例以 AttributeError 结束,那样看到的就不是"行为没修好"而是"测试写错了"。"""
    getattr(f5_models, "_failed_at", {}).pop("ja", None)


@pytest.fixture(autouse=True)
def _clean_live():
    """每条用例前后都把直播状态清掉 —— 一条留下的 "downloading" 会让下一条读到别人的状态。"""
    f5_models.clear_live("ja")
    _forget_failed_at()
    yield
    f5_models.clear_live("ja")
    _forget_failed_at()


def test_a_download_reports_bytes_speed_and_eta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    f5_models._store.set(
        "ja",
        DownloadProgress(
            status="downloading",
            downloaded=1_200_000_000,
            total=5_400_000_000,
            speed=1_500_000.0,
            eta=2_800.0,
            progress=0.22,
            message="dlMsg_downloading",
        ),
    )

    row = _row()

    assert row["status"] == "downloading"
    assert row["downloaded_bytes"] == 1_200_000_000
    assert row["total_bytes"] == 5_400_000_000
    assert row["speed_bps"] == 1_500_000.0
    assert row["eta_seconds"] == 2_800.0
    assert row["progress"] == 0.22


def test_an_unknown_total_is_none_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """还没量到总量时不能报 0:界面拿 0 当分母,画出来的是一条永远不会动的 0%。"""
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    f5_models._store.set("ja", DownloadProgress(status="downloading", downloaded=0, total=0))

    row = _row()

    assert row["status"] == "downloading"
    assert row["total_bytes"] is None, f"未知总量被报成了 {row['total_bytes']}"


def test_a_failure_keeps_a_reason_that_can_be_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    """我们自己的失败带 key,出口按读的人的语言翻 —— 不是一句空 message。"""
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    f5_models._store.set(
        "ja",
        DownloadProgress(status="failed", message="runtimeErr_f5RuntimeMissing", error="boom"),
    )

    row = translate_fields(_row(), ("label", "note", "message"), "en")

    assert row["status"] == "failed"
    assert row["message"] == (
        "Install the F5-TTS runtime first under Admin → Engines → Speech synthesis engines (deployment admins only)"
    )
    assert "message_params" not in row, "参数栏该被出口摘掉,不然前端会把它当字段读"
    assert row["error"] == "boom", "原文要留着,排障时只有它说得出是哪一层出的错"


def test_retry_does_not_show_the_previous_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """重试的第一眼不能还是上一次的字节数和失败原因。"""
    monkeypatch.setattr(f5_models, "installed", lambda model: False)
    monkeypatch.setattr(f5_models, "downloading", lambda: "")
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    monkeypatch.setattr(f5_models, "_run_download", lambda model_id: None)
    f5_models._store.set(
        "ja",
        DownloadProgress(
            status="failed",
            downloaded=9_000_000,
            total=5_400_000_000,
            speed=5.0,
            eta=99.0,
            progress=0.01,
            message="runtimeErr_f5DownloadFailed",
            params={"detail": "上一回"},
            error="上一回",
        ),
    )
    if hasattr(f5_models, "_failed_at"):
        f5_models._failed_at["ja"] = "2026-10-19T12:33:00+00:00"

    row = f5_models.start_download("ja")

    assert row["status"] == "downloading"
    assert row["downloaded_bytes"] == 0, f"重试还挂着上一次的字节数:{row['downloaded_bytes']}"
    assert row["total_bytes"] is None, f"重试还挂着上一次的总量:{row['total_bytes']}"
    assert row["message"] == "dlMsg_preparing"
    assert row["error"] == ""
    assert row["speed_bps"] == 0.0
    assert row["eta_seconds"] is None
    assert row.get("failed_at", "") == "", f"重试还挂着上一次的失败时间:{row.get('failed_at')}"


def test_a_connection_failure_says_which_source_and_what_to_do(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """连不上源的时候,主句说清是哪个源、并指到真能换源的那一页;库的英文原文进 `error`(详情)。"""
    from app.ai.runtime import config as tts_config
    from app.ai.runtime import tts_daemon, tts_models
    from app.core.i18n import render_message

    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (1_000, False))
    monkeypatch.setattr(f5_models, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python")
    monkeypatch.setattr(tts_models, "_worker_env", lambda python="": {})
    monkeypatch.setattr(tts_config, "get", lambda: SimpleNamespace(hf_endpoint="https://hf-mirror.com"))

    class _Pool:
        def request(self, *args, **kwargs):
            raise RuntimeError(
                "huggingface_hub.errors.LocalEntryNotFoundError: An error happened while trying to "
                "locate the file on the Hub and we cannot find the requested files in the local "
                "cache. Please check your connection"
            )

    monkeypatch.setattr(tts_daemon, "pool", lambda: _Pool())

    f5_models._run_download("ja")

    live = f5_models._store.get("ja")
    assert live is not None, "失败了却没留下状态 —— 界面上就是「加载一会儿就没了」"
    assert live.status == "failed"
    assert live.message == "runtimeErr_hubUnreachable", live.message
    assert live.params["endpoint"] == "https://hf-mirror.com"
    #: 原文不再进模板参数/主句:它是「详情」,主句一截就只剩「An error…」。
    assert "detail" not in live.params, live.params
    assert "LocalEntryNotFoundError" in live.error, "原文丢了,详情里什么都没得看"
    shown = render_message(live.message, "zh", live.params)
    assert "LocalEntryNotFoundError" not in shown, shown
    assert "hf-mirror.com" in shown and "管理 → 引擎 → 下载源" in shown, shown
    assert f5_models.status(_JA).get("failed_at"), "终态没有时间 —— 界面说不出「最后一次 …」"


def test_our_own_failure_keeps_its_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """F5 运行环境没装:这是一句我们能翻的话,不能掉进「第三方库原文」那一档。"""
    from app.ai.runtime import tts_models

    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)

    f5_models._run_download("ja")

    live = f5_models._store.get("ja")
    assert live is not None and live.status == "failed"
    assert live.message == "runtimeErr_f5RuntimeMissing"
    assert live.params == {}


def test_an_attempt_killed_by_a_restart_still_shows_up(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """被杀的下载(应用退出 / 后端重启)在内存里什么都不剩,而盘上还留着半截。

    这时候报 missing 的话,界面会回到「下载这个模型」—— 用户看到的就是"加载一会儿就没了,
    像根本没点过"。盘上的痕迹要能把这一句说出来。
    """
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    target = tmp_path / "ja" / ".cache" / "huggingface" / "download" / "JA_21999120"
    target.mkdir(parents=True)
    (target / "model_21999120.pt.lock").write_text("")

    row = _row()

    assert row["status"] == "failed", f"被杀的下载被报成了 {row['status']}"
    assert row["message"] == "runtimeErr_f5DownloadInterrupted"
    assert row["failed_at"], "盘上有痕迹,却说不出「最后一次」是什么时候"


def test_a_model_never_touched_is_still_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """没有任何痕迹就是没下过 —— 不能把所有 missing 都说成"上次没下完"。"""
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))

    assert _row()["status"] == "missing"
    assert _row()["message"] == ""
    assert _row()["failed_at"] == ""


def test_another_languages_partial_files_are_not_the_base_models(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """基础模型落在根下 —— 别的语言包躺在同一个根里,不能算成它的痕迹。"""
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    (tmp_path / "ja" / ".cache").mkdir(parents=True)
    (tmp_path / "ja" / ".cache" / "half").write_text("x")

    base = f5_models._BY_ID["base"]

    assert _row(base)["status"] == "missing", "把别的语言包的半截算到基础模型头上了"


def test_the_list_route_gives_the_reason_in_the_readers_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """出口也要翻:`GET /api/tts/f5-models` 到英文界面时不能冒出一串 runtimeErr_*。

    光测 `translate_fields` 不够 —— 路由里漏掉一个字段,测试照样全绿,而界面上显示的是 key。
    """
    from tests.util import fresh_client

    monkeypatch.setattr(f5_models, "measured_total", lambda model, blocking=False: (5_400_000_000, False))
    f5_models._store.set(
        "ja",
        DownloadProgress(status="failed", message="runtimeErr_f5RuntimeMissing", error="boom"),
    )

    client = fresh_client()
    row = next(item for item in client.get("/api/tts/f5-models", headers={"Accept-Language": "en-US"}).json() if item["id"] == "ja")

    assert row["status"] == "failed"
    assert row["message"] == (
        "Install the F5-TTS runtime first under Admin → Engines → Speech synthesis engines (deployment admins only)"
    )
    assert "message_params" not in row

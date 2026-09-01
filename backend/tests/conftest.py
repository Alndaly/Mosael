"""Isolate every test run in a throwaway data dir BEFORE app modules import.

Without this, reset_db() would drop tables in the developer's live
~/.open-studio/open-studio.db. Environment variables outrank .env in pydantic-settings,
so setting OPEN_STUDIO_DATA_DIR here is sufficient.
"""

from __future__ import annotations

import os
import tempfile

os.environ["OPEN_STUDIO_DATA_DIR"] = tempfile.mkdtemp(prefix="open-studio-test-")
# Tests drive the scheduler tick() directly; the background loop stays off.
os.environ["OPEN_STUDIO_SCHEDULER_ENABLED"] = "0"
# 两个部署级开关在**测试里**打开:整套用例早于它们存在,而且要覆盖的正是它们背后的行为
# (自由注册第二个用户、工作流的 code 节点)。开关自己的用例
# (test_registration_and_code_execution.py)显式把它们按回生产默认值,并单独断言**声明的默认值**
# 是关的 —— 这样"默认关"这件事不会因为测试环境开着而失去保护。
os.environ["OPEN_STUDIO_OPEN_REGISTRATION"] = "1"
os.environ["OPEN_STUDIO_SERVER_SIDE_CODE_EXECUTION"] = "1"
os.environ["OPEN_STUDIO_FEISHU_AUTOSTART"] = "0"
# Don't spawn ffmpeg proxy threads on every video import during the suite;
# test_proxy.py re-enables it explicitly to exercise the pipeline.
os.environ["OPEN_STUDIO_GENERATE_PROXIES"] = "0"
# Force software (libx264+CRF) export so render output is deterministic and we
# don't depend on a hardware encoder being present on the CI/dev box.
os.environ["OPEN_STUDIO_HW_ENCODE"] = "0"
# Don't launch a headless Chromium to rasterize subtitles/花字 in the suite; the ASS
# fallback path stays exercised and tests don't depend on Playwright/dist being present.
os.environ["OPEN_STUDIO_TEXT_RASTERIZE"] = "0"

import pytest


@pytest.fixture(autouse=True)
def _reset_asr_runtime_probe():
    """`asr_models.runtime_ready` / `transcription.resolve_transcription_runtime` 都带进程级缓存,而它们探测的是
    **真实机器**(起子进程 import funasr)。不清的话,一个用例 monkeypatch 出来的结果会渗给下一个,
    表现是单独跑全绿、全量跑红。"""
    from app.ai.runtime import asr_models

    def reset() -> None:
        asr_models.clear_runtime_probes()
        # 下载状态也是进程级的:一个用例留下的 "downloading" 会让后面的用例读到别人的状态
        # (而 start_download 还会因此拒绝服务:「已有模型正在下载」)。
        with asr_models._store._lock:
            asr_models._store._live.clear()

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _no_model_catalog_network():
    """**测试套不许去问真实的模型目录。**

    对话启动会顺手查一下端点的模型列表(拿上下文窗口)。测试里配的都是假地址,而这台机器
    走代理时,连不上的地址不会立刻被拒,要挂满 8 秒才超时 —— 恰好等于 `_wait_idle` 的 8 秒,
    于是两个 8 秒赛跑,谁先到看当时网络。表现出来就是 agent 那一批**概率性**变红:
    单独跑绿(目录被前一个用例缓存了),随机顺序跑红(缓存键对不上,真的出网)。
    倒下的那个还会连累后面几个——`fresh_client` 只等 5 秒就重建库,而线程还卡在网络上。

    进程级缓存也一并清掉:跨用例渗漏正是"单独跑全绿、全量跑红"的另一半原因。
    """
    from app.ai import model_catalog

    model_catalog.clear_cache()
    yield
    model_catalog.clear_cache()


@pytest.fixture(autouse=True)
def _catalog_returns_nothing(monkeypatch):
    """默认让目录查询直接返回空 —— 要测目录本身的用例自己 monkeypatch `httpx.get`
    (见 tests/test_model_catalog.py,它 stub 的是更底下那一层,不受这条影响)。"""
    from app.ai import model_catalog

    monkeypatch.setattr(model_catalog, "cached_model", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _no_remote_size_network():
    """**测试套不许去问下载源的文件大小。**

    列模型卡片会顺手问一次"这些权重实际多大"(ai/runtime/remote_size)。缓存缺失时它在后台起线程
    去请求 —— 测试里那就是真的出网,慢、看网络脸色、而且线程会活过测试本身。
    和模型目录那条同一个道理(见 _no_model_catalog_network),这里一并挡掉:
    默认返回 None = "问不到",于是各处退回目录里那个估算值,正是没有网络时的真实行为。
    """
    from app.ai.runtime import remote_size

    remote_size.clear_cache()
    yield
    remote_size.clear_cache()


@pytest.fixture(autouse=True)
def _remote_size_says_unknown(monkeypatch):
    """要测 remote_size 自己的用例请打桩更底下那一层(httpx),不受这条影响。"""
    from app.ai.runtime import remote_size

    monkeypatch.setattr(remote_size, "cached_files", lambda *a, **kw: None)
    monkeypatch.setattr(remote_size, "files_for", lambda *a, **kw: None)

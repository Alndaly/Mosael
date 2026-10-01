"""登记之后马上补写进 media_info 的键,不被正在转码的代理任务抹掉。

代理线程在转码**之前**读出素材,转码一跑几十秒,结束时把那份旧的 media_info 整份写回 —— 这期间
改口型记下的块标记(dub_lipsync_chunk)就没了,重跑时每一块都再买一次。走真的代理任务(真的 ffmpeg 转码),
只让转码在「块标记写进去」之后才结束,把那条缝撑开。
"""

from __future__ import annotations

import shutil
import subprocess
import threading

import pytest

import app.domain.assets.proxies as proxies
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Workspace
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import wait_for_idle_jobs
from app.domain.workflows.executors.dub_lipsync import CHUNK_KEY, _cached_chunk, _remember_chunk
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_代理转码期间记下的块标记_转码结束后还在_重跑认得出(monkeypatch) -> None:
    fresh_client()
    monkeypatch.setattr(settings, "generate_proxies", True)
    source = settings.data_dir / "chunk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
                    "-pix_fmt", "yuv420p", str(source)], check=True)

    started, release = threading.Event(), threading.Event()
    real_build = proxies.build_proxy

    def slow_build(src, target):
        #: 真的转码,只是等块标记写进去之后才收尾 —— 线上就是这个顺序(转码几十秒,标记在生成任务落地后就写)。
        started.set()
        release.wait(30)
        return real_build(src, target)

    monkeypatch.setattr(proxies, "build_proxy", slow_build)
    with unit_of_work() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        made = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=source, name="对口型第 1 块")
        ws_id, asset_id = ws.id, made.id

    assert started.wait(30), "登记时就派了代理任务,它已经读出了素材、开始转码"
    _remember_chunk(asset_id, "KEY123")
    release.set()
    assert wait_for_idle_jobs(timeout=60)

    with SessionLocal() as db:
        info = db.get(Asset, asset_id).media_info
        assert info.get("proxy_status") == "ready" and info.get("proxy_key"), "代理照样落成"
        assert info.get(CHUNK_KEY) == "KEY123", "转码期间写进去的块标记没被代理的旧值盖掉"
        assert _cached_chunk(db, ws_id, "KEY123") == asset_id, "重跑时认得出这一块,不再花一次钱"
        assert info.get("width") == 320, "登记时探测的字段也都还在"

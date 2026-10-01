"""转写引擎没报语种时,逐字稿的语种记空(认不出),不回落成 "zh"。

回落的 "zh" 和真检测出来的 "zh" 下游分不清:英文片子(插件转写不报语种、paraformer 不带语种标记)被记成中文,
译配译成简体中文时被「原文已经是目标语言」拦下。

已有逐字稿里由回落写成的 "zh" 和真检测出的 "zh" 分不出来,所以**不迁移**:那几份照旧,遇到误拦在翻译节点上把
「原文语言」清空即可(节点说明里写着)。
"""

from __future__ import annotations

import subprocess
import sys
import types

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Transcript, Workflow
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import wait_for_idle_jobs
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def test_paraformer_没有语种标记_请求也没指定_报空不报中文(monkeypatch) -> None:
    """走真的 worker 函数(run_funasr),只把 funasr 库换成给出 paraformer 形状结果(没有 <|en|> 这类标记)的替身。"""
    from app.ai.runtime.workers import asr

    class AutoModel:
        def __init__(self, **_kwargs) -> None:
            pass

        def generate(self, **_kwargs):
            return [{"sentence_info": [{"text": "hello there everyone", "timestamp": [[0, 400], [400, 900]], "spk": 0}]}]

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=AutoModel))
    out = asr.run_funasr({"audio_path": "x.wav", "funasr_model": "paraformer-zh", "funasr_spk_model": ""})
    assert out["language"] == "", "没检测出、也没指定:认不出就是认不出"
    assert asr.run_funasr({"audio_path": "x.wav", "funasr_model": "paraformer-zh", "funasr_spk_model": "",
                           "language": "en"})["language"] == "en", "请求里指定了就用指定的"


def test_插件转写不报语种_逐字稿记空_英文译成中文不被当成同一种语言拦下(monkeypatch) -> None:
    from app.domain.voices import transcription

    class Plugin:
        engine_id = "plugin-asr"
        builtin = False
        name = "云端转写插件"

        def transcribe(self, wav, language):
            return {"segments": [{"start": 0.0, "end": 2.0, "text": "Hello there everyone"}]}

    monkeypatch.setattr(transcription, "transcriber", lambda db, user, provider: Plugin())
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = settings.data_dir / "english.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(source)], check=True)
    with SessionLocal() as db:
        video = register_file_asset(db, workspace_id=ws, project_id=None, source_path=source, name="english.mp4")
        db.commit()
        transcription.start_transcription(db, video.id, created_by=None)
        db.commit()
    assert wait_for_idle_jobs(30)
    with SessionLocal() as db:
        [transcript] = db.scalars(select(Transcript)).all()
        assert transcript.language == "", "引擎没报语种:记空,不是 zh"

    #: 译配模板把逐字稿的语种接到翻译节点的 source_lang 上:空串不比,英文照样译成中文。
    from app.domain import translate as translate_domain

    monkeypatch.setattr(translate_domain, "translate_many", lambda db, texts, target, **_kw: [f"[{target}]{t}" for t in texts])
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        out = get_executor("translate_lines")(db, workflow, {"texts": ["Hello there everyone"], "target_lang": "zh-CN",
                                                            "source_lang": transcript.language})
    assert out["texts"] == ["[zh-CN]Hello there everyone"]

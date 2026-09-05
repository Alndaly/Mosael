"""输入框里的语音输入:说完就用完,**不入库、不建任务**。

和「转写素材」是两件事,虽然识别用的是同一份实现。转写的产出是一份要留存、要能编辑、要投影
回时间线的逐字稿,所以它建 job、产出素材、进任务中心。听写要的只是"用户刚才说了什么" ——
走那条路的话,输入框里每说一句,素材库就多一个几秒钟的 wav 和一条转写记录,任务中心也跟着
刷屏。这条测试钉的就是这个区别。

上限也在这里钉:一段听写是"说一句话",不是"传一段素材"。越界要当场被拒,而不是悄悄占住那个
唯一的识别名额(kind=transcribe 的准入槽是 1)。
"""

from __future__ import annotations

from pathlib import Path

from app.db.models import Asset, Job
from app.core.db import SessionLocal
from app.domain.voices import transcription
from tests.util import fresh_client


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(Asset).count(), db.query(Job).count()


def test_听写不入素材库也不建任务(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    before = _counts()

    # 识别本身在别处验(test_asr_daemon_keeps_the_model_loaded);这里要的是"它没留下东西"。
    monkeypatch.setattr(transcription, "transcribe_clip", lambda *a, **k: "把这句话填进输入框")

    reply = client.post(
        "/api/asr/dictate",
        files={"clip": ("say.webm", b"not really audio, the engine is stubbed", "audio/webm")},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["text"] == "把这句话填进输入框"
    assert _counts() == before, "听写留下了素材或任务 —— 那是转写那条路的语义"


def test_太大的录音在读的时候就被拒(monkeypatch) -> None:
    """上限要在**读之前**生效。读完再判的话,拦住的只是"用不用",不是"收不收"。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    monkeypatch.setattr(transcription, "transcribe_clip", lambda *a, **k: "不该走到这里")

    from app.api.routes import asr as asr_routes

    oversized = b"x" * (asr_routes.DICTATION_MAX_BYTES + 1024)
    reply = client.post("/api/asr/dictate", files={"clip": ("big.webm", oversized, "audio/webm")})
    assert reply.status_code == 413, reply.text


def test_空录音说清楚而不是当成一句空话() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    reply = client.post("/api/asr/dictate", files={"clip": ("empty.webm", b"", "audio/webm")})
    assert reply.status_code == 422, reply.text


def test_识别失败是结果不是服务端故障(monkeypatch) -> None:
    """引擎没装、语言不支持这类失败要能原样显示给用户,而不是一个 500。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    def _boom(*_args, **_kwargs):
        raise transcription.ASRError("缺的是运行环境,不是模型")

    monkeypatch.setattr(transcription, "transcribe_clip", _boom)
    reply = client.post("/api/asr/dictate", files={"clip": ("a.webm", b"aa", "audio/webm")})
    assert reply.status_code == 422
    assert "运行环境" in reply.json()["detail"]


def test_说太久了单独说明(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    def _too_long(*_args, **_kwargs):
        raise transcription.DictationTooLong("这段录音 300 秒,超过了听写的 120 秒上限")

    monkeypatch.setattr(transcription, "transcribe_clip", _too_long)
    reply = client.post("/api/asr/dictate", files={"clip": ("a.webm", b"aa", "audio/webm")})
    assert reply.status_code == 413
    assert "120" in reply.json()["detail"]


def test_分段被拼成一句话不补空格(tmp_path: Path, monkeypatch) -> None:
    """引擎给的是分段(逐字稿的结构),听写要的是一句话。

    中文里用空格拼段是错的,而分段边界本来就落在停顿处 —— 直接接起来就是他说的那句。
    """
    monkeypatch.setattr(transcription, "probe_media", lambda _path: {"duration": 3.0})
    monkeypatch.setattr(transcription, "resolve_transcription_runtime", lambda *a, **k: ("python", "funasr"))
    monkeypatch.setattr(transcription, "_extract_audio", lambda _src, _dst: None)
    monkeypatch.setattr(
        transcription,
        "transcribe_with_engine",
        lambda *a, **k: {"segments": [{"text": "把这句话"}, {"text": "填进输入框"}]},
    )
    assert transcription.transcribe_clip(tmp_path / "x.webm") == "把这句话填进输入框"

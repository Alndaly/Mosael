"""管理 → 引擎 → 转写模型:五张卡上可以设一个「默认模型」。

**两层,不能互相代替:**

- **全局默认**(管理 → 引擎 → 转写模型,部署级):这台机器默认用哪一份权重;只有部署管理员能改,
  和「默认克隆引擎」同一类(那台机器上装了什么、默认用哪个,对所有用户是同一件事)。
- **按用途覆盖**(设置 → 智能体 → 语音对话 →「说话输入用哪一家」):听写这一条路单独挑一家;
  留空就用全局默认。它是**覆盖**,不是另一份默认 —— 所以不能拿它替换全局默认,也不能反过来。

实际生效的值只有一处算:`domain/asr` 的 `resolve_asr_model()`。听写和素材转写都经过它,
所以两边读到的永远是同一个答案(这一条也由本文件最后的棘轮钉着)。

设默认时**必须已经安装**:没装的设成默认,"默认"就是一句空话 —— 下一次转写照样得先下几个 GB。
不认识的 id 直接拒。
"""

from __future__ import annotations

from pathlib import Path

from app.ai.runtime import asr_models
from app.core.db import SessionLocal
from app.db.models import User
from app.domain.voices import transcription
from tests.util import fresh_client

WHISPER_LARGE = "whisperx-large-v3"
WHISPER_SMALL = "whisperx-small"
FUNASR = "funasr"


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one().id


def _installed(monkeypatch, *model_ids: str) -> None:
    """目录里说这几份在盘上。判据本身在 asr_models(真去量盘),这里替掉它 —— 不为一条用例放几个 GB。"""
    monkeypatch.setattr(
        asr_models,
        "is_installed",
        lambda model: (model.id if hasattr(model, "id") else str(model)) in model_ids,
    )


def _set_default(client, model_id: str):
    return client.put(f"/api/asr/models/{model_id}/default")


def _capture_worker(monkeypatch) -> dict:
    """把交给 worker 的那份请求记下来 —— 「实际用的模型」就以它为准。"""
    seen: dict = {}

    def _fake(_audio_path, _python, request):
        seen["request"] = request
        return {"language": "zh", "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]}

    monkeypatch.setattr(transcription, "_invoke_asr_worker", _fake)
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda _engine: "python")
    return seen


def _transcribe(model_id: str, tmp_path: Path) -> dict:
    """按 provider_id 走一次真的 transcribe_with_engine(只把 worker 换成桩)。"""
    from app.domain.asr import resolve_asr_model

    with SessionLocal() as db:
        resolved = resolve_asr_model(db, _me(), explicit=model_id, capability=transcription.CAPABILITY)
        chosen = transcription.transcriber(db, _me(), resolved.provider_id)
        return chosen.transcribe(tmp_path / "clip.wav")


def _choose_dictation(client, engine: str) -> None:
    reply = client.put(
        "/api/settings/agent-voice",
        json={
            "engine": "edge",
            "engine_voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1,
            "enabled": False,
            "asr_engine": engine,
        },
    )
    assert reply.status_code == 200, reply.text


# ---------------------------------------------------------------------------
# ① 能设默认;未安装的设不了;不认识的 id 直接拒
# ---------------------------------------------------------------------------
def test_已安装的模型能设成默认_列表里标出来(monkeypatch) -> None:
    client = _client()
    _installed(monkeypatch, WHISPER_LARGE)

    reply = _set_default(client, WHISPER_LARGE)

    assert reply.status_code == 200, reply.text
    assert reply.json()["is_default"] is True
    rows = client.get("/api/asr/models").json()
    assert [row["id"] for row in rows if row["is_default"]] == [WHISPER_LARGE]


def test_未安装的模型设不了默认_而且不留下半份设置(monkeypatch) -> None:
    """没装的设成默认,"默认"就是一句空话 —— 下一次转写照样得先下几个 GB。"""
    client = _client()
    _installed(monkeypatch, WHISPER_LARGE)  # 只装了 large,small 不在盘上

    reply = _set_default(client, WHISPER_SMALL)

    assert reply.status_code == 409, reply.text
    assert "下载" in reply.json()["detail"], reply.json()["detail"]
    assert not any(row["is_default"] for row in client.get("/api/asr/models").json())


def test_不认识的模型id直接拒(monkeypatch) -> None:
    client = _client()
    _installed(monkeypatch, WHISPER_LARGE)

    assert _set_default(client, "whisperx-ultra").status_code == 404


def test_只有部署管理员能改默认(monkeypatch) -> None:
    """默认是**这台机器**的设定(和下载权重同一类),所以和下载一样只给部署管理员。"""
    from tests.util import second_client

    _client()
    _installed(monkeypatch, WHISPER_LARGE)
    member = second_client("member")

    assert _set_default(member, WHISPER_LARGE).status_code == 403


# ---------------------------------------------------------------------------
# ② 默认立刻生效:转写功能实际用的模型 = 全局默认
# ---------------------------------------------------------------------------
def test_转写实际用的模型就是设的那个默认(monkeypatch, tmp_path) -> None:
    """设的是 WhisperX Large v3,worker 收到的 `whisper_model` 就必须是 large-v3 —— 不是配置里的 small。"""
    client = _client()
    _installed(monkeypatch, WHISPER_LARGE)
    assert _set_default(client, WHISPER_LARGE).status_code == 200
    seen = _capture_worker(monkeypatch)

    _transcribe("", tmp_path)

    assert seen["request"]["provider"] == "whisperx", seen["request"]
    assert seen["request"]["whisper_model"] == "large-v3", seen["request"]


def test_没设默认时保持原来的行为_whisper用配置里的型号(monkeypatch, tmp_path) -> None:
    """不设默认 = 和这一版之前完全一致(自动挑第一个能用的引擎、型号读配置)。"""
    _client()
    seen = _capture_worker(monkeypatch)
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda engine: "python" if engine == "whisperx" else None)

    _transcribe("builtin:whisperx", tmp_path)

    assert seen["request"]["provider"] == "whisperx"
    assert seen["request"]["whisper_model"] == transcription.settings.asr_whisper_model


# ---------------------------------------------------------------------------
# ③ 覆盖优先;清掉覆盖回到全局默认
# ---------------------------------------------------------------------------
def test_语音对话选了谁就用谁_清掉之后回到全局默认(monkeypatch, tmp_path) -> None:
    client = _client()
    _installed(monkeypatch, WHISPER_LARGE, FUNASR)
    assert _set_default(client, WHISPER_LARGE).status_code == 200
    seen = _capture_worker(monkeypatch)
    from app.api.routes.asr import resolve_dictation_engine

    #: 覆盖已设:听写用 FunASR,而不是默认的 WhisperX。
    _choose_dictation(client, "builtin:funasr")
    assert resolve_dictation_engine(_me(), "") == "builtin:funasr"
    _transcribe(resolve_dictation_engine(_me(), ""), tmp_path)
    assert seen["request"]["provider"] == "funasr", seen["request"]

    #: 覆盖清掉:回到全局默认(WhisperX Large v3)。
    _choose_dictation(client, "")
    assert resolve_dictation_engine(_me(), "") == ""
    _transcribe(resolve_dictation_engine(_me(), ""), tmp_path)
    assert seen["request"]["provider"] == "whisperx", seen["request"]
    assert seen["request"]["whisper_model"] == "large-v3", seen["request"]


def test_个人在能力提供方定过的转写默认优先于部署默认(monkeypatch, tmp_path) -> None:
    """一个人自己点过「能力提供方 → 转写」,那是**他做的选择**;部署默认只补"他没选过"的那一半。

    选的是 WhisperX(不是"不定时本来就会用的" FunASR),所以它是一次真的选择、会被存下来。
    """
    client = _client()
    _installed(monkeypatch, FUNASR, WHISPER_LARGE)
    assert _set_default(client, FUNASR).status_code == 200
    reply = client.put("/api/settings/capabilities/transcription", json={"provider_id": "builtin:whisperx"})
    assert reply.status_code == 200, reply.text
    seen = _capture_worker(monkeypatch)

    _transcribe("", tmp_path)

    assert seen["request"]["provider"] == "whisperx", seen["request"]


# ---------------------------------------------------------------------------
# ⑤ 一处解析:有效模型只能由一个函数决定
# ---------------------------------------------------------------------------
def test_有效模型只有一处解析() -> None:
    """`AsrConfig` 只在 domain/asr 里读;`resolve_asr_model` 只在 transcriber 里调一次。

    任何一个入口自己再算一遍,迟早给出两个答案 —— 管理页写着一个、转写用的是另一个,
    而用户看到的是"设了却没生效"。
    """
    app_root = Path(__file__).resolve().parents[1] / "app"
    readers = sorted(
        str(path.relative_to(app_root)) for path in app_root.rglob("*.py") if "AsrConfig" in path.read_text()
    )
    #: ownership 只是归属地图上的一笔(它不读值),另外三处是模型定义、模型出口和那一个解析点。
    assert readers == [
        "db/model_slices/runtime_config.py",
        "db/models.py",
        "domain/asr/__init__.py",
        "domain/ownership.py",
    ], readers

    transcription_source = (app_root / "domain/voices/transcription.py").read_text()
    assert transcription_source.count("resolve_asr_model(") == 1

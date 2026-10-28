"""Qwen3-TTS 作为**本机念字引擎**接进引擎层。

这份测试盯的是「接进来了」而不是「模型好不好听」:

① 注册 —— 能力表和 `/api/tts/engines` 那份目录里都有它,id 走 `builtin:*` 约定;
② 下载 —— 复用引擎权重那套(清单、实测体积、进度、失败原因),不另起一个下载器;
③ 合成 —— 文本进、音频出;失败要带着能读懂的原因,不许写一段正弦音冒充结果;
④ 版本钉住 —— 配置里有确切的 release / commit / sha256,不写会漂的 “latest”;
⑤ 不依赖真机 —— 推理、下载都打桩;
⑥ MPS —— CUDA 优先不变,MPS 次之且必须 float32;MPS 真报错时回落 CPU 并说清代价
   (2026-10-20 真机验证见 docs/validation/2026-10-20-qwen-tts-mps.md)。

版本依据(报告里也写了):Qwen3-TTS 于 2026-01-22 开源,权重 Apache-2.0,
`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` 的 HF commit `0c0e3051…`,
ModelScope revision `ae999bce…`;两个大文件的 sha256 在 `qwen_models.MODEL.files` 里。
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from app.ai.runtime import qwen_models, tts_models
from app.ai.runtime import download_state
from app.ai.runtime import errors
from app.ai.runtime.workers import tts as tts_worker
from app.domain.voices import engine_catalog, voices
from app.domain.voices import errors as voices_errors
from app.domain.voices.speech import CAPABILITY, LOCAL_SPEECH_ENGINES, QWEN_ENGINE


def _wave_bytes(seconds: float = 0.1, sr: int = 24000) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(b"\x00\x00" * int(sr * seconds))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ① 注册:能力表 + 引擎下拉
# ---------------------------------------------------------------------------


def test_engine_id_follows_the_builtin_convention() -> None:
    assert QWEN_ENGINE == "builtin:qwentts"
    #: 能力表里的 id → 运行时目录里的引擎名;两边必须是同一个,否则「选中了」和「跑哪个」会各说各的。
    assert LOCAL_SPEECH_ENGINES[QWEN_ENGINE] == qwen_models.ENGINE_ID
    assert qwen_models.ENGINE_ID in tts_models._BY_ID


def test_it_is_registered_in_the_capability_table() -> None:
    """能力表是「点名一个引擎」的唯一判据 —— 不在表里,require_engine 会当成不认识。"""
    assert any(one.id == QWEN_ENGINE for one in CAPABILITY.builtins)


def test_it_appears_in_the_engine_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎下拉与能力表同源(describe_engines)。缺权重时**照列**,并说清下一步。"""
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine_id: (False, True))
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: False)

    rows = {row["id"]: row for row in engine_catalog.describe_engines(None)}
    row = rows[QWEN_ENGINE]

    assert row["label"] == "ttsProvider_qwen"
    assert row["needs_key"] is False
    # Qwen3-TTS 的 API 没有语速参数:摆一个拨不动的旋钮比不摆更糟。
    assert row["supports_speed"] is False
    # 9 个预置音色,不需要用户手打 id。
    assert row["needs_voice_id"] is False
    assert row["voices"] == [speaker.id for speaker in qwen_models.MODEL.speakers]
    assert row["ready"] is False
    assert row["note"] == "ttsProviderNote_qwenMissing"


def test_the_api_lists_it_and_its_voices() -> None:
    """界面下拉读的就是这两个接口 —— 目录里有、出口翻得出名字,才算真的"出现在下拉里"。"""
    from tests.util import fresh_client

    client = fresh_client()
    engines = {row["id"]: row for row in client.get("/api/tts/engines", headers={"Accept-Language": "en"}).json()}
    assert QWEN_ENGINE in engines
    assert engines[QWEN_ENGINE]["label"] == "Qwen3-TTS (local)"
    assert not engines[QWEN_ENGINE]["label"].startswith("ttsProvider_")

    voices = client.get(f"/api/tts/voices?engine={QWEN_ENGINE}").json()
    assert [row["id"] for row in voices] == [speaker.id for speaker in qwen_models.MODEL.speakers]
    assert {row["source"] for row in voices} == {"preset"}, "本机引擎预置的,不是某家内置的"
    assert [row["label"] for row in voices] == [speaker.label for speaker in qwen_models.MODEL.speakers]


def test_it_is_ready_only_when_weights_and_runtime_are_both_there(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine_id: (True, True))
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    row = next(one for one in engine_catalog.describe_engines(None) if one["id"] == QWEN_ENGINE)
    assert row["ready"] is True
    assert row["note"] == "ttsProviderNote_qwenReady"

    # 解释器有、权重没下 —— 这不是「就绪」,而下拉里那句要说清去哪下。
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: False)
    row = next(one for one in engine_catalog.describe_engines(None) if one["id"] == QWEN_ENGINE)
    assert row["ready"] is False


def test_its_voices_are_the_nine_official_speakers() -> None:
    """界面上的音色必须就是模型真有的那几个 —— 编一个出来,合成时才失败。"""
    rows = engine_catalog._engine_voices(None, QWEN_ENGINE, user_id=None)  # noqa: SLF001 — 目录的内部出口,测试照它
    assert [one.id for one in rows] == [speaker.id for speaker in qwen_models.MODEL.speakers]
    # 名字是给人看的,不是一串 lower_snake_case。
    assert all(one.label and one.label != one.id for one in rows)
    # 语言是模型卡上每个音色的母语,照抄,不从名字里猜。
    assert [one.languages for one in rows] == [(speaker.native_language,) for speaker in qwen_models.MODEL.speakers]


# ---------------------------------------------------------------------------
# ② 下载:复用引擎权重那套
# ---------------------------------------------------------------------------


_HF_FILES = {
    ".gitattributes": 1519,
    "README.md": 57846,
    "config.json": 4908,
    "generation_config.json": 245,
    "merges.txt": 1671839,
    "model.safetensors": 3833402552,
    "preprocessor_config.json": 127,
    "speech_tokenizer/config.json": 2336,
    "speech_tokenizer/configuration.json": 76,
    "speech_tokenizer/model.safetensors": 682293092,
    "speech_tokenizer/preprocessor_config.json": 234,
    "tokenizer_config.json": 7344,
    "vocab.json": 2776833,
}


def test_the_size_comes_from_the_source_and_matches_the_pinned_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """体积问源要,不和目录里写死的估算各说各的(那条路在 F5 上走过一次)。"""
    monkeypatch.setattr(tts_models.remote_size, "files_for", lambda source, repo: dict(_HF_FILES))
    total, estimated = tts_models.measured_total(tts_models._BY_ID[qwen_models.ENGINE_ID], "hf", blocking=True)

    assert estimated is False
    assert total == qwen_models.MODEL.total_bytes == 4_520_218_951


def test_the_download_asks_for_the_pinned_repository() -> None:
    """下载要取的东西由目录声明;它和 `fetch_qwen_weights` 是同一件事的两面。"""
    assert tts_models.download_parts(qwen_models.ENGINE_ID, "hf") == (
        ("hf", qwen_models.MODEL.repo, ()),
    )
    assert tts_models.download_parts(qwen_models.ENGINE_ID, "modelscope") == (
        ("modelscope", qwen_models.MODEL.modelscope_repo, ()),
    )
    assert "modelscope" in tts_models.sources_for(qwen_models.ENGINE_ID)


def test_download_progress_is_the_shared_shape() -> None:
    """进度条、速度、ETA、失败原因都是同一条下载路的形状 —— 新引擎不另造一份。"""
    tts_models._store.set(
        qwen_models.ENGINE_ID,
        download_state.DownloadProgress(status="downloading", downloaded=1024, total=4096, message="dlMsg_preparing"),
    )
    try:
        row = tts_models.get_status(qwen_models.ENGINE_ID)
    finally:
        tts_models._store.clear(qwen_models.ENGINE_ID)

    assert row["status"] == "downloading"
    assert row["downloaded_bytes"] == 1024
    assert row["total_bytes"] == 4096
    assert row["message"] == "dlMsg_preparing"


def test_a_killed_download_still_says_what_happened(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """被杀的下载不能凭空变回「下载这个模型」 —— 盘上的半截就是证据。"""
    monkeypatch.setattr(qwen_models, "root", lambda: tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"half a checkpoint")
    tts_models._store.clear(qwen_models.ENGINE_ID)
    try:
        row = tts_models.get_status(qwen_models.ENGINE_ID)
    finally:
        tts_models._store.clear(qwen_models.ENGINE_ID)

    assert row["status"] == "failed"
    assert row["message"] == "runtimeErr_qwenDownloadInterrupted"
    assert row["downloaded_bytes"] > 0


def test_a_broken_runtime_leaves_a_reason_not_a_silent_missing_button(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败要落在状态上并带着原因 —— 此前「加载一会儿就没了」正是没有原因的那一版。"""

    def boom(engine_id: str) -> None:
        raise errors.RuntimeSetupError("runtimeErr_noBasePythonTts")

    monkeypatch.setattr(tts_models, "ensure_engine_runtime", boom)
    tts_models._store.clear(qwen_models.ENGINE_ID)
    try:
        tts_models._run_download(qwen_models.ENGINE_ID)
        row = tts_models.get_status(qwen_models.ENGINE_ID)
    finally:
        tts_models._store.clear(qwen_models.ENGINE_ID)

    assert row["status"] == "failed"
    assert row["message"] == "runtimeErr_noBasePythonTts", row


def test_the_worker_downloads_the_exact_revision(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """下载源上取哪一版由配置钉住 —— worker 不许自己去取 latest。"""
    calls: dict[str, dict] = {}

    def fake_snapshot(**kwargs):
        calls.update(kwargs)
        return str(tmp_path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=fake_snapshot))
    monkeypatch.setenv("MOSAEL_QWEN_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "hf")
    monkeypatch.setenv("MOSAEL_QWEN_REPO", qwen_models.MODEL.repo)
    monkeypatch.setenv("MOSAEL_QWEN_REVISION", qwen_models.MODEL.hf_revision)
    monkeypatch.setenv("MOSAEL_QWEN_MODELSCOPE_REPO", qwen_models.MODEL.modelscope_repo)
    monkeypatch.setenv("MOSAEL_QWEN_MODELSCOPE_REVISION", qwen_models.MODEL.modelscope_revision)

    tts_worker.fetch_qwen_weights()

    assert calls["repo_id"] == qwen_models.MODEL.repo
    assert calls["revision"] == qwen_models.MODEL.hf_revision
    assert calls["local_dir"] == str(tmp_path)
    assert "latest" not in str(calls["revision"]).lower()


def test_the_worker_refuses_to_download_without_a_pinned_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("MOSAEL_QWEN_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "hf")
    monkeypatch.delenv("MOSAEL_QWEN_REVISION", raising=False)

    with pytest.raises(tts_worker.KeyedWorkerError) as caught:
        tts_worker.fetch_qwen_weights()

    assert caught.value.key == "runtimeErr_qwenNoRevision"


# ---------------------------------------------------------------------------
# ③ 合成:文本进、音频出;失败说原因
# ---------------------------------------------------------------------------


def _local_synthesis(monkeypatch: pytest.MonkeyPatch, tmp_path, pool) -> dict:
    sent: dict = {}

    def request(engine, python, payload, **kwargs):
        sent.update(payload)
        return pool(engine, python, payload, **kwargs)

    monkeypatch.setattr(voices.tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(voices.tts_models, "is_installed", lambda engine_id: True)
    monkeypatch.setattr(voices.tts_daemon, "pool", lambda: types.SimpleNamespace(request=request))
    out = voices.speak_to_file(
        None,
        text="你好,这是一段本机合成的语音。",
        engine=QWEN_ENGINE,
        engine_voice="vivian",
        speed=1.0,
        workspace_id="w1",
        user_id=None,
        out_dir=tmp_path,
        source_type="test",
        source_id="t1",
    )
    assert out.is_file() and out.stat().st_size > 0
    return sent


def test_synthesis_sends_text_to_the_qwen_worker(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def write(engine, python, payload, **_kwargs):
        assert engine == qwen_models.ENGINE_ID
        assert python == "/usr/bin/python3"
        from pathlib import Path

        Path(payload["output_path"]).write_bytes(_wave_bytes())
        return {"engine": qwen_models.ENGINE_ID, "output": payload["output_path"]}

    sent = _local_synthesis(monkeypatch, tmp_path, write)

    assert sent["action"] == "synthesize"
    assert sent["engine"] == qwen_models.ENGINE_ID
    assert sent["text"] == "你好,这是一段本机合成的语音。"
    assert sent["speaker"] == "vivian"
    # 中文走 Auto(模型支持的语言由一个字段描述,而不是在这里猜)。
    assert sent["language"] == "Auto"


def test_japanese_text_asks_for_the_japanese_language(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Qwen3-TTS 支持日文 —— 有硬证据时把语言说清楚,不拿 Auto 赌。"""
    assert qwen_models.language_for("ja") == "Japanese"
    assert qwen_models.language_for("ko") == "Korean"
    assert qwen_models.language_for("ru") == "Russian"
    # 中文/英文以及拉丁字母那几门没有硬证据,交给模型的 Auto。
    assert qwen_models.language_for("zh") == "Auto"
    assert qwen_models.language_for("") == "Auto"

    def write(engine, python, payload, **_kwargs):
        from pathlib import Path

        Path(payload["output_path"]).write_bytes(_wave_bytes())
        return {"engine": engine, "output": payload["output_path"]}

    sent: dict = {}

    def request(engine, python, payload, **kwargs):
        sent.update(payload)
        return write(engine, python, payload, **kwargs)

    monkeypatch.setattr(voices.tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(voices.tts_models, "is_installed", lambda engine_id: True)
    monkeypatch.setattr(voices.tts_daemon, "pool", lambda: types.SimpleNamespace(request=request))
    voices.speak_to_file(
        None, text="こんにちは、今日はいい天気ですね", engine=QWEN_ENGINE, engine_voice="vivian",
        speed=1.0, workspace_id="w1", user_id=None, out_dir=tmp_path,
        source_type="test", source_id="t1",
    )
    assert sent["language"] == "Japanese"


def test_a_worker_failure_keeps_its_reason(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """失败给明确原因(本地引擎的 key 由 worker 带回来),不写占位音。"""

    def boom(engine, python, payload, **_kwargs):
        raise errors.RuntimeSetupError("runtimeErr_qwenModelMissing")

    monkeypatch.setattr(voices.tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(voices.tts_models, "is_installed", lambda engine_id: True)
    monkeypatch.setattr(
        voices.tts_daemon, "pool",
        lambda: types.SimpleNamespace(request=boom),
    )

    with pytest.raises(errors.RuntimeSetupError) as caught:
        voices.speak_to_file(
            None,
            text="你好",
            engine=QWEN_ENGINE,
            engine_voice="vivian",
            speed=1.0,
            workspace_id="w1",
            user_id=None,
            out_dir=tmp_path,
            source_type="test",
            source_id="t1",
        )

    assert caught.value.key == "runtimeErr_qwenModelMissing"


def test_the_worker_runs_the_model_text_in_audio_out(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """推理本身打桩:不进 torch、不读 4.5 GB 权重,只看「文本有没有交进去、wav 有没有出来」。"""
    model_dir = tmp_path / "qwen"
    (model_dir / "speech_tokenizer").mkdir(parents=True)
    (model_dir / "model.safetensors").write_bytes(b"weights")
    (model_dir / "speech_tokenizer" / "model.safetensors").write_bytes(b"tokenizer")
    monkeypatch.setenv("MOSAEL_QWEN_MODEL_DIR", str(model_dir))

    seen: dict = {}
    fake = types.ModuleType("qwen_tts")

    class _Model:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            seen["path"] = path
            seen["kwargs"] = kwargs
            return cls()

        def generate_custom_voice(self, **kwargs):
            seen.update(kwargs)
            return [np.zeros(2400, dtype=np.float32)], 24000

    fake.Qwen3TTSModel = _Model
    monkeypatch.setitem(sys.modules, "qwen_tts", fake)
    tts_worker._LOADED.clear()

    out = tmp_path / "speech.wav"
    try:
        tts_worker.run_qwen({"text": "你好", "speaker": "vivian", "language": "Auto"}, str(out))
    finally:
        tts_worker._LOADED.clear()  # 别把假模型留给同进程里的下一条用例

    assert seen["path"] == str(model_dir)
    assert seen["text"] == "你好"
    assert seen["speaker"] == "vivian"
    assert seen["language"] == "Auto"
    assert out.read_bytes().startswith(b"RIFF")


def test_synthesize_dispatches_qwen_and_not_the_f5_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """worker 的默认引擎是 f5-tts;qwen-tts 必须在分派处点名,否则请求会落到错的引擎上。"""
    called: dict = {}

    def fake_run_qwen(request, output_path):
        called.update(request)
        return "qwen-tts"

    monkeypatch.setattr(tts_worker, "run_qwen", fake_run_qwen)
    assert tts_worker.synthesize({"engine": "qwen-tts", "text": "你好"}, str(tmp_path / "out.wav")) == "qwen-tts"
    assert called["text"] == "你好"


def test_the_worker_says_what_is_missing_instead_of_inventing_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("MOSAEL_QWEN_MODEL_DIR", str(tmp_path / "missing"))

    with pytest.raises(tts_worker.KeyedWorkerError) as caught:
        tts_worker.run_qwen({"text": "你好", "speaker": "vivian"}, str(tmp_path / "out.wav"))

    assert caught.value.key == "runtimeErr_qwenModelMissing"
    assert not (tmp_path / "out.wav").exists()


# ---------------------------------------------------------------------------
# ④ 版本钉住:确切 release + commit + sha256,不是 latest
# ---------------------------------------------------------------------------


def test_the_model_version_is_pinned_with_hashes() -> None:
    model = qwen_models.MODEL

    assert model.id == "qwen3-tts-12hz-1.7b-customvoice"
    assert model.repo == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    assert model.release_date == "2026-01-22"
    assert model.license == "Apache-2.0"
    # 中文是必须支持的;官方 10 种语言都要如实写在目录里。
    assert "zh" in model.languages and "en" in model.languages
    assert set(model.languages) == {"zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"}

    assert re.fullmatch(r"[0-9a-f]{40}", model.hf_revision)
    assert re.fullmatch(r"[0-9a-f]{40}", model.modelscope_revision)
    assert "latest" not in (model.id + model.hf_revision + model.modelscope_revision).lower()

    checkpoint = model.files["model.safetensors"]
    assert checkpoint.sha256 == "38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137"
    assert checkpoint.size == 3_833_402_552
    codec = model.files["speech_tokenizer/model.safetensors"]
    assert codec.sha256 == "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
    assert codec.size == 682_293_092


def test_installed_requires_both_pinned_weight_files(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(qwen_models, "root", lambda: tmp_path)
    assert qwen_models.installed() is False

    (tmp_path / "model.safetensors").write_bytes(b"x")
    assert qwen_models.installed() is False, "只有主模型、没有声码器,合成照样加载不起来"

    (tmp_path / "speech_tokenizer").mkdir()
    (tmp_path / "speech_tokenizer" / "model.safetensors").write_bytes(b"x")
    assert qwen_models.installed() is False, "配置都没下,加载时照样找不到模型结构"

    (tmp_path / "config.json").write_bytes(b"{}")
    assert qwen_models.installed() is True


# ---------------------------------------------------------------------------
# ⑤ 语言与音色:如实
# ---------------------------------------------------------------------------


def test_arabic_is_refused_before_a_job_is_created() -> None:
    """Qwen3-TTS 的 10 种语言里没有阿拉伯文 —— 装作能念只会交出一段废音。"""
    with pytest.raises(voices_errors.VoiceError) as caught:
        voices._refuse_if_unspeakable("مرحبا كيف حالك", QWEN_ENGINE, "vivian", "")  # noqa: SLF001

    assert caught.value.key == "voiceErr_qwenUnsupportedLanguage"


def test_japanese_is_allowed_for_qwen() -> None:
    """日文是它支持的语言之一 —— 不要照抄克隆引擎那条「日文要下权重」的判据。"""
    voices._refuse_if_unspeakable("こんにちは、今日はいい天気ですね", QWEN_ENGINE, "vivian", "")  # noqa: SLF001


# ---------------------------------------------------------------------------
# ⑥ Apple MPS:M4 Max / macOS 27 / torch 2.14.1 / qwen-tts 0.1.1 上真机验过
#    (docs/validation/2026-10-20-qwen-tts-mps.md)。这里只打桩设备探测,不 import 真 torch。
# ---------------------------------------------------------------------------


def _fake_torch(monkeypatch: pytest.MonkeyPatch, *, cuda: bool, mps: bool) -> types.SimpleNamespace:
    """把整个 torch 换成一个只回答设备探测的假货(后端测试环境里本来就没有 torch)。"""
    torch = types.SimpleNamespace(
        float32="torch.float32",
        bfloat16="torch.bfloat16",
        cuda=types.SimpleNamespace(is_available=lambda: cuda),
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


@pytest.fixture
def qwen_state():
    """权重缓存是进程级的:每条用例前后清干净,别让上一条加载的模型留给下一条。"""
    tts_worker._LOADED.clear()
    yield
    tts_worker._LOADED.clear()


def _fake_qwen(monkeypatch: pytest.MonkeyPatch, *, load_fails_on: frozenset[str] = frozenset(),
               generate_fails_on: frozenset[str] = frozenset()) -> dict:
    """假的 qwen_tts:记录每次加载用的设备、每次生成跑在哪个设备上,并按需在指定设备上抛错。"""
    seen: dict = {"loads": [], "generations": []}
    module = types.ModuleType("qwen_tts")

    class _Model:
        def __init__(self, device_map: str) -> None:
            self.device_map = device_map

        @classmethod
        def from_pretrained(cls, path: str, **kwargs: object) -> "_Model":
            seen["loads"].append(kwargs)
            if kwargs["device_map"] in load_fails_on:
                raise RuntimeError(f"{kwargs['device_map']} backend: op not implemented")
            return cls(str(kwargs["device_map"]))

        def generate_custom_voice(self, **_kwargs: object) -> tuple[list, int]:
            seen["generations"].append(self.device_map)
            if self.device_map in generate_fails_on:
                raise RuntimeError(f"{self.device_map} backend: op not implemented")
            return [np.zeros(2400, dtype=np.float32)], 24000

    module.Qwen3TTSModel = _Model
    monkeypatch.setitem(sys.modules, "qwen_tts", module)
    return seen


def _installed_qwen_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    """摆一份「已安装」的权重目录(只建两个必需文件,不真的放内容)。"""
    model_dir = tmp_path / "qwen"
    (model_dir / "speech_tokenizer").mkdir(parents=True)
    (model_dir / "model.safetensors").write_bytes(b"weights")
    (model_dir / "speech_tokenizer" / "model.safetensors").write_bytes(b"tokenizer")
    monkeypatch.setenv("MOSAEL_QWEN_MODEL_DIR", str(model_dir))
    return model_dir


def test_apple_silicon_uses_mps_in_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    """MPS 可用就走 MPS;dtype **必须 float32**(bf16 在 MPS 上又慢又不一致)。"""
    torch = _fake_torch(monkeypatch, cuda=False, mps=True)
    assert tts_worker._qwen_device() == ("mps", torch.float32)


def test_cuda_still_wins_over_mps(monkeypatch: pytest.MonkeyPatch) -> None:
    """CUDA 优先不变:两种都可用时仍然先 CUDA —— 接 MPS 不许动这一支。"""
    torch = _fake_torch(monkeypatch, cuda=True, mps=True)
    assert tts_worker._qwen_device() == ("cuda:0", torch.bfloat16)


def test_without_mps_qwen_stays_on_cpu_in_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    """纯 CPU 的 Mac(没有 MPS):行为不变,仍然是 CPU + float32。"""
    torch = _fake_torch(monkeypatch, cuda=False, mps=False)
    assert tts_worker._qwen_device() == ("cpu", torch.float32)


def test_the_engine_venv_pins_the_torch_that_was_verified() -> None:
    """torch 也钉住:验过的是 2.14.1,以后升级 MPS 行为可能变(验证文档 §8.2)。"""
    assert "torch==2.14.1" in qwen_models.PIP_REQUIREMENTS
    assert "qwen-tts==0.1.1" in qwen_models.PIP_REQUIREMENTS


def test_a_broken_mps_load_falls_back_to_cpu_and_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str], qwen_state
) -> None:
    """MPS 上真报错(未来 torch / 未实现的算子)时:回落 CPU,并把原因和重载代价写清楚。"""
    _installed_qwen_dir(monkeypatch, tmp_path)
    _fake_torch(monkeypatch, cuda=False, mps=True)
    seen = _fake_qwen(monkeypatch, load_fails_on=frozenset({"mps"}))
    out = tmp_path / "speech.wav"

    assert tts_worker.run_qwen({"text": "你好", "speaker": "vivian"}, str(out)) == "qwen-tts"

    assert [load["device_map"] for load in seen["loads"]] == ["mps", "cpu"]
    assert seen["generations"] == ["cpu"]
    assert out.read_bytes().startswith(b"RIFF")
    err = capsys.readouterr().err
    assert "MPS" in err and "CPU" in err, "回落要在日志里说清,不能静默换设备"
    assert "4.5 GB" in err, "重载一遍权重的代价也要说清"


def test_a_broken_mps_generation_reloads_on_cpu_and_says_the_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str], qwen_state
) -> None:
    """加载成功、生成才炸(未实现的算子):丢掉 MPS 实例,换 CPU 重载并重新生成一遍。"""
    _installed_qwen_dir(monkeypatch, tmp_path)
    _fake_torch(monkeypatch, cuda=False, mps=True)
    seen = _fake_qwen(monkeypatch, generate_fails_on=frozenset({"mps"}))
    out = tmp_path / "speech.wav"

    assert tts_worker.run_qwen({"text": "你好", "speaker": "vivian"}, str(out)) == "qwen-tts"

    assert [load["device_map"] for load in seen["loads"]] == ["mps", "cpu"]
    assert seen["generations"] == ["mps", "cpu"]
    assert out.read_bytes().startswith(b"RIFF")
    err = capsys.readouterr().err
    assert "MPS" in err and "CPU" in err, "回落要在日志里说清,不能静默换设备"
    assert "4.5 GB" in err, "重载一遍权重的代价也要说清"


def test_after_a_fallback_the_next_synthesis_does_not_try_mps_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path, qwen_state
) -> None:
    """回落一次就够:缓存里放的是 CPU 那份,后面的请求不能再碰 MPS(碰一次就要重读 4.5 GB)。"""
    _installed_qwen_dir(monkeypatch, tmp_path)
    _fake_torch(monkeypatch, cuda=False, mps=True)
    seen = _fake_qwen(monkeypatch, load_fails_on=frozenset({"mps"}))
    out = tmp_path / "speech.wav"

    assert tts_worker.run_qwen({"text": "你好", "speaker": "vivian"}, str(out)) == "qwen-tts"
    assert tts_worker.run_qwen({"text": "再念一次", "speaker": "vivian"}, str(out)) == "qwen-tts"

    assert [load["device_map"] for load in seen["loads"]] == ["mps", "cpu"]
    assert seen["generations"] == ["cpu", "cpu"]

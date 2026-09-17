"""降噪是一个**能力**(ADR-0017),形状同分离(ADR-0016)。

钉住的是这几条:

1. 内置引擎**真的降了噪、没动说话声** —— 用真 ffmpeg 量,不是断言滤镜字符串长什么样;
2. 噪声底是**量出来的**:写死一个值,要么降不动,要么把人声削掉(实测过前一种);
3. `auto` 不挑会去掉音乐的引擎;人声提取借的是分离的**契约**,跟着分离引擎在不在走;
4. 产出**新素材**:音频进音频出,视频进视频出,原素材不动;
5. 不认得的档位、没准备好的引擎,在排队 / 开卡**之前**就说清楚;
6. 分离和降噪取声音时**不降采样** —— 此前借转写那条路,先砍成 16 kHz 单声道。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai.providers.contracts.denoise import DenoiseError, DenoiseRequest, checked_strength
from app.ai.providers.contracts.separation import VOCALS, SeparationRequest

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _speech_like_with_noise(path: Path, *, noise: float = 0.02, seconds: int = 8) -> None:
    """间断的正弦当"说话"(0.6 秒响、0.4 秒停),叠一层粉噪。停顿里剩下的就是噪声。"""
    _ffmpeg(
        "-f", "lavfi", "-i", f"sine=f=300:d={seconds},volume='if(lt(mod(t,1),0.6),0.3,0)':eval=frame",
        "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a={noise}:r=44100",
        "-filter_complex", "[0][1]amix=inputs=2:normalize=0", "-ar", "44100", "-ac", "2", str(path),
    )


class Test内置引擎真的在降噪:
    @needs_ffmpeg
    @pytest.mark.parametrize("noise", [0.005, 0.02])
    def test_停顿里的噪声压下去__说话段不变(self, tmp_path, noise) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter, measure_levels

        source = tmp_path / "noisy.wav"
        _speech_like_with_noise(source, noise=noise)
        before_floor, before_signal = measure_levels(source)

        by_strength = {}
        for strength in ("light", "medium", "strong"):
            out = FfmpegDenoiseAdapter().denoise(DenoiseRequest(source, strength), tmp_path / f"{strength}.wav")
            by_strength[strength] = measure_levels(out)

        for strength, (_, signal) in by_strength.items():
            assert abs(signal - before_signal) < 1.0, f"{strength} 档把说话声也削了:{before_signal} → {signal}"
        assert by_strength["light"][0] < before_floor - 4
        assert by_strength["medium"][0] < before_floor - 9
        #: 档位是有意义的:越强,停顿里剩得越少。
        assert by_strength["strong"][0] < by_strength["medium"][0] < by_strength["light"][0]

    @needs_ffmpeg
    def test_信噪比低的录音也降得动(self, tmp_path) -> None:
        """最需要降噪的正是这种。nf 的上限起初画在"信号以下 15 dB",结果它被压到噪声底以下,
        三档降得一样少(实测都只有 4 dB)。"""
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter, measure_levels

        source = tmp_path / "loud-noise.wav"
        _speech_like_with_noise(source, noise=0.05)
        before_floor, before_signal = measure_levels(source)
        assert before_signal - before_floor < 12, "前提:这是一段信噪比很低的录音"
        floor, signal = measure_levels(FfmpegDenoiseAdapter().denoise(DenoiseRequest(source, "medium"), tmp_path / "out.wav"))
        assert floor < before_floor - 7
        assert abs(signal - before_signal) < 1.0

    @needs_ffmpeg
    def test_没有停顿的连续音频不被当噪声削掉(self, tmp_path) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter, measure_levels

        source = tmp_path / "music.wav"
        _ffmpeg(
            "-f", "lavfi", "-i",
            "aevalsrc='0.1*sin(2*PI*220*t)+0.08*sin(2*PI*330*t)*(1+0.5*sin(2*PI*0.5*t))+0.05*sin(2*PI*660*t)':d=6:s=44100",
            "-ac", "2", str(source),
        )
        _, before = measure_levels(source)
        _, after = measure_levels(FfmpegDenoiseAdapter().denoise(DenoiseRequest(source, "strong"), tmp_path / "out.wav"))
        assert abs(after - before) < 0.5

    @needs_ffmpeg
    def test_噪声底是量出来的(self, tmp_path) -> None:
        """两段只差噪声大小的音频,量出来的噪声底要差出同样的量级(a 差 4 倍 ≈ 12 dB)。"""
        from app.ai.providers.adapters.local.ffmpeg_denoise import measure_levels

        quiet, loud = tmp_path / "quiet.wav", tmp_path / "loud.wav"
        _speech_like_with_noise(quiet, noise=0.005)
        _speech_like_with_noise(loud, noise=0.02)
        assert 9 < measure_levels(loud)[0] - measure_levels(quiet)[0] < 15

    @needs_ffmpeg
    def test_整段静音不炸(self, tmp_path) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter, measure_levels

        silent = tmp_path / "silent.wav"
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "2", str(silent))
        assert measure_levels(silent) is None
        assert FfmpegDenoiseAdapter().denoise(DenoiseRequest(silent), tmp_path / "out.wav").is_file()


class Test滤镜参数跟着测量走:
    def test_nf_跟着噪声底(self) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import filter_for

        assert "nf=-58.0" in filter_for("light", (-60.0, -20.0))
        assert "nf=-38.0" in filter_for("light", (-40.0, -10.0))

    def test_没有停顿的音频__nf_不抬到信号上(self) -> None:
        """整段音乐的第 10 百分位就是音乐本身;不设这道线,音乐会被当噪声削掉。"""
        from app.ai.providers.adapters.local.ffmpeg_denoise import filter_for

        chain = filter_for("strong", (-30.0, -28.0))
        assert "nf=-34.0" in chain, chain

    def test_nf_在_afftdn_接受的范围里(self) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import filter_for

        assert "nf=-80.0" in filter_for("light", (-95.0, -60.0))
        assert "nf=-20.0" in filter_for("strong", (-10.0, 20.0))

    def test_档位越强削得越多(self) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import filter_for

        reductions = [float(re.search(r"nr=([\d.]+)", filter_for(s, (-60.0, -20.0))).group(1)) for s in ("light", "medium", "strong")]
        assert reductions == sorted(reductions) and len(set(reductions)) == 3


class Test档位:
    def test_空就是默认档(self) -> None:
        assert checked_strength("") == "medium"

    def test_认不出的当场拒__不悄悄按默认跑(self) -> None:
        with pytest.raises(DenoiseError, match="strnog"):
            checked_strength("strnog")
        with pytest.raises(DenoiseError):
            DenoiseRequest(Path("x.wav"), "loud")


class _FakeSeparation:
    engine_id = "fake-sep"

    def __init__(self) -> None:
        self.asked: list[tuple[str, ...]] = []

    def runtime_ready(self) -> bool:
        return True

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        self.asked.append(request.stems)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "vocals.wav"
        path.write_bytes(b"RIFF-vocals")
        return {VOCALS: path}


class Test引擎的挑法:
    def test_auto_是内置的那个(self) -> None:
        from app.ai.providers.registry import get_denoise_adapter

        assert get_denoise_adapter().engine_id == "ffmpeg"
        assert get_denoise_adapter("auto").engine_id == "ffmpeg"

    def test_auto_不挑会去掉音乐的引擎__哪怕它排在前面(self, monkeypatch) -> None:
        from app.ai.providers import registry
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter
        from app.ai.providers.adapters.local.voice_isolation_denoise import VoiceIsolationDenoiseAdapter

        isolation = VoiceIsolationDenoiseAdapter(separation=lambda engine: _FakeSeparation())
        builtin = FfmpegDenoiseAdapter()
        monkeypatch.setattr(registry, "DENOISE_ADAPTERS", {"voice-isolation": isolation, "ffmpeg": builtin})
        assert registry.get_denoise_adapter() is builtin
        #: 点名仍然拿得到。
        assert registry.get_denoise_adapter("voice-isolation") is isolation

    def test_重复的引擎装配时就失败(self) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import FfmpegDenoiseAdapter
        from app.ai.providers.registry import _index_denoise_adapters

        with pytest.raises(RuntimeError, match="重复"):
            _index_denoise_adapters((FfmpegDenoiseAdapter(), FfmpegDenoiseAdapter()))

    def test_节点上的选项就是注册表里那几个(self) -> None:
        from app.ai.providers.contracts.denoise import STRENGTHS
        from app.ai.providers.registry import DENOISE_ADAPTERS
        from app.domain.workflows import NODE_TYPES

        config = NODE_TYPES["denoise_audio"]["config"]
        assert config["engine"]["options"] == ["auto", *DENOISE_ADAPTERS]
        assert config["strength"]["options"] == list(STRENGTHS)


class Test人声提取借的是分离的契约:
    def test_跟着分离引擎在不在走(self) -> None:
        from app.ai.providers.adapters.local.voice_isolation_denoise import VoiceIsolationDenoiseAdapter

        assert VoiceIsolationDenoiseAdapter(separation=lambda engine: None).runtime_ready() is False
        assert VoiceIsolationDenoiseAdapter(separation=lambda engine: _FakeSeparation()).runtime_ready() is True

    def test_只要人声那一条__产物就是它(self, tmp_path) -> None:
        from app.ai.providers.adapters.local.voice_isolation_denoise import VoiceIsolationDenoiseAdapter

        separation = _FakeSeparation()
        out = VoiceIsolationDenoiseAdapter(separation=lambda engine: separation).denoise(
            DenoiseRequest(tmp_path / "in.wav"), tmp_path / "out.wav"
        )
        assert separation.asked == [(VOCALS,)], "只该要人声 —— 多要一条就是多算一条"
        assert out.read_bytes() == b"RIFF-vocals"

    def test_没有分离引擎时说清楚去哪装(self, tmp_path) -> None:
        from app.ai.providers.adapters.local.voice_isolation_denoise import VoiceIsolationDenoiseAdapter

        with pytest.raises(DenoiseError, match="人声分离"):
            VoiceIsolationDenoiseAdapter(separation=lambda engine: None).denoise(
                DenoiseRequest(tmp_path / "in.wav"), tmp_path / "out.wav"
            )

    def test_契约不认识任何一个引擎(self) -> None:
        text = Path("app/ai/providers/contracts/denoise.py").read_text(encoding="utf-8").lower()
        for name in ("ffmpeg", "afftdn", "demucs", "deepfilter", "rnnoise"):
            assert name not in text, f"契约里出现了引擎名 {name}"


class Test排队和开卡之前就判:
    def test_只有音频和视频能降噪(self) -> None:
        from app.db.models import Asset
        from app.domain.denoise import start_denoise_job

        with pytest.raises(DenoiseError, match="只有音频或视频"):
            start_denoise_job(None, asset=Asset(workspace_id="w", kind="image", name="x", file_key="k"), created_by=None)

    def test_档位写错不排队(self) -> None:
        from app.db.models import Asset
        from app.domain.denoise import start_denoise_job

        with pytest.raises(DenoiseError, match="档位"):
            start_denoise_job(
                None, asset=Asset(workspace_id="w", kind="audio", name="x", file_key="k"), created_by=None, strength="max"
            )

    def test_引擎没准备好不排队__说清去哪准备(self, monkeypatch) -> None:
        from app.ai.providers.adapters.local.voice_isolation_denoise import VoiceIsolationDenoiseAdapter
        from app.db.models import Asset
        from app.domain import denoise

        cold = VoiceIsolationDenoiseAdapter(separation=lambda engine: None)
        monkeypatch.setattr(denoise, "get_denoise_adapter", lambda engine="": cold if engine else None)
        with pytest.raises(DenoiseError, match="人声分离"):
            denoise.start_denoise_job(
                None, asset=Asset(workspace_id="w", kind="audio", name="x", file_key="k"), created_by=None, engine="voice-isolation"
            )

    def test_确认卡上说得出人声提取会去掉音乐(self) -> None:
        from app.domain.agent.confirmations import _summarize

        assert "音乐" in _summarize("denoise_audio", {"resolved_engine": "voice-isolation"})
        assert "强力" in _summarize("denoise_audio", {"resolved_engine": "ffmpeg", "strength": "strong"})


@needs_ffmpeg
class Test产出新素材:
    def _asset(self, db, workspace_id: str, kind: str, name: str):
        from app.db.models import Asset

        asset = Asset(workspace_id=workspace_id, kind=kind, name=name, file_key="k")
        db.add(asset)
        db.commit()
        return asset

    def test_音频进音频出__原素材不动(self, monkeypatch, tmp_path) -> None:
        from app.core.db import SessionLocal
        from app.domain import denoise
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()
        source = tmp_path / "talk.wav"
        _speech_like_with_noise(source, seconds=3)
        before = source.read_bytes()
        monkeypatch.setattr(denoise, "_source_path", lambda one: source)
        with SessionLocal() as db:
            asset = self._asset(db, workspace["id"], "audio", "访谈")
            made, engine = denoise.denoise_asset(db, asset, strength="strong")
            assert engine == "ffmpeg"
            assert made.id != asset.id and made.kind == "audio"
            assert "访谈" in made.name and "降噪" in made.name
            assert made.media_info["derived_from_asset_id"] == asset.id
            assert made.media_info["denoise_strength"] == "strong"
            db.refresh(asset)
            assert asset.file_key == "k"
        assert source.read_bytes() == before, "原文件一个字节都不该动"

    def test_视频进视频出__画面原样拷贝(self, monkeypatch, tmp_path) -> None:
        """用户对一段视频点降噪,要的是一段干净的视频,不是一段要自己再合回去的音频。"""
        from app.core.db import SessionLocal
        from app.domain import denoise
        from app.media.paths import resolve_key
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()
        noisy = tmp_path / "noisy.wav"
        _speech_like_with_noise(noisy, seconds=2)
        video = tmp_path / "clip.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2", "-i", str(noisy),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
        )
        monkeypatch.setattr(denoise, "_source_path", lambda one: video)
        with SessionLocal() as db:
            asset = self._asset(db, workspace["id"], "video", "片段")
            made, _ = denoise.denoise_asset(db, asset)
            assert made.kind == "video"
            produced = resolve_key(made.file_key)

        streams = json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(produced)],
                capture_output=True, text=True, check=True,
            ).stdout
        )["streams"]
        kinds = {one["codec_type"]: one for one in streams}
        assert set(kinds) == {"video", "audio"}
        assert kinds["video"]["codec_name"] == "h264" and kinds["video"]["width"] == 160

    def test_不能降噪的素材在领域层就拒(self, tmp_path) -> None:
        from app.db.models import Asset
        from app.domain.denoise import denoise_asset

        with pytest.raises(DenoiseError, match="只有音频或视频"):
            denoise_asset(None, Asset(workspace_id="w", kind="image", name="x", file_key="k"))


@needs_ffmpeg
class Test取声音不降采样:
    def test_保留原采样率和声道(self, tmp_path) -> None:
        from app.media.audio_io import as_audio

        video = tmp_path / "clip.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1",
            "-f", "lavfi", "-i", "sine=f=440:d=1:sample_rate=48000",
            "-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
        )
        audio = as_audio(video, tmp_path)
        stream = json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(audio)],
                capture_output=True, text=True, check=True,
            ).stdout
        )["streams"][0]
        assert stream["sample_rate"] == "48000" and stream["channels"] == 2

    def test_分离也走这条(self) -> None:
        text = Path("app/domain/separation.py").read_text(encoding="utf-8")
        assert "as_audio" in text and "_extract_audio" not in text


@needs_ffmpeg
class Test工作流节点和确认卡:
    def test_节点产出新素材__只动本工作区的素材(self, monkeypatch, tmp_path) -> None:
        from app.core.db import SessionLocal
        from app.db.models import Asset, Workflow
        from app.domain import denoise
        from app.domain.workflows.executors.subjobs import denoise_audio_node
        from app.domain.workflows import WorkflowDomainError
        from tests.util import fresh_client

        client = fresh_client()
        mine = client.post("/api/workspaces", json={"name": "W"}).json()
        other = client.post("/api/workspaces", json={"name": "X"}).json()
        source = tmp_path / "talk.wav"
        _speech_like_with_noise(source, seconds=2)
        monkeypatch.setattr(denoise, "_source_path", lambda one: source)
        with SessionLocal() as db:
            workflow = Workflow(workspace_id=mine["id"], name="wf", graph={"nodes": [], "edges": []})
            ours = Asset(workspace_id=mine["id"], kind="audio", name="访谈", file_key="k")
            theirs = Asset(workspace_id=other["id"], kind="audio", name="别人的", file_key="k")
            db.add_all([workflow, ours, theirs])
            db.commit()

            out = denoise_audio_node(db, workflow, {"asset_id": ours.id, "engine": "auto", "strength": "light"})
            assert out["engine"] == "ffmpeg"
            assert db.get(Asset, out["asset_id"]).media_info["derived_from_asset_id"] == ours.id

            with pytest.raises(WorkflowDomainError):
                denoise_audio_node(db, workflow, {"asset_id": theirs.id})
            with pytest.raises(WorkflowDomainError, match="档位"):
                denoise_audio_node(db, workflow, {"asset_id": ours.id, "strength": "max"})

    def test_确认卡开卡前就判档位和素材类型(self) -> None:
        from app.core.db import SessionLocal
        from app.db.models import Asset
        from app.domain.agent.confirmations import ConfirmationError, _validate_payload
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        with SessionLocal() as db:
            audio = Asset(workspace_id=workspace, kind="audio", name="a", file_key="k")
            image = Asset(workspace_id=workspace, kind="image", name="i", file_key="k")
            db.add_all([audio, image])
            db.commit()

            payload = {"asset_id": audio.id, "strength": ""}
            _validate_payload(db, "denoise_audio", workspace, payload)
            assert payload["strength"] == "medium" and payload["resolved_engine"] == "ffmpeg"

            with pytest.raises(ConfirmationError, match="档位"):
                _validate_payload(db, "denoise_audio", workspace, {"asset_id": audio.id, "strength": "max"})
            with pytest.raises(ConfirmationError, match="只有音频或视频"):
                _validate_payload(db, "denoise_audio", workspace, {"asset_id": image.id})
            with pytest.raises(ConfirmationError, match="没有这份素材"):
                _validate_payload(db, "denoise_audio", "another-workspace", {"asset_id": audio.id})

"""智能体「听」音频(ADR 0103):每条阈值用一段合成的声音钉住,再走一遍素材 → 报告 → 频谱图那条路。

合成而不是录音:要的是**确定**能触发(或者确定不触发)某一条的声音 —— 0.5 秒的断、六次 0.15 秒的短断、
满幅削平的波形、一记单样本的爆音、120 BPM 的鼓点、220 Hz 和 440 Hz 两个音。
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, User
from app.domain.analysis.listening import listen_to_assets
from app.domain.assets.importer import register_file_asset
from app.media.listening import listen
from app.media.listening.compare import compare
from app.media.listening.decode import ListeningError
from app.media.paths import resolve_key
from tests.util import fresh_client

RATE = 44_100


def _wav(folder: Path, name: str, samples: np.ndarray) -> Path:
    path = folder / name
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(data.tobytes())
    return path


def _music(seconds: float = 8.0, *, tone: float = 220.0, fade: bool = True) -> np.ndarray:
    """一个持续的音 + 120 BPM 的噪声鼓点,结尾一秒淡出。"""
    t = np.arange(int(RATE * seconds)) / RATE
    signal = 0.12 * np.sin(2 * np.pi * tone * t)
    rng = np.random.default_rng(7)
    for beat in np.arange(0, seconds, 0.5):
        at = int(beat * RATE)
        signal[at : at + 600] += 0.15 * rng.standard_normal(len(signal[at : at + 600])) * np.linspace(1, 0, 600)[: len(signal[at : at + 600])]
    if fade:
        signal[-RATE:] *= np.linspace(1, 0, RATE)
    return signal


def _kinds(report: dict) -> list[str]:
    return [finding["kind"] for finding in report["findings"]]


def test_一段好好的音乐_速度量得出_淡出_没有问题(tmp_path: Path) -> None:
    report = listen(_wav(tmp_path, "ok.wav", _music()), expect="music")
    assert abs(report["rhythm"]["bpm"] - 120) < 3 and report["rhythm"]["steadiness"] > 0.3
    assert report["gaps"]["ending"] in ("fade", "silence")
    assert _kinds(report) == [], report["findings"]


def test_中间断了半秒_音乐里是坏了_念白里只是停顿(tmp_path: Path) -> None:
    signal = _music()
    signal[int(3.0 * RATE) : int(3.5 * RATE)] = 0
    path = _wav(tmp_path, "gap.wav", signal)
    music = listen(path, expect="music")
    assert "dropouts" in _kinds(music)
    dropout = next(one for one in music["findings"] if one["kind"] == "dropouts")
    assert dropout["severity"] == "high" and abs(dropout["at"][0] - 3.0) < 0.05
    assert "dropouts" not in _kinds(listen(path, expect="speech"))


def test_一卡一卡_反复的短断_音乐里报_念白里不报(tmp_path: Path) -> None:
    signal = _music(10.0)
    for start in np.arange(2.0, 8.0, 1.0):
        signal[int(start * RATE) : int((start + 0.15) * RATE)] = 0
    path = _wav(tmp_path, "choppy.wav", signal)
    assert "choppy" in _kinds(listen(path, expect="music"))
    assert "choppyAny" in _kinds(listen(path, expect="any"))
    assert not {"choppy", "choppyAny"} & set(_kinds(listen(path, expect="speech")))


def test_削波_硬切_爆音各自认得出(tmp_path: Path) -> None:
    clipped = listen(_wav(tmp_path, "clip.wav", _music() * 12), expect="music")
    assert "clipping" in _kinds(clipped) and clipped["findings"][0]["severity"] == "high"

    cut = listen(_wav(tmp_path, "cut.wav", _music(fade=False)), expect="music")
    assert "hardCut" in _kinds(cut)

    quiet = 0.2 * np.sin(2 * np.pi * 330 * np.arange(RATE * 6) / RATE)
    quiet[-RATE:] *= np.linspace(1, 0, RATE)
    quiet[int(2.5 * RATE)] = 0.95
    clicks = listen(_wav(tmp_path, "click.wav", quiet), expect="music")
    assert "clicks" in _kinds(clicks)
    assert abs(next(one for one in clicks["findings"] if one["kind"] == "clicks")["at"][0] - 2.5) < 0.02


def test_音高与比较_低八度差十二个半音(tmp_path: Path) -> None:
    low = listen(_wav(tmp_path, "a.wav", _music(tone=220.0)), expect="music")
    high = listen(_wav(tmp_path, "b.wav", _music(tone=440.0)), expect="music")
    assert abs(low["timbre"]["pitch_hz"] - 220) < 5
    low["asset_id"], high["asset_id"] = "a", "b"
    pair = compare([low, high])[0]
    assert abs(pair["pitch_semitones"] - 12) < 0.5 and pair["brightness_ratio"] > 1


def test_素材这条路_第二次读缓存_频谱图路由_一次最多四段() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with tempfile.TemporaryDirectory() as folder, SessionLocal() as db:
        music = register_file_asset(db, workspace_id=ws, project_id=None, source="generated", name="bgm.wav",
                                    source_path=_wav(Path(folder), "bgm.wav", _music()))
        db.commit()
        music_id = music.id
    with SessionLocal() as db:
        user = db.query(User).first()
        first = listen_to_assets(db, user, [music_id], expect="music")
        assert first["listening"][0]["asset_id"] == music_id and first["images"][0]["mime_type"] == "image/png"
        #: 第二次读的是缓存:同一份报告,而且不再起 ffmpeg。
        cache = next(resolve_key(db.get(Asset, music_id).file_key).parent.glob("listening/*.json"))
        again = listen_to_assets(db, user, [music_id], expect="music", with_spectrograms=False)
        assert again["listening"] == first["listening"] and again["images"] == [] and cache.is_file()
        with pytest.raises(ListeningError):
            listen_to_assets(db, user, [music_id, "a", "b", "c", "d"])

    picture = client.get(f"/api/assets/{music_id}/spectrogram")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
    assert picture.content.startswith(b"\x89PNG")

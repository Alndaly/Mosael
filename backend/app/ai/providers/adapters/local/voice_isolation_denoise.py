"""人声提取当降噪用:只留说话声,别的全去掉。

它**不自己跑模型**,借的是分离能力(ADR-0016)的人声那一条 stem。依赖的是分离的**契约**,
不是某个分离引擎:用哪个分离引擎由注册表回答,由注册表在装配时把那个查询函数递进来 ——
这个文件因此不 import registry(否则两边互相 import)。

**它会连音乐一起去掉**,所以 `auto` 永远不挑它(ADR-0017 决定 2):用户说"降噪"时没有要求把
配乐也拿掉。适合的场合是嘈杂环境里的访谈、口播 —— 那种噪声(人声鼎沸、街道)滤波器降不掉。
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from app.ai.providers.contracts.denoise import DenoiseError, DenoiseRequest
from app.ai.providers.contracts.separation import VOCALS, SeparationAdapter, SeparationError, SeparationRequest

#: 「给我一个现在跑得起来的分离引擎」—— 就是 registry.get_separation_adapter。
SeparationLookup = Callable[[str], SeparationAdapter | None]


class VoiceIsolationDenoiseAdapter:
    engine_id = "voice-isolation"
    label_key = "denoiseEngine_voice_isolation"
    #: 没有档位:一段声音要么是人声要么不是,"轻一点地提取人声"不是一个有意义的说法。
    strengths: tuple[str, ...] = ()
    removes_music = True
    setup_hint = "人声提取要先装一个人声分离引擎(设置 → 本机引擎 → 人声分离)"

    def __init__(self, separation: SeparationLookup) -> None:
        self._separation = separation

    def _engine(self) -> SeparationAdapter | None:
        return self._separation("")

    def runtime_ready(self) -> bool:
        return self._engine() is not None

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        engine = self._engine()
        if engine is None:
            raise DenoiseError(self.setup_hint)
        work = out_path.parent / f"{out_path.stem}-stems"
        try:
            stems = engine.separate(SeparationRequest(audio_path=request.audio_path, stems=(VOCALS,)), work)
        except SeparationError as exc:
            raise DenoiseError(f"人声提取失败:{exc}") from exc
        vocals = stems.get(VOCALS)
        if vocals is None or not vocals.is_file():
            raise DenoiseError("人声提取没有产出人声")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(vocals), out_path)
        shutil.rmtree(work, ignore_errors=True)
        return out_path

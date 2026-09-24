"""RNNoise:ffmpeg 自带的 `arnndn` 滤镜 + 随应用带的一个语音降噪模型。

**不装任何东西**:ffmpeg 本来就在,模型文件 300 KB,打进了安装包
(`ai/runtime/models/rnnoise/`,来源与许可见那里的 README)。

它是**语音模型** —— 训练时只把说话声当信号,所以键盘声、碗碟声这类一阵一阵的噪声也能压下去
(内置频谱降噪对它们几乎无效:实测 −0.4 dB,RNNoise −19 dB),代价是音乐也被当成噪声
(实测一段合成音乐被压低 8 dB)。所以 `removes_music = True`,`auto` 不挑它。

档位落在 `mix` 上:处理结果和原声按比例混回去。实测(间断噪声)0.5 / 0.75 / 1.0 分别压低
约 5 / 10 / 19 dB。
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from app.ai.providers.contracts.denoise import (
    subprocess_failure,
    DENOISE_TIMEOUT_SECONDS,
    LIGHT,
    MEDIUM,
    STRENGTHS,
    STRONG,
    DenoiseError,
    DenoiseRequest,
)
from app.core.child_process import run_logged
from app.core.config import settings

MODEL_DIR = Path(__file__).resolve().parents[3] / "runtime" / "models" / "rnnoise"
MODEL_FILE = "somnolent-hogwash.rnnn"
#: 打包进来的那一份。换模型要同时改这里和 README(测试会核对)。
MODEL_SHA256 = "70bb6685eb0c2a1d18e2918dca3fbfbd39317010b1802eb1b6ea73a92f3fdec0"

_MIX = {LIGHT: 0.5, MEDIUM: 0.75, STRONG: 1.0}


@lru_cache(maxsize=1)
def _ffmpeg_has_arnndn() -> bool:
    """装包用的 ffmpeg 是别人编的,不一定带这个滤镜 —— 问一次记住。"""
    try:
        result = run_logged(
            [settings.ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30, what="探测 ffmpeg 滤镜",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and " arnndn " in result.stdout


class RnnoiseDenoiseAdapter:
    engine_id = "rnnoise"
    label_key = "denoiseEngine_rnnoise"
    description_key = "denoiseDesc_rnnoise"
    strengths = STRENGTHS
    removes_music = True
    setup_hint_key = "denoiseSetup_rnnoise"

    def runtime_ready(self) -> bool:
        return (MODEL_DIR / MODEL_FILE).is_file() and _ffmpeg_has_arnndn()

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = run_logged(
                [
                    settings.ffmpeg, "-y", "-v", "error", "-i", str(request.audio_path.resolve()),
                    # 模型用**相对路径**给:滤镜参数里的路径要为 `:` `\\` 转义,Windows 路径两样都有。
                    # 在模型目录里跑,就一个字符都不用转义。
                    "-af", f"arnndn=m={MODEL_FILE}:mix={_MIX[request.strength]}",
                    "-c:a", "pcm_s16le", str(out_path.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=DENOISE_TIMEOUT_SECONDS,
                cwd=MODEL_DIR,
                what="RNNoise 降噪",
            )
        except subprocess.TimeoutExpired as exc:
            raise DenoiseError("providerErr_denoiseTimeout") from exc
        if result.returncode != 0 or not out_path.is_file():
            raise subprocess_failure("providerErr_denoiseFailed", result.stderr, tool="ffmpeg")
        return out_path

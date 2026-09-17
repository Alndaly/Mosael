"""DeepFilterNet:专做语音增强的模型,这几种里效果最好的一个。

跑的是官方发布的 `deep-filter` 二进制(模型编译在里面),由 `runtime/denoise_models` 下载、
校验、放好;这个文件只做"文件在不在"和"把一次请求翻成一次命令行"。为什么不是 Python 包,
见 denoise_models 的说明。

实测(合成语音 + 噪声):一阵一阵的噪声压低约 34 dB(RNNoise 19,内置频谱降噪不到 1),
而说话声的失真是三者里最小的。一段 40 秒的音频 CPU 上 1.3 秒跑完。
代价:它同样把音乐当噪声(一段合成音乐被压到 −69 dB),所以 `auto` 不挑它。

档位落在 `--atten-lim-db` 上:最多压低多少分贝,其余部分和原声混回去。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.ai.providers.contracts.denoise import (
    DENOISE_TIMEOUT_SECONDS,
    LIGHT,
    MEDIUM,
    STRENGTHS,
    STRONG,
    DenoiseError,
    DenoiseRequest,
)
from app.ai.runtime import denoise_models
from app.core.child_process import run_logged
from app.core.config import settings
from app.core.text import blame_line

#: 100 = 不设上限(二进制自己的默认值)。
_ATTEN_LIMIT_DB = {LIGHT: 12, MEDIUM: 24, STRONG: 100}
#: 模型的原生采样率。先转好再交给它 —— 不让它自己的重采样决定音质。
_MODEL_RATE = 48000


class DeepFilterDenoiseAdapter:
    engine_id = denoise_models.DEEPFILTER
    label_key = "denoiseEngine_deepfilternet"
    description_key = "denoiseDesc_deepfilternet"
    strengths = STRENGTHS
    removes_music = True
    setup_hint_key = "denoiseSetup_deepfilternet"

    def runtime_ready(self) -> bool:
        return denoise_models.deepfilter_ready()

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        binary = denoise_models.deepfilter_path()
        if not binary.is_file():
            raise DenoiseError("DeepFilterNet 还没装好")
        work = out_path.parent / f"{out_path.stem}-deepfilter"
        (work / "out").mkdir(parents=True, exist_ok=True)
        # 二进制按**输入文件名**写输出,所以输入放进自己的目录、起一个固定的名字。
        prepared = work / "input.wav"
        try:
            converted = run_logged(
                [settings.ffmpeg, "-y", "-v", "error", "-i", str(request.audio_path),
                 "-ar", str(_MODEL_RATE), "-c:a", "pcm_s16le", str(prepared)],
                capture_output=True, text=True, timeout=DENOISE_TIMEOUT_SECONDS, what="降噪前转采样率",
            )
            if converted.returncode != 0:
                raise DenoiseError(f"降噪前转换失败:{blame_line(converted.stderr, fallback='ffmpeg 没有说明原因')}")
            result = run_logged(
                [
                    str(binary),
                    # 补偿 STFT 和模型前瞻的延迟 —— 不补的话输出比原声晚几十毫秒,放回视频就对不上口型。
                    "--compensate-delay",
                    "--atten-lim-db", str(_ATTEN_LIMIT_DB[request.strength]),
                    "--output-dir", str(work / "out"),
                    str(prepared),
                ],
                capture_output=True,
                text=True,
                timeout=DENOISE_TIMEOUT_SECONDS,
                what="DeepFilterNet 降噪",
            )
        except subprocess.TimeoutExpired as exc:
            raise DenoiseError("降噪超时") from exc
        produced = work / "out" / prepared.name
        if result.returncode != 0 or not produced.is_file():
            shutil.rmtree(work, ignore_errors=True)
            raise DenoiseError(f"降噪失败:{blame_line(result.stderr or result.stdout, fallback='DeepFilterNet 没有说明原因')}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), out_path)
        shutil.rmtree(work, ignore_errors=True)
        return out_path

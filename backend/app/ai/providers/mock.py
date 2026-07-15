from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from app.ai.providers.base import GenerationProvider, GenerationRequest, ProviderError

"""
Local mock providers: exercise the full generation pipeline (job → provider →
asset registration) offline by synthesizing media with ffmpeg. The prompt
seeds a deterministic color so results are visually distinguishable.
"""


def _prompt_color(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    return f"0x{digest[:6]}"


class MockImageProvider(GenerationProvider):
    name = "mock"
    kind = "image"

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, credential: str | None, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated.png"
        size = str(request.parameters.get("size", "1024x576"))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi",
                    "-i", f"gradients=size={size}:c0={_prompt_color(request.prompt)}:c1=0x101418:n=2",
                    "-frames:v", "1",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.SubprocessError as exc:
            raise ProviderError("Mock image synthesis failed") from exc
        return target


class MockVideoProvider(GenerationProvider):
    name = "mock"
    kind = "video"

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, credential: str | None, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated.mp4"
        duration = float(request.parameters.get("duration_seconds", 5))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi",
                    "-i", f"gradients=size=640x360:c0={_prompt_color(request.prompt)}:c1=0x101418:n=2:speed=0.6:duration={duration}",
                    "-f", "lavfi",
                    "-i", f"anullsrc=r=48000:cl=stereo:d={duration}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(target),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except subprocess.SubprocessError as exc:
            raise ProviderError("Mock video synthesis failed") from exc
        return target

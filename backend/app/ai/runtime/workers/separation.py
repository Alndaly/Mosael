"""Standalone source-separation worker.

Runs inside the *separation interpreter* — a Python that has demucs and torch installed
(`ai/runtime/separation_models` builds and owns that virtualenv). Like its neighbours here it
must not import anything from this app: that interpreter's sys.path does not contain the
repository, so an `app.*` import fails at run time and never in the unit tests.

stdin:  JSON {"audio_path": str, "out_dir": str, "model": str, "stems": [str]}
argv:   [result_json_path] — results go to a FILE because demucs and torch write progress bars
        and warnings straight to stdout/stderr.
output: JSON {"stems": {"vocals": path, "background": path}}
Errors exit non-zero with the message on stderr.

**It uses demucs' Python API rather than spawning `python -m demucs.separate`.** Two reasons,
and the second is the one that matters: a subprocess here would be a second door for external
commands (the repository keeps exactly one, `core.child_process.run_logged`, and this file cannot
import it); and going through the API hands back tensors, so "everything except the voice" is a
tensor addition instead of an ffmpeg mix whose default normalisation would quietly drop each stem
to a third of its level.

**Why "background" is computed rather than picked.** htdemucs is a four-stem model
(vocals / drums / bass / other). What this product needs is "the voice" and "everything else", so
the other three are summed back. Going through the four keeps the door open for exposing them
individually later without changing the contract.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VOCALS = "vocals"
BACKGROUND = "background"


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _separate(request: dict, out_dir: Path) -> dict[str, str]:
    audio = Path(str(request.get("audio_path") or ""))
    if not audio.is_file():
        _fail(f"找不到要分离的音频:{audio}")
    model = str(request.get("model") or "htdemucs")
    wanted = set(request.get("stems") or (VOCALS, BACKGROUND))

    try:
        from demucs.api import Separator, save_audio
    except ImportError as exc:  # pragma: no cover - 只在这个 venv 里才走得到
        _fail(f"这个运行环境里没有 demucs:{exc}")

    try:
        separator = Separator(model=model)
        _, stems = separator.separate_audio_file(audio)
    except Exception as exc:  # noqa: BLE001 — 引擎自己的报错原样交给上层
        _fail(f"分离失败:{exc}")

    if VOCALS not in stems:
        _fail(f"{model} 没有给出人声轨,只有:{'、'.join(sorted(stems))}")

    made: dict[str, str] = {}
    if VOCALS in wanted:
        made[VOCALS] = str(_write(stems[VOCALS], out_dir / "vocals.wav", separator, save_audio))
    if BACKGROUND in wanted:
        others = [tensor for name, tensor in stems.items() if name != VOCALS]
        if not others:
            _fail(f"{model} 只给了人声一条,没有可以合成背景音的部分")
        mixed = others[0]
        for tensor in others[1:]:
            # 直接相加 —— 这几条本来就是从同一段音频里拆出来的,加回去应该等于原样。
            # (ffmpeg 的 amix 默认会各除以路数,背景音会整体变轻。)
            mixed = mixed + tensor
        made[BACKGROUND] = str(_write(mixed, out_dir / "background.wav", separator, save_audio))
    return made


def _write(tensor, target: Path, separator, save_audio) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    save_audio(tensor, str(target), samplerate=separator.samplerate)
    if not target.is_file():
        _fail(f"没能写出 {target.name}")
    return target


def main() -> None:
    if len(sys.argv) < 2:
        _fail("用法:separation.py <result_json_path>")
    result_path = Path(sys.argv[1])
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        _fail(f"请求不是合法 JSON:{exc}")
    out_dir = Path(str(request.get("out_dir") or ""))
    if not str(out_dir):
        _fail("缺少 out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    # TORCH_HOME 由调用方设好(权重落在应用自己的数据目录,不是用户主目录)。
    os.environ.setdefault("TORCH_HOME", str(out_dir.parent / "torch"))
    stems = _separate(request, out_dir)
    result_path.write_text(json.dumps({"stems": stems}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

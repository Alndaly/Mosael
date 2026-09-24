"""Standalone source-separation worker.

Runs inside the *separation interpreter* — a Python that has demucs and torch installed
(`ai/runtime/separation_models` builds and owns that virtualenv). Like its neighbours here it
must not import anything from this app: that interpreter's sys.path does not contain the
repository, so an `app.*` import fails at run time and never in the unit tests.

stdin:  JSON {"audio_path": str, "out_dir": str, "model": str, "stems": [str]}
argv:   [result_json_path] — results go to a FILE because demucs and torch write progress bars
        and warnings straight to stdout/stderr.
output: JSON {"stems": {"vocals": path, "background": path}}
Errors exit non-zero. The reason goes to the result file as {"error": {"key", "params"}} — a message
key the host translates (this interpreter cannot import the host's message table) — and a plain
line goes to stderr for the log.

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


def _fail(key: str, **params: object) -> None:
    """说不行,然后退出。

    给人看的那句话**不在这里拼**:这里只报 key(`providerErr_separation*`)和参数,宿主那边
    (ai/providers/adapters/local/demucs_separation)按读的人的语言翻。stderr 上那行是给日志的。
    """
    rendered = {name: str(value) for name, value in params.items()}
    print(f"{key} {json.dumps(rendered, ensure_ascii=False)}" if rendered else key, file=sys.stderr)
    # 原因写进结果文件(argv[1],宿主约定的那个路径);参数都没给全时只剩 stderr 那一行。
    if len(sys.argv) > 1:
        try:
            Path(sys.argv[1]).write_text(json.dumps({"error": {"key": key, "params": rendered}}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 写不进去就只剩 stderr 那一行;宿主会退回它
    raise SystemExit(1)


def _separate(request: dict, out_dir: Path) -> dict[str, str]:
    audio = Path(str(request.get("audio_path") or ""))
    if not audio.is_file():
        _fail("providerErr_separationAudioMissing", path=audio)
    model = str(request.get("model") or "htdemucs")
    wanted = set(request.get("stems") or (VOCALS, BACKGROUND))

    try:
        from demucs.api import Separator, save_audio
    except ImportError as exc:  # pragma: no cover - 只在这个 venv 里才走得到
        _fail("providerErr_separationNoDemucs", detail=exc)

    try:
        separator = Separator(model=model)
        _, stems = separator.separate_audio_file(audio)
    except Exception as exc:  # noqa: BLE001 — 引擎自己的报错原样交给上层
        _fail("providerErr_separationFailed", detail=exc)

    if VOCALS not in stems:
        _fail("providerErr_separationNoVocals", model=model, stems=", ".join(sorted(stems)))

    made: dict[str, str] = {}
    if VOCALS in wanted:
        made[VOCALS] = str(_write(stems[VOCALS], out_dir / "vocals.wav", separator, save_audio))
    if BACKGROUND in wanted:
        others = [tensor for name, tensor in stems.items() if name != VOCALS]
        if not others:
            _fail("providerErr_separationOnlyVocals", model=model)
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
        _fail("providerErr_separationWriteFailed", name=target.name)
    return target


def main() -> None:
    if len(sys.argv) < 2:
        _fail("usage: separation.py <result_json_path>")
    result_path = Path(sys.argv[1])
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        _fail(f"request is not valid JSON: {exc}")
    out_dir = Path(str(request.get("out_dir") or ""))
    if not str(out_dir):
        _fail("request is missing out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    # TORCH_HOME 由调用方设好(权重落在应用自己的数据目录,不是用户主目录)。
    os.environ.setdefault("TORCH_HOME", str(out_dir.parent / "torch"))
    stems = _separate(request, out_dir)
    result_path.write_text(json.dumps({"stems": stems}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

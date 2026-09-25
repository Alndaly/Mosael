"""在 Manim 的 Python 里跑一次 `manim render …`,出错时**另外**交一份结构化的原因。

为什么不直接 `python -m manim`:Manim 把场景里的异常交给 rich 画成一个带边框的彩色 traceback,
折在 80 列里 —— 从那里面抠「第几行、什么错」要和它的排版较劲,改一个版本就可能抠错。这里在
`Scene.render` 外面包一层:异常一出来,先按标准库 traceback 的样子把**类型、消息、每一帧的文件与行号**
写成一行 JSON(前缀 `MOSAEL_MANIM `)送到 stderr,然后照旧抛给 Manim,它该怎么打印还怎么打印。

插件那一侧读到这一行,就能挑出「用户代码的第几行」说一句人话;读不到(比如 Manim 本身没装好、
在 import 时就崩了)再退回去从输出里挑最像原因的那一行。
"""

from __future__ import annotations

import json
import sys
import traceback

MARKER = "MOSAEL_MANIM "


def say(kind: str, **fields: object) -> None:
    sys.stderr.write(MARKER + json.dumps({"kind": kind, **fields}, ensure_ascii=False, default=str) + "\n")
    sys.stderr.flush()


def report(exc: BaseException) -> None:
    frames = [
        {"file": frame.filename, "line": frame.lineno, "name": frame.name, "code": (frame.line or "").strip()}
        for frame in traceback.extract_tb(exc.__traceback__)
    ]
    # SyntaxError 的位置不在栈里,在它自己身上。
    if isinstance(exc, SyntaxError) and exc.filename:
        frames.append({"file": exc.filename, "line": exc.lineno or 0, "name": "<module>", "code": (exc.text or "").strip()})
    say("error", type=type(exc).__name__, message=str(exc)[:4000], frames=frames[-40:])


def main() -> None:
    try:
        from manim.scene.scene import Scene
    except BaseException as exc:  # noqa: BLE001 —— Manim 本身没装好:也要交一份原因
        report(exc)
        raise
    original = Scene.render

    def render(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            result = original(self, *args, **kwargs)
            # 成片多长:讲解视频的场景自己报每一段,自定义动画靠这一行
            say("rendered", time=float(getattr(self.renderer, "time", 0.0) or 0.0))
            return result
        except BaseException as exc:
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
                report(exc)
            raise

    Scene.render = render  # type: ignore[method-assign]
    from manim.__main__ import main as manim_main

    try:
        manim_main(args=sys.argv[1:], prog_name="manim")
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 场景文件在 import 时就出错(顶层 NameError)走这里
        report(exc)
        raise


if __name__ == "__main__":
    main()

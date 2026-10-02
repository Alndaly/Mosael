"""取当前帧走的是**渲染那条路**,不是抓预览的画布。

预览里花字和字幕是 DOM 叠上去的(见 features/editor/Monitor),画布抓不到它们 —— 抓出来的
画面看着对,只是少了一层字,而用户不会发现自己导出的是没有字幕的那一版。

这条钉住三件事:每一层的滤镜和成片是同一份、文字先渲成 PNG、只出一帧不出音轨。
(只渲这一刻看得见的那部分,画出来的和成片逐像素比对,见 test_still_renders_only_what_is_visible。)
"""

from __future__ import annotations

RATCHET = True

from pathlib import Path

from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan


def _command(**kwargs) -> list[str]:
    #: 用**真的**计划构建器 —— 自己捏一个假 plan 的话,它和真结构差在哪都不知道,
    #: 而这条测试要证明的恰恰是「和成片走的是同一份」。
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets={"a": {"file_key": "a"}},
    )
    return build_ffmpeg_command(plan, lambda key: Path("/nonexistent") / key, Path("/tmp/out.jpg"), **kwargs)


def test_取一帧和出成片用同一份滤镜_只换输出那一段() -> None:
    """**每一层的滤镜都不能改** —— 保真度全在那里:变换、调色、花字、字幕、叠层。
    另写一条取帧的路的话,它迟早和成片长得不一样。取一帧只渲那一刻所在的一段,那一段的
    滤镜链和成片里的是同一条。"""
    still = _command(still_at=0.5)
    movie = _command()

    def chain(command: list[str]) -> str:
        graph = command[command.index("-filter_complex") + 1]
        return next(part for part in graph.split(";") if part.startswith("[0:v]"))

    assert "-filter_complex" in still, "取帧没走滤镜图"
    assert chain(still) == chain(movie), "取帧那一段的滤镜和成片的不一样 —— 它们迟早会画出不同的东西"


def test_只出一帧_不出音轨() -> None:
    still = _command(still_at=3.2)
    assert still[still.index("-frames:v") + 1] == "1"
    assert "-c:a" not in still, "一张图不该带音频编码"
    assert "-t" not in still, "取一帧不该限时长 —— 那是成片的事"


def test_seek_放在滤镜图之后() -> None:
    """输出侧 seek:滤镜图照常从头算,那些跟时间走的东西(关键帧、淡入淡出、字幕出入点)
    才会落在正确的位置上。放到输入侧的话,它们全部从那一刻重新开始。"""
    still = _command(still_at=3.2)
    #: 输入侧也可能有 -ss(那一段从这一刻前一点开始解,时间戳照旧按段内时间),
    #: 要看的是滤镜图之后的那一个。
    after = still[still.index("-filter_complex"):]
    assert "-ss" in after, "输出侧没有 seek"
    assert after[after.index("-ss") + 1] == "3.200"


def test_取帧之前要先把文字渲成_PNG() -> None:
    """字幕和花字是**另起一次无头浏览器渲成 PNG**再叠进滤镜图的。少这一步,取出来的帧就是
    没有字幕的那一版 —— 而画面看着是对的,用户不会发现。

    这条断言的是**接线**:render_still 调没调那一步,而不是那一步算得对不对。
    """
    import subprocess
    import tempfile
    from pathlib import Path as _Path
    from unittest.mock import patch as mock_patch

    from app.media import render_executor

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets={"a": {"file_key": "a"}},
    )
    seen: dict = {}

    def fake_rasterize(p, workdir):
        seen["rasterized"] = True
        return {"subtitles": [], "text_overlays": [], "ai_labels": []}

    def fake_build(p, resolve, output, **kwargs):
        seen["text_layers"] = kwargs.get("text_layers")
        return ["true"]

    def fake_run(*_args, **_kwargs):
        target.write_bytes(b"x")
        return subprocess.CompletedProcess(args=["true"], returncode=0, stdout="", stderr="")

    with tempfile.TemporaryDirectory() as tmp:
        target = _Path(tmp) / "frame.jpg"
        with (
            mock_patch.object(render_executor, "_rasterize_text", side_effect=fake_rasterize),
            mock_patch.object(render_executor, "build_ffmpeg_command", side_effect=fake_build),
            mock_patch.object(render_executor, "run_logged", side_effect=fake_run),
        ):
            render_executor.render_still(plan, lambda key: _Path(key), target, 1.0)

    assert seen.get("rasterized"), "取帧前没渲文字 —— 导出的帧会少一层字幕"
    assert isinstance(seen.get("text_layers"), render_executor.BurnedText), "渲了但没传给命令,等于没渲"


def test_不建声音那一路_也就没有悬着的输出() -> None:
    """第一版只 map 了画面,而滤镜图里 concat 还吐着声音,ffmpeg 连跑都不跑:
    「Filter 'concat' has output 1 (abase) unconnected」—— 当时的补法是把声音丢进 null,
    于是取一帧要把整条时间线的声音解一遍。现在声音那一路根本不建。
    """
    still = _command(still_at=3.2)
    graph = still[still.index("-filter_complex") + 1]
    assert still.count("-map") == 1, f"一张图只该接画面那一路:{still}"
    assert "[abase]" not in graph and "anullsrc" not in graph, "取一帧不该建声音那一路"
    assert "null" not in still[still.index("-frames:v"):], "声音都没建,不该再有丢进 null 的那一路"

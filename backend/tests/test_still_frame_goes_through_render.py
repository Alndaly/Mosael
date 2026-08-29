"""取当前帧走的是**渲染那条路**,不是抓预览的画布。

预览里花字和字幕是 DOM 叠上去的(见 features/editor/Monitor),画布抓不到它们 —— 抓出来的
画面看着对,只是少了一层字,而用户不会发现自己导出的是没有字幕的那一版。

这条钉住三件事:滤镜图和成片是同一份、文字先渲成 PNG、只出一帧不出音轨。
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


def test_取一帧和出成片用同一条命令_只换输出那一段() -> None:
    """**滤镜图一个字都不能改** —— 保真度全在那里:变换、调色、花字、字幕、叠层。
    另写一条取帧的路的话,它迟早和成片长得不一样。"""
    still = _command(still_at=3.2)
    movie = _command()

    assert "-filter_complex" in still, "取帧没走滤镜图"
    assert still[still.index("-filter_complex") + 1] == movie[movie.index("-filter_complex") + 1], (
        "取帧的滤镜图和成片的不一样 —— 它们迟早会画出不同的东西"
    )


def test_只出一帧_不出音轨() -> None:
    still = _command(still_at=3.2)
    assert still[still.index("-frames:v") + 1] == "1"
    assert "-c:a" not in still, "一张图不该带音频编码"
    assert "-t" not in still, "取一帧不该限时长 —— 那是成片的事"


def test_seek_放在滤镜图之后() -> None:
    """输出侧 seek:滤镜图照常从头算,那些跟时间走的东西(关键帧、淡入淡出、字幕出入点)
    才会落在正确的位置上。放到输入侧的话,它们全部从那一刻重新开始。"""
    still = _command(still_at=3.2)
    assert still.index("-ss") > still.index("-filter_complex")
    assert still[still.index("-ss") + 1] == "3.200"


def test_取帧之前要先把文字渲成_PNG() -> None:
    """字幕和花字是**另起一次无头浏览器渲成 PNG**再叠进滤镜图的。少这一步,取出来的帧就是
    没有字幕的那一版 —— 而画面看着是对的,用户不会发现。

    这条断言的是**接线**:render_still 调没调那一步,而不是那一步算得对不对。
    """
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
        return {"marker": "png"}

    def fake_build(p, resolve, output, **kwargs):
        seen["text_pngs"] = kwargs.get("text_pngs")
        return ["true"]

    with tempfile.TemporaryDirectory() as tmp:
        target = _Path(tmp) / "frame.jpg"
        with (
            mock_patch.object(render_executor, "_rasterize_text", side_effect=fake_rasterize),
            mock_patch.object(render_executor, "build_ffmpeg_command", side_effect=fake_build),
            mock_patch.object(render_executor, "run_logged", side_effect=lambda *a, **k: target.write_bytes(b"x")),
        ):
            render_executor.render_still(plan, lambda key: _Path(key), target, 1.0)

    assert seen.get("rasterized"), "取帧前没渲文字 —— 导出的帧会少一层字幕"
    assert seen.get("text_pngs") == {"marker": "png"}, "渲了但没传给命令,等于没渲"


def test_音频那条也要有人接_否则_ffmpeg_直接拒跑() -> None:
    """滤镜图和成片是同一份,而它的 concat 会**同时吐出画面和声音**。只接画面的话 ffmpeg
    连跑都不跑:「Filter 'concat' has output 1 (abase) unconnected」。

    这条是踩出来的:第一版只 map 了画面,取帧在真机上一次都没成功过。
    """
    still = _command(still_at=3.2)
    assert still.count("-map") == 2, f"只接了一路 —— 另一路悬着,ffmpeg 会拒跑:{still}"
    assert still[-3:] == ["-f", "null", "-"], "音频那路没丢进 null"

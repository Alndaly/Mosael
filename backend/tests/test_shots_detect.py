"""拆镜头之「量」那一半(domain/shots/detect.py):刀口解析、动静解析、碎片并镜、中位数掐两头。

纯函数的判据照 ADR 0061:刀口是 ffmpeg scene 分数给的;短于最短镜头的碎片并进前一镜;
每镜的动静取镜内中位数、两头各掐掉 `min(0.4, max(0.1, 镜长×0.15))` 秒(刀口附近的差是切换本身)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.domain.shots import detect

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# --------------------------------------------------------------------------------------
# 解析 ffmpeg 的输出(不跑 ffmpeg)
# --------------------------------------------------------------------------------------

CUTS_TEXT = """frame:0    pts:0       pts_time:0
frame:25    pts:25      pts_time:1.0
lavfi.scene_score=0.56
frame:50    pts:50      pts_time:2.0
lavfi.scene_score=0.91
"""

MOTION_TEXT = """frame:1    pts:1      pts_time:0.2
lavfi.signalstats.YAVG=3.20
frame:2    pts:2      pts_time:0.4
lavfi.signalstats.YAVG=0.10
frame:3    pts:3      pts_time:0.6
lavfi.signalstats.YAVG=127.50
"""


def test_parse_cuts_pairs_pts_time_with_score() -> None:
    cuts = detect._parse_cuts(CUTS_TEXT)
    assert cuts == [{"time": 1.0, "score": 0.56}, {"time": 2.0, "score": 0.91}]


def test_parse_cuts_ignores_score_without_pts() -> None:
    assert detect._parse_cuts("lavfi.scene_score=0.9\n") == []


def test_parse_motion_reads_yavg_series() -> None:
    assert detect._parse_motion(MOTION_TEXT) == [3.2, 0.1, 127.5]


# --------------------------------------------------------------------------------------
# build_shots:刀口 → 镜头
# --------------------------------------------------------------------------------------

def test_build_shots_splits_on_cuts() -> None:
    cuts = [{"time": 1.0, "score": 0.5}, {"time": 2.5, "score": 0.6}]
    shots = detect.build_shots(4.0, cuts, [])
    assert [(s["id"], s["start"], s["end"]) for s in shots] == [
        ("S01", 0.0, 1.0), ("S02", 1.0, 2.5), ("S03", 2.5, 4.0),
    ]
    assert [s["seconds"] for s in shots] == [1.0, 1.5, 1.5]


def test_build_shots_merges_short_fragments_into_previous() -> None:
    #: 0–0.1 是闪白 / 字幕跳变级的碎片,并进前一镜(这里是片头,并进后一镜)。
    cuts = [{"time": 0.1, "score": 0.9}, {"time": 1.0, "score": 0.5}]
    shots = detect.build_shots(2.0, cuts, [])
    assert [(s["start"], s["end"]) for s in shots] == [(0.0, 1.0), (1.0, 2.0)]


def test_build_shots_merges_inner_fragment_into_previous() -> None:
    cuts = [{"time": 1.0, "score": 0.5}, {"time": 1.2, "score": 0.9}, {"time": 2.0, "score": 0.5}]
    shots = detect.build_shots(3.0, cuts, [])
    #: 1.0–1.2 的碎片并进前一镜;1.2–2.0 自己是一镜(它不是碎片)。
    assert [(s["start"], s["end"]) for s in shots] == [(0.0, 1.2), (1.2, 2.0), (2.0, 3.0)]


def test_build_shots_drops_cuts_outside_duration() -> None:
    cuts = [{"time": 0.0, "score": 0.9}, {"time": -1.0, "score": 0.9}, {"time": 99.0, "score": 0.9}]
    shots = detect.build_shots(2.0, cuts, [])
    assert len(shots) == 1 and shots[0]["start"] == 0.0 and shots[0]["end"] == 2.0


def test_build_shots_truncates_at_max_shots() -> None:
    cuts = [{"time": round(i * 0.5, 3), "score": 0.9} for i in range(1, 600)]
    shots = detect.build_shots(300.0, cuts, [])
    assert len(shots) == detect.MAX_SHOTS
    assert shots[-1]["id"] == f"S{detect.MAX_SHOTS:02d}"
    assert shots[-1]["end"] == pytest.approx(detect.MAX_SHOTS * 0.5)  # 截断处就是最后一镜


def test_shot_id_keeps_counting_past_99() -> None:
    assert detect.shot_id(1) == "S01"
    assert detect.shot_id(100) == "S100"


# --------------------------------------------------------------------------------------
# shot_motion:中位数 + 掐两头
# --------------------------------------------------------------------------------------

def _track(value: float, seconds: float, hz: int = detect.MOTION_HZ) -> list[float]:
    return [value] * int(seconds * hz)


def test_shot_motion_median_inside_shot() -> None:
    #: 5 秒镜、两头各掐 0.4s → 采样 0.4–4.6 秒。值恒 7 → 中位数 7。
    track = _track(7.0, 5.0)
    assert detect.shot_motion(track, 0.0, 5.0) == 7.0


def test_shot_motion_trims_cut_edges() -> None:
    #: 整段 0,只在刀口两侧(0 秒附近和 5 秒附近)有尖峰 —— 掐掉两头之后只剩 0。
    track = _track(0.0, 5.0)
    for index in (0, 1, 2, 3, len(track) - 1, len(track) - 2):
        track[index] = 200.0
    assert detect.shot_motion(track, 0.0, 5.0) == 0.0


def test_shot_motion_trim_scales_with_short_shots() -> None:
    #: 0.5 秒的镜:掐 min(0.4, max(0.1, 0.075)) = 0.1s 两头 → 剩 0.3 秒采样。
    track = [9.0, 9.0, 200.0]  # 0.2s / 0.4s / 0.6s:掐 0.1s 两头后只剩前两个采样
    assert detect.shot_motion(track, 0.0, 0.5) == 9.0


def test_shot_motion_none_when_nothing_left_after_trim() -> None:
    assert detect.shot_motion([], 0.0, 5.0) is None
    assert detect.shot_motion([5.0], 0.0, 0.2) is None


def test_shot_motion_uses_median_not_mean() -> None:
    track = _track(2.0, 4.0)
    track[10] = 200.0  # 单帧尖峰不拉高整镜的动静
    assert detect.shot_motion(track, 0.0, 4.0) == 2.0


def test_第_i_个采样落在_i_加_1_除以_hz_秒处() -> None:
    """时间轴约定只有这一条:`values[i]` 在 `(i + 1) / MOTION_HZ` 秒处(ffmpeg 的 tblend 要前一帧,
    第 0 帧不出值,所以整条曲线偏一位)。它同时被 detect.shot_motion 和存下来的曲线用着,谁也别另猜一套。"""
    assert detect.sample_time(0) == pytest.approx(1 / detect.MOTION_HZ)
    assert detect.sample_time(4) == pytest.approx(1.0)
    assert detect.sample_time(0, hz=2) == pytest.approx(0.5)

    #: 只在索引 4(= 1.0 秒)有尖峰:掐掉两头之后只剩 [0.9, 1.1] 秒那一段采样,中位数就是它。
    #: 要是把索引当成 i / hz(0.8 秒),这个窗口里一个采样都取不到,中位数会变成 0。
    track = _track(0.0, 2.0)
    track[4] = 42.0
    assert detect.shot_motion(track, 0.8, 1.2) == 42.0


# --------------------------------------------------------------------------------------
# 真跑一遍 ffmpeg:色块拼接的片子,刀口应该在颜色交界处
# --------------------------------------------------------------------------------------

def _make_color_cut_video(target: Path, *, moving: bool = False) -> None:
    """四段纯色(红绿蓝黄)各 1 秒拼一条 4 秒片子;刀口在 1/2/3 秒。moving=True 时第二段用 testsrc2(整幅在动)。"""
    second = ("nullsrc=s=320x180:r=25:d=1,geq=random(1)*255,format=yuv420p" if moving
              else "color=c=white:s=320x180:r=25:d=1")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", second,
         "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=yellow:s=320x180:r=25:d=1",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(target)],
        check=True, timeout=60,
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_measure_finds_cuts_and_quiet_motion(tmp_path: Path) -> None:
    video = tmp_path / "cuts.mp4"
    _make_color_cut_video(video)
    measured = detect.measure(video)
    times = [cut["time"] for cut in measured.cuts]
    assert len(times) == 3
    for expected in (1.0, 2.0, 3.0):
        assert any(abs(at - expected) < 0.15 for at in times), f"漏了 {expected}s 的刀口: {times}"

    shots = detect.build_shots(4.0, measured.cuts, measured.motion)
    assert len(shots) == 4
    assert shots[0]["id"] == "S01" and shots[3]["id"] == "S04"
    #: 纯色段落整幅没动:中位数该接近 0(掐掉刀口两侧后)。
    assert all(shot["motion"] is not None and shot["motion"] < 5.0 for shot in shots)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_measure_without_motion_only_reads_cuts(tmp_path: Path) -> None:
    video = tmp_path / "cuts.mp4"
    _make_color_cut_video(video)
    measured = detect.measure(video, motion=False)
    assert measured.motion == []
    assert len(measured.cuts) == 3


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_measure_moving_segment_has_real_motion(tmp_path: Path) -> None:
    video = tmp_path / "moving.mp4"
    _make_color_cut_video(video, moving=True)
    measured = detect.measure(video)
    shots = detect.build_shots(4.0, measured.cuts, measured.motion)
    moving = next(shot for shot in shots if 1.0 <= shot["start"] < 2.0)
    still = next(shot for shot in shots if shot["start"] < 1.0)
    assert moving["motion"] is not None and moving["motion"] > 10.0
    assert still["motion"] is not None and still["motion"] < 5.0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_曲线的采样时刻真的按_i_加_1_除以_hz_排(tmp_path: Path) -> None:
    """整幅在动的那一段是 1–2 秒:量的高值必须落在 1.0–2.0 秒对应的那些下标上。

    这一条钉的是**偏几位**:1–2 秒那段是随机噪点,结束那一帧(索引 9)的差值是三位数;0.8 秒还是纯红、
    差值恰好 0。把索引当成 `i / hz` 的话,热的那几个会整体挪到 0.8–1.8 秒 —— 这两条断言当场就红。
    """
    video = tmp_path / "moving.mp4"
    _make_color_cut_video(video, moving=True)
    measured = detect.measure(video)
    hot = {round(detect.sample_time(index), 2)
           for index, value in enumerate(measured.motion) if value > 5}
    assert 1.2 in hot and 1.8 in hot, f"整幅在动的那一段没测出来:{sorted(hot)}"
    assert 2.0 in hot, "噪点段结束那一帧在索引 9(=(9+1)/5 秒处)"
    assert 0.8 not in hot, "0.8 秒还是纯红、差值为 0;它算热就是整条曲线偏了"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_probe_reads_duration_fps_size_and_audio(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)],
        check=True, timeout=60,
    )
    info = detect.probe(video)
    assert info.duration == pytest.approx(2.0, abs=0.2)
    assert info.width == 320 and info.height == 180
    assert info.fps == pytest.approx(25.0, abs=1.0)
    assert info.has_audio is True
    assert info.as_dict()["has_audio"] is True

"""下载要显示速度,而且那个速度得看得下去。

用户:「下载应该有速度显示」。代码里其实**算了**速度 —— 界面上也有渲染它的位置 —— 但用户
截图里那一行只有「下载中(已用 10分44秒)」,速度和 ETA 都不见了。

原因是它按**一次 1.5 秒的采样**算:

    speed = (这次量到的字节 - 上次量到的) / 1.5

而下载器是成块写盘的:同一个 1.5 秒窗口里,可能一个字节都没落下来(还在缓冲/建连/校验),
下一个窗口一下子落 200MB。于是速度在 0 和几百 MB/s 之间跳,而 `eta = … if speed > 100`
这条判据在跳到 0 的那一瞬就把 ETA 抹掉 —— 用户看到的那一眼,恰好是 0 的那一眼。

**一个抖到看不下去的数,和没有这个数差不多。** 用滑动平均把它磨平:速度要能反映"最近这一段
下得多快",而不是"最近 1.5 秒下了多少"。

这段逻辑转写和克隆两条下载路各有一份循环,所以判据放在一处共用的实现上 —— 两份实现必然
在下一次修的时候只修一份。
"""

from __future__ import annotations

from app.core.rate import DownloadRate


def test_a_burst_does_not_read_as_infinite_then_zero() -> None:
    """两个窗口:一个落了 300MB,下一个一个字节都没落。真实速度是两者的平均,而不是 0。"""
    rate = DownloadRate(half_life=6.0)
    rate.update(0, at=0.0)
    rate.update(300_000_000, at=1.5)
    quiet = rate.update(300_000_000, at=3.0)

    assert quiet > 10_000_000, f"一个安静的窗口就把速度打回 0 了:{quiet}"


def test_it_converges_on_a_steady_rate() -> None:
    """稳定下载时,读数要收敛到真实速率上,而不是永远滞后。"""
    rate = DownloadRate(half_life=2.0)
    total = 0
    speed = 0.0
    for step in range(1, 40):
        total += 50_000_000  # 每 1 秒 50MB
        speed = rate.update(total, at=float(step))

    assert 45_000_000 <= speed <= 55_000_000, speed


def test_the_first_sample_has_no_speed() -> None:
    """只有一个点的时候没有速率可言 —— 别编一个出来。"""
    rate = DownloadRate()

    assert rate.update(1_000_000, at=0.0) == 0.0


def test_it_never_goes_negative() -> None:
    """量到的字节数会变小(下载器清理临时文件、换分片)。负速度不是速度。"""
    rate = DownloadRate()
    rate.update(500_000_000, at=0.0)
    rate.update(500_000_000, at=1.0)

    assert rate.update(100_000_000, at=2.0) >= 0.0


def test_eta_needs_both_a_speed_and_a_remainder() -> None:
    rate = DownloadRate(half_life=2.0)
    rate.update(0, at=0.0)
    for step in range(1, 10):
        rate.update(step * 50_000_000, at=float(step))

    assert rate.eta(remaining=500_000_000) is not None
    assert rate.eta(remaining=0) is None  # 下完了没有"还要多久"


def test_eta_is_none_while_nothing_is_moving() -> None:
    """卡住时不要编一个 ETA —— 一个飞涨的"剩余 3 小时"比不显示更让人误判。"""
    rate = DownloadRate()
    rate.update(0, at=0.0)
    rate.update(0, at=5.0)

    assert rate.eta(remaining=1_000_000_000) is None


def test_nobody_hand_rolls_the_speed_math_again() -> None:
    """转写和克隆两条下载路曾经各有一份 `(现在 - 上次) / dt`,于是同一个毛病要修两遍。

    这条盯的是"别再长出第三份"。判据是**形状**:给一个叫 speed/rate 的名字赋一个"差 / 间隔"。
    新写下载进度时改用 core.rate.DownloadRate。
    """
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        if path.as_posix() == "app/core/rate.py":  # 它就是那一份实现
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id not in {"speed", "rate", "bps"}:
                continue
            value = node.value
            if isinstance(value, ast.Call):  # max(0.0, …) 这种包一层的也要看进去
                value = next((a for a in value.args if isinstance(a, ast.BinOp)), value)
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div) \
                    and isinstance(value.left, ast.BinOp) and isinstance(value.left.op, ast.Sub):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, "又手搓了一份速率计算:\n  " + "\n  ".join(offenders)

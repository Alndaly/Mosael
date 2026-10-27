"""下载速率:把抖动的采样磨成一个能看的数。叶子模块 —— 不 import 任何 app 内部的东西。"""

from __future__ import annotations

import math


class DownloadRate:
    """按"最近这一段下得多快"给速度,而不是"最近一次采样落了多少"。

    此前转写和克隆两条下载路各自这么算:

        speed = (这次量到的 - 上次量到的) / 上次到这次的秒数

    而下载器是成块写盘的:同一个窗口里可能一个字节都没落(还在缓冲/建连/校验),下一个窗口
    一下子落几百 MB。于是读数在 0 和几百 MB/s 之间跳,而 ETA 的判据(`speed > 100`)在跳到 0
    的那一瞬就把 ETA 抹掉 —— 用户看到的那一眼,恰好是 0 的那一眼,于是"没有速度显示"。

    指数滑动平均:`half_life` 秒前的样本权重减半。按时间衰减而不是按样本个数衰减,是因为
    采样间隔本身不保证均匀(量一个几 GB 的目录快慢不定)。
    """

    def __init__(self, half_life: float = 6.0) -> None:
        self._half_life = max(0.1, half_life)
        self._last_bytes: int | None = None
        self._last_at: float = 0.0
        self._speed = 0.0

    def update(self, measured_bytes: int, *, at: float) -> float:
        """喂一个采样,拿回平滑后的字节/秒。"""
        if self._last_bytes is None:  # 只有一个点时没有速率可言,别编一个
            self._last_bytes, self._last_at = measured_bytes, at
            return 0.0
        dt = max(at - self._last_at, 1e-3)
        # 量到的字节数会变小(下载器清理临时文件、换分片)。负速度不是速度。
        instant = max(0.0, (measured_bytes - self._last_bytes) / dt)
        weight = 1.0 - math.exp(-dt * math.log(2) / self._half_life)
        self._speed += (instant - self._speed) * weight
        self._last_bytes, self._last_at = measured_bytes, at
        return self._speed

    @property
    def speed(self) -> float:
        return self._speed

    def eta(self, *, remaining: int) -> float | None:
        """还要多久。停着不动时返回 None —— 一个飞涨的「剩余 3 小时」比不显示更让人误判。"""
        if remaining <= 0 or self._speed <= 100:
            return None
        return remaining / self._speed

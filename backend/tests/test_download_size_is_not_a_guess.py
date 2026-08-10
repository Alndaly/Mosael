"""进度条的分母必须是**真的**,不然它到了 100% 还在下。

用户截图:

    Fish Speech S2 Pro   4.0 GB          ⟳ 100%
    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
    5.2 GB / 4.0 GB                下载中(已用 10分44秒)

`5.2 / 4.0` 一眼就是错的。查 Hub 上 `fishaudio/s2-pro` 的实际大小:**11.01 GB**(两个
4~5 GB 的 safetensors + 1.87 GB 的 codec.pth),而目录里当时已经落了 7.25 GB。写在代码里的
4.0 GB 是个拍出来的数,差了将近三倍。

它坏的不只是那根条:

1. 卡片上那句「4.0 GB」是用户**据以决定要不要下**的数字 —— 按它算磁盘、按它算时间。
2. `_is_installed` 的判据是"实测 ≥ 期望 × 0.6" = 2.4 GB。也就是说一个**只下了两成**的模型
   就会被判成"已安装" —— 然后合成在运行时炸。转写那边踩过一模一样的坑(符号链接把量翻倍,
   于是下到一半的模型被判成已装)。

判据分两层:估计值要对得上真实大小;而**当实测已经越过估计值,这个估计就已经被证伪了** ——
那一刻起就不该再拿它当分母,画一根满的条比画不出条更糟(它说的是"下完了")。
"""

from __future__ import annotations

from app.audio import tts_models


def test_the_fish_estimate_matches_the_real_repo() -> None:
    """fishaudio/s2-pro 在 Hub 上实测 11.01 GB(2025-08 查)。差三倍的估计不是估计。"""
    fish = tts_models._BY_ID["fish-speech"]

    assert fish.expected_bytes >= 10_000_000_000, f"还是那个拍出来的数:{fish.expected_bytes}"


def test_the_f5_estimate_is_left_alone() -> None:
    """F5 只下一个 1.35 GB 的检查点 + 0.05 GB 的 vocos —— 1.5 GB 是对的,别顺手改坏。"""
    f5 = tts_models._BY_ID["f5-tts"]

    assert 1_000_000_000 <= f5.expected_bytes <= 2_000_000_000


def test_a_disproven_estimate_stops_being_a_denominator(monkeypatch) -> None:
    """实测越过估计值 = 估计被证伪。那一刻起不再报分母,免得画出一根满的条。"""
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: False)
    engine = tts_models._BY_ID["fish-speech"]
    monkeypatch.setattr(tts_models, "_measure", lambda item: engine.expected_bytes + 1_000_000_000)
    tts_models._store.set(
        "fish-speech",
        tts_models._Live(status="downloading", downloaded=engine.expected_bytes + 1_000_000_000,
                         total=engine.expected_bytes, message="下载中"),
    )
    try:
        row = tts_models.get_status("fish-speech")
        assert row["total_bytes"] == 0, f"还在拿一个已经被证伪的数当分母:{row}"
        assert row["downloaded_bytes"] > 0, "分母没了,分子还得在 —— 否则界面什么都说不出来"
    finally:
        tts_models._store.clear("fish-speech")


def test_a_sane_estimate_still_draws_the_bar() -> None:
    """这道闸只挡"已经被证伪"的那一段,正常下载照常有进度条。"""
    engine = tts_models._BY_ID["fish-speech"]
    tts_models._store.set(
        "fish-speech",
        tts_models._Live(status="downloading", downloaded=engine.expected_bytes // 3,
                         total=engine.expected_bytes, message="下载中"),
    )
    try:
        row = tts_models.get_status("fish-speech")
        assert row["total_bytes"] == engine.expected_bytes
    finally:
        tts_models._store.clear("fish-speech")

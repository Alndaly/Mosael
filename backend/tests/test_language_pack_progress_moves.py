"""下语言包时进度**得动**。

真机反馈:配音面板里点「下载这个模型」,加载一会儿就没反应了。

原因不是卡住,是没人报进度:worker 只在**每个文件开始前**报一次(两个文件 → 0.1、0.5、1.0
三跳),而那 0.1 之后要下 1.3–5.4 GB,几分钟到几十分钟一动不动。引擎权重和转写模型那两条路
早就是"后端在旁边数盘上的字节",这条是第三处、也是唯一的例外 —— 而例外恰好是出问题的那条。

**不指望被观测方主动汇报**:它正忙着下载,不忙着说话。
"""
from __future__ import annotations

import time

from app.ai.runtime import f5_models


def test_progress_follows_bytes_on_disk_not_worker_events(monkeypatch, tmp_path) -> None:
    model = f5_models._BY_ID["ja"]
    target = tmp_path / model.local_dir
    target.mkdir(parents=True)
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda m, blocking=False: (1000, False))
    monkeypatch.setattr(f5_models, "_POLL_SECONDS", 0.02)

    seen: list[float] = []
    real_set_live = f5_models.set_live
    monkeypatch.setattr(f5_models, "set_live",
                        lambda mid, **f: (seen.append(f["progress"]) if "progress" in f else None,
                                          real_set_live(mid, **f))[1])

    watcher = f5_models._ByteWatcher(model, model.id, {"message": "下载中"})
    watcher.start()
    try:
        # worker **一个事件都不报**,只是在下载 —— 盘上的字节慢慢多起来。
        for size in (200, 500, 900):
            (target / "model_21999120.pt").write_bytes(b"x" * size)
            time.sleep(0.08)
    finally:
        watcher.stop()
        f5_models.clear_live(model.id)

    assert seen, "一次进度都没报 —— 界面上就是「点了没反应」"
    assert max(seen) > min(seen), f"进度没动过:{seen}"
    assert max(seen) >= 0.8, f"盘上已经 900/1000 了,而报出去的最高只有 {max(seen)}"


def test_progress_never_claims_done_before_it_is(monkeypatch, tmp_path) -> None:
    """量到的字节到顶也别报 100% —— 「装好了」由检查点在不在说了算,不由进度条说了算。"""
    model = f5_models._BY_ID["ja"]
    target = tmp_path / model.local_dir
    target.mkdir(parents=True)
    (target / "model_21999120.pt").write_bytes(b"x" * 5000)
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    monkeypatch.setattr(f5_models, "measured_total", lambda m, blocking=False: (1000, False))
    monkeypatch.setattr(f5_models, "_POLL_SECONDS", 0.02)

    watcher = f5_models._ByteWatcher(model, model.id, {"message": "x"})
    watcher.start()
    time.sleep(0.1)
    watcher.stop()
    progress = f5_models.status(model)["progress"]
    f5_models.clear_live(model.id)
    assert progress <= 0.99, f"报了 {progress} —— 100% 该由「检查点在盘上」来说"


def test_the_base_model_measures_its_own_checkpoint_not_the_whole_root(monkeypatch, tmp_path) -> None:
    """基础模型 shared_root=True,文件落在根下。量整个根目录会把**别的语言包**一起算进来,
    进度于是从一开始就是满的。"""
    base = f5_models._BY_ID["base"]
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    (tmp_path / "F5TTS_v1_Base").mkdir(parents=True)
    (tmp_path / "F5TTS_v1_Base" / "model_1250000.safetensors").write_bytes(b"x" * 100)
    # 另一个语言包躺在同一个根下 —— 它的字节不该算进基础模型的进度。
    (tmp_path / "ja").mkdir()
    (tmp_path / "ja" / "model_21999120.pt").write_bytes(b"y" * 9000)

    watcher = f5_models._ByteWatcher(base, base.id, {"message": "x"})
    assert watcher._measure() == 100, "把别的语言包的字节也算进来了"

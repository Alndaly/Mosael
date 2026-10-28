"""下载进度要数**没下完的那一截**。

真机截图:管理 → 引擎 → 声音克隆,Qwen3-TTS 正在下,进度条不动,左下方那行实时数值也不动。

前端轮询是好的(`VoiceCloneSection.tsx` 里下载中每 1.2 秒问一次),坏在**后端量错了东西**:
Qwen 走 `snapshot_download(local_dir=…)`,那 3.83 GB 的主权重在整个下载期间都叫

    <local_dir>/.cache/huggingface/download/<hash>.<etag>.incomplete

下完才 rename 成 `model.safetensors`。而进度条的分子此前只数"已经落定"的文件
(`*.incomplete` 被跳过),于是从开始到结束量到的都是同一批小文件 ——
686,760,772 B,也就是截图上的 687 MB / 15%。

**量法只有一份**(`tts_models.bytes_on_disk`),两种问法差一个参数:

  * 「装好了没有」必须排除没下完的 —— 半截权重照样会被算进体积,而加载时会炸;
  * 「下载到哪了」必须算上它们 —— 不然刻度根本不会动。

F5 那条路早就把整个目录都数上了(见 `f5_models._ByteWatcher._measure`),这里是把同一个
量法给到引擎权重这条路上,顺便把两份实现合成一份。
"""

from __future__ import annotations

from app.ai.runtime import f5_models, qwen_models, tts_models
from app.ai.runtime.download_state import DownloadProgress

_QWEN = next(engine for engine in tts_models.CATALOG if engine.id == qwen_models.ENGINE_ID)
_F5 = next(engine for engine in tts_models.CATALOG if engine.id == "f5-tts")


def _write(path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _qwen_root(tmp_path, monkeypatch):
    """把 Qwen 的托管权重目录换成临时目录 —— 测试碰真机上下好的那份就什么都证明不了。"""
    root = tmp_path / "qwen"
    root.mkdir()
    monkeypatch.setattr(qwen_models, "root", lambda: root)
    return root


def test_the_progress_measurement_counts_the_unfinished_blob(tmp_path, monkeypatch) -> None:
    """① 两种没下完的块都要算进**进度**:平铺的 `*.incomplete`,以及 HF 真正用的 `.cache/...` 那一层。"""
    model = _qwen_root(tmp_path, monkeypatch)
    _write(model / "config.json", 100)  # 已经落定的小文件
    _write(model / "model.safetensors.incomplete", 900)  # 平铺的残片(旧式命名)
    # HF 的 local_dir 模式:未完成的块在 <local_dir>/.cache/huggingface/download/ 下。
    _write(model / ".cache" / "huggingface" / "download" / "abc123.etag.incomplete", 500)

    assert tts_models._progress_bytes(model, _QWEN) == 1500


def test_installed_still_refuses_to_count_the_unfinished_blob(tmp_path, monkeypatch) -> None:
    """② 「进度」算它,「装好了没有」不算 —— 后者算错的后果比进度条不动严重得多。"""
    model = _qwen_root(tmp_path, monkeypatch)
    _write(model / "model.safetensors.incomplete", 900)
    _write(model / ".cache" / "huggingface" / "download" / "abc123.etag.incomplete", 500)

    # 它确实在往下走,所以进度要有数……
    assert tts_models._progress_bytes(model, _QWEN) == 1400
    # ……但半截权重不能加载,所以它还不是"装好了"。这一条**不因为改动而变绿**。
    assert tts_models._is_installed(_QWEN) is False


def test_the_install_volume_fallback_still_skips_them(tmp_path, monkeypatch) -> None:
    """②(续)走体积兜底的老目录也一样:判据里的"已经落定的字节"不含残片。

    这条是那道一票否决之外的又一层:体积兜底用的是 `_measure`,而它默认问的是"装好了没有"。
    """
    hub = tmp_path / "hub"
    cached = hub / _F5.cache_dirs[0]
    (cached / "blobs").mkdir(parents=True)
    _write(cached / "blobs" / "abc123.incomplete", 900)
    monkeypatch.setattr(tts_models, "_hf_roots", lambda: [hub])
    monkeypatch.setattr(tts_models, "_f5_model_dir", lambda: None)

    assert tts_models._measure(_F5) == 0
    assert tts_models._is_installed(_F5) is False


def test_the_bar_moves_while_the_main_file_is_still_incomplete(tmp_path, monkeypatch) -> None:
    """③ 会话推进:主文件从 0 长到 X,`downloaded_bytes` 和百分比都要跟着变。

    模拟的就是真机那一幕:主权重一直叫 `*.incomplete`,盘上的字节一直在长,而界面上两个数
    都取自同一个读数(见 `_status_dict` 的 downloading 分支)。
    """
    model = _qwen_root(tmp_path, monkeypatch)
    partial = model / ".cache" / "huggingface" / "download" / "ab12.etag.incomplete"
    partial.parent.mkdir(parents=True)
    monkeypatch.setattr(tts_models, "measured_total", lambda engine, source, blocking=False: (1000, False))

    readings: list[int] = []
    for size in (0, 250, 1000):
        partial.write_bytes(b"x" * size)
        readings.append(tts_models._progress_bytes(model, _QWEN))
    assert readings == [0, 250, 1000], f"主文件从 0 长到 1000,而盘上的读数:{readings}"

    percentages: list[int] = []
    for size in readings:
        tts_models._store.set(
            qwen_models.ENGINE_ID,
            DownloadProgress(status="downloading", downloaded=size, total=1000, message="dlMsg_downloading"),
        )
        row = tts_models.get_status(qwen_models.ENGINE_ID)
        percentages.append(round(row["downloaded_bytes"] / row["total_bytes"] * 100))
    assert percentages == [0, 25, 100], f"进度读数长了,而百分比没动:{percentages}"


def test_f5_progress_still_counts_everything_it_did_before(tmp_path, monkeypatch) -> None:
    """④ F5 的行为不变:它走的是 `hf_hub_download(local_dir=…)` + 自己的 `_ByteWatcher`,
    本来就数整棵目录。抽共用函数不许把它改小。"""
    language = f5_models._BY_ID["ja"]
    target = tmp_path / language.local_dir
    target.mkdir(parents=True)
    monkeypatch.setattr(f5_models, "root", lambda: tmp_path)
    _write(target / "model_21999120.pt", 100)
    _write(target / "abc.incomplete", 200)
    _write(target / ".cache" / "huggingface" / "download" / "def.etag.incomplete", 300)

    watcher = f5_models._ByteWatcher(language, language.id, {"message": "下载中"})
    assert watcher._measure() == 600, "F5 的进度一直是数整个目录的,这次改动把它改小了"


def test_there_is_only_one_size_walker() -> None:
    """一份实现。两份量法就是下一次"只改了一边"的来源 —— 这个 bug 本来就是这么来的。"""
    assert tts_models.bytes_on_disk is tts_models.bytes_on_disk

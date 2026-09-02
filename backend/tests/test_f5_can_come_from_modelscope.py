"""F5 的大文件也能走 ModelScope。

这台机器上实测:HuggingFace 和 hf-mirror 都是 46 KB/s,ModelScope ~9 MB/s。F5 的检查点
1.35 GB —— 走 HF 是八小时,走 ModelScope 是三分钟。

但 ModelScope 上**只有一半**:检查点和 vocab 在 `AI-ModelScope/F5-TTS`,而 F5 还要的
声码器 vocos(charactr/vocos-mel-24khz,约 55 MB)三个命名空间都查过,都是 404。

所以这条路是"大的走快路,小的还走 HF"。这不是遗憾 —— 55 MB 就算 46 KB/s 也就二十分钟,
而 1.35 GB 不走快路根本装不上。**选项要么真的改变什么,要么不该出现**(见
test_every_download_source_does_something):它改变了那 1.35 GB 的去处,所以它成立。
"""

from __future__ import annotations

from app.ai.runtime import tts_models


def test_modelscope_is_offered_for_f5_now() -> None:
    assert "modelscope" in tts_models.sources_for("f5-tts")


def test_the_repo_id_is_the_modelscope_one() -> None:
    """两边的仓库 id 不同名(fish 恰好同名,别把它当规律)。"""
    assert tts_models._BY_ID["f5-tts"].modelscope_repo == "AI-ModelScope/F5-TTS"


def test_the_worker_fetches_the_checkpoint_from_modelscope(monkeypatch, tmp_path) -> None:
    from app.ai.runtime.workers import tts as tts_worker
    grabbed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tts_worker, "_modelscope_file",
        lambda repo, path, local_dir: grabbed.append((repo, path)) or str(tmp_path / path),
    )
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "modelscope")
    monkeypatch.setenv("MOSAEL_F5_MODEL_DIR", str(tmp_path))

    tts_worker.fetch_f5_weights()

    assert ("AI-ModelScope/F5-TTS", tts_worker.F5_CHECKPOINT) in grabbed, grabbed
    assert ("AI-ModelScope/F5-TTS", tts_worker.F5_VOCAB) in grabbed, grabbed


def test_it_does_not_touch_modelscope_on_the_hf_path(monkeypatch, tmp_path) -> None:
    """选 HF 时就老老实实走 HF —— F5TTS 自己会拉,不该在这里抢着下一份。"""
    from app.ai.runtime.workers import tts as tts_worker
    called = []
    monkeypatch.setattr(tts_worker, "_modelscope_file", lambda *a, **k: called.append(a))
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "hf")
    monkeypatch.setenv("MOSAEL_F5_MODEL_DIR", str(tmp_path))

    tts_worker.fetch_f5_weights()

    assert called == []


def test_a_managed_checkpoint_counts_as_installed(tmp_path, monkeypatch) -> None:
    """下到我们自己的目录里,安装检测要认得 —— 否则页面会说"没下",而它就在盘上。"""
    weights = tmp_path / "f5"
    weights.mkdir()
    (weights / "model.safetensors").write_bytes(b"x" * 1_400_000_000)
    (weights / "vocab.txt").write_text("a\nb\n", encoding="utf-8")
    monkeypatch.setattr(tts_models, "_f5_model_dir", lambda: weights)

    assert tts_models._is_installed(tts_models._BY_ID["f5-tts"]) is True


def test_a_managed_dir_without_the_checkpoint_is_not_installed(tmp_path, monkeypatch) -> None:
    weights = tmp_path / "f5"
    weights.mkdir()
    (weights / "vocab.txt").write_text("a\n", encoding="utf-8")
    monkeypatch.setattr(tts_models, "_f5_model_dir", lambda: weights)
    monkeypatch.setattr(tts_models, "_hf_roots", lambda: [])

    assert tts_models._is_installed(tts_models._BY_ID["f5-tts"]) is False


def test_an_engine_offering_modelscope_can_actually_talk_to_it() -> None:
    """列了 ModelScope 这个源,venv 里就得有那个客户端。

    真机上撞到:F5 的依赖表里只有 `f5-tts`,而我给它开了 ModelScope 源 —— 于是拉权重时
    `ModuleNotFoundError: No module named 'modelscope'`。**声明了一种能力,却没带上它需要的
    东西**,和"探测查得比真实路径浅"是同一个形状:两处各说各的。
    """
    for engine in tts_models.CATALOG:
        if "modelscope" in tts_models.sources_for(engine.id):
            assert "modelscope" in engine.pip_requirements, (
                f"{engine.id} 列了 ModelScope 源,但它的运行环境里没有 modelscope 客户端"
            )

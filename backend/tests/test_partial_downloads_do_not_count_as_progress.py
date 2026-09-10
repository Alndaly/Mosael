"""下到一半的分片既不算进度,也要在日志里点名。

用户机器上的实际输出:

    判定:未装好
    量到 1,402,802,293 字节 / 需要 900,000,000(总量 1,500,000,000,估算)
    **有没下完的分片(*.incomplete)**

两行自相矛盾 —— 体积过线了却判未装好。真相是那 1.40 GB 里有一截是 `*.incomplete`:
HuggingFace 下到一半的 blob,既加载不了,也不代表进度已经到手。而"有残片就算没装好"
是一票否决,残片又不会自己消失,于是那个引擎会**永远**显示未装好,重下也不管用
(重下产生的是新 blob,老残片还在原地)。
"""

from __future__ import annotations

from pathlib import Path

from app.ai.runtime import tts_models


def _hub(tmp_path: Path, monkeypatch, name: str) -> Path:
    root = tmp_path / "hub"
    cached = root / name
    (cached / "blobs").mkdir(parents=True)
    monkeypatch.setattr(tts_models, "_hf_roots", lambda: [root])
    return cached


def test_半个分片不计入已下载的字节(tmp_path, monkeypatch) -> None:
    engine = next(e for e in tts_models.CATALOG if e.id == "f5-tts")
    cached = _hub(tmp_path, monkeypatch, engine.cache_dirs[0])
    (cached / "blobs" / "done.safetensors").write_bytes(b"x" * 100)
    (cached / "blobs" / "abc123.incomplete").write_bytes(b"x" * 900)

    # 900 个字节还躺在半路上,不能拿它充数 —— 这个数同时是进度条的分子和体积兜底的判据。
    assert tts_models._measure(engine) == 100


def test_日志点名是哪个残片(tmp_path, monkeypatch) -> None:
    engine = next(e for e in tts_models.CATALOG if e.id == "f5-tts")
    cached = _hub(tmp_path, monkeypatch, engine.cache_dirs[0])
    partial = cached / "blobs" / "abc123.incomplete"
    partial.write_bytes(b"x" * 12345)

    verdict = tts_models._install_verdict(engine)

    # 只说"有没下完的分片"的话,用户分不清是刚才那次还在下,还是上个月那次的尸体。
    assert str(partial) in verdict
    assert "12,345" in verdict
    # 而且要说下一步 —— 否则只会一遍遍重下。
    assert "不会被自动清理" in verdict


def test_没有残片时不提这件事(tmp_path, monkeypatch) -> None:
    engine = next(e for e in tts_models.CATALOG if e.id == "f5-tts")
    cached = _hub(tmp_path, monkeypatch, engine.cache_dirs[0])
    (cached / "blobs" / "done.safetensors").write_bytes(b"x" * 100)

    assert "没下完的分片" not in tts_models._install_verdict(engine)

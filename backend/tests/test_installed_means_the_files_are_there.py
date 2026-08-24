"""「已安装」要看**该有的文件在不在**,不是看体积够不够。

现场抓到的:Fish Speech 的第二个分片才下了三分之一,应用已经说它装好了 ——

    实测 8.20 GB / 阈值 6.60 GB(= 期望 11 GB × 0.6) → is_installed = True

判据是一个**比例**,而比例回答不了"能不能用":一个写了一半的 safetensors 照样计进总量。
后果不是数字难看 —— 是设置页写着「已安装,声音克隆可用」、配音面板放行、然后合成在加载
权重时炸,而错误信息指向的是模型文件损坏,没人会想到是"还没下完"。

转写那边踩过同一个坑的另一种形态(符号链接把体积翻倍,下到一半就够了阈值)。同一个根:
**拿体积猜状态。**

这个模型自己就带着答案:`model.safetensors.index.json` 里写着需要哪些分片,以及它们合起来
应该是多少字节(`metadata.total_size`)。照它核,是确定的,不需要联网,也不用再拍一个比例。
"""

from __future__ import annotations

import json

from app.ai.runtime import tts_models


def _fish_dir(root, *, shards: dict[str, int], total_size: int, codec: bool = True):
    """造一个 fish 权重目录:index 声明需要哪些分片、合起来多少字节。"""
    model = root / "fish-speech-s2-pro"
    model.mkdir(parents=True, exist_ok=True)
    if codec:
        (model / "codec.pth").write_bytes(b"x" * 1024)
    (model / "model.safetensors.index.json").write_text(
        json.dumps({
            "metadata": {"total_size": total_size},
            "weight_map": {f"t{i}": name for i, name in enumerate(shards)},
        }),
        encoding="utf-8",
    )
    for name, size in shards.items():
        (model / name).write_bytes(b"y" * size)
    return model


def test_a_half_written_shard_is_not_installed(tmp_path, monkeypatch) -> None:
    """用户机器上当时的形状:分片 1 完整,分片 2 只有三分之一。

    这里把"期望总量"调到很小,好让**体积判据说装好了** —— 否则这条测试在旧实现下也是绿的
    (合成目录才几 KB,连旧阈值都够不着),那就证明不了任何事。
    """
    import dataclasses

    model = _fish_dir(
        tmp_path,
        shards={"model-00001-of-00002.safetensors": 6000, "model-00002-of-00002.safetensors": 2000},
        total_size=12000,  # 应该是 6000 + 6000
    )
    monkeypatch.setattr(tts_models, "_fish_model_dir", lambda: model)
    tiny = dataclasses.replace(tts_models._BY_ID["fish-speech"], expected_bytes=1000)

    assert tts_models._measure(tiny) >= tiny.expected_bytes * 0.6, "体积判据在这里必须说'装好了'"
    assert tts_models._is_installed(tiny) is False


def test_all_shards_present_and_whole_is_installed(tmp_path, monkeypatch) -> None:
    model = _fish_dir(
        tmp_path,
        shards={"model-00001-of-00002.safetensors": 6000, "model-00002-of-00002.safetensors": 6000},
        total_size=12000,
    )
    monkeypatch.setattr(tts_models, "_fish_model_dir", lambda: model)

    assert tts_models._is_installed(tts_models._BY_ID["fish-speech"]) is True


def test_a_missing_shard_is_not_installed(tmp_path, monkeypatch) -> None:
    """清单里列了两个,盘上只有一个 —— 体积再大也不算。"""
    model = _fish_dir(
        tmp_path,
        shards={"model-00001-of-00002.safetensors": 12000},
        total_size=12000,
    )
    (model / "model.safetensors.index.json").write_text(
        json.dumps({
            "metadata": {"total_size": 12000},
            "weight_map": {"a": "model-00001-of-00002.safetensors", "b": "model-00002-of-00002.safetensors"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(tts_models, "_fish_model_dir", lambda: model)

    assert tts_models._is_installed(tts_models._BY_ID["fish-speech"]) is False


def test_a_missing_codec_is_not_installed(tmp_path, monkeypatch) -> None:
    """codec.pth 是合成时要加载的另一半,分片齐了也不算装好。"""
    model = _fish_dir(
        tmp_path,
        shards={"model-00001-of-00002.safetensors": 6000, "model-00002-of-00002.safetensors": 6000},
        total_size=12000,
        codec=False,
    )
    monkeypatch.setattr(tts_models, "_fish_model_dir", lambda: model)

    assert tts_models._is_installed(tts_models._BY_ID["fish-speech"]) is False


def test_no_index_falls_back_to_the_old_ratio(tmp_path, monkeypatch) -> None:
    """老目录(别的工具下的、没有 index)不能因为读不到清单就一律判成没装 ——
    读不到清单时退回原来的体积判据,而不是把已经能用的环境说成坏的。"""
    model = tmp_path / "legacy"
    model.mkdir()
    (model / "codec.pth").write_bytes(b"x" * 1024)
    (model / "weights.bin").write_bytes(b"y" * 8_000_000_000)
    monkeypatch.setattr(tts_models, "_fish_model_dir", lambda: model)

    assert tts_models._is_installed(tts_models._BY_ID["fish-speech"]) is True


def test_an_in_flight_hf_download_is_not_installed(tmp_path, monkeypatch) -> None:
    """F5 走 HuggingFace 缓存:下载中的 blob 叫 `*.incomplete`,它在就说明还没下完。

    此前只看体积:一个 1.4 GB 的检查点下到 60% 就过线了。
    """
    root = tmp_path / "hub"
    cache = root / "models--SWivid--F5-TTS" / "blobs"
    cache.mkdir(parents=True)
    (cache / "abc").write_bytes(b"y" * 1_400_000_000)
    (cache / "def.incomplete").write_bytes(b"z" * 1000)
    monkeypatch.setattr(tts_models, "_hf_roots", lambda: [root])

    assert tts_models._is_installed(tts_models._BY_ID["f5-tts"]) is False


def test_a_finished_hf_download_is_installed(tmp_path, monkeypatch) -> None:
    root = tmp_path / "hub"
    cache = root / "models--SWivid--F5-TTS" / "blobs"
    cache.mkdir(parents=True)
    (cache / "abc").write_bytes(b"y" * 1_400_000_000)
    monkeypatch.setattr(tts_models, "_hf_roots", lambda: [root])

    assert tts_models._is_installed(tts_models._BY_ID["f5-tts"]) is True

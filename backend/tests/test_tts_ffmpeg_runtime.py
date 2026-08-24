"""torchcodec 要的那份 FFmpeg。

torchaudio 2.9+ 只有 torchcodec 一个解码后端,而 torchcodec 带的是**按 FFmpeg 大版本编译**的
一组 dylib(core4…core9),0.16 起还不带 rpath —— dlopen 自己找不到 libavutil,必须由外部
给库搜索路径。表现是:ffmpeg 装得好好的、版本也对得上,合成照样报「语音合成失败」。

这里钉住两条判据,它们都是被真机打脸之后才写对的:

1. **按盘上实际有哪几个 coreN 推**,不写死支持表 —— torchcodec 每升一版就多支持一个 FFmpeg。
2. **版本看 libavutil,不看 formula 名字** —— 这台机器上 `ffmpeg@8` 里装的是 libavutil.61。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.runtime import tts_models


def _fake_venv(tmp_path: Path, cores: list[int]) -> str:
    site = tmp_path / "venv" / "lib" / "python3.13" / "site-packages" / "torchcodec"
    site.mkdir(parents=True)
    for core in cores:
        (site / f"libtorchcodec_core{core}.dylib").write_text("")
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("")
    return str(python)


def test_supported_avutil_majors_come_from_what_is_on_disk(tmp_path: Path) -> None:
    assert tts_models._torchcodec_avutil_majors(_fake_venv(tmp_path, [4, 7, 9])) == (61, 59, 56)


def test_no_torchcodec_means_nothing_to_inject(tmp_path: Path) -> None:
    """没装 torchcodec(或换了别的后端)就不该注入任何库路径 —— 那只会给别的库添乱。"""
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    assert tts_models._torchcodec_avutil_majors(str(python)) == ()
    assert tts_models._ffmpeg_runtime_dir(str(python)) == ""


def test_picks_by_libavutil_not_by_formula_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`ffmpeg@8` 里装着 libavutil.61 —— 名字是包管理器的说法,dlopen 认的是 libavutil。

    只按名字挑的话会选中 `ffmpeg@8` 然后照样加载失败(真机上就是这么错了一轮)。
    """
    monkeypatch.setattr(tts_models.sys, "platform", "darwin")
    prefix = tmp_path / "opt"
    # 名字是 @8,里面却是 61;真正配 core8(要 60)的是那个叫 @7 的。
    for name, major in (("ffmpeg@8", 61), ("ffmpeg@7", 60)):
        lib = prefix / name / "lib"
        lib.mkdir(parents=True)
        (lib / f"libavutil.{major}.dylib").write_text("")
    monkeypatch.setattr(tts_models, "_ffmpeg_lib_roots", lambda: [prefix])

    python = _fake_venv(tmp_path, [7, 8])  # 支持 libavutil 59 与 60
    picked = tts_models._ffmpeg_runtime_dir(python)
    assert picked.endswith("ffmpeg@7/lib"), picked

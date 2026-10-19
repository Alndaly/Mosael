"""从链接导入的三道闸:大小上限、总超时、落地文件头嗅探。

这三条此前一条都没有。它们不会让什么立刻坏掉,而是让「粘贴一个链接」变成一种可以把
这台机器拖住 / 塞满 / 收下一份 HTML 当视频 的操作:

- **大小上限**:浏览器下载那条路有 2 GiB、截图有 40 MiB,而 yt-dlp 这条路什么都没有 ——
  一个几小时的播放列表能把素材盘写满才停。
- **总超时**:`DOWNLOAD_TIMEOUT_SECONDS` 定义了却没人用。socket 超时只管「一块数据多久没来」,
  一个一直有数据、但永远下不完的流可以走一整天。
- **文件头嗅探**:此前只看后缀和 ffprobe。一个伪装成 `.mp4` 的 HTML 页面会被当视频收下。

测的都是假 yt-dlp(打桩,不连外网),钉住的是**我们这一侧**的判定。
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest
from yt_dlp import utils as ytdlp_utils

from app.core.i18n import t
from app.media import ytdlp

#: 一个真的 mp4 文件头(ftyp box + isom brand)。只有文件头说明不了什么,但这道闸判的就是文件头。
MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"
#: 一个真的 mp3 帧头。音频那条路照常收。
MP3_HEAD = b"ID3\x04\x00\x00\x00\x00\x00\x00"


def _fake_ydl(monkeypatch: pytest.MonkeyPatch, behaviour: Any) -> dict[str, Any]:
    """把 `yt-dlp.YoutubeDL` 换成一个按 `behaviour(options, target_dir)` 干活的壳。

    返回随手记下的 options —— 闸有没有真的交给 yt-dlp,也要看得见。
    """
    seen: dict[str, Any] = {}

    class FakeYDL:
        def __init__(self, options: dict[str, Any], auto_init: bool = True) -> None:
            seen.clear()
            seen.update(options)

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def add_info_extractor(self, extractor):
            pass

        def add_default_info_extractors(self):
            pass

        def extract_info(self, url: str, download: bool = True) -> dict[str, Any]:
            info = behaviour(seen, url)
            return info if isinstance(info, dict) else {"title": "clip", "id": "x", "ext": "mp4"}

        def prepare_filename(self, info: dict[str, Any]) -> str:
            title = str(info.get("title") or "clip")
            return str(Path(seen["outtmpl"]).parent / f"{title} [{info.get('id') or 'x'}].{info.get('ext') or 'mp4'}")

    #: 换的是 **sys.modules 里那个模块**:`download()` 每次调用都 `import yt_dlp`,
    #: 只改我们手里这个模块对象的话,别的测试 pop 过 sys.modules 之后它会重新加载一份没打桩的。
    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL  # type: ignore[attr-defined]
    fake.utils = ytdlp_utils  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    return seen


def _hook(options: dict[str, Any]):
    return options["progress_hooks"][0]


# ---------------- ① 文件大小上限 ----------------


def test_超过上限的文件当场拒并说清(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """假 yt-dlp 报一个 2 GiB 以上的文件:改之前照下,改之后第一次进度回调就停。

    判据是**上限真的交给了 yt-dlp**(`max_filesize`),而且我们在它之前就拦下来 —— 不是等
    几个 GB 落到盘上再说。
    """

    def behaviour(options, _url):
        # yt-dlp 的进度回调就长这样:总数先到,字节还没开始下。
        _hook(options)({
            "status": "downloading",
            "total_bytes": 2_147_483_648 + 1,
            "downloaded_bytes": 0,
        })
        path = Path(options["outtmpl"]).parent / "clip [x].mp4"
        path.write_bytes(MP4_HEAD + b"\x00" * 128)
        return {"title": "clip", "id": "x", "ext": "mp4"}

    seen = _fake_ydl(monkeypatch, behaviour)
    with pytest.raises(ytdlp.YtdlpError) as caught:
        ytdlp.download("https://example.com/v", kind="video", target_dir=tmp_path)

    assert caught.value.key == "urlImportErr_tooLarge"
    assert "太大" in str(caught.value)
    assert "too large" in t(caught.value.key, "en", **caught.value.params)
    assert seen["max_filesize"] == ytdlp.MAX_DOWNLOAD_BYTES, "上限要交给 yt-dlp,别只在事后量一遍"


def test_yt_dlp_自己因过大放弃_也要说清(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """HTTP 下载器发现 Content-Length 超限时**不抛异常**,只打印一句就返回 —— 不能落成「没找到文件」。"""

    def behaviour(options, _url):
        #: 它走的是 YoutubeDL.to_screen:传了 logger 之后进我们手里。
        options["logger"].debug(
            "[download] File is larger than max-filesize (3000000000 bytes > 2147483648 bytes). Aborting.",
        )
        return {"title": "clip", "id": "x", "ext": "mp4"}

    _fake_ydl(monkeypatch, behaviour)
    with pytest.raises(ytdlp.YtdlpError) as caught:
        ytdlp.download("https://example.com/v", kind="video", target_dir=tmp_path)
    assert caught.value.key == "urlImportErr_tooLarge"


# ---------------- ② 总超时 ----------------


def test_总超时到点就停_不是每块_socket_超时(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """假下载一直有进度、却永远下不完:改之前会一直走到假壳自己放弃,改之后到 deadline 就停。

    `socket_timeout` 只管「多久没收到字节」;这条钉的是**整次下载的总时限**。
    """
    monkeypatch.setattr(ytdlp, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)

    beats = 0

    def behaviour(options, _url):
        nonlocal beats
        hook = _hook(options)
        # 一直有数据进来 —— socket 永远不会超时。一直没有 deadline 的话,这个循环会自己数到
        # 上限然后让测试失败(不量挂钟,见 tests_wait_for_events_not_time)。
        while beats < 1_000:
            beats += 1
            hook({"status": "downloading", "total_bytes": 100_000, "downloaded_bytes": 1})
            time.sleep(0.01)
        raise AssertionError("总时限没有生效:假下载一直有进度,却一直没被叫停")

    _fake_ydl(monkeypatch, behaviour)
    with pytest.raises(ytdlp.YtdlpError) as caught:
        ytdlp.download("https://example.com/v", kind="video", target_dir=tmp_path)

    assert caught.value.key == "urlImportErr_timeout"
    assert "超时" in str(caught.value) or "时限" in str(caught.value)
    assert "deadline" in t(caught.value.key, "en", **caught.value.params).lower()
    assert beats < 1_000, "循环跑满了上限,说明 deadline 没拦住它"


def test_用户取消不算超时也不算失败(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """取消仍然抛 `YtdlpCancelled`,不会被总时限那条路改说成「超时失败」。"""

    def behaviour(options, _url):
        _hook(options)({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 1})
        return {"title": "clip", "id": "x", "ext": "mp4"}

    _fake_ydl(monkeypatch, behaviour)
    with pytest.raises(ytdlp.YtdlpCancelled):
        ytdlp.download("https://example.com/v", kind="video", target_dir=tmp_path, should_stop=lambda: True)


# ---------------- ③ 落地文件头嗅探 ----------------


def _download_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes, *, ext: str = "mp4"):
    def behaviour(options, _url):
        path = Path(options["outtmpl"]).parent / f"clip [x].{ext}"
        path.write_bytes(payload)
        return {"title": "clip", "id": "x", "ext": ext}

    _fake_ydl(monkeypatch, behaviour)
    return ytdlp.download("https://example.com/v", kind="audio" if ext == "mp3" else "video", target_dir=tmp_path)


def test_伪装成_mp4_的_HTML_不收(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """后缀叫 .mp4、内容是一张网页:改之前照收,改之后按文件头拒。"""
    with pytest.raises(ytdlp.YtdlpError) as caught:
        _download_bytes(monkeypatch, tmp_path, b"<!doctype html><html><body>not a video</body></html>")
    assert caught.value.key == "urlImportErr_notMedia"
    assert "不是视频" in str(caught.value) or "不是媒体" in str(caught.value)
    assert "isn't video" in t(caught.value.key, "en", **caught.value.params) or "not video" in t(
        caught.value.key, "en", **caught.value.params
    ).lower()
    # 拒掉的那份不该留在暂存目录里冒充「下好的文件」。
    assert list(tmp_path.glob("*.mp4")) == []


def test_真的_mp4_照常收(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = _download_bytes(monkeypatch, tmp_path, MP4_HEAD + b"\x00" * 32)
    assert path.is_file() and path.suffix == ".mp4"


def test_真的_mp3_照常收(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = _download_bytes(monkeypatch, tmp_path, MP3_HEAD + b"\x00" * 32, ext="mp3")
    assert path.is_file() and path.suffix == ".mp3"


def test_看不出是什么就不收(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """不是 HTML、也不是认得的媒体容器:同样拒 —— 白名单,不是黑名单。"""
    with pytest.raises(ytdlp.YtdlpError) as caught:
        _download_bytes(monkeypatch, tmp_path, b"\x00\x00\x00\x00 definitely-not-media")
    assert caught.value.key == "urlImportErr_notMedia"

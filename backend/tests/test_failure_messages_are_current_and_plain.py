"""界面上那句失败原因,要是**纯文本**,而且要描述**现在**的配置。

用户截图里那一行:

    连不上模型下载源(https://hf-mirror.com): [1;35mhuggingface_hub.errors.LocalEntryNotFoundError
    [0m: [35mAn error happened while trying to locate the file on the Hub … Please check you
    —— 在上面的「模型下载源」换一个…再重试。

两个毛病:

1. **`[1;35m` 这些是 ANSI 颜色码。** 子进程(rich / huggingface_hub 的彩色 traceback)以为
   自己在终端里,而这段文字的去处是浏览器 —— 于是转义序列被原样画了出来。凡是把子进程输出
   端到界面上的地方都有这个问题,不只这一处。

2. **它说的是 hf-mirror,而用户已经把源切成 ModelScope 了。** 这条消息是失败当时存进内存的,
   配置改了它不会变;可它长得像"当前状态",于是用户按它去排查一个已经不存在的设置。
   失败消息描述的是一次**过去的尝试**,而它所依据的前提一旦被改掉,它就该消失。

(顺带:`[:200]` 把句子截在 "Please check you",少一个 r —— 截断要发生在句子边界之外。)
"""

from __future__ import annotations

from app.ai.runtime import tts_models
from app.core.text import strip_ansi


def test_ansi_colour_codes_never_reach_the_message() -> None:
    coloured = (
        "Traceback (most recent call last):\n"
        "\x1b[1;35mhuggingface_hub.errors.LocalEntryNotFoundError\x1b[0m: "
        "\x1b[35mAn error happened while trying to locate the file on the Hub\x1b[0m"
    )

    message = tts_models._explain_failure(coloured)

    assert "\x1b" not in message, f"转义序列进了界面:{message!r}"
    assert "[1;35m" not in message and "[0m" not in message, f"颜色码被当成文字画出来了:{message}"
    assert "LocalEntryNotFoundError" in message


def test_strip_ansi_leaves_ordinary_text_alone() -> None:
    assert strip_ansi("没有颜色码的一句话") == "没有颜色码的一句话"
    assert strip_ansi("") == ""


def test_changing_the_download_source_drops_the_stale_failure() -> None:
    """换了源,上一次失败就不再描述"现在" —— 它得让位,而不是继续挂在卡片上。"""
    tts_models._store.set(
        "f5-tts",
        tts_models._Live(status="failed", message="连不上模型下载源(https://hf-mirror.com):…"),
    )

    tts_models.forget_failures()

    live = tts_models._store.get("f5-tts")
    assert live is None or live.status != "failed", "旧的失败还挂着,而它说的那个源已经被换掉了"


def test_forgetting_failures_does_not_kill_a_running_download() -> None:
    """只丢掉失败。正在下的那条要是被清了,界面会以为它停了。"""
    tts_models._store.set("fish-speech", tts_models._Live(status="downloading", message="下载中"))
    try:
        tts_models.forget_failures()
        live = tts_models._store.get("fish-speech")
        assert live is not None and live.status == "downloading"
    finally:
        tts_models._store.clear("fish-speech")


def test_the_hint_survives_a_long_error() -> None:
    """截断不能把那句"去哪改"吃掉 —— 那是整条消息里唯一能行动的部分。"""
    long_error = "x" * 5000 + "\nLocalEntryNotFoundError: check your connection"

    message = tts_models._explain_failure(long_error)

    assert "模型下载源" in message, f"能行动的那半句被截没了:{message[-120:]}"


def test_saving_the_settings_page_drops_it(monkeypatch) -> None:
    """判据要挂在**用户做的那个动作**上:他改的是设置页,不是某个函数。

    只测 `forget_failures()` 本身的话,把路由里那一行删掉照样全绿 —— 而界面上那句过时的话
    就又回来了。
    """
    from tests.util import fresh_client

    client = fresh_client()
    tts_models._store.set(
        "f5-tts",
        tts_models._Live(status="failed", message="连不上模型下载源(https://hf-mirror.com):…"),
    )

    saved = client.put(
        "/api/settings/tts",
        json={"engine": "f5-tts", "python_path": "", "source": "modelscope",
              "pip_index": "", "fish_repo_dir": "", "fish_model_dir": ""},
    )
    assert saved.status_code == 200, saved.text

    row = next(item for item in client.get("/api/tts/models").json() if item["id"] == "f5-tts")
    assert row["status"] != "failed", f"换了源,卡片还挂着按旧源写的失败:{row['message']}"
    assert "hf-mirror" not in row["message"]

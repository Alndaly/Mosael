"""下载失败卡上那句话:主句说人话,原文留在「详情」,指路指到真能改的地方。

维护者截图(剪辑 → 配音,F5 语言包下载失败,卡片只有两行):

    连不上模型下载源(https://hf-mirror.com):LocalEntryNotFoundError: An error occurred while trying
    to locate the file on the Hub…(截断) —— 在上面的「下载源」换一个…再重试。

两个毛病:

① 第三方库的英文原文被拼进了**主句**。卡片只有两行,一截就只剩「An error…」—— 人话和能行动
   的那半句都被挤掉了。原文该留在「详情」里:用户排查时看得到,但不占主句。
② 「上面的『下载源』」在这张卡片所在的 tab 里**不存在**。模型下载源只有一个地方能改:
   「管理 → 引擎 → 下载源」的「模型下载源」一行(要部署管理员;而这张卡片的下载按钮本来也
   只给部署管理员)。文案不许写「上面」这种相对位置 —— 从这张卡片的视角它不在那儿。

这里钉住:主句是中文人话、地址还在、原文仍在请求的那一行(`error`,界面的「详情」读它),
指到的设置路径真的存在,并且文案里建议的每个动作都落在一个真实存在的东西上。
"""

from __future__ import annotations

import pathlib

from app.ai.runtime import f5_models
from app.ai.runtime.download_state import DownloadProgress
from app.core.i18n import render_message

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
MESSAGES = FRONTEND / "app" / "messages"

#: 截图里那段第三方库的原文(界面只看得见前两行)。
RAW = (
    "huggingface_hub.errors.LocalEntryNotFoundError: An error occurred while trying to locate the "
    "file on the Hub and we cannot find the requested files in the local cache. Please check your connection"
)
HUB_PARAMS = {"endpoint": "https://hf-mirror.com", "detail": RAW}


def _zh_messages(name: str) -> str:
    return (MESSAGES / "zh-CN" / name).read_text(encoding="utf-8")


def _en_messages(name: str) -> str:
    return (MESSAGES / "en-US" / name).read_text(encoding="utf-8")


# -- ① 主句人话、原文不进主句 --------------------------------------------------------------

def test_the_headline_is_plain_and_keeps_the_address() -> None:
    shown = render_message("runtimeErr_hubUnreachable", "zh", HUB_PARAMS)

    assert "LocalEntryNotFoundError" not in shown, f"第三方库的英文异常又进了主句:{shown}"
    assert "An error occurred" not in shown, f"第三方库的英文异常又进了主句:{shown}"
    assert "hf-mirror.com" in shown, f"地址丢了 —— 它是排查时唯一有效的信息:{shown}"


def test_the_english_card_does_not_lead_with_the_raw_exception_either() -> None:
    shown = render_message("runtimeErr_hubUnreachable", "en", HUB_PARAMS)

    assert "LocalEntryNotFoundError" not in shown, f"第三方库的英文异常进了英文主句:{shown}"
    assert "An error occurred" not in shown, f"第三方库的英文异常进了英文主句:{shown}"
    assert "hf-mirror.com" in shown, f"地址丢了:{shown}"
    assert "above" not in shown.lower(), f"英文里同样不许说 above —— 那张卡片上方没有这个设置:{shown}"


# -- ② 下一步:指到真的能改的地方,不许写「上面」 -------------------------------------------

def test_the_next_step_points_at_the_admin_setting_not_somewhere_above() -> None:
    shown = render_message("runtimeErr_hubUnreachable", "zh", HUB_PARAMS)

    assert "上面的" not in shown, f"这张卡片所在的 tab 里没有「上面的」什么东西:{shown}"
    assert "管理 → 引擎 → 下载源" in shown, f"没说清去哪儿换源:{shown}"
    assert "模型下载源" in shown, f"没说清换哪一行(下载源那一节有好几行):{shown}"
    assert "重试" in shown, f"没说出这张卡片上真有的动作:{shown}"


def test_the_settings_path_it_names_really_exists() -> None:
    """路径和控件都得真在界面上 —— 否则又是一次「指到不存在的地方」。"""
    zh_shell = _zh_messages("shell.ts")
    zh_ai = _zh_messages("aiStudio.ts")

    #: 管理 / 引擎 / 下载源 / 模型下载源 / 重试:文案里出现的每个词都得是界面上真有的那一处。
    for label, text in (
        ('navAdmin: "管理"', zh_shell),
        ('adminTabEngines: "引擎"', zh_shell),
        ('installSourceTitle: "下载源"', zh_ai),
        ('voiceCloneSource: "模型下载源"', zh_ai),
        ('retry: "重试"', zh_ai),
    ):
        assert label in text, f"文案指到的「{label}」在界面上不存在"

    shown = render_message("runtimeErr_hubUnreachable", "zh", HUB_PARAMS)
    for part in ("管理", "引擎", "下载源", "模型下载源", "重试"):
        assert part in shown, f"文案里的「{part}」没出现在这句话里:{shown}"


def test_the_retry_it_points_at_is_the_button_on_that_card() -> None:
    """文案说「再点『重试』」—— 那颗按钮得真在配音面板的失败卡里,并且真的重新发起下载。"""
    editor = (FRONTEND / "features" / "editor" / "SubtitleDub.tsx").read_text(encoding="utf-8")

    assert 't("retry")' in editor, "文案让点「重试」,这张卡里却没有这颗按钮"
    assert "onClick={onDownload}" in editor, "「重试」按钮没接回下载动作"


def test_the_source_can_actually_be_switched_through_the_settings_api() -> None:
    """那个下拉不是摆设:模型下载源真能换,而且换的选项由后端给。"""
    from tests.util import fresh_client

    row = fresh_client().get("/api/settings/install-source").json()

    assert "model_source" in row, f"设置里没有模型下载源这一项:{row}"
    assert {"hf", "hf-mirror", "modelscope"} <= set(row.get("model_sources") or []), row


# -- ④ 原文留在「详情」:请求里的 error 字段 ------------------------------------------------

def test_the_raw_exception_is_kept_for_the_details_view() -> None:
    message, params, error = f5_models._failure_from(RuntimeError(RAW))

    assert message == "runtimeErr_hubUnreachable", message
    assert params["endpoint"].endswith("hf-mirror.com"), params
    assert "LocalEntryNotFoundError" in error, "原文被扔了 —— 用户想排查时什么都没得看"
    assert "LocalEntryNotFoundError" not in render_message(message, "zh", params), (
        "原文该在「详情」(error)里,不该再回主句"
    )


def test_the_failed_row_carries_the_raw_exception_but_the_message_does_not() -> None:
    """界面那张卡读的是这一行:message 给主句,error 给详情。"""
    from tests.util import fresh_client

    f5_models._store.set(
        "ja",
        DownloadProgress(
            status="failed",
            message="runtimeErr_hubUnreachable",
            params=HUB_PARAMS,
            error=RAW,
        ),
    )
    try:
        row = next(item for item in fresh_client().get("/api/tts/f5-models").json() if item["id"] == "ja")
    finally:
        f5_models._store.clear("ja")

    assert "LocalEntryNotFoundError" in row["error"], "详情里没有原文"
    assert "LocalEntryNotFoundError" not in row["message"], f"原文还在主句里:{row['message']}"
    assert "hf-mirror.com" in row["message"]


# -- ⑤ 同类条目:Log 变体、F5 自己的失败、F5 运行环境 --------------------------------

def test_the_log_variant_says_the_same_thing() -> None:
    shown = render_message(
        "runtimeErr_hubUnreachableLog",
        "zh",
        {**HUB_PARAMS, "log": "/tmp/mosael-download.log"},
    )

    assert "LocalEntryNotFoundError" not in shown, f"日志变体又把原文拼进了主句:{shown}"
    assert "An error occurred" not in shown
    assert "上面的" not in shown, f"日志变体还指着不存在的地方:{shown}"
    assert "管理 → 引擎 → 下载源" in shown
    assert "hf-mirror.com" in shown
    assert "/tmp/mosael-download.log" in shown, f"日志路径丢了,排查时找不到全文:{shown}"


def test_other_f5_failures_do_not_lead_with_the_raw_exception_either() -> None:
    shown = render_message(
        "runtimeErr_f5DownloadFailed",
        "zh",
        {"detail": "OSError: [Errno 28] No space left on device"},
    )

    assert "OSError" not in shown, f"F5 的通用失败也把原文放进了主句:{shown}"
    assert "上面的" not in shown
    assert "重试" in shown, f"没给用户能做的事:{shown}"


def test_f5_runtime_missing_points_at_the_voice_cloning_section() -> None:
    """这条本来就指对了 —— 一并钉住,免得下次改文案又漂走。"""
    shown = render_message("runtimeErr_f5RuntimeMissing", "zh")
    zh_ai = _zh_messages("aiStudio.ts")

    assert '"声音克隆"' in zh_ai and 'voiceCloneTitle: "声音克隆"' in zh_ai
    assert "上面的" not in shown, f"改文案又漂成相对位置了:{shown}"
    assert "管理 → 引擎 → 声音克隆" in shown


def test_the_other_f5_statuses_do_not_point_at_a_ghost_setting() -> None:
    for key in (
        "runtimeErr_f5DownloadInterrupted",
        "runtimeErr_f5LanguageBusy",
        "runtimeErr_downloadNoReason",
    ):
        shown = render_message(key, "zh")
        assert "上面的" not in shown, f"{key} 指着不存在的地方:{shown}"

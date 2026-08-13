"""后端自己的多语言。

**为什么后端要做,而不是"发 key 让前端翻"**:后端这些文案的消费者不止前端 —— 智能体的工具
返回、飞书机器人推的消息、任务中心的通知标题,都不经过前端的 messages.ts。发 key 会让它们
显示成一串 `publishOpt_visibility`。

而它是**多租户、可远程部署**的:没有"服务端语言"这回事,每个请求都得拿到自己的那一种,
所以语言从 Accept-Language 来,不是从某个全局配置来。
"""

from __future__ import annotations

import re

import pytest

from app.core.i18n import DEFAULT_LOCALE, LOCALES, MESSAGES, normalize_locale, t
from app.domain.publish import PUBLISH_PLATFORMS, option_specs
from tests.util import fresh_client

CJK = re.compile(r"[一-鿿]")


def test_every_key_has_every_locale() -> None:
    """缺一种语言就是一处会掉回中文的地方 —— 而它在界面上看起来"就是没翻",查起来很费劲。"""
    missing = {
        key: [loc for loc in LOCALES if not entry.get(loc)]
        for key, entry in MESSAGES.items()
        if any(not entry.get(loc) for loc in LOCALES)
    }
    assert missing == {}


def test_asr_tts_catalogs_store_keys_not_prose() -> None:
    """ASR / TTS 引擎目录、TTS 供应商目录同样是**给人看的文案**,同样该存 key。

    这一条把扫描范围从发布平台扩到它们仨。范围就是待迁清单 —— 与其在别处记一份"还有哪些没迁",
    不如让棘轮自己说,它不会忘也不会过期。
    """
    from app.audio import asr_models, tts_models, tts_providers

    offenders: list[str] = []
    for entry in asr_models.CATALOG:
        for field in ("label", "detail"):
            if CJK.search(str(getattr(entry, field, "") or "")):
                offenders.append(f"asr:{entry.id}.{field}")
    for entry in tts_models.CATALOG:
        for field in ("label", "detail"):
            if CJK.search(str(getattr(entry, field, "") or "")):
                offenders.append(f"tts:{entry.id}.{field}")
    for provider in tts_providers.describe_engines():
        for field in ("label", "note"):
            if CJK.search(str(provider.get(field) or "")):
                offenders.append(f"provider:{provider['id']}.{field}")
    assert offenders == []


def test_catalog_stores_keys_not_prose() -> None:
    """目录里存 key、出口才翻。**这里出现中文就说明有人又直接写了文案** —— 那条从此不会被翻译,
    而且没有任何东西会提示他。"""
    offenders: list[str] = []
    for platform, meta in PUBLISH_PLATFORMS.items():
        if CJK.search(meta["description"]):
            offenders.append(f"{platform}.description")
        for spec in option_specs(platform):
            for field in ("label", "description"):
                if CJK.search(str(spec.get(field) or "")):
                    offenders.append(f"{platform}.{spec['key']}.{field}")
            for choice in spec.get("choices", []):
                if CJK.search(choice["label"]):
                    offenders.append(f"{platform}.{spec['key']}.{choice['value']}")
    assert offenders == []


def test_every_catalog_key_is_translatable() -> None:
    """目录里写的 key 必须在 MESSAGES 里 —— 拼错了 t() 会原样返回它,界面上就是一串 key。"""
    unknown: list[str] = []
    for platform, meta in PUBLISH_PLATFORMS.items():
        for key in [meta["description"], *(s["label"] for s in option_specs(platform))]:
            if key not in MESSAGES:
                unknown.append(key)
    assert unknown == []


@pytest.mark.parametrize(
    ("header", "expected"),
    [("zh-CN,zh;q=0.9", "zh"), ("en-US,en;q=0.9", "en"), ("ja", DEFAULT_LOCALE), (None, DEFAULT_LOCALE)],
)
def test_locale_from_header(header: str | None, expected: str) -> None:
    """只取主语言标签;不认的回落到缺省 —— **不猜**,给缺省至少是一致的。"""
    assert normalize_locale(header) == expected


def test_unknown_key_returns_itself_instead_of_raising() -> None:
    """缺一条翻译不该让整个接口 500:它会以 key 的样子出现在界面上 —— 难看,但看得见。"""
    assert t("nope_not_a_key", "en") == "nope_not_a_key"


def test_platforms_endpoint_speaks_the_caller_language() -> None:
    client = fresh_client()
    seen = {}
    for header, locale in (("zh-CN", "zh"), ("en-US", "en")):
        rows = client.get("/api/publish/platforms", headers={"Accept-Language": header}).json()
        youtube = next(row for row in rows if row["platform"] == "youtube")
        visibility = youtube["options"][0]
        seen[locale] = (visibility["label"], [c["label"] for c in visibility["choices"]])
        # 出口翻完了就不该再有 key 的样子
        assert not visibility["label"].startswith("publishOpt_")
    assert seen["zh"] == ("可见性", ["私享(仅自己)", "不公开列出(有链接可看)", "公开"])
    assert seen["en"] == ("Visibility", ["Private (only you)", "Unlisted (anyone with the link)", "Public"])


def test_engine_catalogs_speak_the_caller_language() -> None:
    """转写模型 / 声音克隆引擎 / 语音引擎三个目录也随请求语言走。

    它们是**同一个机制的第二、三、四个落点** —— 存 key、出口翻译。这条用例盯的是"出口那一步
    有没有真的接上":目录改成 key 之后如果忘了在路由里翻,界面上就会直接显示 `asrDetail_...`。
    """
    client = fresh_client()
    zh = client.get("/api/asr/models", headers={"Accept-Language": "zh-CN"}).json()
    en = client.get("/api/asr/models", headers={"Accept-Language": "en-US"}).json()
    small_zh = next(row for row in zh if row["id"] == "whisperx-small")
    small_en = next(row for row in en if row["id"] == "whisperx-small")
    assert small_zh["detail"] == "多语种,速度与精度均衡(默认)"
    assert small_en["detail"] == "Multilingual; balanced speed and accuracy (default)"

    engines_en = client.get("/api/tts/engines", headers={"Accept-Language": "en"}).json()
    clone = next(row for row in engines_en if row["id"] == "clone")
    assert clone["label"] == "Local voice clone"
    # 翻过之后不该再有 key 的样子 —— 忘了接出口翻译正是这个形状。
    assert not any(str(row.get("label", "")).startswith("ttsProvider_") for row in engines_en)

    models_en = client.get("/api/tts/models", headers={"Accept-Language": "en"}).json()
    assert not any(str(row.get("detail", "")).startswith("ttsDetail_") for row in models_en)


def test_status_messages_are_translated_too() -> None:
    """状态句(「已安装,声音克隆可用」「正在检查运行环境…」)也随语言走。

    它们和目录不同:是按分支**拼**出来的,而不是查表 —— 所以迁移时最容易漏掉出口那一步,
    漏了界面上就直接显示 `modelMsg_cloneReady`。这条盯的就是它。

    下载过程中那些**动态**进度句(「安装 X 运行依赖…」)还没迁:它们带插值,形状是 key + 参数,
    不是一个 key 能表达的。它们只在下载时一闪而过,现状是中文,行为未变。
    """
    client = fresh_client()
    for path in ("/api/asr/models", "/api/tts/models"):
        rows = client.get(path, headers={"Accept-Language": "en"}).json()
        keyish = [row["message"] for row in rows if str(row.get("message", "")).startswith("modelMsg_")]
        assert keyish == [], f"{path} 漏了出口翻译:{keyish}"
        assert not any(CJK.search(str(row.get("message") or "")) for row in rows), f"{path} 英文请求里还有中文"

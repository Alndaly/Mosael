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

"""站点契约数据(`contracts/platform-contracts.json`)必须与后端、与真机核对的数字**一致**。

为什么要有这份数据:适配器里的选择器/文案散在 TS 里,平台改版的信号只有一个 —— 某次真发布失败,
而且失败长得很像成功(「上传完成但按钮点不动」)。把「这个站长什么样、各家上限多少」写成数据之后:

  · `scripts/platform-smoke.cjs` 能每天用**不登录**的浏览器确认「站还认得出来」;
  · 这里的测试确认「数据与后端声明、与 ADR 0076 的核对结果」没有悄悄漂开 —— 漂了不会有报错,
    只会在某一版突然多发一个被平台服务端拒掉的长标题。

这条测试是一道**棘轮**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.publish import PUBLISH_PLATFORMS

RATCHET = True

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "platform-contracts.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_every_publish_platform_has_a_site_contract(contract: dict) -> None:
    """后端认的平台 == 契约里有的平台。少一个,那个平台就没有冒烟、没有上限。"""
    declared = set(contract["platforms"])
    supported = set(PUBLISH_PLATFORMS)
    assert declared == supported, f"契约与后端平台对不上:多在契约 {declared - supported},缺在契约 {supported - declared}"


def test_the_smoke_case_can_actually_fail() -> None:
    """冒烟断言不能是恒真的:每条至少要有 textAny 或 urlAny,且 url 必须是 https。"""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for platform, value in contract["platforms"].items():
        smoke = value["smoke"]
        assert smoke["url"].startswith("https://"), f"{platform}: 冒烟地址必须是 https"
        assert smoke.get("textAny") or smoke.get("urlAny"), f"{platform}: 没有任何断言,这条冒烟永远不会红"


def test_title_limits_match_the_backend(contract: dict) -> None:
    """标题上限只能有一份事实:平台侧超长会让任务在服务端晚失败,而界面按后端那份拦。"""
    for platform, value in contract["platforms"].items():
        backend_max = int(PUBLISH_PLATFORMS[platform]["title_max"])
        assert value["limits"]["titleMax"] == backend_max, (
            f"{platform}: 契约写 {value['limits']['titleMax']},后端写 {backend_max} —— 两份会漂"
        )


def test_verified_image_limits_come_from_the_real_pages(contract: dict) -> None:
    """这几条是 2026-10-22 在真账号创作页上读到的(见 ADR 0076 的「真机核对」),钉住防止被随手改。"""
    expected = {
        "douyin": 35,          # 页面原文「最多支持上传 35 张图片」
        "xiaohongshu": 18,     # 上传后右上角 1/18
        "weixin-channels": 18, # 助手端 18 张,超过会形成视频
        "tiktok": 35,          # 「Up to 35 photos, max 50 MB per photo」
        "youtube": 10,         # 「最多拖动 10 张图片或 GIF」
        "x": 4,                # 每帖 4 张
    }
    for platform, images in expected.items():
        assert contract["platforms"][platform]["limits"]["imageMax"] == images, platform

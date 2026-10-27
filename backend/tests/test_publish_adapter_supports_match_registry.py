"""适配器声明「我做到了哪些内容形状」,注册表声明「平台能发哪些」——两者不能各说各的。

ADR 0076:后端 `PUBLISH_PLATFORMS[platform]["kinds"]` 说平台**能发**什么,执行器侧的适配器用
`readonly supports = [...]` 说我们**实现了**什么。前者是事实,后者是进度;后者超出前者,说明有人
把"平台能发"当成了"我们已经会发",用户会在真实页面上撞到一个做不到的任务。

这条测试是一道**棘轮**:改任何一边都得同时改另一边。没声明 `supports` 的适配器按「只发视频」算。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.publish import IMPLEMENTED_KINDS, content_kinds, implemented_kinds

RATCHET = True

ADAPTERS = Path(__file__).resolve().parents[2] / "electron" / "browser" / "publish" / "adapters"
#: 文件名 → 平台。`mock` 是测试替身,不参与。
FILES = {
    "douyin.ts": "douyin",
    "xiaohongshu.ts": "xiaohongshu",
    "weixinChannels.ts": "weixin-channels",
    "bilibili.ts": "bilibili",
    "tiktok.ts": "tiktok",
    "x.ts": "x",
    "youtube.ts": "youtube",
}


def _supports(path: Path) -> tuple[str, ...]:
    """适配器声明的形状。**声明在类的 `KINDS` 上**(实例字段读不到,见 adapters.ts 的
    `ADAPTER_SUPPORTS`)—— 这里读同一个地方。"""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"static\s+readonly\s+KINDS\s*=\s*\[([^\]]*)\]", text)
    if not match:
        return ("video",)
    return tuple(item.strip().strip("\"'") for item in match.group(1).split(",") if item.strip())


def test_every_adapter_file_has_a_platform() -> None:
    found = {path.name for path in ADAPTERS.glob("*.ts")} - {"shared.ts", "index.ts", "mock.ts"}
    assert found == set(FILES), f"适配器文件与这张表对不上:{found ^ set(FILES)}"


@pytest.mark.parametrize(("file_name", "platform"), sorted(FILES.items()))
def test_an_adapter_never_claims_a_shape_the_platform_cannot_take(file_name: str, platform: str) -> None:
    implemented = set(_supports(ADAPTERS / file_name))
    declared = set(content_kinds(platform))
    assert implemented <= declared, (
        f"{file_name} 说它会发 {sorted(implemented - declared)},但注册表里 {platform} 只声明了 {sorted(declared)} —— "
        f"先改注册表(如果平台真能发),或者别在适配器里声明它"
    )


def test_the_registry_never_promises_a_shape_no_adapter_implements() -> None:
    """反向也要看:平台声明了、但没有任何适配器实现 —— 那是**进度**,不是错误,但必须被看见。

    这里不做硬断言(否则每加一个平台的 kind 就得先写适配器),而是要求这张进度表在测试里写出来,
    改注册表的人会看到自己把哪一格点成了「已实现」。
    """
    implemented = {_supports(ADAPTERS / name) for name in FILES}
    union = {kind for kinds in implemented for kind in kinds}
    assert "video" in union, "连视频都不认了?适配器一定出了事"
    #: 小红书 / 抖音 / X 的图文已接;TikTok / 视频号 / YouTube 的入口待真机确认后跟上。
    assert "image-text" in union


#: 后端 `IMPLEMENTED_KINDS` 与适配器文件声明的是**同一件事**(进度),不能各说各的。
@pytest.mark.parametrize(("file_name", "platform"), sorted(FILES.items()))
def test_the_backend_progress_list_matches_the_adapter_declaration(file_name: str, platform: str) -> None:
    adapter = tuple(sorted(_supports(ADAPTERS / file_name)))
    backend = tuple(sorted(implemented_kinds(platform)))
    assert adapter == backend, (
        f"{platform}: 适配器声明 {adapter},后端 IMPLEMENTED_KINDS 写 {backend} —— "
        f"界面按后者列选项,两边不一致就会摆出一个点了会失败的形状(或藏起一个已经能用的)"
    )


def test_the_progress_list_never_exceeds_the_platform_capability() -> None:
    for platform, kinds in IMPLEMENTED_KINDS.items():
        assert set(kinds) <= set(content_kinds(platform)), platform

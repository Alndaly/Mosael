"""插件的 README 要能在官网上渲染出来。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

README 是给人写的、也要在 GitHub 上好看,所以**不该为了渲染器改写法**。官网那边做了两层
翻译(website/src/app/[locale]/plugins/[slug]):`<https://…>` 这种 autolink 转成普通链接
(MDX 会把尖括号当 JSX 标签,直接编译失败),相对链接改指回仓库(那些路径按目录写的,
搬到网页地址下全是 404)。

这条钉的是**翻译覆盖得住**:出现翻译不掉的写法时在这里红,而不是等到发布网站时构建失败,
或者更糟 —— 构建过了,而详情页上每个「见 xxx」都是死链,写 README 的人完全不知情。
"""

from __future__ import annotations

RATCHET = True

import re
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "plugins" / "examples"
READMES = sorted(EXAMPLES.glob("*/README.md"))

#: markdown 链接,排除 autolink(`<...>`)与锚点。
LINK = re.compile(r"\]\((?!https?://|#)([^)]+)\)")


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.parent.name)
def test_相对链接指得到真实文件(readme: Path) -> None:
    """官网会把它们改写成仓库地址 —— 而改写只保证**地址对**,不保证**文件在**。
    指向一个不存在的文件时,改写完照样是死链,只是死在 GitHub 上。"""
    missing = []
    for target in LINK.findall(readme.read_text(encoding="utf-8")):
        path = (readme.parent / target.split("#", 1)[0].strip()).resolve()
        if not path.exists():
            missing.append(target)
    assert missing == [], f"{readme.parent.name}/README.md 指向了不存在的文件:{missing}"


@pytest.mark.parametrize("readme", READMES, ids=lambda p: p.parent.name)
def test_没有_MDX_翻译不掉的写法(readme: Path) -> None:
    """裸的 `<Something>` 会被 MDX 当成 JSX 组件。autolink(`<https://…>`)官网翻译得掉,
    别的形状翻译不掉 —— 那种要在这里拦住,而不是等构建失败。"""
    text = readme.read_text(encoding="utf-8")
    # 去掉代码块:里面写什么都行,MDX 不解析。
    outside_code = re.sub(r"```[\s\S]*?```|`[^`]*`", "", text)
    suspicious = [
        one for one in re.findall(r"<([A-Za-z][^\s>]*)>", outside_code) if not one.startswith(("http://", "https://"))
    ]
    assert suspicious == [], f"{readme.parent.name}/README.md 里这些尖括号 MDX 会当成组件:{suspicious}"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面两条会一起真空通过。"""
    assert len(READMES) >= 3

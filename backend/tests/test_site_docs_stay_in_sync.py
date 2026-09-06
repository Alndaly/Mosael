"""棘轮:**官网文档两种语言要对得上,而且别把数目写死错**。

两类漂移,都不报错、只是让读的人拿到一份不对的说明:

· **一边有、另一边没有。** 发现时 `guides/plugins` 的英文版只有 3 个小节,中文有 9 个 ——
  英文读者拿到的是三分之一的内容,而两边看起来都"有这一页"。
· **数目写死。** 那一页写着「`plugins/examples/` 下有三个」,而目录里有四个(百度网盘是后加的)。
  这种句子每加一个范例就错一次,而没有任何东西会提醒。

这里只钉机器判得了的:页面成对、小节数一致、`order` 不撞车、以及范例的数目。
散文写得好不好不在此列 —— 那不是棘轮能管的事。
"""

from __future__ import annotations

import pathlib
import re

RATCHET = True

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "website" / "content" / "docs"


def _pages(lang: str) -> dict[str, pathlib.Path]:
    base = DOCS / lang
    return {str(p.relative_to(base)): p for p in base.rglob("*.mdx")}


def _sections(path: pathlib.Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if re.match(r"^## ", line)])


def test_两种语言的页面一一对应() -> None:
    zh, en = _pages("zh"), _pages("en")
    assert sorted(set(zh) - set(en)) == [], f"只有中文版:{sorted(set(zh) - set(en))}"
    assert sorted(set(en) - set(zh)) == [], f"只有英文版:{sorted(set(en) - set(zh))}"


def test_对应的页面小节数一致() -> None:
    """小节数对不上,通常意味着一边少了整块内容 —— 英文版的插件页就这么少过五节。"""
    zh, en = _pages("zh"), _pages("en")
    off = [
        f"{key}: zh {_sections(zh[key])} / en {_sections(en[key])}"
        for key in sorted(set(zh) & set(en))
        if _sections(zh[key]) != _sections(en[key])
    ]
    assert not off, "这些页面两种语言的小节数对不上:\n  " + "\n  ".join(off)


def test_指南的_order_不撞车() -> None:
    """撞车时导航里谁在前谁在后是随机的。`browser-extension` 和 `plugins` 曾经都是 7。"""
    for lang in ("zh", "en"):
        seen: dict[int, str] = {}
        clashes = []
        for path in sorted((DOCS / lang / "guides").glob("*.mdx")):
            match = re.search(r"^order: (\d+)$", path.read_text(encoding="utf-8"), re.M)
            assert match, f"{path} 没写 order"
            order = int(match.group(1))
            if order in seen:
                clashes.append(f"{lang}: {seen[order]} 和 {path.stem} 都是 {order}")
            seen[order] = path.stem
        assert not clashes, "\n  ".join(clashes)


def test_范例的数目和目录一致() -> None:
    """写死的数目每加一个范例就错一次,而没有任何东西会提醒。"""
    actual = len([p for p in (ROOT / "plugins" / "examples").iterdir() if p.is_dir()])
    words = {3: ("三个", "Three"), 4: ("四个", "Four"), 5: ("五个", "Five"), 6: ("六个", "Six")}
    assert actual in words, f"范例有 {actual} 个,给这条测试的 words 表补上对应的写法"
    zh_word, en_word = words[actual]
    zh_text = (DOCS / "zh" / "guides" / "plugins.mdx").read_text(encoding="utf-8")
    en_text = (DOCS / "en" / "guides" / "plugins.mdx").read_text(encoding="utf-8")
    assert f"下有{zh_word}" in zh_text, f"中文版没说「下有{zh_word}」(实际 {actual} 个)"
    assert f"{en_word} of them live" in en_text, f"英文版没说「{en_word} of them」(实际 {actual} 个)"
    # 每个范例目录都该被提到 —— 加了一个却不写进去,和数目写错是同一件事。
    for example in sorted(p.name for p in (ROOT / "plugins" / "examples").iterdir() if p.is_dir()):
        assert example in zh_text, f"中文版没提到范例 {example}"
        assert example in en_text, f"英文版没提到范例 {example}"

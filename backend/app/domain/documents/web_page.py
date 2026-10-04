"""「存成笔记」:把内嵌浏览器里的一页(整页正文)或选中的一段,变成一篇带来源的笔记。

和 to_note(一份文档存成笔记)住在一起:都是「把一份读得到的东西变成笔记」,Markdown 转换也是同一个。

**正文从渲染后的 HTML 里挑**,不是回后端重新抓一遍那个地址:很多页面不登录看不到正文,而登录态只在用户的
浏览器档案里(Electron 那一侧交来的就是那个档案里渲染出来的 DOM)。挑法和转换都是现成的那一套 ——
BeautifulSoup 去掉不是正文的东西(和 websearch.fetch 同一个思路),Markdown 转换用文档解析的那个
(documents.local.html_to_markdown)。

挑正文的规则刻意简单、可预期:有 `<article>` 就取字最多的那一篇,其次 `<main>` / `[role=main]`,都没有才是
整个 body;导航、侧栏、表单、脚本样式一律不要,整页兜底时连页眉页脚也去掉。不做「打分猜正文」—— 猜错的时候
用户说不清它为什么丢了一段,而这几条规则他一眼就能对上。
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from app.core.i18n import tr
from app.domain.note_types import NoteContent, NoteSource

#: 正文最多留多少字(笔记 markdown 的上限是 500000,留出来源那一行)。
MAX_NOTE_MARKDOWN = 400_000

#: 不管正文挑在哪儿,这些都不是正文。
_NEVER = ["script", "style", "noscript", "template", "iframe", "svg", "canvas", "form", "button", "input",
          "select", "textarea", "nav", "aside", "dialog"]
#: 整页兜底(没有 article / main)时,页眉页脚是站点的外壳;挑中了 article / main 时,里面的 header 常常就是标题。
_CHROME = ["header", "footer"]


def article_markdown(html: str, base_url: str) -> str:
    """渲染后的 HTML → 正文 Markdown。链接和图片补成绝对地址(离开那个页面,相对地址就失效了)。"""
    from bs4 import BeautifulSoup

    from app.domain.documents.local import html_to_markdown

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NEVER):
        tag.decompose()
    articles = soup.find_all("article")
    root = (
        max(articles, key=lambda one: len(one.get_text(" ", strip=True)))
        if articles
        else soup.find("main") or soup.find(attrs={"role": "main"})
    )
    if root is None:
        root = soup.body or soup
        for tag in root.find_all(_CHROME):
            tag.decompose()
    else:
        for tag in root.find_all("footer"):
            tag.decompose()
    for link in root.find_all("a"):
        href = str(link.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "data:")):
            link.unwrap()
        else:
            link["href"] = urljoin(base_url, href)
    for image in root.find_all("img"):
        src = str(image.get("src") or image.get("data-src") or "").strip()
        if not src or src.lower().startswith(("data:", "blob:", "javascript:")):
            image.decompose()
        else:
            image["src"] = urljoin(base_url, src)
    markdown = html_to_markdown(str(root))
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()[:MAX_NOTE_MARKDOWN]


def _link_text(text: str) -> str:
    """放进 Markdown 链接文字里的标题:方括号会把链接切断。"""
    return text.replace("[", "\\[").replace("]", "\\]")


def page_note_content(
    *, url: str, title: str, html: str = "", selection: str = "", project_id: str | None = None,
) -> NoteContent | None:
    """一页 / 一段 → 笔记内容;什么都没读出来返回 None(不建一篇空笔记)。

    来源两处都写:sources 里一条 url(笔记页的来源卡、引用都认它),正文开头一行「来源」(导出成 Markdown
    文件、复制到别处时它跟着走)。
    """
    host = urlsplit(url).hostname or url
    page_title = title.strip() or host
    excerpt = selection.strip()
    body = excerpt if excerpt else (article_markdown(html, url) if html.strip() else "")
    if not body:
        return None
    header = "> " + tr("pageNoteFrom", title=_link_text(page_title), url=url)
    return NoteContent(
        title=(tr("pageNoteTitle_selection", title=page_title) if excerpt else page_title)[:240],
        markdown=f"{header}\n\n{body}",
        project_id=project_id,
        sources=[NoteSource(kind="url", url=url, label=page_title[:240], quote=excerpt[:50000])],
    )

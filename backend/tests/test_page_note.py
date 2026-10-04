"""内嵌浏览器顶栏「存成笔记」(`POST /api/notes/from-page`)。

两种来源:整页正文(客户端交来**渲染后的** HTML —— 很多页面不登录看不到正文,登录态只在那个浏览器档案里),
或当前选中的文字。钉住的是:

- 正文挑得对:有 `<article>` / `<main>` 就只要它,导航、页眉页脚、侧栏、脚本样式都不进笔记;
- 链接与图片补成绝对地址(相对地址离开那个页面就失效),`javascript:` 链接只留文字;
- 笔记带着来源:sources 里一条 url(地址 + 页面标题),正文开头一行「来源」;
- 什么都没读出来就说清楚,不建一篇空笔记;
- 鉴权照笔记的规矩。
"""
from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Note
from tests.util import fresh_client, second_client

PAGE = """<!doctype html><html><head><title>页面标题</title><style>.x{color:red}</style></head>
<body>
  <header><nav><a href="/">首页</a> · <a href="/about">关于我们</a></nav></header>
  <aside>热门推荐:别的文章</aside>
  <main>
    <article>
      <h1>一篇文章</h1>
      <p>第一段正文,带一个<a href="/ref?id=2">相对链接</a>和一个<a href="javascript:void(0)">假链接</a>。</p>
      <img src="img/cover.png" alt="封面">
      <h2>小标题</h2>
      <ul><li>要点一</li><li>要点二</li></ul>
      <script>trackEverything()</script>
    </article>
  </main>
  <footer>页脚 · 版权所有</footer>
</body></html>"""


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _save(client, workspace_id: str, **body):
    payload = {
        "workspace_id": workspace_id,
        "url": "https://example.com/blog/post-1",
        "title": "页面标题",
        **body,
    }
    return client.post("/api/notes/from-page", json=payload)


def test_整页正文存成笔记_只要正文_地址补全_带着来源() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _save(client, workspace_id, html=PAGE)
    assert response.status_code == 200, response.text
    note = response.json()
    assert note["title"] == "页面标题"
    markdown = note["markdown"]
    assert "# 一篇文章" in markdown
    assert "## 小标题" in markdown
    assert "- 要点一" in markdown
    assert "[相对链接](https://example.com/ref?id=2)" in markdown
    assert "![封面](https://example.com/blog/img/cover.png)" in markdown
    assert "假链接" in markdown and "javascript:" not in markdown
    for noise in ("首页", "关于我们", "热门推荐", "页脚", "trackEverything", "color:red"):
        assert noise not in markdown
    # 开头一行来源,sources 里一条 url。
    assert markdown.splitlines()[0].startswith("> ")
    assert "[页面标题](https://example.com/blog/post-1)" in markdown.splitlines()[0]
    assert note["sources"] == [
        {"kind": "url", "id": "", "label": "页面标题", "quote": "", "start": None, "end": None,
         "url": "https://example.com/blog/post-1", "revision": None},
    ]


def test_没有_article_时退回整页_但照样去掉导航和页脚() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    html = "<html><body><nav>菜单</nav><div><p>唯一的正文段落。</p></div><footer>版权</footer></body></html>"
    response = _save(client, workspace_id, html=html)
    assert response.status_code == 200, response.text
    markdown = response.json()["markdown"]
    assert "唯一的正文段落。" in markdown
    assert "菜单" not in markdown and "版权" not in markdown


def test_选中的文字存成摘录() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _save(client, workspace_id, selection="  选中的第一行\n第二行  ")
    assert response.status_code == 200, response.text
    note = response.json()
    assert note["title"] == "页面标题(摘录)"
    assert "选中的第一行\n第二行" in note["markdown"]
    assert note["sources"][0]["quote"] == "选中的第一行\n第二行"


def test_什么都没读出来就不建空笔记() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _save(client, workspace_id, html="<html><body><script>x()</script></body></html>")
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.query(Note).count() == 0


def test_来源地址只认_http_s() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    assert _save(client, workspace_id, url="file:///etc/passwd", selection="x").status_code == 422


def test_页面标题空着时用地址当标题() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _save(client, workspace_id, title="", selection="一段话")
    assert response.status_code == 200, response.text
    assert response.json()["title"].startswith("example.com")


def test_别人的工作区存不进去() -> None:
    owner = fresh_client("owner")
    workspace_id = _workspace(owner)
    response = _save(second_client("stranger"), workspace_id, selection="一段话")
    assert response.status_code in (403, 404)

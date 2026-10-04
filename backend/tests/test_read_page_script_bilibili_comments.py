"""分析类模板「读页面」那段脚本在 B 站视频页上走接口那一支:评论取全了没有、取不全时说没说清为什么。

**真跑那段脚本**(node),只把 B 站接口换成按 B 站真实形状回话的假接口 —— 要验的正是脚本怎么翻页、怎么翻楼中楼、
什么时候停、交回的数对不对。

为什么要这些(2026-10,真实执行器 + 已登录的 B 站档案逐条对过):
- 一级评论只翻 15 页(注释写的是 50 页):1374 条评论的视频只取到 300 条一级;
- 楼中楼只用了一级评论里自带的那几条预览(最多 3 条),从不翻 reply/reply:69 条的视频取到 15/50 条回复;
- 置顶评论在 top_replies 里,从不读;
- 未登录时 B 站只给 3 条一级评论、每条下只给前 20 条回复 —— 脚本照样报 mode=api,下游把这几条当成「全部评论」分析,
  而平台显示的总数(view 接口的 stat.reply)只躺在 web_read 里,谁也没告诉。
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.domain.workflows.templates_analysis import _READ_PAGE_SCRIPT

NOTES = {
    "login": "没登录:B 站只给前 3 条一级评论",
    "limit": "到了这次最多取的条数",
    "time": "到了这次取数的时间上限",
    "platform": "其余的平台没有给",
}


def _reply(rpid: int, *, rcount: int = 0, previews: list[dict] | None = None, like: int = 0) -> dict:
    return {
        "rpid": rpid, "rpid_str": str(rpid), "rcount": rcount, "like": like, "ctime": 1759500000,
        "member": {"uname": f"用户{rpid}"}, "content": {"message": f"评论 {rpid}"}, "replies": previews or [],
    }


def _site(*, logged_in: bool, roots: list[dict], top: dict | None, subs: dict[int, list[dict]], total: int,
          root_pages_shown: int | None = None, sub_pages_shown: int | None = None) -> dict:
    """B 站的几个接口按真实形状回话:一级按 20 条一页(第 1 页带置顶),楼中楼按 20 条一页。
    `root_pages_shown` / `sub_pages_shown`:只给前几页(未登录时一级只给 1 页 3 条、楼中楼只给 1 页)。"""
    pages = [roots[i:i + 20] for i in range(0, len(roots), 20)] or [[]]
    if root_pages_shown is not None:
        pages = pages[:root_pages_shown]
    root_pages = []
    for index, page in enumerate(pages):
        data = {"page": {"num": index + 1, "size": 20, "count": total, "acount": total}, "replies": page}
        if index == 0 and top is not None:
            data["top_replies"] = [top]
        root_pages.append({"code": 0, "data": data})
    sub_pages = {}
    for root, items in subs.items():
        chunks = [items[i:i + 20] for i in range(0, len(items), 20)]
        if sub_pages_shown is not None:
            chunks = chunks[:sub_pages_shown]
        sub_pages[str(root)] = [{"code": 0, "data": {"page": {"count": len(items)}, "replies": chunk}} for chunk in chunks]
    return {
        "view": {"code": 0, "data": {"bvid": "BV1test000000", "aid": 777, "title": "测试视频", "pubdate": 1759400000,
                                     "duration": 60, "desc": "", "owner": {"name": "UP", "mid": 1},
                                     "stat": {"reply": total, "view": 1000, "like": 10}}},
        "nav": {"code": 0, "data": {"isLogin": logged_in}},
        "root_pages": root_pages,
        "sub_pages": sub_pages,
    }


_HARNESS = r"""
const site = __SITE__;
const calls = [];
globalThis.location = { href: "https://www.bilibili.com/video/BV1test000000/" };
globalThis.document = { title: "测试视频", body: { innerText: "", scrollHeight: 1000 }, querySelectorAll: () => [] };
globalThis.window = { innerHeight: 800, scrollY: 0, scrollBy() {} };
const answer = (body) => ({ json: async () => body });
globalThis.fetch = async (url) => {
  const u = new URL(url);
  calls.push(u.pathname + u.search);
  const q = Object.fromEntries(u.searchParams);
  if (u.pathname === "/x/web-interface/view") return answer(site.view);
  if (u.pathname === "/x/web-interface/nav") return answer(site.nav);
  if (u.pathname === "/x/v2/reply") {
    const page = site.root_pages[Number(q.pn) - 1];
    return answer(page || { code: 0, data: { page: { count: site.view.data.stat.reply }, replies: null } });
  }
  if (u.pathname === "/x/v2/reply/reply") {
    const page = (site.sub_pages[q.root] || [])[Number(q.pn) - 1];
    return answer(page || { code: 0, data: { page: { count: 0 }, replies: null } });
  }
  throw new Error("unexpected " + url);
};
const input = __INPUT__;
(__SCRIPT__).then((value) => process.stdout.write(JSON.stringify({ value, calls })));
"""


def _run(site: dict, **inputs) -> tuple[dict, list[str]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("这台机器上没有 node")
    program = (_HARNESS.replace("__SITE__", json.dumps(site, ensure_ascii=False))
               .replace("__INPUT__", json.dumps({"page_pause_ms": 0, "notes": NOTES, **inputs}, ensure_ascii=False))
               .replace("__SCRIPT__", _READ_PAGE_SCRIPT))
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    return out["value"], out["calls"]


def _comments(value: dict) -> list[dict]:
    assert value["mode"] == "api", value
    return json.loads(value["text"])["comments"]


def _logged_in_site() -> dict:
    """46 条一级(3 页,第 1 页另有 1 条置顶)+ 27 条楼中楼:一条楼 25 条回复(自带 3 条预览)、一条楼 2 条(自带 2 条)。"""
    many = [_reply(9000 + i) for i in range(25)]
    two = [_reply(9100), _reply(9101)]
    roots = [_reply(1, rcount=25, previews=many[:3]), _reply(2, rcount=2, previews=two)] + [_reply(100 + i) for i in range(43)]
    return _site(logged_in=True, roots=roots, top=_reply(5, like=99), subs={1: many, 2: two}, total=46 + 27)


def test_已登录_一级翻完_置顶算进来_每条楼中楼翻完_预览不重复算() -> None:
    value, calls = _run(_logged_in_site())
    comments = _comments(value)
    assert value["total"] == 73
    assert (value["fetched"], value["fetched_roots"], value["fetched_replies"]) == (73, 46, 27)
    assert len(comments) == 73
    texts = [one["text"] for one in comments]
    assert len(set(texts)) == 73, "楼中楼的预览和翻出来的同一条不能算两次"
    assert "评论 5" in texts, "置顶评论也是评论"
    assert sum(text.startswith("↳ ") for text in texts) == 27, "楼中楼带 ↳ 前缀"
    assert value["gap_note"] == "", "取全了就不说没取全"
    assert any("/x/v2/reply/reply" in one and "root=1" in one for one in calls), "回复多于预览的楼要翻 reply/reply"
    assert not any("root=2&" in one or one.endswith("root=2") for one in calls if "/reply/reply" in one), \
        "预览已经是全部回复的楼不必再翻"


def test_一级评论超过15页照样往下翻() -> None:
    roots = [_reply(i) for i in range(1, 421)]  # 21 页
    value, _calls = _run(_site(logged_in=True, roots=roots, top=None, subs={}, total=420))
    assert value["fetched_roots"] == 420
    assert value["gap_note"] == ""


def test_未登录_平台只给3条一级和每条前20条回复_说清是没登录() -> None:
    subs = {1: [_reply(9000 + i) for i in range(25)], 2: [_reply(9100 + i) for i in range(5)]}
    roots = [_reply(1, rcount=25), _reply(2, rcount=5), _reply(3)] + [_reply(100 + i) for i in range(30)]
    site = _site(logged_in=False, roots=roots[:3], top=None, subs=subs, total=69, sub_pages_shown=1)
    value, _calls = _run(site)
    comments = _comments(value)
    assert (value["fetched_roots"], value["fetched_replies"]) == (3, 25), "3 条一级 + 第一条楼前 20 条 + 第二条楼 5 条"
    assert len(comments) == 28 and value["total"] == 69
    assert value["logged_in"] is False
    assert value["gap_note"] == NOTES["login"]


def test_到了条数上限就停_说清是上限() -> None:
    value, _calls = _run(_logged_in_site(), comment_max=30)
    assert value["fetched"] == 30 == len(_comments(value))
    assert value["fetched_roots"] + value["fetched_replies"] == 30
    assert value["gap_note"] == NOTES["limit"]


def test_到了时间上限就停_说清是时间() -> None:
    value, _calls = _run(_logged_in_site(), budget_ms=1, page_pause_ms=20)
    assert 0 < value["fetched"] < 73
    assert value["gap_note"] == NOTES["time"]


def test_已登录也翻完了_平台的数还是多_说其余是平台没给() -> None:
    site = _logged_in_site()
    site["view"]["data"]["stat"]["reply"] = 80  # 被删除、折叠、仅自己可见的那几条
    value, _calls = _run(site)
    assert value["fetched"] == 73 and value["total"] == 80
    assert value["gap_note"] == NOTES["platform"]


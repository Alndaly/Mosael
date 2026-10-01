"""自媒体分析的三个节点:认链接、整理作品 / 评论算指标、从链接下载。

整理那一步不对齐字段名,按各平台常见的叫法去找 —— 所以这里喂的是**各平台接口原来的样子**(抖音的
`statistics.digg_count`、B 站的 `play` / `created` / `03:21`、小红书的 `liked_count`、浏览器整理出来的
「1.2万」),而不是先替它对齐好的数据。缺的字段要说缺,不能拿 0 冒充。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job
from app.domain import social_media
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client

CST = timezone(timedelta(hours=8))


@dataclass
class _Scope:
    id: str
    workspace_id: str
    name: str = "分析"


def _run(node_type: str, config: dict, workspace_id: str = "ws") -> dict:
    with SessionLocal() as db:
        return get_executor(node_type)(db, _Scope(id="wf", workspace_id=workspace_id), config)


def _stamp(*args: int) -> int:
    return int(datetime(*args, tzinfo=CST).timestamp())


# --------------------------------------------------------------------------------------
# 认链接
# --------------------------------------------------------------------------------------


class Test认链接:
    def test_抖音分享口令里抠出主页链接和_sec_uid(self) -> None:
        out = _run("social_link", {
            "link": "7.43 复制打开抖音，看看【某某的作品】https://www.douyin.com/user/MS4wLjABAAAAab-c_1?from=share 复制此链接",
        })
        assert out["platform"] == "douyin" and out["kind"] == "account"
        assert out["id"] == "MS4wLjABAAAAab-c_1"
        assert out["url"].startswith("https://www.douyin.com/user/MS4wLjABAAAAab-c_1")

    def test_短链跟一次跳转再认(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(social_media, "resolve_short_link",
                            lambda url: "https://www.iesdouyin.com/share/video/7412345678901234567/?region=CN")
        out = _run("social_link", {"link": "https://v.douyin.com/iAbCdEf/", "expect": "video"})
        assert (out["platform"], out["kind"], out["id"]) == ("douyin", "video", "7412345678901234567")

    @pytest.mark.parametrize(("link", "platform", "expected"), [
        ("https://www.xiaohongshu.com/user/profile/5f1e2d3c4b5a69788796a5b4?xsec_token=x", "",
         ("xiaohongshu", "account", "5f1e2d3c4b5a69788796a5b4")),
        ("https://www.xiaohongshu.com/explore/64f0a1b2c3d4e5f6a7b8c9d0", "", ("xiaohongshu", "video", "64f0a1b2c3d4e5f6a7b8c9d0")),
        ("space.bilibili.com/12345678", "", ("bilibili", "account", "12345678")),
        ("看看这个 https://www.bilibili.com/video/BV1xx411c7mD?p=1", "", ("bilibili", "video", "BV1xx411c7mD")),
        ("BV1xx411c7mD", "B站", ("bilibili", "video", "BV1xx411c7mD")),
        ("12345678", "哔哩哔哩", ("bilibili", "account", "12345678")),
        ("MS4wLjABAAAAab", "抖音", ("douyin", "account", "MS4wLjABAAAAab")),
        ("https://www.kuaishou.com/profile/3xabc", "", ("kuaishou", "account", "3xabc")),
    ])
    def test_各平台的链接和编号(self, link: str, platform: str, expected: tuple[str, str, str]) -> None:
        out = _run("social_link", {"link": link, "platform": platform})
        assert (out["platform"], out["kind"], out["id"]) == expected
        assert out["url"].startswith("https://")

    def test_说了平台就以说的为准(self) -> None:
        """用户在开始节点写了「小红书」,链接却是别的样子 —— 平台按他说的(TikHub 按它挑连接)。"""
        out = _run("social_link", {"link": "https://www.xiaohongshu.com/explore/64f0a1b2c3d4e5f6a7b8c9d0", "platform": "XHS"})
        assert out["platform"] == "xiaohongshu"

    def test_光给编号不说平台_当场说清(self) -> None:
        with pytest.raises(WorkflowDomainError) as caught:
            _run("social_link", {"link": "12345678"})
        assert caught.value.key == "wfErr_socialLinkUnreadable"

    def test_空的当场说清(self) -> None:
        with pytest.raises(WorkflowDomainError) as caught:
            _run("social_link", {"link": "  "})
        assert caught.value.key == "wfErr_socialLinkEmpty"

    def test_短链只请求短链域名_跳出去就停(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            asked.append(str(request.url))
            if request.url.host == "b23.tv":
                return httpx.Response(302, headers={"location": "https://www.bilibili.com/video/BV1xx411c7mD?share=1"})
            return httpx.Response(200)

        real = httpx.Client
        monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        assert social_media.resolve_short_link("https://b23.tv/abcd") == "https://www.bilibili.com/video/BV1xx411c7mD?share=1"
        assert asked == ["https://b23.tv/abcd"], "落到 bilibili.com 之后不该再请求"

    def test_短链跟不到_原样交回(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        real = httpx.Client
        monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        assert social_media.resolve_short_link("https://xhslink.com/a/b") == "https://xhslink.com/a/b"


# --------------------------------------------------------------------------------------
# 整理作品
# --------------------------------------------------------------------------------------

DOUYIN_POSTS = {"result": json.dumps({"code": 200, "data": {"aweme_list": [
    {"aweme_id": "1", "desc": "第一条 #美食", "create_time": _stamp(2026, 9, 30, 19, 5), "duration": 15200,
     "statistics": {"digg_count": 1200, "comment_count": 30, "collect_count": 50, "share_count": 8, "play_count": 0},
     "music": {"title": "背景音乐不是标题"}},
    {"aweme_id": "2", "desc": "第二条", "create_time": _stamp(2026, 9, 26, 12, 0), "duration": 61000,
     "statistics": {"digg_count": "1.2万", "comment_count": 300, "collect_count": 500, "share_count": 80, "play_count": 0}},
]}}, ensure_ascii=False)}


class Test整理作品:
    def test_抖音接口原样喂进来_字段按别名取_毫秒换成秒(self) -> None:
        out = _run("social_metrics", {"data": DOUYIN_POSTS, "duration_unit": "milliseconds",
                                      "profile": {"data": {"user": {"nickname": "某某", "follower_count": 34000}}}})
        first, second = out["items"]
        assert first["title"] == "第一条 #美食", "music.title 更深,不该盖过作品自己的 desc"
        assert (first["duration_seconds"], second["duration_seconds"]) == (15.2, 61.0)
        assert second["likes"] == 12000
        assert first["views"] is None, "抖音不公开播放数(给的是 0),不能当成没人看"
        assert first["published_at"].startswith("2026-09-30T19:05")
        assert out["account"]["name"] == "某某" and out["account"]["followers"] == 34000
        assert out["stats"]["interactions_per_follower"] is not None
        assert "views" in out["stats"]["missing"]
        assert out["count"] == 2

    def test_新的在前_只留最新的几条(self) -> None:
        posts = [{"title": f"第{index}条", "published_at": f"2026-09-{index:02d}T10:00:00+08:00", "likes": index}
                 for index in range(1, 11)]
        out = _run("social_metrics", {"data": {"posts": posts}, "limit": 3})
        assert [one["title"] for one in out["items"]] == ["第10条", "第9条", "第8条"]

    def test_B站主页列表没有点赞_不凑互动_按播放排头部(self) -> None:
        data = {"data": {"list": {"vlist": [
            {"bvid": "BV1", "title": "冷门", "created": _stamp(2026, 9, 1), "length": "03:21", "play": 500, "comment": 2},
            {"bvid": "BV2", "title": "爆了", "created": _stamp(2026, 9, 5), "length": "1:02:03", "play": "11.5万", "comment": 900},
        ]}}}
        out = _run("social_metrics", {"data": data})
        by_title = {one["title"]: one for one in out["items"]}
        assert by_title["冷门"]["duration_seconds"] == 201 and by_title["爆了"]["duration_seconds"] == 3723
        assert by_title["爆了"]["views"] == 115000
        assert by_title["爆了"]["interactions"] is None, "没有点赞时,只拿评论数凑出来的「互动」会让互动率低得离谱"
        assert out["stats"]["top"][0]["title"] == "爆了"
        assert set(out["stats"]["missing"]) >= {"likes", "collects", "shares"}

    def test_浏览器整理出来的中文数字和日期(self) -> None:
        data = {"account": {"name": "号"}, "posts": [
            {"title": "一", "published_at": "2026-9-3", "likes": "1.5w", "comments": "300", "views": "10万+"},
            {"title": "二", "published_at": "2026年09月01日", "likes": "800", "comments": None, "views": None},
        ]}
        out = _run("social_metrics", {"data": data})
        first = out["items"][0]
        assert (first["likes"], first["views"]) == (15000, 100000)
        assert first["engagement_rate"] == round((15000 + 300) / 100000, 4)
        assert out["items"][1]["published_at"].startswith("2026-09-01")

    def test_一条作品都没有_照样交出形状和一句话(self) -> None:
        for empty in ("", [], {"data": {"aweme_list": []}}, {"posts": []}):
            out = _run("social_metrics", {"data": empty})
            assert out["count"] == 0 and out["items"] == []
            assert "一条作品都没取到" in out["summary"] or "No posts" in out["summary"]

    def test_作品没有发布时间_频率不编(self) -> None:
        out = _run("social_metrics", {"data": [{"title": "a", "likes": 3}, {"title": "b", "likes": 5}]})
        assert out["stats"]["with_time"] == 0 and "posts_per_week" not in out["stats"]
        assert "published_at" in out["stats"]["missing"]

    def test_发布时段和频率_按北京时间数(self) -> None:
        posts = [{"title": str(day), "published_at": _stamp(2026, 9, day, 20, 30), "likes": 10} for day in (1, 3, 5, 7, 9)]
        out = _run("social_metrics", {"data": posts})
        stats = out["stats"]
        assert stats["top_hours"] == [20]
        assert stats["dayparts"]["evening"] == 5
        assert stats["median_gap_days"] == 2.0
        assert stats["posts_per_week"] == round(5 / 8 * 7, 2)

    @pytest.mark.parametrize(("older", "recent", "signal"), [(100, 400, "growing"), (400, 100, "declining"), (100, 110, "steady")])
    def test_最近一半对之前一半(self, older: int, recent: int, signal: str) -> None:
        posts = [{"title": str(day), "published_at": _stamp(2026, 9, day, 12), "likes": older if day <= 3 else recent}
                 for day in range(1, 7)]
        assert _run("social_metrics", {"data": posts})["stats"]["trend"]["signal"] == signal

    def test_条数太少不谈趋势(self) -> None:
        posts = [{"title": "a", "published_at": _stamp(2026, 9, 1), "likes": 1}, {"title": "b", "published_at": _stamp(2026, 9, 2), "likes": 9}]
        assert _run("social_metrics", {"data": posts})["stats"]["trend"]["signal"] == "insufficient"

    def test_单条作品详情也是一串_只有一条(self) -> None:
        detail = {"data": {"bvid": "BV9", "title": "爆款", "pubdate": _stamp(2026, 9, 30), "duration": 95,
                           "stat": {"view": 100000, "like": 9000, "reply": 300, "favorite": 2000, "share": 500},
                           "pages": [{"cid": 1, "part": "p1", "duration": 95}]}}
        out = _run("social_metrics", {"data": detail})
        assert out["count"] == 1
        one = out["items"][0]
        assert (one["views"], one["likes"], one["comments"], one["collects"], one["shares"]) == (100000, 9000, 300, 2000, 500)

    def test_英文摘要里没有中文标签(self) -> None:
        from app.core.i18n import CURRENT_LOCALE

        token = CURRENT_LOCALE.set("en")
        try:
            out = _run("social_metrics", {"data": DOUYIN_POSTS, "duration_unit": "milliseconds"})
        finally:
            CURRENT_LOCALE.reset(token)
        ours = out["summary"].replace("第一条 #美食", "").replace("第二条", "")
        assert not re.search(r"[一-鿿]", ours), out["summary"]
        assert "Posts counted: 2" in out["summary"]


class Test整理评论:
    def test_三个平台的评论都认得_按赞排(self) -> None:
        douyin = {"comments": [{"cid": "1", "text": "太好看了", "digg_count": 30, "user": {"nickname": "a"}},
                               {"cid": "2", "text": "哪里买", "digg_count": "1.2w", "reply_comment_total": 5}]}
        bili = {"data": {"replies": [{"rpid": 1, "content": {"message": "up主好"}, "like": 10, "member": {"uname": "x"}}]}}
        xhs = {"data": {"comments": [{"id": "c1", "content": "求链接", "like_count": "88", "sub_comment_count": 2}]}}
        assert [one["text"] for one in _run("social_metrics", {"data": douyin, "kind": "comments"})["items"]] == ["哪里买", "太好看了"]
        assert _run("social_metrics", {"data": bili, "kind": "comments"})["items"][0]["text"] == "up主好"
        assert _run("social_metrics", {"data": xhs, "kind": "comments"})["items"][0]["likes"] == 88

    def test_没有评论(self) -> None:
        out = _run("social_metrics", {"data": {"comments": []}, "kind": "comments"})
        assert out["count"] == 0 and out["table"] == ""


# --------------------------------------------------------------------------------------
# 从链接下载
# --------------------------------------------------------------------------------------


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


class Test从链接下载:
    def test_下好就入库_交出素材(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from app.media import ytdlp

        ws = _workspace()

        def download(url: str, *, kind: str, target_dir: Path, **_: object) -> Path:
            path = Path(target_dir) / "某视频 [BV1].mp4"
            path.write_bytes(b"video")
            return path

        monkeypatch.setattr(ytdlp, "download", download)
        out = _run("import_url", {"url": "https://www.bilibili.com/video/BV1xx411c7mD", "max_height": 720}, ws)
        assert out["asset_id"] and out["error"] == ""
        with unit_of_work() as db:
            asset = db.get(Asset, out["asset_id"])
            assert asset.workspace_id == ws and asset.kind == "video"
            job = db.query(Job).filter(Job.kind == "url_import", Job.workspace_id == ws).one()
            assert job.payload["max_height"] == 720

    def test_下载失败_选了不中断就交出原因(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.media import ytdlp

        ws = _workspace()

        def refuse(*_: object, **__: object) -> Path:
            raise ytdlp.YtdlpError("urlImportErr_loginRequired")

        monkeypatch.setattr(ytdlp, "download", refuse)
        out = _run("import_url", {"url": "https://www.douyin.com/video/7412345678901234567", "fail_on_error": "no"}, ws)
        assert out["asset_id"] == "" and out["error"]
        with pytest.raises(WorkflowDomainError):
            _run("import_url", {"url": "https://www.douyin.com/video/7412345678901234567"}, ws)


def test_智能体下载工具先开卡_卡上说清借谁的登录() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    bad = client.post("/api/confirmations", json={"workspace_id": ws, "tool": "import_from_url",
                                                  "payload": {"url": "file:///etc/passwd"}})
    assert bad.status_code in (400, 422), bad.text
    card = client.post("/api/confirmations", json={"workspace_id": ws, "tool": "import_from_url",
                                                   "payload": {"url": "https://www.bilibili.com/video/BV1xx411c7mD"}})
    assert card.status_code == 200, card.text
    pending = card.json()
    assert pending["permission"] == "external"
    assert "BV1xx411c7mD" in pending["summary"]
    with patch("app.domain.jobs.threading.Thread") as thread:
        approved = client.post(f"/api/confirmations/{pending['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"] and thread.called

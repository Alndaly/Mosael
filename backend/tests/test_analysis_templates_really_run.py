"""三张分析类官方模板(账号诊断、爆款拆解、评论区洞察)**整张图真跑一遍**,两条数据来源都跑。

只把**出这台机器**的那几处换成假的,而且换在最外面那一层:

- TikHub:插件是真装上的(仓库里那份清单),一个平台一条真连接、工具真勾选;运行时按「哪条连接上有这个工具」
  挑连接(plugins.nodes.resolve_instance)、插件调用记录都是真的 —— 只有 MCP 那一次网络往返(mcp_bridge._sync)是假的,
  按工具名交回各平台接口**原来的样子**(抖音的 statistics.digg_count、B 站的 play / created ……);
- 内嵌浏览器:会话、权限、关闭都是真的,只有「交给 Electron 执行器、等它回报」那一步(browser._enqueue)是假的;
- 下载:真排「从链接导入」任务,只有 yt-dlp 那一下是假的;
- 对话模型和转写:换成假的,对话的回答先按那一步的 JSON Schema 校验一遍。

其余(认链接、条件分支、整理数据算指标、汇合、存笔记、通知)全是真的执行器,走真的 `engine.execute_graph`。
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest

from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Job, Note, Workflow
from app.domain import browser
from app.domain.plugins import mcp_bridge
from app.domain.plugins import tools as tools_domain
from app.domain.workflows import WorkflowDomainError, validate_graph, with_run_params
from app.domain.workflows import executors as registry
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.templates import ModelChoice, requirement_statuses
from app.domain.workflows.templates_analysis import (
    TIKHUB_CALLS,
    TIKHUB_PLUGIN,
    account_analysis_graph,
    comment_insights_graph,
    viral_video_breakdown_graph,
)
from app.media import ytdlp
from tests.test_plugins import install

CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
CST = timezone(timedelta(hours=8))
MANIFEST = json.loads(
    (Path(__file__).resolve().parents[2] / "plugins" / "examples" / "tikhub" / "mosael.plugin.json").read_text(encoding="utf-8")
)
#: 这几个入参在 TikHub 那边是整数 —— 声明成整数,节点里填的「{{start.post_count}}」要被转成数再交出去。
_INTEGER_INPUTS = {"count", "ps", "pn"}

DOUYIN_USER = "https://www.douyin.com/user/MS4wLjABAAAAtest_sec_uid"
DOUYIN_VIDEO = "https://www.douyin.com/video/7412345678901234567"
XHS_USER = "https://www.xiaohongshu.com/user/profile/5f1e2d3c4b5a69788796a5b4"
XHS_NOTE = "https://www.xiaohongshu.com/explore/64f0a1b2c3d4e5f6a7b8c9d0"
BILI_SPACE = "https://space.bilibili.com/12345678"
BILI_VIDEO = "https://www.bilibili.com/video/BV1xx411c7mD"


def _stamp(day: int, hour: int = 20) -> int:
    return int(datetime(2026, 9, day, hour, 0, tzinfo=CST).timestamp())


# --------------------------------------------------------------------------------------
# 各平台接口原来的样子
# --------------------------------------------------------------------------------------

DOUYIN_PROFILE = {"code": 200, "data": {"user": {"nickname": "做饭的老王", "signature": "家常菜", "follower_count": 52000,
                                                  "aweme_count": 88, "total_favorited": 910000}}}
DOUYIN_POSTS = {"code": 200, "data": {"aweme_list": [
    {"aweme_id": str(day), "desc": f"第 {day} 道菜", "create_time": _stamp(day), "duration": 45000,
     "statistics": {"digg_count": 1000 * day, "comment_count": 20 * day, "collect_count": 30 * day,
                    "share_count": 5 * day, "play_count": 0},
     "music": {"title": "热门音乐"}}
    for day in (2, 5, 8, 11, 14, 17)
], "has_more": True}}
DOUYIN_DETAIL = {"code": 200, "data": {"aweme_detail": {
    "aweme_id": "7412345678901234567", "desc": "三分钟学会番茄炒蛋 #家常菜", "create_time": _stamp(20), "duration": 62000,
    "statistics": {"digg_count": 230000, "comment_count": 8800, "collect_count": 41000, "share_count": 12000, "play_count": 0},
}}}
DOUYIN_COMMENTS = {"code": 200, "data": {"comments": [
    {"cid": "c1", "text": "先放蛋还是先放番茄?", "digg_count": 5200, "user": {"nickname": "小李"}},
    {"cid": "c2", "text": "学会了,今晚就做", "digg_count": "1.1w", "reply_comment_total": 30},
], "cursor": 2}}

#: B 站主页列表:有播放、评论、时长,**没有点赞、收藏、转发**。
BILI_PROFILE = {"code": 0, "data": {"card": {"name": "某UP", "sign": "科普", "fans": 120000, "attention": 30}}}
BILI_POSTS = {"code": 0, "data": {"list": {"vlist": [
    {"bvid": f"BV{day:02d}", "title": f"科普第 {day} 期", "created": _stamp(day, 18), "length": "08:20",
     "play": "1.2万" if day < 10 else 30000 + day, "comment": 50 + day}
    for day in (1, 4, 7, 10, 13, 16)
]}}}

XHS_COMMENTS = {"code": 0, "data": {"comments": [
    {"id": "x1", "content": "这个色号显黑吗", "like_count": "320", "sub_comment_count": 12, "user_info": {"nickname": "a"}},
    {"id": "x2", "content": "求链接!!", "like_count": 88},
]}}

RESPONSES: dict[str, Any] = {
    "douyin_web_handler_user_profile": DOUYIN_PROFILE,
    "douyin_web_fetch_user_post_videos": DOUYIN_POSTS,
    "douyin_web_fetch_one_video": DOUYIN_DETAIL,
    "douyin_web_fetch_video_comments": DOUYIN_COMMENTS,
    "bilibili_web_fetch_user_profile": BILI_PROFILE,
    "bilibili_web_fetch_user_post_videos": BILI_POSTS,
    "xiaohongshu_app_v2_get_note_comments": XHS_COMMENTS,
}


# --------------------------------------------------------------------------------------
# 外面的世界(假的那几处)
# --------------------------------------------------------------------------------------


class Outside:
    """记下每一次出这台机器的调用。`answers` 按 json_schema_name 给对话节点的回答;`pages` 是浏览器读到的页面文字。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any], *, page_text: str = "页面文字",
                 responses: dict[str, Any] | None = None, download_fails: bool = False,
                 page_value: dict[str, Any] | None = None) -> None:
        # 评论洞察的分批笔记是每次必跑的步骤,缺省回答在这;具体测试自己的 schema 照常传。
        self.answers = {"comment_insights_batch": BATCH_NOTE, **answers}
        self.page_text = page_text
        #: 读页面那段脚本交回的整个值;不给就是「读 DOM」那一支的样子(页面文字)。
        self.page_value = page_value
        self.responses = {**RESPONSES, **(responses or {})}
        self.calls: dict[str, list[Any]] = defaultdict(list)
        self.download_fails = download_fails
        monkeypatch.setitem(registry._REGISTRY, "llm", self.llm)
        monkeypatch.setitem(registry._REGISTRY, "transcribe_asset", self.transcribe)
        monkeypatch.setattr(browser, "_enqueue", self.browser_action)
        monkeypatch.setattr(mcp_bridge, "_sync", self.mcp)
        monkeypatch.setattr(ytdlp, "download", self.download)

    def llm(self, db, scope, config):
        name = config["json_schema_name"]
        answer = self.answers[name]
        #: 假回答也得是这一步要的形状 —— 否则测的是一张模板里根本不会出现的数据。
        jsonschema.validate(answer, config["json_schema"])
        self.calls["llm"].append({"name": name, "system": config["system"], "prompt": config["prompt"]})
        return {"text": json.dumps(answer, ensure_ascii=False), "json": answer, "response_format_used": "json_schema"}

    def transcribe(self, db, scope, config):
        self.calls["transcribe"].append(config["asset_id"])
        segments = [{"start": 0.0, "end": 2.8, "text": "番茄炒蛋最容易错的一步"}, {"start": 2.8, "end": 9.0, "text": "是先放蛋"}]
        return {"text": "番茄炒蛋最容易错的一步是先放蛋", "timed_text": json.dumps(segments, ensure_ascii=False),
                "segments": segments, "language": "zh", "transcript_id": "t1", "duration": 62.0}

    def browser_action(self, session_id, action, args, **_kwargs):
        self.calls["browser"].append((action, dict(args or {})))
        if action == "evaluate":
            if self.page_value is not None:
                return {"value": self.page_value}
            return {"value": {"url": "https://example", "title": "页面", "now": "2026-10-01T12:00:00+08:00",
                              "text": self.page_text}}
        return {}

    def mcp(self, _manifest, _env, fn, **_kwargs):
        outside = self

        class Session:
            async def call_tool(self, name, arguments):
                outside.calls["tikhub"].append((name, dict(arguments)))
                #: TikHub 的 FastMCP 把返回值包成 `{"result": "<JSON 文本>"}`。
                return SimpleNamespace(is_error=False, structured_content={"result": json.dumps(outside.responses[name])},
                                       content=[])

        return asyncio.run(fn(Session()))

    def download(self, url, *, kind, target_dir, cookie_file=None, **_kwargs):
        self.calls["download"].append({"url": url, "cookies": cookie_file is not None})
        if self.download_fails:
            raise ytdlp.YtdlpError("urlImportErr_loginRequired")
        path = Path(target_dir) / "video.mp4"
        path.write_bytes(b"video")
        return path


def _tikhub(client, platforms: tuple[str, ...] = ("douyin", "xiaohongshu", "bilibili"), *, enable_tools: bool = True,
            twice: str = "") -> None:
    """一个平台一条 TikHub 连接:配平台、填 key、授网络权限、启用,勾上这几个模板要用的工具。"""
    for platform in platforms + ((twice,) if twice else ()):
        created = client.post(f"/api/plugins/{TIKHUB_PLUGIN}/instances", json={"config": {"TIKHUB_PLATFORM": platform}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/credentials", json={"values": {"TIKHUB_API_KEY": "k"}})
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": {"network:tikhub": True}})
        enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        if enable_tools:
            tools = {tool: True for tool, _ in TIKHUB_CALLS[platform].values()}
            client.patch(f"/api/plugins/instances/{instance_id}/capabilities", json={"tools": tools})


@pytest.fixture
def tikhub_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 服务报出的工具清单:每个平台的端点只报这个平台的工具(和 TikHub 实际一样)。"""

    def discover(_manifest, env, *_args, **_kwargs):
        return [
            {"name": tool, "title": "", "description": tool, "input_schema": {
                "type": "object",
                "properties": {key: {"type": "integer" if key in _INTEGER_INPUTS else "string"} for key in inputs},
            }}
            for tool, inputs in TIKHUB_CALLS[env["TIKHUB_PLATFORM"]].values()
        ]

    monkeypatch.setattr(tools_domain, "discover_tools", discover)


def _setup(*, with_tikhub: bool, **kwargs: Any) -> tuple[str, str]:
    """(工作区, 第一个用户)。插件目录是仓库里那份 TikHub 清单;要不要接连接由 with_tikhub 定。"""
    from app.db.models import User

    client = install(MANIFEST)
    if with_tikhub:
        _tikhub(client, **kwargs)
    workspace = client.get("/api/workspaces").json()[0]["id"]
    with SessionLocal() as db:
        user = db.query(User).order_by(User.created_at).first()
        return workspace, user.id


def _run(ws: str, graph: dict[str, Any], **params: Any) -> dict[str, Any]:
    #: 先过运行前的那一道(和真按下运行时同一份判据,连同这一次带的参数)。
    errors = validate_graph(with_run_params(graph, params))
    assert errors == [], errors
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="分析", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    context, cancelled = execute_graph(graph, wf_id=wf_id, params=params)
    assert not cancelled
    return context


def _notes(ws: str) -> list[Note]:
    with unit_of_work() as db:
        notes = db.query(Note).filter(Note.workspace_id == ws).all()
        for note in notes:
            db.expunge(note)
        return notes


def _note_text(note: Note) -> str:
    return json.dumps({"title": note.title, "body": getattr(note, "markdown", None) or getattr(note, "content", None)
                       or getattr(note, "body", None)}, ensure_ascii=False)


def _report(title: str) -> dict[str, Any]:
    return {"title": title, "verdict": "更新稳定,互动在涨", "report_markdown": "## 现状概览\n……"}


BREAKDOWN = {"title": "番茄炒蛋 · 爆款拆解", "verdict": "一个反常识的钩子", "report_markdown": "## 钩子\n……",
             "script_outline_markdown": "1. 钩子……"}
BATCH_NOTE = {"notes_markdown": "这批在问色号与价格。", "standout_comments": ["这个色号显黑吗"]}

INSIGHT = {"title": "色号 · 评论区洞察", "verdict": "大家最关心显不显黑", "report_markdown": "## 大家在聊什么\n……",
           "reply_suggestions_markdown": "- 回复……"}


# --------------------------------------------------------------------------------------
# 1 · 账号运营诊断
# --------------------------------------------------------------------------------------


class Test账号诊断真跑:
    def test_TikHub_抖音_按平台取资料和作品_算好的指标交给报告_存成笔记(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {"account_diagnosis": _report("做饭的老王 · 运营诊断")})
        context = _run(ws, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub", post_count=20)

        assert [name for name, _ in outside.calls["tikhub"]] == ["douyin_web_handler_user_profile", "douyin_web_fetch_user_post_videos"]
        posts_call = outside.calls["tikhub"][1][1]
        assert posts_call == {"sec_user_id": "MS4wLjABAAAAtest_sec_uid", "count": 20}, "条数要按整数交给 TikHub"
        assert outside.calls["browser"] == [], "走 TikHub 时不该开浏览器"

        metrics = context["dy_metrics"]
        assert metrics["count"] == 6 and metrics["items"][0]["duration_seconds"] == 45.0, "抖音的时长是毫秒"
        assert metrics["account"]["followers"] == 52000
        assert metrics["stats"]["trend"]["signal"] == "growing"

        [report] = outside.calls["llm"]
        assert report["name"] == "account_diagnosis"
        assert "做饭的老王" in report["prompt"] and "每周发布" in report["prompt"], "报告要拿到算好的指标,不是自己算"
        assert "第 17 道菜" in report["prompt"], "逐条明细也要给到"
        [note] = _notes(ws)
        assert note.title == "做饭的老王 · 运营诊断"
        assert "附:关键数据" in _note_text(note)

    def test_TikHub_B站_缺点赞的数据照样诊断_报告里说清缺什么(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {"account_diagnosis": _report("某UP · 运营诊断")})
        context = _run(ws, account_analysis_graph(chat=CHAT), account_link=BILI_SPACE, data_source="tikhub")
        assert [args for _, args in outside.calls["tikhub"]][0] == {"uid": "12345678"}
        metrics = context["bili_metrics"]
        assert set(metrics["stats"]["missing"]) >= {"likes", "collects", "shares"}
        assert metrics["items"][-1]["views"] == 12000 and metrics["items"][-1]["duration_seconds"] == 500
        assert "取不到的字段" in outside.calls["llm"][0]["prompt"]

    def test_浏览器_小红书_页面文字抄成清单再整理_不装TikHub也能跑(self, monkeypatch) -> None:
        ws, _ = _setup(with_tikhub=False)
        page = {
            "account": {"name": "穿搭日记", "handle": "123", "bio": "", "followers": "3.4万", "following": "", "likes_total": "", "posts_total": ""},
            "posts": [
                {"title": "秋天第一套", "published_at": "2026-09-28", "duration": "", "views": "", "likes": "1.2万",
                 "comments": "320", "collects": "4500", "shares": ""},
                {"title": "通勤怎么穿", "published_at": "", "duration": "", "views": "", "likes": "860",
                 "comments": "12", "collects": "", "shares": ""},
            ],
            "login_wall": False, "notes": "",
        }
        outside = Outside(monkeypatch, {"account_page": page, "account_diagnosis": _report("穿搭日记 · 运营诊断")},
                          page_text="穿搭日记 3.4万粉丝 秋天第一套 1.2万 ……")
        context = _run(ws, account_analysis_graph(chat=CHAT), account_link=XHS_USER, data_source="browser")

        actions = [action for action, _ in outside.calls["browser"]]
        assert actions == ["navigate", "evaluate"], actions
        assert outside.calls["browser"][0][1]["url"] == XHS_USER
        assert outside.calls["tikhub"] == []
        with unit_of_work() as db:
            from app.db.models import BrowserSession

            assert db.query(BrowserSession).filter(BrowserSession.status == "open").count() == 0, "读完要关掉"
        page_call, report = outside.calls["llm"]
        assert page_call["name"] == "account_page" and "1.2万" in page_call["prompt"]
        assert "2026-10-01" in page_call["prompt"], "相对时间要按读取时间换算 —— 得把读取时间给到"
        metrics = context["web_metrics"]
        assert metrics["items"][0]["likes"] == 12000 and metrics["account"]["followers"] == 34000
        assert "published_at" not in metrics["stats"]["missing"], "有一条带了时间"
        assert "穿搭日记" in report["prompt"]
        assert len(_notes(ws)) == 1

    def test_一条作品都没取到_说清原因_不写报告也不存笔记(self, monkeypatch) -> None:
        ws, _ = _setup(with_tikhub=False)
        page = {"account": {key: "" for key in ("name", "handle", "bio", "followers", "following", "likes_total", "posts_total")},
                "posts": [], "login_wall": True, "notes": "页面是登录框"}
        outside = Outside(monkeypatch, {"account_page": page})
        context = _run(ws, account_analysis_graph(chat=CHAT), account_link=XHS_USER, data_source="browser")
        assert [one["name"] for one in outside.calls["llm"]] == ["account_page"], "没有作品还去写报告,只能编"
        assert "no_posts_notice" in context and "report" not in context
        assert _notes(ws) == []

    def test_TikHub_不认的平台_停下说清_不调任何工具(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {})
        context = _run(ws, account_analysis_graph(chat=CHAT), account_link="https://www.kuaishou.com/profile/3xabc",
                       data_source="tikhub")
        assert context["link"]["platform"] == "kuaishou"
        assert "tk_unsupported" in context
        assert outside.calls["tikhub"] == [] and outside.calls["llm"] == []

    def test_选了TikHub却没接_失败时说的是去接连接(self, monkeypatch) -> None:
        ws, _ = _setup(with_tikhub=False)
        Outside(monkeypatch, {})
        with pytest.raises(WorkflowDomainError) as caught:
            _run(ws, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")
        assert "TikHub" in str(caught.value), str(caught.value)

    def test_没填链接和数据来源_运行前就拦(self) -> None:
        errors = validate_graph(account_analysis_graph(chat=CHAT))
        assert "「填账号与数据来源」缺少必填:account_link" in errors, errors
        assert "「填账号与数据来源」缺少必填:data_source" in errors, errors


# --------------------------------------------------------------------------------------
# 2 · 爆款拆解
# --------------------------------------------------------------------------------------


class Test爆款拆解真跑:
    def test_TikHub_抖音_详情和评论_下载转写_拆解拿到逐字稿(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {"viral_breakdown": BREAKDOWN})
        context = _run(ws, viral_video_breakdown_graph(chat=CHAT), video_link=DOUYIN_VIDEO, data_source="tikhub",
                       my_topic="凉拌黄瓜")

        assert sorted(name for name, _ in outside.calls["tikhub"]) == ["douyin_web_fetch_one_video", "douyin_web_fetch_video_comments"]
        assert dict(outside.calls["tikhub"])["douyin_web_fetch_one_video"] == {"aweme_id": "7412345678901234567"}
        video = context["dy_video_m"]["items"][0]
        assert (video["likes"], video["collects"], video["duration_seconds"]) == (230000, 41000, 62.0)
        assert [one["text"] for one in context["dy_comments_m"]["items"]] == ["学会了,今晚就做", "先放蛋还是先放番茄?"]

        assert outside.calls["download"] == [{"url": DOUYIN_VIDEO, "cookies": False}]
        assert len(outside.calls["transcribe"]) == 1
        [breakdown] = outside.calls["llm"]
        assert "番茄炒蛋最容易错的一步" in breakdown["prompt"] and '"start": 0.0' in breakdown["prompt"], "要带时间码才谈得上前 3 秒"
        assert "先放蛋还是先放番茄" in breakdown["prompt"]
        assert "凉拌黄瓜" in breakdown["system"]
        [note] = _notes(ws)
        assert note.title == "番茄炒蛋 · 爆款拆解"
        assert "口播逐字稿" in _note_text(note) and "照这个套路做一条" in _note_text(note)

    def test_浏览器_B站_下载失败照样拆_原因交给模型(self, monkeypatch) -> None:
        ws, _ = _setup(with_tikhub=False)
        page = {"video": {"title": "一分钟讲清黑洞", "published_at": "2026-09-30", "duration": "01:05", "views": "35.2万",
                          "likes": "2.1万", "comments": "1890", "collects": "8000", "shares": "900", "author": "某UP",
                          "description": "#科普"},
                "comments": [{"text": "讲得太清楚了", "likes": "3000", "author": "", "published_at": ""}],
                "login_wall": False, "notes": ""}
        outside = Outside(monkeypatch, {"video_page": page, "viral_breakdown": BREAKDOWN}, download_fails=True)
        context = _run(ws, viral_video_breakdown_graph(chat=CHAT), video_link=BILI_VIDEO, data_source="browser")

        assert context["web_video_m"]["items"][0]["views"] == 352000
        assert context["download"]["asset_id"] == "" and context["download"]["error"]
        assert outside.calls["transcribe"] == [] and "transcript" not in context
        breakdown = outside.calls["llm"][-1]
        assert breakdown["name"] == "viral_breakdown"
        assert "登录" in breakdown["prompt"] or "sign" in breakdown["prompt"].lower(), "没有逐字稿的原因要告诉模型"
        assert "讲得太清楚了" in breakdown["prompt"]
        assert len(_notes(ws)) == 1

    def test_浏览器_B站走接口那一支_视频数据和评论都直接整理(self, monkeypatch) -> None:
        """读页面的脚本在 B 站视频页上**优先调它自己的接口**(mode=api):交回的是评论清单,不是页面文字。

        实测撞到:这一支是给评论区洞察加的,爆款拆解没跟上 —— 它把评论 JSON 当「页面文字」交给模型抄视频数据,
        页面文字里根本没有播放、点赞、时长,于是视频数据全空,`has_video` 不成立,整条拆解停在「没取到这条视频」。
        脚本那一支现在顺手把 view 接口里的视频数据带回来(`video`),拆解按 mode 分支直接整理,不再让模型抄。
        """
        ws, _ = _setup(with_tikhub=False)
        view = {"bvid": "BV1xx411c7mD", "aid": 2, "title": "字幕君交流场所", "pubdate": _stamp(9), "duration": 2055,
                "desc": "www", "owner": {"name": "碧诗"},
                "stat": {"view": 5531373, "like": 276830, "reply": 89327, "favorite": 127298, "share": 9100}}
        comments = [{"author": "碧诗", "text": "wwwww", "likes": 54669, "published_at": "2010-12-09"}]
        page = {"url": BILI_VIDEO, "title": "字幕君交流场所_哔哩哔哩_bilibili", "now": "2026-10-04T03:30:00+08:00",
                "mode": "api", "total": 89327, "expanded": -1, "video": view,
                "text": json.dumps({"total": 89327, "comments": comments}, ensure_ascii=False)}
        outside = Outside(monkeypatch, {"viral_breakdown": BREAKDOWN}, page_value=page)
        context = _run(ws, viral_video_breakdown_graph(chat=CHAT), video_link=BILI_VIDEO, data_source="browser",
                       download_video="no")

        assert [call["name"] for call in outside.calls["llm"]] == ["viral_breakdown"], "接口取回的是结构化数据,不该再让模型抄一遍"
        video = context["web_api_video_m"]["items"][0]
        assert (video["views"], video["likes"], video["duration_seconds"]) == (5531373, 276830, 2055.0)
        assert [one["text"] for one in context["web_api_comments_m"]["items"]] == ["wwwww"]
        assert context["has_video"]["result"] is True and "no_video_notice" not in context
        breakdown = outside.calls["llm"][-1]
        assert "字幕君交流场所" in breakdown["prompt"] and "wwwww" in breakdown["prompt"]

    def test_读页面脚本的B站接口那一支_带回视频数据(self) -> None:
        """脚本在浏览器里跑、这里跑不了它 —— 至少钉住接口那一支交回的值里有 view 接口的视频数据。"""
        from app.domain.workflows.templates_analysis import _READ_PAGE_SCRIPT

        api_return = _READ_PAGE_SCRIPT[_READ_PAGE_SCRIPT.index('mode: "api"') - 200:_READ_PAGE_SCRIPT.index('mode: "api"') + 300]
        assert "video" in api_return, api_return

    def test_不下载视频时_不排下载任务(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {"viral_breakdown": BREAKDOWN})
        context = _run(ws, viral_video_breakdown_graph(chat=CHAT), video_link=DOUYIN_VIDEO, data_source="tikhub",
                       download_video="no")
        assert outside.calls["download"] == [] and "download" not in context
        with unit_of_work() as db:
            assert db.query(Job).filter(Job.kind == "url_import").count() == 0
        assert len(outside.calls["llm"]) == 1

    def test_没取到这条视频_停下说清(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {}, responses={"douyin_web_fetch_one_video": {"code": 200, "data": {}},
                                                      "douyin_web_fetch_video_comments": {"code": 200, "data": {"comments": []}}})
        context = _run(ws, viral_video_breakdown_graph(chat=CHAT), video_link=DOUYIN_VIDEO, data_source="tikhub")
        assert "no_video_notice" in context
        assert outside.calls["llm"] == [] and outside.calls["download"] == []


# --------------------------------------------------------------------------------------
# 3 · 评论区洞察
# --------------------------------------------------------------------------------------


class Test评论区洞察真跑:
    def test_TikHub_小红书_评论按赞排好交给洞察(self, monkeypatch, tikhub_tools) -> None:
        ws, _ = _setup(with_tikhub=True)
        outside = Outside(monkeypatch, {"comment_insights": INSIGHT})
        context = _run(ws, comment_insights_graph(chat=CHAT), video_link=XHS_NOTE, data_source="tikhub", focus="色号")
        assert outside.calls["tikhub"] == [("xiaohongshu_app_v2_get_note_comments",
                                            {"note_id": "64f0a1b2c3d4e5f6a7b8c9d0", "share_text": XHS_NOTE})]
        assert [one["likes"] for one in context["xhs_comments_m"]["items"]] == [320, 88]
        [insight] = [call for call in outside.calls["llm"] if call["name"] == "comment_insights"]
        assert "这个色号显黑吗" in insight["prompt"] and "色号" in insight["prompt"]
        [note] = _notes(ws)
        assert "建议回复" in _note_text(note)

    def test_浏览器没读到评论_说清是不是要登录(self, monkeypatch) -> None:
        ws, _ = _setup(with_tikhub=False)
        outside = Outside(monkeypatch, {"comments_page": {"title": "", "comments": [], "login_wall": True, "notes": "登录后查看评论"}})
        context = _run(ws, comment_insights_graph(chat=CHAT), video_link=XHS_NOTE, data_source="browser")
        assert "no_comments_notice" in context and "insight" not in context
        assert [one["name"] for one in outside.calls["llm"]] == ["comments_page"]


# --------------------------------------------------------------------------------------
# 前置检查和运行时同一个判据
# --------------------------------------------------------------------------------------


class Test前置检查:
    def _statuses(self, ws: str, user: str) -> dict[str, str]:
        with SessionLocal() as db:
            return requirement_statuses(db, user_id=user, workspace_id=ws)

    def test_没装TikHub_三项都说缺(self) -> None:
        ws, user = _setup(with_tikhub=False)
        statuses = self._statuses(ws, user)
        assert {statuses[key] for key in ("tikhub_account", "tikhub_video", "tikhub_comments")} == {"missing"}

    def test_接了一个平台并勾了工具_就说齐(self, tikhub_tools) -> None:
        ws, user = _setup(with_tikhub=True, platforms=("bilibili",))
        statuses = self._statuses(ws, user)
        assert statuses["tikhub_account"] == statuses["tikhub_video"] == statuses["tikhub_comments"] == "met"

    def test_接了却没勾工具_说缺_运行时也确实用不了(self, monkeypatch, tikhub_tools) -> None:
        ws, user = _setup(with_tikhub=True, platforms=("douyin",), enable_tools=False)
        assert self._statuses(ws, user)["tikhub_account"] == "missing"
        Outside(monkeypatch, {})
        with pytest.raises(WorkflowDomainError):
            _run(ws, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")

    def test_同一个平台接了两条_运行时不猜_检查也不说齐(self, monkeypatch, tikhub_tools) -> None:
        ws, user = _setup(with_tikhub=True, platforms=("douyin",), twice="douyin")
        assert self._statuses(ws, user)["tikhub_account"] == "missing"
        Outside(monkeypatch, {})
        with pytest.raises(WorkflowDomainError):
            _run(ws, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")

    def test_目录里数据来源是一组_满足一条就够(self) -> None:
        from tests.util import fresh_client

        templates = fresh_client().get("/api/workflows/templates").json()
        for template_id, check in (("account_analysis", "tikhub_account"), ("viral_video_breakdown", "tikhub_video"),
                                   ("comment_insights", "tikhub_comments")):
            card = next(one for one in templates if one["id"] == template_id)
            group = [one for one in card["requirements"] if one["group"] == "data_source"]
            assert [one["check"] for one in group] == [check, ""], "TikHub 一条、内嵌浏览器一条"
            assert all(not one["optional"] for one in group)


# --------------------------------------------------------------------------------------
# 数据来源是选项参数:下拉里两项,按值直接分支,运行前只查选中的那一项
# --------------------------------------------------------------------------------------

GRAPHS = {
    "account_analysis": (account_analysis_graph, "account_link", DOUYIN_USER, "tikhub_account"),
    "viral_video_breakdown": (viral_video_breakdown_graph, "video_link", DOUYIN_VIDEO, "tikhub_video"),
    "comment_insights": (comment_insights_graph, "video_link", DOUYIN_VIDEO, "tikhub_comments"),
}


def _start(graph: dict[str, Any]) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["type"] == "start")["config"]


def _check(ws: str, user: str, graph: dict[str, Any], **params: Any) -> None:
    from app.domain.workflows.engine import check_runnable

    with SessionLocal() as db:
        check_runnable(db, graph, params, user, workspace_id=ws)


class Test数据来源是选项:
    @pytest.mark.parametrize("template_id", list(GRAPHS))
    def test_两个选项_必填_默认空着_TikHub那一项写明要什么(self, template_id: str) -> None:
        build, _, _, check = GRAPHS[template_id]
        start = _start(build(chat=CHAT))
        options = start["param_options"]["data_source"]
        assert [one["value"] for one in options] == ["browser", "tikhub"]
        assert all(one["label"] and one["description"] for one in options)
        assert [one.get("requires") for one in options] == [None, check], "浏览器那一项什么都不用配"
        assert start["params"]["data_source"] == "" and "data_source" in start["required_params"]

    @pytest.mark.parametrize("template_id", list(GRAPHS))
    def test_按值直接分支_没有转小写那一步(self, template_id: str) -> None:
        build = GRAPHS[template_id][0]
        graph = build(chat=CHAT)
        nodes = {node["id"]: node for node in graph["nodes"]}
        assert "source_mode" not in nodes and not [node for node in graph["nodes"] if node["type"] == "text_transform"]
        assert nodes["use_tikhub"]["config"] == {"left": "{{start.data_source}}", "op": "equals", "right": "tikhub"}
        assert graph["meta"]["template_version"] >= 2, "选项参数是第 2 版起的,旧图走「按新版重建」"

    @pytest.mark.parametrize("template_id", list(GRAPHS))
    def test_打错字_运行前就拦_说出能选哪几个(self, template_id: str) -> None:
        build, link, url, _ = GRAPHS[template_id]
        graph = build(chat=CHAT)
        title = next(node for node in graph["nodes"] if node["type"] == "start")["name"]["zh"]
        errors = validate_graph(with_run_params(graph, {link: url, "data_source": "TikHub"}))
        assert errors == [f"「{title}」的参数 data_source 是「TikHub」,只能选:browser(内嵌浏览器)、tikhub(TikHub)"], errors

    @pytest.mark.parametrize("template_id", list(GRAPHS))
    def test_选了TikHub而没装_运行前当场拦_说清去装或改选浏览器(self, template_id: str) -> None:
        build, link, url, _ = GRAPHS[template_id]
        ws, user = _setup(with_tikhub=False)
        with pytest.raises(WorkflowDomainError) as caught:
            _check(ws, user, build(chat=CHAT), **{link: url, "data_source": "tikhub"})
        message = str(caught.value)
        assert "没装 TikHub 插件" not in message, "仓库那份清单装上了:说的该是去接连接"
        assert "还没接 TikHub" in message and "内嵌浏览器" in message, message

    def test_没装插件_说去装(self) -> None:
        from tests.util import fresh_client

        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        from app.db.models import User

        with SessionLocal() as db:
            user = db.query(User).order_by(User.created_at).first().id
        with pytest.raises(WorkflowDomainError) as caught:
            _check(ws, user, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")
        assert "没装 TikHub 插件" in str(caught.value)

    def test_接了却没勾工具_拦下时点名连接和要勾的工具(self, tikhub_tools) -> None:
        ws, user = _setup(with_tikhub=True, platforms=("douyin",), enable_tools=False)
        with pytest.raises(WorkflowDomainError) as caught:
            _check(ws, user, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")
        message = str(caught.value)
        assert "douyin_web_handler_user_profile" in message and "没有勾选" in message, message

    def test_连接停用_拦下时点名那条连接卡在哪(self, tikhub_tools) -> None:
        from app.core.i18n import tr
        from app.db.models import PluginInstance

        ws, user = _setup(with_tikhub=True, platforms=("douyin",))
        with SessionLocal() as db:
            for one in db.query(PluginInstance).all():
                one.enabled = False
            db.commit()
        with pytest.raises(WorkflowDomainError) as caught:
            _check(ws, user, account_analysis_graph(chat=CHAT), account_link=DOUYIN_USER, data_source="tikhub")
        assert tr("pluginBlocked_disabled") in str(caught.value), str(caught.value)

    @pytest.mark.parametrize("template_id", list(GRAPHS))
    def test_选浏览器_不查TikHub(self, template_id: str) -> None:
        build, link, url, _ = GRAPHS[template_id]
        ws, user = _setup(with_tikhub=False)
        _check(ws, user, build(chat=CHAT), **{link: url, "data_source": "browser"})

    def test_TikHub备好了_选它也过(self, tikhub_tools) -> None:
        ws, user = _setup(with_tikhub=True, platforms=("bilibili",))
        _check(ws, user, account_analysis_graph(chat=CHAT), account_link=BILI_SPACE, data_source="tikhub")

    def test_按新版重建_手填过的数据来源只带选项里有的值(self) -> None:
        from tests.util import fresh_client

        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        created = client.post("/api/workflows", json={"workspace_id": ws, "name": "诊断", "template_id": "account_analysis"}).json()
        for typed, carried in (("TikHub", ""), ("tikhub", "tikhub"), ("浏览器", "")):
            old = json.loads(json.dumps(created["graph"]))
            old["meta"]["template_version"] = 1
            _start(old)["params"].update({"data_source": typed, "account_link": DOUYIN_USER})
            saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "旧版", "graph": old})
            assert saved.status_code == 200, saved.text
            rebuilt = client.post(f"/api/workflows/{saved.json()['id']}/rebuild-from-template")
            assert rebuilt.status_code == 200, rebuilt.text
            params = _start(rebuilt.json()["graph"])["params"]
            assert params["data_source"] == carried, typed
            assert params["account_link"] == DOUYIN_USER, "别的开始参数照旧带过去"

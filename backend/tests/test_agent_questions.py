"""智能体在岔路口问用户挑一个。

两三条路都说得通、而选哪条取决于用户想要什么时,模型自己挑一条一路做下去,做错了要推翻的是
一整段工作。摊开来点一下便宜得多。

**和确认卡是两件事,所以各有各的表。** 确认卡问「这件事能不能做」,有 auto_allow 和 bypass
可以自动批准;询问问「你要哪一个」—— 自动回答等于让模型自己编一个答案。共用一张表的话,
那两个开关迟早会把问题一起自动答掉,而现象是「它没问我就动手了」。

校验校得严,是因为**这些字段直接进界面**:没有 label 的选项渲染成一个点不动的空按钮,
重复的 label 让答案对不回是哪一个。模型偶尔会犯这些错,而它们的表现都不是报错,是界面坏掉。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import AgentQuestion
from app.domain.agent import questions as q
from tests.util import fresh_client


def _ok(**over):
    base = {
        "header": "去向",
        "question": "这段成片发到哪儿?",
        "options": [{"label": "B站", "description": "投稿到已登录的账号"}, {"label": "先不发"}],
    }
    return [{**base, **over}]


class Test校验:
    def test_合法的问题过得去(self) -> None:
        out = q.normalize(_ok())
        assert out[0]["question"] == "这段成片发到哪儿?"
        assert [o["label"] for o in out[0]["options"]] == ["B站", "先不发"]
        assert out[0]["multi_select"] is False

    def test_至少两个选项(self) -> None:
        """只有一个的话不必问 —— 那是在走过场。"""
        with pytest.raises(q.QuestionError, match="至少要给 2 个选项"):
            q.normalize(_ok(options=[{"label": "只有一个"}]))

    def test_选项不能没有_label(self) -> None:
        """空的会渲染成一个点不动的按钮 —— 用户以为界面坏了。"""
        with pytest.raises(q.QuestionError, match="label 不能为空"):
            q.normalize(_ok(options=[{"label": "A"}, {"description": "忘了写 label"}]))

    def test_选项不能重名(self) -> None:
        """答案按 label 回传,重名就分不出用户点的是哪一个。"""
        with pytest.raises(q.QuestionError, match="选项重名"):
            q.normalize(_ok(options=[{"label": "同一个"}, {"label": "同一个"}]))

    def test_问题不能重复(self) -> None:
        """答案按问题正文归位,重复就对不回去。"""
        with pytest.raises(q.QuestionError, match="问题重复"):
            q.normalize(_ok() + _ok())

    def test_一次别问太多(self) -> None:
        many = [{**_ok()[0], "question": f"第 {i} 问"} for i in range(5)]
        with pytest.raises(q.QuestionError, match="最多问"):
            q.normalize(many)

    def test_选项也有上限(self) -> None:
        with pytest.raises(q.QuestionError, match="最多"):
            q.normalize(_ok(options=[{"label": f"选项{i}"} for i in range(7)]))

    def test_超长的_header_截断而不是报错(self) -> None:
        """它只是卡片上一个小标签,不值得为它让整次询问失败;但长了会把卡片撑破。"""
        out = q.normalize(_ok(header="这是一个非常非常长的标签会把卡片撑破"))
        assert len(out[0]["header"]) <= q.MAX_HEADER_CHARS

    def test_空清单不行(self) -> None:
        with pytest.raises(q.QuestionError, match="非空"):
            q.normalize([])


class Test回答:
    def _row(self, client) -> tuple[str, AgentQuestion]:
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        sid = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        with SessionLocal() as db:
            row = q.ask(db, workspace_id=ws, session_id=sid, questions=_ok())
            return row.id, row

    def test_记下选了什么(self) -> None:
        client = fresh_client()
        qid, _ = self._row(client)
        with SessionLocal() as db:
            row = db.get(AgentQuestion, qid)
            q.answer(db, row, {"这段成片发到哪儿?": ["B站"]})
            assert row.status == "answered"
            assert row.answers == {"这段成片发到哪儿?": ["B站"]}

    def test_单选也存成列表(self) -> None:
        """两种形状分开存的话,消费端要写两遍解析 —— 而漏掉的那一遍会在多选时炸。"""
        client = fresh_client()
        qid, _ = self._row(client)
        with SessionLocal() as db:
            row = db.get(AgentQuestion, qid)
            q.answer(db, row, {"这段成片发到哪儿?": "B站"})
            assert row.answers["这段成片发到哪儿?"] == ["B站"]

    def test_没问过的问题不收(self) -> None:
        """界面之外的调用方塞进来的东西,不该变成模型看到的「用户说的话」。"""
        client = fresh_client()
        qid, _ = self._row(client)
        with SessionLocal() as db:
            row = db.get(AgentQuestion, qid)
            with pytest.raises(q.QuestionError, match="没有问过"):
                q.answer(db, row, {"我自己编的问题": ["随便"]})

    def test_不能答两次(self) -> None:
        client = fresh_client()
        qid, _ = self._row(client)
        with SessionLocal() as db:
            row = db.get(AgentQuestion, qid)
            q.answer(db, row, {"这段成片发到哪儿?": ["B站"]})
            with pytest.raises(q.QuestionError, match="已经回答过"):
                q.answer(db, row, {"这段成片发到哪儿?": ["先不发"]})

    def test_跳过之后不再是_pending(self) -> None:
        """模型该继续往下走,而不是卡在那儿等一个不会来的答案。"""
        client = fresh_client()
        qid, _ = self._row(client)
        with SessionLocal() as db:
            row = db.get(AgentQuestion, qid)
            q.dismiss(db, row)
            assert row.status == "dismissed"
            assert q.pending_for(db, row.session_id) == []


class Test不会被自动回答:
    def test_询问不在确认卡那套里(self) -> None:
        """**这是分成两张表的全部理由。**

        确认卡有 auto_allow_tools 和 bypass 模式。ask_user 一旦进了 CONFIRMATION_TOOLS,
        开了自动批准的会话里,「你要哪一个」会被自动答掉 —— 而模型收到的是一个它自己编的
        答案,现象是「它没问我就动手了」。
        """
        import mcp_server

        assert "ask_user" not in mcp_server.CONFIRMATION_TOOLS
        assert "ask_user" in mcp_server.READ_ONLY_TOOLS, "问一句话不改任何东西,该是只读"


class Test接口:
    def test_形状不对回_422_而不是_500(self) -> None:
        """这是模型给错了形状,消息里要说清怎么改 —— 它下一步就是改了重发。"""
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        sid = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        res = client.post(
            "/api/agent/questions",
            json={"workspace_id": ws, "session_id": sid, "questions": _ok(options=[{"label": "就一个"}])},
        )
        assert res.status_code == 422
        assert "至少要给 2 个选项" in res.json()["detail"]

    def test_待答清单按会话取(self) -> None:
        """一个问题脱离它的上下文没有意义 —— 别的对话不该看到它。"""
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        mine = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        other = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        client.post("/api/agent/questions", json={"workspace_id": ws, "session_id": mine, "questions": _ok()})

        assert len(client.get(f"/api/agent/questions?session_id={mine}").json()) == 1
        assert client.get(f"/api/agent/questions?session_id={other}").json() == []

    def test_答完就不在待答里了(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        sid = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        qid = client.post(
            "/api/agent/questions", json={"workspace_id": ws, "session_id": sid, "questions": _ok()}
        ).json()["id"]

        res = client.post(f"/api/agent/questions/{qid}/answer", json={"answers": {"这段成片发到哪儿?": ["B站"]}})
        assert res.status_code == 200 and res.json()["status"] == "answered"
        assert client.get(f"/api/agent/questions?session_id={sid}").json() == []

"""任务干完了,回执要送回发起它的那次对话。

智能体提交一次生成之后就断了线索:它只知道「提交成功」,不知道跑完没有。表现是两种,
哪一种都不好 —— 要么反复 get_job 轮询(用户看着它一遍遍查同一件事),要么干脆当作没这回事,
让用户自己回来问「好了吗」。而任务这一层本来就知道自己什么时候结束。

**方向必须是反的**:任务域不认识智能体,是智能体在装配时把自己登记进去。反过来写的话,
发布、导出、转写都会因为「智能体也许想知道」而依赖上智能体域,而任务是更底下那一层。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain import jobs as jobs_domain
from tests.util import fresh_client


@pytest.fixture
def spy():
    """临时登记一种回执送法,记下它收到了什么。"""
    seen: list[tuple[str, dict[str, Any]]] = []
    jobs_domain.register_receipt_deliverer("spy", lambda db, job, receipt: seen.append((job.id, receipt)))
    yield seen
    jobs_domain._RECEIPT_DELIVERERS.pop("spy", None)


def _job(db, workspace_id: str, **payload_extra) -> Job:
    return jobs_domain.create_job(
        db, workspace_id=workspace_id, kind="ai_generation", created_by=None, payload={"subject": "x", **payload_extra}
    )


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


class Test不管谁怎么写状态都送得出:
    """**这是这套机制最初写错的地方。**

    回执一开始挂在 `finish_job` 里,而全仓库只有 render.py 走它 —— 生成、发布、配音、
    代理、从链接导入全是直接 `job.status = "failed"`。于是它挂在了一条几乎没人走的路上:
    智能体提交完一次视频生成、任务因为「ComfyUI 需要工作流模板」失败了,而它一无所知,
    对话就停在那儿。

    改成监听**状态变化**之后,写法无关。这几条钉住的就是"写法无关"。
    """

    def test_直接赋值也送(self, spy) -> None:
        """生成、配音、代理、从链接导入都是这么写的。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            job.status = "failed"
            job.error = "ComfyUI 视频生成需要工作流模板"
            db.commit()
        assert len(spy) == 1, "直接赋 status 的路径没送出回执"

    def test_走_finish_job_也送(self, spy) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            jobs_domain.finish_job(db, job, status="succeeded")
            db.commit()
        assert len(spy) == 1

    def test_只在进终态那一次送(self, spy) -> None:
        """一个已经 failed 的行再被写一次别的字段,不该再发一封。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            job.status = "failed"
            db.commit()
            job.message = "换个说法"
            db.commit()
        assert len(spy) == 1

    def test_中间状态不送(self, spy) -> None:
        """queued → running 不是终态,送了等于每个任务开跑都打扰一次智能体。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            job.status = "running"
            db.commit()
        assert spy == []

    def test_没提交就不送(self, spy) -> None:
        """送信会写库、还会叫醒一个智能体回合。外层要是回滚了,消息却已经发出去了。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            job.status = "failed"
            db.flush()
            assert spy == [], "还没提交就送出去了"
            db.rollback()
        assert spy == []


class Test回执在终态送出:
    def test_成功时送(self, spy) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            jobs_domain.finish_job(db, job, status="succeeded")
            db.commit()
        assert [one[1]["kind"] for one in spy] == ["spy"]

    def test_失败时也送(self, spy) -> None:
        """失败恰恰是最该说一声的 —— 不说的话智能体会一直等一个不会来的结果。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            jobs_domain.finish_job(db, job, status="failed", error="供应商拒了")
            db.commit()
        assert len(spy) == 1

    def test_没写回执的任务不送(self, spy) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws)
            db.commit()
            jobs_domain.finish_job(db, job, status="succeeded")
            db.commit()
        assert spy == []

    def test_只送一次(self, spy) -> None:
        """finish_job 对已经终态的任务是空操作 —— 回执也不该补发第二封。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "spy"})
            db.commit()
            jobs_domain.finish_job(db, job, status="succeeded")
            jobs_domain.finish_job(db, job, status="failed")
            db.commit()
        assert len(spy) == 1

    def test_送不到不能把任务弄失败(self) -> None:
        """活儿已经干完了,产物已经在库里。回执是附加的一步,它出事不该反过来改任务的结论。"""
        client = fresh_client()
        ws = _workspace(client)

        def boom(db, job, receipt):
            raise RuntimeError("送信的路上摔了一跤")

        jobs_domain.register_receipt_deliverer("boom", boom)
        try:
            with SessionLocal() as db:
                job = _job(db, ws, receipt={"kind": "boom"})
                db.commit()
                assert jobs_domain.finish_job(db, job, status="succeeded") is True
                db.commit()
                db.refresh(job)
                assert job.status == "succeeded"
        finally:
            jobs_domain._RECEIPT_DELIVERERS.pop("boom", None)

    def test_不认识的回执种类静静跳过(self, spy) -> None:
        """老任务、或者某个模块没装配上 —— 都不该炸。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws, receipt={"kind": "还没人登记这种"})
            db.commit()
            assert jobs_domain.finish_job(db, job, status="succeeded") is True
            db.commit()


class Test终态只写一次:
    """`finish_job` 的去重此前只在**调用方已经提交**时才成立。

    没提交的话,第二次调用的 `db.refresh` 会从库里读回旧状态,把内存里那笔刚写的终态冲掉 ——
    两次都返回 True,最终状态由后一次说了算。这条和回执无关,是 finish_job 自己的毛病;
    回执只是让它从「日志里少一行」变成了用户可见的「被通知了两次,一次成功一次失败」。
    """

    def test_没提交也挡得住第二次(self) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws)
            db.commit()
            assert jobs_domain.finish_job(db, job, status="succeeded") is True
            assert jobs_domain.finish_job(db, job, status="failed") is False, "第二次终态被写进去了"
            assert job.status == "succeeded"

    def test_提交了也挡得住(self) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            job = _job(db, ws)
            db.commit()
            jobs_domain.finish_job(db, job, status="succeeded")
            db.commit()
            assert jobs_domain.finish_job(db, job, status="failed") is False
            assert job.status == "succeeded"


class Test上下文变量把回执传下去:
    def test_期间建的任务自动带上回执(self, spy) -> None:
        """确认卡执行的是发布/导出/生成三种活儿,各有各的入口函数。逐个加参数意味着每加一种
        能被智能体触发的任务都要再改一处,而漏掉的那一处不报错 —— 只是回执永远送不到。"""
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            token = jobs_domain.set_receipt({"kind": "spy", "session_id": "s1"})
            try:
                job = _job(db, ws)
            finally:
                jobs_domain.reset_receipt(token)
            db.commit()
            assert job.payload["receipt"] == {"kind": "spy", "session_id": "s1"}

    def test_出了这段就不带(self, spy) -> None:
        client = fresh_client()
        ws = _workspace(client)
        with SessionLocal() as db:
            token = jobs_domain.set_receipt({"kind": "spy"})
            jobs_domain.reset_receipt(token)
            job = _job(db, ws)
            db.commit()
            assert "receipt" not in job.payload


class Test方向是反的:
    def test_任务域不认识智能体(self) -> None:
        """domain/jobs 里出现 `domain.agent` 就说明依赖反了 —— 那一刻起,发布和导出也
        跟着依赖上了智能体域。"""
        from pathlib import Path

        source = Path(jobs_domain.__file__).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        assert "domain.agent" not in code and "domain import agent" not in code

    def test_登记发生在装配层(self) -> None:
        """不在 import 时自动生效 —— 那样测试和脚本会拿到一个自己没要求过的副作用。"""
        from pathlib import Path

        main = Path(__file__).resolve().parents[1] / "app" / "main.py"
        assert "agent_receipts.install()" in main.read_text(encoding="utf-8")

"""回执要当一张**任务卡**看,而不是一句冻结了语言的通知;而且它必须真的到得了智能体手里。

两条真机上的毛病:

1. 回执只带 `job_id` / `asset_ids`,正文是 `_summarize` 拼好的一句中文(失败原因取 `job.error`,
   而重启收尾把那句中文**渲染进了列**)。界面只能原样显示 —— 英文界面里失败原因永远是中文,
   也没法「查看任务 / 前往生成记录 / 重新取回」。
2. 会话空闲时回执落库**就算已送**,紧接着起一轮;那一轮被后端重启掐断时,收尾只把会话拨回 idle,
   回执仍标着已送,而 `unseen_since_last_success` 只看 user/assistant —— **用户看得见,智能体没读到**。

这里钉住三件事:payload 带够信息(key + 参数 + 完整 subject + 生成记录 id)、失败原因在**出口**
按请求方的语言翻、重启之后那条已送的回执会重新变成待送并真的被下一轮读到。
"""

from __future__ import annotations

import threading
from typing import Any

from app.ai.sidecar.pi_client import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, GenerationJob
from app.domain import jobs as jobs_domain
from app.domain.agent import host, receipts
from tests.test_agent_queue import _session
from tests.util import fresh_client, user_id


class Turns:
    """假模型:记下每一轮收到的提示词。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, *args: Any, **kwargs: Any) -> TurnResult:
        self.prompts.append(str(kwargs.get("prompt") or (args[1] if len(args) > 1 else "")))
        assert self.gate.wait(15), "测试没放行这一轮"
        return TurnResult(text="好的")


def _workspace(sid: str) -> str:
    with SessionLocal() as db:
        return db.get(AgentSession, sid).workspace_id


def _message_payloads(client, sid: str, *, locale: str = "zh-CN") -> list[dict[str, Any]]:
    rows = client.get(
        f"/api/agent/sessions/{sid}/messages", headers={"Accept-Language": locale}
    ).json()
    return [row for row in rows if row["role"] == host.JOB_RECEIPT_ROLE]


def test_回执_payload_带够信息_subject_不静默截断(monkeypatch) -> None:
    """回执落库时就该带着:种类、状态、失败 key 与参数、**完整** subject、生成记录 id。"""
    client = fresh_client()
    sid = _session(client)
    owner = user_id()
    prompt = "一只在雨里等车的柴犬," * 24  # 远超 80 字

    with SessionLocal() as db:
        #: 会话正忙 —— 回执落成待送,不在这里起一轮(这一条只验 payload)。
        db.get(AgentSession, sid).status = "running"
        job = jobs_domain.create_job(
            db,
            workspace_id=_workspace(sid),
            kind="ai_generation",
            created_by=owner,
            payload={
                "subject": prompt,  # 建任务处（generation.operations）现在也存完整原文
                "request": {"prompt": prompt},
                "session_id": "gen-session-1",
                "receipt": receipts.receipt_to_session(sid),
            },
            message="jobMsg_generationQueued",
        )
        db.commit()
        generation = GenerationJob(
            workspace_id=_workspace(sid), job_id=job.id, provider="p", model="m", kind="image",
            request={"prompt": prompt},
        )
        db.add(generation)
        job.status = "failed"
        job.error_key = jobs_domain.RESTART_ERROR_KEY
        job.error = ""
        db.commit()
        job_id = job.id
        generation_id = generation.id

    payloads = _message_payloads(client, sid)
    assert len(payloads) == 1
    payload = payloads[0]["payload"]
    assert payload["job_id"] == job_id
    assert payload["kind"] == "ai_generation"
    assert payload["status"] == "failed"
    assert payload["asset_ids"] == []
    assert payload["error_key"] == jobs_domain.RESTART_ERROR_KEY
    assert payload["error_params"] == {}
    assert payload["error"] == "", "带 key 的失败不该把渲染好的那句存进回执"
    assert payload["generation_id"] == generation_id
    assert payload["generation_session_id"] == "gen-session-1"
    assert payload["subject"] == prompt, "subject 被截成 80 字了 —— 界面再 Truncate 也回不到全文"
    assert payload["undelivered"] is True

    #: 给模型读的那一句仍然是短句,但截断要有省略号,不能悄悄切掉。
    content = payloads[0]["content"]
    assert "…" in content
    assert prompt not in content


def test_失败原因按请求方的语言在出口翻_不再冻结中文(monkeypatch) -> None:
    """回执里的失败原因由**出口**用 error_key 翻;英文请求拿到的就是英文。"""
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "running"
        job = jobs_domain.create_job(
            db,
            workspace_id=_workspace(sid),
            kind="tts",
            created_by=user_id(),
            payload={"subject": "配音 1", "receipt": receipts.receipt_to_session(sid)},
        )
        db.commit()
        job.status = "failed"
        job.error_key = jobs_domain.RESTART_ERROR_KEY
        job.error = ""
        db.commit()

    english = _message_payloads(client, sid, locale="en-US")[0]["payload"]
    assert english["error_key"] == jobs_domain.RESTART_ERROR_KEY
    assert "backend restarted" in (english["error_summary"] or "").lower(), english
    assert "后端重启" not in (english["error_summary"] or "")

    chinese = _message_payloads(client, sid, locale="zh-CN")[0]["payload"]
    assert "后端重启" in (chinese["error_summary"] or ""), chinese


def test_已送回执被重启掐断_收尾后重新待送_下一轮真读到(monkeypatch) -> None:
    """先红:此前收尾只拨回会话,回执仍算已送,智能体永远读不到那个任务的结果。"""
    turns = Turns()
    monkeypatch.setattr(host, "run_turn", turns)
    client = fresh_client()
    sid = _session(client)
    owner = user_id()

    with SessionLocal() as db:
        job = jobs_domain.create_job(
            db,
            workspace_id=_workspace(sid),
            kind="tts",
            created_by=owner,
            #: **不挂 receipt**:这条测试要的是「那条回执已经落库、那一轮被杀」的样子;
            #: 挂着的话任务落终态会真的再送一条新的待送回执,把要验的那条挤成倒数第二条。
            payload={"subject": "配音 1"},
        )
        db.commit()
        job.status = "succeeded"
        job.result = {"asset_id": "asset-1"}
        #: 把「空闲时收到回执」落库的样子原样摆出来:自己的角色、**已送**(没有 undelivered),
        #: 然后那一轮在进程里跑到一半被重启掐断。
        db.add(
            AgentMessage(
                session_id=sid,
                role=host.JOB_RECEIPT_ROLE,
                content="「配音 1」已完成,素材 id:asset-1。",
                payload={
                    "job_id": job.id, "asset_ids": ["asset-1"], "kind": "tts", "status": "succeeded",
                    "subject": "配音 1", "undelivered": False,
                },
            )
        )
        session = db.get(AgentSession, sid)
        session.status = "running"
        db.commit()

        assert host.reconcile_orphaned_agent_sessions(db) == 1
        db.commit()  # 测试是入口:重启收尾不提交(见 domain/restart.settle_previous_run)

    assert host.wait_for_idle_turns(20), "收尾之后那一轮没跑完"
    assert turns.prompts, "重启收尾没有把那条回执重新交给智能体"
    assert "「配音 1」已完成,素材 id:asset-1" in turns.prompts[0]
    assert job.id in turns.prompts[0]

    with SessionLocal() as db:
        receipt = db.query(AgentMessage).filter_by(session_id=sid, role=host.JOB_RECEIPT_ROLE).one()
        assert not (receipt.payload or {}).get("undelivered"), "交给智能体之后还标着待送"
        #: 收尾补的那句「上一轮中断了」还在,但回执已经交出去了 —— 两件事都做了。
        assert db.get(AgentSession, sid).status == "idle"


def test_最后一条不是回执就不动它(monkeypatch) -> None:
    """用户在那条回执之后又说了一句:该重放的是用户那句话(已有机制),不是那条回执。"""
    turns = Turns()
    monkeypatch.setattr(host, "run_turn", turns)
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=sid, role="user", content="在吗", payload={}))
        db.get(AgentSession, sid).status = "running"
        db.commit()
        assert host.reconcile_orphaned_agent_sessions(db) == 1
        db.commit()

    assert host.wait_for_idle_turns(20)
    assert turns.prompts == []

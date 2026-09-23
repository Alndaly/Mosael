"""浏览器自动化 worker 通道:claim / report / heartbeat。

与发布/通用 job worker 同一信任边界:X-Mosael-Worker-Key(本机 0600 文件),在 main.py 挂载处统一
加依赖。Electron 的浏览器 worker 拉取 queued 动作、执行、回报;后端从不反向连接执行器。

**这是 ADR-0002 的第三条通道,而它此前一条都没落。** ADR 开篇写着「**任何**跨进程执行的任务
都走同一个拉取式契约」,并规定认领带持久化的 `lease_token` + `lease_expires_at`、worker 必须在
`report` 里原样带回、并至少每 20 秒心跳一次。任务通道全有,发布通道明写为历史例外,而浏览器
这条在 ADR 里**一个字都没有** —— `ClaimRequest.worker` 收下了却从不使用,表上也没有对应的列。

没有单一的可见现象:单执行器下它工作正常。问题是**没有任何东西能在多执行器或执行器崩溃时
保证正确**,而隔壁两条都有。同一个文件(`electron/publish/browserBackend.ts`)里为发布执行器的
workerId 写了整整一页「必须跨重启稳定」的理由,隔壁这条道没学。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.domain.browser import claim_next_action, renew_action_leases, report_action

router = APIRouter(tags=["browser-worker"])


class ClaimRequest(BaseModel):
    #: 认领者的身份。**必须跨重启稳定** —— 执行器重启后第一拍要认出自己那些没跑完的动作,
    #: 那是这个判据存在的全部理由。客户端此前发的是字面量 "browser",不是身份。
    worker: str = Field(default="", max_length=64)


class ReportRequest(BaseModel):
    action_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    last_url: str | None = None
    #: 认领时拿到的令牌,原样带回。对不上就拒绝:这条动作已经不归你了。
    lease_token: str | None = Field(default=None, max_length=64)


class LeaseClaim(BaseModel):
    action_id: str
    lease_token: str = Field(min_length=1, max_length=64)


class HeartbeatRequest(BaseModel):
    worker: str = Field(default="", max_length=64)
    #: 我正在干的那些。心跳的作用就是**带着它们来续约** —— 一个只说"我还在"的心跳,
    #: 回答不了"你手上那条动作还算不算数"。
    claims: list[LeaseClaim] = Field(default_factory=list, max_length=200)


@router.post("/browser/worker/claim")
def claim(body: ClaimRequest, db: DbSession) -> dict[str, Any]:
    action = claim_next_action(db, worker=body.worker)
    return {"action": action}


@router.patch("/browser/worker/report")
def report(body: ReportRequest, db: DbSession) -> dict[str, Any]:
    try:
        act = report_action(
            db,
            body.action_id,
            status=body.status,
            result=body.result,
            error=body.error,
            last_url=body.last_url,
            lease_token=body.lease_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": act.id, "status": act.status}


@router.post("/browser/worker/heartbeat")
def heartbeat(body: HeartbeatRequest, db: DbSession) -> dict[str, Any]:
    """执行器报「我还在」,并**给手上那些动作续约**。

    返回 `renewed`:真的续上了的那些 id。没续上的,执行器那边该停手 —— 它手上那条已经被
    判过期、或者被别人接走了,再写结果只会盖掉别人正在干的那一份。

    这里不再记任何进程内状态。曾经有一个 `_HEARTBEATS` 字典写进去,全仓零个读者,而它按
    worker 名字无限长;"这个执行器还在吗"的答案现在写在**动作行的租约上**,和另外两条通道一样。
    """
    renewed = renew_action_leases(db, worker=body.worker, claims=[one.model_dump() for one in body.claims])
    return {"ok": True, "renewed": renewed}

"""后果**不在这个应用里**的那几件事:发出去的帖子、别人服务器上的改动、本机跑过的代码,
以及用用户已登录的身份开浏览器。

前面几档最坏是花钱或改坏自己的数据(撤得回),这一档撤不回来 —— 卡上的措辞要和「编辑时间线」
明显不同,用户才会真的看一眼再点。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from sqlalchemy import select

from app.db.models import PublishAccount


def _summarize_publish_asset(db: Session, payload: dict[str, Any]) -> Summary:
    title = str(payload.get("title") or "").strip()
    what = fragment("confirm_publishTitled", title=title) if title else fragment("confirm_publishUntitled")
    return "confirm_publishAsset", {"what": what}

def _execute_publish_asset(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset as AssetModel, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(payload["account_id"]))
    asset = db.get(AssetModel, str(payload["asset_id"]))
    if account is None or account.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_publishAccountNotFound")
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ConfirmationError("confirmErr_assetNotFound")
    task = start_publish(
        db,
        workspace_id=confirmation.workspace_id,
        account=account,
        asset=asset,
        title=str(payload.get("title") or ""),
        description=str(payload.get("description") or ""),
        tags=[],
        # 批准这张卡的人 —— 智能体自己不是主体,它用的是批准者的授权(见 confirmations._execute_approved)。
        actor=actor,
    )
    return {"task_id": task.id, "status": task.status}

def _validate_http_request(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    url = str(payload.get("url") or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        # file:// 会把本机文件读成「请求结果」交回给模型。只认 http(s),而且在**开卡时**就认 ——
        # 一张说不清要请求什么的卡,没有让用户去点批准的道理。
        raise ConfirmationError("confirmErr_httpOnly")

def _summarize_http_request(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_httpRequest", {
        "method": payload.get("method", "POST"),
        "url": str(payload.get("url") or "")[:120],
    }

def _execute_http_request(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.workflows.executors.basic import run_http

    return run_http(
        method=str(payload.get("method") or "POST"),
        url=str(payload["url"]),
        headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
        body=str(payload.get("body") or ""),
    )

def _validate_run_code(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain import sandbox

    if sandbox.active_backend() is None:
        raise ConfirmationError(
            "这台机器上没有可用的代码隔离环境,因此不执行代码。请在部署机上安装并启动 Docker。"
        )

def _summarize_run_code(db: Session, payload: dict[str, Any]) -> Summary:
    code = str(payload.get("code") or "")
    head = code.strip().splitlines()[0][:60] if code.strip() else ""
    return "confirm_runCode", {
        "chars": len(code),
        "head": fragment("confirm_codeHead", head=head) if head else "",
    }

def _execute_run_code(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.workflows.executors.basic import run_python

    return run_python(str(payload.get("code") or ""), dict(payload.get("inputs") or {}))

def _validate_run_host_code(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain import host_code

    reason = host_code.available()
    if reason:
        raise ConfirmationError(reason)

def _summarize_run_host_code(db: Session, payload: dict[str, Any]) -> Summary:
    code = str(payload.get("code") or "")
    head = code.strip().splitlines()[0][:60] if code.strip() else ""
    return "confirm_runHostCode", {
        "chars": len(code),
        "head": fragment("confirm_codeHead", head=head) if head else "",
    }

def _execute_run_host_code(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import host_code

    payload = confirmation.payload
    try:
        return host_code.run(str(payload.get("code") or ""), dict(payload.get("inputs") or {}))
    except host_code.HostCodeError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc

def _validate_browser_open(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    url = str(payload.get("url") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ConfirmationError("confirmErr_browserHttpOnly")

def _summarize_browser_open(db: Session, payload: dict[str, Any]) -> Summary:
    url = str(payload.get("url") or "").strip()
    named = str(payload.get("session_mode")) == "named"
    return "confirm_browserOpen", {
        "mode": fragment("confirm_browserNamed" if named else "confirm_browserEphemeral"),
        "target": fragment("confirm_browserTarget", url=url) if url else "",
    }

def _execute_browser_open(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain import browser as browser_domain

    session = browser_domain.open_session(
        db,
        workspace_id=confirmation.workspace_id,
        kind="named" if str(payload.get("session_mode")) == "named" else "ephemeral",
        name=str(payload.get("session_name") or ""),
        owner_kind="agent",
        actor=actor,
    )
    url = str(payload.get("url") or "").strip()
    if url:
        browser_domain.run_action(session.id, "navigate", {"url": url})
    return {"session_id": session.id, "url": url}

def _validate_browser_pool_open(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain import browser as browser_domain

    url = str(payload.get("url") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ConfirmationError("confirmErr_browserHttpOnly")
    try:
        profile = browser_domain.get_profile(db, workspace_id, str(payload.get("profile_id") or ""))
    except browser_domain.BrowserDomainError as exc:
        raise ConfirmationError(str(exc)) from exc
    # 把档案名/平台落进 payload,让确认卡点名是哪个登录身份(_summarize 无 db)。
    payload["profile_name"] = profile.name
    account = db.scalar(select(PublishAccount).where(PublishAccount.profile_id == profile.id))
    payload["platform"] = account.platform if account else None

def _summarize_browser_pool_open(db: Session, payload: dict[str, Any]) -> Summary:
    name = str(payload.get("profile_name") or payload.get("profile_id") or "")
    platform = payload.get("platform")
    who = (fragment("confirm_profilePublish", name=name, platform=platform) if platform
           else fragment("confirm_profileGeneric", name=name))
    url = str(payload.get("url") or "").strip()
    return "confirm_browserPoolOpen", {
        "who": who,
        "target": fragment("confirm_browserTarget", url=url) if url else "",
    }

def _execute_browser_pool_open(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain import browser as browser_domain

    # 用户已在确认卡上显式授权使用这个登录身份 → 在该池档案分区开会话(受租约)。
    # 「批准」只是同意,不是权限:批准的人自己得能用这个档案 —— 别人的私有档案在 open_session 里被拒。
    session = browser_domain.open_session(
        db,
        workspace_id=confirmation.workspace_id,
        profile_id=str(payload.get("profile_id") or ""),
        owner_kind="agent",
        actor=actor,
    )
    url = str(payload.get("url") or "").strip()
    if url:
        browser_domain.run_action(session.id, "navigate", {"url": url})
    return {"session_id": session.id, "url": url}

confirmable_tool(ConfirmableTool(
    name="publish_asset",
    permission="external",
    cost="none",
    gate="publish",
    gate_label="公开发布",
    summarize=_summarize_publish_asset,
    execute=_execute_publish_asset,
))


confirmable_tool(ConfirmableTool(
    name="http_request",
    permission="external",
    cost="none",
    gate="http_request",
    gate_label="对外请求",
    summarize=_summarize_http_request,
    execute=_execute_http_request,
    validate=_validate_http_request,
))


confirmable_tool(ConfirmableTool(
    name="run_code",
    permission="external",
    cost="none",
    gate="run_code",
    gate_label="沙箱执行代码",
    summarize=_summarize_run_code,
    execute=_execute_run_code,
    validate=_validate_run_code,
))


confirmable_tool(ConfirmableTool(
    name="run_host_code",
    permission="external",
    cost="none",
    gate="run_host_code",
    gate_label="不隔离执行代码",
    summarize=_summarize_run_host_code,
    execute=_execute_run_host_code,
    validate=_validate_run_host_code,
))


confirmable_tool(ConfirmableTool(
    name="browser_open",
    permission="edit",
    cost="none",
    summarize=_summarize_browser_open,
    execute=_execute_browser_open,
    validate=_validate_browser_open,
))


confirmable_tool(ConfirmableTool(
    name="browser_pool_open",
    permission="external",
    cost="none",
    summarize=_summarize_browser_pool_open,
    execute=_execute_browser_pool_open,
    validate=_validate_browser_pool_open,
))



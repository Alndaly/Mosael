"""后果**不在这个应用里**的那几件事:发出去的帖子、别人服务器上的改动、本机跑过的代码,
以及用用户已登录的身份开浏览器。

前面几档最坏是花钱或改坏自己的数据(撤得回),这一档撤不回来 —— 卡上的措辞要和「编辑时间线」
明显不同,用户才会真的看一眼再点。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.confirmable.registry import ConfirmableTool, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from sqlalchemy import select

from app.db.models import PublishAccount


def _summarize_publish_asset(db: Session, payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "").strip()
    return f"⚠️ 用你的账号**公开发布**{f'「{title}」' if title else '一条内容'}"

def _execute_publish_asset(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Asset as AssetModel, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(payload["account_id"]))
    asset = db.get(AssetModel, str(payload["asset_id"]))
    if account is None or account.workspace_id != confirmation.workspace_id:
        raise ValueError("发布账号不存在")
    if asset is None or asset.workspace_id != confirmation.workspace_id:
        raise ValueError("素材不存在")
    task = start_publish(
        db,
        workspace_id=confirmation.workspace_id,
        account=account,
        asset=asset,
        title=str(payload.get("title") or ""),
        description=str(payload.get("description") or ""),
        tags=[],
        created_by=actor,
    )
    return {"task_id": task.id, "status": task.status}

def _validate_http_request(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    url = str(payload.get("url") or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        # file:// 会把本机文件读成「请求结果」交回给模型。只认 http(s),而且在**开卡时**就认 ——
        # 一张说不清要请求什么的卡,没有让用户去点批准的道理。
        raise ConfirmationError("只能请求 http(s) 网址")

def _summarize_http_request(db: Session, payload: dict[str, Any]) -> str:
    return f"⚠️ 向外部发起 {payload.get('method', 'POST')} 请求: {str(payload.get('url') or '')[:120]}"

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

def _summarize_run_code(db: Session, payload: dict[str, Any]) -> str:
    code = str(payload.get("code") or "")
    head = code.strip().splitlines()[0][:60] if code.strip() else ""
    return f"在隔离沙箱里运行一段 Python({len(code)} 字符,无网络、看不到你的文件){f': {head}…' if head else ''}"

def _execute_run_code(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.workflows.executors.basic import run_python

    return run_python(str(payload.get("code") or ""), dict(payload.get("inputs") or {}))

def _validate_run_host_code(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain import host_code

    reason = host_code.available()
    if reason:
        raise ConfirmationError(reason)

def _summarize_run_host_code(db: Session, payload: dict[str, Any]) -> str:
    code = str(payload.get("code") or "")
    head = code.strip().splitlines()[0][:60] if code.strip() else ""
    return (f"⚠️ **不隔离**,直接在你的电脑上运行一段 Python({len(code)} 字符),可读写你的文件"
            f"{f': {head}…' if head else ''}")

def _execute_run_host_code(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import host_code

    payload = confirmation.payload
    try:
        return host_code.run(str(payload.get("code") or ""), dict(payload.get("inputs") or {}))
    except host_code.HostCodeError as exc:
        raise ValueError(str(exc)) from exc

def _validate_blender_execute(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.core.config import settings

    if not settings.local_desktop:
        raise ConfirmationError("Blender 建模只在本机桌面版可用 —— Blender 要和 Mosael 跑在同一台电脑上。")
    if not str(payload.get("code") or "").strip():
        raise ConfirmationError("没有要在 Blender 里执行的代码")

def _summarize_blender_execute(db: Session, payload: dict[str, Any]) -> str:
    code = str(payload.get("code") or "")
    purpose = str(payload.get("purpose") or "").strip()[:80]
    lines = len(code.strip().splitlines())
    return (f"⚠️ 在你的 Blender 里执行建模代码({lines} 行){f':{purpose}' if purpose else ''}"
            " —— Blender 的 Python 不是沙箱,可读写本机文件;执行前已压撤销点,可在 Blender 里 ⌘Z")

def _execute_blender_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.db.models import User
    from app.domain.blender import agent as blender_agent

    # 连接归人:用批准这张卡的那个人的 Blender。自动放行时 actor 是开模式的人(见 autopilot)。
    user = db.get(User, actor) if actor else None
    if user is None:
        raise ValueError("找不到批准这次操作的用户")
    payload = confirmation.payload
    result = blender_agent.execute(db, user, confirmation.workspace_id, str(payload.get("code") or ""),
                                   str(payload.get("instance_id") or ""))
    if result.get("error"):
        # 代码自己的错:把 traceback 交回去,模型据此改了再试。traceback 在 worker 那边已按层数
        # 收过(limit=6),这里不再按位置裁 —— 裁掉的往往正是写着错因的最后一行。
        raise ValueError(f"Blender 里的代码出错了:\n{result['error']}")
    return result

def _validate_browser_open(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    url = str(payload.get("url") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ConfirmationError("浏览器只能打开 http(s) 网址")

def _summarize_browser_open(db: Session, payload: dict[str, Any]) -> str:
    url = str(payload.get("url") or "").strip()
    mode = "具名持久" if str(payload.get("session_mode")) == "named" else "临时"
    return f"智能体打开{mode}浏览器" + (f" → {url}" if url else "")

def _execute_browser_open(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain import browser as browser_domain

    session = browser_domain.open_session(
        db,
        workspace_id=confirmation.workspace_id,
        kind="named" if str(payload.get("session_mode")) == "named" else "ephemeral",
        name=str(payload.get("session_name") or ""),
        owner_kind="agent",
    )
    url = str(payload.get("url") or "").strip()
    if url:
        browser_domain.run_action(session.id, "navigate", {"url": url})
    return {"session_id": session.id, "url": url}

def _validate_browser_pool_open(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain import browser as browser_domain

    url = str(payload.get("url") or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ConfirmationError("浏览器只能打开 http(s) 网址")
    try:
        profile = browser_domain.get_profile(db, workspace_id, str(payload.get("profile_id") or ""))
    except browser_domain.BrowserDomainError as exc:
        raise ConfirmationError(str(exc)) from exc
    # 把档案名/平台落进 payload,让确认卡点名是哪个登录身份(_summarize 无 db)。
    payload["profile_name"] = profile.name
    account = db.scalar(select(PublishAccount).where(PublishAccount.profile_id == profile.id))
    payload["platform"] = account.platform if account else None

def _summarize_browser_pool_open(db: Session, payload: dict[str, Any]) -> str:
    name = str(payload.get("profile_name") or payload.get("profile_id") or "")
    platform = payload.get("platform")
    who = f"「{name}」" + (f"({platform} 发布账号)" if platform else "(通用档案)")
    url = str(payload.get("url") or "").strip()
    return f"⚠️ 智能体请求复用你的浏览器档案 {who} 的登录身份跑任务" + (f" → {url}" if url else "")

def _execute_browser_pool_open(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain import browser as browser_domain

    # 用户已在确认卡上显式授权使用这个登录身份 → 在该池档案分区开会话(受租约)。
    session = browser_domain.open_session(
        db,
        workspace_id=confirmation.workspace_id,
        profile_id=str(payload.get("profile_id") or ""),
        owner_kind="agent",
    )
    url = str(payload.get("url") or "").strip()
    if url:
        browser_domain.run_action(session.id, "navigate", {"url": url})
    return {"session_id": session.id, "url": url}

confirmable_tool(ConfirmableTool(
    name="publish_asset",
    permission="external",
    cost="none",
    summarize=_summarize_publish_asset,
    execute=_execute_publish_asset,
))


confirmable_tool(ConfirmableTool(
    name="http_request",
    permission="external",
    cost="none",
    summarize=_summarize_http_request,
    execute=_execute_http_request,
    validate=_validate_http_request,
))


confirmable_tool(ConfirmableTool(
    name="run_code",
    permission="external",
    cost="none",
    summarize=_summarize_run_code,
    execute=_execute_run_code,
    validate=_validate_run_code,
))


confirmable_tool(ConfirmableTool(
    name="run_host_code",
    permission="external",
    cost="none",
    summarize=_summarize_run_host_code,
    execute=_execute_run_host_code,
    validate=_validate_run_host_code,
))


confirmable_tool(ConfirmableTool(
    name="blender_execute",
    permission="external",
    cost="none",
    summarize=_summarize_blender_execute,
    execute=_execute_blender_execute,
    validate=_validate_blender_execute,
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



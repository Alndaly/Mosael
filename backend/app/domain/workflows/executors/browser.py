"""浏览器自动化(RPA)节点:在隔离浏览器会话里操作网页。

每个节点把动作交给 domain/browser.run_action(入队 → 阻塞轮询到 Electron 执行器回报),与
wait_for_job 同样的「后端等外部执行器」模型。session 输出串起整条链:打开浏览器 → 各步骤透传
session → 关闭。会话与发布登录物理隔离(分区命名空间不同)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain import browser
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register


def _session_id(config: dict[str, Any]) -> str:
    sid = str(config.get("session") or "").strip()
    if not sid:
        raise WorkflowDomainError("缺少浏览器会话:先用「打开浏览器」节点,并把它的 session 输出连过来")
    return sid


def _truthy(value: Any) -> bool:
    #: 认好几种拼法,因为这个值不一定来自下拉框 —— 它也可以从上游连线过来(模型吐的 "是"、
    #: HTTP 回来的 "on")。下拉框给的是 true/false,这里宽容的是**别处**送来的写法。
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "是")


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


#: 失败现场的截图给多大。captureBase64 已经缩到 480 宽,这道闸防的是意外(超大 DPR、
#: 执行器换实现)——失败记录进的是任务总线的 payload,不该由它把库撑起来。
_SHOT_MAX_CHARS = 400_000
#: 截图本身也要能失败得快。这一步是**补充说明**,不是任务的一部分:会话已经没了的时候,
#: 等它 60 秒只是把一次失败拖成两次。
_SHOT_TIMEOUT_SECONDS = 8.0


def _failure_scene(session_id: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
    """这一步失败的时候,页面长什么样。

    **「等待超时」之后最想知道的就是这个**:选择器没写错的话,那一刻屏幕上是登录墙、是验证码,
    还是页面根本没跳过去?URL 我们已经能说了(1d33ab27),但站点改版之后光有 URL 不够 ——
    一张图能省掉「把节点配置重贴一遍、手动复现一次」那整个来回。

    整段最多值一张图:拿不到就算了,绝不让取证本身变成第二次失败。
    """
    scene: dict[str, Any] = {"action": action}
    for key in ("selector", "url", "url_contains", "text", "expression"):
        value = str(args.get(key) or "").strip()
        if value:
            scene[key] = value[:200]
    try:
        shot = browser.run_action(session_id, "screenshot", {}, timeout=_SHOT_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — 会话已经关掉、执行器没响应……都只意味着"这次没有图"
        return scene
    image = str(shot.get("value") or "")
    if image.startswith("data:image/") and len(image) <= _SHOT_MAX_CHARS:
        scene["screenshot"] = image
    last_url = str(shot.get("lastUrl") or "").strip()
    if last_url:
        scene["page_url"] = last_url[:500]
    return scene


def _run(session_id: str, action: str, args: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    try:
        if timeout is None:
            return browser.run_action(session_id, action, args)
        return browser.run_action(session_id, action, args, timeout=timeout)
    except browser.BrowserDomainError as exc:
        raise WorkflowDomainError(str(exc), details=_failure_scene(session_id, action, args)) from exc


@register("browser_open")
def browser_open(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("session_mode") or "ephemeral")
    try:
        if mode == "pool":
            profile_id = str(config.get("profile_id") or "").strip()
            if not profile_id:
                raise WorkflowDomainError("请选择浏览器池档案(session_mode=pool)")
            session = browser.open_session(
                db, workspace_id=workflow.workspace_id, profile_id=profile_id, owner_kind="workflow", owner_id=workflow.id
            )
        else:
            session = browser.open_session(
                db,
                workspace_id=workflow.workspace_id,
                kind="named" if mode == "named" else "ephemeral",
                name=str(config.get("session_name") or ""),
                owner_kind="workflow",
                owner_id=workflow.id,
            )
    except browser.BrowserDomainError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    url = str(config.get("url") or "").strip()
    if url:
        _run(session.id, "navigate", {"url": url})
    return {"session": session.id}


@register("browser_navigate")
def browser_navigate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    _run(sid, "navigate", {"url": str(config.get("url") or "")})
    return {"session": sid}


@register("browser_click")
def browser_click(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    _run(sid, "click", {
        "selector": str(config.get("selector") or ""),
        "text": str(config.get("text") or ""),
        "exact": _truthy(config.get("exact")),
    })
    return {"session": sid}


@register("browser_input")
def browser_input(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    _run(sid, "input", {"selector": str(config.get("selector") or ""), "value": str(config.get("value") or "")})
    return {"session": sid}


@register("browser_upload")
def browser_upload(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """往 <input type=file> 塞一个本地文件(发布上传视频的关键)。asset_id 或 file_path 二选一——
    asset_id 在后端解析成本机绝对路径再交给执行器(素材文件与执行器同机,本地优先)。"""
    from app.db.models import Asset
    from app.media.paths import resolve_key

    sid = _session_id(config)
    path = str(config.get("file_path") or "").strip()
    asset_id = str(config.get("asset_id") or "").strip()
    if asset_id and not path:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workflow.workspace_id:
            raise WorkflowDomainError("上传素材不存在")
        if not asset.file_key:
            raise WorkflowDomainError("上传素材没有文件")
        path = str(resolve_key(asset.file_key))
    if not path:
        raise WorkflowDomainError("上传节点需要 asset_id 或 file_path")
    timeout_ms = _int(config.get("timeout_ms"), 15_000)
    _run(
        sid,
        "upload",
        {"selector": str(config.get("selector") or "").strip(), "path": path, "timeout_ms": timeout_ms},
        timeout=timeout_ms / 1000 + 20,
    )
    return {"session": sid}


@register("browser_extract")
def browser_extract(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    attribute = str(config.get("attribute") or "").strip()
    out = _run(sid, "extract", {
        "selector": str(config.get("selector") or ""),
        "attribute": attribute or None,
        "all": _truthy(config.get("all")),
    })
    return {"session": sid, "value": out.get("value")}


@register("browser_wait")
def browser_wait(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    timeout_ms = _int(config.get("timeout_ms"), 15_000)
    args: dict[str, Any] = {"timeout_ms": timeout_ms}
    if config.get("selector"):
        args["selector"] = str(config["selector"])
        args["gone"] = _truthy(config.get("gone"))
    elif config.get("url_contains"):
        args["url_contains"] = str(config["url_contains"])
    elif config.get("text"):
        args["text"] = str(config["text"])
    else:
        raise WorkflowDomainError("等待节点需要 selector / url_contains / text 之一")
    _run(sid, "wait", args, timeout=timeout_ms / 1000 + 15)
    return {"session": sid}


@register("browser_scroll")
def browser_scroll(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    _run(sid, "scroll", {"selector": str(config.get("selector") or ""), "dy": _int(config.get("dy"), 600)})
    return {"session": sid}


@register("browser_evaluate")
def browser_evaluate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_id(config)
    out = _run(sid, "evaluate", {"expression": str(config.get("expression") or "")})
    return {"session": sid, "value": out.get("value")}


@register("browser_close")
def browser_close(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = str(config.get("session") or "").strip()
    if sid:
        browser.close_session(db, sid)
    return {}

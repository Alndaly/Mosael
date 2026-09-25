"""浏览器自动化(RPA)节点:在隔离浏览器会话里操作网页。

每个节点把动作交给 domain/browser.run_action(入队 → 阻塞轮询到 Electron 执行器回报),与
wait_for_job 同样的「后端等外部执行器」模型。session 输出串起整条链:打开浏览器 → 各步骤透传
session → 关闭。会话与发布登录物理隔离(分区命名空间不同)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Job, Workflow
from app.domain import browser, host_files, sharing
from app.domain.jobs import current_actor, current_parent_job_id
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register


def _session_in(db: Session, workflow: Workflow, config: dict[str, Any]) -> str:
    """取这个浏览器会话,并确认它属于本工作流所在的工作区。和 subjobs 的 _sequence_in 成对。

    session 常常来自上游节点,而上游拿得到任何地方的 id;run_action 不认识工作区。不挡的话,
    A 工作区的工作流能在 B 工作区某人已登录的池档案会话里取 cookie、点发布,或者把它关掉。
    智能体那条路一直挡着(api/routes/agent_browser._verify),漏的只有这一条。
    """
    sid = str(config.get("session") or "").strip()
    if not sid:
        raise WorkflowDomainError("wfErr_browserSessionMissing")
    # 池档案会话还要这次运行的操作人自己能用那个档案(见 browser.attach_session)。
    try:
        session = browser.attach_session(db, sid, workspace_id=workflow.workspace_id, actor=current_actor(db))
    except sharing.NotUsableError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if session is None:
        raise WorkflowDomainError("wfErr_browserSessionNotInWorkspace")
    return session.id


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
        raise WorkflowDomainError.from_error(exc, details=_failure_scene(session_id, action, args)) from exc


def _run_owner(db: Session) -> str | None:
    """会话归谁:**这次运行** —— 最外层那条工作流任务。

    不是这条工作流:同一条工作流并发跑两次时,两次会拿到同一个池档案会话(同 owner 复用),
    一次的「关闭」关掉的是另一次正在用的视图。也不是当前这一层:子流程(call_workflow)是
    这次运行的一部分,「登录」子流程把 session 交回给调用方是正当用法,不能在子流程收尾时就关。

    运行落终态(成功、失败、取消)时,它名下的会话由 domain/browser 的收拾动作关掉。
    """
    owner: str | None = None
    job_id = current_parent_job_id()
    while job_id:
        job = db.get(Job, job_id)
        if job is None or job.kind != "workflow":
            break
        owner, job_id = job.id, job.parent_job_id
    return owner


@register("browser_open")
def browser_open(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("session_mode") or "ephemeral")
    owner = _run_owner(db)
    #: 谁在用:这次运行的操作人。手动运行是点运行的人,定时任务 / webhook 是任务主人
    #: (见 scheduler.operations._open_run)。池档案是某人的登录身份,别人的私有档案在这里被拒。
    actor = current_actor(db)
    try:
        if mode == "pool":
            profile_id = str(config.get("profile_id") or "").strip()
            if not profile_id:
                raise WorkflowDomainError("wfErr_pickPoolProfile")
            session = browser.open_session(
                db, workspace_id=workflow.workspace_id, profile_id=profile_id, owner_kind="workflow", owner_id=owner,
                actor=actor,
            )
        else:
            session = browser.open_session(
                db,
                workspace_id=workflow.workspace_id,
                kind="named" if mode == "named" else "ephemeral",
                name=str(config.get("session_name") or ""),
                owner_kind="workflow",
                owner_id=owner,
                actor=actor,
            )
    except (browser.BrowserDomainError, sharing.NotUsableError) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    url = str(config.get("url") or "").strip()
    if url:
        _run(session.id, "navigate", {"url": url})
    return {"session": session.id}


@register("browser_navigate")
def browser_navigate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    _run(sid, "navigate", {"url": str(config.get("url") or "")})
    return {"session": sid}


@register("browser_click")
def browser_click(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    _run(sid, "click", {
        "selector": str(config.get("selector") or ""),
        "text": str(config.get("text") or ""),
        "exact": _truthy(config.get("exact")),
    })
    return {"session": sid}


@register("browser_input")
def browser_input(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    _run(sid, "input", {"selector": str(config.get("selector") or ""), "value": str(config.get("value") or "")})
    return {"session": sid}


@register("browser_upload")
def browser_upload(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """往 <input type=file> 塞一个本地文件(发布上传视频的关键)。asset_id 或 file_path 二选一。

    两条来源都经 domain/host_files 放行:asset_id 是本工作区素材库里的文件;file_path 是这台电脑上
    的路径 —— 那是部署主人的私有资源,只有部署管理员、或路径落在管理员共享给成员的文件夹里才读得到。
    否则同事在工作流里填一个 `~/.ssh/id_rsa`,就能把主人的私钥塞进任意网页。
    """
    from app.db.models import Asset

    sid = _session_in(db, workflow, config)
    path = str(config.get("file_path") or "").strip()
    asset_id = str(config.get("asset_id") or "").strip()
    try:
        if path:
            file = host_files.ensure_readable(db, path, actor=current_actor(db))
        elif asset_id:
            asset = db.get(Asset, asset_id)
            if asset is None or asset.workspace_id != workflow.workspace_id:
                raise WorkflowDomainError("wfErr_uploadAssetMissing")
            if not asset.file_key:
                raise WorkflowDomainError("wfErr_uploadAssetNoFile")
            file = host_files.asset_file(asset)
        else:
            raise WorkflowDomainError("wfErr_uploadNeedsSource")
    except (host_files.HostFileError, host_files.HostFileNotAllowed) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    timeout_ms = _int(config.get("timeout_ms"), 15_000)
    selector = str(config.get("selector") or "").strip()
    try:
        browser.upload_file(sid, file, selector=selector, timeout_ms=timeout_ms)
    except browser.BrowserDomainError as exc:
        raise WorkflowDomainError.from_error(
            exc, details=_failure_scene(sid, "upload", {"selector": selector})
        ) from exc
    return {"session": sid}


@register("browser_extract")
def browser_extract(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    attribute = str(config.get("attribute") or "").strip()
    out = _run(sid, "extract", {
        "selector": str(config.get("selector") or ""),
        "attribute": attribute or None,
        "all": _truthy(config.get("all")),
    })
    return {"session": sid, "value": out.get("value")}


@register("browser_wait")
def browser_wait(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
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
        raise WorkflowDomainError("wfErr_waitNeedsCondition")
    _run(sid, "wait", args, timeout=timeout_ms / 1000 + 15)
    return {"session": sid}


@register("browser_scroll")
def browser_scroll(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    _run(sid, "scroll", {"selector": str(config.get("selector") or ""), "dy": _int(config.get("dy"), 600)})
    return {"session": sid}


@register("browser_evaluate")
def browser_evaluate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, workflow, config)
    out = _run(sid, "evaluate", {"expression": str(config.get("expression") or "")})
    return {"session": sid, "value": out.get("value")}


@register("browser_close")
def browser_close(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    # 留空不报错:上游分支没走到「打开浏览器」时,关闭这一步本来就无事可做。
    if not str(config.get("session") or "").strip():
        return {}
    browser.close_session(db, _session_in(db, workflow, config))
    return {}

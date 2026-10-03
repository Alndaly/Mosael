"""浏览器自动化(RPA)节点:在隔离浏览器会话里操作网页。

每个节点把动作交给 domain/browser.run_action(入队 → 阻塞轮询到 Electron 执行器回报),与
wait_for_job 同样的「后端等外部执行器」模型。session 输出串起整条链:打开浏览器 → 各步骤透传
session → 关闭。会话与发布登录物理隔离(分区命名空间不同)。
"""

from __future__ import annotations

from typing import Any, NoReturn

from sqlalchemy.orm import Session

from app.db.models import Job
from app.domain import browser, host_files, sharing
from app.domain.jobs import current_parent_job_id
from app.domain.permissions import NotVisible
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.authority import current_authority
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.run_scope import halted


def _session_in(db: Session, scope: RunScope, config: dict[str, Any]) -> str:
    """取这个浏览器会话,并确认它属于这次运行所在的工作区。和 subjobs 的 _sequence_in 成对。

    session 常常来自上游节点,而上游拿得到任何地方的 id;run_action 不认识工作区。不挡的话,
    A 工作区的工作流能在 B 工作区某人已登录的池档案会话里取 cookie、点发布,或者把它关掉。
    智能体那条路一直挡着(api/routes/agent_browser._verify),漏的只有这一条。
    """
    sid = str(config.get("session") or "").strip()
    if not sid:
        raise WorkflowDomainError("wfErr_browserSessionMissing")
    # 池档案会话还要这次运行能用那个档案:操作人,和被执行那一版图的担保人(见 browser.attach_session、
    # workflows.authority)。
    try:
        session = browser.attach_session(db, sid, workspace_id=scope.workspace_id, actor=current_authority(db))
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


def _element_wait(config: dict[str, Any]) -> dict[str, int]:
    """点击 / 输入之前等元素出现多久:节点上填了就交给执行器,没填由执行器用它的缺省(5 秒)。"""
    raw = config.get("wait_ms")
    if raw in (None, ""):
        return {}
    return {"wait_ms": max(0, _int(raw, 0))}


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
    """跑一个动作。**这一轮停了就不再等**(workflows.run_scope:同一张图里别的节点失败了):此前在飞的
    动作只认自己的超时,兄弟节点早已失败,它还要陪着等满两分钟。"""
    try:
        if timeout is None:
            return browser.run_action(session_id, action, args, should_stop=halted)
        return browser.run_action(session_id, action, args, timeout=timeout, should_stop=halted)
    except browser.BrowserDomainError as exc:
        _raise_failure(exc, session_id, action, args)


def _raise_failure(exc: browser.BrowserDomainError, session_id: str, action: str, args: dict[str, Any]) -> NoReturn:
    """这一步失败了:带上失败现场抛出。这一轮已经停了的话不取证 —— 没人看这一步的结果了,截一张图只是再等几秒。"""
    if halted():
        raise WorkflowDomainError("wfErr_cancelled") from exc
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
def browser_open(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("session_mode") or "ephemeral")
    owner = _run_owner(db)
    #: 谁在用:这次运行的操作人(手动运行是点运行的人,定时任务 / webhook 是任务主人,见
    #: scheduler.operations._open_run),加上被执行那一版图的担保人(见 workflows.authority)。
    #: 池档案是某人的登录身份,别人的私有档案、同事改过而主人没认可的那一版,在这里被拒。
    actor = current_authority(db)
    try:
        if mode == "pool":
            profile_id = str(config.get("profile_id") or "").strip()
            if not profile_id:
                raise WorkflowDomainError("wfErr_pickPoolProfile")
            session = browser.open_session(
                db, workspace_id=scope.workspace_id, profile_id=profile_id, owner_kind="workflow", owner_id=owner,
                actor=actor,
            )
        else:
            session = browser.open_session(
                db,
                workspace_id=scope.workspace_id,
                kind="named" if mode == "named" else "ephemeral",
                name=str(config.get("session_name") or ""),
                owner_kind="workflow",
                owner_id=owner,
                actor=actor,
            )
    except (browser.BrowserDomainError, sharing.NotUsableError) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    #: 具名会话第一次打开、而升级时它的旧登录没能带过来:原因交在 notice 上(否则人只看到「登录没了」)
    notice = browser.login_notice(db, session)
    url = str(config.get("url") or "").strip()
    if url:
        _run(session.id, "navigate", {"url": url})
    return {"session": session.id, "notice": notice}


@register("browser_navigate")
def browser_navigate(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    _run(sid, "navigate", {"url": str(config.get("url") or "")})
    return {"session": sid}


@register("browser_click")
def browser_click(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    _run(sid, "click", {
        "selector": str(config.get("selector") or ""),
        "text": str(config.get("text") or ""),
        "exact": _truthy(config.get("exact")),
        **_element_wait(config),
    })
    return {"session": sid}


@register("browser_input")
def browser_input(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    _run(sid, "input", {
        "selector": str(config.get("selector") or ""),
        "value": str(config.get("value") or ""),
        **_element_wait(config),
    })
    return {"session": sid}


@register("browser_upload")
def browser_upload(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """往 <input type=file> 塞一个本地文件(发布上传视频的关键)。asset_id 或 file_path 只能给一个(见 host_files.upload_source)。

    两条来源都经 domain/host_files 放行:asset_id 是本工作区素材库里的文件;file_path 是这台电脑上
    的路径 —— 那是部署主人的私有资源,只有部署管理员、或路径落在管理员共享给成员的文件夹里才读得到。
    否则同事在工作流里填一个 `~/.ssh/id_rsa`,就能把主人的私钥塞进任意网页。
    """
    sid = _session_in(db, scope, config)
    try:
        file = host_files.upload_source(
            db,
            workspace_id=scope.workspace_id,
            asset_id=str(config.get("asset_id") or ""),
            path=str(config.get("file_path") or ""),
            actor=current_authority(db),
        )
    except (host_files.HostFileError, host_files.HostFileNotAllowed, NotVisible) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    timeout_ms = _int(config.get("timeout_ms"), 15_000)
    selector = str(config.get("selector") or "").strip()
    try:
        browser.upload_file(sid, file, selector=selector, timeout_ms=timeout_ms, should_stop=halted)
    except browser.BrowserDomainError as exc:
        _raise_failure(exc, sid, "upload", {"selector": selector})
    return {"session": sid}


@register("browser_extract")
def browser_extract(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    attribute = str(config.get("attribute") or "").strip()
    out = _run(sid, "extract", {
        "selector": str(config.get("selector") or ""),
        "attribute": attribute or None,
        "all": _truthy(config.get("all")),
        "allow_missing": _truthy(config.get("allow_missing")),
    })
    return {"session": sid, "value": out.get("value")}


@register("browser_wait")
def browser_wait(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
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
def browser_scroll(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    _run(sid, "scroll", {
        "selector": str(config.get("selector") or ""),
        "dy": _int(config.get("dy"), 600),
        "allow_missing": _truthy(config.get("allow_missing")),
    })
    return {"session": sid}


@register("browser_evaluate")
def browser_evaluate(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    sid = _session_in(db, scope, config)
    #: 脚本原样交出去(它不插值,见 binding),上游的值在 input 里、作为 JSON 数据进脚本(见 electron 的 scriptWithInput)。
    raw_input = config.get("input")
    args: dict[str, Any] = {
        "expression": str(config.get("expression") or ""),
        "input": raw_input if isinstance(raw_input, dict) else {},
    }
    #: 长读脚本(分页拉评论这类)可以声明自己的预算;缺省仍是 worker 的 20s。上限三分钟,
    #: 再大就是挂起而不是读取。后端轮询的上限要比脚本预算宽一点,不然 worker 还在跑这边先超时。
    timeout_ms = _int(config.get("timeout_ms"), 0)
    if timeout_ms:
        timeout_ms = min(max(timeout_ms, 1000), 180_000)
        args["timeout_ms"] = timeout_ms
    out = _run(sid, "evaluate", args, timeout=timeout_ms / 1000 + 15 if timeout_ms else None)
    return {"session": sid, "value": out.get("value")}


@register("browser_close")
def browser_close(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    # 留空不报错:上游分支没走到「打开浏览器」时,关闭这一步本来就无事可做。
    if not str(config.get("session") or "").strip():
        return {}
    browser.close_session(db, _session_in(db, scope, config))
    return {}

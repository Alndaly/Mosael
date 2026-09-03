from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.permissions import ensure_workspace_perm
from app.db.models import PublishAccount, Sequence, ToolConfirmation, User, now
from app.domain.jobs import reset_receipt, set_receipt
from app.domain.sequences import operations as seq_ops
from app.domain.workflows import external_nodes_in_graph

"""
Confirmation kernel (plan §16.2/§17.2): mutating external-agent tools never
execute directly. They create a pending confirmation; the user approves it in
the UI, and only then does the mapped action run. Timeline edits go through
SequenceOperations, so every approved edit stays undoable.
"""


class ConfirmationError(ValueError):
    pass


# Tool registry with permission levels (plan §17.4).
TOOL_DEFS: dict[str, dict[str, str]] = {
    "edit_timeline": {"permission": "edit", "cost": "none"},
    "render_sequence": {"permission": "render-cost", "cost": "render"},
    "convert_video_to_gif": {"permission": "render-cost", "cost": "render"},
    "generate_image": {"permission": "ai-cost", "cost": "ai"},
    "generate_video": {"permission": "ai-cost", "cost": "ai"},
    "generate_audio": {"permission": "ai-cost", "cost": "ai"},
    "generate_podcast": {"permission": "ai-cost", "cost": "ai"},
    # 工作流:建/改是编辑权限;运行可能触发渲染与 AI 消耗,按最高档要求确认。
    "create_workflow": {"permission": "edit", "cost": "none"},
    "update_workflow": {"permission": "edit", "cost": "none"},
    "edit_workflow": {"permission": "edit", "cost": "none"},
    # 创意画板:改的是用户攒想法的那张画布,和改工作流同一档 —— 最坏也撤得回。
    "edit_board": {"permission": "edit", "cost": "none"},
    "run_workflow": {"permission": "ai-cost", "cost": "ai"},
    # 智能体开一个隔离浏览器并导航——入口确认(用户看到目标网址再放行);后续同会话动作内联。
    "browser_open": {"permission": "edit", "cost": "none"},
    # 智能体复用用户**已登录**的浏览器池档案——跨信任边界,确认卡点名是哪个登录身份,用户逐次显式授权。
    # 它是 external 而不是 edit:`edit` 那一档的含义是"最坏也撤得回",而这里交出去的是用户在别人
    # 站点上的**真实身份** —— 拿它发的帖、下的单、改的资料,这个应用一件也撤不回。
    "browser_pool_open": {"permission": "external", "cost": "none"},
    # 后果不在这个应用里的三件事:发出去的帖子、别人服务器上的改动、本机跑过的代码。
    # 前面几档最坏是花钱或改坏自己的数据(可撤销),这一档撤不回来,所以单列一个权限档次
    # ——确认卡上的措辞得和「编辑时间线」明显不同,用户才会真的看一眼再点。
    "publish_asset": {"permission": "external", "cost": "none"},
    "http_request": {"permission": "external", "cost": "none"},
    "run_code": {"permission": "external", "cost": "none"},
}

#: 时间线操作的种类由**序列域**说了算(见 domain/sequences/operations)——
#: 那是"能对时间线做什么"的清单,不是智能体这一个入口的清单。
EDIT_OP_KINDS = seq_ops.EDIT_OP_KINDS


def request_confirmation(
    db: Session,
    *,
    workspace_id: str,
    tool: str,
    payload: dict[str, Any],
    requested_by: str = "external-agent",
    session_id: str | None = None,
) -> ToolConfirmation:
    definition = TOOL_DEFS.get(tool)
    if definition is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    _validate_payload(db, tool, workspace_id, payload)
    external = external_nodes_in_graph(_graph_under_review(db, tool, payload))
    confirmation = ToolConfirmation(
        workspace_id=workspace_id,
        tool=tool,
        permission="external" if external else definition["permission"],
        summary=_summarize(tool, payload, external),
        payload=payload,
        requested_by=requested_by,
        session_id=session_id,
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return confirmation


def authorize_and_approve(db: Session, user: User, confirmation: ToolConfirmation) -> ToolConfirmation:
    """批准一张确认卡 —— **所有入口的唯一实现**。

    入口不止一个:桌面端走 HTTP 路由(bearer token 认身份),飞书走卡片回调(open_id 经账号
    绑定认身份)。身份怎么认由入口负责,认出来之后「这个人能不能批、批了会发生什么」必须只有
    一份 —— 之前是两边各抄一遍,谁往路由里加第四道校验,飞书那条就会静默漏掉,而这恰恰是授权
    路径,漏掉等于越权。

    两道闸门缺一不可:
      - ensure_workspace_perm(edit):他得是这个工作区的人,**而且**持有 edit。这里点名 edit,
        而不是靠 ensure_workspace_access 去看「当前请求是不是 POST」—— 那个判断读的是只在 ASGI
        中间件里绑定的 ContextVar,默认 GET。今天两个入口都是 POST,所以校验碰巧成立;哪天批准
        从后台线程发起(自动放行、重试、队列),viewer 的批准就会连同执行一起通过且不报错。
        批准永远是写操作,权限就该显式写出来。
      - 记在谁头上:decided_by。

    此前这里还有第三道 —— `ensure_graph_node_privileges`,专门挡 code 节点。它随隔离执行器一起
    撤掉了(ADR 0008 D2):那道闸本来就是缺沙箱的补丁,而「谁有资格写代码」是个错问题。代码现在
    跑在内核强制的隔离里(见 domain/sandbox),写它就是普通的内容编辑。
    """
    ensure_workspace_perm(db, user, confirmation.workspace_id, "edit")
    # 记在谁头上。自动放行也有人 —— 这次 turn 是以他的身份跑的,上面三道闸也是按他校验的。
    # `decision_mode` 不在这里定:默认就是 manual(人点的),自动放行会在派活之前先改掉它。
    confirmation.decided_by = user.id
    return approve_confirmation(db, confirmation)


def effective_permission(db: Session, tool: str, payload: dict[str, Any]) -> str:
    """这次调用**实际属于**哪一档。`TOOL_DEFS` 里的值只是下限。

    静态表说不清后果,因为同一个工具的后果取决于参数:`run_workflow` 挂在 `ai-cost` 上,而它要跑的
    那张图里可能有 publish / http_request / code / browser_* —— 一张"可能产生 AI 消耗"的卡能执行
    以上全部。反过来,一张只有 llm 节点的图就真的只是花钱。

    工作流的**写入**同样按结果图定档,而不是按"这只是一次编辑":一旦 publish 节点写进图里,点着
    它的可以是定时器或 webhook,那时没有任何卡挡在前面 —— 所以闸必须落在写进去的那一刻。

    档位不是徽标而已:它决定卡片的措辞,三档权限模式下还直接决定要不要放行。定错了,放开的就是
    错的东西。
    """
    definition = TOOL_DEFS.get(tool)
    if definition is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    if external_nodes_in_graph(_graph_under_review(db, tool, payload)):
        return "external"
    return definition["permission"]


def _graph_to_persist(db: Session, tool: str, payload: dict[str, Any]) -> object:
    """这张卡批准之后**会写进库**的那张图。**特权门禁**看的是它。

    只有三个工具会落库。`run_workflow` 不在其中 —— 它执行一张**已经落过库**的图,而那张图在写入
    的那一刻就过过门禁了;把运行也当成落库,等于让不是 instance-admin 的 editor 连别人建好的
    工作流都跑不了(而且定时/webhook 触发根本没有"操作人"可校验)。

    create/update_workflow 带着整份图,取 `payload["graph"]` 就是它。edit_workflow 只带
    `operations` —— 图要把 ops 应用到当前图上才出现。此前门禁一律读 `payload.get("graph")`,
    于是 edit_workflow 那条恒为 None、静默跳过:editor 在画布上存不下 code 节点(三条路由都挡),
    却可以让智能体 add_node(type=code) 再自己批一下,门就白设了。

    必须**应用后再扫**,不能只看 ops 里的 node type:`set_node_config` 能把一整张含 code 的图
    塞进子图体里,那一手在 ops 层面看不见,在结果图上一眼就能看见(扫描器本来就递归子图体)。

    ops 应用不了(图在开卡后被改过)就返回 None:同一份 apply_graph_ops 紧接着会在 _execute 里
    再跑一次并失败,什么都不会落库 —— 这里不放行任何东西,所以不是 fail-open。
    """
    if tool in ("create_workflow", "update_workflow"):
        return payload.get("graph")
    if tool != "edit_workflow":
        return None
    from app.db.models import Workflow
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.graph_ops import apply_graph_ops

    workflow = db.get(Workflow, str(payload.get("workflow_id") or ""))
    if workflow is None:
        return None
    try:
        return apply_graph_ops(workflow.graph or {}, payload.get("operations") or [])
    except WorkflowDomainError:
        return None


def _graph_under_review(db: Session, tool: str, payload: dict[str, Any]) -> object:
    """这次调用会**落库或执行**的那张图。**档位派生**看的是它。

    比落库那张多一个 `run_workflow`:运行不写库,但它把图里的每个节点真的执行一遍 —— 对"后果落在
    哪"这个问题,运行恰恰是后果发生的那一刻。两个问题的答案不同,所以是两个函数而不是一个带开关的
    (一个开关迟早会被下一个调用方按错)。
    """
    if tool == "run_workflow":
        from app.db.models import Workflow

        workflow = db.get(Workflow, str(payload.get("workflow_id") or ""))
        return workflow.graph if workflow is not None else None
    return _graph_to_persist(db, tool, payload)


def authorize_and_reject(db: Session, user: User, confirmation: ToolConfirmation) -> ToolConfirmation:
    """拒绝一张确认卡。同样要 edit —— 拒绝是对**别人发起的待办**下结论,和批准是同一类决定。

    这不是收紧:两个入口都是 POST,而 ensure_workspace_access 在 POST 上判的就是 edit,所以
    走 HTTP 一直如此。写成显式的,是为了不让同一个人在两条调用路径上得到两种答案。
    """
    ensure_workspace_perm(db, user, confirmation.workspace_id, "edit")
    return reject_confirmation(db, confirmation)




def reject_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "rejected")
    confirmation.resolved_at = now()
    db.commit()
    return confirmation


def approve_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "approved")
    try:
        result = _execute(db, confirmation)
        confirmation.status = "executed"
        confirmation.result = result
    except Exception as exc:
        confirmation.status = "failed"
        confirmation.error = str(exc)[:500]
    confirmation.resolved_at = now()
    db.commit()
    db.refresh(confirmation)
    return confirmation


def _claim(db: Session, confirmation: ToolConfirmation, to_status: str) -> None:
    """Take exclusive ownership of a pending confirmation, or refuse.

    Reading `confirmation.status` off the in-memory object and then assigning it is a
    check-then-act: two requests that both load the pending row both pass the check and both
    run the executor. That is a second track added, a second render queued, a second image
    billed. One conditional UPDATE lets the database pick a winner instead — the loser changes
    no rows and is told the confirmation is already settled.
    """
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.id == confirmation.id, ToolConfirmation.status == "pending")
        .values(status=to_status)
    )
    db.commit()
    db.refresh(confirmation)
    if result.rowcount != 1:
        raise ConfirmationError(f"Confirmation is already {confirmation.status}")


def _validate_payload(db: Session, tool: str, workspace_id: str, payload: dict[str, Any]) -> None:
    if tool == "run_code":
        # 这台机器上隔离不住就不开卡 —— 不该开一张注定执行不了的卡去等用户点。
        # 判据是**有没有真的隔离得住**,不是一个开关(见 domain/sandbox)。
        from app.domain import sandbox

        if sandbox.active_backend() is None:
            raise ConfirmationError(
                "这台机器上没有可用的代码隔离环境,因此不执行代码。请在部署机上安装并启动 Docker。"
            )
    if tool == "browser_open":
        url = str(payload.get("url") or "").strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            raise ConfirmationError("浏览器只能打开 http(s) 网址")
    if tool == "http_request":
        url = str(payload.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            # file:// 会把本机文件读成「请求结果」交回给模型。只认 http(s),而且在**开卡时**就认 ——
            # 一张说不清要请求什么的卡,没有让用户去点批准的道理。
            raise ConfirmationError("只能请求 http(s) 网址")
    if tool == "browser_pool_open":
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
    if tool in ("edit_timeline", "render_sequence"):
        sequence = db.get(Sequence, str(payload.get("sequence_id", "")))
        if sequence is None or sequence.workspace_id != workspace_id:
            raise ConfirmationError("Sequence not found in this workspace")
    if tool == "convert_video_to_gif":
        from app.db.models import Asset

        asset = db.get(Asset, str(payload.get("asset_id") or ""))
        if asset is None or asset.workspace_id != workspace_id:
            raise ConfirmationError("这个工作区里没有这份视频素材")
        if asset.kind != "video":
            raise ConfirmationError("只有视频素材可以转换为 GIF")
        try:
            fps = int(payload.get("fps") or 12)
            width = int(payload.get("width") or 720)
            start = float(payload.get("start") or 0)
            duration = payload.get("duration")
            duration = float(duration) if duration not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ConfirmationError("GIF 参数格式不正确") from exc
        if fps < 1 or fps > 30 or width < 64 or width > 1920 or start < 0 or (duration is not None and duration <= 0):
            raise ConfirmationError("GIF 参数超出允许范围")
    if tool == "edit_timeline":
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ConfirmationError("edit_timeline requires a non-empty operations list")
        for operation in operations:
            kind = operation.get("kind") if isinstance(operation, dict) else None
            if kind not in EDIT_OP_KINDS:
                raise ConfirmationError(f"Unsupported timeline operation: {kind}")
    if tool in ("generate_image", "generate_video", "generate_audio"):
        if not str(payload.get("prompt") or payload.get("text") or "").strip():
            raise ConfirmationError("Generation requires a prompt")
    if tool == "generate_podcast":
        mode = str(payload.get("mode") or "summarize")
        if mode not in {"summarize", "read", "research"}:
            raise ConfirmationError("Unsupported podcast mode")
        if mode == "research":
            required = payload.get("topic")
        else:
            required = payload.get("text") or payload.get("prompt")
        if not str(required or "").strip():
            raise ConfirmationError("Podcast generation requires text or topic")
    if tool == "create_workflow":
        from app.domain.workflows import validate_graph

        if not str(payload.get("name", "")).strip():
            raise ConfirmationError("create_workflow requires a name")
        if payload.get("graph") is not None:
            errors = validate_graph(payload["graph"], require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))
    if tool in ("update_workflow", "edit_workflow", "run_workflow"):
        from app.db.models import Workflow
        from app.domain.workflows import validate_graph

        workflow = db.get(Workflow, str(payload.get("workflow_id", "")))
        if workflow is None or workflow.workspace_id != workspace_id:
            raise ConfirmationError("Workflow not found in this workspace")
        if tool == "update_workflow" and payload.get("graph") is not None:
            errors = validate_graph(payload["graph"], require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))
        if tool == "edit_workflow":
            from app.domain.workflows import WorkflowDomainError
            from app.domain.workflows.graph_ops import GRAPH_OP_KINDS, apply_graph_ops

            operations = payload.get("operations")
            if not isinstance(operations, list) or not operations:
                raise ConfirmationError("edit_workflow requires a non-empty operations list")
            for operation in operations:
                kind = operation.get("kind") if isinstance(operation, dict) else None
                if kind not in GRAPH_OP_KINDS:
                    raise ConfirmationError(f"Unsupported workflow op: {kind}")
            # Dry-run the ops onto the current graph so malformed edits fail fast (before approval).
            try:
                preview = apply_graph_ops(workflow.graph or {}, operations)
            except WorkflowDomainError as exc:
                raise ConfirmationError(str(exc)) from exc
            errors = validate_graph(preview, require_config=False, allow_missing_start=True)
            if errors:
                raise ConfirmationError("；".join(errors))


    if tool == "edit_board":
        from app.db.models import Board
        from app.domain.board_ops import BOARD_OP_KINDS, apply_board_ops
        from app.domain.boards import BoardDomainError, normalize_canvas

        board = db.get(Board, str(payload.get("board_id", "")))
        if board is None or board.workspace_id != workspace_id:
            raise ConfirmationError("这个工作区里没有这张画板")
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ConfirmationError("edit_board 需要一个非空的 operations 列表")
        for operation in operations:
            kind = operation.get("kind") if isinstance(operation, dict) else None
            if kind not in BOARD_OP_KINDS:
                raise ConfirmationError(f"不支持的画板算子:{kind}")
        # 先干跑一遍:写坏的算子要在**批准之前**就失败,而不是让用户点了同意才看到报错。
        try:
            normalize_canvas(apply_board_ops(board.canvas or {}, operations))
        except BoardDomainError as exc:
            raise ConfirmationError(str(exc)) from exc


def _external_warning(external: set[str] | None) -> str:
    """把「这张图会伸到应用外面去」写成人话,挂在摘要末尾。

    摘要是用户点批准之前唯一会读的一行。`edit_workflow` 早就为 code 节点这么做了(见
    test_confirmation_disclosure);同样的理由对 `run_workflow` 一字不差地成立 —— 而它此前只说
    「可能产生 AI/渲染消耗」,把"会用你的账号发帖"整个咽了回去。
    """
    if not external:
        return ""
    from app.domain.workflows import NODE_TYPES

    #: 目录里存的是 key(见 core/i18n),这句话是给**用户**看的 —— 直接拼进去的话卡上会写
    #: 「含 wfNode_code 节点」。这里就是出口,所以在这里翻。
    from app.core.i18n import get_current_locale, t

    locale = get_current_locale()
    labels = sorted(t(str((NODE_TYPES.get(name) or {}).get("label") or name), locale) for name in external)
    return f"  ⚠️ 含{'、'.join(labels)}节点(后果在本应用之外,撤不回)"


def _summarize(tool: str, payload: dict[str, Any], external: set[str] | None = None) -> str:
    if tool == "edit_timeline":
        kinds = [operation.get("kind", "?") for operation in payload.get("operations", [])]
        return f"{len(kinds)} 个时间线操作: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
    if tool == "render_sequence":
        return "导出时间线为 mp4"
    if tool == "convert_video_to_gif":
        duration = payload.get("duration")
        clip = f"，截取 {duration} 秒" if duration not in (None, "") else ""
        return f"把视频转成新的 GIF（{payload.get('fps', 12)} fps，宽 {payload.get('width', 720)} px{clip}），原视频不变"
    if tool == "create_workflow":
        nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
        return f"创建工作流「{payload.get('name', '')}」({nodes or 1} 个节点)" + _external_warning(external)
    if tool == "update_workflow":
        nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
        head = f"修改工作流({nodes} 个节点)" if nodes else "修改工作流"
        return head + _external_warning(external)
    if tool == "edit_board":
        kinds = [op.get("kind", "?") for op in payload.get("operations", []) if isinstance(op, dict)]
        return f"{len(kinds)} 个画板编辑: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
    if tool == "edit_workflow":
        ops = [op for op in payload.get("operations", []) if isinstance(op, dict)]
        kinds = [op.get("kind", "?") for op in ops]
        # A `code` node runs arbitrary local Python when the workflow is later run, so say so
        # here rather than leaving it to be noticed in the payload.
        adds_code = any(
            op.get("kind") == "add_node" and str(op.get("node_type") or op.get("type")) == "code" for op in ops
        )
        head = f"{len(kinds)} 个工作流编辑: {', '.join(kinds[:6])}{'…' if len(kinds) > 6 else ''}"
        # code 那句更具体(点名"运行时执行本地 Python"),留着;其余外部节点走通用那句。
        if adds_code:
            return head + "  ⚠️ 含代码节点(运行时执行本地 Python)"
        return head + _external_warning(external)
    if tool == "run_workflow":
        name = str(payload.get("name") or payload.get("workflow_id") or "")
        head = f"运行工作流{f'「{name}」' if name else ''}(可能产生 AI/渲染消耗)"
        return head + _external_warning(external)
    if tool == "browser_open":
        url = str(payload.get("url") or "").strip()
        mode = "具名持久" if str(payload.get("session_mode")) == "named" else "临时"
        return f"智能体打开{mode}浏览器" + (f" → {url}" if url else "")
    if tool == "browser_pool_open":
        name = str(payload.get("profile_name") or payload.get("profile_id") or "")
        platform = payload.get("platform")
        who = f"「{name}」" + (f"({platform} 发布账号)" if platform else "(通用档案)")
        url = str(payload.get("url") or "").strip()
        return f"⚠️ 智能体请求复用你的浏览器档案 {who} 的登录身份跑任务" + (f" → {url}" if url else "")
    if tool == "publish_asset":
        title = str(payload.get("title") or "").strip()
        return f"⚠️ 用你的账号**公开发布**{f'「{title}」' if title else '一条内容'}"
    if tool == "http_request":
        return f"⚠️ 向外部发起 {payload.get('method', 'POST')} 请求: {str(payload.get('url') or '')[:120]}"
    if tool == "run_code":
        code = str(payload.get("code") or "")
        head = code.strip().splitlines()[0][:60] if code.strip() else ""
        return f"⚠️ 在你的机器上运行一段 Python({len(code)} 字符){f': {head}…' if head else ''}"
    prompt = str(payload.get("prompt") or payload.get("text") or payload.get("topic") or "")[:80]
    if tool == "generate_image":
        return f"生成图片: {prompt}"
    if tool == "generate_video":
        return f"生成视频: {prompt}"
    if tool == "generate_audio":
        return f"生成音频: {prompt}"
    if tool == "generate_podcast":
        return f"生成播客: {prompt}"
    return f"{tool}: {prompt}"


def _execute(db: Session, confirmation: ToolConfirmation) -> dict[str, Any]:
    """跑这张卡批准的那件事。

    整段包在 set_receipt 里:**这里面建的任何后台任务,干完了都把回执送回发起它的那次对话**。
    智能体此前提交完就断了线索,只知道「提交成功」,不知道跑完没有 —— 要么反复轮询,要么
    干脆当作没这回事。发布/导出/生成各有各的入口函数,逐个加参数就得每加一种任务改一处,
    而漏掉的那一处不会报错,只是那种任务的回执永远送不到。
    """
    if confirmation.session_id:
        from app.domain.agent.receipts import receipt_to_session

        token = set_receipt(receipt_to_session(confirmation.session_id))
        try:
            return _execute_approved(db, confirmation)
        finally:
            reset_receipt(token)
    return _execute_approved(db, confirmation)


def _execute_approved(db: Session, confirmation: ToolConfirmation) -> dict[str, Any]:
    payload = confirmation.payload
    # 这一步替谁干:批准它的那个人。智能体自己不是主体 —— 它花的是批准者的额度、用的是
    # 批准者的钥匙(见 domain/provider_credentials 与 Job.created_by)。
    actor = confirmation.decided_by
    if confirmation.tool == "publish_asset":
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
    if confirmation.tool == "http_request":
        from app.domain.workflows.executors.basic import run_http

        return run_http(
            method=str(payload.get("method") or "POST"),
            url=str(payload["url"]),
            headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
            body=str(payload.get("body") or ""),
        )
    if confirmation.tool == "run_code":
        from app.domain.workflows.executors.basic import run_python

        return run_python(str(payload.get("code") or ""), dict(payload.get("inputs") or {}))
    if confirmation.tool == "browser_open":
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
    if confirmation.tool == "browser_pool_open":
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
    if confirmation.tool == "edit_timeline":
        return _execute_edit_timeline(db, payload)
    if confirmation.tool == "render_sequence":
        from app.domain.render import start_export

        job = start_export(db, str(payload["sequence_id"]))
        return {"job_id": job.id}
    if confirmation.tool == "convert_video_to_gif":
        from app.db.models import Asset
        from app.domain.assets.video_gif import start_video_to_gif

        asset = db.get(Asset, str(payload["asset_id"]))
        if asset is None or asset.workspace_id != confirmation.workspace_id:
            raise ValueError("素材不存在")
        duration = payload.get("duration")
        job = start_video_to_gif(
            db,
            asset=asset,
            created_by=actor,
            fps=int(payload.get("fps") or 12),
            width=int(payload.get("width") or 720),
            start=float(payload.get("start") or 0),
            duration=float(duration) if duration not in (None, "") else None,
        )
        return {"job_id": job.id, "source_asset_id": asset.id}
    if confirmation.tool in ("generate_image", "generate_video"):
        from app.domain.generation import create_generation_job
        from app.domain.generation.operations import parse_source_assets
        from app.domain.generation.runner import start_generation_thread
        from app.domain import provider_models
        kind = "image" if confirmation.tool == "generate_image" else "video"
        provider = str(payload.get("provider", "")).strip()
        model = str(payload.get("model", "")).strip()
        if not provider or not model:
            default = provider_models.resolve_default(db, kind, actor)
            if default is not None:
                provider, model = default.profile.vendor, default.model_id
        if not provider or not model:
            raise RuntimeError("没有配置可用于生成的真实供应商和模型")
        generation, job = create_generation_job(
            db,
            workspace_id=confirmation.workspace_id,
            session_id=None,
            project_id=payload.get("project_id"),
            created_by=actor,
            provider=provider,
            model=model,
            kind=kind,
            prompt=str(payload["prompt"]),
            negative_prompt=str(payload.get("negative_prompt", "")),
            parameters=dict(payload.get("parameters") or {}),
            source_assets=parse_source_assets(payload.get("source_assets"), kind=kind),
        )
        start_generation_thread(generation.id)
        return {"job_id": job.id, "generation_id": generation.id}
    if confirmation.tool == "generate_audio":
        from app.domain.voices.voices import start_synthesis
        from app.domain import provider_models

        profile_id = str(payload.get("provider_profile_id") or "").strip()
        engine = str(payload.get("engine") or payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not engine:
            default = provider_models.resolve_default(db, "tts", actor)
            if default is not None:
                profile_id = default.provider_profile_id
                engine = default.profile.vendor
                model = model or default.model_id
        if not engine:
            raise RuntimeError("没有配置可用于语音生成的真实供应商")
        job = start_synthesis(
            db,
            text=str(payload.get("text") or payload.get("prompt") or ""),
            project_id=payload.get("project_id"),
            created_by=actor,
            workspace_id=confirmation.workspace_id,
            engine=engine,
            engine_voice=str(payload.get("voice") or payload.get("engine_voice") or ""),
            engine_voice_resource=str(payload.get("voice_resource") or payload.get("engine_voice_resource") or ""),
            speed=float(payload.get("speed") or 1.0),
            provider_profile_id=profile_id or None,
            engine_model=model,
        )
        return {"job_id": job.id}
    if confirmation.tool == "generate_podcast":
        from app.domain.voices.voices import start_podcast
        from app.domain import provider_models

        profile_id = str(payload.get("provider_profile_id") or "").strip()
        if not profile_id:
            default = provider_models.resolve_default(db, "podcast", actor)
            if default is not None:
                profile_id = default.provider_profile_id
        job = start_podcast(
            db,
            workspace_id=confirmation.workspace_id,
            project_id=payload.get("project_id"),
            created_by=actor,
            text=str(payload.get("text") or payload.get("prompt") or ""),
            topic=str(payload.get("topic") or ""),
            mode=str(payload.get("mode") or "summarize"),
            speakers=list(payload.get("speakers") or []),
            speed=float(payload.get("speed") or 1.0),
            provider_profile_id=profile_id or None,
        )
        return {"job_id": job.id}
    if confirmation.tool == "create_workflow":
        from app.domain.workflows import create_workflow

        workflow = create_workflow(
            db,
            workspace_id=confirmation.workspace_id,
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            graph=payload.get("graph"),
            source="agent",
            created_by=actor,
        )
        return {"workflow_id": workflow.id}
    if confirmation.tool == "update_workflow":
        from app.db.models import Workflow
        from app.domain.workflows import update_workflow

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None  # validated at request time
        update_workflow(
            db,
            workflow,
            {key: payload[key] for key in ("name", "description", "graph") if key in payload},
            source="agent",
            created_by=actor,
        )
        return {"workflow_id": workflow.id}
    if confirmation.tool == "edit_workflow":
        from app.db.models import Workflow
        from app.domain.workflows import update_workflow
        from app.domain.workflows.graph_ops import apply_graph_ops

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None
        # Re-apply onto the CURRENT graph at approval time (not the request-time snapshot).
        new_graph = apply_graph_ops(workflow.graph or {}, payload["operations"])
        update_workflow(
            db,
            workflow,
            {"graph": new_graph},
            source="agent",
            created_by=actor,
        )
        return {"workflow_id": workflow.id, "nodes": len(new_graph.get("nodes", []))}
    if confirmation.tool == "edit_board":
        from app.db.models import Board
        from app.domain.board_ops import apply_board_ops
        from app.domain.boards import update_board

        board = db.get(Board, str(payload["board_id"]))
        assert board is not None  # 开卡时校验过
        # 落到**批准这一刻**的画布上,而不是开卡时的那份快照 —— 这中间用户很可能还在拖东西。
        canvas = apply_board_ops(board.canvas or {}, payload["operations"])
        update_board(db, workspace_id=board.workspace_id, board_id=board.id, name=None, canvas=canvas)
        return {"board_id": board.id, "items": len(canvas.get("items", []))}
    if confirmation.tool == "run_workflow":
        from app.db.models import Workflow
        from app.domain.workflows.engine import start_workflow_job

        workflow = db.get(Workflow, str(payload["workflow_id"]))
        assert workflow is not None
        job = start_workflow_job(db, workflow, created_by=actor, params=dict(payload.get("params") or {}))
        return {"job_id": job.id}
    raise ConfirmationError(f"No executor for tool {confirmation.tool}")


def _execute_edit_timeline(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    sequence_id = str(payload["sequence_id"])
    applied = seq_ops.apply_edit_operations(db, sequence_id, payload["operations"])
    sequence = db.get(Sequence, sequence_id)
    return {"applied_operations": applied, "sequence_revision": sequence.revision if sequence else None}

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.worker_key import LEGACY_WORKER_KEY_HEADER, WORKER_KEY_HEADER, verify_worker_key
from app.core.permissions import ensure_instance_admin, get_current_user
from app.db.models import User

DbSession = Annotated[Session, Depends(session_scope)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def ensure_graph_node_privileges(db: Session, user: User, graph: object) -> None:
    """Gate the workflow nodes that grant host access rather than content access.

    A `code` node runs arbitrary Python on whatever machine hosts the backend. That is process
    isolated (subprocess, `-I`, PATH-only env, 20s, output cap) but deliberately *not* sandboxed:
    the code can read the filesystem and make outbound requests. On a single-user install the
    author is the machine owner, so this is a non-event. On a team/remote backend it is not —
    `edit` is the gate on every mutating workflow route, and editors hold `edit` by default, so
    without this check "can edit content" silently implies "can own the server".

    Same reasoning that already put provider credentials and the interpreter path behind
    `ensure_instance_admin` (see its docstring); this closes the remaining path to the same
    capability. Checked when the graph is *persisted*, not when it runs: scheduler and webhook
    triggers have no acting user to check, and a graph that could never store a `code` node does
    not need a run-time gate. A single-user install owns its default workspace and is unaffected.
    """
    from app.domain.workflows import NODE_TYPES, privileged_nodes_in_graph

    used = privileged_nodes_in_graph(graph)
    if not used:
        return
    try:
        ensure_instance_admin(db, user, "credentials")
    except HTTPException as exc:
        # ensure_instance_admin 的通用文案是「Instance settings require admin with 'credentials'」,
        # 对着一张工作流画布看到这句没人懂自己撞了什么。换成点名节点的说法。
        labels = "、".join(sorted(str(NODE_TYPES.get(t, {}).get("label") or t) for t in used))
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"「{labels}」节点会在后端主机上执行任意代码,只有管理员能保存含此类节点的工作流",
        ) from exc


def require_worker_key(request: Request) -> None:
    """Gate for the local publish-worker channel.

    It carries no user session — the worker is an Electron process, not a person — so it
    authenticates with the per-process secret written to the data directory at startup. A web
    page cannot read that file, which is exactly what separates the worker from any other caller
    able to reach 127.0.0.1.
    """
    # 旧头名一并接受:升级后第一次启动可能是「新壳 + 复用的旧后端」,反之亦然。
    sent = request.headers.get(WORKER_KEY_HEADER) or request.headers.get(LEGACY_WORKER_KEY_HEADER)
    if not verify_worker_key(sent):
        raise HTTPException(status_code=401, detail="Invalid or missing worker key")

"""跨会话记忆:每轮都注入系统提示的那几条事实。

这个模块是 `AgentMemory` 的拥有方(见 domain/ownership.py)。

记忆是**不检索也
生效**的行为约定 —— "视频统一 1080p 竖屏"、"片头永远用 brand-intro.mp4"、"客户不要红色"。
它们的价值恰恰在于不用想起来 —— 用户说过一次,以后每一轮都在。
Claude Code 的 CLAUDE.md、Codex 的 AGENTS.md 解决的是同一个问题,只是那边落在文件里 ——
这个应用里没有"工程目录",所以落在库里,并在设置页给出同一份可编辑的清单。

**注入必须有上限**。记忆是每轮都要付的固定成本:一条 200 字的记忆 × 50 条,就是每轮先烧掉
上万 token,而用户完全看不到这笔开销。所以单条截断、总量封顶,超出的部分不注入 ——
宁可漏掉最旧的几条,也不能让记忆把上下文吃光。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentMemory

#: 单条记忆的字数上限。记忆是**约定**不是**资料** —— 每一轮都要为它付 token,所以它必须短。
MAX_CONTENT_CHARS = 500

#: 注入系统提示的总字数上限。超出后丢最旧的(用户手写的优先保留,见 list_memories 的排序)。
MAX_PROMPT_CHARS = 4000

#: 一个作用域下最多存多少条。到顶后 remember 会拒绝,而不是无声地把最旧的顶掉 ——
#: 静默淘汰会让用户以为记住了,而它已经不在了。
MAX_ENTRIES = 100


def list_memories(db: Session, workspace_id: str, project_id: str | None = None) -> list[AgentMemory]:
    """该工作区(以及可选的某个项目)下生效的记忆。

    只传 workspace_id 时**只返回工作区级**的;传了 project_id 则是"工作区级 + 该项目级",
    与注入时的口径一致 —— 设置页按同一个函数列表,用户看到的就是模型看到的。

    用户手写的排在前面:注入被截断时,先保住人明确写下的那几条。
    """
    stmt = select(AgentMemory).where(AgentMemory.workspace_id == workspace_id)
    if project_id:
        stmt = stmt.where((AgentMemory.project_id.is_(None)) | (AgentMemory.project_id == project_id))
    else:
        stmt = stmt.where(AgentMemory.project_id.is_(None))
    rows = list(db.scalars(stmt))
    rows.sort(key=lambda row: (0 if row.source == "user" else 1, row.created_at))
    return rows


def remember(
    db: Session,
    workspace_id: str,
    content: str,
    *,
    project_id: str | None = None,
    source: str = "agent",
) -> AgentMemory:
    """记一条。这是**唯一**建 AgentMemory 的地方(数据归属棘轮会盯着)。

    同一作用域下内容完全相同的不重复建 —— 模型很容易在不同会话里把同一件事再记一遍,
    不去重的话清单会慢慢长成同义反复。
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("记忆内容不能为空")
    if len(text) > MAX_CONTENT_CHARS:
        raise ValueError(f"单条记忆最多 {MAX_CONTENT_CHARS} 字 —— 它每一轮都要重发一遍,写不下的说明那不是一条约定")
    existing = [row for row in list_memories(db, workspace_id, project_id) if row.content == text]
    if existing:
        return existing[0]
    if len(list_memories(db, workspace_id, project_id)) >= MAX_ENTRIES:
        raise ValueError(f"记忆已达 {MAX_ENTRIES} 条上限,请先删掉不再需要的")
    row = AgentMemory(
        workspace_id=workspace_id,
        project_id=project_id or None,
        content=text,
        source=source if source in ("agent", "user") else "agent",
    )
    db.add(row)
    db.flush()
    return row


def update(db: Session, memory: AgentMemory, content: str) -> AgentMemory:
    text = (content or "").strip()
    if not text:
        raise ValueError("记忆内容不能为空")
    if len(text) > MAX_CONTENT_CHARS:
        raise ValueError(f"单条记忆最多 {MAX_CONTENT_CHARS} 字 —— 它每一轮都要重发一遍,写不下的说明那不是一条约定")
    memory.content = text
    db.flush()
    return memory


def forget(db: Session, memory: AgentMemory) -> None:
    db.delete(memory)
    db.flush()


def get(db: Session, memory_id: str) -> AgentMemory | None:
    return db.get(AgentMemory, memory_id)


def memory_prompt(db: Session, workspace_id: str, project_id: str | None = None) -> str:
    """注入系统提示的那一段。没有记忆时返回空串(**不要**留一个空标题 —— 那等于告诉模型
    "这里本该有东西",它会开始猜)。

    总量封顶:记忆是每轮都付的固定开销,而用户看不到这笔账。宁可漏掉最旧的几条。
    """
    rows = list_memories(db, workspace_id, project_id)
    if not rows:
        return ""
    lines: list[str] = []
    used = 0
    for row in rows:
        line = f"- {row.content}"
        if used + len(line) > MAX_PROMPT_CHARS:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return (
        "\n\n【长期记忆】以下是你在此前的会话中记下、或用户直接写下的约定,默认一直有效:\n"
        + "\n".join(lines)
        + "\n发现新的、值得跨会话保留的约定或事实时,用 remember 记下来(只记约定与偏好,"
        + "不要把对话内容或资料塞进去 —— 它每一轮都要重发一遍)。用户说「不用记了/忘掉」时用 forget 删掉。"
    )

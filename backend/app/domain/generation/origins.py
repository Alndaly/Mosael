"""生成会话的出处(ADR 0052):这条会话是在哪一处开出来的 —— 和对话的「家」(ADR 0044,domain/agent/places)同一个形状,
一个种类加一个 id,建的那一刻定、之后不变。

| 种类 | id | 谁写 |
| --- | --- | --- |
| `studio` | 空 | 创作页自己开的(草稿第一次提交、「新的一条」) |
| `audio_page` | `speech` / `podcast` | 「以前的语音 / 播客」:之前在「音频」页做的,ADR 0055 的迁移并进来的那两条;标题按读的人的语言写 |
| `board` | 画板 id | 画板格子的「生成」、画板上跑的能力 |
| `workflow` | 工作流 id | 工作流里的生成类节点(AI 生成、补全多角度、人物说话) |
| `entity` | 资产 id | 资产详情页的「补全多角度」「生成表情」「说话」(跑的是同一批节点,作用域是资产自己) |
| `schedule` | 定时任务 id | 定时任务 |
| `agent` | 对话 id | 智能体的生成工具(批准确认卡之后) |
| `comfyui` | `<连接 id>/<路径>` | ComfyUI 工作台的「运行」(和 0044 的 `comfyui` 地方同一种写法) |

`studio`、`audio_page` 是「在创作页这边开的」(`HERE`),列在创作页上面;别的收进「来自别处」。

**不设外键**:一列指几种表,而且要的正是「东西删了,会话照旧」(§7)。名字现查(`describe_origins`),查不到是 `deleted`,
看的人看不见是 `hidden`。别处开的会话一处一条(同一个人在同一处的生成都进这一条,`operations._resolve_session`),
不分族 —— 一块画板上本来就有图有歌(锁族是创作页的规矩,ADR 0055 §2)。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentSession, Board, Entity, GenerationSession, ScheduledTask, User, Workflow
from app.domain import sharing
from app.domain.place_names import DELETED, HIDDEN, OK, Describe, Described, comfy_places, workspace_things

STUDIO = "studio"
AUDIO_PAGE = "audio_page"
#: 画板、工作流、ComfyUI 和对话的家(ADR 0044)是同一个种类、同一种 id 写法。
BOARD = "board"
WORKFLOW = "workflow"
ENTITY = "entity"
SCHEDULE = "schedule"
AGENT = "agent"
COMFYUI = "comfyui"

#: 在创作页这边开的:列在上面,不进「来自别处」。
HERE: tuple[str, ...] = (STUDIO, AUDIO_PAGE)

@dataclass(frozen=True)
class Origin:
    kind: str
    id: str = ""


STUDIO_ORIGIN = Origin(STUDIO)


def of_run_scope(scope_id: str) -> Origin:
    """工作流执行器跑在谁名下(`RunScope.id`)→ 出处:画板上跑的能力是 `board:<id>`、资产详情页上的是 `entity:<id>`
    (见 boards.tools.BoardScope、entities.drawing.EntityScope),别的就是那张工作流。"""
    for prefix, kind in (("board:", BOARD), ("entity:", ENTITY)):
        if scope_id.startswith(prefix):
            return Origin(kind, scope_id[len(prefix):])
    return Origin(WORKFLOW, scope_id)


# ---------- 现查名字 ----------
#
# 状况(`GenerationSessionOut.origin_state`)和对话的家同一套:`ok` / `deleted` / `hidden`(domain/place_names)。


def _here(_db: Session, _viewer: User, ids: set[str]) -> Described:
    return {origin_id: (OK, "") for origin_id in ids}


def _shared_thing(model: Any, share_kind: str, name_of: Callable[[Any], str]) -> Describe:
    """定时任务、对话:是某人的,共享进工作区才看得见(domain/sharing)—— 看不见就只说「一个定时任务」「一段对话」。"""

    def describe(db: Session, viewer: User, ids: set[str]) -> Described:
        rows = {row.id: row for row in db.scalars(select(model).where(model.id.in_(ids)))}
        described: Described = {}
        for origin_id in ids:
            row = rows.get(origin_id)
            if row is None:
                described[origin_id] = (DELETED, "")
            elif not sharing.may_use(db, share_kind, row, viewer.id):
                described[origin_id] = (HIDDEN, "")
            else:
                described[origin_id] = (OK, name_of(row))
        return described

    return describe


DESCRIBE: dict[str, Describe] = {
    STUDIO: _here,
    AUDIO_PAGE: _here,
    BOARD: workspace_things(Board, Board.name),
    WORKFLOW: workspace_things(Workflow, Workflow.name),
    COMFYUI: comfy_places,
    ENTITY: workspace_things(Entity, Entity.name),
    SCHEDULE: _shared_thing(ScheduledTask, "scheduled_task", lambda task: task.name or ""),
    AGENT: _shared_thing(AgentSession, "agent_session", lambda session: session.title or ""),
}
KINDS: tuple[str, ...] = tuple(DESCRIBE)


def describe_origins(db: Session, viewer: User, sessions: Iterable[GenerationSession]) -> list[GenerationSession]:
    """给每条会话标上 `origin_name` / `origin_state`(和出参用的 `origin_id_shown`)—— **按看的人**查。每种出处一次查询。"""
    rows = list(sessions)
    wanted: dict[str, set[str]] = {}
    for session in rows:
        wanted.setdefault(session.origin_kind, set()).add(session.origin_id)
    found = {
        (kind, origin_id): result
        for kind, ids in wanted.items()
        for origin_id, result in DESCRIBE.get(kind, _here)(db, viewer, ids).items()
    }
    for session in rows:
        session.origin_state, session.origin_name = found[(session.origin_kind, session.origin_id)]  # type: ignore[attr-defined]
        #: 删了、看不见时连 id 也不给(ComfyUI 的 id 里就是那台机器上的文件路径)。只设在这个不落库的属性上 —— 改
        #: `origin_id` 本身会随事务写回去。`audio_page` 的 id 是给界面挑文案用的,照给。
        session.origin_id_shown = session.origin_id if session.origin_state == OK else ""  # type: ignore[attr-defined]
    return rows

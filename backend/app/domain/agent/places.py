"""地方:界面上的每一处、一段对话的家、每条消息在哪说的,都是这同一个形状 —— 一个种类加一个 id(ADR 0044 §1)。

| 种类 | id |
| --- | --- |
| `studio` | 空(AI Studio,以及页面上没打开哪样东西的时候) |
| `project` / `note` / `board` / `workflow` / `scene` | 那样东西的 id |
| `comfyui` | `<连接 id>/<路径>`(存过的)、`<连接 id>#<标签页 key>`(没存过的)、`<连接 id>`(画布上一张都没开) |

连接 id 里没有 `/`、`#`,从左边第一个 `/` 或 `#` 切开就分得清。

**家不设外键**:一列指六种表,而且要的正是「东西删了,对话照旧」。所以名字现查(`describe_homes`),查不到就是 `deleted`,
看的人看不见就是 `hidden`(只说「在一篇笔记里开的」,标题不漏出来)。每一种地方怎么校验、怎么按 id 批量取名字,摊在
`KINDS` 这一张表上(和 domain/sharing.KINDS 一样):要加第八种地方,改的只是这张表。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, literal, select, update
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import AgentMessage, AgentSession, Board, Note, PluginInstance, Project, Scene3D, User, Workflow, WorkspaceMember
from app.domain.permissions import NotVisible

STUDIO = "studio"
PROJECT = "project"
NOTE = "note"
BOARD = "board"
WORKFLOW = "workflow"
SCENE = "scene"
COMFYUI = "comfyui"

#: 家的三种状况(`AgentSessionOut.home_state`)。
OK = "ok"
DELETED = "deleted"
HIDDEN = "hidden"

#: 一样东西的 id 最长多少(库里的 id 是 32 位十六进制)。ComfyUI 的 id 带路径,上限是列宽。
_THING_ID_CHARS = 64
_COMFY_ID_CHARS = 700


@dataclass(frozen=True)
class Place:
    kind: str
    id: str = ""

    def as_payload(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}


STUDIO_PLACE = Place(STUDIO)


class PlaceError(LocalizedError, ValueError):
    """地方的形状不对(种类不认识、id 写法不对),或者那个 ComfyUI 连接不是他的。api 翻成 422。"""


# ---------- 形状 ----------


def comfy_parts(place_id: str) -> tuple[str, str, str]:
    """(连接 id, 存过的路径, 没存过的标签页 key):后两样至多一样不空。从左边第一个 `/` 或 `#` 切开。"""
    marks = [index for index in (place_id.find("/"), place_id.find("#")) if index >= 0]
    if not marks:
        return place_id, "", ""
    cut = min(marks)
    connection, rest = place_id[:cut], place_id[cut + 1:]
    return (connection, rest, "") if place_id[cut] == "/" else (connection, "", rest)


def checked(kind: str, place_id: str) -> Place:
    """只校验形状 —— 那样东西在不在、他看不看得见,是 `ensure_home` 的事。"""
    place_id = place_id or ""
    if kind not in KINDS:
        raise PlaceError("agentErr_placeUnknownKind", kind=kind)
    if kind == STUDIO:
        if place_id:
            raise PlaceError("agentErr_placeBadId", kind=kind)
    elif kind == COMFYUI:
        connection, path, key = comfy_parts(place_id)
        segments = path.split("/")
        if (
            not connection
            or len(place_id) > _COMFY_ID_CHARS
            or any(ord(char) < 32 for char in place_id)
            or (path and ("" in segments or ".." in segments))
            or (place_id != connection and not (path or key))
        ):
            raise PlaceError("agentErr_placeBadId", kind=kind)
    elif not place_id or len(place_id) > _THING_ID_CHARS:
        raise PlaceError("agentErr_placeBadId", kind=kind)
    return Place(kind, place_id)


def from_payload(value: Any) -> Place | None:
    """消息 payload 里记着的 `place`。没有(飞书、另一段对话的通知、老消息)就是 None。"""
    if not isinstance(value, dict):
        return None
    try:
        return checked(str(value.get("kind") or ""), str(value.get("id") or ""))
    except PlaceError:
        return None


def home_of(session: AgentSession) -> Place:
    return Place(session.home_kind, session.home_id)


def turn_place(db: Session, session: AgentSession) -> Place:
    """这一轮在哪(ADR 0044 §8):这一轮要回答的那条用户消息记着的 `place` —— 最新一条不在排队的用户消息;它没记
    (飞书、另一段对话发来的通知、老消息)就是这段对话的家。决定这一轮发哪些工具,水位也照它算。"""
    #: 排在队里的(还没轮到它们的)从最新的往前跳过;队不会排到几十条那么长。
    payloads = db.scalars(
        select(AgentMessage.payload)
        .where(AgentMessage.session_id == session.id, AgentMessage.role == "user")
        .order_by(AgentMessage.created_at.desc())
        .limit(50)
    )
    latest = next((payload for payload in payloads if not (payload or {}).get("queued")), None)
    return from_payload((latest or {}).get("place")) or home_of(session)


def memory_project(session: AgentSession) -> str | None:
    """项目级记忆跟着家走:家是一个剪辑项目时注入那个项目的(此前读的 `project_id` 界面从没设过)。"""
    return session.home_id if session.home_kind == PROJECT else None


# ---------- 每一种地方:校验、按 id 批量取名字 ----------

#: id → (状况, 名字)。看不见、删了的,名字是空串 —— 响应里不出现看的人看不见的标题。
Described = dict[str, tuple[str, str]]


@dataclass(frozen=True)
class PlaceKind:
    #: 建会话时:那样东西在、他看得见、在这个工作区里。不在 / 看不见是 `NotVisible`(404),连接不是他的是 `PlaceError`(422)。
    ensure: Callable[[Session, User, str, str], None]
    describe: Callable[[Session, User, set[str]], Described]
    #: 给智能体看的那句「在…里开的」:(有名字时, 删了时, 看不见时)。
    words: tuple[str, ...]


def _studio_ensure(_db: Session, _user: User, _workspace_id: str, _place_id: str) -> None:
    return None


def _studio_describe(_db: Session, _viewer: User, ids: set[str]) -> Described:
    return {place_id: (OK, "") for place_id in ids}


def _workspace_thing(model: Any, name_column: Any, words: tuple[str, str, str]) -> PlaceKind:
    """剪辑项目、笔记、画板、工作流、3D 场景:都是工作区里的东西,工作区的人都看得见(各自的读闸都是「它在、你是这个
    工作区的人」)。建会话时它得在这次对话所在的工作区里 —— 别的工作区的和不存在的是同一个回答。"""

    def ensure(db: Session, _user: User, workspace_id: str, place_id: str) -> None:
        owner_workspace = db.scalar(select(model.workspace_id).where(model.id == place_id))
        if owner_workspace != workspace_id:
            raise NotVisible("Not found")

    def describe(db: Session, viewer: User, ids: set[str]) -> Described:
        rows = db.execute(select(model.id, name_column, model.workspace_id).where(model.id.in_(ids))).all()
        mine = set(db.scalars(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == viewer.id)))
        found = {row[0]: ((OK, row[1] or "") if row[2] in mine else (HIDDEN, "")) for row in rows}
        return {place_id: found.get(place_id, (DELETED, "")) for place_id in ids}

    return PlaceKind(ensure=ensure, describe=describe, words=words)


def _comfy_connection(db: Session, user: User, connection_id: str) -> PluginInstance | None:
    """他自己接的、认领了工作流库的那个连接(和 workbench_agent.connection 同一条:连接归人)。"""
    from app.domain.plugins import instances as inst
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.manifest import WORKFLOW_LIBRARY

    instance = db.get(PluginInstance, connection_id)
    if instance is None or instance.owner_user_id != user.id:
        return None
    try:
        provides = inst.manifest_for(db, instance).provides
    except PluginDomainError:  # 包卸掉了
        return None
    return instance if WORKFLOW_LIBRARY in provides else None


def _comfy_ensure(db: Session, user: User, _workspace_id: str, place_id: str) -> None:
    """连接得是他能用的;路径只校验形状 —— 那台机器上有没有这个文件不问(要连过去,而且没存过的本来就不在)。"""
    if _comfy_connection(db, user, comfy_parts(place_id)[0]) is None:
        raise PlaceError("agentErr_placeNotYourComfy")


def _file_name(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[: -len(".json")] if name.lower().endswith(".json") else name


def _comfy_describe(db: Session, viewer: User, ids: set[str]) -> Described:
    """名字取路径里的文件名(不连那台机器);画布上一张都没开的,是连接的名字。连接删了是 `deleted`,不是他的是 `hidden`。"""
    connections = {comfy_parts(place_id)[0] for place_id in ids}
    owners = dict(db.execute(
        select(PluginInstance.id, PluginInstance.owner_user_id).where(PluginInstance.id.in_(connections))
    ).all())
    names = dict(db.execute(select(PluginInstance.id, PluginInstance.name).where(PluginInstance.id.in_(connections))).all())
    described: Described = {}
    for place_id in ids:
        connection, path, key = comfy_parts(place_id)
        if connection not in owners:
            described[place_id] = (DELETED, "")
        elif owners[connection] != viewer.id:
            described[place_id] = (HIDDEN, "")
        else:
            described[place_id] = (OK, _file_name(path or key) if (path or key) else names[connection])
    return described


KINDS: dict[str, PlaceKind] = {
    STUDIO: PlaceKind(ensure=_studio_ensure, describe=_studio_describe, words=("在 AI Studio 里开的",) * 3),
    PROJECT: _workspace_thing(Project, Project.name, ("在剪辑《{name}》里开的", "在已删除的剪辑项目里开的", "在一个剪辑项目里开的")),
    NOTE: _workspace_thing(Note, Note.title, ("在笔记《{name}》里开的", "在已删除的笔记里开的", "在一篇笔记里开的")),
    BOARD: _workspace_thing(Board, Board.name, ("在创意画板《{name}》里开的", "在已删除的创意画板里开的", "在一块创意画板里开的")),
    WORKFLOW: _workspace_thing(Workflow, Workflow.name, ("在工作流《{name}》里开的", "在已删除的工作流里开的", "在一个工作流里开的")),
    SCENE: _workspace_thing(Scene3D, Scene3D.name, ("在 3D 场景《{name}》里开的", "在已删除的 3D 场景里开的", "在一个 3D 场景里开的")),
    COMFYUI: PlaceKind(
        ensure=_comfy_ensure, describe=_comfy_describe,
        words=("在 ComfyUI 的《{name}》里开的", "在已删除的 ComfyUI 连接里开的", "在一台 ComfyUI 里开的"),
    ),
}


def ensure_home(db: Session, user: User, workspace_id: str, place: Place) -> Place:
    """建会话时的家:形状对、那样东西在、他看得见。工作区的 `ai` 权限由调用方先查。"""
    home = checked(place.kind, place.id)
    KINDS[home.kind].ensure(db, user, workspace_id, home.id)
    return home


def describe_homes(db: Session, viewer: User, sessions: Iterable[AgentSession]) -> list[AgentSession]:
    """给每段对话标上 `home_name` / `home_state`(和出参用的 `home_id_shown`)—— **按看的人**查。一页五十条,每种地方一次查询。"""
    rows = list(sessions)
    wanted: dict[str, set[str]] = {}
    for session in rows:
        wanted.setdefault(session.home_kind, set()).add(session.home_id)
    found = {
        (kind, place_id): result
        for kind, ids in wanted.items()
        for place_id, result in KINDS[kind].describe(db, viewer, ids).items()
    }
    for session in rows:
        session.home_state, session.home_name = found[(session.home_kind, session.home_id)]
        #: 家删了、看不见时,响应里连 id 也不给:ComfyUI 的 id 里就是那台机器上的文件路径。只设在这个不落库的属性上 ——
        #: 改 `home_id` 本身会随事务写回去。
        session.home_id_shown = session.home_id if session.home_state == OK else ""
    return rows


def where(session: AgentSession) -> str:
    """给智能体看的那句「在笔记《B》里开的」(list_agent_sessions):找该通知谁时,看得出哪段是哪儿的。
    先 `describe_homes`。"""
    named, deleted, hidden = KINDS[session.home_kind].words
    if session.home_state == DELETED:
        return deleted
    if session.home_state == HIDDEN:
        return hidden
    if session.home_kind == COMFYUI:
        _connection, path, key = comfy_parts(session.home_id)
        if key:
            named = "在 ComfyUI 没存过的《{name}》里开的"
        elif not path:
            named = "在 ComfyUI「{name}」里开的"
    return named.replace("{name}", session.home_name)


def move_comfy_homes(db: Session, user: User, workspace_id: str, from_id: str, to_id: str) -> int:
    """ComfyUI 那张工作流第一次存盘、改名、挪文件夹(工作台的桥报来的,ADR 0044 §9):家跟着挪。只挪他自己的对话;同一台
    连接里挪。不按工作区筛 —— 同一台连接可以在几个工作区里用,文件换了地方,哪个工作区里家在它上面的都跟着挪。

    Mosael 自家的东西按 id 认,永远不用挪 —— 所以这里只收 ComfyUI。返回挪了几段。
    """
    source = checked(COMFYUI, from_id)
    target = checked(COMFYUI, to_id)
    if comfy_parts(source.id)[0] != comfy_parts(target.id)[0]:
        raise PlaceError("agentErr_placeMoveAcrossConnections")
    _comfy_ensure(db, user, workspace_id, target.id)
    return _move_homes(db, user.id, AgentSession.home_id == source.id, target.id)


def follow_library_move(
    db: Session, connection: PluginInstance, old_path: str, new_path: str, *, folder: bool = False
) -> int:
    """在 Mosael 工作流库(ADR 0035)里改名、挪、移进 / 移出回收目录:家在那个文件上的对话跟着挪,和改文件同一个事务
    (ADR 0044 §9)。`folder`:挪的是一个文件夹,家在它里面(任意深)的每一张都换上新的前缀。路径照工作流库的写法
    (`workflows/` 下的相对路径,和桥报的 `path` 同一种),按原样比 —— 大小写不同是另一个文件。

    连接归一个人,家能建在它上面的只有他(`_comfy_ensure`)—— 按连接的主人筛。返回挪了几段。
    """
    old, new = f"{connection.id}/{old_path}", f"{connection.id}/{new_path}"
    if old == new:
        return 0
    if not folder:
        return _move_homes(db, connection.owner_user_id, AgentSession.home_id == old, new)
    old_prefix, new_prefix = f"{old}/", f"{new}/"
    # 前缀按原样比(substr,不用 LIKE:SQLite 的 LIKE 不分大小写,还得转义 % 和 _)
    inside = func.substr(AgentSession.home_id, 1, len(old_prefix)) == old_prefix
    renamed = literal(new_prefix) + func.substr(AgentSession.home_id, len(old_prefix) + 1)
    return _move_homes(db, connection.owner_user_id, inside, renamed)


def _move_homes(db: Session, owner_user_id: str, which: ColumnElement[bool], home_id: Any) -> int:
    moved = db.execute(
        update(AgentSession)
        .where(AgentSession.owner_user_id == owner_user_id, AgentSession.home_kind == COMFYUI, which)
        # 挪家不算对话里有动静:不碰 updated_at(列表按它排,改个文件名不该把这几段顶到最前)。
        .values(home_id=home_id, updated_at=AgentSession.updated_at)
        .execution_options(synchronize_session=False)
    )
    return int(moved.rowcount or 0)

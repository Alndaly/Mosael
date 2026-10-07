"""一个工作区有哪些技能、各自开没开、文件在哪(ADR 0040 §2–§3)。

三个来源,一份清单:

- **内置**:仓库里的 `domain/agent/builtin_skills/<名字>/`,随应用发,只读;没有索引行就是开着的。
- **工作区**:`<数据目录>/skills/<工作区 id>/<名字>/`,成员新建、导入、从对话存成的,也包括有人直接扔进那个文件夹的
  (那种没有索引行,默认关着,看过全文才开)。
- **插件**:装好的插件包里的 `skills/<名字>/`,只读,跟着插件装卸;每个工作区自己开,默认关 —— 随 Mosael 一起发的插件
  (`plugins/bundled`)带的默认开,和内置的一样(见 default_enabled)。

模型看到的名字(`ref`):内置和工作区的就是 `name`;插件的带上插件 id —— `dev.mosael.comfyui:workflow-tips`。内置的名字是
保留的,工作区里起不了同名的;插件的带前缀,撞不上。**没有「同名谁盖谁」**:那会让一个插件悄悄换掉内置的做法。

内容只在文件里,这里每次照文件读(按修改时间缓存解析结果)。读不了的技能照样列出来,带着原因 —— 设置页要能告诉人
「这个文件夹里的 SKILL.md 第 3 行写错了」,而不是让它凭空消失。
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import LocalizedError
from app.db.models import AgentSkill, PluginPackage
from mosael_formats.agent_skill import (
    MAX_FILE_BYTES,
    MAX_PATH_DEPTH,
    MAX_SKILL_FILES,
    NAME_RE,
    SKILL_FILENAME,
    SkillDoc,
    SkillError,
    check_path,
    is_junk,
    is_text,
    parse_skill_md,
)

BUILTIN = "builtin"
WORKSPACE = "workspace"
PLUGIN = "plugin"
#: 列出来的顺序:内置、工作区、插件(系统提示里的目录也按它排,同样的技能每轮是同一段字)。
SOURCE_ORDER = {BUILTIN: 0, WORKSPACE: 1, PLUGIN: 2}

#: 工作区技能的来历(索引行上的 `origin`)。没有索引行的工作区技能是「扔进文件夹的」:FOLDER。
#: AGENT:智能体在对话里起草(新建、复制成我的)、人在确认卡上批的(ADR 0043)。
CREATED, IMPORTED, CONVERSATION, COPIED, FOLDER = "created", "imported", "conversation", "copied", "folder"
AGENT = "agent"

#: 看起来像脚本的文件:读的时候标明「Mosael 不执行它」(ADR 0040 §6)。
SCRIPT_SUFFIXES = frozenset({".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".bat", ".cmd"})

BUILTIN_ROOT = Path(__file__).resolve().parent.parent / "builtin_skills"
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SkillDomainError(LocalizedError):
    """技能这一块的错误,带 HTTP 状态(由 main 的异常处理翻)。"""

    def __init__(self, key: str, status: int = 422, **params: object) -> None:
        super().__init__(key, **params)
        self.status = status


@dataclass(frozen=True)
class Skill:
    source: str
    #: 文件夹名。合格的技能里它就是 SKILL.md 的 `name`。
    name: str
    root: Path
    package_id: str = ""
    package_name: str = ""
    doc: SkillDoc | None = None
    #: 读不了 / 不能用的原因(给人看);空串 = 好的。
    problem: str = ""
    enabled: bool = False
    origin: str = ""
    imported_from: str = ""
    #: 智能体在哪次对话里建的(新建、复制、导入经确认卡落地的);别的是空串。
    agent_session_id: str = ""

    @property
    def ref(self) -> str:
        return f"{self.package_id}:{self.name}" if self.source == PLUGIN else self.name

    @property
    def title(self) -> str:
        return (self.doc.title if self.doc else "") or self.name

    @property
    def description(self) -> str:
        return self.doc.description if self.doc else ""

    @property
    def editable(self) -> bool:
        return self.source == WORKSPACE

    @property
    def usable(self) -> bool:
        return self.doc is not None and not self.problem

    @property
    def active(self) -> bool:
        """会出现在系统提示的目录里、模型能 use_skill 的那些。"""
        return self.enabled and self.usable


def skills_dir() -> Path:
    return settings.data_dir / "skills"


def workspace_dir(workspace_id: str) -> Path:
    """`<数据目录>/skills/<工作区 id>`。id 过白名单 —— 它要拼进路径。"""
    if not _WORKSPACE_ID.match(str(workspace_id or "")):
        raise SkillDomainError("skillErr_badWorkspace", status=404)
    return skills_dir() / workspace_id


def default_enabled(source: str, *, shipped: bool = False) -> bool:
    """没有索引行时开不开:内置的开着;**随 Mosael 一起发的插件**(`plugins/bundled`,和后端、前端一起签名发版,见
    domain/plugins/bundled)带的也开着 —— 它和内置技能一样是这一版应用的一部分,工作台的「助手」一打开就该照它做
    (ADR 0042 §8)。扔进文件夹的、市场里装的插件带的,都要人看过全文再开。"""
    return source == BUILTIN or (source == PLUGIN and shipped)


def plugin_roots(db: Session) -> list[tuple[str, str, Path]]:
    """装着的插件包里的 `skills/` 目录:[(包 id, 显示名, 目录)]。"""
    from app.domain.plugins.manifest import PATH_KEY
    from mosael_formats.plugin_manifest import text_of

    out = []
    for package in db.scalars(select(PluginPackage).order_by(PluginPackage.id)):
        raw = dict(package.manifest or {})
        path = str(raw.get(PATH_KEY) or "")
        if not path:
            continue
        root = Path(path) / "skills"
        if root.is_dir() and not root.is_symlink():
            out.append((package.id, text_of(raw.get("name"), author_locale=str(raw.get("default_locale") or "")) or package.name, root))
    return out


def _folders(root: Path) -> list[tuple[str, Path]]:
    """`root` 下每个装着 SKILL.md 的子文件夹。名字不像技能名的(`.staging`、`My Skill`)跳过 —— 它们不是技能,
    要么是 Mosael 自己的暂存,要么根本没法被模型点名。符号链接一律不跟。"""
    if not root.is_dir() or root.is_symlink():
        return []
    out = []
    for child in sorted(root.iterdir(), key=lambda one: one.name):
        if child.is_symlink() or not child.is_dir() or not NAME_RE.match(child.name):
            continue
        marker = child / SKILL_FILENAME
        if marker.is_file() and not marker.is_symlink():
            out.append((child.name, child))
    return out


def _parse(path: Path, folder: str) -> tuple[SkillDoc | None, str]:
    """读一份 SKILL.md:好的回 (文档, ""),读不了回 (None, 原因)。原因**此刻**才按读的人的语言说 ——
    缓存里存的是错误本身(key + 参数),不是第一次读到时那种语言的一句话。"""
    try:
        stat = path.stat()
    except OSError:
        return None, str(SkillDomainError("skillErr_unreadable"))
    doc, error = _parse_cached(str(path), folder, stat.st_mtime_ns, stat.st_size)
    return doc, str(error) if error is not None else ""


@lru_cache(maxsize=512)
def _parse_cached(path: str, folder: str, _mtime: int, _size: int) -> tuple[SkillDoc | None, Exception | None]:
    """按 (路径, 修改时间, 大小) 缓存:系统提示每轮都要列一遍,而文件很少变。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, SkillDomainError("skillErr_unreadable")
    try:
        return parse_skill_md(text, folder=folder), None
    except SkillError as exc:
        return None, exc


def list_skills(db: Session, workspace_id: str) -> list[Skill]:
    """这个工作区看得到的全部技能,按来源、插件、名字排好。"""
    rows = {
        (row.source, row.package_id, row.name): row
        for row in db.scalars(select(AgentSkill).where(AgentSkill.workspace_id == workspace_id))
    }
    builtin_names = {name for name, _ in _folders(BUILTIN_ROOT)}
    from app.domain.plugins import bundled  # 用到才引:插件域不该在技能目录载入时就整个拉进来

    shipped = {one.id for one in bundled.plugins()}

    def make(source: str, name: str, root: Path, package_id: str = "", package_name: str = "") -> Skill:
        row = rows.get((source, package_id, name))
        doc, problem = _parse(root / SKILL_FILENAME, name)
        if source == WORKSPACE and name in builtin_names:
            problem = problem or str(SkillDomainError("skillErr_reservedName", name=name))
        return Skill(
            source=source,
            name=name,
            root=root,
            package_id=package_id,
            package_name=package_name,
            doc=doc,
            problem=problem,
            enabled=row.enabled if row is not None else default_enabled(source, shipped=package_id in shipped),
            origin=row.origin if row is not None else (FOLDER if source == WORKSPACE else source),
            imported_from=row.imported_from if row is not None else "",
            agent_session_id=(row.agent_session_id or "") if row is not None else "",
        )

    out = [make(BUILTIN, name, root) for name, root in _folders(BUILTIN_ROOT)]
    out += [make(WORKSPACE, name, root) for name, root in _folders(workspace_dir(workspace_id))]
    for package_id, package_name, base in plugin_roots(db):
        out += [make(PLUGIN, name, root, package_id, package_name) for name, root in _folders(base)]
    return sorted(out, key=lambda one: (SOURCE_ORDER[one.source], one.package_id, one.name))


def stale_rows(db: Session, workspace_id: str, skills: list[Skill]) -> list[AgentSkill]:
    """索引里有、文件夹已经没了的行(技能被删掉、插件被卸掉)。由技能域在列出设置页时清掉。"""
    present = {(one.source, one.package_id, one.name) for one in skills}
    return [
        row
        for row in db.scalars(select(AgentSkill).where(AgentSkill.workspace_id == workspace_id))
        if (row.source, row.package_id, row.name) not in present
    ]


def active_skills(db: Session, workspace_id: str) -> list[Skill]:
    return [one for one in list_skills(db, workspace_id) if one.active]


def find(db: Session, workspace_id: str, ref: str) -> Skill | None:
    """按模型看到的名字找。插件的写成 `包 id:名字`。"""
    ref = str(ref or "").strip()
    for one in list_skills(db, workspace_id):
        if one.ref == ref:
            return one
    return None


def source_label(skill: Skill) -> str:
    """来源,说给模型和人听的那一句(ADR 0040 §6:处处标来源)。"""
    from app.core.i18n import tr

    if skill.source == BUILTIN:
        return tr("skillSource_builtin")
    if skill.source == PLUGIN:
        return tr("skillSource_plugin", name=skill.package_name or skill.package_id)
    if skill.origin == IMPORTED:
        return tr("skillSource_imported", name=skill.imported_from or "?")
    return tr(f"skillSource_{skill.origin}") if skill.origin in (CREATED, CONVERSATION, COPIED, FOLDER, AGENT) else tr("skillSource_created")


# ---------------------------------------------------------------- 文件


@dataclass(frozen=True)
class SkillFile:
    path: str
    size: int
    script: bool


def files_of(skill: Skill) -> list[SkillFile]:
    """技能文件夹里的文件(相对路径,posix 写法),SKILL.md 排第一。符号链接不跟、不列;系统垃圾不列。"""
    out: list[SkillFile] = []

    def walk(folder: Path, prefix: str, depth: int) -> None:
        if depth > MAX_PATH_DEPTH or len(out) > MAX_SKILL_FILES:
            return
        for child in sorted(folder.iterdir(), key=lambda one: one.name):
            if child.is_symlink():
                continue
            relative = f"{prefix}{child.name}"
            if child.is_dir():
                walk(child, f"{relative}/", depth + 1)
            elif child.is_file() and not is_junk(relative):
                out.append(SkillFile(relative, child.stat().st_size, Path(relative).suffix.lower() in SCRIPT_SUFFIXES))

    if skill.root.is_dir():
        walk(skill.root, "", 1)
    return sorted(out, key=lambda one: (one.path != SKILL_FILENAME, one.path))


def resolve_file(skill: Skill, path: str) -> Path:
    """技能里一个文件的真实位置。路径先过规整(没有 `..`、绝对路径、反斜杠),再逐段确认不是符号链接,
    最后按真实路径核一次:必须在这个技能的文件夹里面(ADR 0040 §6)。"""
    try:
        relative = check_path(path)
    except SkillError as exc:
        raise SkillDomainError.relay(exc) from exc
    root = skill.root.resolve()
    current = skill.root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise SkillDomainError("skillErr_badPath", path=relative)
    target = current.resolve()
    if root not in target.parents:
        raise SkillDomainError("skillErr_badPath", path=relative)
    if not target.is_file():
        raise SkillDomainError("skillErr_fileMissing", status=404, path=relative)
    return target


#: read_skill_file 一次最多给多少字。和 read_note 一个量级:够读完一份参考,又不至于一口吃掉上下文。
READ_CHUNK_CHARS = 20000


def read_file(skill: Skill, path: str, *, offset: int = 0, length: int = READ_CHUNK_CHARS) -> dict:
    """读技能里的一个文件。文本按字分段给(`next_offset` 不为空就接着读);二进制只说类型和大小。"""
    target = resolve_file(skill, path)
    relative = check_path(path)
    size = target.stat().st_size
    script = Path(relative).suffix.lower() in SCRIPT_SUFFIXES
    if size > MAX_FILE_BYTES:
        raise SkillDomainError("skillErr_fileTooLarge", path=relative, limit=MAX_FILE_BYTES // (1024 * 1024))
    data = target.read_bytes()
    if not is_text(data):
        return {"path": relative, "binary": True, "size": size, "type": mimetypes.guess_type(relative)[0] or "application/octet-stream"}
    text = data.decode("utf-8")
    start = max(0, int(offset or 0))
    count = max(1, min(int(length or READ_CHUNK_CHARS), READ_CHUNK_CHARS))
    end = start + count
    return {
        "path": relative,
        "content": text[start:end],
        "offset": start,
        "total_chars": len(text),
        "next_offset": end if end < len(text) else None,
        "script": script,
    }


__all__ = [
    "AGENT",
    "BUILTIN",
    "BUILTIN_ROOT",
    "PLUGIN",
    "READ_CHUNK_CHARS",
    "SOURCE_ORDER",
    "WORKSPACE",
    "Skill",
    "SkillDomainError",
    "SkillFile",
    "active_skills",
    "default_enabled",
    "files_of",
    "find",
    "list_skills",
    "plugin_roots",
    "read_file",
    "resolve_file",
    "skills_dir",
    "source_label",
    "stale_rows",
    "workspace_dir",
]

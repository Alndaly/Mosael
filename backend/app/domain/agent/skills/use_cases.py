"""技能各件事带权限检查的入口:路由和智能体工具调这里(ADR 0040 §3)。

权限和记忆一样:工作区成员都能看;编辑以上(`"ai"`)能新建、改、删、导入、开关。技能拿不到任何新权限 ——
它只是一段做法,写操作照旧走确认卡 —— 所以不需要比记忆更高的一档。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import User
from app.domain.agent.skills import catalog, runtime, store
from app.domain.agent.skills.catalog import CONVERSATION, CREATED, Skill, SkillDomainError
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from mosael_formats.agent_skill import SkillDoc, SkillError, bundles_from_files, read_skill_archive


def _skill(db: Session, workspace_id: str, ref: str) -> Skill:
    found = catalog.find(db, workspace_id, ref)
    if found is None:
        raise SkillDomainError("skillErr_notFound", status=404, name=str(ref)[:120])
    return found


def list_skills(db: Session, user: User, workspace_id: str) -> list[Skill]:
    """设置页的列表。顺手清掉文件夹已经没了的索引行。"""
    ensure_workspace_access(db, user, workspace_id)
    skills = catalog.list_skills(db, workspace_id)
    store.forget_stale(db, workspace_id, skills)
    return skills


def get_skill(db: Session, user: User, workspace_id: str, ref: str) -> Skill:
    ensure_workspace_access(db, user, workspace_id)
    return _skill(db, workspace_id, ref)


def read_file(db: Session, user: User, workspace_id: str, ref: str, path: str) -> tuple[Skill, bytes, str]:
    """一个文件的原始内容(设置页看、下载)。返回 (技能, 内容, 规整过的路径)。"""
    from mosael_formats.agent_skill import check_path

    ensure_workspace_access(db, user, workspace_id)
    skill = _skill(db, workspace_id, ref)
    target = catalog.resolve_file(skill, path)
    return skill, target.read_bytes(), check_path(path)


def create(db: Session, user: User, workspace_id: str, doc: SkillDoc, *, from_conversation: bool = False) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return store.create(db, workspace_id, doc, origin=CONVERSATION if from_conversation else CREATED, user_id=user.id)


def update(db: Session, user: User, workspace_id: str, ref: str, doc: SkillDoc) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return store.update(db, workspace_id, _skill(db, workspace_id, ref), doc, user_id=user.id)


def delete(db: Session, user: User, workspace_id: str, ref: str) -> None:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    store.delete(db, workspace_id, _skill(db, workspace_id, ref))


def set_enabled(db: Session, user: User, workspace_id: str, ref: str, enabled: bool) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    store.set_enabled(db, workspace_id, _skill(db, workspace_id, ref), enabled, user_id=user.id)
    return _skill(db, workspace_id, ref)


def put_file(db: Session, user: User, workspace_id: str, ref: str, path: str, data: bytes) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    skill = _skill(db, workspace_id, ref)
    store.put_file(skill, path, data)
    return skill


def delete_file(db: Session, user: User, workspace_id: str, ref: str, path: str) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    skill = _skill(db, workspace_id, ref)
    store.delete_file(skill, path)
    return skill


def copy(db: Session, user: User, workspace_id: str, ref: str, name: str) -> Skill:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return store.copy_to_workspace(db, workspace_id, _skill(db, workspace_id, ref), name, user_id=user.id)


def export(db: Session, user: User, workspace_id: str, refs: list[str]) -> bytes:
    ensure_workspace_access(db, user, workspace_id)
    return store.export_archive([_skill(db, workspace_id, ref) for ref in refs])


def stage_import(db: Session, user: User, workspace_id: str, *, archive: bytes | None = None,
                 files: dict[str, bytes] | None = None, source_name: str = "") -> dict:
    """读一个 `.zip`(或一个文件夹里的全部文件),放进暂存,回审阅要的全文。什么都还没装。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    try:
        bundles = read_skill_archive(archive) if archive is not None else bundles_from_files(files or {})
    except SkillError as exc:
        raise SkillDomainError.relay(exc) from exc
    import_id = store.stage_import(workspace_id, bundles, source_name)
    return store.preview_import(db, workspace_id, import_id)


def commit_import(db: Session, user: User, workspace_id: str, import_id: str, choices: list[dict]) -> list[Skill]:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return store.commit_import(db, workspace_id, import_id, choices, user_id=user.id)


# ---------------------------------------------------------------- 智能体工具


def use_skill(db: Session, user: User, workspace_id: str, ref: str) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return runtime.use_skill(db, workspace_id, ref)


def read_skill_file(db: Session, user: User, workspace_id: str, ref: str, path: str, offset: int = 0) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return runtime.read_skill_file(db, workspace_id, ref, path, offset)


__all__ = [
    "commit_import",
    "copy",
    "create",
    "delete",
    "delete_file",
    "export",
    "get_skill",
    "list_skills",
    "put_file",
    "read_file",
    "read_skill_file",
    "set_enabled",
    "stage_import",
    "update",
    "use_skill",
]

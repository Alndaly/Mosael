"""技能各件事带权限检查的入口:路由和智能体工具调这里(ADR 0040 §3)。

权限和记忆一样:工作区成员都能看;编辑以上(`"ai"`)能新建、改、删、导入、开关。技能拿不到任何新权限 ——
它只是一段做法,写操作照旧走确认卡 —— 所以不需要比记忆更高的一档。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AgentSession, User
from app.domain.agent.skills import catalog, drafting, managing, remote, runtime, store
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


def draft_from_session(db: Session, user: User, session_id: str) -> dict[str, str]:
    """「存成技能」:起草,不保存。看得见这次对话、又能在这个工作区里建技能,才值得花这一次模型调用。"""
    from app.domain.agent.sessions import readable_session

    session: AgentSession = readable_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    return drafting.draft_from_session(db, session, user_id=user.id)


# ---------------------------------------------------------------- 智能体工具


def use_skill(db: Session, user: User, workspace_id: str, ref: str) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return runtime.use_skill(db, workspace_id, ref)


def read_skill_file(db: Session, user: User, workspace_id: str, ref: str, path: str, offset: int = 0) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return runtime.read_skill_file(db, workspace_id, ref, path, offset)


# ---------------------------------------------------------------- 智能体自己管技能(ADR 0043)
#
# 看:成员都能看(和设置页一样)。写:编辑以上(`"ai"`),开卡时按开卡的人查一次、批准时按批的人再查一次 ——
# 写的那几件都经确认卡(confirmable/skills.py),这里是卡的两头:`review_*` 算卡上的事实,`apply_*` 批了之后落地。


def agent_listing(db: Session, user: User, workspace_id: str) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    return managing.listing(db, workspace_id)


def inspect(db: Session, user: User, workspace_id: str, ref: str) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return managing.inspect(db, workspace_id, ref)


def stage_from_url(db: Session, user: User, workspace_id: str, url: str) -> dict:
    """import_skill 的第一步:从链接取回来、读好、放进暂存,回审阅要的全文 —— 和设置页上传同一份暂存与审阅。什么都还没装。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    fetched = remote.fetch(url)
    try:
        bundles = read_skill_archive(fetched.archive) if fetched.archive is not None else bundles_from_files(fetched.files or {})
    except SkillError as exc:
        raise SkillDomainError.relay(exc) from exc
    import_id = store.stage_import(workspace_id, bundles, fetched.source_name)
    return store.preview_import(db, workspace_id, import_id)


def import_preview(db: Session, user: User, workspace_id: str, import_id: str) -> dict:
    """暂存着的一次导入的全文(智能体导入的确认卡照它画审阅)。"""
    ensure_workspace_access(db, user, workspace_id)
    return store.preview_import(db, workspace_id, import_id)


def review(db: Session, user: User, workspace_id: str, action: str, payload: dict) -> dict:
    """开卡之前:这个人能不能在这里改技能,和卡上要摆的事实(全文、对比、指纹)。`action` 是 managing 里的那一件。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return _REVIEWS[action](db, workspace_id, payload)


def apply(db: Session, user: User, workspace_id: str, action: str, payload: dict, *, session_id: str | None) -> dict:
    """批准之后:批的人能不能改技能,再照开卡时的 payload 落地。回写进卡里的结果。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    if action == "create":
        made = managing.apply_create(db, workspace_id, payload, user_id=user.id, session_id=session_id)
        return {"name": made.ref, "enabled": made.enabled}
    if action == "copy":
        made = managing.apply_copy(db, workspace_id, payload, user_id=user.id, session_id=session_id)
        return {"name": made.ref, "enabled": made.enabled}
    if action == "update":
        return {"name": managing.apply_update(db, workspace_id, payload).ref}
    if action == "enable":
        changed = managing.apply_enable(db, workspace_id, payload, user_id=user.id)
        return {"name": changed.ref, "enabled": changed.enabled}
    if action == "delete":
        return {"name": managing.apply_delete(db, workspace_id, payload), "deleted": True}
    if action == "import":
        made = managing.apply_import(db, workspace_id, payload, user_id=user.id, session_id=session_id)
        return {"imported": [{"name": one.ref, "enabled": one.enabled} for one in made]}
    raise ValueError(action)


_REVIEWS = {
    "create": managing.review_create,
    "copy": managing.review_copy,
    "update": managing.review_update,
    "enable": managing.review_enable,
    "delete": managing.review_delete,
    "import": managing.review_import,
}


__all__ = [
    "agent_listing",
    "apply",
    "commit_import",
    "copy",
    "create",
    "delete",
    "delete_file",
    "draft_from_session",
    "export",
    "get_skill",
    "import_preview",
    "inspect",
    "list_skills",
    "put_file",
    "read_file",
    "read_skill_file",
    "review",
    "set_enabled",
    "stage_from_url",
    "stage_import",
    "update",
    "use_skill",
]

"""工作区技能的写:新建、改、删、开关、文件、导入、导出、复制(ADR 0040 §3、§6、§7)。

**这是唯一建 `AgentSkill` 行的地方**(数据归属棘轮盯着)。内容只写文件:一个技能就是
`<数据目录>/skills/<工作区 id>/<名字>/`,拷走就是导出。

写文件夹先写在暂存目录里、写完整了再一次改名搬过去 —— 半截的技能不会出现在列表里,更不会进系统提示。
内置和插件的技能只读:想改就「复制成我的」。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid

logger = logging.getLogger(__name__)
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentSkill
from app.core.unit_of_work import after_commit
from app.domain.agent.skills import catalog
from app.domain.agent.skills.catalog import (
    BUILTIN,
    COPIED,
    IMPORTED,
    WORKSPACE,
    Skill,
    SkillDomainError,
)
from mosael_formats.agent_skill import (
    MAX_FILE_BYTES,
    MAX_SKILL_BYTES,
    MAX_SKILL_FILES,
    SKILL_FILENAME,
    SkillBundle,
    SkillDoc,
    SkillError,
    check_files,
    check_name,
    check_path,
    is_text,
    parse_skill_md,
    render_skill_md,
    validate,
    write_skill_archive,
)

#: 暂存目录:导入等人审阅的那几个技能、写到一半的文件夹。名字带点,catalog 不会把它当成技能。
STAGING = ".staging"
#: 导入暂存多久没人确认就清掉。
STAGING_TTL_SECONDS = 3600


def _relay(exc: SkillError) -> SkillDomainError:
    return SkillDomainError.relay(exc)


def _row(db: Session, workspace_id: str, skill: Skill) -> AgentSkill | None:
    return db.scalars(
        select(AgentSkill).where(
            AgentSkill.workspace_id == workspace_id,
            AgentSkill.source == skill.source,
            AgentSkill.package_id == skill.package_id,
            AgentSkill.name == skill.name,
        )
    ).first()


def _upsert_row(
    db: Session,
    workspace_id: str,
    *,
    source: str,
    name: str,
    package_id: str = "",
    enabled: bool,
    origin: str,
    imported_from: str = "",
    user_id: str | None = None,
    agent_session_id: str | None = None,
) -> AgentSkill:
    row = db.scalars(
        select(AgentSkill).where(
            AgentSkill.workspace_id == workspace_id,
            AgentSkill.source == source,
            AgentSkill.package_id == package_id,
            AgentSkill.name == name,
        )
    ).first()
    if row is None:
        row = AgentSkill(workspace_id=workspace_id, source=source, package_id=package_id, name=name, created_by=user_id)
        db.add(row)
    row.enabled = enabled
    row.origin = origin
    row.imported_from = imported_from[:255]
    row.agent_session_id = agent_session_id or None
    db.flush()
    return row


def set_enabled(db: Session, workspace_id: str, skill: Skill, enabled: bool, *, user_id: str | None) -> None:
    """开关。读不了的技能开不了 —— 开着一个模型 use_skill 时只会报错的东西没有意义。"""
    if enabled and not skill.usable:
        raise SkillDomainError("skillErr_broken", status=409, name=skill.ref, detail=skill.problem)
    row = _row(db, workspace_id, skill)
    if row is None:
        _upsert_row(db, workspace_id, source=skill.source, name=skill.name, package_id=skill.package_id,
                    enabled=enabled, origin=skill.origin, user_id=user_id)
    else:
        row.enabled = enabled
        db.flush()


def forget_stale(db: Session, workspace_id: str, skills: list[Skill]) -> None:
    """索引里有、文件夹已经没了的行(在 Mosael 外面删了文件夹、插件卸了):清掉。"""
    for row in catalog.stale_rows(db, workspace_id, skills):
        db.delete(row)
    db.flush()


# ---------------------------------------------------------------- 暂存与落地


def _staging_root() -> Path:
    root = catalog.skills_dir() / STAGING
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_staging() -> None:
    root = catalog.skills_dir() / STAGING
    if not root.is_dir():
        return
    cutoff = time.time() - STAGING_TTL_SECONDS
    for child in root.iterdir():
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
        except OSError as exc:
            #: 清不掉不能无声:暂存目录只涨不消,磁盘缓慢上涨没人知道。debug 级 —— 它在后台跑,
            #: 不是用户等着的事。
            logger.debug("技能暂存目录 %s 清不掉: %s", child, exc)
            continue


def _write_tree(folder: Path, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        target = folder / check_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _place(workspace_id: str, name: str, files: dict[str, bytes], *, replace_existing: bool = False) -> Path:
    """把一个技能的全部文件写进暂存、再改名搬到 `<工作区>/<名字>`。"""
    check_files({path: len(data) for path, data in files.items()})
    destination = catalog.workspace_dir(workspace_id) / name
    if destination.exists() and not replace_existing:
        raise SkillDomainError("skillErr_exists", status=409, name=name)
    scratch = _staging_root() / f"write-{uuid.uuid4().hex}"
    _write_tree(scratch, files)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        retired = _staging_root() / f"old-{uuid.uuid4().hex}"
        destination.rename(retired)
        shutil.rmtree(retired, ignore_errors=True)
    scratch.rename(destination)
    return destination


def _reserved(db: Session, workspace_id: str, name: str) -> None:
    check = {one.name for one in catalog.list_skills(db, workspace_id) if one.source == BUILTIN}
    if name in check:
        raise SkillDomainError("skillErr_reservedName", status=409, name=name)


def _check_doc(doc: SkillDoc) -> SkillDoc:
    try:
        validate(doc)
    except SkillError as exc:
        raise _relay(exc) from exc
    return doc


# ---------------------------------------------------------------- 新建、改、删


def create(
    db: Session,
    workspace_id: str,
    doc: SkillDoc,
    *,
    origin: str,
    user_id: str | None,
    enabled: bool = True,
    files: dict[str, bytes] | None = None,
    imported_from: str = "",
    replace_existing: bool = False,
    skill_md: bytes | None = None,
    agent_session_id: str | None = None,
) -> Skill:
    """新建一个工作区技能(新建、存成技能、导入、复制都走这里)。`files` 是 SKILL.md 以外的文件。
    `agent_session_id`:智能体在哪次对话里经确认卡建的(ADR 0043);人建的不给。

    `skill_md`:原样落地的那份 SKILL.md(导入且没改名时)。**一个字节都不动** —— 别处导出的技能导进来再导出去,
    拿回的是同一份文件;重新渲染会把作者的注释、引号、换行全换成 Mosael 的写法。它读出来必须就是 `doc`。
    """
    _check_doc(doc)
    _reserved(db, workspace_id, doc.name)
    payload = {path: data for path, data in (files or {}).items() if path != SKILL_FILENAME}
    if skill_md is not None and parse_skill_md(skill_md.decode("utf-8")) != doc:
        raise SkillDomainError("skillErr_unreadable")
    payload[SKILL_FILENAME] = skill_md if skill_md is not None else render_skill_md(doc).encode("utf-8")
    _place(workspace_id, doc.name, payload, replace_existing=replace_existing)
    _upsert_row(db, workspace_id, source=WORKSPACE, name=doc.name, enabled=enabled, origin=origin,
                imported_from=imported_from, user_id=user_id, agent_session_id=agent_session_id)
    found = catalog.find(db, workspace_id, doc.name)
    assert found is not None
    return found


def _editable(skill: Skill) -> None:
    if not skill.editable:
        raise SkillDomainError("skillErr_readOnly", status=409, name=skill.ref)


def update(db: Session, workspace_id: str, skill: Skill, fields: SkillDoc, *, user_id: str | None) -> Skill:
    """改一个工作区技能的头和正文。`fields` 里的规范字段和正文用新的;不认识的字段、`allowed-tools`
    照旧(它们不在表单上,原样写回)。改了名字就连文件夹一起改名,开关和来历跟着走。"""
    _editable(skill)
    base = skill.doc or SkillDoc(name=skill.name, description="")
    doc = _check_doc(replace(fields, allowed_tools=base.allowed_tools, allowed_tools_raw=base.allowed_tools_raw, extra=base.extra))
    if doc.name != skill.name:
        _reserved(db, workspace_id, doc.name)
        destination = catalog.workspace_dir(workspace_id) / doc.name
        if destination.exists():
            raise SkillDomainError("skillErr_exists", status=409, name=doc.name)
        skill.root.rename(destination)
        row = _row(db, workspace_id, skill)
        if row is not None:
            row.name = doc.name
            db.flush()
        root = destination
    else:
        root = skill.root
    (root / SKILL_FILENAME).write_text(render_skill_md(doc), encoding="utf-8")
    found = catalog.find(db, workspace_id, doc.name)
    assert found is not None
    return found


def rewrite(db: Session, workspace_id: str, skill: Skill, files: dict[str, bytes]) -> Skill:
    """整份换掉一个工作区技能的内容(智能体改技能,ADR 0043):`files` 是改之后的**全部**文件(含 SKILL.md)。

    和新建一样先在暂存里写完整、再一次换过去 —— 改到一半的技能不会出现在列表里、更不会进系统提示。名字不变,
    开关和来历(索引行)不动。SKILL.md 必须读得出、名字还是它自己。
    """
    _editable(skill)
    try:
        doc = parse_skill_md(files[SKILL_FILENAME].decode("utf-8"))
    except (KeyError, UnicodeDecodeError) as exc:
        raise SkillDomainError("skillErr_unreadable") from exc
    except SkillError as exc:
        raise _relay(exc) from exc
    if doc.name != skill.name:
        raise SkillDomainError("skillErr_folderMismatch", folder=skill.name, name=doc.name)
    _place(workspace_id, skill.name, files, replace_existing=True)
    found = catalog.find(db, workspace_id, skill.name)
    assert found is not None
    return found


def delete(db: Session, workspace_id: str, skill: Skill) -> None:
    """删一个工作区技能:行当场删,文件夹在事务提交之后删(回滚了的话技能还在,文件不能先没了)。"""
    _editable(skill)
    row = _row(db, workspace_id, skill)
    if row is not None:
        db.delete(row)
        db.flush()
    root = skill.root
    after_commit(db, lambda: shutil.rmtree(root, ignore_errors=True))


def delete_workspace_files(workspace_id: str) -> None:
    """工作区删掉之后,它的技能文件夹一起删(行由外键带走)。"""
    shutil.rmtree(catalog.workspace_dir(workspace_id), ignore_errors=True)


def put_file(skill: Skill, path: str, data: bytes) -> None:
    """加 / 换技能里的一个文件(SKILL.md 走 update)。上限照 §6:单个文件、整个技能、文件个数。"""
    _editable(skill)
    try:
        relative = check_path(path)
    except SkillError as exc:
        raise _relay(exc) from exc
    if relative == SKILL_FILENAME:
        raise SkillDomainError("skillErr_skillMdViaForm")
    if len(data) > MAX_FILE_BYTES:
        raise SkillDomainError("skillErr_fileTooLarge", path=relative, limit=MAX_FILE_BYTES // (1024 * 1024))
    existing = {one.path: one.size for one in catalog.files_of(skill)}
    existing[relative] = len(data)
    if len(existing) > MAX_SKILL_FILES:
        raise SkillDomainError("skillErr_tooManyFiles", limit=MAX_SKILL_FILES)
    if sum(existing.values()) > MAX_SKILL_BYTES:
        raise SkillDomainError("skillErr_skillTooLarge", limit=MAX_SKILL_BYTES // (1024 * 1024))
    current = skill.root
    for part in relative.split("/")[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise SkillDomainError("skillErr_badPath", path=relative)
    target = skill.root / relative
    if target.is_symlink() or target.is_dir():
        raise SkillDomainError("skillErr_badPath", path=relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def delete_file(skill: Skill, path: str) -> None:
    _editable(skill)
    target = catalog.resolve_file(skill, path)
    if check_path(path) == SKILL_FILENAME:
        raise SkillDomainError("skillErr_skillMdViaForm")
    target.unlink()
    root = skill.root.resolve()
    parent = target.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def read_all(skill: Skill) -> dict[str, bytes]:
    """一个技能的全部文件(导出、复制用)。"""
    return {one.path: catalog.resolve_file(skill, one.path).read_bytes() for one in catalog.files_of(skill)}


def copy_to_workspace(db: Session, workspace_id: str, skill: Skill, name: str, *, user_id: str | None) -> Skill:
    """内置 / 插件(或别的工作区技能)复制一份成「我的」,换个名字,就能改了。默认开着,原来那个不动。"""
    if skill.doc is None:
        raise SkillDomainError("skillErr_broken", status=409, name=skill.ref, detail=skill.problem)
    try:
        check_name(name)
    except SkillError as exc:
        raise _relay(exc) from exc
    files = read_all(skill)
    return create(db, workspace_id, replace(skill.doc, name=name), origin=COPIED, user_id=user_id, files=files,
                  imported_from=skill.ref)


def export_archive(skills: list[Skill]) -> bytes:
    """几个技能 → 一个 `.zip`,每个技能一层同名文件夹(别家导入认的就是这个形状)。"""
    return write_skill_archive([(one.name, read_all(one)) for one in skills])


# ---------------------------------------------------------------- 导入:先暂存、给人看全文,再落地


def stage_import(workspace_id: str, bundles: list[SkillBundle], source_name: str) -> str:
    """把读好的几个技能放进暂存,等人审阅。返回暂存 id。"""
    _clean_staging()
    import_id = uuid.uuid4().hex
    folder = _staging_root() / f"import-{import_id}"
    for bundle in bundles:
        _write_tree(folder / "skills" / bundle.doc.name, bundle.files)
    (folder / "import.json").write_text(
        json.dumps(
            {
                "workspace_id": workspace_id,
                "source_name": source_name[:255],
                "skills": [{"name": one.doc.name, "folder": one.folder} for one in bundles],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return import_id


def _staged(workspace_id: str, import_id: str) -> tuple[Path, dict]:
    if not import_id.isalnum() or len(import_id) != 32:
        raise SkillDomainError("skillErr_importGone", status=404)
    folder = catalog.skills_dir() / STAGING / f"import-{import_id}"
    try:
        info = json.loads((folder / "import.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillDomainError("skillErr_importGone", status=404) from exc
    if info.get("workspace_id") != workspace_id:
        raise SkillDomainError("skillErr_importGone", status=404)
    return folder, info


def _staged_files(folder: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not path.is_symlink():
            out[path.relative_to(folder).as_posix()] = path.read_bytes()
    return out


def preview_import(db: Session, workspace_id: str, import_id: str) -> dict:
    """暂存的导入,**全文**给人看(ADR 0040 §6):每个文本文件的全部内容、二进制文件的大小、不认的字段、脚本、和已有技能撞没撞名。"""
    folder, info = _staged(workspace_id, import_id)
    existing = {one.name: one for one in catalog.list_skills(db, workspace_id) if one.source in (BUILTIN, WORKSPACE)}
    skills = []
    for entry in info.get("skills", []):
        name = str(entry.get("name") or "")
        files = _staged_files(folder / "skills" / name)
        doc = parse_skill_md(files[SKILL_FILENAME].decode("utf-8"))
        clash = existing.get(name)
        skills.append(
            {
                "name": name,
                "title": doc.title,
                "description": doc.description,
                "license": doc.license,
                "compatibility": doc.compatibility,
                "allowed_tools": doc.allowed_tools,
                "unknown_fields": sorted(doc.extra),
                "folder": str(entry.get("folder") or ""),
                "conflict": "" if clash is None else ("builtin" if clash.source == BUILTIN else "workspace"),
                "files": [
                    {
                        "path": path,
                        "size": len(data),
                        "script": Path(path).suffix.lower() in catalog.SCRIPT_SUFFIXES,
                        **({"text": data.decode("utf-8")} if is_text(data) else {"binary": True}),
                    }
                    for path, data in sorted(files.items(), key=lambda item: (item[0] != SKILL_FILENAME, item[0]))
                ],
            }
        )
    return {"import_id": import_id, "source_name": info.get("source_name", ""), "skills": skills}


def commit_import(
    db: Session,
    workspace_id: str,
    import_id: str,
    choices: list[dict],
    *,
    user_id: str | None,
    agent_session_id: str | None = None,
) -> list[Skill]:
    """照审阅时的选择落地:每个技能要不要、改不改名、开不开、撞名时替不替换。没提到的技能不装。
    `agent_session_id`:智能体经确认卡导入的,记下是哪次对话(ADR 0043)。"""
    folder, info = _staged(workspace_id, import_id)
    staged = {str(entry.get("name") or "") for entry in info.get("skills", [])}
    source_name = str(info.get("source_name") or "")
    out: list[Skill] = []
    for choice in choices:
        name = str(choice.get("name") or "")
        if name not in staged:
            raise SkillDomainError("skillErr_importGone", status=404)
        files = _staged_files(folder / "skills" / name)
        original = files[SKILL_FILENAME]
        doc = parse_skill_md(original.decode("utf-8"))
        target = str(choice.get("rename_to") or "").strip() or name
        if target != name:
            try:
                check_name(target)
            except SkillError as exc:
                raise _relay(exc) from exc
            doc = replace(doc, name=target)
        existing = catalog.find(db, workspace_id, target)
        replacing = bool(choice.get("replace")) and existing is not None and existing.source == WORKSPACE
        out.append(
            create(
                db,
                workspace_id,
                doc,
                origin=IMPORTED,
                user_id=user_id,
                enabled=bool(choice.get("enable")),
                files=files,
                imported_from=source_name,
                replace_existing=replacing,
                #: 没改名就原样落地;改了名,头里的 name 得跟着改,只能重新写一份。
                skill_md=original if target == name else None,
                agent_session_id=agent_session_id,
            )
        )
    after_commit(db, lambda: shutil.rmtree(folder, ignore_errors=True))
    return out


__all__ = [
    "STAGING",
    "commit_import",
    "copy_to_workspace",
    "create",
    "delete",
    "delete_file",
    "delete_workspace_files",
    "export_archive",
    "forget_stale",
    "preview_import",
    "put_file",
    "read_all",
    "rewrite",
    "set_enabled",
    "stage_import",
    "update",
]

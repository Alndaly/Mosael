"""智能体技能:设置 → 智能体 → 技能,以及对话里的「/」菜单和「存成技能」(ADR 0040)。

技能是工作区的;`{ref}` 是模型看到的名字(插件的技能写成 `插件 id:名字`)。看:工作区成员;改:编辑以上。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.skills import (
    AgentSkillCopy,
    AgentSkillDetailOut,
    AgentSkillDraftOut,
    AgentSkillEnable,
    AgentSkillImportCommit,
    AgentSkillImportOut,
    AgentSkillOut,
    AgentSkillWrite,
)
from app.domain.agent.skills import catalog, managing, use_cases
from app.domain.agent.skills.catalog import Skill, SkillDomainError
from mosael_formats.agent_skill import (
    MAX_ARCHIVE_UNPACKED_BYTES,
    MAX_SKILL_FILES,
    MAX_SKILLS_PER_IMPORT,
    TITLE_KEY,
    SkillDoc,
    is_text,
)

router = APIRouter(tags=["agent-skills"])

#: 一次导入最多收多大的上传(压缩包或一堆文件)。解开后的上限另算(格式包里),这里挡的是传上来的字节。
MAX_IMPORT_UPLOAD_BYTES = MAX_ARCHIVE_UNPACKED_BYTES


def _out(skill: Skill) -> dict:
    return {
        "ref": skill.ref,
        "name": skill.name,
        "title": skill.title,
        "description": skill.description,
        "source": skill.source,
        "source_label": catalog.source_label(skill),
        "origin": skill.origin,
        "agent_session_id": skill.agent_session_id or None,
        "enabled": skill.enabled,
        "editable": skill.editable,
        "problem": skill.problem,
    }


def _detail(skill: Skill) -> dict:
    doc = skill.doc
    files = []
    for one in catalog.files_of(skill):
        data = catalog.resolve_file(skill, one.path).read_bytes()
        text = is_text(data)
        files.append({"path": one.path, "size": one.size, "script": one.script,
                      "text": data.decode("utf-8") if text else None, "binary": not text})
    return {
        **_out(skill),
        "license": doc.license if doc else "",
        "compatibility": doc.compatibility if doc else "",
        "allowed_tools": doc.allowed_tools if doc else "",
        "unknown_fields": sorted(doc.extra) if doc else [],
        "metadata": {key: value for key, value in (doc.metadata if doc else {}).items() if key != TITLE_KEY},
        "body": doc.body if doc else "",
        "files": files,
    }


def _doc(body: AgentSkillWrite, base: SkillDoc | None = None) -> SkillDoc:
    """表单 → SkillDoc(和智能体的工具同一处规整,见 managing.compose_doc)。改的时候 metadata 里显示名以外的键原样留着。"""
    return managing.compose_doc(name=body.name, title=body.title, description=body.description, body=body.body,
                                license=body.license, compatibility=body.compatibility, base=base)


@router.get("/workspaces/{workspace_id}/skills", response_model=list[AgentSkillOut])
def list_skills(workspace_id: str, db: Tx, user: CurrentUser) -> list[dict]:
    """这个工作区看得到的全部技能:内置、我的、来自插件。「/」菜单只摆其中开着、能用的。"""
    return [_out(one) for one in use_cases.list_skills(db, user, workspace_id)]


@router.get("/workspaces/{workspace_id}/skills/{ref}", response_model=AgentSkillDetailOut)
def get_skill(workspace_id: str, ref: str, db: DbSession, user: CurrentUser) -> dict:
    """一个技能的全部内容(文本文件给全文):编辑表单和「看过全文再开」都用它。"""
    return _detail(use_cases.get_skill(db, user, workspace_id, ref))


@router.post("/workspaces/{workspace_id}/skills", response_model=AgentSkillDetailOut, status_code=201)
def create_skill(workspace_id: str, body: AgentSkillWrite, db: Tx, user: CurrentUser) -> dict:
    return _detail(use_cases.create(db, user, workspace_id, _doc(body), from_conversation=body.from_conversation))


@router.put("/workspaces/{workspace_id}/skills/{ref}", response_model=AgentSkillDetailOut)
def update_skill(workspace_id: str, ref: str, body: AgentSkillWrite, db: Tx, user: CurrentUser) -> dict:
    current = use_cases.get_skill(db, user, workspace_id, ref)
    return _detail(use_cases.update(db, user, workspace_id, ref, _doc(body, current.doc)))


@router.delete("/workspaces/{workspace_id}/skills/{ref}", status_code=204)
def delete_skill(workspace_id: str, ref: str, db: Tx, user: CurrentUser) -> Response:
    use_cases.delete(db, user, workspace_id, ref)
    return Response(status_code=204)


@router.put("/workspaces/{workspace_id}/skills/{ref}/enabled", response_model=AgentSkillOut)
def set_skill_enabled(workspace_id: str, ref: str, body: AgentSkillEnable, db: Tx, user: CurrentUser) -> dict:
    return _out(use_cases.set_enabled(db, user, workspace_id, ref, body.enabled))


@router.post("/workspaces/{workspace_id}/skills/{ref}/copy", response_model=AgentSkillDetailOut, status_code=201)
def copy_skill(workspace_id: str, ref: str, body: AgentSkillCopy, db: Tx, user: CurrentUser) -> dict:
    """内置 / 插件的技能复制一份成「我的」,换个名字就能改。"""
    return _detail(use_cases.copy(db, user, workspace_id, ref, body.name.strip()))


@router.get("/workspaces/{workspace_id}/skills/{ref}/export")
def export_skill(workspace_id: str, ref: str, db: DbSession, user: CurrentUser) -> Response:
    """导出成 `.zip`:一层同名文件夹,里面就是技能文件夹原样 —— 别家导入认的就是这个形状。"""
    data = use_cases.export(db, user, workspace_id, [ref])
    filename = ref.replace(":", "-")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}.zip"'},
    )


@router.get("/workspaces/{workspace_id}/skills/{ref}/files/{path:path}")
def read_skill_file(workspace_id: str, ref: str, path: str, db: DbSession, user: CurrentUser) -> Response:
    """技能里一个文件的原始字节(下载)。路径越界、符号链接一律 400。"""
    _skill, data, relative = use_cases.read_file(db, user, workspace_id, ref, path)
    name = relative.rsplit("/", 1)[-1]
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/workspaces/{workspace_id}/skills/{ref}/files/{path:path}", response_model=AgentSkillDetailOut)
def put_skill_file(workspace_id: str, ref: str, path: str, db: Tx, user: CurrentUser,
                   file: UploadFile = File(...)) -> dict:
    """加 / 换技能里的一个文件(SKILL.md 走表单)。同步端点:要写库,不能在事件循环上做。"""
    data = file.file.read()
    return _detail(use_cases.put_file(db, user, workspace_id, ref, path, data))


@router.delete("/workspaces/{workspace_id}/skills/{ref}/files/{path:path}", response_model=AgentSkillDetailOut)
def delete_skill_file(workspace_id: str, ref: str, path: str, db: Tx, user: CurrentUser) -> dict:
    return _detail(use_cases.delete_file(db, user, workspace_id, ref, path))


@router.post("/workspaces/{workspace_id}/skill-imports", response_model=AgentSkillImportOut)
def stage_skill_import(
    workspace_id: str,
    db: Tx,
    user: CurrentUser,
    archive: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
    paths: list[str] = Form(default=[]),
    source_name: str = Form(default=""),
) -> dict:
    """导入第一步:收一个 `.zip`(`archive`),或者一个文件夹里的全部文件(`files` 与同序的相对路径 `paths`)。
    读好、放进暂存,回**全文**给人审阅 —— 什么都还没装(ADR 0040 §6)。同步端点:解包、写库都不该在事件循环上做。"""
    if archive is not None:
        data = archive.file.read(MAX_IMPORT_UPLOAD_BYTES + 1)
        if len(data) > MAX_IMPORT_UPLOAD_BYTES:
            raise SkillDomainError("skillErr_archiveTooLarge", limit=MAX_IMPORT_UPLOAD_BYTES // (1024 * 1024))
        return use_cases.stage_import(db, user, workspace_id, archive=data,
                                      source_name=source_name or archive.filename or "skill.zip")
    if not files or len(files) != len(paths):
        raise SkillDomainError("skillErr_noSkillMd")
    if len(files) > MAX_SKILL_FILES * MAX_SKILLS_PER_IMPORT:
        raise SkillDomainError("skillErr_tooManyFiles", limit=MAX_SKILL_FILES)
    collected: dict[str, bytes] = {}
    total = 0
    for upload, relative in zip(files, paths, strict=True):
        data = upload.file.read(MAX_IMPORT_UPLOAD_BYTES + 1)
        total += len(data)
        if total > MAX_IMPORT_UPLOAD_BYTES:
            raise SkillDomainError("skillErr_archiveTooLarge", limit=MAX_IMPORT_UPLOAD_BYTES // (1024 * 1024))
        collected[relative] = data
    folder = source_name or (paths[0].split("/", 1)[0] if paths else "")
    return use_cases.stage_import(db, user, workspace_id, files=collected, source_name=folder)


@router.get("/workspaces/{workspace_id}/skill-imports/{import_id}", response_model=AgentSkillImportOut)
def get_skill_import(workspace_id: str, import_id: str, db: DbSession, user: CurrentUser) -> dict:
    """暂存着的一次导入的全文。智能体导入(import_skill)的确认卡照它画审阅 —— 和设置页导入同一份暂存、同一个审阅。"""
    return use_cases.import_preview(db, user, workspace_id, import_id)


@router.post("/workspaces/{workspace_id}/skill-imports/{import_id}", response_model=list[AgentSkillOut])
def commit_skill_import(workspace_id: str, import_id: str, body: AgentSkillImportCommit, db: Tx,
                        user: CurrentUser) -> list[dict]:
    """导入第二步:照审阅时的选择落地(装哪几个、改不改名、开不开、撞名时替不替换)。"""
    choices = [choice.model_dump() for choice in body.choices]
    return [_out(one) for one in use_cases.commit_import(db, user, workspace_id, import_id, choices)]


@router.post("/agent/sessions/{session_id}/skill-draft", response_model=AgentSkillDraftOut)
def draft_skill(session_id: str, db: Tx, user: CurrentUser) -> dict:
    """「存成技能」:用这次对话正在用的对话模型起草一份 SKILL.md。**不保存** —— 交回编辑表单,用户改完再建。"""
    return use_cases.draft_from_session(db, user, session_id)


__all__ = ["router"]

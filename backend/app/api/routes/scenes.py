from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.api.deps import CurrentUser, DbSession
from app.api.schemas.scenes import SceneCreate, SceneUpdate, SceneOut, SceneOperations
from app.db.models import Scene3D, Scene3DModel, Scene3DRevision
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes import (apply_scene_operations, create_scene, delete_scene_model_files,
                                get_scene, import_model, model_file, save_scene, scene_preview)

router = APIRouter(tags=["3D scenes"])


@router.get("/scenes")
def list_scenes(workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    rows = db.scalars(select(Scene3D).where(Scene3D.workspace_id == workspace_id).order_by(Scene3D.updated_at.desc()).limit(200))
    return [{"id": r.id, "name": r.name, "revision": r.revision, "updated_at": r.updated_at,
             "object_count": len(r.content.get("objects", [])), "shot_count": len(r.content.get("shots", [])),
             "preview": scene_preview(r.content)} for r in rows]


@router.post("/scenes", response_model=SceneOut)
def create(body: SceneCreate, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    return create_scene(db, body.workspace_id, body.name, body.content)


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def read(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    return get_scene(db, workspace_id, scene_id)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def edit(scene_id: str, body: SceneUpdate, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    return save_scene(db, get_scene(db, body.workspace_id, scene_id), body.base_revision, body.name, body.content)


@router.get("/scenes/{scene_id}/revisions")
def revisions(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_scene(db, workspace_id, scene_id)
    rows = db.scalars(select(Scene3DRevision).where(Scene3DRevision.scene_id == scene_id).order_by(Scene3DRevision.revision.desc()).limit(100))
    return [{"revision": r.revision, "name": r.snapshot["name"], "created_at": r.created_at} for r in rows]


@router.get("/scenes/{scene_id}/revisions/{revision}")
def revision_content(scene_id: str, revision: int, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_scene(db, workspace_id, scene_id)
    row = db.get(Scene3DRevision, (scene_id, revision))
    if row is None:
        raise HTTPException(404, "Revision not found")
    return row.snapshot


@router.post("/scenes/{scene_id}/models")
async def upload(scene_id: str, db: DbSession, user: CurrentUser, workspace_id: str = Form(...), file: UploadFile = File(...)):
    ensure_workspace_perm(db, user, workspace_id, "edit")
    scene = get_scene(db, workspace_id, scene_id)
    # **把文件对象直接交出去,一个字节都不经过这里。** multipart 解析时整份已经落到临时文件上,
    # `file.file` 就是那个句柄;`file.size` 是真实大小,用来在落盘之前就挡掉超限的。
    model = import_model(db, scene, file.filename or "Model", file.file, declared_size=file.size)
    return {"id": model.id, "name": model.name, "format": model.format}


@router.get("/scenes/{scene_id}/models/{model_id}")
def model_data(scene_id: str, model_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_scene(db, workspace_id, scene_id)
    model = db.get(Scene3DModel, model_id)
    if model is None or model.scene_id != scene_id:
        raise HTTPException(404, "Model not found")
    # **流式发文件,不把它读进内存。** 此前是 `Response(model.data)`:一份 100 MB 的模型,
    # 每个并发下载各占一份内存。FileResponse 走 sendfile,顺带自带 Range 支持。
    path = model_file(model)
    if not path.is_file():
        raise HTTPException(404, "模型文件已不在,请重新导入。")
    return FileResponse(path, media_type="model/gltf-binary" if model.format == "glb" else "model/gltf+json",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post('/scenes/{scene_id}/operations', response_model=SceneOut)
def operations(scene_id: str, body: SceneOperations, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, 'edit')
    return apply_scene_operations(db, get_scene(db, body.workspace_id, scene_id), body.base_revision,
                                  body.objects, body.remove_ids, body.shots, body.name)


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, workspace_id, "edit")
    scene = get_scene(db, workspace_id, scene_id)
    # 行随场景 CASCADE 一起走;**文件不会** —— 和字体、LUT 同一套,由这里显式清掉。
    delete_scene_model_files(scene)
    db.delete(scene)
    db.commit()
    return Response(status_code=204)

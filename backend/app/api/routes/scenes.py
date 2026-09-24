from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession
from app.api.schemas.scenes import (SceneCreate, SceneOperations, SceneOut, SceneReferenceOut,
                                    SceneReferenceRequest, SceneUpdate)
from app.db.models import Scene3D, Scene3DModel, Scene3DRevision
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes import (apply_scene_operations, create_scene, delete_model, get_scene,
                                import_model, list_models, model_file, render_shot_references,
                                save_scene, scene_preview, view_scene)
#: 路由函数也叫 delete_scene(接口名),所以领域那个换个名字进来 —— 同名的两个东西
#: 放在一个文件里,读的人得每次判断是哪一个。
from app.domain.scenes import delete_scene as remove_scene

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


# 模型归**工作区**,不归某个场景(见 db.model_slices.scenes.Scene3DModel):一件道具导一次、
# 处处能摆,而工作流每跑一次都新建一个场景 —— 挂在场景下面时它永远进不了自动成片的布景。
@router.get("/scene-models")
def models(workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    return [{"id": m.id, "name": m.name, "format": m.format, "size": m.size} for m in list_models(db, workspace_id)]


@router.post("/scene-models")
async def upload(db: DbSession, user: CurrentUser, workspace_id: str = Form(...), file: UploadFile = File(...)):
    ensure_workspace_perm(db, user, workspace_id, "edit")
    # **把文件对象直接交出去,一个字节都不经过这里。** multipart 解析时整份已经落到临时文件上,
    # `file.file` 就是那个句柄;`file.size` 是真实大小,用来在落盘之前就挡掉超限的。
    model = import_model(db, workspace_id, file.filename or "Model", file.file, declared_size=file.size)
    return {"id": model.id, "name": model.name, "format": model.format, "size": model.size}


@router.delete("/scene-models/{model_id}", status_code=204)
def remove_model(model_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, workspace_id, "edit")
    delete_model(db, workspace_id, model_id)
    return Response(status_code=204)


@router.get("/scene-models/{model_id}")
def model_data(model_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    model = db.get(Scene3DModel, model_id)
    if model is None or model.workspace_id != workspace_id:
        raise HTTPException(404, "Model not found")
    # **流式发文件,不把它读进内存。** 此前是 `Response(model.data)`:一份 100 MB 的模型,
    # 每个并发下载各占一份内存。FileResponse 走 sendfile,顺带自带 Range 支持。
    path = model_file(model)
    if not path.is_file():
        raise HTTPException(404, tr("routeErr_modelFileGone"))
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
    # 删除的**引用完整性决定**在领域层(domain/scenes.delete_scene),不在这里 ——
    # 路由是薄转译。此前这一句是裸的 `db.delete(scene)`,于是"还有谁在用"这件事在场景这条
    # 路上根本没人问,而同一层的模型那条路问了。
    remove_scene(db, workspace_id, scene_id)
    return Response(status_code=204)


@router.get("/scenes/{scene_id}/view")
def view(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
         views: Annotated[list[str], Query()] = [], shot_id: str = "", time: float = 0.0):  # noqa: B006
    """渲几张图给智能体看。不写素材库、不落盘 —— 只读。"""
    ensure_workspace_access(db, user, workspace_id)
    return view_scene(db, get_scene(db, workspace_id, scene_id), views=views, shot_id=shot_id, time=time)


@router.post("/scenes/{scene_id}/shots/{shot_id}/references", response_model=SceneReferenceOut)
def references(scene_id: str, shot_id: str, body: SceneReferenceRequest, db: DbSession, user: CurrentUser):
    """渲这个镜头的白模参考(首尾静帧 / 运镜视频),登记成素材。会往素材库里写东西,所以要 edit。"""
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    scene = get_scene(db, body.workspace_id, scene_id)
    return render_shot_references(db, scene, shot_id, render=body.render, project_id=body.project_id)

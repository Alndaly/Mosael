from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, Response
from fastapi.responses import FileResponse
from app.api.responses import file_response
from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.scenes import (SceneCreate, SceneOperations, SceneOut, SceneReferenceOut,
                                    SceneReferenceRequest, SceneUpdate)
from app.domain.scenes import use_cases

router = APIRouter(tags=["3D scenes"])

# 闸与「这个场景在不在这个工作区」都在 domain/scenes/use_cases;这里只做 HTTP 的转译。


@router.get("/scenes")
def list_scenes(workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.list_scenes(db, user, workspace_id)


@router.post("/scenes", response_model=SceneOut)
def create(body: SceneCreate, db: Tx, user: CurrentUser):
    return use_cases.create(db, user, body.workspace_id, body.name, body.content)


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def read(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.read(db, user, workspace_id, scene_id)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def edit(scene_id: str, body: SceneUpdate, db: Tx, user: CurrentUser):
    return use_cases.save(
        db, user, body.workspace_id, scene_id, base_revision=body.base_revision, name=body.name, content=body.content
    )


@router.get("/scenes/{scene_id}/preview")
def preview_image(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """画板 3D 场景格上的全景白模(JPEG)。`<img>` 带不了请求头,凭据走 `?token=`;调用方在地址里带上修订号,
    场景一改地址就变,浏览器缓存不会给出旧图。"""
    path = use_cases.overview_image(db, user, workspace_id, scene_id)
    return file_response(db, path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/scenes/{scene_id}/revisions")
def revisions(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.revisions(db, user, workspace_id, scene_id)


@router.get("/scenes/{scene_id}/revisions/{revision}")
def revision_content(scene_id: str, revision: int, workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.revision_content(db, user, workspace_id, scene_id, revision)


# 模型归**工作区**,不归某个场景(见 db.model_slices.scenes.Scene3DModel):一件道具导一次、
# 处处能摆,而工作流每跑一次都新建一个场景 —— 挂在场景下面时它永远进不了自动成片的布景。
@router.get("/scene-models")
def models(workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.list_models(db, user, workspace_id)


@router.post("/scene-models")
def upload(db: Tx, user: CurrentUser, workspace_id: str = Form(...), file: UploadFile = File(...)):
    # 同步端点(跑在线程池里):导入是拷一份可能上百 MB 的文件,放在 async 里会把事件循环卡住。
    # **把文件对象直接交出去,一个字节都不经过这里。** multipart 解析时整份已经落到临时文件上,
    # `file.file` 就是那个句柄;`file.size` 是真实大小,用来在落盘之前就挡掉超限的。
    model = use_cases.import_model(
        db, user, workspace_id, name=file.filename or "Model", stream=file.file, declared_size=file.size
    )
    return {"id": model.id, "name": model.name, "format": model.format, "size": model.size}


@router.delete("/scene-models/{model_id}", status_code=204)
def remove_model(model_id: str, workspace_id: str, db: Tx, user: CurrentUser):
    use_cases.delete_model(db, user, workspace_id, model_id)
    return Response(status_code=204)


@router.get("/scene-models/{model_id}")
def model_data(model_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    model, path = use_cases.model_file(db, user, workspace_id, model_id)
    # **流式发文件,不把它读进内存。** 此前是 `Response(model.data)`:一份 100 MB 的模型,
    # 每个并发下载各占一份内存。FileResponse 走 sendfile,顺带自带 Range 支持。
    if not path.is_file():
        raise HTTPException(404, tr("routeErr_modelFileGone"))
    return file_response(db, path, media_type="model/gltf-binary" if model.format == "glb" else "model/gltf+json",
                         headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post('/scenes/{scene_id}/operations', response_model=SceneOut)
def operations(scene_id: str, body: SceneOperations, db: Tx, user: CurrentUser):
    return use_cases.apply_operations(
        db, user, body.workspace_id, scene_id, base_revision=body.base_revision,
        objects=body.objects, remove_ids=body.remove_ids, shots=body.shots, name=body.name,
    )


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: str, workspace_id: str, db: Tx, user: CurrentUser):
    use_cases.delete(db, user, workspace_id, scene_id)
    return Response(status_code=204)


@router.get("/scenes/{scene_id}/view")
def view(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
         views: Annotated[list[str], Query()] = [], shot_id: str = "", time: float = 0.0):  # noqa: B006
    """渲几张图给智能体看。不写素材库、不落盘 —— 只读。"""
    return use_cases.view(db, user, workspace_id, scene_id, views=views, shot_id=shot_id, time=time)


@router.post("/scenes/{scene_id}/shots/{shot_id}/references", response_model=SceneReferenceOut)
def references(scene_id: str, shot_id: str, body: SceneReferenceRequest, db: Tx, user: CurrentUser):
    """渲这个镜头的白模参考(首尾静帧 / 运镜视频),登记成素材。会往素材库里写东西,所以要 edit。"""
    return use_cases.render_references(
        db, user, body.workspace_id, scene_id, shot_id, render=body.render, project_id=body.project_id
    )

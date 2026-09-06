from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Response
from sqlalchemy import select
from app.api.deps import CurrentUser, DbSession
from app.api.schemas.scenes import SceneCreate, SceneUpdate, SceneOut, SceneOperations
from app.db.models import Scene3D, Scene3DModel, Scene3DRevision
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes import create_scene, get_scene, save_scene, import_model, apply_scene_operations

router = APIRouter(tags=["3D scenes"])


@router.get("/scenes")
def list_scenes(workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    rows = db.scalars(select(Scene3D).where(Scene3D.workspace_id == workspace_id).order_by(Scene3D.updated_at.desc()).limit(200))
    return [{"id": r.id, "name": r.name, "revision": r.revision, "updated_at": r.updated_at,
             "object_count": len(r.content.get("objects", [])), "shot_count": len(r.content.get("shots", []))} for r in rows]


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
    get_scene(db, workspace_id, scene_id)
    data = await file.read(25 * 1024 * 1024 + 1)
    model = import_model(db, scene_id, file.filename or "Model", data)
    return {"id": model.id, "name": model.name, "format": model.format}


@router.get("/scenes/{scene_id}/models/{model_id}")
def model_data(scene_id: str, model_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_scene(db, workspace_id, scene_id)
    model = db.get(Scene3DModel, model_id)
    if model is None or model.scene_id != scene_id:
        raise HTTPException(404, "Model not found")
    return Response(model.data, media_type="model/gltf-binary" if model.format == "glb" else "model/gltf+json",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post('/scenes/{scene_id}/operations', response_model=SceneOut)
def operations(scene_id: str, body: SceneOperations, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, 'edit')
    return apply_scene_operations(db, get_scene(db, body.workspace_id, scene_id), body.base_revision,
                                  body.objects, body.remove_ids, body.shots, body.name)

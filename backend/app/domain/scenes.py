"""Workspace-owned scene revisions and bounded, self-contained glTF imports."""
import json
import struct
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.db.models import Scene3D, Scene3DRevision, Scene3DModel
from app.db.model_base import now
from app.domain.scene_types import SceneContent


def get_scene(db: Session, workspace_id: str, scene_id: str) -> Scene3D:
    scene = db.scalar(select(Scene3D).where(Scene3D.id == scene_id, Scene3D.workspace_id == workspace_id))
    if scene is None:
        raise HTTPException(404, "3D scene not found")
    return scene


def check_models(db: Session, scene_id: str, content: SceneContent):
    ids = {o.model_id for o in content.objects if o.model_id}
    if ids:
        owned = set(db.scalars(select(Scene3DModel.id).where(Scene3DModel.scene_id == scene_id, Scene3DModel.id.in_(ids))))
        if owned != ids:
            raise HTTPException(422, "Imported model does not belong to this scene")


def create_scene(db: Session, workspace_id: str, name: str, content: SceneContent) -> Scene3D:
    if any(o.model_id for o in content.objects):
        raise HTTPException(422, "Import models after creating the scene")
    scene = Scene3D(workspace_id=workspace_id, name=name, content=content.model_dump(mode="json"))
    db.add(scene)
    db.flush()
    db.add(Scene3DRevision(scene_id=scene.id, revision=1, snapshot={"name": name, "content": scene.content}))
    db.commit()
    db.refresh(scene)
    return scene


def save_scene(db: Session, scene: Scene3D, base_revision: int, name: str, content: SceneContent) -> Scene3D:
    if scene.revision != base_revision:
        raise HTTPException(409, "Scene changed elsewhere. Keep your draft and reload before saving.")
    check_models(db, scene.id, content)
    data = content.model_dump(mode="json")
    if data == scene.content and name == scene.name:
        return scene
    result = db.execute(update(Scene3D).where(Scene3D.id == scene.id, Scene3D.revision == base_revision).values(
        name=name, content=data, revision=base_revision+1, updated_at=now()), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Scene changed elsewhere")
    db.add(Scene3DRevision(scene_id=scene.id, revision=base_revision+1, snapshot={"name": name, "content": data}))
    db.commit()
    db.refresh(scene)
    return scene


def validate_model(data: bytes) -> str:
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Model limit is 25 MB")
    fmt = "glb" if data[:4] == b"glTF" else "gltf"
    try:
        if fmt == "glb":
            magic, version, length, chunk_size, chunk_type = struct.unpack("<4sIIII", data[:20])
            if version != 2 or length != len(data) or chunk_type != 0x4E4F534A or chunk_size > len(data)-20:
                raise ValueError("Invalid GLB header")
            doc = json.loads(data[20:20+chunk_size])
        else:
            doc = json.loads(data)
        if doc.get("asset", {}).get("version") != "2.0":
            raise ValueError("glTF 2.0 required")
        # Never allow imported models to fetch network URLs or local files.
        def inspect(value, depth=0):
            if depth > 48:
                raise ValueError("Model structure too deep")
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "uri" and (not isinstance(child, str) or not child.startswith("data:")):
                        raise ValueError("Use a self-contained GLB or embedded glTF; external resources are not supported")
                    inspect(child, depth+1)
            elif isinstance(value, list):
                for child in value:
                    inspect(child, depth+1)
        inspect(doc)
        if len(doc.get("nodes", [])) > 5000 or len(doc.get("meshes", [])) > 2000:
            raise ValueError("Model is too complex for real-time editing")
    except (ValueError, TypeError, AttributeError, struct.error, RecursionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return fmt


def import_model(db: Session, scene_id: str, name: str, data: bytes) -> Scene3DModel:
    fmt = validate_model(data)
    model = Scene3DModel(scene_id=scene_id, name=name[:160], format=fmt, data=data)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def apply_scene_operations(db: Session, scene: Scene3D, base_revision: int, objects: list[dict], remove_ids: list[str], shots: list[dict] | None, name: str | None) -> Scene3D:
    """Merge object fields atomically; deletion includes descendants. No executable code."""
    from copy import deepcopy
    from pydantic import ValidationError
    content = deepcopy(scene.content)
    removed = set(remove_ids)
    for _ in range(16):
        removed.update(o['id'] for o in content['objects'] if o.get('parent_id') in removed)
    by_id = {o['id']: o for o in content['objects'] if o['id'] not in removed}
    for patch in objects:
        if not isinstance(patch.get('id'), str):
            raise HTTPException(422, 'Every object operation needs an id')
        obj = {**by_id.get(patch['id'], {}), **patch}
        if 'parameters' in patch and isinstance(patch['parameters'], dict):
            obj['parameters'] = {**by_id.get(patch['id'], {}).get('parameters', {}), **patch['parameters']}
        by_id[patch['id']] = obj
    content['objects'] = list(by_id.values())
    if shots is not None:
        content['shots'] = shots
    try:
        validated = SceneContent.model_validate(content)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return save_scene(db, scene, base_revision, name if name is not None else scene.name, validated)

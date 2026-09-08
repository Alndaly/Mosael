from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.db.models import PluginInstance
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.scenes import get_scene
from app.domain.blender import bridge

router = APIRouter(prefix='/scenes', tags=['Blender'])


@router.get('/blender/connections')
def connections(db: DbSession, user: CurrentUser):
    rows = db.scalars(select(PluginInstance).where(PluginInstance.owner_user_id == user.id, PluginInstance.package_id == bridge.PACKAGE))
    return {'local': settings.local_desktop, 'connections': [{'id': r.id, 'name': r.name, 'enabled': r.enabled} for r in rows]}


@router.post('/blender/connections/{instance_id}/check')
def check(instance_id: str, db: DbSession, user: CurrentUser):
    instance = bridge.connection(db, user, instance_id)
    with bridge.exclusive(instance.id):
        result = bridge.call(db, instance, 'get_scene_info', {'user_prompt': '检查 Blender 连接'})
    # An upstream socket error is sometimes returned as JSON rather than MCP isError.
    if 'objects' not in result or result.get('error'):
        raise HTTPException(502, '无法读取 Blender 场景，请在 Blender 中开启 MCP Add-on。')
    return {'name': result.get('name', 'Blender'), 'object_count': result.get('object_count', len(result['objects']))}


@router.post('/blender/pull')
def pull(workspace_id: str, instance_id: str, db: DbSession, user: CurrentUser):
    """把 Blender 里当前打开的场景取成一个新的 Mosael 场景。不要求先发送过。"""
    ensure_workspace_perm(db, user, workspace_id, 'edit')
    return bridge.pull(db, user, workspace_id, instance_id)


@router.get('/{scene_id}/blender')
def history(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    return bridge.history(get_scene(db, workspace_id, scene_id), user)


@router.post('/{scene_id}/blender')
def send(scene_id: str, db: DbSession, user: CurrentUser, workspace_id: str = Form(...),
         instance_id: str = Form(...), revision: int = Form(...), shot_id: str = Form(...), file: UploadFile = File(...)):
    ensure_workspace_perm(db, user, workspace_id, 'edit')
    scene = get_scene(db, workspace_id, scene_id)
    return bridge.send(db, user, scene, instance_id, revision, shot_id, file.file, size=file.size)


@router.post('/{scene_id}/blender/{transfer_id}/receive')
def receive(scene_id: str, transfer_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
            into_current: bool = False):
    """接回 Blender 的改动。

    `into_current=true` 时不建新场景,而是把模型导进当前场景、把新内容返回给编辑器,
    由它当成一次可撤销的改动写下去(理由见 bridge.receive 的说明)。
    """
    ensure_workspace_perm(db, user, workspace_id, 'edit')
    return bridge.receive(db, user, get_scene(db, workspace_id, scene_id), transfer_id,
                          into_current=into_current)


@router.get('/{scene_id}/blender/{transfer_id}/project')
def project(scene_id: str, transfer_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    folder, record = bridge.load(get_scene(db, workspace_id, scene_id), user, transfer_id)
    path = folder / record.get('latest_blend', 'scene.blend')
    if not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
        raise HTTPException(404, 'Blender project not found')
    return FileResponse(path, filename='Mosael.blend', media_type='application/octet-stream', headers={'Cache-Control': 'private, no-store'})

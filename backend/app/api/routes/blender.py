from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.api.responses import file_response
from sqlalchemy import select
from app.api.deps import CurrentUser, DbSession, Tx
from app.core.config import settings
from app.db.models import PluginInstance
from app.domain.blender import bridge, use_cases

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
        raise bridge.upstream_failure(result.get('error'), 'blenderErr_cantReadScene')
    return {'name': result.get('name', 'Blender'), 'object_count': result.get('object_count', len(result['objects']))}


@router.post('/blender/pull')
def pull(workspace_id: str, instance_id: str, db: Tx, user: CurrentUser):
    """把 Blender 里当前打开的场景取成一个新的 Mosael 场景。不要求先发送过。"""
    return use_cases.pull(db, user, workspace_id, instance_id)


@router.get('/{scene_id}/blender')
def history(scene_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.history(db, user, workspace_id, scene_id)


class BlenderSendRequest(BaseModel):
    workspace_id: str
    instance_id: str
    revision: int
    shot_id: str


@router.post('/{scene_id}/blender')
def send(scene_id: str, body: BlenderSendRequest, db: DbSession, user: CurrentUser):
    """把场景发进 Blender。GLB 在后端生成(见 bridge.send)—— 不再由浏览器导出上传。"""
    return use_cases.send(db, user, body.workspace_id, scene_id, instance_id=body.instance_id, revision=body.revision,
                          shot_id=body.shot_id)


@router.post('/{scene_id}/blender/{transfer_id}/receive')
def receive(scene_id: str, transfer_id: str, workspace_id: str, db: Tx, user: CurrentUser,
            into_current: bool = False):
    """接回 Blender 的改动。

    `into_current=true` 时不建新场景,而是把模型导进当前场景、把新内容返回给编辑器,
    由它当成一次可撤销的改动写下去(理由见 bridge.receive 的说明)。
    """
    return use_cases.receive(db, user, workspace_id, scene_id, transfer_id, into_current=into_current)


@router.get('/{scene_id}/blender/{transfer_id}/project')
def project(scene_id: str, transfer_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    path = use_cases.project_file(db, user, workspace_id, scene_id, transfer_id)
    return file_response(db, path, filename='Mosael.blend', media_type='application/octet-stream',
                         headers={'Cache-Control': 'private, no-store'})


# ---- 智能体用的那几条(见 domain/blender/agent.py)。跑代码不在这里:它只走确认卡。 ----

@router.get('/blender/agent/inspect')
def agent_inspect(workspace_id: str, db: DbSession, user: CurrentUser, instance_id: str = ''):
    """当前 Blender 场景里有什么。固定脚本,只读。"""
    return use_cases.inspect(db, user, workspace_id, instance_id)


@router.get('/blender/agent/look')
def agent_look(workspace_id: str, db: DbSession, user: CurrentUser,
               views: Annotated[list[str], Query()] = [], objects: Annotated[list[str], Query()] = [],  # noqa: B006
               shading: str = 'solid', zoom: float = 1.0, instance_id: str = ''):
    """把当前 Blender 场景渲成几张图给智能体看。临时改渲染设置,渲完还原。"""
    return use_cases.look(db, user, workspace_id, views=views, objects=objects, shading=shading, zoom=zoom,
                          instance_id=instance_id)


class BlenderImportRequest(BaseModel):
    workspace_id: str
    base_revision: int
    name: str = ''
    objects: list[str] = []
    position: list[float] | None = None
    instance_id: str = ''


@router.post('/{scene_id}/blender/agent/import')
def agent_import(scene_id: str, body: BlenderImportRequest, db: Tx, user: CurrentUser):
    """把 Blender 里做好的东西作为一个模型物体加进这个场景。"""
    return use_cases.import_to_scene(
        db, user, body.workspace_id, scene_id, base_revision=body.base_revision, name=body.name, objects=body.objects,
        position=body.position, instance_id=body.instance_id)

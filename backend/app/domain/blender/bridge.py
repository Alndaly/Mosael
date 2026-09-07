"""Local, user-owned MCP scene exchange. All Blender execution uses plugin invocation."""
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from app.core.config import settings
from app.db.models import PluginInstance, Scene3D, Scene3DModel, Scene3DRevision
from app.domain.plugins import PluginDomainError, instances, tools
from app.domain.scene_types import SceneContent
from app.domain.scenes import validate_model
from .scripts import command

PACKAGE = 'dev.mosael.blender'
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def connection(db, user, instance_id):
    if not settings.local_desktop:
        raise HTTPException(409, '场景互通需要本机桌面后端与 Blender 运行在同一台电脑。')
    instance = db.get(PluginInstance, instance_id)
    if not instance or instance.owner_user_id != user.id or instance.package_id != PACKAGE:
        raise HTTPException(404, 'Blender connection not found')
    if instance.config.get('BLENDER_HOST', '127.0.0.1') not in ('localhost', '127.0.0.1', '::1'):
        raise HTTPException(422, '场景互通仅支持本机 Blender。')
    try:
        if not 1 <= int(instance.config.get('BLENDER_PORT', '9876')) <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(422, '请将 Blender 连接端口设为 1–65535 的整数。') from None
    blocked = instances.blocked_reason(db, instance)
    if blocked:
        raise HTTPException(409, blocked)
    return instance


@contextmanager
def exclusive(instance_id):
    with _guard:
        lock = _locks.setdefault(instance_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, '正在与 Blender 同步，请稍后再试。')
    try:
        yield
    finally:
        lock.release()


def call(db, instance, tool, payload, workspace_id=None):
    try:
        result = tools.invoke(db, instance.id, tool, payload, workspace_id=workspace_id)
    except PluginDomainError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result.status != 'succeeded':
        raise HTTPException(502, result.error or 'Blender 未响应，请检查 Add-on 连接。')
    output = result.output
    # FastMCP wraps string return values in structuredContent.result.
    if isinstance(output.get('result'), str):
        try:
            decoded = json.loads(output['result'])
            return decoded if isinstance(decoded, dict) else {'text': output['result']}
        except ValueError:
            return {'text': output['result']}
    return output


def root(scene):
    return Path(settings.data_dir) / 'blender-bridge' / scene.workspace_id / scene.id


def write_record(folder, record):
    temporary = folder / 'transfer.tmp'
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    temporary.replace(folder / 'transfer.json')


def load(scene, user, transfer_id):
    try:
        if str(UUID(transfer_id)) != transfer_id:
            raise ValueError()
        folder = root(scene) / transfer_id
        record = json.loads((folder / 'transfer.json').read_text())
        if record['owner'] != user.id:
            raise ValueError()
    except (ValueError, OSError, KeyError):
        raise HTTPException(404, 'Transfer not found') from None
    return folder, record


def summary(record):
    return {k: record.get(k) for k in ('id', 'instance_id', 'status', 'created_at', 'source_revision', 'scene_name', 'error', 'received_scene_id', 'warnings')}


def history(scene, user):
    if not root(scene).exists():
        return []
    records = []
    for path in root(scene).glob('*/transfer.json'):
        try:
            record = json.loads(path.read_text())
            if record['owner'] == user.id:
                records.append(summary(record))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(records, key=lambda r: r['created_at'], reverse=True)[:30]


def execute(db, instance, operation, payload, workspace_id):
    output = call(db, instance, 'execute_blender_code', {'code': command(operation, payload), 'user_prompt': 'Mosael 3D 场景互通'}, workspace_id)
    result = Path(payload['result_path'])
    # Upstream may return errors as ordinary text. A unique completion file is mandatory.
    if not result.is_file():
        raise HTTPException(502, 'Blender 未完成同步：'+str(output.get('text', '请检查 Blender Add-on，并重试。'))[:600])
    if result.stat().st_size > 4*1024*1024:
        raise HTTPException(502, 'Blender 返回的数据过大。')
    try:
        value = json.loads(result.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError) as exc:
        raise HTTPException(502, 'Blender 同步结果无法读取，请重试。') from exc


def send(db, user, scene, instance_id, revision, shot_id, data):
    instance = connection(db, user, instance_id)
    if revision != scene.revision:
        raise HTTPException(409, '场景已变更，请等待保存完成后重新发送。')
    if shot_id not in {s['id'] for s in scene.content['shots']}:
        raise HTTPException(422, 'Shot not found')
    if validate_model(data) != 'glb':
        raise HTTPException(422, '场景传输需要 GLB。')
    with exclusive(instance.id):
        transfer_id = str(uuid4())
        folder = root(scene) / transfer_id
        folder.mkdir(parents=True)
        (folder / 'input.glb').write_bytes(data)
        snapshot = {'id': scene.id, 'name': scene.name, 'content': scene.content}
        record = {'id': transfer_id, 'owner': user.id, 'instance_id': instance.id, 'source_revision': revision,
                  'snapshot': snapshot, 'status': 'sending', 'created_at': datetime.now(timezone.utc).isoformat()}
        write_record(folder, record)
        try:
            result = execute(db, instance, 'send', {'snapshot': snapshot, 'shot_id': shot_id, 'transfer_id': transfer_id,
                'input_path': str(folder / 'input.glb'), 'blend_path': str(folder / 'scene.blend'),
                'result_path': str(folder / 'sent.json')}, scene.workspace_id)
            record.update(status='ready', scene_name=result['scene_name'])
        except Exception as exc:
            record.update(status='failed', error=str(getattr(exc, 'detail', exc)))
            raise
        finally:
            write_record(folder, record)
        return summary(record)


def receive(db, user, scene, transfer_id):
    folder, record = load(scene, user, transfer_id)
    instance = connection(db, user, record['instance_id'])
    if record['status'] != 'ready':
        raise HTTPException(409, '请先成功发送一个场景。')
    with exclusive(instance.id):
        attempt = folder / str(uuid4())
        attempt.mkdir()
        result = execute(db, instance, 'receive', {'transfer_id': transfer_id,
            'shots': record['snapshot']['content']['shots'], 'output_path': str(attempt / 'model.glb'),
            'blend_path': str(attempt / 'scene.blend'), 'result_path': str(attempt / 'result.json')}, scene.workspace_id)
        try:
            with (attempt / 'model.glb').open('rb') as stream:
                data = stream.read(25*1024*1024+1)
        except OSError as exc:
            raise HTTPException(502, 'Blender 没有生成可接收的模型，请重试。') from exc
        fmt = validate_model(data)
        model_id = uuid4().hex
        try:
            content = SceneContent.model_validate({**record['snapshot']['content'], 'shots': result['shots'],
                'objects': [{'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id}]})
        except (ValidationError, KeyError) as exc:
            raise HTTPException(422, 'Blender 镜头超出当前场景支持范围，未导入。') from exc
        # Commit the new scene, model and initial revision together; preserve the source.
        received = Scene3D(workspace_id=scene.workspace_id, name=(record['snapshot']['name']+' · Blender')[:160], content=content.model_dump(mode='json'))
        db.add(received)
        db.flush()
        db.add(Scene3DModel(id=model_id, scene_id=received.id, name='Blender model', format=fmt, data=data))
        db.add(Scene3DRevision(scene_id=received.id, revision=1, snapshot={'name': received.name, 'content': received.content}))
        db.commit()
        record.update(received_scene_id=received.id, warnings=result.get('warnings', []), latest_blend=str(attempt.relative_to(folder) / 'scene.blend'))
        write_record(folder, record)
        return summary(record)

"""Local, user-owned MCP scene exchange. All Blender execution uses plugin invocation.

**为什么抛领域异常而不是 HTTPException**:互通也从 MCP 工具进来,不只走路由。状态码由边界
统一翻(见 main.py 的处理器),与 `domain/permissions`、`domain/notes`、`domain/scenes` 同构。

四个子类各对应一个**故意的**答案,尤其 502:Blender 没响应、或者回了读不懂的东西,那是
**上游**的问题,不是调用方请求有错 —— 用 4xx 会让人去改自己的请求,而该做的是去看 Add-on。
"""
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from pydantic import ValidationError
from app.core.config import settings
from app.db.models import PluginInstance
from app.domain.plugins import PluginDomainError, instances, tools
from app.domain.scene_types import SceneContent
from app.domain.scenes import create_scene_with_model, validate_model
from .scripts import command

class BlenderDomainError(ValueError):
    """Blender 互通说不行。`status` 由子类给,边界照着翻(见 main.py)。"""

    status = 422


class BlenderNotFound(BlenderDomainError):
    status = 404


class BlenderConflict(BlenderDomainError):
    """当前状态下做不了:不是本机、连接被禁用、正在同步、或者场景已经变了。"""

    status = 409


class BlenderUnavailable(BlenderDomainError):
    """**上游的问题。** Blender 没响应、或回了读不懂/过大的数据。"""

    status = 502


PACKAGE = 'dev.mosael.blender'
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def connection(db, user, instance_id):
    if not settings.local_desktop:
        raise BlenderConflict('场景互通需要本机桌面后端与 Blender 运行在同一台电脑。')
    instance = db.get(PluginInstance, instance_id)
    if not instance or instance.owner_user_id != user.id or instance.package_id != PACKAGE:
        raise BlenderNotFound('Blender connection not found')
    if instance.config.get('BLENDER_HOST', '127.0.0.1') not in ('localhost', '127.0.0.1', '::1'):
        raise BlenderDomainError('场景互通仅支持本机 Blender。')
    try:
        if not 1 <= int(instance.config.get('BLENDER_PORT', '9876')) <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        raise BlenderDomainError('请将 Blender 连接端口设为 1–65535 的整数。') from None
    blocked = instances.blocked_reason(db, instance)
    if blocked:
        raise BlenderConflict(blocked)
    return instance


@contextmanager
def exclusive(instance_id):
    with _guard:
        lock = _locks.setdefault(instance_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise BlenderConflict('正在与 Blender 同步，请稍后再试。')
    try:
        yield
    finally:
        lock.release()


def call(db, instance, tool, payload, workspace_id=None):
    try:
        result = tools.invoke(db, instance.id, tool, payload, workspace_id=workspace_id)
    except PluginDomainError as exc:
        raise BlenderConflict(str(exc)) from exc
    if result.status != 'succeeded':
        raise BlenderUnavailable(result.error or 'Blender 未响应，请检查 Add-on 连接。')
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
        record = json.loads((folder / 'transfer.json').read_text(encoding='utf-8'))
        if record['owner'] != user.id:
            raise ValueError()
    except (ValueError, OSError, KeyError):
        raise BlenderNotFound('Transfer not found') from None
    return folder, record


def summary(record):
    return {k: record.get(k) for k in ('id', 'instance_id', 'status', 'created_at', 'source_revision', 'scene_name', 'error', 'received_scene_id', 'warnings')}


def history(scene, user):
    if not root(scene).exists():
        return []
    records = []
    for path in root(scene).glob('*/transfer.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
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
        raise BlenderUnavailable('Blender 未完成同步：'+str(output.get('text', '请检查 Blender Add-on，并重试。'))[:600])
    if result.stat().st_size > 4*1024*1024:
        raise BlenderUnavailable('Blender 返回的数据过大。')
    try:
        value = json.loads(result.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError) as exc:
        raise BlenderUnavailable('Blender 同步结果无法读取，请重试。') from exc


def send(db, user, scene, instance_id, revision, shot_id, data):
    instance = connection(db, user, instance_id)
    if revision != scene.revision:
        raise BlenderConflict('场景已变更，请等待保存完成后重新发送。')
    if shot_id not in {s['id'] for s in scene.content['shots']}:
        raise BlenderDomainError('Shot not found')
    if validate_model(data) != 'glb':
        raise BlenderDomainError('场景传输需要 GLB。')
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
        raise BlenderConflict('请先成功发送一个场景。')
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
            raise BlenderUnavailable('Blender 没有生成可接收的模型，请重试。') from exc
        fmt = validate_model(data)
        model_id = uuid4().hex
        try:
            content = SceneContent.model_validate({**record['snapshot']['content'], 'shots': result['shots'],
                'objects': [{'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id}]})
        except (ValidationError, KeyError) as exc:
            raise BlenderDomainError('Blender 镜头超出当前场景支持范围，未导入。') from exc
        # 场景、模型、初始修订一起落地。**建行归场景域**(ADR-0003),这里只描述要建什么。
        received = create_scene_with_model(
            db, workspace_id=scene.workspace_id, name=record['snapshot']['name'] + ' · Blender',
            content=content, model_id=model_id, model_name='Blender model',
            model_format=fmt, model_data=data)
        record.update(received_scene_id=received.id, warnings=result.get('warnings', []), latest_blend=str(attempt.relative_to(folder) / 'scene.blend'))
        write_record(folder, record)
        return summary(record)

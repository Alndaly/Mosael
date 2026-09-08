"""Local, user-owned MCP scene exchange. All Blender execution uses plugin invocation.

**为什么抛领域异常而不是 HTTPException**:互通也从 MCP 工具进来,不只走路由。状态码由边界
统一翻(见 main.py 的处理器),与 `domain/permissions`、`domain/notes`、`domain/scenes` 同构。

四个子类各对应一个**故意的**答案,尤其 502:Blender 没响应、或者回了读不懂的东西,那是
**上游**的问题,不是调用方请求有错 —— 用 4xx 会让人去改自己的请求,而该做的是去看 Add-on。
"""
import json
import shutil
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
from app.domain.scenes import MODEL_READ_LIMIT, create_scene_with_model, import_model, validate_model
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


def receive(db, user, scene, transfer_id, *, into_current=False):
    """把 Blender 里的改动接回来。

    两种去处:

        into_current=False   建一个新场景(默认)。原场景一个字节都不动。
        into_current=True    **落到当前场景上**,作为它的下一次编辑。

    后者只做一半:把模型导进这个场景,然后**把新内容返回给调用方**,由编辑器像"恢复某个
    历史版本"那样把它当成一次普通改动写下去。这么分是有原因的 ——

      * 编辑器手上有一份草稿。若这里直接改库,那份草稿立刻就是旧的,它的下一次自动保存
        要么冲突、要么把刚接回来的东西盖掉;
      * 走编辑器那条路,接收就**能撤销**(⌘Z),和恢复历史版本同一个手感;
      * 并发也不必在这里再造一套:自动保存本来就带 base_revision 的 CAS。

    代价是用户若立刻撤销,那份导进来的模型行就没人引用了。它仍归这个场景所有
    (`check_models` 的约束成立),只是占着存储 —— 比"库改了、草稿旧了"那种错法便宜得多。
    """
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
                data = stream.read(MODEL_READ_LIMIT)
        except OSError as exc:
            raise BlenderUnavailable('Blender 没有生成可接收的模型，请重试。') from exc
        fmt = validate_model(data)
        # 落到当前场景:模型先进库(建行归场景域,ADR-0003),内容交回编辑器去写。
        model_id = import_model(db, scene.id, 'Blender model', data).id if into_current else uuid4().hex
        try:
            content = SceneContent.model_validate({**record['snapshot']['content'], 'shots': result['shots'],
                'objects': [{'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id}]})
        except (ValidationError, KeyError) as exc:
            raise BlenderDomainError('Blender 镜头超出当前场景支持范围，未导入。') from exc
        if into_current:
            record.update(warnings=result.get('warnings', []), latest_blend=str(attempt.relative_to(folder) / 'scene.blend'))
            write_record(folder, record)
            return {**summary(record), 'content': content.model_dump(mode='json')}
        # 场景、模型、初始修订一起落地。**建行归场景域**(ADR-0003),这里只描述要建什么。
        received = create_scene_with_model(
            db, workspace_id=scene.workspace_id, name=record['snapshot']['name'] + ' · Blender',
            content=content, model_id=model_id, model_name='Blender model',
            model_format=fmt, model_data=data)
        record.update(received_scene_id=received.id, warnings=result.get('warnings', []), latest_blend=str(attempt.relative_to(folder) / 'scene.blend'))
        write_record(folder, record)
        return summary(record)


def pull(db, user, workspace_id, instance_id):
    """把 Blender 里当前打开的那个场景取成一个新的 Mosael 场景。

    **不要求先发送过。** send/receive 是一趟往返:receive 靠发送时写在 Scene 上的
    `mosael_transfer_id` 找回那一份。而人手上常常先有一个 Blender 工程,这条是给它的入口。

    只取几何体。相机取不回来:Mosael 的镜头要知道"看向哪里",发送时那是我们自己写在相机上的
    `mosael_target_distance`;换成任意一个 Blender 相机,这个距离无从得知,猜一个只会让构图
    默默错掉。有相机就明说一句,而不是悄悄丢掉。

    落盘的只有一份临时 GLB:它的字节随后进了模型表,文件本身没有第二个读者,所以用完即删 ——
    留下来就是一个没有任何入口能清理的目录(传输记录那套是按场景归档的,这里还没有场景)。
    """
    instance = connection(db, user, instance_id)
    with exclusive(instance.id):
        folder = Path(settings.data_dir) / 'blender-bridge' / workspace_id / '_pull' / str(uuid4())
        folder.mkdir(parents=True)
        try:
            result = execute(db, instance, 'pull', {'output_path': str(folder / 'model.glb'),
                'result_path': str(folder / 'pulled.json')}, workspace_id)
            try:
                with (folder / 'model.glb').open('rb') as stream:
                    data = stream.read(MODEL_READ_LIMIT)
            except OSError as exc:
                raise BlenderUnavailable('Blender 没有导出可用的模型，请重试。') from exc
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        fmt = validate_model(data)
        model_id = uuid4().hex
        content = SceneContent.model_validate({'objects': [
            {'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id}]})
        scene = create_scene_with_model(
            db, workspace_id=workspace_id, name=result.get('scene_name') or 'Blender 场景',
            content=content, model_id=model_id, model_name='Blender model',
            model_format=fmt, model_data=data)
        warnings = list(result.get('warnings') or [])
        if result.get('camera_count'):
            warnings.append('Blender 里的 %d 个相机没有一起取回 —— 镜头需要「看向哪里」，'
                            '而这个距离只有从 Mosael 发送过去的相机才带着。请在这里重新设计镜头。'
                            % result['camera_count'])
        return {'scene_id': scene.id, 'name': scene.name, 'warnings': warnings}

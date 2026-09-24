"""Local, user-owned MCP scene exchange. All Blender execution uses plugin invocation.

**为什么抛领域异常而不是 HTTPException**:互通也从 MCP 工具进来,不只走路由。状态码由边界
统一翻(见 main.py 的处理器),与 `domain/permissions`、`domain/notes`、`domain/scenes` 同构。

四个子类各对应一个**故意的**答案,尤其 502:Blender 没响应、或者回了读不懂的东西,那是
**上游**的问题,不是调用方请求有错 —— 用 4xx 会让人去改自己的请求,而该做的是去看 Add-on。
"""
import json
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from pydantic import ValidationError
from app.core.config import settings
from app.core.i18n import LocalizedError, t
from app.db.models import PluginInstance
from app.domain.plugins import PluginDomainError, instances, tools
from app.domain.scene_types import SceneContent
from app.domain.scenes import create_scene, import_model, validate_model_file
from .scripts import command

class BlenderDomainError(LocalizedError):
    """Blender 互通说不行。带文案 key(`blenderErr_*`,见 core/i18n),按请求方的语言翻;
    `status` 由子类给,边界照着翻(见 main.py)。"""

    status = 422


class BlenderNotFound(BlenderDomainError):
    status = 404


class BlenderConflict(BlenderDomainError):
    """当前状态下做不了:不是本机、连接被禁用、正在同步、或者场景已经变了。"""

    status = 409


class BlenderTimeout(BlenderDomainError):
    """**我等得不够久**,不是对面坏了。

    这两件事此前在出口混成一句「Blender 未响应,请检查 Add-on 连接」—— 而那时 Blender 正在
    好好地跑,排查方向于是从第一步就被指向了 Add-on。更坏的一半:超时之后**没人告诉 Blender
    停**,`exclusive()` 那把锁当场释放,而那边的脚本还在它自己的主线程上跑。用户看到失败就
    重试,第二次排在第一次后面 —— 又是一次超时。所以这句话要明说「别立刻重试」。
    """

    status = 504


class BlenderUnavailable(BlenderDomainError):
    """**上游的问题。** Blender 没响应、或回了读不懂/过大的数据。"""

    status = 502


#: Blender MCP Add-on 没开、端口不对时,上游原样回的那句话。认出它就换成一句能照着做的话。
_ADDON_NOT_RUNNING = "could not connect to blender"


def upstream_failure(text: object, empty_key: str, framed: str = "blenderErr_syncFailed") -> BlenderUnavailable:
    """Blender 那边没做成:把上游回的原文变成一条带 key 的错误。

    最常见的「Add-on 没开」认出来,给一句照着做就行的话;别的原文放进翻好的句子里当 `detail`
    (它是上游的话,我们不翻、也不猜);什么都没回就用 `empty_key`。
    """
    detail = str(text or "").strip()
    if not detail:
        return BlenderUnavailable(empty_key)
    if _ADDON_NOT_RUNNING in detail.lower():
        return BlenderUnavailable("blenderErr_addonNotRunning")
    return BlenderUnavailable(framed, detail=detail[:600])


PACKAGE = 'dev.mosael.blender'
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def connection(db, user, instance_id):
    if not settings.local_desktop:
        raise BlenderConflict('blenderErr_notLocalDesktop')
    instance = db.get(PluginInstance, instance_id)
    if not instance or instance.owner_user_id != user.id or instance.package_id != PACKAGE:
        raise BlenderNotFound('blenderErr_connectionNotFound')
    if instance.config.get('BLENDER_HOST', '127.0.0.1') not in ('localhost', '127.0.0.1', '::1'):
        raise BlenderDomainError('blenderErr_localOnly')
    try:
        if not 1 <= int(instance.config.get('BLENDER_PORT', '9876')) <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        raise BlenderDomainError('blenderErr_badPort') from None
    blocked = instances.blocked_reason(db, instance)
    if blocked:
        raise BlenderConflict('blenderErr_blocked', reason=blocked)
    return instance


def resolve(db, user, instance_id=''):
    """这次用哪个 Blender 连接。没指定就用他自己的第一个**可用**连接 —— 多数人只有一个。

    界面上那个下拉总会带着 id 过来;智能体不该被迫先列一遍连接再挑一个,那是一整轮对话。
    """
    from sqlalchemy import select

    if instance_id:
        return connection(db, user, instance_id)
    rows = db.scalars(select(PluginInstance).where(
        PluginInstance.owner_user_id == user.id, PluginInstance.package_id == PACKAGE,
        PluginInstance.enabled.is_(True))).all()
    if not rows:
        raise BlenderNotFound('blenderErr_noConnection')
    reasons: list[BlenderDomainError] = []
    for row in rows:
        try:
            return connection(db, user, row.id)
        except BlenderDomainError as exc:
            reasons.append(exc)
    raise BlenderConflict(reasons[0].key, **reasons[0].params)


@contextmanager
def exclusive(instance_id):
    with _guard:
        lock = _locks.setdefault(instance_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise BlenderConflict('blenderErr_busy')
    try:
        yield
    finally:
        lock.release()


#: 一次**场景互通**(send / receive / pull)允许跑多久。
#:
#: **它不该是插件运行时那 60 秒。** 那个数对标的是「一个插件工具该跑多久」,而这 60 秒里要装下:
#: `uvx --python 3.14 mcp-for-blender` **起一个子进程**(而且每次调用都重连、不常驻)、MCP 握手、
#: 逐帧 `keyframe_insert`(每个镜头 ceil(duration*30) 帧 × 4 条 data path)、逐个模型
#: `import_scene.gltf`、最后 `export_glb`(材质失败还要再导一遍)。大一点的场景必然超时,
#: 用户看到的是「Blender 未响应」,而 Blender 其实正在好好地跑。
#:
#: 五分钟是按上面那条清单估的。这条路由由**界面**发起,上面没有更短的预算压着它。
BLENDER_SYNC_TIMEOUT_SECONDS = 300

#: 智能体的 inspect / look / execute 允许跑多久。
#:
#: **比上面那个短,因为上面还站着一个等得更急的人**:这几个工具由 MCP 客户端调用,
#: 而 `mcp_server.py` 给的客户端预算是 180 秒。后端等得比调用方久没有任何意义 ——
#: 对方早就放弃了,而我们还占着那把独占锁,用户的下一次操作被挡在外面。
#: 两者的先后由 contracts/shared-constants.json 的 budgets 钉着。
BLENDER_AGENT_TIMEOUT_SECONDS = 150


def call(db, instance, tool, payload, workspace_id=None, timeout=BLENDER_SYNC_TIMEOUT_SECONDS):
    started = time.monotonic()
    try:
        result = tools.invoke(db, instance.id, tool, payload,
                              workspace_id=workspace_id, timeout=timeout)
    except PluginDomainError as exc:
        raise BlenderConflict('blenderErr_plugin', detail=str(exc)) from exc
    if result.status != 'succeeded':
        # **「我等得不够久」和「对面坏了」是两件事。** 判据用**实际等了多久**,不去嗅错误
        # 文本 —— 前者是事实,后者是措辞,而措辞会变。
        if time.monotonic() - started >= timeout - 1:
            raise BlenderTimeout('blenderErr_timeout', seconds=int(timeout))
        raise upstream_failure(result.error, 'blenderErr_unresponsive')
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
        raise BlenderNotFound('blenderErr_transferNotFound') from None
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


def execute(db, instance, operation, payload, workspace_id, timeout=BLENDER_SYNC_TIMEOUT_SECONDS):
    output = call(db, instance, 'execute_blender_code', {'code': command(operation, payload), 'user_prompt': 'Mosael 3D 场景互通'}, workspace_id, timeout)
    result = Path(payload['result_path'])
    # Upstream may return errors as ordinary text. A unique completion file is mandatory.
    if not result.is_file():
        raise upstream_failure(output.get('text'), 'blenderErr_syncFailedNoDetail', framed='blenderErr_syncFailed')
    if result.stat().st_size > 4*1024*1024:
        raise BlenderUnavailable('blenderErr_tooLarge')
    try:
        value = json.loads(result.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError) as exc:
        raise BlenderUnavailable('blenderErr_unreadable') from exc


def shots_with_frames(content):
    """把镜头摊平成 Blender 那边认的形状:每个镜头带上它那台相机的关键帧。

    **Blender 里相机就是物体、运镜就是它的动画**,而 Mosael 这边现在也是了 —— 但 worker 收的
    仍然是"一个镜头带一串帧"这种扁平结构。保持这个线上格式不变是有意的:worker.py 跑在
    别人的 Blender 里,换掉它的入参形状意味着新旧应用和新旧 Add-on 的组合都要考虑。
    这里做一次投影就够了。

    静止的相机(空轨)摊成一帧 —— Blender 那边需要至少一个关键帧才能定住机位。
    """
    cameras = {o['id']: o for o in content.get('objects', []) if o.get('kind') == 'camera'}
    flat = []
    for shot in content.get('shots', []):
        camera = cameras.get(shot.get('camera_id'))
        if camera is None:
            raise BlenderDomainError('blenderErr_shotNoCamera', name=shot.get('name', ''))
        track = camera.get('track') or [{
            'time': 0, 'position': camera.get('position', [8, 5, 8]),
            'target': camera.get('target', [0, 1, 0]), 'fov': camera.get('fov', 45),
        }]
        frames = [{**frame,
                   'target': frame.get('target') or camera.get('target', [0, 1, 0]),
                   'fov': frame.get('fov') if frame.get('fov') is not None else camera.get('fov', 45)}
                  for frame in track]
        flat.append({**shot, 'frames': frames})
    return flat


def apply_shot_frames(content, flat):
    """把 Blender 回传的每镜头关键帧写回**相机物体的轨**上。

    这是 `shots_with_frames` 的反向。写回相机而不是镜头 —— 镜头上已经没有 frames 这个字段了。
    """
    cameras = {o['id']: o for o in content.get('objects', []) if o.get('kind') == 'camera'}
    shots = {s['id']: s for s in content.get('shots', [])}
    for shot in flat:
        camera = cameras.get(shot.get('camera_id'))
        frames = shot.get('frames')
        if camera is None or not frames:
            continue
        if shot.get('id') in shots and 'easing' in shot:
            shots[shot['id']]['easing'] = shot['easing']
        first = frames[0]
        camera['position'] = first.get('position', camera.get('position'))
        camera['target'] = first.get('target', camera.get('target'))
        camera['fov'] = first.get('fov', camera.get('fov'))
        # 只有一帧就是固定机位 —— 不留一条空转的轨。
        camera['track'] = frames if len(frames) > 1 else []
    return content


def send(db, user, scene, instance_id, revision, shot_id):
    """把这个场景发进 Blender。**GLB 由后端自己生成**(domain/scene_render/gltf)。

    此前这一份是浏览器用 three.js 导出再上传的,于是"发送场景"这件事要求有人正开着那个页面 ——
    跑在后端的智能体根本做不到。现在界面按钮和智能体工具走同一个实现、同一份几何。

    导入的 GLB 模型不塞进生成的那一份里:它们是各自独立的文件(可能还带着 Draco/KTX2 压缩),
    解开再编一遍毫无必要。生成的 GLB 里给每个模型物体留一个带 `mosael_object_id` 的空节点,
    Blender 那边把对应的文件导进来挂上去(见 worker.attach_models)。
    """
    from app.db.models import Scene3DModel
    from app.domain.scene_render import find_shot
    from app.domain.scene_render.gltf import write_glb
    from app.domain.scene_types import SceneContent
    from app.domain.scenes import model_file

    instance = resolve(db, user, instance_id)
    if revision != scene.revision:
        raise BlenderConflict('blenderErr_sceneChanged')
    if shot_id not in {s['id'] for s in scene.content['shots']}:
        raise BlenderDomainError('blenderErr_shotNotFound')
    with exclusive(instance.id):
        transfer_id = str(uuid4())
        folder = root(scene) / transfer_id
        folder.mkdir(parents=True)
        content = SceneContent.model_validate(scene.content)
        written = write_glb(content, find_shot(content, shot_id), folder / 'input.glb')
        models = []
        for entry in written['models']:
            model = db.get(Scene3DModel, entry['model_id'])
            if model is None or model.scene_id != scene.id:
                continue
            path = model_file(model)
            if path.is_file():
                models.append({'object_id': entry['object_id'], 'name': model.name, 'path': str(path)})
        snapshot = {'id': scene.id, 'name': scene.name, 'content': scene.content}
        record = {'id': transfer_id, 'owner': user.id, 'instance_id': instance.id, 'source_revision': revision,
                  'snapshot': snapshot, 'status': 'sending', 'created_at': datetime.now(timezone.utc).isoformat()}
        write_record(folder, record)
        try:
            worker_snapshot = {**snapshot, 'content': {**snapshot['content'],
                'shots': shots_with_frames(snapshot['content'])}}
            result = execute(db, instance, 'send', {'snapshot': worker_snapshot, 'shot_id': shot_id, 'transfer_id': transfer_id,
                'input_path': str(folder / 'input.glb'), 'models': models, 'blend_path': str(folder / 'scene.blend'),
                'result_path': str(folder / 'sent.json')}, scene.workspace_id)
            record.update(status='ready', scene_name=result['scene_name'], warnings=result.get('warnings', []))
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
        raise BlenderConflict('blenderErr_sendFirst')
    with exclusive(instance.id):
        attempt = folder / str(uuid4())
        attempt.mkdir()
        result = execute(db, instance, 'receive', {'transfer_id': transfer_id,
            'shots': shots_with_frames(record['snapshot']['content']), 'output_path': str(attempt / 'model.glb'),
            'blend_path': str(attempt / 'scene.blend'), 'result_path': str(attempt / 'result.json')}, scene.workspace_id)
        exported = attempt / 'model.glb'
        if not exported.is_file():
            raise BlenderUnavailable('blenderErr_noModel')
        validate_model_file(exported)
        # 模型先进库(建行归场景域,ADR-0003)。它归**工作区**,所以两条路(落到当前场景 /
        # 建一个新场景)都是同一步 —— 此前新建那条要等场景有了 id 才挂得上模型,于是多出
        # 一个「场景+模型+修订一把落地」的特例函数。
        with exported.open('rb') as stream:
            model_id = import_model(db, scene.workspace_id, 'Blender model', stream,
                                    declared_size=exported.stat().st_size).id
        try:
            # 接回来的场景 = 一个 Blender 模型 + 原来那些机位(带回传的运镜)。相机是物体,
            # 所以它们和模型一起进 objects;镜头仍然只是"用哪台机位、拍多久"。
            snapshot = record['snapshot']['content']
            # Returned camera keys are world-space; the geometry's former groups now live
            # inside the imported GLB, so their IDs cannot remain as camera parents.
            cameras = [{**o, 'parent_id': None} for o in snapshot.get('objects', []) if o.get('kind') == 'camera']
            received = apply_shot_frames({'objects': cameras, 'shots': [dict(s) for s in snapshot.get('shots', [])]}, result['shots'])
            content = SceneContent.model_validate({**snapshot, 'shots': received['shots'],
                'objects': [{'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id},
                            *received['objects']]})
        except (ValidationError, KeyError) as exc:
            raise BlenderDomainError('blenderErr_shotOutOfRange') from exc
        if into_current:
            record.update(warnings=result.get('warnings', []), latest_blend=str(attempt.relative_to(folder) / 'scene.blend'))
            write_record(folder, record)
            return {**summary(record), 'content': content.model_dump(mode='json')}
        # **建行归场景域**(ADR-0003),这里只描述要建什么。模型已经在这个工作区里了。
        received = create_scene(db, scene.workspace_id, record['snapshot']['name'] + ' · Blender', content)
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
            exported = folder / 'model.glb'
            if not exported.is_file():
                raise BlenderUnavailable('blenderErr_noExport')
            validate_model_file(exported)
            with exported.open('rb') as stream:
                model_id = import_model(db, workspace_id, 'Blender model', stream,
                                        declared_size=exported.stat().st_size).id
            # 从默认内容长出来:它自带一台机位和一个指着它的镜头,而镜头没有机位是非法的。
            # 直接给一份只有模型的 objects,等于交出一个引用了不存在机位的场景。
            blank = SceneContent().model_dump(mode='json')
            content = SceneContent.model_validate({**blank, 'objects': [
                *blank['objects'],
                {'id': 'blender-model', 'kind': 'model', 'name': 'Blender 模型', 'model_id': model_id}]})
            scene = create_scene(db, workspace_id, result.get('scene_name') or 'Blender 场景', content)
        finally:
            #: 临时目录用完即删 —— 字节已经拷进场景的模型目录,这里没有第二个读者。
            shutil.rmtree(folder, ignore_errors=True)
        warnings = list(result.get('warnings') or [])
        if result.get('camera_count'):
            warnings.append('Blender 里的 %d 个相机没有一起取回 —— 镜头需要「看向哪里」，'
                            '而这个距离只有从 Mosael 发送过去的相机才带着。请在这里重新设计镜头。'
                            % result['camera_count'])
        return {'scene_id': scene.id, 'name': scene.name, 'warnings': warnings}


def reconcile_orphaned_transfers() -> int:
    """重启把停在 `sending` 的互通记录判成失败。

    `send()` 先写 `status='sending'` 再去跑 Blender,正常路径靠 `finally` 改写成 ready/failed
    —— 进程被杀就写不到。留下来的那份:`receive()` 要求 `status == 'ready'` 所以接不回来,
    而 `history()` 会**永远**把它列在历史里,看起来像一次还在进行的同步。

    这是一份磁盘记录而不是一张表,所以它不在 `domain/restart.py` 那张按表推导的清单上 ——
    但它是同一条规矩的第六处(见那份文件的说明)。扫的是整棵 `blender-bridge/`:
    这一步在**启动时**跑,那时没有任何请求在飞,`sending` 只可能是上一个进程留下的。
    """
    base = Path(settings.data_dir) / 'blender-bridge'
    if not base.exists():
        return 0
    healed = 0
    for path in base.glob('*/*/*/transfer.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if record.get('status') != 'sending':
            continue
        record.update(status='failed', error=t('blenderErr_interruptedByRestart'))
        try:
            write_record(path.parent, record)
        except OSError:
            continue
        healed += 1
    return healed

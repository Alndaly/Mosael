"""智能体在 Blender 里建模:看结构、看画面、跑建模代码、把做好的东西收进 Mosael 场景。

和按钮那条互通(bridge.send / receive / pull)共用连接校验、互斥锁和 worker —— 区别只在
入口:按钮是用户点的,这里是智能体调的。作用对象都是**用户此刻在 Blender 里开着的那个场景**。

跑代码是 `external` 档:Blender 的 Python 能读写本机文件、能起进程,它不是沙箱。所以它走
确认卡(`blender_execute`),自动放行里有自己独立的一档 —— 放开「在 Blender 里建模」不连带
放开「在电脑上随便跑代码」。看结构、看画面、导出走固定脚本,只读(导出写的是我们自己的临时
目录),不用确认。
"""

from __future__ import annotations

import base64
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.db.models import PluginInstance
from app.domain.blender import bridge
from app.domain.blender.bridge import BlenderConflict, BlenderDomainError, BlenderNotFound, BlenderUnavailable

#: 与 worker.LOOK_VIEWS 同一组名字,外加 `camera`(Blender 场景里的活动相机)。
LOOK_VIEWS = ("overview", "front", "side", "back", "top", "camera")
LOOK_SHADINGS = ("solid", "rendered")
#: 和 view_scene 同一个上限:每张图都进模型上下文。
LOOK_LIMIT = 4


def resolve(db, user, instance_id: str = ""):
    """这次用哪个 Blender 连接。没指定就用他自己的第一个**可用**连接 —— 多数人只有一个。"""
    if instance_id:
        return bridge.connection(db, user, instance_id)
    rows = db.scalars(select(PluginInstance).where(
        PluginInstance.owner_user_id == user.id, PluginInstance.package_id == bridge.PACKAGE,
        PluginInstance.enabled.is_(True))).all()
    if not rows:
        raise BlenderNotFound('还没有连接 Blender:在插件页安装并启用「Blender MCP」,并在 Blender 里开启 MCP Add-on。')
    reasons = []
    for row in rows:
        try:
            return bridge.connection(db, user, row.id)
        except BlenderDomainError as exc:
            reasons.append(str(exc))
    raise BlenderConflict(reasons[0])


@contextmanager
def _workspace_folder(workspace_id: str):
    """一次调用的临时目录。用完即删:图片读成 base64、GLB 拷进模型目录之后,文件没有第二个读者。"""
    folder = Path(settings.data_dir) / 'blender-bridge' / workspace_id / '_agent' / str(uuid4())
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(db, instance, operation: str, payload: dict, workspace_id: str, folder: Path) -> dict:
    with bridge.exclusive(instance.id):
        return bridge.execute(db, instance, operation, {**payload, 'result_path': str(folder / 'result.json')},
                              workspace_id)


def inspect(db, user, workspace_id: str, instance_id: str = '') -> dict:
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        return _run(db, instance, 'inspect', {}, workspace_id, folder)


def look(db, user, workspace_id: str, *, views: list[str], objects: list[str] | None = None,
         shading: str = 'solid', instance_id: str = '') -> dict:
    wanted = list(dict.fromkeys(views or ['overview']))[:LOOK_LIMIT]
    unknown = [one for one in wanted if one not in LOOK_VIEWS]
    if unknown:
        raise BlenderDomainError(f"不认识的视角 {', '.join(unknown)};可选 {'、'.join(LOOK_VIEWS)}")
    if shading not in LOOK_SHADINGS:
        raise BlenderDomainError(f"shading 只能是 {' 或 '.join(LOOK_SHADINGS)}")
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        result = _run(db, instance, 'look', {'views': wanted, 'objects': objects or [], 'shading': shading,
                                             'folder': str(folder)}, workspace_id, folder)
        images = []
        for one in result.get('images', []):
            path = Path(one['path'])
            # 只读我们自己给的那个目录里的文件 —— 路径是 Blender 那边回传的,不能照单全收。
            if not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():
                raise BlenderUnavailable('Blender 没有渲出画面,请检查 Add-on 连接后重试。')
            images.append({'view': one['view'], 'mime_type': 'image/jpeg',
                           'data': base64.b64encode(path.read_bytes()).decode()})
    return {'scene_name': result.get('scene_name'), 'shading': shading, 'warnings': result.get('warnings', []),
            'images': images}


def execute(db, user, workspace_id: str, code: str, instance_id: str = '') -> dict:
    """跑建模代码。**只由确认卡调用**(confirmable/external.py 的 blender_execute)。

    代码自己的错误(traceback)不算「Blender 出了问题」:照原样交回去,由模型改了再试。
    """
    if not code.strip():
        raise BlenderDomainError('没有要执行的代码')
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        return _run(db, instance, 'execute', {'code': code}, workspace_id, folder)


def import_to_scene(db, user, scene, *, base_revision: int, name: str = '', objects: list[str] | None = None,
                    position: list[float] | None = None, instance_id: str = '') -> dict:
    """把 Blender 里做好的东西(整个场景,或按名字挑的几个物体)作为**一个模型物体**加进 Mosael 场景。

    先比修订再导出:场景已经被别人改过的话,不必让 Blender 白导一趟。写入仍走 save_scene 的
    CAS —— 两次检查之间被改了,那一次照样冲突,模型文件留在场景目录里等下一次引用。
    """
    from app.domain.scenes import apply_scene_operations, import_model

    if base_revision != scene.revision:
        raise BlenderConflict(f'场景已更新到修订 {scene.revision},请先 get_scene 再导入。')
    instance = resolve(db, user, instance_id)
    with _workspace_folder(scene.workspace_id) as folder:
        output = folder / 'model.glb'
        result = _run(db, instance, 'export', {'objects': objects or [], 'output_path': str(output)},
                      scene.workspace_id, folder)
        if not output.is_file():
            raise BlenderUnavailable('Blender 没有导出可用的模型,请重试。')
        label = (name or result.get('scene_name') or 'Blender 模型').strip()[:160]
        with output.open('rb') as stream:
            model = import_model(db, scene, label, stream, declared_size=output.stat().st_size)
    object_id = f'blender-{uuid4().hex[:10]}'
    entry = {'id': object_id, 'kind': 'model', 'name': label, 'model_id': model.id}
    if position is not None:
        entry['position'] = position
    saved = apply_scene_operations(db, scene, base_revision, [entry], [], None, None)
    return {'object_id': object_id, 'model_id': model.id, 'revision': saved.revision,
            'warnings': result.get('warnings', [])}

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
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.domain.blender import bridge
from app.domain.blender.bridge import BlenderConflict, BlenderDomainError, BlenderUnavailable, render_warnings

#: 能从哪些角度看 Blender 里的东西 —— **只此一处**,角度随调用一起发给 worker。
#: 值是 (方位角, 仰角),度:方位 0 = 从 -Y 看过去,和 Blender 的「前视图」(小键盘 1)一致;
#: 90 = 从 +X 看,即「右视图」。顶视不取 90°:相机上方向是 +Y,正对下方时退化。
#: `camera` 是个例外 —— 它用 Blender 场景自己的活动相机,没有角度。
LOOK_VIEWS: dict[str, tuple[float, float] | None] = {
    "overview": (35, 30), "front": (0, 5), "side": (90, 5), "back": (180, 5), "top": (0, 89),
    "camera": None,
}
#: 预设之外还能写 `"<方位角>/<仰角>"`(度)。六个固定机位够看整体摆位,**不够看细节**:
#: 一个铰链、一处接缝、两件东西之间的缝隙,往往正好躲在这六个方向的正面或侧面里 ——
#: 而"换个角度再看一眼"正是建模时最常做的动作。
ANGLE_VIEW = re.compile(r"^(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)$")
#: `xray` 是**看穿**:两件东西是不是真的穿在一起、内部有没有多出来的几何,实体着色下全被表面
#: 盖住。此前想给的是线框,实测 Workbench 的线框只在视口里有,F12 渲出来是空背景 ——
#: 而空图和"没建出来"长得一模一样,这种回答比没有更坏。
LOOK_SHADINGS = ("solid", "xray", "rendered")
#: 取景倍数:>1 更近,<1 更远。1 是把选中的东西整个装进画面。
#: 上限 8 —— 再近就只剩几个像素的三角形,看不出任何东西。
ZOOM_RANGE = (0.2, 8.0)
#: 和 view_scene 同一个上限:每张图都进模型上下文。
LOOK_LIMIT = 4


def _angles(name: str) -> tuple[float, float]:
    """一个视角条目 → (方位角, 仰角)。预设名,或 `"<az>/<el>"`。"""
    if name in LOOK_VIEWS:
        return LOOK_VIEWS[name] or (0.0, 0.0)
    matched = ANGLE_VIEW.match(name.strip())
    if matched is None:
        raise BlenderDomainError("blenderErr_unknownView", name=name, choices="、".join(LOOK_VIEWS))
    elevation = float(matched.group(2))
    if not -89 <= elevation <= 89:
        # ±90° 时相机的上方向退化(正对下方看时"哪边是上"没有定义),画面会莫名其妙地转。
        raise BlenderDomainError("blenderErr_elevationRange", value=elevation)
    return float(matched.group(1)), elevation


#: 用哪个连接的判断和按钮那条路是同一份(bridge.resolve):智能体不传 instance_id,取第一个可用的。
resolve = bridge.resolve


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
    """智能体这条路用**更短**的那个预算 —— 上面站着 MCP 客户端的 180 秒(见 bridge 里的说明)。"""
    with bridge.exclusive(instance.id):
        return bridge.execute(db, instance, operation, {**payload, 'result_path': str(folder / 'result.json')},
                              workspace_id, bridge.BLENDER_AGENT_TIMEOUT_SECONDS)


def inspect(db, user, workspace_id: str, instance_id: str = '') -> dict:
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        return _run(db, instance, 'inspect', {}, workspace_id, folder)


def look(db, user, workspace_id: str, *, views: list[str], objects: list[str] | None = None,
         shading: str = 'solid', zoom: float = 1.0, instance_id: str = '') -> dict:
    wanted = list(dict.fromkeys(views or ['overview']))[:LOOK_LIMIT]
    angles = [_angles(name) for name in wanted]   # 不认识的在这里就报出来,不白跑一趟 Blender
    if shading not in LOOK_SHADINGS:
        raise BlenderDomainError("blenderErr_shadingChoice", choices=" / ".join(LOOK_SHADINGS))
    low, high = ZOOM_RANGE
    if not low <= zoom <= high:
        raise BlenderDomainError("blenderErr_zoomRange", low=low, high=high, value=zoom)
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        views = [{'name': name, 'azimuth': angle[0], 'elevation': angle[1]}
                 for name, angle in zip(wanted, angles)]
        result = _run(db, instance, 'look', {'views': views, 'objects': objects or [], 'shading': shading,
                                             'zoom': zoom, 'folder': str(folder)}, workspace_id, folder)
        images = []
        for one in result.get('images', []):
            path = Path(one['path'])
            # 只读我们自己给的那个目录里的文件 —— 路径是 Blender 那边回传的,不能照单全收。
            if not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():
                raise BlenderUnavailable('blenderErr_noRender')
            images.append({'view': one['view'], 'mime_type': 'image/jpeg',
                           'data': base64.b64encode(path.read_bytes()).decode()})
    return {'scene_name': result.get('scene_name'), 'shading': shading, 'warnings': render_warnings(result.get('warnings')),
            'images': images}


def execute(db, user, workspace_id: str, code: str, instance_id: str = '') -> dict:
    """跑建模代码。**只由确认卡调用**(confirmable/external.py 的 blender_execute)。

    代码自己的错误(traceback)不算「Blender 出了问题」:照原样交回去,由模型改了再试。
    """
    if not code.strip():
        raise BlenderDomainError('blenderErr_noCode')
    instance = resolve(db, user, instance_id)
    with _workspace_folder(workspace_id) as folder:
        return _run(db, instance, 'execute', {'code': code}, workspace_id, folder)


def import_to_scene(db, user, scene, *, base_revision: int, name: str = '', objects: list[str] | None = None,
                    position: list[float] | None = None, instance_id: str = '') -> dict:
    """把 Blender 里做好的东西(整个场景,或按名字挑的几个物体)作为**一个模型物体**加进 Mosael 场景。

    先比修订再导出:场景已经被别人改过的话,不必让 Blender 白导一趟。写入仍走 save_scene 的
    CAS —— 两次检查之间被改了,那一次照样冲突,而模型已经在这个工作区里了(它归工作区,不归
    场景),下一次直接摆上去就行,不必再导一遍。
    """
    from app.domain.scenes import apply_scene_operations, import_model

    if base_revision != scene.revision:
        raise BlenderConflict('blenderErr_staleRevision', revision=scene.revision)
    instance = resolve(db, user, instance_id)
    with _workspace_folder(scene.workspace_id) as folder:
        output = folder / 'model.glb'
        result = _run(db, instance, 'export', {'objects': objects or [], 'output_path': str(output)},
                      scene.workspace_id, folder)
        if not output.is_file():
            raise BlenderUnavailable('blenderErr_noExport')
        label = (name or result.get('scene_name') or 'Blender 模型').strip()[:160]
        with output.open('rb') as stream:
            model = import_model(db, scene.workspace_id, label, stream, declared_size=output.stat().st_size)
    object_id = f'blender-{uuid4().hex[:10]}'
    entry = {'id': object_id, 'kind': 'model', 'name': label, 'model_id': model.id}
    if position is not None:
        entry['position'] = position
    saved = apply_scene_operations(db, scene, base_revision, [entry], [], None, None)
    return {'object_id': object_id, 'model_id': model.id, 'revision': saved.revision,
            'warnings': render_warnings(result.get('warnings'))}

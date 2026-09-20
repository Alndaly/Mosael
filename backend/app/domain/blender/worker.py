"""Executed inside Blender by the MCP execute_blender_code tool."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector


def axis(v):
    return Vector((v[0], -v[2], v[1]))


def inverse_axis(v):
    return [v[0], v[2], -v[1]]


def sample(shot, t):
    frames = shot['frames']
    if t <= frames[0]['time']:
        first = frames[0]
        return first['position'], first['target'], first['fov']
    for a, b in zip(frames, frames[1:]):
        if t < b['time']:
            u = (t-a['time'])/(b['time']-a['time'])
            if shot['easing'] == 'smooth':
                u = u*u*(3-2*u)
            # `u` 在默认值上绑死:lambda 捕获循环变量,这里虽然当场就用、行为是对的,
            # 但那正是 late binding 出错的形状,写死绑定省得下次有人把它挪出循环。
            mix = lambda x, y, u=u: [v+(y[i]-v)*u for i, v in enumerate(x)]  # noqa: E731
            return mix(a['position'], b['position']), mix(a['target'], b['target']), a['fov']+(b['fov']-a['fov'])*u
    a = frames[-1]
    return a['position'], a['target'], a['fov']


def dimensions(scene, aspect):
    scene.render.resolution_x, scene.render.resolution_y = {'16:9': (1280, 720), '9:16': (720, 1280), '1:1': (1280, 1280)}[aspect]
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1


def add_camera(scene, shot):
    data = bpy.data.cameras.new(shot['name'])
    camera = bpy.data.objects.new(shot['name'], data)
    scene.collection.objects.link(camera)
    camera['mosael_shot_id'] = shot['id']
    camera['mosael_shot'] = json.dumps(shot)
    camera.rotation_mode = 'QUATERNION'
    data.sensor_fit = 'VERTICAL'
    data.sensor_height = 24
    # Integer video frames plus the exact endpoint; the endpoint is not an extra output frame.
    times = sorted(set([i/30 for i in range(math.ceil(shot['duration']*30))] + [shot['duration']]))
    for t in times:
        p, target, fov = sample(shot, t)
        p, target = axis(p), axis(target)
        camera.location = p
        camera.rotation_quaternion = (target-p).to_track_quat('-Z', 'Y')
        camera['mosael_target_distance'] = (target-p).length
        data.lens = 24/(2*math.tan(math.radians(fov)/2))
        f = t*30+1
        for field in ('location', 'rotation_quaternion', '["mosael_target_distance"]'):
            camera.keyframe_insert(data_path=field, frame=f)
        data.keyframe_insert(data_path='lens', frame=f)
    return camera


def export_glb(path, **overrides):
    """导出 GLB。**材质导不出来时退到只导几何体,而不是整趟失败。**

    Blender 自带的 glTF 导出器会在某些材质上抛断言:`io/com/gltf2_io.py` 的 `from_union`
    逐个试候选序列化器,全失败就 `assert False` —— 错误里看不出是哪个材质、哪个字段。
    而 `exporter.glTF.to_dict()` 在导出流程里是**无条件**跑的,所以这份场景用 Blender 自带的
    File → Export → glTF 同样会失败:不是我们传的参数不对,是那份材质导不出去。

    我们修不了它,但可以不让它变成一句"502"。几何体本身通常是好的 —— 第二次尝试关掉材质,
    把模型拿到手,再明说材质没跟过来。**只在这一层降级,不在别处**:降级过一次就要出一条
    警告,悄悄少东西比报错更难查。
    """
    options = dict(filepath=path, export_format='GLB', use_active_scene=True,
                   export_apply=True, export_animations=False, export_cameras=False,
                   export_lights=True, export_extras=True)
    options.update(overrides)
    try:
        bpy.ops.export_scene.gltf(**options)
        return []
    except Exception as exc:
        reason = str(exc).strip().splitlines()[-1][:160] if str(exc).strip() else exc.__class__.__name__
    options.update(export_materials='NONE', export_extras=False)
    bpy.ops.export_scene.gltf(**options)
    return ['Blender 的 glTF 导出器在这个场景的材质上失败了，已只导出几何体。'
            '材质请在 Mosael 里重新指定，或用 .blend 保留原始设置。（' + reason + '）']


def attach_models(scene, models):
    """把导入的模型文件各自导进来,挂到生成的 GLB 里给它留的那个空节点下。

    模型不打包进场景那一份 GLB(后端不解别人的压缩网格),所以这里补上:按 `mosael_object_id`
    找到锚点,导入文件,把新出现的根物体认作它的孩子 —— 姿态因此来自锚点,和 Mosael 里一致。
    """
    warnings = []
    anchors = {o.get('mosael_object_id'): o for o in scene.objects if o.get('mosael_object_id')}
    for entry in models:
        anchor = anchors.get(entry['object_id'])
        if anchor is None:
            warnings.append('模型「' + entry['name'] + '」没有找到对应的位置，已跳过。')
            continue
        before = set(scene.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=entry['path'])
        except Exception as exc:
            warnings.append('模型「' + entry['name'] + '」导入失败：' + str(exc).strip().splitlines()[-1][:160])
            continue
        for obj in [o for o in scene.objects if o not in before]:
            if obj.parent is None:
                obj.parent = anchor
    return warnings


def send(payload):
    snapshot = payload['snapshot']
    old = bpy.context.window.scene
    scene = bpy.data.scenes.new('Mosael · '+snapshot['name'])
    scene['mosael_transfer_id'] = payload['transfer_id']
    scene['mosael_source_id'] = snapshot['id']
    bpy.context.window.scene = scene
    try:
        bpy.ops.import_scene.gltf(filepath=payload['input_path'])
        warnings = attach_models(scene, payload.get('models') or [])
        scene.render.fps = 30
        scene.render.fps_base = 1
        scene.world = bpy.data.worlds.new(scene.name)
        scene.world.use_nodes = True
        bg = snapshot['content']['background'].lstrip('#')
        scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = tuple(int(bg[i:i+2], 16)/255 for i in (0, 2, 4))+(1,)
        scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = snapshot['content']['ambient']
        cameras = [add_camera(scene, s) for s in snapshot['content']['shots']]
        scene.camera = next((c for c in cameras if c['mosael_shot_id'] == payload['shot_id']), cameras[0])
        selected_shot = json.loads(scene.camera['mosael_shot'])
        dimensions(scene, selected_shot['aspect'])
        scene.frame_start = 1
        scene.frame_end = max(1, math.ceil(selected_shot['duration']*30))
        scene.frame_set(1)
        bpy.data.libraries.write(payload['blend_path'], {scene}, fake_user=True)
        return {'scene_name': scene.name, 'object_count': len(scene.objects), 'camera_count': len(cameras),
                'warnings': warnings, 'blender_version': bpy.app.version_string}
    except Exception:
        bpy.context.window.scene = old
        bpy.data.scenes.remove(scene)
        raise


def receive(payload):
    scene = next((s for s in bpy.data.scenes if s.get('mosael_transfer_id') == payload['transfer_id']), None)
    if scene is None:
        raise ValueError('对应的 Mosael 场景已关闭或移除，请重新发送场景。')
    previous = bpy.context.window.scene
    previous_frame = scene.frame_current
    previous_subframe = scene.frame_subframe
    resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.pixel_aspect_x, scene.render.pixel_aspect_y, scene.render.resolution_percentage)
    bpy.context.window.scene = scene
    warnings, shots = [], []
    try:
        cameras = {c.get('mosael_shot_id'): c for c in scene.objects if c.type == 'CAMERA'}
        for source in payload['shots']:
            camera = cameras.get(source['id'])
            shot = dict(source)
            if camera is None:
                warnings.append('镜头「'+source['name']+'」不存在，保留发送时的镜头。')
                shots.append(shot)
                continue
            dimensions(scene, source['aspect'])
            count = min(100, math.ceil(source['duration']*30)+1)
            frames = []
            for i in range(count):
                t = source['duration']*i/(count-1)
                frame = t*scene.render.fps/scene.render.fps_base+1
                scene.frame_set(int(frame), subframe=frame-int(frame))
                evaluated = camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
                matrix = evaluated.matrix_world
                p = matrix.translation
                rotation = matrix.to_quaternion()
                direction = rotation @ Vector((0, 0, -1))
                expected = direction.to_track_quat('-Z', 'Y')
                if evaluated.data.type != 'PERSP' or abs(rotation.dot(expected)) < .99999:
                    frames = []
                    warnings.append('镜头「'+source['name']+'」使用正交或倾斜视角，保留发送时的镜头。')
                    break
                target = p+direction*max(.01, evaluated.get('mosael_target_distance', 5))
                corners = evaluated.data.view_frame(scene=scene)
                fov = math.degrees(2*math.atan(max(abs(v.y/v.z) for v in corners)))
                frames.append({'time': t, 'position': inverse_axis(p), 'target': inverse_axis(target), 'fov': fov})
            if frames:
                shot['frames'], shot['easing'] = frames, 'linear'
                if count == 100:
                    warnings.append('镜头「'+source['name']+'」已采样为 100 个关键帧，请检查运动。')
            shots.append(shot)
        # Snapshot the geometry at the first frame, without mixing native cameras into the model.
        scene.frame_set(1)
        warnings += export_glb(payload['output_path'])
        bpy.data.libraries.write(payload['blend_path'], {scene}, fake_user=True)
        return {'scene_name': scene.name, 'object_count': len(scene.objects), 'shots': shots, 'warnings': warnings}
    finally:
        scene.render.resolution_x, scene.render.resolution_y, scene.render.pixel_aspect_x, scene.render.pixel_aspect_y, scene.render.resolution_percentage = resolution
        scene.frame_set(previous_frame, subframe=previous_subframe)
        bpy.context.window.scene = previous


def pull(payload):
    """把**当前正在编辑的那个 Blender 场景**整体导出来。

    和 receive 的区别是它不认 `mosael_transfer_id`:没发送过、纯在 Blender 里做出来的场景
    也能取回。代价是相机取不回来 —— Mosael 的镜头要知道"看向哪里",而那是发送时由我们写在
    相机上的 `mosael_target_distance`;换成任意一个 Blender 相机,这个距离无从得知,
    猜一个只会让构图默默错掉。所以这里只取几何体,镜头留给 Mosael 这边重新设计。

    **不切换场景、不写 .blend**:用户此刻正开着这个工程,动他的当前场景是没必要的越界,
    而工程文件就在他自己手上。
    """
    scene = bpy.context.window.scene
    if not any(o.type == 'MESH' for o in scene.objects):
        raise ValueError('当前 Blender 场景里没有网格物体，切换到要导入的场景后重试。')
    # 别人的工程里什么自定义属性都可能有,而我们从不读 GLB 里的 extras —— 不带它进来。
    warnings = export_glb(payload['output_path'], export_extras=False)
    return {'scene_name': scene.name, 'object_count': len(scene.objects),
            'camera_count': sum(1 for o in scene.objects if o.type == 'CAMERA'),
            'warnings': warnings, 'blender_version': bpy.app.version_string}


# ---------------------------------------------------------------------------------------------
# 智能体用的四个操作:看结构、看画面、跑建模代码、把做好的东西导出来。
#
# 都作用在**当前正在编辑的那个 Blender 场景**上 —— 和 pull 一样。用 `bpy.context.scene` 而不是
# `context.window.scene`:MCP Add-on 里两者是同一个,而无界面(--background)时没有 window ——
# 这几个操作因此能在无界面的 Blender 里被测试真跑一遍(tests/test_blender_worker_live.py)。智能体在这里建模,就是在
# 用户眼前这个工程里建;它看到的、导出的,也就是用户此刻看到的那一份。
# ---------------------------------------------------------------------------------------------

#: 超过这么多物体只列前面这些 —— 一个几千物体的工程整份交给模型,读不完也用不上。
INSPECT_LIMIT = 300
#: 视角的角度**随 payload 一起来**(见 blender/agent.py 的 LOOK_VIEWS)——
#: 同一份名字和角度不写两遍:这边是跑在别人 Blender 里的脚本,导不进宿主的模块,
#: 所以由宿主把 (方位角, 仰角) 一起发过来,这里只负责按角度摆相机。
LOOK_SIZE = (960, 540)
LOOK_FOV = 40


def _rounded(values, digits=3):
    return [round(float(v), digits) for v in values]


def inspect(payload):
    scene = bpy.context.scene
    objects = []
    for obj in list(scene.objects)[:INSPECT_LIMIT]:
        entry = {'name': obj.name, 'type': obj.type, 'parent': obj.parent.name if obj.parent else None,
                 'location': _rounded(obj.location), 'rotation_deg': _rounded([math.degrees(v) for v in obj.rotation_euler], 1),
                 'scale': _rounded(obj.scale), 'dimensions': _rounded(obj.dimensions), 'visible': obj.visible_get()}
        if obj.type == 'MESH':
            entry.update(vertices=len(obj.data.vertices), faces=len(obj.data.polygons),
                         modifiers=[m.type for m in obj.modifiers],
                         materials=[slot.material.name for slot in obj.material_slots if slot.material])
        objects.append(entry)
    return {'scene_name': scene.name, 'blender_version': bpy.app.version_string,
            'unit': scene.unit_settings.system, 'unit_scale': scene.unit_settings.scale_length,
            'object_count': len(scene.objects), 'truncated': len(scene.objects) > INSPECT_LIMIT,
            'active_camera': scene.camera.name if scene.camera else None,
            'mosael_source_id': scene.get('mosael_source_id'), 'objects': objects}


def _bounds(scene, names):
    points = []
    for obj in scene.objects:
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'} or not obj.visible_get():
            continue
        if names and obj.name not in names:
            continue
        points += [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    if not points:
        raise ValueError('没有可以取景的可见物体' + ('(按名字没找到:' + '、'.join(names) + ')' if names else ''))
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    return (low + high) / 2, max((high - low).length / 2, 0.1)


def _engine(shading):
    if shading == 'solid':
        return 'BLENDER_WORKBENCH'
    engines = bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys()
    return 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'


def look(payload):
    """渲几张图给智能体看。**临时**改渲染设置、加一台临时相机,渲完全部还原 —— 用户的工程不留痕。"""
    scene = bpy.context.scene
    names = payload.get('objects') or []
    center, radius = _bounds(scene, names)
    render, shading = scene.render, scene.display.shading
    saved = (render.engine, scene.camera, render.resolution_x, render.resolution_y, render.resolution_percentage,
             render.filepath, render.image_settings.file_format, render.film_transparent,
             shading.light, shading.color_type, shading.show_cavity)
    #: 实体模式用一块中性灰做背景:没有 World 时 Workbench 渲出来是纯黑,深色物体直接融进去。
    #: 材质预览模式不换 —— 那时 World 就是光照的一部分。
    world = scene.world
    backdrop = bpy.data.worlds.new('mosael-look') if payload.get('shading', 'solid') == 'solid' else None
    if backdrop is not None:
        backdrop.color = (0.3, 0.32, 0.35)
        scene.world = backdrop
    data = bpy.data.cameras.new('mosael-look')
    camera = bpy.data.objects.new('mosael-look', data)
    scene.collection.objects.link(camera)
    images, warnings = [], []
    try:
        render.engine = _engine(payload.get('shading', 'solid'))
        render.resolution_x, render.resolution_y = LOOK_SIZE
        render.resolution_percentage = 100
        render.image_settings.file_format = 'JPEG'
        render.film_transparent = False
        shading.light, shading.color_type, shading.show_cavity = 'STUDIO', 'MATERIAL', True
        if render.engine != 'BLENDER_WORKBENCH' and hasattr(scene, 'eevee'):
            scene.eevee.taa_render_samples = 16
        data.sensor_fit = 'VERTICAL'
        data.angle = math.radians(LOOK_FOV)
        for index, view in enumerate(payload['views']):
            name = view['name']
            if name == 'camera':
                if saved[1] is None:
                    warnings.append('场景里没有活动相机,跳过 camera 视角。')
                    continue
                scene.camera = saved[1]
            else:
                azimuth, elevation = (math.radians(v) for v in (view['azimuth'], view['elevation']))
                direction = Vector((math.sin(azimuth) * math.cos(elevation), -math.cos(azimuth) * math.cos(elevation), math.sin(elevation)))
                # 包围球比包围盒松得多(一块大地面就能把球撑大一圈),按球算再乘 0.7 才不至于把
                # 东西缩在画面中间一小块 —— 立面视角下也不会切边,见 test_blender_worker_live。
                distance = radius / math.sin(math.radians(LOOK_FOV) / 2) * 0.7
                camera.location = center + direction * distance
                camera.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
                data.clip_start, data.clip_end = max(0.001, distance * 0.01), distance * 4
                scene.camera = camera
            path = str(Path(payload['folder']) / ('%d-%s.jpg' % (index, name)))
            render.filepath = path
            bpy.ops.render.render(write_still=True)
            images.append({'view': name, 'path': path})
    finally:
        (render.engine, scene.camera, render.resolution_x, render.resolution_y, render.resolution_percentage,
         render.filepath, render.image_settings.file_format, render.film_transparent,
         shading.light, shading.color_type, shading.show_cavity) = saved
        bpy.data.objects.remove(camera)
        bpy.data.cameras.remove(data)
        if backdrop is not None:
            scene.world = world
            bpy.data.worlds.remove(backdrop)
    return {'scene_name': scene.name, 'images': images, 'warnings': warnings}


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)[:2000]


def execute(payload):
    """跑智能体写的建模代码。先压一个撤销点:用户在 Blender 里按 ⌘Z 就能退回去。

    出错不抛:把 traceback 交回去,模型据此改代码再试 —— 抛出去的话,上游只剩一句
    "Blender 未完成同步",模型不知道是第几行、什么错。
    """
    import contextlib
    import io
    import traceback

    try:
        bpy.ops.ed.undo_push(message='Mosael 智能体建模')
    except Exception:
        pass
    scope = {'bpy': bpy, 'Vector': Vector, 'math': math}
    printed = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(payload['code'], '<agent>', 'exec'), scope)
    except Exception:
        error = traceback.format_exc(limit=6)
    return {'error': error, 'printed': printed.getvalue()[-20000:], 'output': _jsonable(scope.get('output')),
            'scene_name': bpy.context.scene.name, 'object_count': len(bpy.context.scene.objects)}


def export(payload):
    """把当前场景(或按名字挑出来的那几个物体,连同它们的子物体)导成 GLB。选择状态原样还原。"""
    scene = bpy.context.scene
    names = set(payload.get('objects') or [])
    if not names:
        if not any(o.type == 'MESH' for o in scene.objects):
            raise ValueError('当前 Blender 场景里没有网格物体。')
        warnings = export_glb(payload['output_path'], export_extras=False)
        return {'scene_name': scene.name, 'object_count': len(scene.objects), 'warnings': warnings}
    picked = [o for o in scene.objects if o.name in names]
    missing = names - {o.name for o in picked}
    if missing:
        raise ValueError('Blender 场景里没有这些物体:' + '、'.join(sorted(missing)))
    for obj in list(picked):
        picked += [child for child in obj.children_recursive if child not in picked]
    previous = [o for o in scene.objects if o.select_get()]
    active = bpy.context.view_layer.objects.active
    try:
        for obj in scene.objects:
            obj.select_set(obj in picked)
        warnings = export_glb(payload['output_path'], export_extras=False, use_selection=True)
    finally:
        for obj in scene.objects:
            obj.select_set(obj in previous)
        bpy.context.view_layer.objects.active = active
    return {'scene_name': scene.name, 'object_count': len(picked), 'warnings': warnings}


def run(operation, payload):
    value = {'send': send, 'receive': receive, 'pull': pull, 'inspect': inspect, 'look': look,
             'execute': execute, 'export': export}[operation](payload)
    Path(payload['result_path']).write_text(json.dumps(value), encoding='utf-8')
    print('MOSAEL_BRIDGE_COMPLETE')

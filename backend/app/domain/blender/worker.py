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


# ---------------------------------------------------------------------------------------------
# 原生相机 → Mosael 机位。
#
# Mosael 的机位是 position + target + 垂直 fov,上方向永远是世界上方。一台 Blender 相机的
# **画面**只由位置、朝向和视角决定 —— target 离相机多远并不改变这一帧拍到什么,它只决定两件事:
# 编辑器里绕着转的那个支点,以及两个关键帧之间视线怎么插值。所以"距离从哪来"不是能不能取回
# 的问题,而是取一个讲得通的支点:按下面 `look_candidates` 的顺序,第一个站得住的就用。
#
# 下面几个纯函数不碰 bpy,单测直接喂数(tests/test_blender_worker_export.py)。
# ---------------------------------------------------------------------------------------------

#: 支点离相机至少这么远:再近,轨道控制一拖就翻到相机背后去。
LOOK_MIN = 0.1
#: 支点最远:射线打到一块几公里外的天空球时,支点跟过去没有意义(坐标也会超出场景范围)。
LOOK_MAX = 1000.0
#: 什么都推不出来时(看向空处、场景在身后):和 receive 缺属性时的默认值一样。
LOOK_DEFAULT = 5.0
#: 机位的滚转容差。receive 的判据是四元数点积 ≥ .99999,折成角度约 0.5°,这里取同一个量级。
ROLL_TOLERANCE_DEGREES = 0.5
#: 视线和竖直方向的夹角余弦超过它就算"正对上下方" —— 与白模渲染器 raster.look_at 换参考轴的阈值一致:
#: 那一段里 Mosael 的上方向本身就不再是世界上方,转过去的画面会绕视线转一个任意角度。
VERTICAL_LIMIT = .999
#: Mosael 的画幅(宽/高)。
ASPECTS = {'16:9': 16/9, '9:16': 9/16, '1:1': 1.0}
#: 一个镜头最多多少个关键帧、多长 —— 与 SceneObject.track 和 SceneShot.duration 的上限一致。
SAMPLE_LIMIT = 100
SHOT_LIMIT_SECONDS = 120.0


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _unit(v):
    length = math.sqrt(_dot(v, v))
    return [x/length for x in v] if length > 1e-9 else None


def nearest_aspect(ratio):
    """Blender 输出尺寸(宽/高)最接近的 Mosael 画幅。按比值的对数比,9:16 和 16:9 才对称。"""
    return min(ASPECTS, key=lambda name: abs(math.log(ASPECTS[name]/ratio)))


def vertical_fov(lens, sensor_width, sensor_height, sensor_fit, aspect):
    """Blender 相机在宽高比 `aspect` 的画面上的**垂直**视角(度)。Mosael 和 three.js 的 fov 都是垂直的。

    传感器怎么贴到画面上,和 Blender 自己的规则一致(BKE_camera_sensor_fit):AUTO 把
    sensor_width 贴在较长的那条边上,HORIZONTAL 贴在宽上,VERTICAL 用 sensor_height 贴在高上。
    """
    if sensor_fit == 'VERTICAL':
        half = sensor_height/2/lens
    elif sensor_fit == 'HORIZONTAL' or aspect >= 1:
        half = sensor_width/2/lens/aspect
    else:
        half = sensor_width/2/lens
    return math.degrees(2*math.atan(half))


def camera_axes(matrix):
    """世界矩阵(行优先 4x4,Blender 坐标)→ (位置, 视线方向, 画面上方向)。相机看向本地 -Z、上是 +Y。"""
    position = [matrix[i][3] for i in range(3)]
    return position, _unit([-matrix[i][2] for i in range(3)]), _unit([matrix[i][1] for i in range(3)])


def upright(forward, up):
    """这台相机能不能写成 Mosael 的 position + target:画面不滚转、也不正对上下方。"""
    if forward is None or up is None or abs(forward[2]) > VERTICAL_LIMIT:
        return False
    right = _unit(_cross(forward, [0, 0, 1]))
    return _dot(_cross(right, forward), up) >= math.cos(math.radians(ROLL_TOLERANCE_DEGREES))


def look_distance(candidates):
    """按优先级排好的候选距离(米,可以是 None)里**第一个**站得住的:有限、不比 LOOK_MIN 近。

    `candidates` 可以是生成器 —— 前面的站住了,后面那些(射线求交)就不必算。
    """
    for value in candidates:
        if value is not None and math.isfinite(value) and value >= LOOK_MIN:
            return min(float(value), LOOK_MAX)
    return LOOK_DEFAULT


def camera_key(time, matrix, distance, fov):
    """一个时刻的 Mosael 机位关键帧;画面有滚转或正对上下方时返回 None(Mosael 表示不了)。"""
    position, forward, up = camera_axes(matrix)
    if not upright(forward, up):
        return None
    target = [p + f*distance for p, f in zip(position, forward)]
    return {'time': round(time, 5), 'position': _rounded(inverse_axis(position), 5),
            'target': _rounded(inverse_axis(target), 5), 'fov': round(fov, 4)}


def settle(keys):
    """整段都没动就是一台固定机位,只留一帧 —— Mosael 里「有没有轨」正好等于「动不动」。"""
    first = keys[0]
    fields = lambda key: key['position'] + key['target'] + [key['fov']]  # noqa: E731
    if all(max(abs(a-b) for a, b in zip(fields(key), fields(first))) < 1e-4 for key in keys[1:]):
        return [{**first, 'time': 0}]
    return keys


def sample_times(frame_start, frame_end, fps):
    """会动的原生相机在哪些时刻采样:(镜头时长, [(秒, 帧号)], 是否截短)。

    与 send / receive 同一个约定:时长覆盖 frame_start..frame_end 的每一个输出帧,终点那一刻
    (frame_end + 1)也采 —— 它不是多出来的一帧,而是最后一帧和它之间的插值要用到它。
    超过 SAMPLE_LIMIT 个时刻就均匀取 SAMPLE_LIMIT 个;超过 SHOT_LIMIT_SECONDS 就只取前面那一段。
    """
    duration = (frame_end - frame_start + 1)/fps
    truncated = duration > SHOT_LIMIT_SECONDS
    duration = min(duration, SHOT_LIMIT_SECONDS)
    count = max(2, min(SAMPLE_LIMIT, round(duration*fps) + 1))
    return duration, [(duration*i/(count-1), frame_start + duration*i/(count-1)*fps) for i in range(count)], truncated


def _may_move(obj):
    """它(或它的某个父级)有没有可能随时间动:带动画、驱动器或约束。只是个"要不要逐帧采样"的门槛 ——
    真没动的,采完由 settle 收成一帧。"""
    while obj is not None:
        if obj.animation_data or len(obj.constraints) or (obj.data is not None and getattr(obj.data, 'animation_data', None)):
            return True
        obj = obj.parent
    return False


def look_candidates(scene, depsgraph, camera, position, forward, center):
    """一台原生相机"看向哪里"的候选距离,**越靠前越是用户自己表达过的意图**:

      1. `mosael_target_distance` —— 从 Mosael 发过去的相机自己带着,往返原样;
      2. Track To / Damped Track 约束的目标 —— 用户明说了"看着它";
      3. 景深的对焦物体,再是开着景深时的对焦距离 —— 用户说了"焦点在那";
      4. 沿视线打一条射线,画面正中第一个挡住视线的表面(从近裁剪面起算:比它近的东西本来就拍不到);
      5. 场景包围盒中心在视线上的投影 —— 构图大致围着它转;
    都站不住就由 look_distance 给默认值。给的是**沿视线的距离**:目标点不在视线上时取投影,
    否则 target 会把镜头拧向别处。
    """
    along = lambda point: _dot([a-b for a, b in zip(point, position)], forward)  # noqa: E731
    yield camera.get('mosael_target_distance')
    for constraint in camera.constraints:
        if constraint.type in ('TRACK_TO', 'DAMPED_TRACK') and not constraint.mute and constraint.target is not None:
            yield along(constraint.target.evaluated_get(depsgraph).matrix_world.translation)
    dof = camera.data.dof
    if dof.focus_object is not None:
        yield along(dof.focus_object.evaluated_get(depsgraph).matrix_world.translation)
    if dof.use_dof:
        yield dof.focus_distance
    start = max(camera.data.clip_start, 0.0)
    hit, location = scene.ray_cast(depsgraph, Vector(position) + Vector(forward)*start, Vector(forward),
                                   distance=max(camera.data.clip_end - start, 0.001))[:2]
    if hit:
        yield along(location)
    if center is not None:
        yield along(center)


def pulled_cameras(scene):
    """当前场景里的相机 → Mosael 机位。返回 ([{name, aspect, frames, duration?}], warnings)。

    活动相机排第一(它成为打开场景时的那个镜头),其余按名字。采样会切帧,完了切回原处。
    """
    cameras = sorted((o for o in scene.objects if o.type == 'CAMERA'), key=lambda o: (o != scene.camera, o.name))
    if not cameras:
        return [], []
    render = scene.render
    aspect = nearest_aspect(render.resolution_x*render.pixel_aspect_x/(render.resolution_y*render.pixel_aspect_y))
    moving = any(_may_move(camera) for camera in cameras)
    if moving:
        duration, samples, truncated = sample_times(scene.frame_start, scene.frame_end, render.fps/render.fps_base)
    else:
        duration, samples, truncated = None, [(0.0, None)], False
    try:
        center = _bounds(scene, [])[0]
    except ValueError:
        center = None
    keys, rejected, warnings = {c.name: [] for c in cameras}, set(), []
    current = (scene.frame_current, scene.frame_subframe)
    try:
        for time, frame in samples:
            if frame is not None:
                scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for camera in cameras:
                if camera.name in rejected:
                    continue
                evaluated = camera.evaluated_get(depsgraph)
                data = evaluated.data
                if data.type != 'PERSP':
                    rejected.add(camera.name)
                    warnings.append('相机「'+camera.name+'」没有取回：它是正交或全景相机，Mosael 只有透视镜头。')
                    continue
                matrix = [list(row) for row in evaluated.matrix_world]
                position, forward, _ = camera_axes(matrix)
                distance = look_distance(look_candidates(scene, depsgraph, evaluated, position, forward, center)) if forward else LOOK_DEFAULT
                fov = vertical_fov(data.lens, data.sensor_width, data.sensor_height, data.sensor_fit, ASPECTS[aspect])
                key = camera_key(time, matrix, distance, fov)
                if key is None:
                    rejected.add(camera.name)
                    warnings.append('相机「'+camera.name+'」没有取回：画面有滚转或正对上下方，Mosael 的镜头始终保持水平。')
                    continue
                keys[camera.name].append(key)
    finally:
        if moving:
            scene.frame_set(current[0], subframe=current[1])
    pulled = []
    for camera in cameras:
        if camera.name in rejected:
            continue
        frames = settle(keys[camera.name])
        entry = {'name': camera.name, 'aspect': aspect, 'frames': frames}
        if len(frames) > 1:
            entry['duration'] = round(duration, 5)
            if len(frames) == SAMPLE_LIMIT:
                warnings.append('镜头「'+camera.name+'」已采样为 100 个关键帧，请检查运动。')
            if truncated:
                warnings.append('镜头「'+camera.name+'」只取了 Blender 时间线的前 120 秒。')
        pulled.append(entry)
    return pulled, warnings


def pulled_lights(scene):
    """当前场景里的灯光,**原样的物理量**:类型、世界位置、光线方向、线性颜色、功率。

    换算成 Mosael 的灯(单位、色温、朝向 → 方位角)在宿主那边做(bridge.native_lights):那边有
    和渲染器同一份的色温曲线,不必在这里再抄一份。这里只做两件和 Blender 自己的 glTF 导出器
    (io_scene_gltf2/blender/exp/lights.py)一致的折算:颜色乘上色温开关给的颜色,功率乘上 2^曝光,
    不归一化的面光再乘面积 —— 那样两边说的"一盏多亮、什么颜色的灯"是同一个东西。
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lights = []
    for obj in sorted((o for o in scene.objects if o.type == 'LIGHT'), key=lambda o: o.name):
        evaluated = obj.evaluated_get(depsgraph)
        data, matrix = evaluated.data, evaluated.matrix_world
        color = list(data.color)[:3]
        if getattr(data, 'use_temperature', False):
            color = [c*t for c, t in zip(color, data.temperature_color)]
        power = data.energy*2**getattr(data, 'exposure', 0.0)
        if data.type == 'AREA' and not getattr(data, 'normalize', True):
            power *= data.area(matrix_world=matrix)
        entry = {'name': obj.name, 'type': data.type, 'position': _rounded(inverse_axis(matrix.translation), 5),
                 'direction': _rounded(inverse_axis(-(matrix.to_3x3() @ Vector((0, 0, 1))).normalized()), 6),
                 'color': _rounded(color, 6), 'power': float(power),
                 'hidden': obj.hide_render or not obj.visible_get()}
        if data.type == 'SPOT':
            entry['spot_size'] = math.degrees(data.spot_size)
        lights.append(entry)
    return lights


def pull(payload):
    """把**当前正在编辑的那个 Blender 场景**整体取出来:几何体成一份 GLB,相机和灯光成 Mosael 的物体。

    和 receive 的区别是它不认 `mosael_transfer_id`:没发送过、纯在 Blender 里做出来的场景
    也能取回。原生相机没有 Mosael 发送时写上的 `mosael_target_distance`,"看向哪里"的距离
    由 look_candidates 按用户表达过的意图推出来 —— 它不改变画面,见上面那段说明。

    灯光**不进 GLB**:它们成了 Mosael 自己的灯,再塞进模型文件,视口会从模型里再点一遍
    (three.js 的 GLTFLoader 会照着 KHR_lights_punctual 建灯),同一盏灯亮两次。

    **不切换场景、不写 .blend**:用户此刻正开着这个工程,动他的当前场景是没必要的越界,
    而工程文件就在他自己手上。采样运镜要逐帧切,切完回到原来那一帧。
    用 `bpy.context.scene`:MCP Add-on 里它就是窗口里那个场景,无界面时也有(测试因此能真跑)。
    """
    scene = bpy.context.scene
    if not any(o.type == 'MESH' for o in scene.objects):
        raise ValueError('当前 Blender 场景里没有网格物体，切换到要导入的场景后重试。')
    lights = pulled_lights(scene)
    # 别人的工程里什么自定义属性都可能有,而我们从不读 GLB 里的 extras —— 不带它进来。
    warnings = export_glb(payload['output_path'], export_extras=False, export_lights=False)
    cameras, camera_warnings = pulled_cameras(scene)
    return {'scene_name': scene.name, 'object_count': len(scene.objects), 'cameras': cameras, 'lights': lights,
            'warnings': warnings + camera_warnings, 'blender_version': bpy.app.version_string}


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
    if shading in ('solid', 'xray'):
        return 'BLENDER_WORKBENCH'
    engines = bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys()
    return 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'


def look(payload):
    """渲几张图给智能体看。**临时**改渲染设置、加一台临时相机,渲完全部还原 —— 用户的工程不留痕。"""
    scene = bpy.context.scene
    names = payload.get('objects') or []
    center, radius = _bounds(scene, names)
    # 取景倍数:>1 靠近。整体摆位看 1 就够,而细节(铰链、接缝、两件东西之间的缝隙)在
    # 整场景取景下只有几个像素 —— 那时它和"没建出来"长得一模一样。
    zoom = float(payload.get('zoom') or 1.0)
    mode = payload.get('shading', 'solid')
    render, shading = scene.render, scene.display.shading
    saved = (render.engine, scene.camera, render.resolution_x, render.resolution_y, render.resolution_percentage,
             render.filepath, render.image_settings.file_format, render.film_transparent,
             shading.light, shading.color_type, shading.show_cavity, shading.show_xray)
    #: 实体模式用一块中性灰做背景:没有 World 时 Workbench 渲出来是纯黑,深色物体直接融进去。
    #: 材质预览模式不换 —— 那时 World 就是光照的一部分。
    world = scene.world
    backdrop = bpy.data.worlds.new('mosael-look') if mode in ('solid', 'xray') else None
    if backdrop is not None:
        backdrop.color = (0.3, 0.32, 0.35)
        scene.world = backdrop
    data = bpy.data.cameras.new('mosael-look')
    camera = bpy.data.objects.new('mosael-look', data)
    scene.collection.objects.link(camera)
    images, warnings = [], []
    try:
        render.engine = _engine(mode)
        render.resolution_x, render.resolution_y = LOOK_SIZE
        render.resolution_percentage = 100
        render.image_settings.file_format = 'JPEG'
        render.film_transparent = False
        shading.light, shading.color_type, shading.show_cavity = 'STUDIO', 'MATERIAL', True
        # 透视:看两件东西是不是真的穿在一起、内部有没有多出来的几何 —— 实体着色下这些全被
        # 表面盖住。**不用线框**:Workbench 的线框是视口着色模式,F12 渲出来是一张空背景
        # (实测 Blender 5.2,设了 wireframe_color_type 也一样),而空图和"没建出来"长得一模一样。
        shading.show_xray = mode == 'xray'
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
                distance = radius / math.sin(math.radians(LOOK_FOV) / 2) * 0.7 / max(zoom, 0.01)
                camera.location = center + direction * distance
                camera.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
                data.clip_start, data.clip_end = max(0.001, distance * 0.01), distance * 4
                scene.camera = camera
            # 文件名只用序号:视角名现在可以是 "125/18" 这种自定义角度,**里面的斜杠会被当成
            # 目录** —— 实测第二张图落进了一个叫 125 的子目录里,而上游按路径找不到它。
            # 回给调用方的 `view` 仍然是原样的名字。
            path = str(Path(payload['folder']) / ('%d.jpg' % index))
            render.filepath = path
            bpy.ops.render.render(write_still=True)
            images.append({'view': name, 'path': path})
    finally:
        (render.engine, scene.camera, render.resolution_x, render.resolution_y, render.resolution_percentage,
         render.filepath, render.image_settings.file_format, render.film_transparent,
         shading.light, shading.color_type, shading.show_cavity, shading.show_xray) = saved
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

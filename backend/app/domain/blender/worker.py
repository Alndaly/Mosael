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


def send(payload):
    snapshot = payload['snapshot']
    old = bpy.context.window.scene
    scene = bpy.data.scenes.new('Mosael · '+snapshot['name'])
    scene['mosael_transfer_id'] = payload['transfer_id']
    scene['mosael_source_id'] = snapshot['id']
    bpy.context.window.scene = scene
    try:
        bpy.ops.import_scene.gltf(filepath=payload['input_path'])
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
        return {'scene_name': scene.name, 'object_count': len(scene.objects), 'camera_count': len(cameras), 'blender_version': bpy.app.version_string}
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
        bpy.ops.export_scene.gltf(filepath=payload['output_path'], export_format='GLB', use_active_scene=True,
                                  export_extras=True, export_cameras=False, export_lights=True,
                                  export_apply=True, export_animations=False)
        bpy.data.libraries.write(payload['blend_path'], {scene}, fake_user=True)
        return {'scene_name': scene.name, 'object_count': len(scene.objects), 'shots': shots, 'warnings': warnings}
    finally:
        scene.render.resolution_x, scene.render.resolution_y, scene.render.pixel_aspect_x, scene.render.pixel_aspect_y, scene.render.resolution_percentage = resolution
        scene.frame_set(previous_frame, subframe=previous_subframe)
        bpy.context.window.scene = previous


def run(operation, payload):
    value = send(payload) if operation == 'send' else receive(payload)
    Path(payload['result_path']).write_text(json.dumps(value), encoding='utf-8')
    print('MOSAEL_BRIDGE_COMPLETE')

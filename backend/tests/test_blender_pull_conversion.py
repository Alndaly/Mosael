"""从 Blender 取回场景时,原生相机和灯光怎么变成 Mosael 的机位、镜头、灯。

换算都是纯函数:相机那一半在 worker.py 里(它要在 Blender 里逐帧跑,取"看向哪里"的距离要射线求交),
用假的 bpy 载进来直接喂数;灯光那一半在 bridge 里(要用渲染器那一份色温曲线)。在真 Blender 里
端到端跑一遍的在 test_blender_worker_live.py。
"""
import math

from app.domain.blender import bridge
from app.domain.scene_render.gltf import LIGHT_UNIT
from app.domain.scene_render.raster import hex_to_linear, sun_direction
from app.domain.scene_types import SceneContent
from tests.test_blender_worker_export import load

worker = load(lambda **options: None)

#: 站在 Blender 的 (0, -10, 2)、水平看向 +Y 的相机(rotation_euler = (90°, 0, 0))。行优先。
LEVEL = [[1, 0, 0, 0], [0, 0, -1, -10], [0, 1, 0, 2], [0, 0, 0, 1]]


def _rolled(degrees):
    """LEVEL 再绕自己的视线滚转 `degrees` 度。"""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    x, y = [c, 0, s], [-s, 0, c]   # 本地 X / Y 在世界里的方向(视线仍是 +Y)
    return [[x[0], y[0], 0, 0], [x[1], y[1], -1, -10], [x[2], y[2], 0, 2], [0, 0, 0, 1]]


# ---- 相机:worker 里的纯函数 ----------------------------------------------------------------

def test_a_level_camera_becomes_position_plus_target_in_mosael_axes():
    key = worker.camera_key(0, LEVEL, 10, 40)
    # Blender (x, y, z) → Mosael (x, z, -y):站在 (0, 2, 10),看向 10 米外的 (0, 2, 0)。
    assert key == {'time': 0, 'position': [0, 2, 10], 'target': [0, 2, 0], 'fov': 40}


def test_cameras_mosael_cannot_hold_level_are_refused():
    assert worker.camera_key(0, _rolled(0.3), 5, 40) is not None, '半度以内的滚转是数值噪声'
    assert worker.camera_key(0, _rolled(10), 5, 40) is None
    straight_down = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 5], [0, 0, 0, 1]]   # Blender 新建相机的默认朝向
    assert worker.camera_key(0, straight_down, 5, 40) is None


def test_vertical_fov_follows_blenders_sensor_fit():
    # Blender 默认相机:50mm、36mm 宽的传感器、AUTO。16:9 的画面上它贴宽边。
    assert round(worker.vertical_fov(50, 36, 24, 'AUTO', 16/9), 3) == round(math.degrees(2*math.atan(18/50/(16/9))), 3)
    # 竖幅时 AUTO 把同一条传感器贴到高上。
    assert round(worker.vertical_fov(50, 36, 24, 'AUTO', 9/16), 3) == round(math.degrees(2*math.atan(18/50)), 3)
    # 发送时写的就是 VERTICAL + 24mm 高:往返得回原来的 fov。
    lens = 24/(2*math.tan(math.radians(45)/2))
    assert abs(worker.vertical_fov(lens, 36, 24, 'VERTICAL', 16/9) - 45) < 1e-9


def test_nearest_aspect_is_symmetric_between_landscape_and_portrait():
    assert worker.nearest_aspect(1920/1080) == '16:9'
    assert worker.nearest_aspect(1080/1920) == '9:16'
    assert worker.nearest_aspect(5/4) == '1:1'
    assert worker.nearest_aspect(2.39) == '16:9'


def test_look_distance_takes_the_first_candidate_that_stands():
    assert worker.look_distance([None, .05, float('nan'), 7.5, 3]) == 7.5
    assert worker.look_distance([]) == worker.LOOK_DEFAULT
    assert worker.look_distance([-3]) == worker.LOOK_DEFAULT, '目标在相机背后不算'
    assert worker.look_distance([50000]) == worker.LOOK_MAX

    def lazy():
        yield 4.0
        raise AssertionError('前一个站住了,后面的射线求交不该再算')
    assert worker.look_distance(lazy()) == 4.0


def test_a_camera_that_never_moved_settles_into_one_key():
    still = worker.camera_key(0, LEVEL, 10, 40)
    assert worker.settle([still, {**still, 'time': 1}, {**still, 'time': 2}]) == [still]
    moved = {**still, 'time': 1, 'position': [0, 2, 9]}
    assert worker.settle([still, moved]) == [still, moved]


def test_sampling_covers_every_output_frame_plus_the_endpoint():
    duration, samples, truncated = worker.sample_times(1, 60, 30)
    assert duration == 2 and len(samples) == 61 and not truncated
    assert samples[0] == (0, 1) and samples[-1] == (2, 61)
    # 长时间线:最多 100 个时刻、最长 120 秒,截短要说出来。
    duration, samples, truncated = worker.sample_times(1, 10000, 24)
    assert duration == 120 and len(samples) == 100 and truncated


# ---- 相机:宿主这边摆成机位 + 镜头 -----------------------------------------------------------

def _key(time, position, target=(0, 1, 0), fov=40):
    return {'time': time, 'position': list(position), 'target': list(target), 'fov': fov}


def test_native_cameras_become_camera_objects_with_shots_named_after_them():
    cameras = [
        {'name': 'Camera', 'aspect': '16:9', 'frames': [_key(0, (4, 3, 8))]},
        {'name': 'Dolly', 'aspect': '16:9', 'duration': 2, 'frames': [_key(0, (0, 2, 8)), _key(2, (0, 2, 4))]},
    ]
    objects, shots, warnings = bridge.native_cameras(cameras)
    assert warnings == []
    assert [o['name'] for o in objects] == [s['name'] for s in shots] == ['Camera', 'Dolly']
    still, dolly = objects
    assert still['position'] == [4, 3, 8] and still['target'] == [0, 1, 0] and still['track'] == []
    assert len(dolly['track']) == 2 and dolly['position'] == [0, 2, 8]
    assert shots[1]['duration'] == 2 and shots[1]['easing'] == 'linear' and 'duration' not in shots[0]
    SceneContent.model_validate({'objects': objects, 'shots': shots})


def test_native_cameras_skip_one_by_one_with_a_reason():
    too_wide = {'name': 'Fisheye', 'aspect': '16:9', 'frames': [_key(0, (4, 3, 8), fov=150)]}
    many = [{'name': 'Cam %d' % i, 'aspect': '16:9', 'frames': [_key(0, (i, 3, 8))]} for i in range(33)]
    objects, shots, warnings = bridge.native_cameras([too_wide, *many])
    assert len(shots) == 32 and objects[0]['name'] == 'Cam 0'
    assert warnings == ['相机「Fisheye」没有取回：位置或视角超出 Mosael 支持的范围。',
                        '相机「Cam 32」没有取回：一个场景最多 32 个镜头。']


# ---- 灯光 --------------------------------------------------------------------------------

def _light(kind, power, **extra):
    return {'name': extra.pop('name', kind.title()), 'type': kind, 'position': [1, 3, 2], 'direction': [0, -1, 0],
            'color': [1, 1, 1], 'power': power, 'hidden': False, **extra}


def test_a_point_light_sent_to_blender_comes_back_the_same():
    """发送:强度 × LIGHT_UNIT 坎德拉 → Blender 的 glTF 导入器按 W = cd × 4π / 683 折成瓦。取回要正好反过来。"""
    watts = 30*LIGHT_UNIT*4*math.pi/683
    color = [float(v) for v in hex_to_linear('#ffcc88')]
    objects, lighting, notes = bridge.native_lights([_light('POINT', watts, color=color)], 10)
    assert notes == [] and lighting is None
    assert objects[0]['intensity'] == 30 and objects[0]['color'] == '#ffcc88' and objects[0]['position'] == [1, 3, 2]
    # Blender 默认那盏 1000 W 的点光,在 Mosael 里和默认的 30 同一个量级。
    assert 50 < bridge.point_intensity(1000) < 60


def test_spot_and_area_lights_come_back_as_points_and_say_what_was_lost():
    objects, _, notes = bridge.native_lights([_light('SPOT', 1000, spot_size=45.0), _light('AREA', 500)], 10)
    assert [o['kind'] for o in objects] == ['light', 'light']
    assert notes == ['聚光灯「Spot」按点光取回：Mosael 没有聚光，45° 的光锥没有带过来。',
                     '面光「Area」按点光取回：Mosael 没有面光，面积和朝向没有带过来。']


def test_a_sun_becomes_the_key_light_with_the_same_direction():
    toward = sun_direction(35, 55)
    sun = _light('SUN', 4, direction=[float(-v) for v in toward])
    objects, lighting, notes = bridge.native_lights([sun], 10)
    assert objects == [] and notes == []
    assert (lighting.azimuth, lighting.elevation) == (35, 55)
    assert lighting.intensity == 2.732 and lighting.preset == 'custom'
    assert lighting.temperature == 6600, '纯白 = 渲染器色温曲线上正好是白的那一档'


def test_sun_approximations_are_spelled_out():
    below = _light('SUN', 40, name='Moon', direction=[0, .5, -.866], color=[0, 1, 0])
    brighter = _light('SUN', 50, name='Noon', direction=[0, -1, 0], hidden=True)
    objects, lighting, notes = bridge.native_lights([below, brighter], 10)
    # 看得见的优先,哪怕另一个更亮。
    assert lighting.elevation == 0 and lighting.intensity == 20
    assert notes[0] == '太阳「Noon」没有取回：Mosael 只有一盏主光，已用「Moon」。'
    assert notes[1].startswith('太阳「Moon」已作为场景主光；光从地平线以下射来')
    assert '强度超出 Mosael 的上限' in notes[1] and '颜色不是色温能表示的' in notes[1]


def test_lights_beyond_the_object_limit_are_named():
    objects, _, notes = bridge.native_lights([_light('POINT', 100, name='A'), _light('POINT', 100, name='B')], 1)
    assert [o['name'] for o in objects] == ['A']
    assert notes == ['灯光「B」没有取回：一个场景最多 500 个物体。']

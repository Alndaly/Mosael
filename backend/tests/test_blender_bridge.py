"""Exchange authorization, immutable imports and the MCP completion contract."""
import json
import struct
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.domain.blender.bridge import BlenderDomainError
from app.domain.scenes import SceneDomainError, model_file


def _model_object(content):
    """接回来的场景里那份 Blender 模型。**不能按下标取** —— 相机现在也是物体,和它同在
    objects 里,谁排第一取决于构造顺序。"""
    return next(o for o in content['objects'] if o['kind'] == 'model')
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.config import settings
from app.db.models import User, PluginPackage, PluginInstance, Scene3D, Scene3DModel
from app.domain.blender import bridge
from app.domain.plugins.manifest import parse
from app.domain.scene_types import SceneContent
from tests.test_scenes import setup_scene

MANIFEST = Path(__file__).resolve().parents[2] / 'plugins/examples/blender/mosael.plugin.json'


def glb():
    data = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}]}).encode()
    data += b' ' * (-len(data) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20+len(data), len(data), 0x4E4F534A)+data


def test_send_projects_camera_tracks_for_the_worker_without_mutating_the_snapshot(monkeypatch, tmp_path):
    _, _, initial = setup_scene()
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    monkeypatch.setattr(bridge, 'resolve', lambda *args, **kw: SimpleNamespace(id='local'))
    def execute(db, instance, operation, payload, workspace_id):
        assert operation == 'send'
        shot = payload['snapshot']['content']['shots'][0]
        assert shot['frames'][0]['target'] == [0, 1, 0]
        assert shot['frames'][0]['fov'] == 45
        return {'scene_name': 'Test'}
    monkeypatch.setattr(bridge, 'execute', execute)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        scene = db.get(Scene3D, initial['id'])
        sent = bridge.send(db, user, scene, 'local', scene.revision, scene.content['shots'][0]['id'])
        _, record = bridge.load(scene, user, sent['id'])
        assert 'frames' not in scene.content['shots'][0]
        assert 'frames' not in record['snapshot']['content']['shots'][0]


def test_blender_projection_resolves_optional_key_fields():
    from app.domain.scene_types import SceneContent
    content = SceneContent().model_dump(mode='json')
    content['objects'][0]['track'] = [{'time': 2, 'position': [3, 2, 5], 'target': [0, 1, 0], 'fov': None}]
    assert bridge.shots_with_frames(content)[0]['frames'][0]['fov'] == 45


def test_manifest_passes_local_connection_config():
    manifest = parse(json.loads(MANIFEST.read_text()), str(MANIFEST.parent))
    fields = {f.key:f for f in manifest.config}
    assert fields['BLENDER_PORT'].type == 'string'
    assert fields['DISABLE_TELEMETRY'].default == 'true'
    assert manifest.runtime.kind == 'mcp'
    assert manifest.multiple
    assert [o['value'] for o in fields['BLENDER_HOST'].options] == ['127.0.0.1', 'localhost']


def test_returned_baked_camera_keys_keep_linear_timing():
    from app.domain.scene_types import SceneContent
    content = SceneContent().model_dump(mode='json')
    flat = bridge.shots_with_frames(content)
    flat[0]['easing'] = 'linear'
    received = bridge.apply_shot_frames(content, flat)
    assert received['shots'][0]['easing'] == 'linear'


def test_mcp_string_wrapper_and_missing_completion(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.tools, 'invoke', lambda *a, **k: SimpleNamespace(status='succeeded', output={'result': '{"objects": [], "name": "Scene"}'}))
    assert bridge.call(None, SimpleNamespace(id='i'), 'get_scene_info', {})['objects'] == []
    with pytest.raises(BlenderDomainError) as error:
        bridge.execute(None, SimpleNamespace(id='i'), 'send', {'result_path':str(tmp_path/'fresh.json')}, 'ws')
    assert error.value.status == 502


def test_connection_requires_local_owner_and_grants(monkeypatch):
    c, ws, scene = setup_scene()
    with SessionLocal() as db:
        user=db.scalar(select(User)); other=SimpleNamespace(id='other')
        db.add(PluginPackage(id=bridge.PACKAGE,name='Blender',version='0.1.0',manifest=json.loads(MANIFEST.read_text())))
        db.flush()
        i=PluginInstance(owner_user_id=user.id,package_id=bridge.PACKAGE,name='Blender',enabled=True,config={})
        db.add(i);db.commit()
        monkeypatch.setattr(settings,'local_desktop',False)
        with pytest.raises(BlenderDomainError) as e: bridge.connection(db,user,i.id)
        assert e.value.status==409
        monkeypatch.setattr(settings,'local_desktop',True)
        with pytest.raises(BlenderDomainError) as e: bridge.connection(db,other,i.id)
        assert e.value.status==404
        with pytest.raises(BlenderDomainError) as e: bridge.connection(db,user,i.id)
        assert e.value.status==409


def test_roundtrip_is_new_scene_and_transfers_are_owner_scoped(monkeypatch, tmp_path):
    c, ws, initial = setup_scene()
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    monkeypatch.setattr(bridge,'connection',lambda *args: SimpleNamespace(id='local'))
    def fake_execute(db, instance, operation, payload, workspace_id):
        Path(payload['blend_path']).write_bytes(b'BLENDER')
        if operation=='send':return {'scene_name':'Mosael Test'}
        Path(payload['output_path']).write_bytes(glb())
        return {'shots':payload['shots'], 'warnings':[]}
    monkeypatch.setattr(bridge,'execute',fake_execute)
    with SessionLocal() as db:
        user=db.scalar(select(User));scene=db.get(Scene3D,initial['id'])
        with pytest.raises(BlenderDomainError) as e:bridge.send(db,user,scene,'local',0,scene.content['shots'][0]['id'])
        assert e.value.status==409
        sent=bridge.send(db,user,scene,'local',scene.revision,scene.content['shots'][0]['id'])
        assert bridge.history(scene,SimpleNamespace(id='other'))==[]
        with pytest.raises(BlenderDomainError) as e:bridge.load(scene,SimpleNamespace(id='other'),sent['id'])
        assert e.value.status==404
        with pytest.raises(BlenderDomainError):bridge.load(scene,user,'../../elsewhere')
        received=bridge.receive(db,user,scene,sent['id'])
        assert received['received_scene_id']!=scene.id
        new=db.get(Scene3D,received['received_scene_id'])
        model=db.get(Scene3DModel,_model_object(new.content)['model_id'])
        assert model.workspace_id==new.workspace_id and model_file(model).read_bytes()==glb()
        assert scene.revision==1 and [o['kind'] for o in scene.content['objects']]==['camera']
        assert [s['id'] for s in new.content['shots']]==[s['id'] for s in initial['content']['shots']]
        assert bridge.history(scene,user)[0]['received_scene_id']==new.id
        before=len(list(db.scalars(select(Scene3D))))
        def invalid(*args):
            result=fake_execute(*args);Path(args[3]['output_path']).write_bytes(b'bad');return result
        monkeypatch.setattr(bridge,'execute',invalid)
        # 坏的 GLB 由**场景域**判(validate_model),不是 Blender 域 —— 从前两边都抛
        # HTTPException,这条断言分不出来。两者边界上都翻成 422,HTTP 行为不变。
        with pytest.raises(SceneDomainError):bridge.receive(db,user,scene,sent['id'])
        assert len(list(db.scalars(select(Scene3D))))==before


@pytest.mark.parametrize('grouped', [False, True])
def test_receive_into_current_imports_the_model_and_hands_content_back(monkeypatch, tmp_path, grouped):
    """接回当前场景时:模型进这个场景的库,内容**交回调用方**,不建新场景、不动库里的内容。

    最后那两条是重点。编辑器手上有一份草稿,这里若顺手把场景内容也写了,那份草稿立刻就是旧的
    —— 它的下一次自动保存要么冲突、要么把刚接回来的东西盖掉。所以这里只做"模型进库",
    内容由编辑器当成一次可撤销的改动写下去(见 bridge.receive 的说明)。
    """
    c, ws, initial = setup_scene()
    if grouped:
        initial['content']['objects'][0]['parent_id'] = 'camera-group'
        initial['content']['objects'].append({'id': 'camera-group', 'kind': 'group'})
        response = c.patch('/api/scenes/' + initial['id'], json={
            'workspace_id': ws, 'name': initial['name'], 'base_revision': initial['revision'],
            'content': initial['content'],
        })
        assert response.status_code == 200, response.text
        initial = response.json()
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    monkeypatch.setattr(bridge,'connection',lambda *args: SimpleNamespace(id='local'))
    def fake_execute(db, instance, operation, payload, workspace_id):
        Path(payload['blend_path']).write_bytes(b'BLENDER')
        if operation=='send':return {'scene_name':'Mosael Test'}
        Path(payload['output_path']).write_bytes(glb())
        return {'shots':payload['shots'], 'warnings':[]}
    monkeypatch.setattr(bridge,'execute',fake_execute)
    with SessionLocal() as db:
        user=db.scalar(select(User));scene=db.get(Scene3D,initial['id'])
        sent=bridge.send(db,user,scene,'local',scene.revision,scene.content['shots'][0]['id'])
        before=len(list(db.scalars(select(Scene3D))))
        received=bridge.receive(db,user,scene,sent['id'],into_current=True)

        assert received['received_scene_id'] is None
        assert len(list(db.scalars(select(Scene3D))))==before      # 没有新场景

        content=received['content']
        model=db.get(Scene3DModel,_model_object(content)['model_id'])
        assert model.workspace_id==scene.workspace_id and model_file(model).read_bytes()==glb()   # 模型归工作区
        assert [s['id'] for s in content['shots']]==[s['id'] for s in initial['content']['shots']]

        db.refresh(scene)
        assert scene.revision == initial['revision'] and scene.content == initial['content']
        assert all(o['parent_id'] is None for o in content['objects'])
        assert bridge.history(scene,user)[0]['received_scene_id'] is None


def test_pull_takes_the_open_blender_scene_without_a_prior_send(monkeypatch, tmp_path):
    """没发送过也能取:pull 走的是「当前打开的那个 Blender 场景」,不认 transfer_id。

    另外钉三件事:原生相机成了机位 + 镜头(取不回的那台有一条带原因的说明)、灯光成了 Mosael 的灯,
    以及那个临时目录**用完即删** —— 它的字节已经进了模型表,留着就是一个没有入口能清理的目录。
    """
    c, ws, initial = setup_scene()
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    monkeypatch.setattr(bridge,'connection',lambda *args: SimpleNamespace(id='local'))
    camera = {'name': 'Camera', 'aspect': '16:9',
              'frames': [{'time': 0, 'position': [7.4, 5, 6.9], 'target': [0, 0, 0], 'fov': 22.9}]}
    light = {'name': 'Light', 'type': 'POINT', 'position': [4.1, 5.9, -1], 'direction': [0, -1, 0],
             'color': [1, 1, 1], 'power': 1000, 'hidden': False}
    def fake_execute(db, instance, operation, payload, workspace_id):
        assert operation=='pull'
        Path(payload['output_path']).write_bytes(glb())
        return {'scene_name':'客厅','object_count':7,'cameras':[camera],'lights':[light],
                'warnings':[{'key': 'blenderWarn_cameraRolled', 'params': {'name': 'Top'}}]}
    monkeypatch.setattr(bridge,'execute',fake_execute)
    with SessionLocal() as db:
        user=db.scalar(select(User))
        before=len(list(db.scalars(select(Scene3D))))
        result=bridge.pull(db,user,ws,'local')

        assert len(list(db.scalars(select(Scene3D))))==before+1
        scene=db.get(Scene3D,result['scene_id'])
        assert scene.name=='客厅' and scene.workspace_id==ws
        model=db.get(Scene3DModel,_model_object(scene.content)['model_id'])
        assert model.workspace_id==scene.workspace_id and model_file(model).read_bytes()==glb()
        assert [(s['name'], s['camera_id']) for s in scene.content['shots']]==[('Camera', 'blender-camera-1')]
        assert [o['kind'] for o in scene.content['objects']]==['camera', 'model', 'light']
        assert result['warnings']==['相机「Top」没有取回：画面有滚转或正对上下方，Mosael 的镜头始终保持水平。']
        assert not list((tmp_path/'blender-bridge'/ws/'_pull').glob('*'))


def test_pull_without_usable_cameras_keeps_the_default_shot(monkeypatch, tmp_path):
    """一台相机都没取回时,默认机位和指着它的镜头留着 —— 镜头没有机位是非法的。"""
    c, ws, initial = setup_scene()
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    monkeypatch.setattr(bridge,'connection',lambda *args: SimpleNamespace(id='local'))
    def fake_execute(db, instance, operation, payload, workspace_id):
        Path(payload['output_path']).write_bytes(glb())
        return {'scene_name':'空镜','cameras':[],'lights':[],'warnings':[]}
    monkeypatch.setattr(bridge,'execute',fake_execute)
    with SessionLocal() as db:
        result=bridge.pull(db,db.scalar(select(User)),ws,'local')
        scene=db.get(Scene3D,result['scene_id'])
        default=SceneContent().model_dump(mode='json')
        assert scene.content['shots']==default['shots'] and scene.content['lighting']==default['lighting']
        assert result['warnings']==[]


def test_send_carries_workspace_models_along(monkeypatch, tmp_path):
    """场景里摆着导入的模型时照样发得出去,模型文件交给 Blender 那边挂上。

    线上:模型早就从「属于场景」迁成了「属于工作区」,这里还在读 `model.scene_id` —— 场景里
    只要有一件导入的道具,发送就抛 AttributeError,界面上看到的是「127.0.0.1:8800 连不上」。
    """
    c, ws, initial = setup_scene()
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    doc = {'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0}
    mid = c.post('/api/scene-models', data={'workspace_id': ws},
                 files={'file': ('prop.gltf', json.dumps(doc).encode(), 'model/gltf+json')}).json()['id']
    content = initial['content']
    content['objects'].append({'id': 'prop', 'kind': 'model', 'model_id': mid, 'name': 'Prop'})
    r = c.patch('/api/scenes/' + initial['id'], json={'workspace_id': ws, 'name': 'Studio', 'base_revision': 1, 'content': content})
    assert r.status_code == 200, r.text
    monkeypatch.setattr(bridge, 'resolve', lambda *args, **kw: SimpleNamespace(id='local'))
    seen = {}
    def execute(db, instance, operation, payload, workspace_id):
        seen['models'] = payload['models']
        return {'scene_name': 'Test'}
    monkeypatch.setattr(bridge, 'execute', execute)
    with SessionLocal() as db:
        user = db.scalar(select(User))
        scene = db.get(Scene3D, initial['id'])
        bridge.send(db, user, scene, 'local', scene.revision, scene.content['shots'][0]['id'])
    assert [m['object_id'] for m in seen['models']] == ['prop']
    assert all(Path(m['path']).is_file() for m in seen['models'])

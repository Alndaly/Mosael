"""Exchange authorization, immutable imports and the MCP completion contract."""
import json
import struct
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.domain.blender.bridge import BlenderDomainError
from app.domain.scenes import SceneDomainError
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.config import settings
from app.db.models import User, PluginPackage, PluginInstance, Scene3D, Scene3DModel
from app.domain.blender import bridge
from app.domain.plugins.manifest import parse
from tests.test_scenes import setup_scene

MANIFEST = Path(__file__).resolve().parents[2] / 'plugins/examples/blender/mosael.plugin.json'


def glb():
    data = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}]}).encode()
    data += b' ' * (-len(data) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20+len(data), len(data), 0x4E4F534A)+data


def test_manifest_passes_local_connection_config():
    manifest = parse(json.loads(MANIFEST.read_text()), str(MANIFEST.parent))
    fields = {f.key:f for f in manifest.config}
    assert fields['BLENDER_PORT'].type == 'string'
    assert fields['DISABLE_TELEMETRY'].default == 'true'
    assert manifest.runtime.kind == 'mcp'
    assert manifest.multiple
    assert [o['value'] for o in fields['BLENDER_HOST'].options] == ['127.0.0.1', 'localhost', '::1']


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
        with pytest.raises(BlenderDomainError) as e:bridge.send(db,user,scene,'local',0,'camera-1',glb())
        assert e.value.status==409
        sent=bridge.send(db,user,scene,'local',scene.revision,'camera-1',glb())
        assert bridge.history(scene,SimpleNamespace(id='other'))==[]
        with pytest.raises(BlenderDomainError) as e:bridge.load(scene,SimpleNamespace(id='other'),sent['id'])
        assert e.value.status==404
        with pytest.raises(BlenderDomainError):bridge.load(scene,user,'../../elsewhere')
        received=bridge.receive(db,user,scene,sent['id'])
        assert received['received_scene_id']!=scene.id
        new=db.get(Scene3D,received['received_scene_id'])
        model=db.get(Scene3DModel,new.content['objects'][0]['model_id'])
        assert model.scene_id==new.id and model.data==glb()
        assert scene.revision==1 and scene.content['objects']==[]
        assert new.content['shots']==initial['content']['shots']
        assert bridge.history(scene,user)[0]['received_scene_id']==new.id
        before=len(list(db.scalars(select(Scene3D))))
        def invalid(*args):
            result=fake_execute(*args);Path(args[3]['output_path']).write_bytes(b'bad');return result
        monkeypatch.setattr(bridge,'execute',invalid)
        # 坏的 GLB 由**场景域**判(validate_model),不是 Blender 域 —— 从前两边都抛
        # HTTPException,这条断言分不出来。两者边界上都翻成 422,HTTP 行为不变。
        with pytest.raises(SceneDomainError):bridge.receive(db,user,scene,sent['id'])
        assert len(list(db.scalars(select(Scene3D))))==before


def test_receive_into_current_imports_the_model_and_hands_content_back(monkeypatch, tmp_path):
    """接回当前场景时:模型进这个场景的库,内容**交回调用方**,不建新场景、不动库里的内容。

    最后那两条是重点。编辑器手上有一份草稿,这里若顺手把场景内容也写了,那份草稿立刻就是旧的
    —— 它的下一次自动保存要么冲突、要么把刚接回来的东西盖掉。所以这里只做"模型进库",
    内容由编辑器当成一次可撤销的改动写下去(见 bridge.receive 的说明)。
    """
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
        sent=bridge.send(db,user,scene,'local',scene.revision,'camera-1',glb())
        before=len(list(db.scalars(select(Scene3D))))
        received=bridge.receive(db,user,scene,sent['id'],into_current=True)

        assert received['received_scene_id'] is None
        assert len(list(db.scalars(select(Scene3D))))==before      # 没有新场景

        content=received['content']
        model=db.get(Scene3DModel,content['objects'][0]['model_id'])
        assert model.scene_id==scene.id and model.data==glb()      # 模型归当前场景
        assert content['shots']==initial['content']['shots']

        db.refresh(scene)
        assert scene.revision==1 and scene.content['objects']==[]   # 库里的内容没被动过
        assert bridge.history(scene,user)[0]['received_scene_id'] is None

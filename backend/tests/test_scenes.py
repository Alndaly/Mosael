import json

import pytest

from tests.util import fresh_client


def setup_scene():
    c = fresh_client()
    ws = c.post('/api/workspaces', json={'name': '3D test'}).json()['id']
    r = c.post('/api/scenes', json={'workspace_id': ws, 'name': 'Studio'})
    assert r.status_code == 200, r.text
    return c, ws, r.json()


def test_scene_revision_conflict_and_immutable_snapshot():
    c, ws, scene = setup_scene()
    payload = {'workspace_id': ws, 'name': 'Room', 'content': scene['content'], 'base_revision': 1}
    payload['content']['objects'] = [{'id': 'room', 'kind': 'room'}]
    r = c.patch('/api/scenes/' + scene['id'], json=payload)
    assert r.status_code == 200, r.text
    assert r.json()['revision'] == 2
    assert c.patch('/api/scenes/' + scene['id'], json=payload).status_code == 409
    old = c.get(f"/api/scenes/{scene['id']}/revisions/1", params={'workspace_id': ws}).json()
    assert old['content']['objects'] == []
    other = c.post('/api/workspaces', json={'name': 'Other'}).json()['id']
    assert c.get('/api/scenes/' + scene['id'], params={'workspace_id': other}).status_code == 404


def test_invalid_scene_hierarchy_camera_and_nonfinite():
    c, ws, scene = setup_scene()
    for objects in [[{'id': 'x', 'kind': 'group', 'parent_id': 'x'}], [{'id': 'x', 'kind': 'box', 'position': [1e99, 0, 0]}], [{'id': 'x', 'kind': 'model'}]]:
        r = c.post('/api/scenes', json={'workspace_id': ws, 'content': {'objects': objects}})
        assert r.status_code == 422, r.text
    r = c.post('/api/scenes', json={'workspace_id': ws, 'content': {'shots': [{'id': 's', 'frames': [{'time': 1}]}]}})
    assert r.status_code == 422, r.text


def test_model_import_is_self_contained_and_scene_scoped():
    c, ws, scene = setup_scene()
    path = f"/api/scenes/{scene['id']}/models"
    def upload(doc):
        return c.post(path, data={'workspace_id': ws}, files={'file': ('model.gltf', json.dumps(doc).encode(), 'model/gltf+json')})
    assert upload({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'https://example.com/model.bin'}]}).status_code == 422
    assert upload({'asset': {'version': '2.0'}, 'images': [{'uri': 'file:///etc/passwd'}]}).status_code == 422
    model = upload({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0})
    assert model.status_code == 200, model.text
    mid = model.json()['id']
    second = c.post('/api/scenes', json={'workspace_id': ws}).json()
    assert c.get(f"/api/scenes/{second['id']}/models/{mid}", params={'workspace_id': ws}).status_code == 404
    second['content']['objects'] = [{'id': 'model', 'kind': 'model', 'model_id': mid}]
    r = c.patch('/api/scenes/' + second['id'], json={'workspace_id': ws, 'name': 'Other', 'base_revision': 1, 'content': second['content']})
    assert r.status_code == 422


def test_agent_operations_merge_and_delete_hierarchy_atomically():
    c, ws, scene = setup_scene()
    path = f"/api/scenes/{scene['id']}/operations"
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 1, 'objects': [{'id': 'g', 'kind': 'group'}, {'id': 'box', 'kind': 'box', 'parent_id': 'g', 'parameters': {'width': 4}}]})
    assert r.status_code == 200, r.text
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 2, 'objects': [{'id': 'box', 'parameters': {'height': 3}}]})
    assert r.status_code == 200, r.text
    obj = r.json()['content']['objects'][1]
    assert obj['parameters']['width'] == 4 and obj['parameters']['height'] == 3
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 3, 'objects': [{'id': 'g', 'parent_id': 'box'}]})
    assert r.status_code == 422
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 3, 'remove_ids': ['g']})
    assert r.status_code == 200 and r.json()['content']['objects'] == []


def test_board_scene_reference_must_belong_to_workspace():
    c, ws, scene = setup_scene()
    canvas = {'items': [{'id': 'scene-node', 'kind': 'scene', 'scene_id': scene['id'], 'x': 0, 'y': 0}], 'edges': []}
    r = c.post('/api/boards', json={'workspace_id': ws, 'name': 'Scene board', 'canvas': canvas})
    assert r.status_code == 200, r.text
    assert r.json()['canvas']['items'][0]['scene_id'] == scene['id']
    other = c.post('/api/workspaces', json={'name': 'Other'}).json()['id']
    r = c.post('/api/boards', json={'workspace_id': other, 'name': 'Bad scene board', 'canvas': canvas})
    assert r.status_code == 400, r.text


def test_delete_scene_is_workspace_scoped_and_cascades_owned_data():
    from sqlalchemy import select
    from app.core.db import SessionLocal
    from app.db.models import Scene3DModel, Scene3DRevision
    c, ws, scene = setup_scene()
    path = f"/api/scenes/{scene['id']}"
    other = c.post('/api/workspaces', json={'name': 'Other'}).json()['id']
    assert c.delete(path, params={'workspace_id': other}).status_code == 404
    assert c.get(path, params={'workspace_id': ws}).status_code == 200
    model = c.post(path + '/models', data={'workspace_id': ws}, files={'file': ('empty.gltf', json.dumps({'asset': {'version': '2.0'}}).encode(), 'model/gltf+json')})
    assert model.status_code == 200, model.text
    retained = c.post('/api/scenes', json={'workspace_id': ws, 'name': 'Keep'}).json()
    assert c.delete(path, params={'workspace_id': ws}).status_code == 204
    assert c.get(path, params={'workspace_id': ws}).status_code == 404
    assert c.get(f"/api/scenes/{retained['id']}", params={'workspace_id': ws}).status_code == 200
    assert c.delete(path, params={'workspace_id': ws}).status_code == 404
    with SessionLocal() as db:
        assert db.get(Scene3DModel, model.json()['id']) is None
        assert not db.scalars(select(Scene3DRevision).where(Scene3DRevision.scene_id == scene['id'])).all()


def test_the_model_size_limit_is_one_number_and_never_contradicts_itself():
    """超限的回答要能直接照着做,而且**不能自相矛盾**。

    这里钉的是一个真出过的错:调用方只读「上限 + 1」个字节(不把一份 500 MB 的文件整个读进
    内存),于是 `len(data)` 最大就是上限 + 1 —— 拿它当文件大小报出来,500 MB 会变成
    「模型 100.0 MB,超出上限 100 MB」。读起来像 bug,还把用户往"再减一点点就行"骗。
    真实大小只有调用方(文件系统 / multipart)知道,所以由它传;传不了就干脆不报大小。

    顺带钉住"**只有一个数**":路由读文件和领域判上限此前各写了一遍 25 MB,改一处漏一处
    不会有任何提示 —— 只会变成"路由收下了、领域又拒了"。
    """
    from app.api.routes import scenes as scene_routes
    from app.domain.scenes import MODEL_LIMIT_BYTES, MODEL_READ_LIMIT, SceneTooLarge, validate_model

    assert MODEL_READ_LIMIT == MODEL_LIMIT_BYTES + 1
    assert scene_routes.MODEL_READ_LIMIT is MODEL_READ_LIMIT

    limit = MODEL_LIMIT_BYTES // 1024 // 1024
    truncated = b'glTF' + b'\0' * MODEL_READ_LIMIT

    def refuse(**kwargs):
        with pytest.raises(SceneTooLarge) as excinfo:
            validate_model(truncated, **kwargs)
        return str(excinfo.value)

    # 知道真实大小:报出来,并且和上限对得上。
    known = refuse(size=520 * 1024 * 1024)
    assert '520.0 MB' in known and f'{limit} MB' in known

    # 不知道:只说上限,绝不拿截断后的读数冒充文件大小。
    unknown = refuse()
    assert f'{limit} MB' in unknown
    assert f'{limit}.0 MB' not in unknown

    # 恰好超一个字节:四舍五入会等于上限,同样不报 —— 否则又是那句自相矛盾的话。
    assert f'{limit}.0 MB' not in refuse(size=MODEL_READ_LIMIT)

    assert 'Blender' in unknown   # 怎么减

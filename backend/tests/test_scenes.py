import json
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

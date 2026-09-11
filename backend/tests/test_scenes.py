import json
import struct
from pathlib import Path

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
    # 相机现在是场景里的物体,而镜头指着它 —— 替换 objects 时不能把它丢掉
    # (丢掉就是一个引用了不存在机位的场景,后端会拒)。
    camera = next(o for o in scene['content']['objects'] if o['kind'] == 'camera')
    payload['content']['objects'] = [camera, {'id': 'room', 'kind': 'room'}]
    r = c.patch('/api/scenes/' + scene['id'], json=payload)
    assert r.status_code == 200, r.text
    assert r.json()['revision'] == 2
    assert c.patch('/api/scenes/' + scene['id'], json=payload).status_code == 409
    old = c.get(f"/api/scenes/{scene['id']}/revisions/1", params={'workspace_id': ws}).json()
    assert [o['kind'] for o in old['content']['objects']] == ['camera']   # 空场景自带一台机位
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
    second['content']['objects'] = [
        next(o for o in second['content']['objects'] if o['kind'] == 'camera'),
        {'id': 'model', 'kind': 'model', 'model_id': mid},
    ]
    r = c.patch('/api/scenes/' + second['id'], json={'workspace_id': ws, 'name': 'Other', 'base_revision': 1, 'content': second['content']})
    assert r.status_code == 422


def test_agent_operations_merge_and_delete_hierarchy_atomically():
    c, ws, scene = setup_scene()
    path = f"/api/scenes/{scene['id']}/operations"
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 1, 'objects': [{'id': 'g', 'kind': 'group'}, {'id': 'box', 'kind': 'box', 'parent_id': 'g', 'parameters': {'width': 4}}]})
    assert r.status_code == 200, r.text
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 2, 'objects': [{'id': 'box', 'parameters': {'height': 3}}]})
    assert r.status_code == 200, r.text
    obj = next(o for o in r.json()['content']['objects'] if o['id'] == 'box')
    assert obj['parameters']['width'] == 4 and obj['parameters']['height'] == 3
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 3, 'objects': [{'id': 'g', 'parent_id': 'box'}]})
    assert r.status_code == 422
    r = c.post(path, json={'workspace_id': ws, 'base_revision': 3, 'remove_ids': ['g']})
    # 删掉组和它的后代之后只剩那台默认机位 —— 它是物体,所以也在这份列表里。
    assert r.status_code == 200 and [o['kind'] for o in r.json()['content']['objects']] == ['camera']


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


def _glb(total: int, tmp_path: Path) -> Path:
    """造一个**声明自己有 total 字节**的合法 GLB,但用稀疏文件占位 —— 建 200 MB 是瞬时的。

    这正是要测的性质:GLB 的资源都在后面的二进制块里,校验一个字节都不看它,只要文件头和
    前面那段 JSON。所以后面是不是真的写满了,校验根本不关心。
    """
    document = json.dumps({"asset": {"version": "2.0"}}).encode()
    header = struct.pack("<4sIIII", b"glTF", 2, total, len(document), 0x4E4F534A)
    path = tmp_path / "big.glb"
    with path.open("wb") as out:
        out.write(header + document)
        out.truncate(total)          # 稀疏:不真的占 200 MB 磁盘
    return path


def test_glb_is_validated_from_its_head_so_it_can_be_much_larger(tmp_path):
    """GLB 的上限比内嵌 glTF 高得多,**因为两者的代价不同,不是因为产品想让它高**。

    GLB 只要读文件头和那段 JSON(几百 KB),而内嵌 glTF 是一整份 JSON、资源是 base64 塞在
    里面的,校验必须 `json.loads` 整份 —— 那一下就是文件大小的好几倍内存。
    """
    from app.domain.scenes import (EMBEDDED_GLTF_LIMIT_BYTES, MODEL_LIMIT_BYTES,
                                   SceneTooLarge, validate_model_file)

    assert MODEL_LIMIT_BYTES > EMBEDDED_GLTF_LIMIT_BYTES

    # 比内嵌 glTF 的上限还大的 GLB:应当通过,而且不会因为"读整份"而慢或炸。
    big = EMBEDDED_GLTF_LIMIT_BYTES * 2
    assert validate_model_file(_glb(big, tmp_path)) == "glb"

    # 超过 GLB 自己的上限才拒。
    with pytest.raises(SceneTooLarge):
        validate_model_file(_glb(MODEL_LIMIT_BYTES + 1, tmp_path))


def test_refusing_a_too_large_model_never_contradicts_itself():
    """超限的话要能直接照着做,而且不能自相矛盾。

    钉的是一个真出过的错:调用方只读「上限 + 1」个字节,于是拿 `len(data)` 当文件大小报出来,
    500 MB 会变成「模型 100.0 MB,超出上限 100 MB」—— 读起来像 bug,还把用户往"再减一点点
    就行"骗。真实大小由调用方传;传不了就干脆不报大小。
    """
    from app.domain.scenes import (EMBEDDED_GLTF_LIMIT_BYTES, MODEL_LIMIT_BYTES,
                                   SceneTooLarge, validate_model)

    def refuse(data: bytes, **kwargs) -> str:
        with pytest.raises(SceneTooLarge) as excinfo:
            validate_model(data, **kwargs)
        return str(excinfo.value)

    limit = MODEL_LIMIT_BYTES // 1024 // 1024
    known = refuse(b"glTF" + b"\0" * 32, size=MODEL_LIMIT_BYTES * 3)
    assert f"{limit} MB" in known and f"{MODEL_LIMIT_BYTES * 3 / 1024 / 1024:.1f} MB" in known

    # 恰好超一点:四舍五入等于上限,就不报大小 —— 否则又是那句自相矛盾的话。
    assert f"{limit}.0 MB" not in refuse(b"glTF" + b"\0" * 32, size=MODEL_LIMIT_BYTES + 1)

    # 内嵌 glTF 走另一档,而且要说清楚"改导出 GLB 就能大得多"。
    embedded = refuse(b"{}" + b"\0" * 32, size=EMBEDDED_GLTF_LIMIT_BYTES + 1024 * 1024)
    assert f"{EMBEDDED_GLTF_LIMIT_BYTES // 1024 // 1024} MB" in embedded
    assert "GLB" in embedded and str(limit) in embedded


def test_keyframes_can_start_later_and_deleting_a_key_preserves_the_others():
    c, ws, scene = setup_scene()
    objects = scene['content']['objects']
    camera = next(o for o in objects if o['kind'] == 'camera')
    camera['track'] = [{'time': 3, 'position': [0, 2, 5], 'target': [0, 1, 0]}]
    result = c.patch('/api/scenes/' + scene['id'], json={
        'workspace_id': ws, 'name': scene['name'], 'base_revision': scene['revision'], 'content': scene['content'],
    })
    assert result.status_code == 200, result.text
    restored = next(o for o in result.json()['content']['objects'] if o['id'] == camera['id'])
    assert [f['time'] for f in restored['track']] == [3]
    camera['track'].append(dict(camera['track'][0]))
    invalid = c.patch('/api/scenes/' + scene['id'], json={
        'workspace_id': ws, 'name': scene['name'], 'base_revision': result.json()['revision'], 'content': scene['content'],
    })
    assert invalid.status_code == 422


def test_场景列表带着画缩略图要的字段_但不背整条运镜轨():
    """卡片上的缩略图是**从场景数据直出**的(同画板/工作流),所以列表得带上画得着的那几个字段。

    带什么和不带什么都要钉住:带少了缩略图画不出来,带多了列表就背着 200 个场景的全部关键帧 ——
    一条轨可以有 100 帧,而缩略图只需要相机走过哪儿。隐藏的物体不该出现在图上。
    """
    c, ws, scene = setup_scene()
    content = {
        **scene['content'],
        'objects': [
            {'id': 'a', 'name': '箱', 'kind': 'box', 'position': [1, 0, 2], 'color': '#ff0000',
             'parameters': {'width': 3, 'depth': 4}},
            {'id': 'hidden', 'name': '藏', 'kind': 'box', 'hidden': True},
            {'id': 'cam', 'name': '机位', 'kind': 'camera', 'position': [8, 5, 8], 'target': [0, 1, 0],
             'track': [{'time': 0, 'position': [0, 2, 0], 'target': [1, 0, 1]},
                       {'time': 3, 'position': [5, 2, 6], 'target': [1, 0, 1]}]},
        ],
        'shots': [{'id': 's1', 'name': '镜头 1', 'duration': 3, 'camera_id': 'cam'}],
    }
    saved = c.patch(f"/api/scenes/{scene['id']}",
                    json={'workspace_id': ws, 'name': 'Studio', 'content': content, 'base_revision': scene['revision']})
    assert saved.status_code == 200, saved.text

    row = next(item for item in c.get(f'/api/scenes?workspace_id={ws}').json() if item['id'] == scene['id'])
    objects = row['preview']['objects']
    assert [o['kind'] for o in objects] == ['box', 'camera'], '隐藏的物体不该进缩略图'
    box = objects[0]
    assert box['position'] == [1, 0, 2] and box['color'] == '#ff0000'
    # 只挑画得着的三个:width/depth 给方体,radius 给球和柱。门洞、台阶数这些俯视图上没有。
    assert box['parameters'] == {'width': 3, 'depth': 4, 'radius': 1}, '只挑画得着的参数'
    # 相机只带走过的位置点,不带整帧(target/fov 这些缩略图用不上)。
    assert objects[1]['path'] == [[0, 2, 0], [5, 2, 6]]
    assert 'track' not in objects[1] and 'track' not in box


def test_场景缩略图的物体数有上限():
    """列表一次最多 200 个场景。不设限的话,一个大场景就能把列表页的响应拖垮。"""
    from app.domain.scenes import PREVIEW_OBJECT_LIMIT, scene_preview

    many = {'objects': [{'id': f'o{i}', 'kind': 'box'} for i in range(PREVIEW_OBJECT_LIMIT + 25)]}
    assert len(scene_preview(many)['objects']) == PREVIEW_OBJECT_LIMIT

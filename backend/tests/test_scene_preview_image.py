"""画板 3D 场景格上的全景白模:整个场景的自由视角,按修订号缓存,场景一改就换一张、旧的删掉。"""

from __future__ import annotations

import io

from PIL import Image

from app.media.paths import scene_preview_dir
from tests.test_scenes import setup_scene


def test_场景格的预览是整个场景的全景白模_按修订号缓存_改了就换一张() -> None:
    client, ws, scene = setup_scene()
    url = f"/api/scenes/{scene['id']}/preview"
    first = client.get(url, params={"workspace_id": ws})
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(first.content)).size == (960, 540)
    cached = sorted(path.name for path in scene_preview_dir(ws).glob("*.jpg"))
    assert cached == [f"{scene['id']}-1.jpg"]

    content = scene["content"]
    camera = next(one for one in content["objects"] if one["kind"] == "camera")
    content["objects"] = [camera, {"id": "room", "kind": "room"}]
    saved = client.patch(f"/api/scenes/{scene['id']}", json={"workspace_id": ws, "name": "Room", "content": content,
                                                             "base_revision": 1})
    assert saved.status_code == 200, saved.text
    assert client.get(url, params={"workspace_id": ws}).content != first.content, "加了一个房间,画面要变"
    assert sorted(path.name for path in scene_preview_dir(ws).glob("*.jpg")) == [f"{scene['id']}-2.jpg"], "旧修订那张删掉"


def test_别的工作区拿不到_删了场景缓存也走() -> None:
    client, ws, scene = setup_scene()
    other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    assert client.get(f"/api/scenes/{scene['id']}/preview", params={"workspace_id": other}).status_code == 404
    assert client.get(f"/api/scenes/{scene['id']}/preview", params={"workspace_id": ws}).status_code == 200
    assert client.delete(f"/api/scenes/{scene['id']}", params={"workspace_id": ws}).status_code in (200, 204)
    assert list(scene_preview_dir(ws).glob("*.jpg")) == []

"""姿势与服装两种资产(ADR 0091 §2):能套在任何人物身上的参考,和人物 / 场景 / 道具共用一套表。

判据是用户看得到的后果:能建、能按种类列出来;姿势的参考图按**机位**标(斜侧、俯拍、仰拍),标成人物才有的
「表情」当场拒;体位、人数只能从词表里选;词表接口把这几样连同名字一起交给界面,界面不另抄一份。
"""

from __future__ import annotations

from app.domain.entities import catalog
from tests.util import fresh_client, seed_assets


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _create(client, workspace_id: str, **body):
    res = client.post("/api/entities", json={"workspace_id": workspace_id, **body})
    assert res.status_code == 200, res.text
    return res.json()


def test_姿势和服装能建_能按种类列出来() -> None:
    client = fresh_client()
    ws = _workspace(client)
    pose = _create(client, ws, kind="pose", name="抱膝坐", prompt="坐在地上,双手抱住一侧膝盖,背部后仰",
                   attributes={"posture": "sitting", "people": "single"})
    _create(client, ws, kind="costume", name="黑色连衣裙", prompt="黑色及膝连衣裙,白色蕾丝领")

    assert pose["attributes"] == {"posture": "sitting", "people": "single"}
    poses = client.get("/api/entities", params={"workspace_id": ws, "kind": "pose"}).json()
    costumes = client.get("/api/entities", params={"workspace_id": ws, "kind": "costume"}).json()
    assert [row["name"] for row in poses] == ["抱膝坐"]
    assert [row["name"] for row in costumes] == ["黑色连衣裙"]


def test_体位和人数只能从词表里选_服装没有专有字段() -> None:
    client = fresh_client()
    ws = _workspace(client)

    bad_posture = client.post("/api/entities", json={"workspace_id": ws, "kind": "pose", "name": "x",
                                                     "attributes": {"posture": "flying"}})
    assert bad_posture.status_code == 422
    assert "posture" in bad_posture.json()["detail"]

    costume_with_field = client.post("/api/entities", json={"workspace_id": ws, "kind": "costume", "name": "y",
                                                            "attributes": {"posture": "standing"}})
    assert costume_with_field.status_code == 422


def test_姿势的参考图按机位标_人物才有的角度当场拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"p_front": "image", "p_high": "image", "p_face": "image"})
    pose = _create(client, ws, kind="pose", name="站姿")

    default = client.post(f"/api/entities/{pose['id']}/references", json={"asset_id": "p_front"})
    assert default.status_code == 200, default.text
    high = client.post(f"/api/entities/{pose['id']}/references", json={"asset_id": "p_high", "role": "high_angle"})
    assert high.status_code == 200, high.text
    roles = {ref["asset_id"]: ref["role"] for ref in client.get(f"/api/entities/{pose['id']}").json()["references"]}
    assert roles == {"p_front": "front", "p_high": "high_angle"}

    expression = client.post(f"/api/entities/{pose['id']}/references", json={"asset_id": "p_face", "role": "expression"})
    assert expression.status_code in (400, 422), expression.text


def test_词表接口交出两种新资产_缺省角度和体位人数的名字() -> None:
    client = fresh_client()
    data = client.get("/api/entities/catalog").json()

    assert {"pose", "costume"} <= {one["kind"] for one in data["kinds"]}
    assert data["roles_by_kind"]["pose"] == list(catalog.ROLES_BY_KIND["pose"])
    assert data["default_role"] == catalog.DEFAULT_ROLE
    postures = [one["value"] for one in data["attribute_choices"]["pose"]["posture"]]
    assert postures == list(catalog.ATTRIBUTE_CHOICES["pose"]["posture"])
    assert all(one["label"] and one["label"] != one["value"] for one in data["attribute_choices"]["pose"]["people"])
    assert {"three_quarter", "high_angle", "low_angle"} <= {one["role"] for one in data["roles"]}


def test_每一种资产都有整套词表() -> None:
    """新加一种资产时,这几张表都得跟着写 —— 漏一张的话,挂图、建资产或者「补全多角度」会在那一种上 KeyError。"""
    for kind in catalog.KINDS:
        assert kind in catalog.ROLES_BY_KIND, kind
        assert kind in catalog.DEFAULT_ROLE, kind
        assert catalog.DEFAULT_ROLE[kind] in catalog.ROLES_BY_KIND[kind], kind
        assert kind in catalog.ATTRIBUTE_KEYS, kind
        assert set(catalog.ATTACH_PRIORITY.get(kind, ())) <= set(catalog.ROLES_BY_KIND[kind]), kind

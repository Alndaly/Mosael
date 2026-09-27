"""资产库(ADR 0027 阶段 1):人物 / 场景 / 道具的增删改查、参考图、变体、封面、删除规则、反查。

判据是**用户看得到的后果**,不是函数被调了几次:删素材之后资产还在、少了那一张且说得出少了哪一张;
删资产之后素材一张不少;别的工作区的人读不到、viewer 写不了。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Board, GenerationJob, Workflow
from tests.util import fresh_client, make_voice, second_client, seed_assets


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _create(client, workspace_id: str, **body):
    payload = {"workspace_id": workspace_id, "kind": "character", "name": "张三", **body}
    res = client.post("/api/entities", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_建一个人物_读回来_列出来() -> None:
    client = fresh_client()
    ws = _workspace(client)
    made = _create(client, ws, description="主角", prompt="黑色短发,红围巾", tags=["主角", "主角", " 冬天 "])
    assert made["kind"] == "character"
    assert made["tags"] == ["主角", "冬天"]
    assert made["attributes"] == {"real_person": False}
    assert made["references"] == [] and made["variants"] == []

    got = client.get(f"/api/entities/{made['id']}").json()
    assert got["prompt"] == "黑色短发,红围巾"

    _create(client, ws, kind="location", name="老街")
    listed = client.get("/api/entities", params={"workspace_id": ws}).json()
    assert {row["name"] for row in listed} == {"张三", "老街"}
    only = client.get("/api/entities", params={"workspace_id": ws, "kind": "location"}).json()
    assert [row["name"] for row in only] == ["老街"]
    tagged = client.get("/api/entities", params={"workspace_id": ws, "tag": "冬天"}).json()
    assert [row["name"] for row in tagged] == ["张三"]
    # 关键字在提示词描述里也找得到 —— 找「红围巾」时名字里往往没有这三个字。
    found = client.get("/api/entities", params={"workspace_id": ws, "q": "红围巾"}).json()
    assert [row["name"] for row in found] == ["张三"]


def test_种类和专有字段写错当场拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    bad_kind = client.post("/api/entities", json={"workspace_id": ws, "kind": "style", "name": "水彩"})
    assert bad_kind.status_code == 422
    wrong_key = client.post(
        "/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "伞", "attributes": {"voice_id": "v"}}
    )
    assert wrong_key.status_code == 422 and "voice_id" in wrong_key.json()["detail"]
    bad_color = client.post(
        "/api/entities",
        json={"workspace_id": ws, "kind": "character", "name": "李四", "attributes": {"blockout_color": "red"}},
    )
    assert bad_color.status_code == 422


def test_授权声明由服务端记下是谁_什么时候() -> None:
    client = fresh_client()
    ws = _workspace(client)
    made = _create(client, ws, attributes={"real_person": True, "consent": {"kind": "self", "declared_by": "冒名"}})
    consent = made["attributes"]["consent"]
    me = client.get("/api/auth/me").json()
    assert consent["kind"] == "self"
    assert consent["declared_by"] == me["id"], "声明人是登录的人,不是请求体里写的"
    assert consent["declared_at"]
    assert made["usable_for_digital_human"] is True

    # 真人配「虚构」是自相矛盾;虚构人物声明「本人」也是。
    contradictory = client.patch(
        f"/api/entities/{made['id']}", json={"attributes": {"real_person": True, "consent": {"kind": "fictional"}}}
    )
    assert contradictory.status_code == 422
    # 真人没有声明:不能用于数字人。
    undeclared = client.patch(f"/api/entities/{made['id']}", json={"attributes": {"real_person": True}}).json()
    assert "consent" not in undeclared["attributes"]
    assert undeclared["usable_for_digital_human"] is False


def test_音色和_3D_场景要在这个工作区() -> None:
    client = fresh_client()
    ws = _workspace(client)
    gone = client.post(
        "/api/entities",
        json={"workspace_id": ws, "kind": "character", "name": "王五", "attributes": {"voice_id": "no-such-voice"}},
    )
    assert gone.status_code == 422
    voice_id = make_voice(ws)
    ok = _create(client, ws, attributes={"voice_id": voice_id, "blockout_color": "#FF8800"})
    assert ok["attributes"]["voice_id"] == voice_id
    assert ok["attributes"]["blockout_color"] == "#ff8800"
    scene = client.post("/api/entities", json={"workspace_id": ws, "kind": "location", "name": "片场",
                                               "attributes": {"scene_id": "nope", "time_of_day": "黄昏"}})
    assert scene.status_code == 422


def test_参考图_挂上_换角度_排序_设封面_摘掉() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"front": "image", "side": "image", "sheet": "image", "clip": "video", "song": "audio"})
    made = _create(client, ws)
    eid = made["id"]

    first = client.post(f"/api/entities/{eid}/references", json={"asset_id": "front"}).json()
    assert [(r["asset_id"], r["role"]) for r in first["references"]] == [("front", "front")], "人物缺省是正面"
    assert first["display_cover_asset_id"] == "front", "没设封面时封面是第一张参考图"
    assert first["cover_asset_id"] is None
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "side", "role": "side"})
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "sheet", "role": "turnaround", "cover": True})
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "clip", "role": "concept"})
    assert client.post(f"/api/entities/{eid}/references", json={"asset_id": "song"}).status_code == 422
    assert client.post(f"/api/entities/{eid}/references", json={"asset_id": "front", "role": "nope"}).status_code == 422

    got = client.get(f"/api/entities/{eid}").json()
    assert [r["asset_id"] for r in got["references"]] == ["front", "side", "sheet", "clip"]
    assert got["cover_asset_id"] == "sheet"

    # 同一份素材再挂一次 = 改角度,不重复挂。
    again = client.post(f"/api/entities/{eid}/references", json={"asset_id": "side", "role": "back"}).json()
    assert [(r["asset_id"], r["role"]) for r in again["references"]][1] == ("side", "back")
    assert len(again["references"]) == 4

    role = client.patch(f"/api/entities/{eid}/references/side", json={"role": "closeup"}).json()
    assert role["references"][1]["role"] == "closeup"

    order = client.put(f"/api/entities/{eid}/references/order", json={"asset_ids": ["sheet", "front", "clip", "side"]})
    assert [r["asset_id"] for r in order.json()["references"]] == ["sheet", "front", "clip", "side"]
    # 少一张的排列拒 —— 另一个人刚挂了一张时,按旧清单排说不清新的那张去哪儿。
    stale = client.put(f"/api/entities/{eid}/references/order", json={"asset_ids": ["sheet", "front"]})
    assert stale.status_code == 409

    # 封面只能是自己的一张图片。
    assert client.patch(f"/api/entities/{eid}", json={"cover_asset_id": "clip"}).status_code == 422
    seed_assets(ws, {"stranger": "image"})
    assert client.patch(f"/api/entities/{eid}", json={"cover_asset_id": "stranger"}).status_code == 422
    assert client.patch(f"/api/entities/{eid}", json={"cover_asset_id": "front"}).json()["cover_asset_id"] == "front"

    removed = client.delete(f"/api/entities/{eid}/references/front").json()
    assert [r["asset_id"] for r in removed["references"]] == ["sheet", "clip", "side"]
    assert removed["cover_asset_id"] is None, "摘掉的是封面:封面退回第一张参考图"
    assert removed["display_cover_asset_id"] == "sheet"
    # 素材本身还在素材库里。
    assert client.get("/api/assets/front").status_code == 200


def test_删素材_资产还在_少一张_说得出少了哪一张() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"face": "image", "body": "image"})
    eid = _create(client, ws)["id"]
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "face", "role": "front", "cover": True})
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "body", "role": "full_body"})

    assert client.delete("/api/assets/face").status_code == 204

    got = client.get(f"/api/entities/{eid}").json()
    assert [r["asset_id"] for r in got["references"]] == ["body"]
    assert got["cover_asset_id"] is None
    assert [(row["name"], row["role"]) for row in got["lost_references"]] == [("face", "front")]
    # 看过了就能清掉。
    cleared = client.delete(f"/api/entities/{eid}/lost-references").json()
    assert cleared["lost_references"] == []


def test_删资产不删素材_有变体要明说() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"face": "image"})
    parent = _create(client, ws, prompt="黑色短发")
    client.post(f"/api/entities/{parent['id']}/references", json={"asset_id": "face"})
    variant = client.post(f"/api/entities/{parent['id']}/variants", json={"name": "冬装", "prompt": "羽绒服"})
    assert variant.status_code == 200, variant.text
    assert variant.json()["parent_name"] == "张三"
    assert variant.json()["kind"] == "character"

    refused = client.delete(f"/api/entities/{parent['id']}")
    assert refused.status_code == 409 and "1" in refused.json()["detail"]
    assert client.delete(f"/api/entities/{parent['id']}", params={"with_variants": "true"}).status_code == 204
    assert client.get(f"/api/entities/{parent['id']}").status_code == 404
    assert client.get(f"/api/entities/{variant.json()['id']}").status_code == 404
    assert client.get("/api/assets/face").status_code == 200, "删资产不删素材"


def test_变体只有一层_种类跟着母体() -> None:
    client = fresh_client()
    ws = _workspace(client)
    parent = _create(client, ws)
    variant = client.post(f"/api/entities/{parent['id']}/variants", json={"name": "少年"}).json()
    nested = client.post(f"/api/entities/{variant['id']}/variants", json={"name": "少年 · 冬装"})
    assert nested.status_code == 422
    mismatched = client.post("/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "x",
                                                    "parent_id": parent["id"]})
    assert mismatched.status_code == 422

    listed = client.get("/api/entities", params={"workspace_id": ws}).json()
    assert [row["name"] for row in listed] == ["张三"], "列表缺省只列母体"
    assert listed[0]["variant_count"] == 1
    variants = client.get("/api/entities", params={"workspace_id": ws, "parent_id": parent["id"]}).json()
    assert [row["name"] for row in variants] == ["少年"]
    detail = client.get(f"/api/entities/{parent['id']}").json()
    assert [row["name"] for row in detail["variants"]] == ["少年"]


def test_素材属于哪些资产() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"face": "image"})
    a = _create(client, ws)
    b = client.post(f"/api/entities/{a['id']}/variants", json={"name": "冬装"}).json()
    client.post(f"/api/entities/{a['id']}/references", json={"asset_id": "face", "role": "front"})
    client.post(f"/api/entities/{b['id']}/references", json={"asset_id": "face", "role": "closeup"})
    rows = client.get("/api/assets/face/entities").json()
    assert sorted((row["name"], row["role"], row["parent_name"]) for row in rows) == [
        ("冬装", "closeup", "张三"), ("张三", "front", ""),
    ]


def test_别的工作区读不到_viewer_写不了() -> None:
    owner = fresh_client()
    ws = _workspace(owner)
    seed_assets(ws, {"face": "image"})
    eid = _create(owner, ws)["id"]

    stranger = second_client("stranger")
    theirs = stranger.post("/api/workspaces", json={"name": "Theirs"}).json()["id"]
    assert stranger.get(f"/api/entities/{eid}").status_code in (403, 404)
    assert stranger.get("/api/entities", params={"workspace_id": ws}).status_code in (403, 404)
    assert stranger.patch(f"/api/entities/{eid}", json={"name": "偷改"}).status_code in (403, 404)
    assert stranger.get("/api/assets/face/entities").status_code in (403, 404)
    # 别的工作区的素材挂不进来。
    seed_assets(theirs, {"their-face": "image"})
    assert owner.post(f"/api/entities/{eid}/references", json={"asset_id": "their-face"}).status_code == 422

    viewer = second_client("viewer")
    owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "viewer", "role": "viewer"})
    invitation = viewer.get("/api/invitations").json()["invitations"][0]
    viewer.post(f"/api/invitations/{invitation['id']}/accept")
    assert viewer.get(f"/api/entities/{eid}").status_code == 200, "viewer 读得到"
    assert viewer.patch(f"/api/entities/{eid}", json={"name": "改"}).status_code == 403
    assert viewer.post(f"/api/entities/{eid}/references", json={"asset_id": "face"}).status_code == 403
    assert viewer.delete(f"/api/entities/{eid}").status_code == 403
    assert viewer.post("/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "伞"}).status_code == 403


def test_在哪里用过() -> None:
    client = fresh_client()
    ws = _workspace(client)
    eid = _create(client, ws)["id"]
    other = _create(client, ws, name="李四")["id"]
    me = client.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Board(workspace_id=ws, name="有资产格", canvas={"items": [
            {"id": "e1", "kind": "entity", "x": 0, "y": 0, "entity_id": eid}], "edges": []}))
        db.add(Board(workspace_id=ws, name="提示词里 @", canvas={"items": [
            {"id": "i1", "kind": "image", "x": 0, "y": 0, "form": {"mentioned_entity_ids": [eid]}}], "edges": []}))
        db.add(Board(workspace_id=ws, name="只有李四", canvas={"items": [
            {"id": "e2", "kind": "entity", "x": 0, "y": 0, "entity_id": other}], "edges": []}))
        db.add(GenerationJob(workspace_id=ws, provider="p", model="m", kind="image",
                             request={"prompt": "街头", "entities": [{"id": eid, "name": "张三"}]}))
        db.add(GenerationJob(workspace_id=ws, provider="p", model="m", kind="image",
                             request={"prompt": "别人", "entities": [{"id": other, "name": "李四"}]}))
        db.add(Workflow(workspace_id=ws, name="出图流程", graph={"nodes": [
            {"id": "g", "type": "ai_generate", "config": {"entity_ids": [eid]}}], "edges": []}))
        db.add(Workflow(workspace_id=ws, name="无关", graph={"nodes": [], "edges": []}))
        db.commit()
    usage = client.get(f"/api/entities/{eid}/usage").json()
    assert sorted((row["name"], row["how"]) for row in usage["boards"]) == [("提示词里 @", "mention"), ("有资产格", "cell")]
    assert [row["prompt"] for row in usage["generations"]] == ["街头"]
    assert [row["name"] for row in usage["workflows"]] == ["出图流程"]
    assert me

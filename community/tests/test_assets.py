"""资产(人物 / 场景 / 道具)分享到社区:分享包校验、参考图归属、真人审核、版本、下载、举报(ADR 0027 §4)。"""

from __future__ import annotations

from conftest import API, login_as
from test_shares import png, sha, upload

from mosael_formats.asset_bundle import SCHEMA

ALICE = "+8613800000031"
BOB = "+8613800000032"
MOD = "+8613800000033"


def bundle(*images: bytes, kind: str = "character", real_person: bool = False, **extra) -> dict:
    references = [
        {"sha256": sha(data), "content_type": "image/png", "width": 64, "height": 48, "role": role}
        for data, role in zip(images, ("front", "side", "turnaround", "back"))
    ]
    attributes = {"real_person": real_person, "blockout_color": "#aabbcc"} if kind == "character" else {}
    return {
        "schema": SCHEMA,
        "kind": kind,
        "name": "林小满",
        "description": "短片女主角,十七岁",
        "prompt": "a 17-year-old girl, short black hair, school uniform",
        "tags": ["主角"],
        "attributes": attributes,
        "references": references,
        "cover_sha256": references[0]["sha256"] if references else "",
        **extra,
    }


def submit(client, headers, body: dict, **fields):
    return client.post(f"{API}/assets", headers=headers, json={"bundle": body, **fields})


def test_虚构人物发布即上架_按种类筛_下载拿到分享包和图片地址(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    front, side = png((10, 20, 200)), png((200, 20, 10))
    upload(client, alice, front, side)
    created = submit(client, alice, bundle(front, side))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["submission"]["status"] == "approved"
    assert body["asset_kind"] == "character" and body["real_person"] is False
    assert body["reference_count"] == 2 and body["cover_url"]
    slug = body["slug"]

    listed = client.get(f"{API}/assets", params={"asset_kind": "character"}).json()["items"]
    assert [one["slug"] for one in listed] == [slug]
    assert client.get(f"{API}/assets", params={"asset_kind": "prop"}).json()["items"] == []
    assert client.get(f"{API}/assets", params={"asset_kind": "robot"}).status_code == 422

    detail = client.get(f"{API}/assets/{slug}").json()
    assert detail["bundle"]["name"] == "林小满"
    assert set(detail["media"]) == {sha(front), sha(side)}
    assert "consent_kind" not in detail, "授权声明只给作者和审核员看"

    downloaded = client.get(f"{API}/assets/{slug}/download")
    assert downloaded.status_code == 200
    payload = downloaded.json()
    assert payload["bundle"]["references"][0]["role"] == "front"
    assert payload["media"][sha(front)]["url"].startswith("https://mosael.test/")
    assert client.get(f"{API}/assets/{slug}").json()["downloads"] == 1


def test_真人人物要授权声明_进审核_通过后才公开(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    mod = login_as(client, ctx, sms, MOD, role="moderator")
    face = png((1, 2, 3))
    upload(client, alice, face)

    refused = submit(client, alice, bundle(face, real_person=True))
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_asset_bundle"

    created = submit(client, alice, bundle(face, real_person=True), consent_kind="self")
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    assert created.json()["submission"]["status"] == "pending"
    assert client.get(f"{API}/assets").json()["items"] == [], "审核通过前不公开"
    assert client.get(f"{API}/assets/{slug}").status_code == 404

    mine = client.get(f"{API}/assets/{slug}", headers=alice).json()
    assert mine["consent_kind"] == "self" and mine["bundle"]["attributes"]["real_person"] is True

    queue = client.get(f"{API}/admin/queue", headers=mod).json()["items"]
    [entry] = [one for one in queue if one["kind"] == "asset"]
    assert entry["consent_kind"] == "self" and sha(face) in entry["media"]
    approved = client.post(f"{API}/admin/submissions/{entry['id']}/approve", headers=mod, json={"note": "本人照片,核对过"})
    assert approved.status_code == 200

    public = client.get(f"{API}/assets/{slug}").json()
    assert public["real_person"] is True and "consent_kind" not in public


def test_不该出门的字段被拒并点名(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    face = png((5, 5, 5))
    upload(client, alice, face)
    body = bundle(face)
    body["attributes"]["voice_id"] = "v-123"
    refused = submit(client, alice, body)
    assert refused.status_code == 422
    assert "voice_id" in refused.json()["error"]["message"]


def test_参考图必须是自己上传过的(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    never = png((9, 9, 9))
    refused = submit(client, alice, bundle(never))
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "unknown_blob"

    bobs = png((8, 8, 8))
    upload(client, bob, bobs)
    stolen = submit(client, alice, bundle(bobs))
    assert stolen.status_code == 422 and stolen.json()["error"]["code"] == "unknown_blob", "知道别人一张图的哈希不够"


def test_新版本沿用同一个链接_种类不能换_别人不能替你发(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    first, second = png((1, 100, 1)), png((100, 1, 1))
    upload(client, alice, first, second)
    slug = submit(client, alice, bundle(first)).json()["slug"]

    again = client.post(f"{API}/assets/{slug}/versions", headers=alice, json={"bundle": bundle(first, second), "changelog": "加了侧面"})
    assert again.status_code == 201 and again.json()["version"] == "2"
    assert client.get(f"{API}/assets/{slug}").json()["reference_count"] == 2

    changed = client.post(f"{API}/assets/{slug}/versions", headers=alice, json={"bundle": bundle(first, kind="prop")})
    assert changed.status_code == 422 and changed.json()["error"]["code"] == "asset_kind_changed"

    upload(client, bob, first)
    hijack = client.post(f"{API}/assets/{slug}/versions", headers=bob, json={"bundle": bundle(first)})
    assert hijack.status_code == 403


def test_举报理由里有冒用肖像(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    face = png((7, 70, 7))
    upload(client, alice, face)
    slug = submit(client, alice, bundle(face)).json()["slug"]
    reported = client.post(f"{API}/assets/{slug}/report", headers=bob, json={"reason": "likeness", "detail": "这是我的脸"})
    assert reported.status_code == 201, reported.text


def test_统计和作者主页里有资产(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    face = png((70, 7, 7))
    upload(client, alice, face)
    submit(client, alice, bundle(face, kind="location", attributes={"time_of_day": "黄昏"}))
    overview = client.get(f"{API}/stats/overview").json()
    assert overview["assets"] == 1 and len(overview["top_assets"]) == 1
    handle = client.get(f"{API}/me", headers=alice).json()["handle"]
    profile = client.get(f"{API}/users/{handle}").json()
    assert profile["assets_count"] == 1 and profile["assets"][0]["asset_kind"] == "location"


def test_工作流和插件的列表不受资产影响(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    face = png((3, 30, 3))
    upload(client, alice, face)
    submit(client, alice, bundle(face))
    assert client.get(f"{API}/workflows").json()["items"] == [] or all(
        one["kind"] == "workflow" for one in client.get(f"{API}/workflows").json()["items"]
    )

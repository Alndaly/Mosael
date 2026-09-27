"""画板分享:三步上传、哈希核对、快照校验、版本、可见性、撤回 410、预览图;以及存储与请求上限。"""

from __future__ import annotations

import hashlib
import io
from urllib.parse import urlsplit

from conftest import API, login_as
from PIL import Image
from sqlalchemy import select

from community.models import Blob, ShareVersion
from mosael_formats.board_snapshot import SCHEMA

ALICE = "+8613800000021"
BOB = "+8613800000022"


def png(color=(200, 30, 30), size=(64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


def upload(client, headers, *files: bytes, content_type: str = "image/png") -> dict:
    response = client.post(
        f"{API}/shares/uploads",
        headers=headers,
        json={"files": [{"sha256": sha(one), "size": len(one), "content_type": content_type} for one in files]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_sha = {one["sha256"]: one for one in body["uploads"]}
    for data in files:
        target = by_sha.get(sha(data))
        if target is None:
            continue
        assert target["method"] == "PUT" and target["url"].startswith("https://mosael.test/api/community/v1/uploads/")
        put = client.put(put_url(target["url"]), content=data, headers=target["headers"])
        assert put.status_code == 204, put.text
    return body


def snapshot(*images: bytes, **extra) -> dict:
    items = [
        {
            "id": f"i{index}",
            "kind": "image",
            "x": index * 300,
            "y": 0,
            "width": 260,
            "height": 180,
            "title": f"图 {index}",
            "media": {"sha256": sha(data), "content_type": "image/png", "width": 64, "height": 48},
        }
        for index, data in enumerate(images)
    ]
    items.append({"id": "n1", "kind": "note", "x": 0, "y": 300, "width": 220, "height": 140, "text": "hello", "color": "yellow"})
    items.append({"id": "d1", "kind": "document", "title": "文", "markdown": "# 正文", "revision": 13})
    return {"schema": SCHEMA, "viewport": {"x": 0, "y": 0, "zoom": 1}, "items": items, "edges": [{"id": "e1", "source": "n1", "target": "d1"}], **extra}


def share(client, headers, snap: dict, *, board_key="board-key-0001", title="我的画板", visibility="unlisted"):
    return client.post(f"{API}/shares", headers=headers, json={"board_key": board_key, "title": title, "visibility": visibility, "snapshot": snap})


def test_三步上传_同一张画板再分享是新版本(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    a, b = png(), png((20, 200, 20))
    first = upload(client, alice, a, b)
    assert len(first["uploads"]) == 2 and first["skipped"] == []
    # 断了能续:再要一次,已经传好的跳过
    again = upload(client, alice, a, b)
    assert again["uploads"] == [] and sorted(again["skipped"]) == sorted([sha(a), sha(b)])

    created = share(client, alice, snapshot(a, b), visibility="public")
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == {"slug", "url", "version"} and body["version"] == 1
    assert body["url"] == f"https://mosael.test/zh/b/{body['slug']}"

    viewed = client.get(f"{API}/shares/{body['slug']}").json()
    assert viewed["version"] == 1 and viewed["snapshot"]["items"][0]["media"]["sha256"] == sha(a)
    assert viewed["media"][sha(a)]["url"].startswith("/community-media/blobs/")
    assert viewed["media"][sha(a)]["url"].endswith(".png")
    assert viewed["owner"]["handle"]

    second = share(client, alice, snapshot(b), title="改了标题")
    assert second.status_code == 200 and second.json() == {**body, "version": 2}
    assert client.get(f"{API}/shares/{body['slug']}").json()["title"] == "改了标题"


def test_哈希对不上的上传被拒(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    real = png()
    response = client.post(
        f"{API}/shares/uploads", headers=alice, json={"files": [{"sha256": sha(real), "size": len(real), "content_type": "image/png"}]}
    )
    target = response.json()["uploads"][0]
    forged = png((1, 2, 3))
    forged = forged + b"\0" * (len(real) - len(forged)) if len(forged) < len(real) else forged[: len(real)]
    put = client.put(put_url(target["url"]), content=forged, headers=target["headers"])
    assert put.status_code == 400 and put.json()["error"]["code"] == "hash_mismatch"
    short = client.put(put_url(target["url"]), content=real[:10], headers=target["headers"])
    assert short.status_code == 400 and short.json()["error"]["code"] == "size_mismatch"
    tampered = put_url(target["url"]).replace("t=", "t=x")
    assert client.put(tampered, content=real).status_code == 403
    with ctx.sessions() as db:
        assert db.get(Blob, sha(real)).status == "pending"
    # 没上传成功的文件,快照不能引用
    refused = share(client, alice, snapshot(real))
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "unknown_blob"


def test_快照引用没上传过的哈希被拒(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    ghost = b"never uploaded"
    response = share(client, alice, snapshot(ghost))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_blob" and sha(ghost) in response.json()["error"]["message"]


def test_别人上传的文件要先声明拥有才能引用(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    data = png()
    upload(client, alice, data)
    assert share(client, bob, snapshot(data)).json()["error"]["code"] == "unknown_blob"
    claimed = upload(client, bob, data)
    assert claimed["skipped"] == [sha(data)]  # 去重:不用再传一遍
    assert share(client, bob, snapshot(data)).status_code == 201


def test_快照格式不对(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bad = snapshot()
    bad["schema"] = "mosael.board-snapshot/9"
    response = share(client, alice, bad)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_snapshot"
    local = snapshot()
    local["items"][0]["src"] = "file:///Users/me/secret.png"
    assert share(client, alice, local).status_code == 422
    ctx.settings.share_max_items = 1
    assert share(client, alice, snapshot()).json()["error"]["code"] == "invalid_snapshot"
    assert share(client, alice, snapshot(), board_key="short").json()["error"]["code"] == "board_key_invalid"


def test_上传的类型白名单与限额(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    html = b"<html><script>alert(1)</script></html>"
    for content_type in ("text/html", "image/svg+xml", "application/javascript"):
        response = client.post(
            f"{API}/shares/uploads", headers=alice, json={"files": [{"sha256": sha(html), "size": len(html), "content_type": content_type}]}
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == "content_type_not_allowed"
        message = response.json()["error"]["message"]
        assert content_type in message and "image/png" in message and "video/mp4" in message
    en = client.post(
        f"{API}/shares/uploads",
        headers={**alice, "Accept-Language": "en"},
        json={"files": [{"sha256": sha(html), "size": len(html), "content_type": "text/html"}]},
    )
    assert en.json()["error"]["message"].startswith("This file type isn't supported: text/html. Supported types: image/png")
    # 声称是图片、其实是 HTML:落盘前按文件头认出来
    response = client.post(
        f"{API}/shares/uploads", headers=alice, json={"files": [{"sha256": sha(html), "size": len(html), "content_type": "image/png"}]}
    )
    target = response.json()["uploads"][0]
    assert client.put(put_url(target["url"]), content=html).status_code == 422
    ctx.settings.share_max_file_bytes = 10
    too_big = client.post(
        f"{API}/shares/uploads", headers=alice, json={"files": [{"sha256": "a" * 64, "size": 11, "content_type": "image/png"}]}
    )
    assert too_big.status_code == 413
    ctx.settings.share_max_file_bytes = 10**9
    ctx.settings.user_storage_quota_bytes = 100
    quota = client.post(
        f"{API}/shares/uploads", headers=alice, json={"files": [{"sha256": "b" * 64, "size": 101, "content_type": "image/png"}]}
    )
    assert quota.status_code == 413 and quota.json()["error"]["code"] == "quota_exceeded"


def test_单张画板的总量上限(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    data = png()
    upload(client, alice, data)
    ctx.settings.share_max_total_bytes = 10
    response = share(client, alice, snapshot(data))
    assert response.status_code == 413 and response.json()["error"]["code"] == "share_too_large"


def test_撤回之后_410_再分享得到新链接(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    slug = share(client, alice, snapshot()).json()["slug"]
    bob = login_as(client, ctx, sms, BOB)
    assert client.delete(f"{API}/shares/{slug}", headers=bob).status_code == 403
    assert client.delete(f"{API}/shares/{slug}", headers=alice).status_code == 204
    gone = client.get(f"{API}/shares/{slug}")
    assert gone.status_code == 410 and gone.json()["error"]["code"] == "share_revoked"
    assert client.get(f"{API}/shares/{slug}/og.png").status_code == 410
    again = share(client, alice, snapshot())
    assert again.status_code == 201 and again.json()["slug"] != slug and again.json()["version"] == 1
    assert client.get(f"{API}/shares/{slug}").status_code == 410


def test_可见性(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    me = client.get(f"{API}/me", headers=alice).json()
    slug = share(client, alice, snapshot()).json()["slug"]
    # unlisted:知道链接能看,但不进公开列表和主页
    unlisted = client.get(f"{API}/shares/{slug}")
    assert unlisted.status_code == 200 and unlisted.headers["x-robots-tag"] == "noindex"
    assert client.get(f"{API}/shares").json()["items"] == []
    assert client.get(f"{API}/users/{me['handle']}").json()["boards"] == []
    patched = client.patch(f"{API}/shares/{slug}", headers=alice, json={"visibility": "public"})
    assert patched.status_code == 200 and patched.json()["visibility"] == "public"
    assert [one["slug"] for one in client.get(f"{API}/shares").json()["items"]] == [slug]
    assert client.get(f"{API}/users/{me['handle']}").json()["boards_count"] == 1
    assert "x-robots-tag" not in client.get(f"{API}/shares/{slug}").headers
    assert client.patch(f"{API}/shares/{slug}", headers=alice, json={"visibility": "secret"}).status_code == 422
    mine = client.get(f"{API}/me/shares", headers=alice).json()["items"]
    assert [one["slug"] for one in mine] == [slug]


def test_预览图第一次请求时生成并缓存(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    images = [png((index * 60, 100, 200 - index * 40), (120, 90)) for index in range(5)]
    upload(client, alice, *images)
    slug = share(client, alice, snapshot(*images), title="一张很长很长的中文标题,用来测试折行是不是正常工作的 Mosael board").json()["slug"]
    first = client.get(f"{API}/shares/{slug}/og.png")
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(first.content))
    assert image.size == (1200, 630)
    with ctx.sessions() as db:
        version = db.scalars(select(ShareVersion)).one()
        assert version.og_key == f"og/{version.id}.png"
        assert ctx.storage.exists(version.og_key)
    second = client.get(f"{API}/shares/{slug}/og.png")
    assert second.content == first.content
    # 没有图的画板也有一张(只有标题和字标)
    plain = share(client, alice, snapshot(), board_key="board-key-0002", title="").json()["slug"]
    assert Image.open(io.BytesIO(client.get(f"{API}/shares/{plain}/og.png").content)).size == (1200, 630)


def test_分享举报与下架(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    mod = login_as(client, ctx, sms, "+8613800000029", role="moderator")
    slug = share(client, alice, snapshot(), visibility="public").json()["slug"]
    assert client.post(f"{API}/shares/{slug}/report", headers=bob, json={"reason": "inappropriate"}).status_code == 201
    assert client.post(f"{API}/admin/items/shares/{slug}/hide", headers=mod, json={}).status_code == 200
    removed = client.get(f"{API}/shares/{slug}")
    assert removed.status_code == 410 and removed.json()["error"]["code"] == "share_removed"


# ---------------- 通用:安全头与请求上限 ----------------


def test_安全头与_nosniff(client) -> None:
    response = client.get(f"{API}/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in response.headers


def test_请求体超过上限(client, ctx, sms) -> None:
    ctx.settings.json_body_max_bytes = 100
    # BodyLimitMiddleware 在建应用时拿到的是同一个 settings 对象
    response = client.post(f"{API}/auth/device/code", json={"client_name": "x" * 500})
    assert response.status_code == 413 and response.json()["error"]["code"] == "body_too_large"


def test_未知路径也是统一的错误形状(client) -> None:
    response = client.get(f"{API}/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"

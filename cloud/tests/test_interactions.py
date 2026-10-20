"""互动:点赞 / 收藏的幂等与并发去重、评论的校验 / 纯文本 / 权限 / 分页。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from conftest import api, execute, scalar, signup

from community_helpers import make_identity, publish_ok


def _share(client) -> dict:
    signup(client)
    make_identity(client)
    return publish_ok(client)


# ---------------------------------------------------------------- 点赞 / 收藏


def test_like_is_idempotent_and_delete_is_idempotent(client):
    share = _share(client)

    for _ in range(2):
        response = client.post(api(f"/shares/{share['id']}/like"))
        assert response.status_code == 204, response.text
    assert client.get(api(f"/shares/{share['id']}")).json()["stats"]["likes"] == 1

    for _ in range(2):
        response = client.delete(api(f"/shares/{share['id']}/like"))
        assert response.status_code == 204, response.text
    assert client.get(api(f"/shares/{share['id']}")).json()["stats"]["likes"] == 0


def test_favorite_is_idempotent_and_delete_is_idempotent(client):
    share = _share(client)

    for _ in range(2):
        assert client.post(api(f"/shares/{share['id']}/favorite")).status_code == 204
    assert client.get(api(f"/shares/{share['id']}")).json()["stats"]["favorites"] == 1

    for _ in range(2):
        assert client.delete(api(f"/shares/{share['id']}/favorite")).status_code == 204
    assert client.get(api(f"/shares/{share['id']}")).json()["stats"]["favorites"] == 0


def test_concurrent_likes_cannot_duplicate(client, app, db_path):
    """④ 并发的两次点赞靠 `(share_id, user_id)` 主键只留一行 —— 不是先查再插。"""
    share = _share(client)

    workers = [TestClient(app), TestClient(app)]
    for worker in workers:
        worker.cookies.update(client.cookies)

    def hit(worker: TestClient) -> int:
        try:
            return worker.post(api(f"/shares/{share['id']}/like")).status_code
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(hit, workers))

    assert statuses == [204, 204]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_likes") == 1
    assert client.get(api(f"/shares/{share['id']}")).json()["stats"]["likes"] == 1


def test_likes_require_a_session_and_an_existing_share(client):
    share = _share(client)
    assert client.post(api(f"/shares/{share['id']}/like")).status_code == 204

    guest = TestClient(client.app)
    try:
        assert guest.post(api(f"/shares/{share['id']}/like")).status_code == 401
    finally:
        guest.close()

    client.cookies.clear()
    assert client.post(api("/shares/does-not-exist/like")).status_code == 401


# ---------------------------------------------------------------- 评论


def test_comment_requires_identity_and_session(client, app, db_path):
    share = _share(client)

    guest = TestClient(app)
    try:
        assert guest.post(api(f"/shares/{share['id']}/comments"), json={"body": "hi"}).status_code == 401
    finally:
        guest.close()

    other = TestClient(app)
    try:
        signup(other, email="bob@example.com")  # 注册即登录,而且注册就带了默认身份
        # 没有身份的**老账号**才该被拦:把昵称清掉,模拟那种账号(写接口的门禁一行未动)。
        execute(db_path, "UPDATE cloud_users SET display_name = NULL WHERE email = 'bob@example.com'")
        response = other.post(api(f"/shares/{share['id']}/comments"), json={"body": "hi"})
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "identity_required"
    finally:
        other.close()


def test_comment_must_be_non_empty_and_bounded(client, db_path):
    share = _share(client)

    empty = client.post(api(f"/shares/{share['id']}/comments"), json={"body": "   "})
    assert empty.status_code == 422
    assert empty.json()["error"] == "comment_empty"

    long = client.post(api(f"/shares/{share['id']}/comments"), json={"body": "x" * 2001})
    assert long.status_code == 422
    assert long.json()["error"] == "comment_too_long"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_comments") == 0


def test_comment_body_is_returned_as_plain_text_not_rendered(client):
    """社区内容是别人写的:存原文,响应是 JSON 纯文本;不渲染 HTML、不渲染 markdown。"""
    share = _share(client)
    raw = '<script>alert("x")</script> **bold** & <img src=x onerror=alert(1)>'
    created = client.post(api(f"/shares/{share['id']}/comments"), json={"body": raw})
    assert created.status_code == 201, created.text
    assert created.headers["content-type"].startswith("application/json")
    assert created.json()["comment"]["body"] == raw

    listed = client.get(api(f"/shares/{share['id']}/comments"))
    assert listed.headers["content-type"].startswith("application/json")
    assert listed.json()["items"][0]["body"] == raw


def test_only_the_comment_author_can_delete_it(client, app):
    share = _share(client)
    comment = client.post(api(f"/shares/{share['id']}/comments"), json={"body": "mine"}).json()["comment"]

    other = TestClient(app)
    try:
        signup(other, email="bob@example.com")
        make_identity(other, "Bob")
        forbidden = other.delete(api(f"/shares/{share['id']}/comments/{comment['id']}"))
        assert forbidden.status_code == 404, forbidden.text
        assert forbidden.json()["error"] == "comment_not_found"
    finally:
        other.close()

    assert client.delete(api(f"/shares/{share['id']}/comments/{comment['id']}")).status_code == 204
    assert client.get(api(f"/shares/{share['id']}/comments")).json()["items"] == []


def test_comments_paginate_newest_first(client, db_path):
    share = _share(client)
    ids = []
    for body in ("one", "two", "three"):
        ids.append(client.post(api(f"/shares/{share['id']}/comments"), json={"body": body}).json()["comment"]["id"])
    for day, comment_id in enumerate(ids, start=1):
        execute(
            db_path,
            "UPDATE cloud_share_comments SET created_at = ? WHERE id = ?",
            (f"2026-03-0{day} 00:00:00.000000", comment_id),
        )

    first = client.get(api(f"/shares/{share['id']}/comments?limit=2")).json()
    assert [item["body"] for item in first["items"]] == ["three", "two"]
    assert first["next_cursor"]

    second = client.get(
        api(f"/shares/{share['id']}/comments?limit=2&cursor={first['next_cursor']}")
    ).json()
    assert [item["body"] for item in second["items"]] == ["one"]
    assert second["next_cursor"] is None

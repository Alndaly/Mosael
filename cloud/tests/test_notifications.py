"""通知:互动 → 作者收到一条;自己对自己不产生;取消 / 删评论收回去;

同一 (作者, 互动者, 分享, 类型) 的**未读只留一条**;分页 + 未读总数;公开响应无 email;
软删的分享的通知不出现在列表里(但数据不删)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import api, execute, scalar, signup

from community_helpers import leaves, make_identity, publish_ok


def _published(client) -> dict:
    signup(client, email="alice@example.com")
    make_identity(client, "Alice", "alice")
    return publish_ok(client)


def _actor(app, *, email: str, name: str, handle: str) -> TestClient:
    made = TestClient(app)
    signup(made, email=email)
    make_identity(made, name, handle)
    return made


def _items(client) -> list[dict]:
    response = client.get(api("/notifications"))
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _summary(client) -> dict:
    response = client.get(api("/notifications"))
    assert response.status_code == 200, response.text
    return response.json()


def _pin_newest_first(db_path, items: list[dict]) -> None:
    """把列表当前的"新在前"顺序钉成不相撞的时间,分页才有确定答案。"""
    for offset, item in enumerate(items):
        execute(
            db_path,
            "UPDATE cloud_share_notifications SET created_at = ? WHERE id = ?",
            (f"2026-04-0{len(items) - offset} 00:00:00.000000", item["id"]),
        )


def test_like_favorite_and_comment_notify_the_author(client, app, db_path):
    """① 点赞 / 收藏 / 评论 → 分享作者收到一条,actor 只有公开三列。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        after_like = _items(client)
        assert len(after_like) == 1
        item = after_like[0]
        assert item["kind"] == "like"
        assert item["read_at"] is None
        assert item["created_at"]
        assert set(item["actor"]) == {"display_name", "handle", "avatar_seed", "official"}
        assert item["actor"]["display_name"] == "Bob"
        assert item["actor"]["handle"] == "bob"
        assert item["share"] == {"id": share["id"], "title": share["title"], "kind": share["kind"]}
        assert "comment_preview" not in item

        assert bob.post(api(f"/shares/{share['id']}/favorite")).status_code == 204
        assert bob.post(api(f"/shares/{share['id']}/comments"), json={"body": "Nice work"}).status_code == 201

        data = _summary(client)
        assert [one["kind"] for one in data["items"]] == ["comment", "favorite", "like"]
        assert data["items"][0]["comment_preview"] == "Nice work"
        assert data["unread"] == 3
        assert len({one["id"] for one in data["items"]}) == 3

        # 互动者不是作者:他自己没有通知。
        assert _items(bob) == []
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 3
    finally:
        bob.close()


def test_self_interaction_produces_no_notification(client, db_path):
    """② 自己给自己的分享点赞 / 收藏 / 评论 → 没有通知。"""
    share = _published(client)

    assert client.post(api(f"/shares/{share['id']}/like")).status_code == 204
    assert client.post(api(f"/shares/{share['id']}/favorite")).status_code == 204
    assert client.post(api(f"/shares/{share['id']}/comments"), json={"body": "self"}).status_code == 201

    data = _summary(client)
    assert data["items"] == []
    assert data["unread"] == 0
    assert client.get(api("/notifications/unread-count")).json() == {"count": 0}
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 0


def test_unliking_and_unfavoriting_remove_the_unread_notification(client, app, db_path):
    """③ 取消点赞 / 收藏 → 对应未读通知消失(已读的不动,它是历史)。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert _summary(client)["unread"] == 1
        assert bob.delete(api(f"/shares/{share['id']}/like")).status_code == 204
        assert _summary(client)["items"] == []
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 0

        assert bob.post(api(f"/shares/{share['id']}/favorite")).status_code == 204
        assert _summary(client)["unread"] == 1
        assert bob.delete(api(f"/shares/{share['id']}/favorite")).status_code == 204
        assert _summary(client)["items"] == []
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 0

        # 已读之后取消:未读没了,已读那一行留作历史,不再断言"他还赞着"。
        assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert client.post(api("/notifications/read"), json={}).status_code == 200
        assert bob.delete(api(f"/shares/{share['id']}/like")).status_code == 204
        history = _summary(client)
        assert len(history["items"]) == 1
        assert history["items"][0]["read_at"] is not None
        assert history["unread"] == 0
    finally:
        bob.close()


def test_deleting_a_comment_deletes_its_notification(client, app, db_path):
    """③ 删评论 → 对应通知一起删(读没读过都删)。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        comment = bob.post(api(f"/shares/{share['id']}/comments"), json={"body": "temporary"}).json()["comment"]
        assert [one["kind"] for one in _items(client)] == ["comment"]
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 1

        assert bob.delete(api(f"/shares/{share['id']}/comments/{comment['id']}")).status_code == 204
        assert _summary(client)["items"] == []
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 0
    finally:
        bob.close()


def test_repeated_interactions_leave_at_most_one_unread(client, app, db_path):
    """④ 同一个人对同一条分享反复点赞 → 最多一条未读;连续评论也合并成一条未读。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        for _ in range(3):
            assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert len(_items(client)) == 1
        assert _summary(client)["unread"] == 1

        assert bob.delete(api(f"/shares/{share['id']}/like")).status_code == 204
        for _ in range(2):
            assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert len(_items(client)) == 1
        assert _summary(client)["unread"] == 1
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 1

        # 同一个人的第二条评论:未读仍是一条,comment_preview 指向最新那条。
        for body in ("first", "second"):
            assert bob.post(api(f"/shares/{share['id']}/comments"), json={"body": body}).status_code == 201
        comment_items = [one for one in _items(client) if one["kind"] == "comment"]
        assert len(comment_items) == 1
        assert comment_items[0]["comment_preview"] == "second"
        assert _summary(client)["unread"] == 2  # 一条 like + 一条 comment,不是四条
    finally:
        bob.close()


def test_pagination_and_unread_total(client, app, db_path):
    """⑤ 分页(新在前)+ unread 是总数,不是本页条数;unread-count 同一个数。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    carol = _actor(app, email="carol@example.com", name="Carol", handle="carol")
    dave = _actor(app, email="dave@example.com", name="Dave", handle="dave")
    try:
        assert bob.post(api(f"/shares/{share['id']}/comments"), json={"body": "from bob"}).status_code == 201
        assert carol.post(api(f"/shares/{share['id']}/favorite")).status_code == 204
        assert dave.post(api(f"/shares/{share['id']}/like")).status_code == 204

        _pin_newest_first(db_path, _items(client))

        first = client.get(api("/notifications?limit=2")).json()
        assert [one["kind"] for one in first["items"]] == ["like", "favorite"]
        assert first["next_cursor"]
        assert first["unread"] == 3

        second = client.get(api(f"/notifications?limit=2&cursor={first['next_cursor']}")).json()
        assert [one["kind"] for one in second["items"]] == ["comment"]
        assert second["next_cursor"] is None
        assert second["unread"] == 3

        assert client.get(api("/notifications/unread-count")).json() == {"count": 3}
    finally:
        bob.close()
        carol.close()
        dave.close()


def test_mark_read_by_ids_and_all(client, app):
    """⑥ POST /read 指定 ids / 不传就全标;别人的 id 标不动。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    carol = _actor(app, email="carol@example.com", name="Carol", handle="carol")
    try:
        assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert carol.post(api(f"/shares/{share['id']}/like")).status_code == 204
        items = _items(client)
        assert len(items) == 2
        newest = items[0]["id"]

        marked = client.post(api("/notifications/read"), json={"ids": [newest]}).json()
        assert marked == {"marked": 1, "unread": 1}
        by_id = {one["id"]: one for one in _items(client)}
        assert by_id[newest]["read_at"] is not None
        assert by_id[items[1]["id"]]["read_at"] is None

        # 别人的通知 id:同一个响应,但一行都不改;返回的未读是**调用者自己**的。
        someone_elses = items[1]["id"]
        stolen = bob.post(api("/notifications/read"), json={"ids": [someone_elses]}).json()
        assert stolen == {"marked": 0, "unread": 0}
        still = {one["id"]: one for one in _items(client)}
        assert still[someone_elses]["read_at"] is None
        assert _summary(client)["unread"] == 1

        # 空数组 = 明确"没有要标的",不等于全部。
        assert client.post(api("/notifications/read"), json={"ids": []}).json() == {"marked": 0, "unread": 1}

        # 完全不传 body = 全部标已读。
        assert client.post(api("/notifications/read")).json() == {"marked": 1, "unread": 0}
        assert all(one["read_at"] is not None for one in _items(client))
        assert client.get(api("/notifications/unread-count")).json() == {"count": 0}
    finally:
        bob.close()
        carol.close()


def test_notification_responses_never_leak_email(client, app, db_path):
    """⑦ 全字段扫描:没有 email 这个键,也没有任何账号邮箱当值;actor 恰好是公开三列。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        assert bob.post(api(f"/shares/{share['id']}/comments"), json={"body": "**plain** <b>text</b>"}).status_code == 201
        response = client.get(api("/notifications"))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()

        for path, leaf in leaves(payload):
            assert "email" not in path.lower(), path
            assert leaf not in {"alice@example.com", "bob@example.com"}, path
        assert "alice@example.com" not in response.text
        assert "bob@example.com" not in response.text
        assert set(payload["items"][0]["actor"]) == {"display_name", "handle", "avatar_seed", "official"}
        # 纯文本预览:原样截断,不渲染 markdown / HTML。
        assert payload["items"][0]["comment_preview"] == "**plain** <b>text</b>"

        long_body = "x" * 500
        longer = bob.post(api(f"/shares/{share['id']}/comments"), json={"body": long_body})
        assert longer.status_code == 201
        preview = next(one["comment_preview"] for one in _items(client) if one["kind"] == "comment")
        assert preview == "x" * 120
        assert len(preview) == 120
    finally:
        bob.close()


def test_soft_deleted_share_hides_its_notifications_without_deleting_rows(client, app, db_path):
    """⑦ 分享软删 → 通知过滤掉,但数据不删;未读数也不把它算进去。"""
    share = _published(client)
    bob = _actor(app, email="bob@example.com", name="Bob", handle="bob")
    try:
        assert bob.post(api(f"/shares/{share['id']}/like")).status_code == 204
        assert _summary(client)["unread"] == 1

        assert client.delete(api(f"/shares/{share['id']}")).status_code == 204

        hidden = _summary(client)
        assert hidden["items"] == []
        assert hidden["unread"] == 0
        assert client.get(api("/notifications/unread-count")).json() == {"count": 0}
        assert scalar(db_path, "SELECT COUNT(*) FROM cloud_share_notifications") == 1
        assert scalar(db_path, "SELECT status FROM cloud_shares WHERE id = ?", (share["id"],)) == "removed"
    finally:
        bob.close()


def test_notifications_require_a_session(client, app):
    """接口一律要登录;游客拿不到任何别人的东西。"""
    guest = TestClient(app)
    try:
        assert guest.get(api("/notifications")).status_code == 401
        assert guest.get(api("/notifications/unread-count")).status_code == 401
        assert guest.post(api("/notifications/read"), json={}).status_code == 401
    finally:
        guest.close()

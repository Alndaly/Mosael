"""分享:发布、列表(分页 / 排序 / 搜索)、详情、payload、下载、删除、按人列出。

钉住三件事:内容必须挂在身份上;`payload` 只在 `/payload` 与 `/download` 出;公开响应
逐字段扫描不到 email。
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from conftest import api, execute, scalar, signup

from community_helpers import leaves, make_identity, publish_ok, share_body

SHARE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def test_publishing_requires_a_session(client):
    response = client.post(api("/shares"), json=share_body())
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"


def test_publishing_without_a_display_name_is_409(client, db_path):
    """② 没有昵称 → 409 + "先起个名字";不是 401,也不是注册时就拦。"""
    signup(client)  # 注册即登录,但还没有身份
    response = client.post(api("/shares"), json=share_body())
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "identity_required"
    assert "名字" in body["message"]["zh"]
    assert "name" in body["message"]["en"]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_shares") == 0


def test_publish_returns_public_shape_without_payload_or_email(client):
    signup(client)
    make_identity(client, "Alice", "alice")
    payload = {"version": 1, "nodes": [{"id": "n1"}], "edges": []}
    share = publish_ok(client, payload=payload)

    assert SHARE_ID_RE.fullmatch(share["id"]), share["id"]
    assert share["kind"] == "workflow"
    assert share["title"] == "Space Opera"
    assert share["bytes"] == len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    assert share["license"] == "CC-BY-4.0"
    assert share["author"] == {
        "display_name": "Alice",
        "handle": "alice",
        "avatar_seed": share["author"]["avatar_seed"],
        "official": False,
    }
    assert share["stats"] == {"downloads": 0, "likes": 0, "favorites": 0, "comments": 0}
    assert share["liked_by_me"] is False
    assert share["favorited_by_me"] is False

    # 列表 / 详情都不带 payload —— 那是两次单独请求才拿的东西。
    assert "payload" not in share
    detail = client.get(api(f"/shares/{share['id']}")).json()
    assert "payload" not in detail
    assert client.get(api(f"/shares/{share['id']}/payload")).json()["payload"] == payload


def test_payload_over_two_megabytes_is_413_and_nothing_is_stored(client, db_path):
    """③ 超 2 MB → 413 + 人话;不静默截断。"""
    signup(client)
    make_identity(client)
    oversized = {"blob": "x" * (2 * 1024 * 1024 + 16)}
    response = client.post(api("/shares"), json=share_body(payload=oversized))
    assert response.status_code == 413, response.text
    assert response.json()["error"] == "payload_too_large"
    assert "2 MB" in response.json()["message"]["en"]
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_shares") == 0


def test_invalid_kind_is_422_and_nothing_is_stored(client, db_path):
    signup(client)
    make_identity(client)
    response = client.post(api("/shares"), json=share_body(kind="theme"))
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_kind"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_shares") == 0


def test_plugin_kind_is_published_listed_and_readable(client):
    """① `plugin` 和 workflow / board 一样能发、能按 kind 过滤、详情与 payload 都认它。"""
    signup(client)
    make_identity(client)
    plugin_payload = {"manifest": {"id": "mosael.example", "version": "1.0.0"}, "files": []}
    plugin = publish_ok(client, kind="plugin", title="Example Plugin", payload=plugin_payload)
    workflow = publish_ok(client, kind="workflow", title="A Workflow")

    assert plugin["kind"] == "plugin"
    assert client.get(api(f"/shares/{plugin['id']}")).json()["kind"] == "plugin"

    plugins = client.get(api("/shares?kind=plugin")).json()["items"]
    assert [item["id"] for item in plugins] == [plugin["id"]]
    workflows = client.get(api("/shares?kind=workflow")).json()["items"]
    assert [item["id"] for item in workflows] == [workflow["id"]]

    # payload 走的是和用户分享完全相同的那条路:没有第二套结构。
    assert client.get(api(f"/shares/{plugin['id']}/payload")).json()["payload"] == plugin_payload


def test_unknown_kind_is_still_rejected_everywhere(client):
    """① 加 `plugin` 不等于放开校验:非法 kind 在写、列表、过滤三处都还是 422。"""
    signup(client)
    make_identity(client)
    response = client.post(api("/shares"), json=share_body(kind="plugin "))
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_kind"
    assert client.get(api("/shares?kind=theme")).status_code == 422


def test_title_is_required_and_bounded(client):
    signup(client)
    make_identity(client)

    empty = client.post(api("/shares"), json=share_body(title="   "))
    assert empty.status_code == 422
    assert empty.json()["error"] == "title_required"

    long = client.post(api("/shares"), json=share_body(title="x" * 201))
    assert long.status_code == 422
    assert long.json()["error"] == "title_too_long"


def test_missing_payload_is_422(client):
    signup(client)
    make_identity(client)
    body = share_body()
    body.pop("payload")
    response = client.post(api("/shares"), json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_payload"


def test_malformed_json_body_is_422(client, db_path):
    """③ "合法 JSON" 由请求体解析把关;坏 JSON 不会变成半份工程文件存进库。"""
    signup(client)
    make_identity(client)
    response = client.post(
        api("/shares"),
        content=b'{"kind": "workflow", "title": "x", "payload": ',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_shares") == 0


def test_payload_exactly_at_two_megabytes_is_accepted(client):
    """③ 边界:正好 2 MB 收,不因为差一个字节把正常工程文件拒掉。"""
    signup(client)
    make_identity(client)
    payload = {"blob": "x" * (2 * 1024 * 1024 - len('{"blob":""}'))}
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) == 2 * 1024 * 1024
    share = publish_ok(client, payload=payload)
    assert share["bytes"] == 2 * 1024 * 1024


def test_download_returns_payload_and_counts(client):
    signup(client)
    make_identity(client)
    payload = {"version": 1, "nodes": [{"id": "n1"}]}
    share = publish_ok(client, payload=payload)

    for _ in range(2):
        response = client.post(api(f"/shares/{share['id']}/download"))
        assert response.status_code == 200, response.text
        assert response.json()["payload"] == payload

    detail = client.get(api(f"/shares/{share['id']}")).json()
    assert detail["stats"]["downloads"] == 2


def test_delete_is_author_only_and_soft_removes_the_share(client, app, db_path):
    signup(client, email="alice@example.com")
    make_identity(client)
    share = publish_ok(client)

    other = TestClient(app)
    try:
        signup(other, email="bob@example.com")
        forbidden = other.delete(api(f"/shares/{share['id']}"))
        # 不是作者 = 404:不区分"不存在"与"不是你的",也不给已删除的 id 留探测口。
        assert forbidden.status_code == 404, forbidden.text
        assert forbidden.json()["error"] == "share_not_found"
    finally:
        other.close()

    assert client.delete(api(f"/shares/{share['id']}")).status_code == 204
    # 软删:行还在,status 变了。
    assert scalar(db_path, "SELECT status FROM cloud_shares WHERE id = ?", (share["id"],)) == "removed"
    assert client.get(api(f"/shares/{share['id']}")).status_code == 404
    assert client.get(api(f"/shares/{share['id']}/payload")).status_code == 404
    assert client.post(api(f"/shares/{share['id']}/download")).status_code == 404
    assert client.get(api("/shares")).json()["items"] == []
    # 作者重复删除仍然 204(幂等)。
    assert client.delete(api(f"/shares/{share['id']}")).status_code == 204


def test_list_paginates_with_a_cursor_and_newest_first(client, db_path):
    """⑦ 分页 + new 排序。显式改 created_at,不依赖执行顺序。"""
    signup(client)
    make_identity(client)
    ids = {title: publish_ok(client, title=title)["id"] for title in ("first", "second", "third")}
    for day, title in enumerate(("first", "second", "third"), start=1):
        execute(
            db_path,
            "UPDATE cloud_shares SET created_at = ? WHERE id = ?",
            (f"2026-01-0{day} 00:00:00.000000", ids[title]),
        )

    first_page = client.get(api("/shares?limit=2")).json()
    assert [item["title"] for item in first_page["items"]] == ["third", "second"]
    assert first_page["next_cursor"]

    second_page = client.get(api(f"/shares?limit=2&cursor={first_page['next_cursor']}")).json()
    assert [item["title"] for item in second_page["items"]] == ["first"]
    assert second_page["next_cursor"] is None


def test_hot_sort_puts_interactions_first(client, db_path):
    """⑦ 排序:hot = 下载 + 点赞×3 + 收藏×2 + 评论。"""
    signup(client)
    make_identity(client)
    quiet = publish_ok(client, title="Quiet")
    loud = publish_ok(client, title="Loud")
    execute(db_path, "UPDATE cloud_shares SET created_at = ? WHERE id = ?", ("2026-02-01 00:00:00.000000", quiet["id"]))
    execute(db_path, "UPDATE cloud_shares SET created_at = ? WHERE id = ?", ("2026-01-01 00:00:00.000000", loud["id"]))

    assert client.post(api(f"/shares/{loud['id']}/like")).status_code == 204
    assert client.post(api(f"/shares/{loud['id']}/favorite")).status_code == 204
    assert client.post(api(f"/shares/{loud['id']}/comments"), json={"body": "nice"}).status_code == 201

    hot = client.get(api("/shares?sort=hot")).json()["items"]
    assert [item["title"] for item in hot] == ["Loud", "Quiet"]
    assert hot[0]["stats"] == {"downloads": 0, "likes": 1, "favorites": 1, "comments": 1}


def test_hot_sort_paginates(client):
    """⑦ hot 排序也走同一套游标(分数 → 时间 → id)。"""
    signup(client)
    make_identity(client)
    for title in ("One", "Two", "Three"):
        publish_ok(client, title=title)

    seen: list[str] = []
    cursor = ""
    for _ in range(4):
        page = client.get(api(f"/shares?sort=hot&limit=1&cursor={cursor}")).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"] or ""
        if not cursor:
            break
    assert len(seen) == 3
    assert len(set(seen)) == 3


def test_search_and_kind_filter(client):
    """⑦ 搜索 + kind 过滤。"""
    signup(client)
    make_identity(client)
    publish_ok(client, kind="workflow", title="Space Opera", summary="A workflow about stars.")
    publish_ok(client, kind="board", title="Story Board", summary="Pictures, not words.")

    found = client.get(api("/shares?q=space")).json()["items"]
    assert [item["kind"] for item in found] == ["workflow"]
    found_summary = client.get(api("/shares?q=stars")).json()["items"]
    assert [item["title"] for item in found_summary] == ["Space Opera"]

    boards = client.get(api("/shares?kind=board")).json()["items"]
    assert [item["title"] for item in boards] == ["Story Board"]

    # `plugin` 是合法 kind,只是这一页里还没有;真正非法的值仍然 422。
    assert client.get(api("/shares?kind=plugin")).json()["items"] == []
    assert client.get(api("/shares?kind=theme")).status_code == 422
    assert client.get(api("/shares?sort=random")).status_code == 422
    assert client.get(api("/shares?cursor=not-a-cursor")).status_code == 422


def test_user_shares_by_handle(client):
    signup(client)
    make_identity(client, "Alice", "alice")
    publish_ok(client, title="One")
    publish_ok(client, title="Two")

    response = client.get(api("/users/alice/shares"))
    assert response.status_code == 200, response.text
    assert {item["title"] for item in response.json()["items"]} == {"One", "Two"}

    missing = client.get(api("/users/nobody/shares"))
    assert missing.status_code == 404
    assert missing.json()["error"] == "user_not_found"


def test_viewer_flags_are_false_for_guests(client, app):
    signup(client)
    make_identity(client)
    share = publish_ok(client)
    assert client.post(api(f"/shares/{share['id']}/like")).status_code == 204
    assert client.post(api(f"/shares/{share['id']}/favorite")).status_code == 204

    mine = client.get(api("/shares")).json()["items"][0]
    assert mine["liked_by_me"] is True
    assert mine["favorited_by_me"] is True

    guest = TestClient(app)
    try:
        anonymous = guest.get(api("/shares")).json()["items"][0]
        assert anonymous["liked_by_me"] is False
        assert anonymous["favorited_by_me"] is False
        assert guest.get(api(f"/shares/{share['id']}")).status_code == 200
    finally:
        guest.close()


def test_public_responses_never_contain_email(client):
    """⑤ 全字段扫描:列表 / 详情 / 用户页 / 评论里都没有 email 键,也没有注册邮箱的值。"""
    signup(client)
    make_identity(client, "Alice", "alice")
    share = publish_ok(client)
    client.post(api(f"/shares/{share['id']}/comments"), json={"body": "hello"})

    responses = [
        client.get(api("/shares")),
        client.get(api(f"/shares/{share['id']}")),
        client.get(api(f"/shares/{share['id']}/comments")),
        client.get(api("/users/alice/shares")),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        for path, value in leaves(response.json()):
            assert not any(part == "email" for part in re.split(r"[.\[\]]", path)), path
            assert value != "alice@example.com", path
            assert "alice@example.com" not in str(value), path

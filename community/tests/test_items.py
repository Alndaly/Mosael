"""工作流与插件:提交、版本、审核、列表与详情、下载 / 点赞 / 浏览、举报与下架、index.json、官方条目导入。"""

from __future__ import annotations

import json

import pytest
from conftest import (
    API,
    login_as,
    make_plugin_zip,
    plugin_manifest,
    workflow_file,
)
from sqlalchemy import select

from community.catalog import seed_official
from community.config import REPO_ROOT
from community.models import Item, ItemDailyStat, ItemVersion
from mosael_formats.plugin_index import ENTRY_KEYS

ALICE = "+8613800000011"
BOB = "+8613800000012"
MOD = "+8613800000013"


def post_workflow(client, headers, data: bytes | None = None, **fields):
    return client.post(
        f"{API}/workflows",
        headers=headers,
        files={"file": ("flow.mosael-workflow.json", data or workflow_file(), "application/json")},
        data={"title": "我的流程", "summary": "一句话", "tags": "视频, 剪辑", **fields},
    )


def post_plugin(client, headers, data: bytes, path: str = "/plugins", **fields):
    return client.post(f"{API}{path}", headers=headers, files={"file": ("p.zip", data, "application/zip")}, data=fields)


# ---------------- 工作流 ----------------


def test_工作流发布即上架_标出运行代码节点(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    created = post_workflow(client, alice, workflow_file(with_code=True))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["published"] is True and body["has_code"] is True and body["node_count"] == 3
    assert body["code_node_types"] == ["code"]
    assert body["tags"] == ["剪辑", "视频"]
    assert body["submission"]["status"] == "approved"
    slug = body["slug"]

    listing = client.get(f"{API}/workflows").json()
    assert [one["slug"] for one in listing["items"]] == [slug] and listing["next_cursor"] is None
    assert client.get(f"{API}/workflows", params={"tag": "视频"}).json()["items"]
    assert client.get(f"{API}/workflows", params={"q": "流程"}).json()["items"]
    assert not client.get(f"{API}/workflows", params={"q": "nothing-like-this"}).json()["items"]

    detail = client.get(f"{API}/workflows/{slug}").json()
    assert detail["graph"]["nodes"][0]["id"] == "start"
    assert len(detail["downloads_30d"]) == 30


def test_不是工作流文件的提交被拒(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bad = post_workflow(client, alice, json.dumps({"format": "nope", "graph": {}}).encode())
    assert bad.status_code == 422
    assert bad.json()["error"] == {"code": "invalid_file", "message": "不是有效的 Mosael 工作流文件"}
    dangling = json.dumps(
        {"format": "mosael-workflow", "version": 1, "graph": {"nodes": [{"id": "a", "type": "x"}], "edges": [{"source": "a", "target": "zz"}]}}
    ).encode()
    assert post_workflow(client, alice, dangling).status_code == 422
    too_new = json.dumps({"format": "mosael-workflow", "version": 99, "graph": {"nodes": []}}).encode()
    en = client.post(
        f"{API}/workflows",
        headers={**alice, "Accept-Language": "en"},
        files={"file": ("f.json", too_new, "application/json")},
        data={"title": "t"},
    )
    assert "newer than this app supports" in en.json()["error"]["message"]


def test_工作流新版本只有作者能发(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    slug = post_workflow(client, alice).json()["slug"]
    bob = login_as(client, ctx, sms, BOB)
    denied = client.post(f"{API}/workflows/{slug}/versions", headers=bob, files={"file": ("f.json", workflow_file(), "application/json")})
    assert denied.status_code == 403
    ok = client.post(
        f"{API}/workflows/{slug}/versions", headers=alice, files={"file": ("f.json", workflow_file(), "application/json")}, data={"changelog": "修了"}
    )
    assert ok.status_code == 201 and ok.json()["version"] == "2"
    versions = client.get(f"{API}/workflows/{slug}/versions").json()
    assert [one["number"] for one in versions["items"]] == [2, 1]


def test_下载计数后跳到附件_点赞_浏览按天聚合(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    slug = post_workflow(client, alice).json()["slug"]
    bob = login_as(client, ctx, sms, BOB)
    response = client.get(f"{API}/workflows/{slug}/download", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/community-media/files/workflows/")
    assert response.headers["location"].endswith(".mosael-workflow.json")
    assert client.post(f"{API}/workflows/{slug}/like", headers=bob).json() == {"liked": True, "likes": 1}
    assert client.post(f"{API}/workflows/{slug}/like", headers=bob).json()["likes"] == 1
    client.get(f"{API}/workflows/{slug}")
    detail = client.get(f"{API}/workflows/{slug}", headers=bob).json()
    assert detail["downloads"] == 1 and detail["likes"] == 1 and detail["liked"] is True
    assert detail["downloads_30d"][-1]["count"] == 1
    with ctx.sessions() as db:
        row = db.scalars(select(ItemDailyStat)).one()
        assert (row.downloads, row.likes, row.views) == (1, 1, 2)
    assert client.delete(f"{API}/workflows/{slug}/like", headers=bob).json() == {"liked": False, "likes": 0}
    trending = client.get(f"{API}/workflows", params={"sort": "trending"}).json()["items"]
    assert trending[0]["slug"] == slug


def test_分页游标(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    for index in range(5):
        post_workflow(client, alice, title=f"flow number {index}")
    seen: list[str] = []
    cursor = None
    while True:
        page = client.get(f"{API}/workflows", params={"sort": "new", "limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [one["slug"] for one in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5
    assert client.get(f"{API}/workflows", params={"cursor": "!!!"}).status_code == 422


# ---------------- 插件 ----------------


def test_插件先进审核队列_通过后才公开(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    mod = login_as(client, ctx, sms, MOD, role="moderator")
    created = post_plugin(client, alice, make_plugin_zip(plugin_manifest()), tags="hello")
    assert created.status_code == 201, created.text
    assert created.json()["submission"]["status"] == "pending"
    assert created.json()["slug"] == "dev.someone.hello"
    assert client.get(f"{API}/plugins").json()["items"] == []
    assert client.get(f"{API}/plugins/dev.someone.hello").status_code == 404
    assert client.get(f"{API}/plugins/dev.someone.hello", headers=alice).status_code == 200
    assert client.get(f"{API}/admin/queue", headers=alice).status_code == 403

    queue = client.get(f"{API}/admin/queue", headers=mod).json()["items"]
    assert len(queue) == 1
    entry = queue[0]
    assert entry["permissions"] == ["network:example"]
    assert [one["path"] for one in entry["files"]] == ["main.py", "mosael.plugin.json"]
    assert entry["diff"]["previous_version"] is None
    assert entry["diff"]["permissions"]["added"] == ["network:example"]

    approved = client.post(f"{API}/admin/submissions/{entry['id']}/approve", headers=mod, json={"note": "ok"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    listing = client.get(f"{API}/plugins").json()["items"]
    assert [one["plugin_id"] for one in listing] == ["dev.someone.hello"]
    again = client.post(f"{API}/admin/submissions/{entry['id']}/approve", headers=mod)
    assert again.status_code == 409

    submissions = client.get(f"{API}/me/submissions", headers=alice).json()["items"]
    assert submissions[0]["status"] == "approved" and submissions[0]["review_note"] == "ok"


def test_新版本的差异_与只能升版本(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    mod = login_as(client, ctx, sms, MOD, role="admin")
    post_plugin(client, alice, make_plugin_zip(plugin_manifest()))
    first = client.get(f"{API}/admin/queue", headers=mod).json()["items"][0]
    client.post(f"{API}/admin/submissions/{first['id']}/approve", headers=mod)

    same = post_plugin(client, alice, make_plugin_zip(plugin_manifest()))
    assert same.status_code == 409 and same.json()["error"]["code"] == "version_exists"
    older = post_plugin(client, alice, make_plugin_zip(plugin_manifest(version="0.9.0")))
    assert older.status_code == 409 and older.json()["error"]["code"] == "version_not_newer"
    not_semver = post_plugin(client, alice, make_plugin_zip(plugin_manifest(version="latest")))
    assert not_semver.status_code == 422 and not_semver.json()["error"]["code"] == "plugin_version_invalid"

    v2 = plugin_manifest(version="1.1.0", permissions=["network:example", "fs:read"])
    v2["tools"]["declare"].append({"name": "shout", "label": "Shout"})
    response = post_plugin(
        client, alice, make_plugin_zip(v2, {"main.py": "print('changed')\n", "extra.py": "x"}), path="/plugins/dev.someone.hello/versions"
    )
    assert response.status_code == 201, response.text
    diff = client.get(f"{API}/admin/queue", headers=mod).json()["items"][0]["diff"]
    assert diff["previous_version"] == "1.0.0"
    assert diff["permissions"] == {"added": ["fs:read"], "removed": []}
    assert diff["tools"]["added"] == ["shout"]
    assert diff["files"]["added"] == ["extra.py"] and diff["files"]["changed"] == ["main.py", "mosael.plugin.json"]
    assert diff["manifest"]["changed"]["version"] == {"from": "1.0.0", "to": "1.1.0"}
    # 待审的新版本不影响公开的那一版
    assert client.get(f"{API}/plugins/dev.someone.hello").json()["version"] == "1.0.0"


def test_插件_id_归第一个提交者(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    post_plugin(client, alice, make_plugin_zip(plugin_manifest()))
    stolen = post_plugin(client, bob, make_plugin_zip(plugin_manifest(version="2.0.0")))
    assert stolen.status_code == 409 and stolen.json()["error"]["code"] == "plugin_id_taken"
    other = post_plugin(client, alice, make_plugin_zip(plugin_manifest(plugin_id="dev.someone.other")), path="/plugins/dev.someone.hello/versions")
    assert other.status_code == 422 and other.json()["error"]["code"] == "plugin_id_mismatch"


@pytest.mark.parametrize(
    ("archive", "expected"),
    [
        (make_plugin_zip(plugin_manifest(), {"../../evil.py": "x"}), "插件包里有越界路径"),
        (make_plugin_zip(plugin_manifest(), symlink="link"), "符号链接"),
        (make_plugin_zip(plugin_manifest(), {"/etc/cron.d/evil": "x"}), "越界路径"),
        (make_plugin_zip({"id": "x", "version": "1.0.0"}), "插件清单不合法"),
        (b"not a zip at all", "不是一个合法的 zip 包"),
        (make_plugin_zip(plugin_manifest(instance={"config": [{"key": "PATH"}]})), "盖掉宿主给插件的环境变量"),
        (make_plugin_zip(plugin_manifest(instance={"config": [{"key": "no_proxy"}]})), "盖掉宿主给插件的环境变量"),
    ],
)
def test_恶意或不合格的插件包(client, ctx, sms, archive: bytes, expected: str) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    response = post_plugin(client, alice, archive)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_file"
    assert expected in response.json()["error"]["message"]
    with ctx.sessions() as db:
        assert db.scalars(select(Item)).all() == []


def test_插件包太大(client, ctx, sms) -> None:
    ctx.settings.plugin_max_bytes = 1000
    alice = login_as(client, ctx, sms, ALICE)
    import os

    response = post_plugin(client, alice, make_plugin_zip(plugin_manifest(), {"blob.bin": os.urandom(5000)}))
    assert response.status_code == 413


def test_解压炸弹(client, ctx, sms) -> None:
    ctx.settings.plugin_max_unpacked_bytes = 10_000
    alice = login_as(client, ctx, sms, ALICE)
    response = post_plugin(client, alice, make_plugin_zip(plugin_manifest(), {"zeros.bin": b"\0" * 100_000}))
    assert response.status_code == 422 and "解压后超过" in response.json()["error"]["message"]


def test_index_json_与发版产物同形(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    mod = login_as(client, ctx, sms, MOD, role="moderator")
    post_plugin(client, alice, make_plugin_zip(plugin_manifest()))
    pending = client.get(f"{API}/plugins/index.json").json()
    assert pending == {"channel": "community", "plugins": []}
    entry = client.get(f"{API}/admin/queue", headers=mod).json()["items"][0]
    client.post(f"{API}/admin/submissions/{entry['id']}/approve", headers=mod)
    index = client.get(f"{API}/plugins/index.json").json()
    assert len(index["plugins"]) == 1
    plugin = index["plugins"][0]
    assert tuple(plugin) == ENTRY_KEYS
    registry = json.loads((REPO_ROOT / "website/public/plugins/registry.json").read_text(encoding="utf-8"))
    assert set(plugin) == set(registry["plugins"][0])
    # 下载地址钉在索引许的那一版上(和发版产物钉 tag 同一个道理:许的就是给的)
    assert plugin["download"] == "https://mosael.test/api/community/v1/plugins/dev.someone.hello/download?version=1.0.0"
    assert plugin["tools"][0]["effects"] == "none" and plugin["bundled"] is False


# ---------------- 举报与下架 ----------------


def test_举报进队列_下架后看不到(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    bob = login_as(client, ctx, sms, BOB)
    mod = login_as(client, ctx, sms, MOD, role="moderator")
    slug = post_workflow(client, alice).json()["slug"]
    report = client.post(f"{API}/workflows/{slug}/report", headers=bob, json={"reason": "spam", "detail": "广告"})
    assert report.status_code == 201
    dup = client.post(f"{API}/workflows/{slug}/report", headers=bob, json={"reason": "spam"})
    assert dup.status_code == 409
    reports = client.get(f"{API}/admin/reports", headers=mod).json()["items"]
    assert reports[0]["target"] == {"kind": "workflow", "slug": slug, "title": "我的流程"}

    hidden = client.post(f"{API}/admin/items/workflows/{slug}/hide", headers=mod, json={"reason": "spam"})
    assert hidden.status_code == 200
    assert client.get(f"{API}/workflows/{slug}").status_code == 410
    assert client.get(f"{API}/workflows").json()["items"] == []
    assert client.get(f"{API}/workflows/{slug}", headers=alice).status_code == 200
    assert client.get(f"{API}/admin/reports", headers=mod).json()["items"] == []
    client.post(f"{API}/admin/items/workflows/{slug}/hide", headers=mod, json={"hidden": False})
    assert client.get(f"{API}/workflows/{slug}").status_code == 200


# ---------------- 统计与主页 ----------------


def test_统计与作者主页(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    me = client.get(f"{API}/me", headers=alice).json()
    slug = post_workflow(client, alice).json()["slug"]
    client.get(f"{API}/workflows/{slug}/download", follow_redirects=False)
    overview = client.get(f"{API}/stats/overview").json()
    assert overview["users"] == 1 and overview["workflows"] == 1 and overview["downloads"] == 1
    assert overview["top_workflows"][0]["slug"] == slug
    series = client.get(f"{API}/stats/timeseries", params={"metric": "downloads", "days": 7}).json()
    assert len(series["points"]) == 7 and series["points"][-1]["value"] == 1
    signups = client.get(f"{API}/stats/timeseries", params={"metric": "signups", "days": 3}).json()
    assert signups["points"][-1]["value"] == 1
    assert client.get(f"{API}/stats/timeseries", params={"metric": "nope"}).status_code == 422

    profile = client.get(f"{API}/users/{me['handle']}").json()
    assert profile["workflows_count"] == 1 and profile["workflows"][0]["slug"] == slug
    assert len(profile["contributions"]) == 365 and profile["contributions"][-1]["count"] == 1
    assert client.get(f"{API}/users/nobody_here").status_code == 404


# ---------------- 官方条目 ----------------


def test_官方条目导入_幂等(client, ctx) -> None:
    root = REPO_ROOT / "website" / "public"
    with ctx.sessions() as db:
        first = seed_official(ctx, db, root)
    assert first.created and not first.new_versions
    with ctx.sessions() as db:
        second = seed_official(ctx, db, root)
        assert not second.created and not second.new_versions
        items = db.scalars(select(Item)).all()
        assert all(item.official for item in items)
        assert db.scalar(select(ItemVersion).limit(1)) is not None
    registry = json.loads((root / "plugins/registry.json").read_text(encoding="utf-8"))
    catalog = json.loads((root / "workflows/catalog.json").read_text(encoding="utf-8"))
    plugins = client.get(f"{API}/plugins", params={"official": "true", "limit": 50}).json()["items"]
    # 官方条目的 slug 和官网现有地址一致:插件是 plugins/ 下的目录名,工作流是模板 id 把 _ 换成 -
    directories = {path.parent.name for path in (REPO_ROOT / "plugins").glob("*/*/mosael.plugin.json")}
    assert {one["slug"] for one in plugins} == directories
    assert {one["plugin_id"] for one in plugins} == {one["id"] for one in registry["plugins"]}
    assert plugins[0]["author"]["handle"] == "official" and plugins[0]["official"] is True
    workflows = client.get(f"{API}/workflows", params={"limit": 50}).json()["items"]
    assert {one["slug"] for one in workflows} == {one["id"].replace("_", "-") for one in catalog}
    # 官方插件的包在 GitHub Release 上;缺省的 index.json 只列社区插件
    assert client.get(f"{API}/plugins/index.json").json()["plugins"] == []
    official_index = client.get(f"{API}/plugins/index.json", params={"include": "official"}).json()["plugins"]
    assert all(entry["download"].startswith("https://github.com/") for entry in official_index)
    slug = catalog[0]["id"].replace("_", "-")
    en = client.get(f"{API}/workflows/{slug}/download", params={"locale": "en"}, follow_redirects=False)
    assert en.headers["location"].endswith(f"{slug}.en.mosael-workflow.json")
    detail = client.get(f"{API}/workflows/{slug}", headers={"Accept-Language": "en"}).json()
    assert detail["graph"]["nodes"] and detail["extra"]["stages"]


def test_发新版本时可以一起改标题简介标签封面(client, ctx, sms) -> None:
    """应用「重新发布」时带的是和新建同一组字段:file、title、summary、tags(JSON 数组字符串)、cover。"""
    import io

    from PIL import Image

    alice = login_as(client, ctx, sms, ALICE)
    slug = post_workflow(client, alice, tags='["a", "b"]').json()["slug"]
    assert client.get(f"{API}/workflows/{slug}").json()["tags"] == ["a", "b"]
    cover = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(cover, format="PNG")
    response = client.post(
        f"{API}/workflows/{slug}/versions",
        headers=alice,
        files={"file": ("f.json", workflow_file(), "application/json"), "cover": ("c.png", cover.getvalue(), "image/png")},
        data={"title": "新标题", "summary": "新简介", "tags": '["c"]'},
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"{API}/workflows/{slug}").json()
    assert (detail["title"], detail["summary"], detail["tags"]) == ("新标题", "新简介", ["c"])
    assert detail["cover_url"].endswith(".png")
    # 没给的字段不动
    client.post(f"{API}/workflows/{slug}/versions", headers=alice, files={"file": ("f.json", workflow_file(), "application/json")})
    assert client.get(f"{API}/workflows/{slug}").json()["title"] == "新标题"


def test_保留的_slug_与官方插件的地址不能被占(client, ctx, sms) -> None:
    alice = login_as(client, ctx, sms, ALICE)
    assert post_workflow(client, alice, title="new").json()["slug"] != "new"
    for plugin_id in ("new", "new-version"):
        response = post_plugin(client, alice, make_plugin_zip(plugin_manifest(plugin_id=plugin_id)))
        assert response.status_code == 409 and response.json()["error"]["code"] == "plugin_id_taken"
    with ctx.sessions() as db:
        seed_official(ctx, db, REPO_ROOT / "website" / "public")
    for plugin_id in ("baidu-pan", "dev.mosael.baidu-pan"):
        response = post_plugin(client, alice, make_plugin_zip(plugin_manifest(plugin_id=plugin_id)))
        assert response.status_code == 409 and response.json()["error"]["code"] == "plugin_id_taken"

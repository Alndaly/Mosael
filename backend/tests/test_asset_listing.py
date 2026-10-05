"""素材列表分页(`GET /api/assets`)、各种类数量(`GET /api/assets/facets`)和时间线用到的素材
(`GET /api/sequences/{id}/assets`)。

此前 `GET /api/assets` 一次交回整个工作区的每一份素材、带着完整的 media_info:一千二百份素材是
将近 1 MB 的 JSON,素材页把它们一次全画出来,打开要好几秒。现在列表是一页一页的、只带卡片要的字段,
筛选和排序在服务端做;页签上的数字另取;剪辑台要的完整字段按时间线取。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.util import fresh_client, insert_asset, second_client

T0 = datetime(2026, 1, 1, 12, 0, 0)


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _page(client, ws: str, **params) -> dict:
    response = client.get("/api/assets", params={"workspace_id": ws, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _walk(client, ws: str, **params) -> list[str]:
    """顺着游标一页页往下翻,交回见到的 id(按页的顺序)。"""
    seen: list[str] = []
    cursor = None
    for _ in range(50):
        page = _page(client, ws, **params, **({"cursor": cursor} if cursor else {}))
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("游标翻不到头")


def test_the_list_is_paged_newest_first_and_every_asset_shows_up_exactly_once() -> None:
    client = fresh_client()
    ws = _workspace(client)
    ids = [insert_asset(ws, kind="image", name=f"a{n}", created_at=T0 + timedelta(minutes=n)) for n in range(7)]
    # 同一时刻建的两份:排序只看时间的话,翻页时会在页边上重复或漏掉其中一份。
    ids += [insert_asset(ws, kind="image", name=f"same{n}", created_at=T0 + timedelta(minutes=3)) for n in range(2)]

    first = _page(client, ws, limit=3)
    assert len(first["items"]) == 3
    assert first["total"] == 9
    assert first["next_cursor"]

    walked = _walk(client, ws, limit=3)
    assert sorted(walked) == sorted(ids), "每一份都出现,而且只出现一次"
    assert walked[0] == ids[6], "最新导入的在最前"
    assert walked[-1] == ids[0]


def test_filters_run_on_the_server() -> None:
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    other = client.post("/api/projects", json={"workspace_id": ws, "name": "O"}).json()["id"]
    beach = insert_asset(ws, kind="video", name="Beach Day", tags=["海边", "b-roll"])
    voice = insert_asset(ws, kind="audio", name="旁白", tags=["b-roll"], source="tts")
    still = insert_asset(ws, kind="image", name="cover", original_filename="SUNSET.png", project_id=project)
    theirs = insert_asset(ws, kind="image", name="100%_done", project_id=other)
    doc = insert_asset(ws, kind="document", name="brief")

    def ids(**params) -> set[str]:
        return {item["id"] for item in _page(client, ws, **params)["items"]}

    assert ids(kind=["video", "audio"]) == {beach, voice}
    assert ids(kind="document") == {doc}
    assert ids(q="beach") == {beach}, "名字不分大小写"
    assert ids(q="sunset") == {still}, "也搜原始文件名"
    assert ids(q="海") == {beach}, "也搜标签"
    assert ids(q="%") == {theirs}, "% 是字面上的百分号,不是通配符"
    assert ids(tag=["b-roll", "海边"]) == {beach}, "默认要同时带有"
    assert ids(tag=["b-roll", "海边"], tag_match="any") == {beach, voice}
    assert ids(source="tts") == {voice}
    assert ids(project_id=project) == {beach, voice, still, doc}, "项目里看得到工作区级素材,看不到别的项目的"
    assert _page(client, ws, kind="video", q="nothing")["total"] == 0


def test_sorting_is_the_servers_job_and_survives_paging() -> None:
    client = fresh_client()
    ws = _workspace(client)
    short = insert_asset(ws, kind="audio", name="banana", media_info={"duration": 2.5}, created_at=T0)
    long = insert_asset(ws, kind="video", name="Apple", media_info={"duration": 90}, created_at=T0 + timedelta(minutes=1))
    still = insert_asset(ws, kind="image", name="cherry", created_at=T0 + timedelta(minutes=2))
    middle = insert_asset(ws, kind="video", name="date", media_info={"duration": 30}, created_at=T0 + timedelta(minutes=3))

    assert _walk(client, ws, sort="name", limit=1) == [long, short, still, middle], "按名字升序,不分大小写"
    assert _walk(client, ws, sort="duration", limit=1) == [long, middle, short, still], "按时长降序,没有时长的垫底"
    assert _walk(client, ws, sort="created", limit=2) == [middle, still, long, short]

    renamed = client.patch(f"/api/assets/{short}", json={"name": "banana 2"})
    assert renamed.status_code == 200
    assert _walk(client, ws, sort="updated", limit=3)[0] == short, "刚改过的在最前"


def test_a_card_carries_what_a_card_shows_and_nothing_else() -> None:
    client = fresh_client()
    ws = _workspace(client)
    insert_asset(
        ws, kind="video", name="clip", file_key="media/x/clip.mp4", tags=["t"],
        media_info={"duration": 12.0, "width": 1920, "height": 1080, "fps": 25.0, "has_thumbnail": True,
                    "proxy_status": "ready", "proxy_key": "media/x/proxy.mp4", "source_url": "https://example.com/v"},
    )
    insert_asset(ws, kind="document", name="brief", media_info={"format": "pdf", "pages": 3, "size_bytes": 2048})

    items = {item["name"]: item for item in _page(client, ws)["items"]}
    clip = items["clip"]
    assert clip["media_info"] == {
        "duration": 12.0, "width": 1920, "height": 1080, "fps": 25.0, "has_thumbnail": True,
        "format": None, "pages": None, "size_bytes": None,
    }
    assert "file_key" not in clip, "文件位置是取文件那几个接口的事,卡片不带"
    assert clip["tags"] == ["t"]
    assert {"id", "kind", "name", "source", "derived", "ai_generated", "created_at", "updated_at"} <= set(clip)
    assert "derived_from" not in clip, "整份出处不带:一段成片的出处可以是两百多份素材"
    assert items["brief"]["media_info"]["pages"] == 3
    # 详情另取:那里照旧是完整的。
    full = client.get(f"/api/assets/{clip['id']}").json()
    assert full["media_info"]["proxy_key"] == "media/x/proxy.mp4"


def test_one_unreadable_number_does_not_take_the_whole_page_down() -> None:
    client = fresh_client()
    ws = _workspace(client)
    insert_asset(ws, kind="audio", name="broken", media_info={"duration": float("nan"), "width": "wide"})
    insert_asset(ws, kind="audio", name="fine", media_info={"duration": 3.0})

    items = {item["name"]: item for item in _page(client, ws)["items"]}
    assert items["broken"]["media_info"]["duration"] is None
    assert items["broken"]["media_info"]["width"] is None
    assert items["fine"]["media_info"]["duration"] == 3.0


def test_a_cursor_is_only_good_for_the_list_it_came_from() -> None:
    client = fresh_client()
    ws = _workspace(client)
    for n in range(3):
        insert_asset(ws, kind="image", name=f"a{n}")
    cursor = _page(client, ws, limit=1)["next_cursor"]

    garbage = client.get("/api/assets", params={"workspace_id": ws, "cursor": "not-a-cursor"})
    assert garbage.status_code == 422
    other_sort = client.get("/api/assets", params={"workspace_id": ws, "cursor": cursor, "sort": "name"})
    assert other_sort.status_code == 422, "按时间排的游标拿去按名字翻,只会翻出错乱的一页"
    assert client.get("/api/assets", params={"workspace_id": ws, "limit": 1000}).status_code == 422
    assert client.get("/api/assets", params={"workspace_id": ws, "sort": "size"}).status_code == 422


def test_facets_count_every_kind_and_tag_whatever_the_search_says() -> None:
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    insert_asset(ws, kind="video", name="v1", tags=["海边"])
    insert_asset(ws, kind="video", name="v2", tags=["海边", "b-roll"])
    insert_asset(ws, kind="audio", name="a1", project_id=project)
    insert_asset(ws, kind="image", name="i1", tags=["b-roll"])

    facets = client.get("/api/assets/facets", params={"workspace_id": ws}).json()
    assert facets["total"] == 4
    assert facets["kinds"] == {"video": 2, "audio": 1, "image": 1}
    assert facets["tags"] == {"海边": 2, "b-roll": 2}

    other = client.post("/api/projects", json={"workspace_id": ws, "name": "O"}).json()["id"]
    scoped = client.get("/api/assets/facets", params={"workspace_id": ws, "project_id": other}).json()
    assert scoped["total"] == 3, "别的项目的那份不算,工作区级的算"


def test_strangers_see_neither_the_list_nor_the_facets() -> None:
    client = fresh_client()
    ws = _workspace(client)
    insert_asset(ws, kind="image", name="a")
    stranger = second_client("stranger")
    assert stranger.get("/api/assets", params={"workspace_id": ws}).status_code == 404
    assert stranger.get("/api/assets/facets", params={"workspace_id": ws}).status_code == 404


def test_the_editor_gets_the_full_assets_its_timeline_uses() -> None:
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    used = insert_asset(ws, kind="video", name="used", project_id=project,
                        media_info={"duration": 5.0, "proxy_status": "ready", "has_waveform": True})
    insert_asset(ws, kind="video", name="unused", project_id=project, media_info={"duration": 5.0})
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "Main"}).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    for start in (0, 5):
        placed = client.post(
            f"/api/sequences/{sequence['id']}/clips",
            json={"track_id": track["id"], "asset_id": used, "timeline_start": start, "src_in": 0, "src_out": 5},
        )
        assert placed.status_code == 200, placed.text

    assets = client.get(f"/api/sequences/{sequence['id']}/assets").json()
    assert [one["id"] for one in assets] == [used], "用到几次都只给一份,没用到的不给"
    assert assets[0]["media_info"]["proxy_status"] == "ready", "剪辑台要完整字段"
    assert second_client("stranger").get(f"/api/sequences/{sequence['id']}/assets").status_code == 404

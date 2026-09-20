"""智能体删素材 / 删项目:这一档撤不回来,所以卡上说的话必须就是待会儿真做的事。

这两个工具是用户反馈加的:他让智能体"把这几个下载源一起删掉",而智能体只有改名、移动项目、
打标签 —— 它算得出清单,却只能让用户自己去界面上一个个点。
"""

from __future__ import annotations

from tests.util import fresh_client


def _workspace(client):
    return client.post("/api/workspaces", json={"name": "W"}).json()


def _asset(client, ws, name: str, project_id: str | None = None):
    return client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "kind": "video",
            "name": name,
            "file_key": f"media/{name}.mp4",
            **({"project_id": project_id} if project_id else {}),
        },
    ).json()


def test_删素材的卡是永久删除那一档() -> None:
    """`edit` 那一档的定义是"最坏也撤得回",而这件事撤不回来 —— 标成 edit 就是在用户点
    批准前唯一会看的那行字上说谎。"""
    client = fresh_client()
    ws = _workspace(client)
    one = _asset(client, ws, "a")
    card = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "delete_assets", "payload": {"asset_ids": [one["id"]]}},
    ).json()

    assert card["permission"] == "destroy"
    assert "撤不回来" in card["summary"]
    assert "a" in card["summary"], "卡上要写出名字 —— 只说「1 个素材」的话,用户没法核对"

    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert client.get(f"/api/assets/{one['id']}").status_code == 404


def test_卡上要说清时间线会受什么影响() -> None:
    """删掉之后片段会变成脱机占位、而那条序列就导不出去了 —— 批准之前必须知道。"""
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = _asset(client, ws, "b-roll", project["id"])
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 5},
    )

    card = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "delete_assets", "payload": {"asset_ids": [asset["id"]]}},
    ).json()
    assert "1 个片段" in card["summary"], card["summary"]

    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["offline_clips"] == 1
    after = client.get(f"/api/sequences/{sequence['id']}").json()
    clip = next(t for t in after["tracks"] if t["kind"] == "video")["clips"][0]
    assert clip["offline_asset"]["name"] == "b-roll"


def test_有一个不在这个工作区就整张卡不开() -> None:
    """按"这一批"给用户看,执行时却只删掉其中几个,那张卡说的话就不是真的了 ——
    而这一档没有第二次机会去纠正。"""
    client = fresh_client()
    ws = _workspace(client)
    mine = _asset(client, ws, "mine")
    refused = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "delete_assets", "payload": {"asset_ids": [mine["id"], "nope"]}},
    )
    assert refused.status_code == 422
    assert "nope" in refused.text
    assert client.get(f"/api/assets/{mine['id']}").status_code == 200, "一张开不出来的卡不该动任何东西"


def test_一次删太多就拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    refused = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "delete_assets", "payload": {"asset_ids": [f"x{i}" for i in range(21)]}},
    )
    assert refused.status_code == 422
    assert "20" in refused.text


def test_删项目连时间线一起没_素材回到工作区() -> None:
    """素材**不跟着删**。这句话卡上一定要说:否则用户会以为批准删项目就等于把里面的素材
    也清了,反过来也会不敢批。"""
    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "旧稿"}).json()
    asset = _asset(client, ws, "keep-me", project["id"])
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()

    card = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "delete_projects", "payload": {"project_ids": [project["id"]]}},
    ).json()
    assert card["permission"] == "destroy"
    assert "旧稿" in card["summary"]
    assert "不会被删" in card["summary"], card["summary"]

    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert client.get(f"/api/sequences/{sequence['id']}").status_code == 404
    kept = client.get(f"/api/assets/{asset['id']}").json()
    assert kept["project_id"] is None, "素材要回到工作区,而不是跟着项目一起没"


def test_删除不会被自动放行() -> None:
    """自动放行里 destroy 和 external 走同一条路:没有可枚举的判据,一律回到人。
    "帮我清理一下" 不该变成一次无人值守的删除。"""
    from app.domain.agent import rules

    ruling = rules.evaluate("delete_assets", {"asset_ids": ["x"]}, rules.normalize(None))
    assert ruling.denied, "删除没有放行判据,必须弹卡"

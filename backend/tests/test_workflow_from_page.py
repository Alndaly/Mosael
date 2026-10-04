"""内嵌浏览器顶栏「用当前页开工」(`POST /api/workflows/from-page`)。

三张分析模板(视频爆款拆解 / 账号运营诊断 / 评论区洞察):建好一张(或打开已建的那张),把当前页的链接填进开始
节点,数据来源默认「内嵌浏览器」,并且**用当前这个浏览器档案**去读页面(打开浏览器那一步换成浏览器池 + 这个档案;
爆款拆解里下载视频那一步也借它的登录态)。

钉住的:
- 没建过就按模板建一张,名字是模板名;建过就打开最近改过的那张、改它的参数(写成新的一版,不另起一张);
- 绑着定时任务的那张不动它 —— 改了链接,定时任务下一次就去分析别的东西了;另建一张;
- 没有档案(比如 RPA 会话视图)时只填链接和数据来源,读页面那一步照模板原样;
- 档案要是这个人用得了的(别人的私有档案被拒);
- 别的模板不接。
"""
from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ScheduledTask, Workflow
from app.domain.workflows.templates_analysis import ACCOUNT_ANALYSIS, COMMENT_INSIGHTS, VIRAL_VIDEO_BREAKDOWN
from tests.util import fresh_client, second_client

VIDEO = "https://www.bilibili.com/video/BV1xx411c7mD"
ACCOUNT = "https://space.bilibili.com/2"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _profile(client, workspace_id: str, name: str = "B 站号") -> str:
    response = client.post("/api/browser/profiles", json={"workspace_id": workspace_id, "name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _start(client, workspace_id: str, template_id: str, url: str, profile_id: str | None = None):
    return client.post("/api/workflows/from-page", json={
        "workspace_id": workspace_id, "template_id": template_id, "url": url, "profile_id": profile_id,
    })


def _nodes(graph: dict, node_type: str) -> list[dict]:
    return [node for node in graph["nodes"] if node["type"] == node_type]


def test_没建过就按模板建一张_链接填进开始节点_读页面用这个档案() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    profile_id = _profile(client, workspace_id)
    response = _start(client, workspace_id, VIRAL_VIDEO_BREAKDOWN, VIDEO, profile_id)
    assert response.status_code == 200, response.text
    workflow = response.json()
    graph = workflow["graph"]
    assert graph["meta"]["template_id"] == VIRAL_VIDEO_BREAKDOWN
    params = _nodes(graph, "start")[0]["config"]["params"]
    assert params["video_link"] == VIDEO
    assert params["data_source"] == "browser"
    opens = _nodes(graph, "browser_open")
    assert opens and all(node["config"]["session_mode"] == "pool" and node["config"]["profile_id"] == profile_id for node in opens)
    imports = _nodes(graph, "import_url")
    assert imports and all(node["config"]["profile_id"] == profile_id for node in imports)
    assert workflow["name"] in ("自媒体视频爆款拆解", "Why a video went viral")


def test_建过就打开那张_改它的参数_不另起一张() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    profile_id = _profile(client, workspace_id)
    first = _start(client, workspace_id, COMMENT_INSIGHTS, VIDEO, profile_id).json()
    other_video = "https://www.bilibili.com/video/BV1GJ411x7h7"
    second = _start(client, workspace_id, COMMENT_INSIGHTS, other_video, profile_id)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first["id"]
    assert _nodes(second.json()["graph"], "start")[0]["config"]["params"]["video_link"] == other_video
    revisions = client.get(f"/api/workflows/{first['id']}/revisions").json()
    assert len(revisions) == 2
    with SessionLocal() as db:
        assert db.query(Workflow).filter(Workflow.workspace_id == workspace_id).count() == 1


def test_账号诊断填的是账号链接() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _start(client, workspace_id, ACCOUNT_ANALYSIS, ACCOUNT)
    assert response.status_code == 200, response.text
    params = _nodes(response.json()["graph"], "start")[0]["config"]["params"]
    assert params["account_link"] == ACCOUNT
    assert params["data_source"] == "browser"


def test_没有档案时只填链接和数据来源_读页面那一步照模板原样() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _start(client, workspace_id, VIRAL_VIDEO_BREAKDOWN, VIDEO)
    assert response.status_code == 200, response.text
    opens = _nodes(response.json()["graph"], "browser_open")
    assert all(node["config"]["session_mode"] == "named" for node in opens)
    assert all(node["config"].get("profile_id", "") == "" for node in _nodes(response.json()["graph"], "import_url"))


def test_绑着定时任务的那张不动_另建一张() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    first = _start(client, workspace_id, COMMENT_INSIGHTS, VIDEO).json()
    # 直接落一条定时任务:建任务的接口会先试跑检查(测试库里没有对话模型,检查过不去),而这里要的只是「绑着」。
    with SessionLocal() as db:
        db.add(ScheduledTask(
            workspace_id=workspace_id, name="每天看评论", kind="workflow", trigger_type="manual",
            payload={"workflow_id": first["id"]},
        ))
        db.commit()
    second = _start(client, workspace_id, COMMENT_INSIGHTS, "https://www.bilibili.com/video/BV1GJ411x7h7")
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first["id"]
    kept = client.get(f"/api/workflows/{first['id']}").json()
    assert _nodes(kept["graph"], "start")[0]["config"]["params"]["video_link"] == VIDEO


def test_别人的私有档案借不了() -> None:
    owner = fresh_client("owner")
    workspace_id = _workspace(owner)
    profile_id = _profile(owner, workspace_id)
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace_id}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    assert mate.post(f"/api/invitations/{invitation['id']}/accept").status_code == 200
    response = _start(mate, workspace_id, VIRAL_VIDEO_BREAKDOWN, VIDEO, profile_id)
    assert response.status_code == 403, response.text


def test_别的模板不接() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _start(client, workspace_id, "highlight_shorts", VIDEO)
    assert response.status_code == 422


def test_链接只认_http_s() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    assert _start(client, workspace_id, VIRAL_VIDEO_BREAKDOWN, "javascript:alert(1)").status_code == 422

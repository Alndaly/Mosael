"""共享来的生成会话**只能看**。

生成会话是某人的私人工作线程。主人把它共享进工作区,是给同事看:历史、产出、花费都看得到。而此前写操作只查了
「看得见」,于是同事能把别人的会话改名、删掉、收进自己的分组;更隐蔽的是换模型 —— 会话记着的是连接,连接归个人,
同事在别人的会话里一换模型,就把**他自己的**连接写进了别人的会话。

读写两道闸在 domain/generation/sessions:看 = 是主人或共享进了这个工作区(看不见就 404);写 = 还得是主人(403)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client, second_client


def _team() -> tuple[TestClient, str, TestClient]:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _session(owner: TestClient, workspace: str, *, shared: bool, title: str = "海报几版", kind: str = "image") -> str:
    session = owner.post(
        "/api/generation/sessions", json={"workspace_id": workspace, "title": title, "kind": kind}
    ).json()
    if shared:
        owner.post(f"/api/shares/generation_session/{session['id']}", json={"workspace_id": workspace})
    return session["id"]


def test_共享来的会话_同事看得见_标着不是他的() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)

    listed = mate.get(f"/api/generation/sessions?workspace_id={workspace}").json()
    assert [(one["id"], one["is_mine"]) for one in listed] == [(sid, False)]
    assert mate.get(f"/api/generation/jobs?workspace_id={workspace}&session_id={sid}").status_code == 200


def test_共享来的会话_同事改不了_删不了_收不进分组_换不了模型() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)

    for body in (
        {"title": "我改的"},
        {"group_id": "whatever"},
        {"provider_profile_id": None, "model": "gpt-image-1", "kind": "image"},
    ):
        res = mate.patch(f"/api/generation/sessions/{sid}", json=body)
        assert res.status_code == 403, (body, res.text)
        assert "主人" in res.json()["detail"] or "owner" in res.json()["detail"]
    assert mate.delete(f"/api/generation/sessions/{sid}").status_code == 403

    kept = owner.get(f"/api/generation/sessions?workspace_id={workspace}").json()[0]
    assert (kept["title"], kept["model"], kept["group_id"]) == ("海报几版", None, None)


def test_共享来的会话_同事不能在里面生成() -> None:
    """在拒绝之前什么都不做:不解析模型、不渲参考、不传素材(见 operations._named_session)。"""
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)
    res = mate.post("/api/generation/jobs", json={
        "workspace_id": workspace, "session_id": sid, "provider": "openai", "model": "gpt-image-1",
        "kind": "image", "prompt": "一张海报",
    })
    assert res.status_code == 403, res.text
    assert owner.get(f"/api/generation/jobs?workspace_id={workspace}&session_id={sid}").json() == []


def test_没共享的会话_同事连它在不在都不知道() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=False)
    assert mate.patch(f"/api/generation/sessions/{sid}", json={"title": "x"}).status_code == 404
    assert mate.delete(f"/api/generation/sessions/{sid}").status_code == 404


def test_主人照常能改_回来的那一份仍说是他的() -> None:
    owner, workspace, _mate = _team()
    sid = _session(owner, workspace, shared=True)
    renamed = owner.patch(f"/api/generation/sessions/{sid}", json={"title": "定稿"})
    assert renamed.status_code == 200
    assert (renamed.json()["title"], renamed.json()["is_mine"], renamed.json()["shared"]) == ("定稿", True, True)
    assert owner.delete(f"/api/generation/sessions/{sid}").status_code == 204


def test_会话列表按种类筛_生成页和音频页各看各的() -> None:
    owner, workspace, _mate = _team()
    image = _session(owner, workspace, shared=False, title="海报", kind="image")
    video = _session(owner, workspace, shared=False, title="短片", kind="video")
    audio = _session(owner, workspace, shared=False, title="片尾曲", kind="audio")
    untyped = owner.post("/api/generation/sessions", json={"workspace_id": workspace}).json()

    def ids(query: str) -> set[str]:
        return {one["id"] for one in owner.get(f"/api/generation/sessions?workspace_id={workspace}{query}").json()}

    # 没说种类的会话归「生成」页(图像)—— 会话一定有种类,否则哪一页都不列它。
    assert untyped["kind"] == "image"
    assert ids("&kind=image&kind=video") == {image, video, untyped["id"]}
    assert ids("&kind=audio") == {audio}
    assert ids("") == {image, video, audio, untyped["id"]}


# ---------- 任务总线上的那一行,跟着生成所在的会话走 ----------
#
# 每次生成在任务中心(`/api/jobs`)也有一行,payload 里就是提示词和整份请求。此前那几条路由只查了工作区成员,
# 于是别人私有会话里写的提示词,在任务中心和生成页的进度列表里谁都看得到 —— 「私有」只挡住了会话列表。


def _generation_job(workspace: str, sid: str, prompt: str = "一张不想给别人看的海报") -> str:
    from app.core.db import SessionLocal
    from app.db.models import GenerationJob, User
    from app.domain.jobs import create_job

    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "tester").one()
        job = create_job(
            db, workspace_id=workspace, kind="ai_generation", created_by=owner.id,
            payload={"subject": prompt, "request": {"prompt": prompt}},
        )
        db.add(GenerationJob(
            workspace_id=workspace, session_id=sid, job_id=job.id, provider="test", model="m", kind="image",
            request={"prompt": prompt},
        ))
        db.commit()
        return job.id


def _jobs_seen(client: TestClient, workspace: str) -> set[str]:
    res = client.get(f"/api/jobs?workspace_id={workspace}&kind=ai_generation")
    assert res.status_code == 200, res.text
    return {job["id"] for job in res.json()}


def test_没共享的会话_它的生成任务同事在任务中心看不到() -> None:
    owner, workspace, mate = _team()
    job = _generation_job(workspace, _session(owner, workspace, shared=False))

    assert job not in _jobs_seen(mate, workspace)
    missing = mate.get("/api/jobs/no-such-job")
    for res in (
        mate.get(f"/api/jobs/{job}"),
        mate.get(f"/api/jobs/{job}/events"),
        mate.get(f"/api/jobs/{job}/children"),
        mate.post(f"/api/jobs/{job}/cancel"),
    ):
        assert (res.status_code, res.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Job not found"})
    assert owner.get(f"/api/jobs/{job}").json()["status"] == "queued"

    assert job in _jobs_seen(owner, workspace)
    assert owner.get(f"/api/jobs/{job}/events").status_code == 200


def test_共享来的会话_它的生成任务同事看得见_取消不了() -> None:
    """看是共享给他的;取消是在主人的会话里写 —— 那是主人正在付钱的一次生成。"""
    owner, workspace, mate = _team()
    job = _generation_job(workspace, _session(owner, workspace, shared=True))

    assert job in _jobs_seen(mate, workspace)
    assert mate.get(f"/api/jobs/{job}").status_code == 200
    denied = mate.post(f"/api/jobs/{job}/cancel")
    assert denied.status_code == 403, denied.text
    assert owner.get(f"/api/jobs/{job}").json()["status"] == "queued"
    assert owner.post(f"/api/jobs/{job}/cancel").status_code == 200


def test_不挂在会话上的任务_仍是工作区的() -> None:
    from app.core.db import SessionLocal
    from app.domain.jobs import create_job

    owner, workspace, mate = _team()
    with SessionLocal() as db:
        job = create_job(db, workspace_id=workspace, kind="export", created_by=None, payload={})
        db.commit()
        job_id = job.id
    assert mate.get(f"/api/jobs/{job_id}").status_code == 200
    assert job_id in {one["id"] for one in mate.get(f"/api/jobs?workspace_id={workspace}").json()}

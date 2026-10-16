"""拆镜头在界面上那条路(ADR 0061 §5):素材详情页点一下排一条任务、再读这份视频的镜头表。

第一步(量刀口、取帧、判画面、落库、三个工作流节点)已经在了,缺的是**对外入口**。这份测试守的就是那个入口:

① 任务种类在目录里 —— 任务中心据此显示名字、决定要不要提示、做完刷哪些数据、能取消;
② 读镜头表:没拆过是 200 + `status="none"`,**不是 404**(「还没拆」和「看不到这份素材」是两件事);拆过是那份表;
③ `analyze_asset` 的 `mode="shots"` 排的是**同一条任务**(同一个 kind、同一张表),不是另开一条路;
④ 逐镜的帧图取得到;名字不在那个形状里的取不到(不是把素材目录里的任何文件发出去)。

量 + 取帧用 ffmpeg 现造的小片子(四段纯色,刀口在 1/2/3 秒),和 test_shots_breakdowns 同一招;没有视觉模型时
机器那一半照样交(不碰网络)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import mcp_server
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, ShotBreakdown, User
from app.domain.assets import use_cases
from app.domain.shots import breakdowns
from tests.util import fresh_client, insert_asset, user_id, wait_settled

HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _make_cut_video(target: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=white:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=yellow:s=320x180:r=25:d=1",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(target)],
        check=True, timeout=60,
    )


def _me() -> User:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one()


@pytest.fixture
def client():
    return fresh_client()


@pytest.fixture
def video(client):
    """素材库里一份真实的 4 秒四刀口小片子(和 test_shots_breakdowns 同一份造法)。"""
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "test-shots-api"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    asset_id = insert_asset(
        ws_id, kind="video", name="刀口样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    yield {"id": asset_id, "workspace_id": ws_id}
    shutil.rmtree(media / "test-shots-api", ignore_errors=True)


# --------------------------------------------------------------------------------------
# ① 任务种类:任务中心看得到、有名字、能取消
# --------------------------------------------------------------------------------------

def test_拆镜头在任务种类目录里(client) -> None:
    """目录里的一行决定任务中心怎么显示它。**可取消不用在这里声明** —— 它是 in-process 任务,
    走的是 `POST /api/jobs/{id}/cancel` 那条通用路(任务总线按状态判,不按种类判)。"""
    zh = client.get("/api/jobs/kinds", headers={"Accept-Language": "zh-CN"}).json()
    entry = next((one for one in zh["kinds"] if one["kind"] == "shot_breakdown"), None)
    assert entry == {
        "kind": "shot_breakdown", "label": "拆镜头", "announce": "always",
        "affects": ["assets"], "view": "media", "record_field": None,
    }
    en = client.get("/api/jobs/kinds", headers={"Accept-Language": "en-US"}).json()
    assert {one["kind"]: one["label"] for one in en["kinds"]}["shot_breakdown"] == "Shot breakdown"


# --------------------------------------------------------------------------------------
# ② 读镜头表:没拆过 != 404
# --------------------------------------------------------------------------------------

def test_没拆过的视频读出来是未拆过(client, video) -> None:
    body = client.get(f"/api/assets/{video['id']}/shots")
    assert body.status_code == 200, "「还没拆过」是一次正常的回答,不是 404"
    shape = body.json()
    assert shape["asset_id"] == video["id"] and shape["status"] == "none"
    assert shape["shots"] == [] and shape["sheets"] == [] and shape["hints"] == []
    assert shape["report_markdown"] == "" and shape["storyboard_markdown"] == ""
    assert shape["updated_at"] is None


def test_看不到的素材还是404(client) -> None:
    """「还没拆」是 200,「没有这份素材」不能也变成 200 —— 那就分不出「未拆过」和「不是你的」。"""
    assert client.get("/api/assets/no-such-asset/shots").status_code == 404


def test_只有视频可以拆(client) -> None:
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    image_id = insert_asset(ws_id, kind="image", name="图", file_key="", media_info={})
    assert client.post(f"/api/assets/{image_id}/shots").status_code == 422
    with SessionLocal() as db:
        with pytest.raises(breakdowns.ShotBreakdownError) as err:
            use_cases.start_shots(db, _me(), image_id)
        assert err.value.key == "shotsErr_notVideo"


# --------------------------------------------------------------------------------------
# ③ 点一下:排任务、任务表 / 任务中心看得到、跑完读得到表
# --------------------------------------------------------------------------------------

def test_点一下排一条任务_任务表里看得到_跑完读得到那张表(client, video) -> None:
    started = client.post(f"/api/assets/{video['id']}/shots")
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["kind"] == "shot_breakdown" and job["payload"]["asset_id"] == video["id"]
    assert job["status"] in ("queued", "running")
    assert job["message"], "任务上带着一句给人看的话(拆镜头排队中)"

    listed = client.get("/api/jobs", params={"workspace_id": video["workspace_id"], "kind": "shot_breakdown"}).json()
    assert [one["id"] for one in listed] == [job["id"]], "任务表里看得到它"
    panel = client.get("/api/jobs/center", params={"workspace_id": video["workspace_id"]}).json()
    assert job["id"] in [one["id"] for one in panel["jobs"]], "任务中心里也看得到它"

    assert wait_settled(client, job["id"]) == "succeeded"
    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["result"]["asset_id"] == video["id"] and detail["result"]["shots"] == 4

    shape = client.get(f"/api/assets/{video['id']}/shots").json()
    assert shape["status"] == "ready"
    assert shape["id"] and shape["asset_id"] == video["id"]
    assert shape["params"]["threshold"] > 0
    assert shape["meta"]["duration"] == pytest.approx(4.0, abs=0.2)
    assert len(shape["shots"]) == 4
    first = shape["shots"][0]
    #: 刀口、起止、时长、实测动静是**代码量的**(ADR 0061 的第一半);景别运镜那一半要视觉模型,这里没有。
    assert first["id"] == "S01" and first["start"] == pytest.approx(0.0, abs=0.05)
    assert first["seconds"] == pytest.approx(1.0, abs=0.2)
    assert isinstance(first["motion"], float)
    assert "size" not in first, "没配视觉模型时不该有模型判出来的那几栏"
    assert shape["sheets"] and shape["sheets"][0] == {
        "index": 1, "first": "S01", "last": "S04", "a": "sheet-01a.jpg", "b": "sheet-01b.jpg",
    }
    assert shape["stats"]["shots"] == 4
    assert "## 镜头表" in shape["report_markdown"]
    assert "**S01**" in shape["storyboard_markdown"]
    assert shape["updated_at"]


def test_重拆还是同一份表(client, video) -> None:
    """一份视频一份镜头表(ADR 0061 待拍板 2):再点一次是覆盖,不是多一份。"""
    first = client.post(f"/api/assets/{video['id']}/shots").json()
    assert wait_settled(client, first["id"]) == "succeeded"
    with SessionLocal() as db:
        row_id = breakdowns.breakdown_for(db, video["id"]).id
    second = client.post(f"/api/assets/{video['id']}/shots").json()
    assert wait_settled(client, second["id"]) == "succeeded"
    with SessionLocal() as db:
        rows = db.query(ShotBreakdown).filter_by(asset_id=video["id"]).all()
        assert [row.id for row in rows] == [row_id]


def test_量到一半能停(client, video, monkeypatch) -> None:
    """它是 in-process 任务,「取消」走任务中心那条通用路(`POST /api/jobs/{id}/cancel`)。

    量 / 取帧 / 每判完一批之间都问一句「还要不要我」(jobs.ensure_wanted),所以停下之后**不会留下半张表**,
    也不会被收尾的 `finish_job` 改回 succeeded(见 test_job_cancellation)。
    """
    import threading

    from app.domain.analysis import shots_task

    started, release = threading.Event(), threading.Event()
    real = breakdowns.measure_into

    def slow(*args, **kwargs):
        started.set()
        assert release.wait(20), "没等到放行"
        return real(*args, **kwargs)

    monkeypatch.setattr(shots_task.breakdowns, "measure_into", slow)
    job = client.post(f"/api/assets/{video['id']}/shots").json()
    assert started.wait(20), "任务没跑起来"

    stopped = client.post(f"/api/jobs/{job['id']}/cancel")
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"

    release.set()
    assert wait_settled(client, job["id"]) == "cancelled", "取消之后不许有人把它改成 succeeded"
    assert client.get(f"/api/assets/{video['id']}/shots").json()["status"] == "none", "停下了就不该留下半张表"


# --------------------------------------------------------------------------------------
# ④ 逐镜的帧图(详情页那些缩略图)
# --------------------------------------------------------------------------------------

def test_帧图取得到_别的名字取不到(client, video) -> None:
    job = client.post(f"/api/assets/{video['id']}/shots").json()
    assert wait_settled(client, job["id"]) == "succeeded"

    frame = client.get(f"/api/assets/{video['id']}/shots/frames/S01a.jpg")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
    assert frame.content[:2] == b"\xff\xd8", "真的是张 JPEG"

    for bad in ("S01c.jpg", "sheet-01a.jpg", "nope.jpg", "S01a.png"):
        assert client.get(f"/api/assets/{video['id']}/shots/frames/{bad}").status_code == 404, bad
    assert client.get("/api/assets/no-such-asset/shots/frames/S01a.jpg").status_code == 404


# --------------------------------------------------------------------------------------
# ⑤ 对话里「拆一下镜头」一步到位:analyze_asset 的 mode="shots"
# --------------------------------------------------------------------------------------

def test_analyze_asset_的_shots_模式排的是同一条任务(client, video) -> None:
    with mcp_server.calling_as(user_id=user_id(), requested_by="test"):
        job = mcp_server.analyze_asset(video["id"], mode="shots")
    assert job["kind"] == "shot_breakdown" and job["payload"]["asset_id"] == video["id"]
    assert job["status"] in ("queued", "running")
    assert "answer" not in job, "这个模式不回分析结论,回的是一条任务"

    assert wait_settled(client, job["id"]) == "succeeded"
    shape = client.get(f"/api/assets/{video['id']}/shots").json()
    assert shape["status"] == "ready" and len(shape["shots"]) == 4, "排出来的和素材页那个按钮是同一张表"


def test_智能体那一路用的是这次对话的连接和模型(client, video) -> None:
    """会话里定下的连接和模型照用(和 analyze 同一个来源);会话里选的**视频看法**管不到它 ——
    `mode="shots"` 不是「怎么喂视频」,那条路(`mcp_server._queue_shot_breakdown`)根本不读它。"""
    target = SimpleNamespace(connection=SimpleNamespace(id="profile-from-session"), model="vision-from-session",
                             mode="native")
    with SessionLocal() as db:
        job = use_cases.start_shots(db, _me(), video["id"], session_target=target)
        assert job.kind == "shot_breakdown"
        assert job.payload["profile_id"] == "profile-from-session"
        assert job.payload["model"] == "vision-from-session"
        assert job.payload["surface"] == "automation"
        assert job.payload["threshold"] == 0.3, "界面 / 对话都不传阈值,用默认的那个"
        job_id = job.id
        db.commit()
    #: 这条连接不存在,跑起来挑不到视觉模型 → 机器那一半照样交(和没配视觉连接时同一条路)。
    assert wait_settled(client, job_id) == "succeeded"
    assert client.get(f"/api/assets/{video['id']}/shots").json()["status"] == "ready"

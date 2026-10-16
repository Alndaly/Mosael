"""analyze_asset 换喂法(ADR 0061 §3):抽帧路按镜头抽、每张图标镜号;两条路都带上已有镜头表。

视觉调用打桩(monkeypatch service.call_vision_model),收提示词与帧;视频用 ffmpeg 现造的四刀口小片子。

**镜头路的数量由镜头数决定,不由时长决定**:镜数 ≤ `MAX_VISUAL_FRAMES` 每镜一张中点帧;超过就交联系表
(全片每一镜都在里面),交不完的记一条 `hints`。时长只在没有镜头信息时用来猜密度(均匀回落)。
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, ShotBreakdown
from app.domain.analysis import service
from app.domain.shots import breakdowns, detect, frames
from tests.util import fresh_client, insert_asset

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


@pytest.fixture
def client():
    return fresh_client()


@pytest.fixture
def video_asset(client):
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "test-shots-analysis"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    asset_id = insert_asset(
        ws_id, kind="video", name="刀口样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    with SessionLocal() as db:
        yield db.get(Asset, asset_id)
    shutil.rmtree(media / "test-shots-analysis", ignore_errors=True)


def _shots(count: int, duration: float = 4.0) -> list[dict]:
    """`count` 个时长均匀的假镜头(时间码落在时长里;取帧拼表只用得到刀口和时长)。"""
    step = duration / count
    return [{"id": detect.shot_id(index), "start": round((index - 1) * step, 3), "end": round(index * step, 3),
             "seconds": round(step, 3), "motion": 0.0}
            for index in range(1, count + 1)]


def _write_breakdown(asset: Asset, shots: list[dict], *, duration: float, sheets: list[dict] | None = None) -> None:
    with SessionLocal() as db:
        db.add(ShotBreakdown(
            asset_id=asset.id, workspace_id=asset.workspace_id, lang="zh", params={},
            meta={"duration": duration}, cuts=[], shots=shots, sheets=sheets or [],
        ))
        db.commit()


def _write_sheets_on_disk(asset: Asset, shots: list[dict]) -> list[dict]:
    """把这一份表的联系表按量刀口那条路的样子落盘(`shots/frames/` + `shots/sheets/`),
    帧用 PIL 造(不跑 ffmpeg),返回 `row.sheets` 该有的样子。"""
    root = breakdowns.shots_dir(asset)
    for shot in shots:
        for point in frames.FRAME_POINTS:
            target = root / "frames" / frames.frame_name(shot["id"], point)
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (320, 180), (80, 120, 160)).save(target, "JPEG")
    return frames.make_sheets(shots, root / "frames", root / "sheets", 16 / 9)


def _add_vision_profile(client) -> None:
    client.post("/api/settings/providers", json={"name": "Kimi", "vendor": "moonshot",
                                                 "config": {"api_key": "sk-moonshot"}})


def _video_asset(client, duration: float) -> Asset:
    """一段**真有这么长**的片子(media_info 的时长就是它):时长 × 镜数 的各种组合都在真片长上跑,
    镜头表里的时间码落在片子里、取帧取得到。"""
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    #: 一份素材一个目录:`shots/` 挂在这份素材的目录下,别和别的片子共用(见 domain/shots/breakdowns)。
    media = settings.media_dir / "test-shots-analysis" / uuid4().hex[:8]
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"long-{duration:g}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s=320x180:r=25:d={duration:g}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)],
        check=True, timeout=120,
    )
    asset_id = insert_asset(
        ws_id, kind="video", name="长片样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": duration, "width": 320, "height": 180, "fps": 25},
    )
    with SessionLocal() as db:
        return db.get(Asset, asset_id)


def _captured_analyze(client, monkeypatch, asset_id: str, question: str = "这条片子的节奏怎么样?") -> dict:
    from app.db.models import User

    captured: dict = {}

    def fake_call(db, profile, messages, call=None, **kwargs):
        captured["messages"] = messages
        return "看完了"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    response = client.post(f"/api/assets/{asset_id}/analyze", json={"question": question, "mode": "frames"})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
        result = service.analyze_asset(db, db.get(Asset, asset_id), question,
                                       mode="frames", user_id=me)
    captured["result"] = result
    return captured


def _image_count(messages: list) -> int:
    return len([part for part in messages[0]["content"] if part["type"] == "image_url"])


def _hints(asset_id: str) -> list[dict]:
    """这条素材那份镜头表上的提示(路由那条路会提交,所以另开一个会话读得到)。"""
    with SessionLocal() as db:
        row = db.scalar(select(ShotBreakdown).where(ShotBreakdown.asset_id == asset_id))
        return list(row.hints) if row is not None else []


def _content_text(messages: list) -> tuple[str, list[str]]:
    """第一段是提示词正文;后面每隔一张图前面那段 `【…】` 是这张图的标注(中点帧或联系表)。"""
    parts = messages[0]["content"]
    labels = [part["text"] for part in parts[1:] if part["type"] == "text"]
    return parts[0]["text"], labels


def test_frames_path_samples_per_shot_with_labels(client, video_asset, monkeypatch) -> None:
    """没拆过镜头:现场量刀口(只量刀口那一路),每镜一帧取中点,每张图前标 S0X · 起–止。"""
    _add_vision_profile(client)
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    assert "按镜头抽取的" in text
    assert "【S01 · 0:00.0–0:01.0】" in labels
    assert "【S04 · 0:03.0–0:04.0】" in labels
    assert len(labels) == 4  # 4 镜 ≤ MAX_VISUAL_FRAMES,每镜一帧(不是按时长算出来的 4)
    parts = captured["messages"][0]["content"]
    images = [p for p in parts if p["type"] == "image_url"]
    assert len(images) == 4
    assert captured["result"]["frames"] == 4


def test_frames_path_uses_existing_breakdown_and_sends_shot_table(client, video_asset, monkeypatch) -> None:
    """拆过镜头:直接用表里的刀口(不再量一遍),提示词带上判过的景别运镜。"""
    _add_vision_profile(client)
    with SessionLocal() as db:
        db.add(ShotBreakdown(
            asset_id=video_asset.id, workspace_id=video_asset.workspace_id, lang="zh",
            params={}, meta={"duration": 4.0},
            cuts=[{"time": 2.0, "score": 0.9}],
            shots=[{"id": "S01", "start": 0.0, "end": 2.0, "seconds": 2.0, "motion": 0.1,
                    "size": "wide", "camera": ["static"], "dialogue": "开场", "frame": "海边的全景"},
                   {"id": "S02", "start": 2.0, "end": 4.0, "seconds": 2.0, "motion": 5.0}],
            sheets=[],
        ))
        db.commit()
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    #: 表里的两镜直接用,不现量(两刀口的片子若现量会出四个标注)。
    assert labels == ["【S01 · 0:00.0–0:02.0】", "【S02 · 0:02.0–0:04.0】"]
    #: 两条路都带镜头表:量好的刀口时长、判过的景别运镜。
    assert "【镜头表(刀口和时长是代码量的,准确" in text
    assert "全景" in text and "固定" in text


def test_short_fast_cut_is_not_squeezed_by_duration(client, monkeypatch) -> None:
    """6 秒 6 镜:数量 = 镜头数(6),不再被时长算出来的 4 压到。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 6.0)
    _write_breakdown(asset, _shots(6, duration=6.0), duration=6.0)
    captured = _captured_analyze(client, monkeypatch, asset.id)
    _text, labels = _content_text(captured["messages"])
    assert len(labels) == 6, "6 镜就是 6 张,不是时长算出来的 4"
    assert labels[0].startswith("【S01 ") and labels[-1].startswith("【S06 ")
    assert _image_count(captured["messages"]) == 6
    assert captured["result"]["frames"] == 6
    assert service.fallback_frame_count(6.0) == 4  # 回落口径仍是 4 —— 两套数不一样才是重点


def test_two_shots_in_a_long_video_get_two_frames(client, monkeypatch) -> None:
    """90 秒 2 镜:给 2 张(每镜一张),不再按时长给 15 张几乎一样的图。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 90.0)
    _write_breakdown(asset, _shots(2, duration=90.0), duration=90.0)
    captured = _captured_analyze(client, monkeypatch, asset.id)
    _text, labels = _content_text(captured["messages"])
    assert len(labels) == 2
    assert _image_count(captured["messages"]) == 2
    assert captured["result"]["frames"] == 2
    assert service.fallback_frame_count(90.0) == 15  # 回落口径下这条片子本来会给 15 张


def test_more_shots_than_budget_hands_over_contact_sheets(client, monkeypatch) -> None:
    """200 秒 53 镜:超过预算走联系表 —— 三组表(6 张)把**最后一镜**也覆盖到,不再只看到前 16 镜。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 200.0)
    shots = _shots(53, duration=200.0)
    made = _write_sheets_on_disk(asset, shots)
    _write_breakdown(asset, shots, duration=200.0, sheets=made)
    assert len(made) == 3  # 25 + 25 + 3
    captured = _captured_analyze(client, monkeypatch, asset.id)
    text, labels = _content_text(captured["messages"])
    assert "按镜头抽取的" not in text and "联系表" in text
    assert len(labels) == 6 and _image_count(captured["messages"]) == 6  # 3 组 A/B
    #: 53 镜每一镜都在这三组的覆盖范围里 —— 不是只看到前 16 镜。
    assert labels == [
        "【联系表 1 · S01–S25 · 15% 处】", "【联系表 1 · S01–S25 · 85% 处】",
        "【联系表 2 · S26–S50 · 15% 处】", "【联系表 2 · S26–S50 · 85% 处】",
        "【联系表 3 · S51–S53 · 15% 处】", "【联系表 3 · S51–S53 · 85% 处】",
    ]
    #: 交的是盘上那份表本身(不是又现场拼一遍)。
    parts = captured["messages"][0]["content"]
    first_image = next(part for part in parts if part["type"] == "image_url")
    sheet_file = breakdowns.shots_dir(asset) / "sheets" / made[0]["a"]
    assert first_image["image_url"]["url"].endswith(base64.b64encode(sheet_file.read_bytes()).decode())
    assert _hints(asset.id) == [], "全交出去了,不该有提示"


def test_sheets_over_the_call_budget_say_what_is_missing(client, monkeypatch) -> None:
    """交不完时不许硬交、也不许装作全看到了:前 `MAX_SHEET_GROUPS` 组交出去,剩下的记一条提示。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 300.0)
    shots = _shots(100, duration=300.0)
    made = _write_sheets_on_disk(asset, shots)
    _write_breakdown(asset, shots, duration=300.0, sheets=made)
    captured = _captured_analyze(client, monkeypatch, asset.id)
    text, labels = _content_text(captured["messages"])
    assert len(labels) == service.MAX_SHEET_GROUPS * 2
    assert labels == [
        "【联系表 1 · S01–S25 · 15% 处】", "【联系表 1 · S01–S25 · 85% 处】",
        "【联系表 2 · S26–S50 · 15% 处】", "【联系表 2 · S26–S50 · 85% 处】",
        "【联系表 3 · S51–S75 · 15% 处】", "【联系表 3 · S51–S75 · 85% 处】",
    ]
    hints = _hints(asset.id)
    assert hints == [{"shot": "S76", "kind": "sheets_truncated", "field": "", "value": "S100"}]
    #: 没交出来的那段也对模型直说了(不许装作全看到了)。
    assert "S76" in text and "S100" in text and "没在表里的镜头你没看到" in text


def test_sheets_are_built_on_the_fly_without_writing_into_the_asset_dir(client, monkeypatch) -> None:
    """没拆过镜头(表是现场量的、`shots/sheets/` 还是空的):现场拼表交出去 —— 但只写临时目录,
    没有表的素材不该凭空多出一个 `shots/`(「一份素材一份表」)。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 200.0)
    shots = _shots(53, duration=200.0)
    monkeypatch.setattr(service, "_breakdown_shots_for", lambda _db, _asset, _path: (shots, None))
    captured = _captured_analyze(client, monkeypatch, asset.id)
    text, labels = _content_text(captured["messages"])
    assert "联系表" in text and len(labels) == 6
    assert labels == [
        "【联系表 1 · S01–S25 · 15% 处】", "【联系表 1 · S01–S25 · 85% 处】",
        "【联系表 2 · S26–S50 · 15% 处】", "【联系表 2 · S26–S50 · 85% 处】",
        "【联系表 3 · S51–S53 · 15% 处】", "【联系表 3 · S51–S53 · 85% 处】",
    ], "现场拼的表也要覆盖到最后一镜"
    assert _image_count(captured["messages"]) == 6
    assert not (breakdowns.shots_dir(asset) / "sheets").exists(), "没表的素材不该多出一个 shots/"


def test_no_sheets_at_all_degrades_visibly_instead_of_pretending(client, monkeypatch) -> None:
    """表拿不到(现场拼也失败):退一步按预算抽中点帧,但记一条提示 + 对模型说清没看全。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 200.0)
    shots = _shots(53, duration=200.0)
    _write_breakdown(asset, shots, duration=200.0)  # 有表,但没有 sheets(旧数据 / 文件被删)

    def _cannot_build(*_args, **_kwargs):
        raise frames.ShotFramesError("shotsErr_noFrames")

    monkeypatch.setattr(frames, "sheets_in_memory", _cannot_build)
    captured = _captured_analyze(client, monkeypatch, asset.id)
    text, labels = _content_text(captured["messages"])
    assert len(labels) == service.MAX_VISUAL_FRAMES  # 退一步:预算内的中点帧,不是一张都没有
    assert labels[-1].startswith("【S53 "), "退一步也要覆盖到最后一镜(均匀挑,不是只挑前几镜)"
    hints = _hints(asset.id)
    assert hints == [{"shot": "", "kind": "sheets_unavailable", "field": "", "value": "53"}]
    assert "不是每一镜都看到了" in text


def test_repeated_analysis_keeps_one_hint_per_kind(client, monkeypatch) -> None:
    """重跑分析:同类提示不叠加(记在镜头表上的是「这次」的状态,不是流水账)。"""
    _add_vision_profile(client)
    asset = _video_asset(client, 300.0)
    shots = _shots(100, duration=300.0)
    made = _write_sheets_on_disk(asset, shots)
    _write_breakdown(asset, shots, duration=300.0, sheets=made)
    _captured_analyze(client, monkeypatch, asset.id)
    _captured_analyze(client, monkeypatch, asset.id)
    assert [hint["kind"] for hint in _hints(asset.id)] == ["sheets_truncated"]


def test_native_path_also_carries_shot_table(client, video_asset, monkeypatch) -> None:
    """原生那条路也带镜头表(ADR:两条路都带)。"""
    _add_vision_profile(client)
    with SessionLocal() as db:
        db.add(ShotBreakdown(
            asset_id=video_asset.id, workspace_id=video_asset.workspace_id, lang="zh",
            params={}, meta={"duration": 4.0}, cuts=[],
            shots=[{"id": "S01", "start": 0.0, "end": 4.0, "seconds": 4.0, "motion": 0.1,
                    "size": "close", "camera": ["static"], "frame": "主播特写"}],
            sheets=[],
        ))
        db.commit()
    captured: dict = {}

    def fake_call(db, profile, messages, call=None, **kwargs):
        captured["messages"] = messages
        return "看完了"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    from app.db.models import User

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
        result = service.analyze_asset(db, db.get(Asset, video_asset.id), "什么景别?",
                                       mode="native", user_id=me)
    assert result["mode"] == "native"
    prompt = captured["messages"][0]["content"][0]["text"]
    assert "【镜头表" in prompt and "特写" in prompt


def test_no_breakdown_falls_back_to_even_frames(client, video_asset, monkeypatch) -> None:
    """量刀口失败(比如替身视频读不出):回落老喂法 —— 均匀抽帧,数量仍按时长算(4 秒片子 4 张)。

    这条路的签名也不许动:既有测试替身按 `extract_video_frames(path)` 单参形状挂着
    (见 test_analysis.test_analyze_auto_falls_back_to_frames)。"""
    _add_vision_profile(client)
    calls: list[tuple] = []
    real = service.extract_video_frames

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "extract_video_frames", spy)
    monkeypatch.setattr(service, "_breakdown_shots_for", lambda _db, _asset, _path: ([], None))
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    assert "按时间均匀抽取" in text
    assert labels == []
    assert captured["result"]["frames"] == service.fallback_frame_count(4.0) == 4
    assert calls and {len(args) for args, _kwargs in calls} == {1}, "回落仍走 extract_video_frames(path) 单参"

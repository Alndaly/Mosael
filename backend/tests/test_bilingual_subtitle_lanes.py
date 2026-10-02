"""双语分两条字幕轨:两条各占一处,预览和导出一致。

审查时:预览(Monitor)只画找到的第一条,导出把两条都烧在同一个位置 —— 预览少一种语言,成片两行字压成一团。
规则(哪条轨是哪一道、奇数道换到画面另一头)由 contracts/text-layer-cases.json 与 subtitle-cases.json 钉住;
这里在真时间线 → 渲染计划 → ffmpeg 命令这条路上看两道是不是真的分开了。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.render import build_plan_for_sequence
from app.media.render_executor import build_ffmpeg_command
from tests.util import fresh_client


def _bilingual(client) -> str:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 4.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    for text in ("你好", "Hello"):
        seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
        track = [t for t in seq["tracks"] if t["kind"] == "subtitle"][-1]["id"]
        response = client.post(f"/api/sequences/{sid}/subtitles/generate",
                               json={"track_id": track, "cues": [{"text": text, "timeline_start": 0.0, "duration": 2.0}]})
        assert response.status_code == 200, response.text
    return sid


def test_两条字幕轨各占一道_先建的那条在原位(tmp_path: Path) -> None:
    client = fresh_client()
    sid = _bilingual(client)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sid)
    lanes = {item.text: item.lane for item in plan.subtitles}
    assert lanes == {"你好": 0, "Hello": 1}


def test_导出的两道字幕不在同一个位置(tmp_path: Path) -> None:
    client = fresh_client()
    sid = _bilingual(client)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sid)
    # 按预览 CSS 渲染的 PNG 那条路:两张一样大的字幕图,叠加坐标的 y 必须不同。
    pngs = {"subtitles": [(tmp_path / f"s{i}.png", 400, 60) for i in range(len(plan.subtitles))], "text_overlays": []}
    graph = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4", text_pngs=pngs))
    ys = re.findall(r"\[stin\d+\]overlay=x=\d+:y=(\d+)", graph)
    assert len(ys) == 2 and ys[0] != ys[1], graph

    # libass 回落那条路:第二道带 \an8(换到顶部),第一道沿用默认样式。
    build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4")
    ass = (tmp_path / "o.ass").read_text(encoding="utf-8")
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:") and ",Default," in line]
    first = next(line for line in dialogues if line.endswith("你好"))
    second = next(line for line in dialogues if line.endswith("Hello"))
    assert "\\an" not in first and "{\\an8}Hello" in second

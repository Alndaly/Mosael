"""工作流的「截取片段」节点:从视频里截一段存成新素材,取末尾几秒时从片尾往前数(逐段续写取上一段的尾巴)。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain.assets.importer import register_file_asset
from app.domain.assets.trim import TrimError, clip_range
from app.domain.workflows.engine import execute_graph
from app.media.paths import resolve_key
from app.media.probe import probe_media
from tests.util import fresh_client


def _asset(duration: float | None = 10.0) -> SimpleNamespace:
    return SimpleNamespace(media_info={} if duration is None else {"duration": duration})


@pytest.mark.parametrize("config,expected", [
    ({"last_seconds": 2}, (8.0, 10.0)),
    ({"last_seconds": 30}, (0.0, 10.0)),
    ({"start": 1, "end": 3}, (1.0, 3.0)),
    ({"start": 4}, (4.0, 10.0)),
    ({"last_seconds": 2, "start": 1, "end": 3}, (8.0, 10.0)),
])
def test_截哪一段(config: dict, expected: tuple[float, float]) -> None:
    assert clip_range(_asset(), **config) == expected


def test_读不出时长_从片尾算不了() -> None:
    with pytest.raises(TrimError) as caught:
        clip_range(_asset(None), last_seconds=2)
    assert caught.value.key == "trimErr_noDuration"
    assert clip_range(_asset(None), start=1, end=2) == (1.0, 2.0)


def test_负数拒() -> None:
    with pytest.raises(TrimError) as caught:
        clip_range(_asset(), last_seconds=-1)
    assert caught.value.key == "trimErr_lastSecondsNegative"


def test_真截一段_尾巴是新素材_来源记着原片(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = tmp_path / "shot.mp4"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24:duration=3",
                    "-pix_fmt", "yuv420p", str(source)], check=True)
    with SessionLocal() as db:
        asset = register_file_asset(db, workspace_id=ws, project_id=None, source_path=source, name="上一段", source="generated")
        workflow = Workflow(workspace_id=ws, name="截", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        asset_id, wf_id = asset.id, workflow.id
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}},
                       {"id": "tail", "type": "media_clip", "config": {"asset_id": asset_id, "last_seconds": 1}}],
             "edges": [{"id": "e", "source": "start", "target": "tail"}]}
    context, _ = execute_graph(graph, wf_id=wf_id, params={})
    made = context["tail"]
    assert made["source_asset_id"] == asset_id and made["duration"] == pytest.approx(1.0, abs=0.01)
    with SessionLocal() as db:
        clip = db.get(Asset, made["asset_id"])
        assert clip.derived_from == [{"asset_id": asset_id, "op": "trim"}]
        assert probe_media(resolve_key(clip.file_key))["duration"] == pytest.approx(1.0, abs=0.1)

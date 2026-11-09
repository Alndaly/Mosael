"""首帧、尾帧交给视频模型之前按视频的画幅摆正(ADR 0094)。

真跑带货口播:出图那步交回 2048×2048 的方图,H3 按 9:16 出片时把它直接压进竖屏 —— 衬衫整件被横向压窄。
漏斗在提交之前居中裁满,模型收到的就是目标画幅的那一张。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.intermediates import FITTED_FRAME
from app.domain.assets.lineage import FIT
from app.domain.generation.frame_fit import target_aspect
from app.domain.generation.origins import STUDIO_ORIGIN
from app.media.paths import resolve_key
from tests.util import fresh_client


@pytest.mark.parametrize(("parameters", "expected"), [
    ({"aspect_ratio": "16:9"}, 16 / 9),
    ({"115.aspect_ratio": "9:16 (Portrait Widescreen)"}, 9 / 16),
    ({"size": "1280x720"}, 1280 / 720),
    ({"aspect_ratio": "adaptive", "size": "1280x720"}, None),
    ({"aspect_ratio": "9:16", "size": "1280x720"}, 9 / 16),
    ({"resolution": "720p"}, None),
    ({}, None),
])
def test_目标画幅从参数里读_读不到就是None(parameters: dict, expected: float | None) -> None:
    got = target_aspect(parameters)
    assert got == pytest.approx(expected) if expected is not None else got is None


def _image(tmp_path: Path, ws: str, name: str, size: tuple[int, int]) -> str:
    path = tmp_path / f"{name}.png"
    image = Image.new("RGB", size, "white")
    #: 正中间一块红:居中裁满之后它还在正中间。
    w, h = size
    image.paste((255, 0, 0), (w // 2 - 10, h // 2 - 10, w // 2 + 10, h // 2 + 10))
    image.save(path)
    with SessionLocal() as db:
        asset = register_file_asset(db, workspace_id=ws, project_id=None, source_path=path, name=name, ai_generated=True)
        db.commit()
        return asset.id


def _generate(ws: str, profile: str, source_assets: list[dict], parameters: dict) -> dict:
    from app.domain.generation.operations import create_generation_job

    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, origin=STUDIO_ORIGIN, workspace_id=ws, session_id=None, project_id=None, created_by=None,
            provider="bytedance", provider_profile_id=profile, model="doubao-seedance-2-0-260128", kind="video",
            prompt="衬衫挂在窗边", negative_prompt="", parameters=parameters, source_assets=source_assets,
        )
        db.commit()
        return generation.request


@pytest.fixture
def seedance(monkeypatch):
    from app.domain import jobs as jobs_bus
    from tests.test_entity_generation_paths import _seedance

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return ws, _seedance(client)


def test_方图当竖屏视频的首帧_居中裁成九比十六_记下改了什么(seedance, tmp_path: Path) -> None:
    ws, profile = seedance
    square = _image(tmp_path, ws, "衬衫", (1024, 1024))
    request = _generate(ws, profile, [{"asset_id": square, "role": "first_frame"}], {"aspect_ratio": "9:16"})

    [source] = request["source_assets"]
    assert source["role"] == "first_frame" and source["asset_id"] != square
    [fitted] = request["fitted_frames"]
    assert fitted == {"role": "first_frame", "from": square, "to": source["asset_id"], "aspect": "9:16",
                      "from_size": [1024, 1024], "to_size": [576, 1024]}
    with SessionLocal() as db:
        made = db.get(Asset, source["asset_id"])
        assert made.derived_from == [{"asset_id": square, "op": FIT}]
        assert made.intermediate == FITTED_FRAME, "工序零件,素材库默认不列"
        assert made.ai_generated, "AI 标记从原图继承"
        with Image.open(resolve_key(made.file_key)) as image:
            assert image.size == (576, 1024)
            assert image.getpixel((288, 512))[:3] == (255, 0, 0), "居中裁:正中那块还在正中"


def test_首帧本来就是目标画幅_什么都不改(seedance, tmp_path: Path) -> None:
    ws, profile = seedance
    portrait = _image(tmp_path, ws, "竖图", (720, 1280))
    request = _generate(ws, profile, [{"asset_id": portrait, "role": "first_frame"}], {"aspect_ratio": "9:16"})
    assert request["source_assets"] == [{"asset_id": portrait, "role": "first_frame"}]
    assert "fitted_frames" not in request


def test_读不到目标画幅_不动(seedance, tmp_path: Path) -> None:
    ws, profile = seedance
    square = _image(tmp_path, ws, "方图", (1024, 1024))
    request = _generate(ws, profile, [{"asset_id": square, "role": "first_frame"}], {})
    assert request["source_assets"] == [{"asset_id": square, "role": "first_frame"}]
    assert "fitted_frames" not in request


def test_首尾帧都摆_参考图不动(seedance, tmp_path: Path) -> None:
    ws, profile = seedance
    head = _image(tmp_path, ws, "头", (1024, 1024))
    tail = _image(tmp_path, ws, "尾", (1024, 768))
    request = _generate(ws, profile, [{"asset_id": head, "role": "first_frame"}, {"asset_id": tail, "role": "last_frame"}],
                        {"aspect_ratio": "16:9"})
    assert [one["role"] for one in request["fitted_frames"]] == ["first_frame", "last_frame"]
    assert all(one["to_size"][0] * 9 == one["to_size"][1] * 16 for one in request["fitted_frames"])

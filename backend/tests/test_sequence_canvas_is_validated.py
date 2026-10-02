"""新建序列查画幅和帧率,范围与改画幅、工作流同一份。

此前新建序列一样都不查:宽 -5、高 0、帧率 0 的序列建得出来,要到预览按宽高比算尺寸、导出把帧率交给
ffmpeg 时才炸。改画幅查 16–8192,工作流的「新建成片项目」查 16–16384 —— 三处三个说法。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Project
from app.domain.sequences import create_sequence_scaffold
from app.domain.sequences.errors import SequenceDomainError
from tests.util import fresh_client


@pytest.fixture()
def project():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project_id = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    return client, ws, project_id


@pytest.mark.parametrize(
    "canvas",
    [
        {"width": -5},
        {"height": 0},
        {"fps": 0},
        {"fps": -30},
        {"width": 100000},
        {"height": 3},
        {"fps": 1000},
    ],
)
def test_接口拒收越界的画幅与帧率(project, canvas) -> None:
    client, ws, project_id = project
    res = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project_id, "name": "S", **canvas})
    assert res.status_code == 422, res.text


def test_默认值和边界值照收(project) -> None:
    client, ws, project_id = project
    made = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project_id, "name": "S"}).json()
    assert (made["width"], made["height"], made["fps"]) == (1920, 1080, 30.0)
    edge = client.post(
        "/api/sequences",
        json={"workspace_id": ws, "project_id": project_id, "name": "S", "width": 8192, "height": 16, "fps": 240},
    )
    assert edge.status_code == 200, edge.text


@pytest.mark.parametrize(("width", "height", "fps"), [(0, 1080, 30.0), (1920, 1080, 0.0), (1920, 1080, float("nan"))])
def test_领域层同样拒_不只靠接口那一层(project, width, height, fps) -> None:
    _client, _ws, project_id = project
    with SessionLocal() as db:
        with pytest.raises(SequenceDomainError):
            create_sequence_scaffold(db, db.get(Project, project_id), name="S", width=width, height=height, fps=fps)

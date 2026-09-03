"""Installed official workflow copies receive the same data-edge repair as new templates."""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_official_workflow_data_bindings
from tests.util import fresh_client


def _legacy_graph(source: str) -> dict:
    return {
        "meta": {"source": source, "template_id": "transcript_video_cleanup", "template_version": 1},
        "nodes": [
            {"id": "source", "type": "asset", "config": {"asset_id": "asset-1"}},
            {
                "id": "transcript",
                "type": "transcribe_asset",
                "config": {"asset_id": "{{source.asset_id}}", "engine": "auto"},
            },
        ],
        "edges": [{"id": "source_transcript", "source": "source", "target": "transcript"}],
    }


def test_only_installed_official_workflows_are_migrated() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Bindings"}).json()
    ids: dict[str, str] = {}
    for source in ("official", "custom"):
        created = client.post(
            "/api/workflows",
            json={"workspace_id": workspace["id"], "name": source},
        ).json()
        ids[source] = created["id"]
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(_legacy_graph(source)), "id": created["id"]},
            )

    _migrate_official_workflow_data_bindings()
    _migrate_official_workflow_data_bindings()  # startup migrations are intentionally re-entrant

    with engine.begin() as connection:
        stored = {
            source: json.loads(
                connection.execute(
                    text("SELECT graph FROM workflows WHERE id = :id"), {"id": workflow_id}
                ).scalar_one()
            )
            for source, workflow_id in ids.items()
        }
    official_transcript = stored["official"]["nodes"][1]
    assert official_transcript["config"]["asset_id"] == ""
    assert official_transcript["inputs"] == ["asset_id"]
    assert stored["official"]["edges"][0]["kind"] == "data"
    assert stored["custom"] == _legacy_graph("custom")

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.db import Base, SessionLocal, engine, init_db
from app.domain.plugins import scan_plugins
from app.main import app


def reset_db(tmp_path: Path) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_plugin_manifest_scan_enable_tool_and_invocation(tmp_path: Path) -> None:
    reset_db(tmp_path)
    plugin_dir = tmp_path / "plugins" / "caption-helper"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mibu.plugin.json").write_text(
        json.dumps(
            {
                "id": "dev.caption-helper",
                "name": "Caption Helper",
                "version": "0.1.0",
                "permissions": ["assets:read", "sequence:write"],
                "skills": [{"id": "caption_assets", "description": "Create captions for selected media."}],
                "tools": [
                    {
                        "name": "caption_asset",
                        "description": "Generate captions for an asset.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"asset_id": {"type": "string"}},
                            "required": ["asset_id"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        scanned = scan_plugins(db, tmp_path / "plugins")
    assert [plugin.id for plugin in scanned] == ["dev.caption-helper"]

    client = TestClient(app)
    enabled = client.patch("/api/plugins/dev.caption-helper", json={"enabled": True}).json()
    assert enabled["enabled"] is True

    permissions = client.get("/api/plugins/dev.caption-helper/permissions").json()
    assert {grant["permission"]: grant["granted"] for grant in permissions} == {
        "assets:read": False,
        "sequence:write": False,
    }

    tools = client.get("/api/plugins/tools").json()
    assert tools == []

    blocked = client.post(
        "/api/plugins/dev.caption-helper/tools/caption_asset/invoke",
        json={"input": {"asset_id": "asset_1"}},
    )
    assert blocked.status_code == 422
    assert "permissions" in blocked.json()["detail"]

    granted = client.patch(
        "/api/plugins/dev.caption-helper/permissions",
        json={"grants": {"assets:read": True, "sequence:write": True}},
    ).json()
    assert all(item["granted"] for item in granted)

    tools = client.get("/api/plugins/tools").json()
    assert tools[0]["plugin_id"] == "dev.caption-helper"
    assert tools[0]["tool_name"] == "caption_asset"
    assert tools[0]["skills"][0]["id"] == "caption_assets"

    skills = client.get("/api/agent/skills").json()
    skill_ids = {skill["id"] for skill in skills}
    assert "mibu.ai_generation" in skill_ids
    assert "dev.caption-helper:caption_assets" in skill_ids

    invocation = client.post(
        "/api/plugins/dev.caption-helper/tools/caption_asset/invoke",
        json={"input": {"asset_id": "asset_1"}},
    ).json()
    assert invocation["status"] == "queued"
    assert invocation["input"]["asset_id"] == "asset_1"

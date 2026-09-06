from pathlib import Path
import json
import runpy

from app.domain.workflows.revisions import graph_digest
from tests.util import fresh_client

ROOT = Path(__file__).resolve().parents[2]


def test_website_downloads_match_real_templates_and_import_into_the_app():
    generated = runpy.run_path(str(ROOT / "scripts/sync-website-workflows.py"))["catalog_files"]()
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Website downloads"}).json()
    for filename, expected in generated.items():
        file = ROOT / "website/public/workflows" / filename
        assert file.exists(), f"Missing downloadable workflow: {filename}"
        assert file.read_text(encoding="utf-8") == expected, "Run scripts/sync-website-workflows.py"
        if filename == "catalog.json":
            continue
        envelope = json.loads(expected)
        assert envelope["graph_hash"] == graph_digest(envelope["graph"])
        response = client.post("/api/workflows/import", json={"workspace_id": workspace["id"], "data": envelope})
        assert response.status_code == 200, response.text
        exported = client.get(f'/api/workflows/{response.json()["id"]}/export').json()
        assert exported["graph"] == envelope["graph"]

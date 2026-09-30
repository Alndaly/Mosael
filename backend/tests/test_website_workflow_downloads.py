from pathlib import Path
import json
import runpy

import pytest

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


def test_删掉或改名的模板_旧下载查得出来_同步时删掉(tmp_path):
    """此前 --check 发现不了多出来的孤儿文件,写入模式也只覆盖不删:旧的那份下载会一直留在官网上。"""
    script = runpy.run_path(str(ROOT / "scripts/sync-website-workflows.py"))
    files = {"a.zh.mosael-workflow.json": "{}\n", "catalog.json": "[]\n"}
    script["sync"](tmp_path, files, check=False)
    (tmp_path / "gone.zh.mosael-workflow.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("不归同步脚本管\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="gone.zh.mosael-workflow.json"):
        script["sync"](tmp_path, files, check=True)
    script["sync"](tmp_path, files, check=False)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.zh.mosael-workflow.json", "catalog.json", "notes.txt"]
    script["sync"](tmp_path, files, check=True)


def test_官网目录里没有孤儿下载():
    script = runpy.run_path(str(ROOT / "scripts/sync-website-workflows.py"))
    assert script["orphans"](ROOT / "website/public/workflows", script["catalog_files"]()) == []

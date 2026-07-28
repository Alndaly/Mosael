from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from app.domain.plugins.runtime import PluginRuntimeError, check_required_input, execute_tool
from tests.util import fresh_client

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "plugins" / "examples" / "text-toolkit"


def make_plugin(tmp_path: Path, entry_body: str, entry: str = "main.py") -> dict:
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / entry).write_text(textwrap.dedent(entry_body), encoding="utf-8")
    return {"_path": str(plugin_dir), "entry": entry}


def test_example_plugin_word_count_end_to_end() -> None:
    manifest = json.loads((EXAMPLE / "open-studio.plugin.json").read_text(encoding="utf-8"))
    manifest["_path"] = str(EXAMPLE)
    output = execute_tool(manifest, "word_count", {"text": "大家好 欢迎来到米布"})
    assert output["chars"] == 9
    assert output["estimated_seconds"] == 2.0
    tags = execute_tool(manifest, "extract_hashtags", {"text": "上新啦 #好物# #newvideo 冲"})
    assert tags["hashtags"] == ["好物", "newvideo"]


def test_plugin_error_response_raises() -> None:
    manifest = json.loads((EXAMPLE / "open-studio.plugin.json").read_text(encoding="utf-8"))
    manifest["_path"] = str(EXAMPLE)
    with pytest.raises(PluginRuntimeError, match="unknown tool"):
        execute_tool(manifest, "nope", {})


def test_crashing_plugin_reports_exit_code(tmp_path) -> None:
    manifest = make_plugin(tmp_path, "import sys; sys.exit(3)")
    with pytest.raises(PluginRuntimeError, match="退出码 3"):
        execute_tool(manifest, "x", {})


def test_garbage_output_rejected(tmp_path) -> None:
    manifest = make_plugin(tmp_path, "print('not json')")
    with pytest.raises(PluginRuntimeError, match="不是合法 JSON"):
        execute_tool(manifest, "x", {})


def test_entry_escape_rejected(tmp_path) -> None:
    (tmp_path / "outside.py").write_text("print('{}')", encoding="utf-8")
    manifest = make_plugin(tmp_path, "pass")
    manifest["entry"] = "../outside.py"
    with pytest.raises(PluginRuntimeError, match="插件目录内"):
        execute_tool(manifest, "x", {})


def test_missing_required_input() -> None:
    with pytest.raises(PluginRuntimeError, match="缺少必填输入: text"):
        check_required_input({"input_schema": {"type": "object", "required": ["text"]}}, {})


def test_invoke_api_records_success_and_failure(tmp_path, monkeypatch) -> None:
    from app.core.config import settings as app_settings

    plugins_dir = tmp_path / "plugins"
    target = plugins_dir / "text-toolkit"
    target.mkdir(parents=True)
    (target / "open-studio.plugin.json").write_text((EXAMPLE / "open-studio.plugin.json").read_text(encoding="utf-8"), "utf-8")
    (target / "tools").mkdir()
    (target / "tools" / "main.py").write_text((EXAMPLE / "tools" / "main.py").read_text(encoding="utf-8"), "utf-8")
    monkeypatch.setattr(type(app_settings), "plugins_dir", property(lambda self: plugins_dir))

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # plugin admin routes need an admin
    plugins = client.post("/api/plugins/scan").json()
    assert plugins[0]["id"] == "dev.openstudio.text-toolkit"
    client.patch(f"/api/plugins/{plugins[0]['id']}", json={"enabled": True})

    res = client.post(
        f"/api/plugins/{plugins[0]['id']}/tools/word_count/invoke",
        json={"input": {"text": "你好世界"}},
    ).json()
    assert res["status"] == "succeeded"
    assert res["output"]["chars"] == 4

    failed = client.post(
        f"/api/plugins/{plugins[0]['id']}/tools/word_count/invoke",
        json={"input": {}},
    ).json()
    assert failed["status"] == "failed" and "text" in failed["error"]

    history = client.get("/api/plugins/invocations").json()
    assert len(history) == 2

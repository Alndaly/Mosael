"""模型库(`op: library`)不该在插件这一侧先把模型清单削掉。

## 现场

`plugins/bundled/comfyui/tools/library.py` 里有一个 `OUTPUT_BUDGET = 900_000`(旧 1MB 的九成):模型一多,它先把
可选的装饰(触发词、在用的工作流、标题、预览文件)削掉,还嫌大就把 `models` 砍掉一截并写一句「文件太多,只列出了
前 N 个」。宿主后来给目录类回答放宽到 `runtime.CATALOG_OUTPUT_BYTES = 8MB`(见 test_comfyui_remote_libraries_
fit_the_output_limit.py),但插件这一侧仍然自己先削 —— 宿主放宽了也没用,用户看到的还是缺了的清单。

## 钉的是什么

- 抬到与宿主同一条线(8MB),不取消上限:超过时仍先削可选的装饰;
- **模型条目一条都不删**:真的超过 8MB 就整份交给宿主,由宿主整份不收、说清是哪一问 / 上限 / 实际读到多大 /
  下一步(插件不再静默削);
- 两个假 ComfyUI(本机随机端口,不连外网):一个量出 1MB~8MB 之间的整份回答,一个量出 >8MB。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.i18n import render_message
from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginRuntimeError, execute_tool
from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service",
            "shared_models", "workflows", "tooling", "library", "sources", "install", "model_files", "families",
            "workflow_library", "workflow_import", "canvas", "diagnose", "templates", "node_types", "node_packs",
            "node_catalog", "app_form", "json_style", "weights", "nsfw", "previews", "provenance", "civitai", "lookup",
            "pinned", "managed", "versions", "model_search", "workbench", "canvas_edit")

#: 一个「模型很多」的 ComfyUI:1500 个文件、名字够长,整份回答在 1MB 与 8MB 之间(旧 900KB 上限收不下)。
MANY = 1_500
MANY_NAME = 520
#: 真的非常多:8000 个文件,整份回答约 13MB(超过 8MB 那条线,又在宿主 16MB 的硬止损之内 —— 宿主能读全,
#: 所以报得出「实际读到多大」)。
HUGE = 8_000
HUGE_NAME = 780


def _models(count: int, length: int) -> list[str]:
    #: `.pth` 没有文件头可读 —— 这一条量的是「列出多少」,不去为每个文件读元数据(那是另一批用例的事)。
    return [f"lora_{index:05d}_" + "x" * length + ".pth" for index in range(count)]


def _fake_models(count: int, length: int):
    with FakeComfyUI() as server:
        server.state.model_folders = {"loras": _models(count, length)}
        yield server


@pytest.fixture
def many_models():
    yield from _fake_models(MANY, MANY_NAME)


@pytest.fixture
def huge_models():
    yield from _fake_models(HUGE, HUGE_NAME)


def _plugin_stdout(url: str) -> str:
    """直接问插件进程一句,拿它写在 stdout 上的那一份 —— 插件有没有自己先削,量这里。"""
    done = subprocess.run(
        [sys.executable, str(PLUGIN / ENTRY)], input=json.dumps({"tool": "comfyui_generation", "input": {"op": "library"},
                                                                 "locale": "zh", "accepts": ["shared_tables"]}),
        capture_output=True, text=True, cwd=str(PLUGIN),
        env={**os.environ, "SERVER_URL": url, "PYTHONUTF8": "1", "MOSAEL_PLUGIN": "1"},
        timeout=600, check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return done.stdout


@pytest.fixture
def plugin_modules(monkeypatch):
    """在进程里 import 插件自己的 `library`,只为了量「整份」有多大(不经过它的上限)。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import library
        from comfy_http import Comfy

        yield library, Comfy
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _full_size(library, comfy) -> int:
    """把插件自己的上限抬到不可能撞线,量它**本该**交回的整份有多大。"""
    original = library.OUTPUT_BUDGET
    library.OUTPUT_BUDGET = 10 ** 9
    try:
        full = library.library({}, comfy, "zh")
    finally:
        library.OUTPUT_BUDGET = original
    return len(json.dumps(full, ensure_ascii=False).encode())


def test_模型很多时_整份交回不再自己削(many_models, plugin_modules, tmp_path: Path) -> None:
    """改之前:插件把 1500 个削到几百个并写「只列出了前 N 个」;改之后:整份 1500 个,没有那句。"""
    library, Comfy = plugin_modules
    comfy = Comfy(many_models.url, "zh")
    full = _full_size(library, comfy)
    print(f"op library (untrimmed): bytes={full:,} "
          f"(host 1MB={runtime.MAX_OUTPUT_BYTES:,}, catalog={runtime.CATALOG_OUTPUT_BYTES:,}, plugin={library.OUTPUT_BUDGET:,})")
    assert runtime.MAX_OUTPUT_BYTES < full <= runtime.CATALOG_OUTPUT_BYTES, "假环境的量不对,这条什么都没量到"

    out = library.library({}, comfy, "zh")
    note = str((out.get("download") or {}).get("note") or "")
    print(f"op library (plugin): models={len(out['models']):,}/{MANY:,} note={note!r}")
    assert len(out["models"]) == MANY, "插件自己把模型清单削了(「只列出了前 N 个」)"
    assert "只列出了前" not in note and "only the first" not in note

    # 宿主这一层也整份收下(宿主给 library 的就是目录类预算,见 model_library.library)。
    data_dir = tmp_path / "plugin-data"
    data_dir.mkdir()
    received = execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "library"},
                            {"SERVER_URL": many_models.url}, data_dir=data_dir, timeout=300,
                            output_budget=runtime.CATALOG_OUTPUT_BYTES)
    assert len(received.output["models"]) == MANY


def test_真的超过8MB时_插件整份交回_宿主整份不收并说清(huge_models, tmp_path: Path) -> None:
    """插件不再静默削:>8MB 的那一份原样 stdout;宿主按目录预算整份不收,文案说得清。"""
    sent = _plugin_stdout(huge_models.url)
    size = len(sent.encode())
    print(f"op library (>8MB): chars={len(sent):,} bytes={size:,} (catalog={runtime.CATALOG_OUTPUT_BYTES:,})")
    assert size > runtime.CATALOG_OUTPUT_BYTES, "插件还在自己削 —— 它应该整份交回,由宿主那道闸说不"

    data_dir = tmp_path / "plugin-data"
    data_dir.mkdir()
    with pytest.raises(PluginRuntimeError) as caught:
        execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "library"},
                     {"SERVER_URL": huge_models.url}, data_dir=data_dir, timeout=600,
                     output_budget=runtime.CATALOG_OUTPUT_BYTES)
    exc = caught.value
    assert exc.key == "pluginErr_outputTooLarge"
    text = render_message(exc.key, "zh", exc.params)
    # 哪一问(工具名含 op)、上限、实际读到多大、下一步。
    assert "comfyui_generation · library" in text, text
    assert "8.0 MB" in text, text
    assert "实际已读到" in text, text
    assert "刷新" in text and "减少" in text, text

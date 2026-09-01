"""Provider 的能力 Interface、供应商 Adapter 和 Registry 不能重新混成一层。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.ai.providers.registry import _index_generation_adapters, _index_speech_adapters

RATCHET = True

APP = Path(__file__).resolve().parents[1] / "app"
PROVIDERS = APP / "ai" / "providers"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_能力契约不反向依赖adapter或registry() -> None:
    for path in (PROVIDERS / "contracts").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith("app.ai.providers.adapters") for name in imports), path
        assert "app.ai.providers.registry" not in imports, path


def test_领域模块只经公共interface使用provider() -> None:
    offenders: list[str] = []
    for path in (APP / "domain").rglob("*.py"):
        if any(name.startswith("app.ai.providers.adapters") for name in _imports(path)):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, f"domain 不应选择具体 Adapter:{offenders}"


def test_adapter不反向导入公共门面或registry() -> None:
    offenders: list[str] = []
    for path in (PROVIDERS / "adapters").rglob("*.py"):
        imports = _imports(path)
        if "app.ai.providers" in imports or "app.ai.providers.registry" in imports:
            offenders.append(str(path.relative_to(PROVIDERS)))
    assert not offenders, f"Adapter 只能依赖 contracts 或共享基础设施:{offenders}"


def test_provider根目录只保留公共interface装配和共享下载seam() -> None:
    actual = {path.name for path in PROVIDERS.glob("*.py")}
    assert actual == {"__init__.py", "media_transfer.py", "registry.py"}


def test_adapter根目录按企业或平台分组() -> None:
    adapters = PROVIDERS / "adapters"
    assert {path.name for path in adapters.glob("*.py")} == {"__init__.py"}


def test_同企业的不同产品协议有各自命名空间() -> None:
    adapters = PROVIDERS / "adapters"
    bytedance = adapters / "bytedance"
    alibaba = adapters / "alibaba"

    assert {path.name for path in bytedance.glob("*.py")} == {"__init__.py"}
    assert {path.name for path in bytedance.iterdir() if path.is_dir() and path.name != "__pycache__"} == {
        "ark",
        "volcano",
    }
    assert {path.name for path in alibaba.glob("*.py")} == {"__init__.py"}
    assert {path.name for path in alibaba.iterdir() if path.is_dir() and path.name != "__pycache__"} == {"dashscope"}


def test_registry拒绝静默覆盖重复adapter() -> None:
    class GenerationAdapter:
        vendor_id = "same"
        media_kind = "video"

    class SpeechAdapter:
        engine_id = "same"

    with pytest.raises(RuntimeError, match="重复的生成 Adapter"):
        _index_generation_adapters((GenerationAdapter(), GenerationAdapter()))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="重复的语音 Adapter"):
        _index_speech_adapters((SpeechAdapter, SpeechAdapter))  # type: ignore[arg-type]

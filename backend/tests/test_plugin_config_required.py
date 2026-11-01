"""插件配置的必填、默认值与注入规则(见 docs/PLUGIN_MANIFEST.md「必填与默认值」)。

此前三处各按各的:必填按真假值判(关着的开关、填了 0 的数字都算「缺少配置」)、布尔项缺省也是必填、
从没保存过的连接不看 `default`、注入时 `str(False)` 写成 `"False"`。PoseAtlas 的「包含成人内容」开关
就因此报「缺少配置」。这里钉住统一后的规则:判断缺不缺和注入插件进程用同一份生效值。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.plugins import instances as inst
from mosael_formats.plugin_manifest import _fields

FIELDS = _fields([
    {"key": "adult", "type": "boolean", "label": "成人", "default": False},
    {"key": "flag", "type": "boolean", "label": "开关", "required": True},
    {"key": "region", "type": "string", "label": "区域", "default": "cn"},
    {"key": "count", "type": "number", "label": "数量", "default": 0},
    {"key": "endpoint", "type": "string", "label": "端点"},
    {"key": "note", "type": "string", "label": "备注", "required": False},
], secret=False)


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch):
    manifest = SimpleNamespace(config=FIELDS, credentials=[])
    monkeypatch.setattr(inst, "manifest_for", lambda db, instance: manifest)
    monkeypatch.setattr(inst, "credential_values", lambda db, instance_id: {})
    return lambda config: SimpleNamespace(id="c1", config=config)


def test_布尔项从不算必填_写了_required_true_也一样() -> None:
    required = {spec.key: spec.required for spec in FIELDS}
    assert required == {"adult": False, "flag": False, "region": True, "count": True, "endpoint": True, "note": False}


def test_关着的开关和填了0的数字不算缺(connection) -> None:
    saved = connection({"adult": False, "flag": False, "region": "cn", "count": 0.0, "endpoint": "https://x"})
    assert inst.missing_config(None, saved) == []


def test_从没保存过时按默认值算_只缺没有默认值的(connection) -> None:
    assert inst.missing_config(None, connection(None)) == ["端点"]


def test_空串和None才算缺(connection) -> None:
    cleared = connection({"region": "", "count": None, "endpoint": "https://x"})
    assert inst.missing_config(None, cleared) == ["区域", "数量"]


def test_注入用同一份生效值_布尔写小写_整数不带小数点(connection) -> None:
    env = inst.secrets_for(None, connection({"flag": True, "count": 3.0, "endpoint": "https://x"}))
    assert env == {"adult": "false", "flag": "true", "region": "cn", "count": "3", "endpoint": "https://x"}


def test_保存时落下的默认值与生效值一致() -> None:
    manifest = SimpleNamespace(config=FIELDS)
    assert inst._fit_config(manifest, {}) == inst.effective_config(manifest, None)

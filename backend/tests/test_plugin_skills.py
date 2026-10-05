"""插件带技能(ADR 0040 §9):插件包里的 `skills/<名字>/SKILL.md` 装包时校验,装上后以插件为来源列出,每个工作区自己开。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.agent.skills import catalog, runtime, store
from app.domain.plugins import packages
from app.domain.plugins import registry as market
from app.domain.plugins.errors import PluginDomainError
from tests.util import fresh_client

MANIFEST = {
    "id": "dev.test.skilled",
    "name": {"zh": "带技能的插件", "en": "Skilled plugin"},
    "version": "1.0.0",
    "manifest_version": 7,
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"expose": "all", "declare": [{"name": "upscale", "description": "放大一张图", "effects": "paid"}]},
}

SKILL = (
    "---\nname: batch-upscale\ndescription: 用这个插件批量放大素材:先列出要处理的、分批跑、跑完核对尺寸。\n"
    "metadata:\n  mosael-title: 批量放大\n---\n\n1. 先用 list_assets 找出要处理的素材\n2. 每批不超过 10 张\n"
)


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"skilled-main/{name}", body)
    return buffer.getvalue()


def test_装上带技能的插件_技能以插件为来源列出_默认关_开了才进目录() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    market.install_archive(_zip({
        "mosael.plugin.json": json.dumps(MANIFEST, ensure_ascii=False), "main.py": "print('{}')",
        "skills/batch-upscale/SKILL.md": SKILL, "skills/batch-upscale/references/批次.md": "每批 10 张",
    }), settings.plugins_dir, overwrite=True)
    with SessionLocal() as db:
        packages.scan(db, settings.plugins_dir)
        db.commit()
        skill = catalog.find(db, ws, "dev.test.skilled:batch-upscale")
        assert skill is not None and skill.source == catalog.PLUGIN and not skill.enabled and not skill.editable
        assert skill.title == "批量放大" and catalog.source_label(skill) == "插件「带技能的插件」"
        assert "dev.test.skilled:batch-upscale" not in runtime.skills_prompt(db, ws)
        store.set_enabled(db, ws, skill, True, user_id=None)
        db.commit()
        assert "- dev.test.skilled:batch-upscale(批量放大):" in runtime.skills_prompt(db, ws)
        read = runtime.read_skill_file(db, ws, "dev.test.skilled:batch-upscale", "references/批次.md")
        assert read["content"] == "每批 10 张"
    listed = {one["ref"]: one for one in client.get(f"/api/workspaces/{ws}/skills").json()}
    assert listed["dev.test.skilled:batch-upscale"]["source"] == "plugin"


@pytest.mark.parametrize(
    "files",
    [
        {"skills/wrong-folder/SKILL.md": SKILL},
        {"skills/batch-upscale/SKILL.md": "没有头"},
        {"skills/notes.md": "散落的文件"},
    ],
)
def test_技能不合格的插件包装不上(files: dict[str, str], tmp_path) -> None:
    data = _zip({"mosael.plugin.json": json.dumps(MANIFEST, ensure_ascii=False), "main.py": "x", **files})
    with pytest.raises(PluginDomainError) as caught:
        market.install_archive(data, tmp_path)
    assert caught.value.key == "pluginErr_skillsInvalid"
    assert not (tmp_path / "dev.test.skilled").exists(), "不合格的包不在磁盘上留下任何东西"

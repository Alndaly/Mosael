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


def test_随_Mosael_发的插件带的技能默认开_像内置的一样_能关() -> None:
    """ComfyUI 插件随应用发(plugins/bundled),它带的「ComfyUI 工作流」(ADR 0042 §8)是这一版应用的一部分:每个工作区默认开,
    工作台的「助手」一打开就照它做;市场里装的插件带的照旧默认关(上一条)。关了就不进目录。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        packages.scan(db, settings.plugins_dir)
        db.commit()
        skill = catalog.find(db, ws, "dev.mosael.comfyui:comfyui-workflows")
        assert skill is not None and skill.source == catalog.PLUGIN and skill.usable and skill.enabled, skill and skill.problem
        assert skill.title == "ComfyUI 工作流"
        assert "- dev.mosael.comfyui:comfyui-workflows(ComfyUI 工作流):" in runtime.skills_prompt(db, ws)
        body = runtime.use_skill(db, ws, "dev.mosael.comfyui:comfyui-workflows")["instructions"]
        assert "comfy_check" in body and "comfy_canvas_edit" in body and "点「应用」" in body, "改画布要用户点「应用」(ADR 0042 第二步)"
        assert "还不能下载模型、装节点包、运行" in body, "下载、装、试跑在第三步:技能不许说那几样已经有了"
        store.set_enabled(db, ws, skill, False, user_id=None)
        db.commit()
        assert "comfyui-workflows" not in runtime.skills_prompt(db, ws)

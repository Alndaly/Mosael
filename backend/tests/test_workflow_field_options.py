"""节点字段的动态选项(`options_from`)。

前端对所有带这个声明的字段走同一个接口,不认识具体节点。这里钉住:
1. 声明里用到的来源都真的存在 —— 写错一个名字,界面上就是一个永远空的下拉;
2. 引擎清单:克隆总在最前,只列就绪的,不列播客;
3. 音色清单跟着引擎变:克隆 → 工作区音色库(别的工作区的不列),其余 → 那个引擎的目录;
4. 接口本身:要有工作区权限,来源名写错说清楚。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from tests.util import fresh_client


def test_声明里用到的来源都存在() -> None:
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.field_options import SOURCES

    used = {
        f"{name}.{key}": meta["options_from"]
        for name, spec in NODE_TYPES.items()
        for key, meta in (spec.get("config") or {}).items()
        if isinstance(meta, dict) and meta.get("options_from")
    }
    assert used, "至少语音节点在用"
    missing = {field: source for field, source in used.items() if source not in SOURCES}
    assert not missing, f"这些字段声明的选项来源不存在:{missing}"


def _ctx(workspace_id: str = "w", parent: str = ""):
    from app.domain.workflows.field_options import OptionContext

    return OptionContext(workspace_id=workspace_id, user_id=None, parent=parent, locale="zh")


def test_引擎清单_克隆在前_只列就绪的_不列播客(monkeypatch) -> None:
    from app.domain.voices import engine_catalog
    from app.domain.workflows.field_options import field_options

    monkeypatch.setattr(engine_catalog, "describe_engines", lambda user_id=None: [
        {"id": "clone", "label": "ttsProvider_clone", "ready": False},
        {"id": "edge", "label": "Edge", "ready": True},
        {"id": "volcano", "label": "火山", "ready": False},
        {"id": engine_catalog.PODCAST_ENGINE, "label": "播客", "ready": True},
    ])
    options = field_options(None, "speech_engines", _ctx())
    assert [one["value"] for one in options] == ["clone", "edge"]
    assert options[0]["label"] == "克隆音色(配音库)"


def test_音色清单跟着引擎变(monkeypatch) -> None:
    from app.db.models import Voice, Workspace
    from app.domain.voices import engine_catalog
    from app.domain.workflows.field_options import field_options

    client = fresh_client()
    mine = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        other = Workspace(name="别人的")
        db.add(other)
        db.flush()
        db.add_all([
            Voice(workspace_id=mine, name="我的嗓子", reference_key="r1"),
            Voice(workspace_id=other.id, name="别人的嗓子", reference_key="r2"),
        ])
        db.commit()

        cloned = field_options(db, "speech_voices", _ctx(mine, parent="clone"))
        assert [one["label"] for one in cloned] == ["我的嗓子"]
        #: 没选引擎时按克隆算 —— 和执行体一致。
        assert field_options(db, "speech_voices", _ctx(mine, parent="")) == cloned

        monkeypatch.setattr(engine_catalog, "list_engine_voices", lambda db, engine, user_id: [
            {"value": f"{engine}-1", "label": "晓晓", "resource_id": "res"},
        ])
        assert field_options(db, "speech_voices", _ctx(mine, parent="edge")) == [{"value": "edge-1", "label": "晓晓"}]


def test_接口要工作区权限_来源写错说清楚() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    ok = client.get("/api/workflows/field-options", params={"source": "speech_voices", "workspace_id": workspace, "parent": "clone"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == []

    wrong = client.get("/api/workflows/field-options", params={"source": "nope", "workspace_id": workspace})
    assert wrong.status_code == 404 and "nope" in wrong.text

    stranger = client.get("/api/workflows/field-options", params={"source": "speech_voices", "workspace_id": "not-mine"})
    assert stranger.status_code in {403, 404}


def test_节点类型接口把选项来源发下去() -> None:
    client = fresh_client()
    types = {item["type"]: item for item in client.get("/api/workflows/node-types").json()}
    config = types["synthesize_speech"]["config"]
    assert config["engine"]["options_from"] == "speech_engines"
    assert config["voice"]["options_from"] == "speech_voices"
    assert config["voice"]["depends_on"] == "engine"
    assert list(config).index("voice") == list(config).index("engine") + 1
    assert "required_one_of" not in types["synthesize_speech"]


class _VoiceDB:
    """克隆那条会核对音色的工作区;单测里给一个只认得这一条音色的库。"""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id

    def get(self, model, key):
        return type("V", (), {"id": key, "workspace_id": self.workspace_id})()


@pytest.mark.parametrize("engine", ["", "clone"])
def test_执行体把克隆音色交给克隆那条(engine, monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(subjobs, "current_actor", lambda db: None)
    workflow = type("W", (), {"workspace_id": "w"})()
    params = subjobs._speech_params(_VoiceDB("w"), workflow, {"engine": engine, "voice": "v1"}, what="测试")
    assert params["voice_id"] == "v1" and "engine_voice" not in params and "workspace_id" not in params


def test_执行体不收别的工作区的克隆音色(monkeypatch) -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(subjobs, "current_actor", lambda db: None)
    workflow = type("W", (), {"workspace_id": "w"})()
    with pytest.raises(WorkflowDomainError, match="配音库里没有这个音色"):
        subjobs._speech_params(_VoiceDB("别人的"), workflow, {"voice": "v1"}, what="测试")

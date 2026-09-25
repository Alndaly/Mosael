"""语音合成有两条路,每个调用方都要能走通它声称支持的那一条。

`start_synthesis` 的分叉在 `engine` 上,而它的**默认值是 `"clone"`** —— clone 那条必须查到
一行 Voice。于是一个只传 voice_id 的调用方就永远只能用克隆音色,**而没有任何一处写着这件事**:
是那个默认值替它做的决定。工作流的 synthesize_speech 节点和画板配音都这么漏过,表现是用户
选了引擎音色却毫无作用 —— 没有报错,只是那个参数根本没被送下去。

这里不测合成本身(那要真的跑引擎),只钉**参数有没有一路传到底**。这正是当初漏掉的那一环:
两个调用方的代码各自都"看起来对",错在它们没把手上的东西交出去。
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def captured(monkeypatch):
    """截下 start_synthesis 的关键字参数,不真的建任务。"""
    seen: dict[str, Any] = {}

    class _Job:
        id = "job-1"
        result = {"asset_id": "asset-1"}
        status = "succeeded"

    def fake(db, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return _Job()

    import app.domain.voices.voices as voices_module

    monkeypatch.setattr(voices_module, "start_synthesis", fake)
    return seen


class Test工作流节点:
    def _run(self, config: dict[str, Any], monkeypatch):
        from app.domain.workflows.executors import subjobs

        # 签名跟着真的 `wait_for_job` 走:`release=` 是调用方在等待期间交还的会话
        # (见 executors/common —— 不还就是一群等着的父节点占满连接预算)。替身少一个参数,
        # 等于把"调用点有没有把会话交出去"这件事从测试里挖掉。
        monkeypatch.setattr(
            subjobs, "wait_for_job",
            lambda _id, *, release=None: type("J", (), {"result": {"asset_id": "a1"}})(),
        )
        monkeypatch.setattr(subjobs, "current_actor", lambda _db: "u1")
        workflow = type("W", (), {"workspace_id": "ws-1"})()
        db = type("DB", (), {"get": lambda self, model, key: type("V", (), {"workspace_id": "ws-1"})()})()
        return subjobs.synthesize_speech(db, workflow, config)

    def test_引擎音色一路传到底(self, captured, monkeypatch) -> None:
        """这条是修复本身:此前 engine / engine_voice 填了也没被传下去。音色现在是一格,
        选了引擎时它就是那个引擎的音色;资源族由执行体自己查,不靠界面存。"""
        from app.domain.voices import engine_catalog

        monkeypatch.setattr(
            engine_catalog, "list_engine_voices",
            lambda db, engine, user_id: [{"value": "zh_female_x", "label": "x", "resource_id": "res-9"}],
        )
        self._run({"text": "念一句", "engine": "volcano", "voice": "zh_female_x", "speed": 1.25}, monkeypatch)
        assert captured["engine"] == "volcano"
        assert captured["engine_voice"] == "zh_female_x"
        assert captured["engine_voice_resource"] == "res-9"
        assert "voice_id" not in captured, "引擎那条不该收到克隆那条的参数"
        assert captured["speed"] == 1.25
        # 引擎那条要一个工作区来认领产出 —— 克隆那条是从 Voice 行上取的。
        assert captured["workspace_id"] == "ws-1"

    def test_克隆时音色就是配音库里的那一个(self, captured, monkeypatch) -> None:
        self._run({"text": "念一句", "engine": "clone", "voice": "v-1"}, monkeypatch)
        assert captured["engine"] == "clone"
        assert captured["voice_id"] == "v-1"
        assert "engine_voice" not in captured

    def test_没填引擎按克隆算(self, captured, monkeypatch) -> None:
        self._run({"text": "念一句", "voice": "v-1"}, monkeypatch)
        assert captured["engine"] == "clone" and captured["voice_id"] == "v-1"

    def test_没选音色时直说(self, captured, monkeypatch) -> None:
        from app.domain.workflows import WorkflowDomainError

        with pytest.raises(WorkflowDomainError, match="没有选音色"):
            self._run({"text": "念一句", "engine": "edge"}, monkeypatch)


class Test画板配音:
    """和上面同一个漏法,所以一起钉住。"""

    def test_节点声明的字段都进了请求体(self) -> None:
        from app.domain.boards.producers import SpeakForm

        fields = set(SpeakForm.model_fields)
        assert {"engine", "engine_voice", "engine_voice_resource", "speed"} <= fields


def test_音色是一格_清单跟着引擎变() -> None:
    """此前存成 voice_id / engine_voice 两个键,由前端按引擎显示其一 —— 两个键一前一后,换引擎时
    音色那一格上下跳,看起来就是两个音色框;"显示哪一个""顺手填资源号"都是前端按节点类型写死的
    特例。现在:一格 `voice`,依赖 `engine`,两格的清单都由 options_from 声明,前端不认识这个节点。
    """
    from app.core.i18n import MESSAGES
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.field_options import SOURCES

    for node in ("synthesize_speech", "dub_subtitles"):
        config = NODE_TYPES[node]["config"]
        assert not {"voice_id", "engine_voice", "engine_voice_resource"} & set(config), node
        keys = list(config)
        #: 顺序就是界面顺序:先说嗓子从哪来,再挑一把。
        assert keys.index("engine") + 1 == keys.index("voice"), keys
        assert config["engine"]["default"] == "clone"
        assert config["engine"]["options_from"] in SOURCES
        assert config["voice"]["options_from"] in SOURCES
        assert config["voice"]["depends_on"] == "engine"
        assert config["voice"]["required"] is True
        assert "留空" not in MESSAGES[config["voice"]["description"]]["zh"]

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

        monkeypatch.setattr(subjobs, "wait_for_job", lambda _id: type("J", (), {"result": {"asset_id": "a1"}})())
        monkeypatch.setattr(subjobs, "current_actor", lambda _db: "u1")
        workflow = type("W", (), {"workspace_id": "ws-1"})()
        return subjobs.synthesize_speech(None, workflow, config)

    def test_引擎音色一路传到底(self, captured, monkeypatch) -> None:
        """这条是修复本身:此前 engine / engine_voice 填了也没被传下去。"""
        self._run(
            {
                "text": "念一句",
                "engine": "volcano",
                "engine_voice": "zh_female_x",
                "engine_voice_resource": "res-9",
                "speed": 1.25,
            },
            monkeypatch,
        )
        assert captured["engine"] == "volcano"
        assert captured["engine_voice"] == "zh_female_x"
        assert captured["engine_voice_resource"] == "res-9"
        assert captured["speed"] == 1.25
        # 引擎那条要一个工作区来认领产出 —— 克隆那条是从 Voice 行上取的。
        assert captured["workspace_id"] == "ws-1"

    def test_只填克隆音色时还是走克隆(self, captured, monkeypatch) -> None:
        """已经存下来的工作流里只有 voice_id。加了一条路不能把它们弄坏。"""
        self._run({"text": "念一句", "voice_id": "v-1"}, monkeypatch)
        assert captured["engine"] == "clone"
        assert captured["voice_id"] == "v-1"

    def test_两边都空时说清楚有哪两条路(self, captured, monkeypatch) -> None:
        """「音色不存在」会让人以为是自己选的那个没了 —— 而其实是一个都没选。"""
        from app.domain.workflows import WorkflowDomainError

        with pytest.raises(WorkflowDomainError) as error:
            self._run({"text": "念一句"}, monkeypatch)
        assert "克隆音色" in str(error.value) and "引擎音色" in str(error.value)


class Test画板配音:
    """和上面同一个漏法,所以一起钉住。"""

    def test_节点声明的字段都进了请求体(self) -> None:
        from app.api.schemas.boards import BoardSpeak

        fields = set(BoardSpeak.model_fields)
        assert {"engine", "engine_voice", "engine_voice_resource", "speed"} <= fields


def test_节点契约把两条路都摆出来() -> None:
    """两边都不能是 required:填了引擎音色却被 voice_id 的红星拦住,等于表单在撒谎。"""
    from app.domain.workflows import NODE_TYPES

    config = NODE_TYPES["synthesize_speech"]["config"]
    assert not config["voice_id"].get("required")
    assert not config["engine"].get("required")
    assert config["text"].get("required") is True
    for key in ("engine", "engine_voice", "engine_voice_resource", "speed"):
        assert key in config, key

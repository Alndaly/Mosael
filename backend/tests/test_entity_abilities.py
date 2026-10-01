"""资产格的两项能力(ADR 0027 阶段 4):补全多角度、生成表情。

每一张是一次普通的生成(`@` 着这个资产,参考图照 `@资产` 那条路挂上),画成的按角度挂回这个资产。
这里把生成那一侧换成假的(建任务、起线程、等结果),钉住的是:画哪几张、用哪个模型、挂成什么角度、
挂不上 / 画不成时怎么说;以及画板上它们挂在资产格上。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.unit_of_work import unit_of_work
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.executors import entities as executors
from app.domain.workflows.field_options import OptionContext, field_options
from tests.util import fresh_client, seed_assets

REFERENCE_CAPS = {"parameter_keys": ["prompt", "reference_image"], "source_limits": {"reference_image": 4}}
OPTIONS = [
    {"id": "p1:image:edit", "provider": "vendor", "provider_profile_id": "p1", "model": "edit", "label": "连接 · 能改图",
     "is_default": True, "adapter_available": True, "capabilities": REFERENCE_CAPS},
    {"id": "p1:image:t2i", "provider": "vendor", "provider_profile_id": "p1", "model": "t2i", "label": "连接 · 只看字",
     "is_default": False, "adapter_available": True, "capabilities": {"parameter_keys": ["prompt"]}},
    {"id": "p2:image:edit", "provider": "other", "provider_profile_id": "p2", "model": "edit", "label": "另一家 · 能改图",
     "is_default": False, "adapter_available": True, "capabilities": REFERENCE_CAPS},
]


class FakeGeneration:
    """建任务、起线程、等结果都换成假的:每建一次记下参数,等的时候交回一张新图(`fail` 里的那几次报错)。"""

    def __init__(self, workspace_id: str, fail: set[int] | None = None) -> None:
        self.workspace_id = workspace_id
        self.calls: list[dict[str, Any]] = []
        self.fail = fail or set()

    def create(self, db, **kwargs):
        index = len(self.calls)
        self.calls.append(kwargs)
        seed_assets(self.workspace_id, {f"drawn-{index}": "image"})
        return SimpleNamespace(id=f"gen-{index}"), SimpleNamespace(id=f"job-{index}")

    def wait(self, job_id: str, *, release=None):
        index = int(job_id.split("-")[1])
        if index in self.fail:
            raise WorkflowDomainError("wfErr_childFailed", params={"reason": "供应商拒了"})
        return SimpleNamespace(result={"asset_ids": [f"drawn-{index}"]})


@pytest.fixture()
def setup(monkeypatch):
    from app.domain import generation
    from app.domain.generation import resolution, runner

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"front": "image", "clip": "video"})
    fake = FakeGeneration(ws)
    monkeypatch.setattr(generation, "create_generation_job", fake.create)
    monkeypatch.setattr(runner, "start_generation_thread", lambda generation_id: None)
    monkeypatch.setattr(resolution, "generation_options", lambda db, kind, user_id=None: list(OPTIONS))
    monkeypatch.setattr(executors, "wait_for_job", fake.wait)
    return client, ws, fake


def _entity(client, ws: str, kind: str = "character", name: str = "林小满", refs=(("front", "front"),)) -> str:
    made = client.post("/api/entities", json={"workspace_id": ws, "kind": kind, "name": name, "prompt": "短发"}).json()
    for asset_id, role in refs:
        client.post(f"/api/entities/{made['id']}/references", json={"asset_id": asset_id, "role": role})
    return made["id"]


def _scope(ws: str):
    return SimpleNamespace(workspace_id=ws, id="board:b1", name="画板")


def _roles(client, entity_id: str) -> list[tuple[str, str]]:
    return [(ref["asset_id"], ref["role"]) for ref in client.get(f"/api/entities/{entity_id}").json()["references"]]


def test_补全多角度_只画还没有的角度_每张都点名这个资产_画成的按角度挂回去(setup) -> None:
    client, ws, fake = setup
    entity_id = _entity(client, ws)
    with unit_of_work() as db:
        out = executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})

    assert [call["entity_ids"] for call in fake.calls] == [[entity_id]] * 3, "每一张都 @ 着这个资产,参考图由 @资产 那条路挂"
    assert {(call["provider_profile_id"], call["model"], call["kind"]) for call in fake.calls} == {("p1", "edit", "image")}, \
        "没点名模型用他设的默认"
    assert "Side view" in fake.calls[0]["prompt"] and "turnaround" in fake.calls[2]["prompt"]
    assert out == {"asset_ids": ["drawn-0", "drawn-1", "drawn-2"], "asset_id": "drawn-0", "entity_id": entity_id,
                   "added": 3, "failed": 0}
    assert _roles(client, entity_id) == [("front", "front"), ("drawn-0", "side"), ("drawn-1", "back"), ("drawn-2", "turnaround")]

    with unit_of_work() as db, pytest.raises(WorkflowDomainError) as complete:
        executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert complete.value.key == "wfErr_entityAnglesComplete", "都有了就直说,不白花钱再画一遍"

    with unit_of_work() as db:
        again = executors.entity_angles(db, _scope(ws), {"entity_id": entity_id, "scope": "all", "model": "p2:image:edit"})
    assert again["added"] == 4 and fake.calls[-1]["provider"] == "other", "「每个角度都重画」四张都画,用点名的模型"


def test_场景的角度是机位_补的是全景_反打_俯视里还没有的(setup) -> None:
    client, ws, fake = setup
    entity_id = _entity(client, ws, kind="location", name="旧城天台", refs=(("front", "wide"),))
    with unit_of_work() as db:
        out = executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert out["added"] == 2 and "Reverse angle" in fake.calls[0]["prompt"]
    assert [role for _asset, role in _roles(client, entity_id)] == ["wide", "reverse", "overhead"]


def test_画不出同一个的_先说清楚_不花钱(setup) -> None:
    client, ws, fake = setup
    video_only = _entity(client, ws, name="只有视频", refs=(("clip", "front"),))
    usable = _entity(client, ws, name="有图")
    cases = [
        ({"entity_id": video_only}, "wfErr_entityNeedsImage"),
        ({}, "wfErr_entityNeedsTarget"),
        ({"entity_id": usable, "model": "p1:image:t2i"}, "wfErr_entityModelNoReferences"),
        ({"entity_id": usable, "model": "gone:image:x"}, "wfErr_entityModelMissing"),
        ({"entity_id": usable, "scope": "some"}, "wfErr_entityAnglesScope"),
    ]
    for config, key in cases:
        with unit_of_work() as db, pytest.raises(WorkflowDomainError) as caught:
            executors.entity_angles(db, _scope(ws), config)
        assert caught.value.key == key, config
    assert fake.calls == [], "这些都该在建生成任务之前挡下"


def test_生成表情_只有人物_一种一张_挂成表情(setup) -> None:
    client, ws, fake = setup
    prop = _entity(client, ws, kind="prop", name="红伞")
    person = _entity(client, ws)
    with unit_of_work() as db, pytest.raises(WorkflowDomainError) as caught:
        executors.entity_expressions(db, _scope(ws), {"entity_id": prop})
    assert caught.value.key == "wfErr_entityExpressionsCharacterOnly"

    with unit_of_work() as db:
        out = executors.entity_expressions(db, _scope(ws), {"entity_id": person, "expressions": "开心、哭 ,开心\n害羞"})
    assert out["added"] == 3 and [("开心" in c["prompt"], "哭" in c["prompt"]) for c in fake.calls][:2] == [(True, False), (False, True)]
    assert [role for _asset, role in _roles(client, person)] == ["front", "expression", "expression", "expression"]

    with unit_of_work() as db:
        executors.entity_expressions(db, _scope(ws), {"entity_id": person})
    assert len(fake.calls) == 3 + 5, "没写就画缺省的五种"


def test_有几张没画成_画成的照样挂上_一张都没成才失败(setup) -> None:
    client, ws, fake = setup
    entity_id = _entity(client, ws)
    fake.fail = {1}
    with unit_of_work() as db:
        out = executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert (out["added"], out["failed"]) == (2, 1)
    assert [role for _asset, role in _roles(client, entity_id)] == ["front", "side", "turnaround"]

    other = _entity(client, ws, name="阿澄")
    fake.fail = {3, 4, 5}
    with unit_of_work() as db, pytest.raises(WorkflowDomainError) as caught:
        executors.entity_angles(db, _scope(ws), {"entity_id": other})
    assert caught.value.key == "wfErr_childFailed", "带着第一张没画成的原因"
    assert _roles(client, other) == [("front", "front")]


def test_模型下拉只列收参考图的_默认那个标出来(setup) -> None:
    client, ws, _fake = setup
    ctx = OptionContext(workspace_id=ws, user_id=None, parent="", locale="zh")
    with unit_of_work() as db:
        options = field_options(db, "reference_image_models", ctx)
    assert options == [
        {"value": "p1:image:edit", "label": "连接 · 能改图 · 默认"},
        {"value": "p2:image:edit", "label": "另一家 · 能改图"},
    ]


def test_画板上是资产格的能力_宿主给的是它引用的资产_要花钱() -> None:
    from app.domain.boards.producers import _node_producers
    from app.domain.boards.tools import host_value
    from app.domain.boards.transforms import board_group, board_hosts, board_role, host_fields, is_content_transform

    for node_type in ("entity_angles", "entity_expressions"):
        meta = NODE_TYPES[node_type]
        assert is_content_transform(meta), node_type
        assert board_role(meta) == "ability" and board_hosts(meta) == ("entity",)
        assert host_fields(meta) == {"entity": "entity_id"} and board_group(meta) == "entity"
    fresh_client()
    with unit_of_work() as db:
        producers = _node_producers(db, None)
        assert producers["node:entity_angles"].effects == "paid", "付费生成:智能体替人点要确认卡"
        assert producers["node:entity_expressions"].hosts == ("entity",)
        host = {"id": "i1", "kind": "entity", "entity_id": "e-42"}
        assert host_value(db, "ws", host, "entity_id", "entity") == "e-42"
        assert host_value(db, "ws", {"id": "i2", "kind": "entity"}, "entity_id", "entity") is None


def test_详情页上点_说不通的当场_422_说得通的起一个任务_画成的挂回来(setup) -> None:
    from tests.util import wait_status

    client, ws, fake = setup
    prop = _entity(client, ws, kind="prop", name="红伞")
    refused = client.post(f"/api/entities/{prop}/draw", json={"ability": "expressions"})
    assert refused.status_code == 422 and "红伞" in refused.json()["detail"]
    assert fake.calls == [], "说不通的不起任务、不花钱"

    person = _entity(client, ws)
    started = client.post(f"/api/entities/{person}/draw", json={"ability": "angles", "model": "p2:image:edit"})
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["kind"] == "entity_draw"
    assert wait_status(client, job["id"]) == "succeeded"
    assert [role for _asset, role in _roles(client, person)] == ["front", "side", "back", "turnaround"]
    assert {call["provider"] for call in fake.calls} == {"other"}


def test_资产格不是一个样子_生成表情只挂在人物上_场景点了起任务之前就拒(setup) -> None:
    from app.domain.boards.actions import BoardInputError
    from app.domain.boards.tools import _check_entity_kind
    from app.domain.boards.transforms import host_entity_kinds

    client, ws, fake = setup
    assert host_entity_kinds(NODE_TYPES["entity_expressions"]) == ["character"]
    assert host_entity_kinds(NODE_TYPES["entity_angles"]) == [], "补全多角度三种都有(各补各的角度)"
    listed = {one["id"]: one for one in client.get("/api/boards/producers", params={"workspace_id": ws}).json()}
    assert listed["node:entity_expressions"]["host_entity_kinds"] == ["character"]

    place = _entity(client, ws, kind="location", name="竹林小径", refs=(("front", "wide"),))
    person = _entity(client, ws)
    meta = NODE_TYPES["entity_expressions"]["config"]["entity_id"]
    with unit_of_work() as db:
        with pytest.raises(BoardInputError) as caught:
            _check_entity_kind(db, ws, place, meta, "生成表情")
        assert caught.value.key == "boardErr_abilityNotForEntityKind"
        _check_entity_kind(db, ws, person, meta, "生成表情")


def test_默认图片模型不收参考图_留空时用第一个收参考图的_下拉标的也是它(setup, monkeypatch) -> None:
    """此前留空只认默认:默认的图片模型只会文生图时,下拉里明明列着能用的,留空却报「不收参考图」。
    现在和说话照片、改口型同一个先后:默认合用就用它,否则第一个合用的。"""
    from app.domain.generation import resolution

    client, ws, fake = setup
    options = [{**one, "is_default": one["id"] == "p1:image:t2i"} for one in OPTIONS]
    monkeypatch.setattr(resolution, "generation_options", lambda db, kind, user_id=None: list(options))
    entity_id = _entity(client, ws)
    with unit_of_work() as db:
        executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert {call["provider_profile_id"] for call in fake.calls} == {"p1"} and fake.calls[0]["model"] == "edit"
    with unit_of_work() as db:
        listed = field_options(db, "reference_image_models", OptionContext(workspace_id=ws, user_id=None, parent="", locale="zh"))
    assert [one["label"] for one in listed] == ["连接 · 能改图 · 默认", "另一家 · 能改图"]

    monkeypatch.setattr(resolution, "generation_options",
                        lambda db, kind, user_id=None: [one for one in options if one["id"] == "p1:image:t2i"])
    with unit_of_work() as db, pytest.raises(WorkflowDomainError) as caught:
        executors.entity_angles(db, _scope(ws), {"entity_id": entity_id, "scope": "all"})
    assert caught.value.key == "wfErr_entityModelNone"


def test_这一轮在停_几张一起起的都取消_不只是正在等的那一张(setup, monkeypatch) -> None:
    """wait_for_job 停下时只取消它正在等的那一张;另外几张照样在生成、照样扣费。等的是真的 wait_for_job。"""
    from app.db.models import Job
    from app.domain.generation import runner
    from app.domain.workflows.executors.common import wait_for_job
    from app.domain.workflows.run_scope import halt_scope

    client, ws, _fake = setup
    monkeypatch.setattr(executors, "wait_for_job", wait_for_job)
    children: list[str] = []

    def create(db, **kwargs):
        job = Job(workspace_id=ws, kind="generation", status="running", created_by=None)
        db.add(job)
        db.flush()
        children.append(job.id)
        return SimpleNamespace(id=f"gen-{len(children)}"), job

    monkeypatch.setattr("app.domain.generation.create_generation_job", create)
    monkeypatch.setattr(runner, "start_generation_thread", lambda generation_id: None)
    entity_id = _entity(client, ws)
    with halt_scope() as halt, unit_of_work() as db:
        halt.set()
        with pytest.raises(WorkflowDomainError) as caught:
            executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert caught.value.key == "wfErr_cancelled" and len(children) == 3
    with unit_of_work() as db:
        assert [(db.get(Job, one).status, db.get(Job, one).error_key) for one in children] == [("failed", "jobErr_cancelled")] * 3


def test_第三张被拒_前两张已经建好的任务一并取消_不停在排队(setup, monkeypatch) -> None:
    """漏斗每建一张就提交一次;第 N 张被拒时,前面几张已经落库却还没起线程 —— 此前它们永远停在 queued。"""
    from app.db.models import Job
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.jobs import create_job

    client, ws, _fake = setup
    children: list[str] = []

    def create(db, **kwargs):
        if len(children) == 2:
            raise GenerationDomainError("genErr_noDefaultModel")
        job = create_job(db, workspace_id=ws, kind="ai_generation", payload={}, created_by=None)
        db.commit()  # 和真的漏斗一样:每建一张就提交
        children.append(job.id)
        return SimpleNamespace(id=f"gen-{len(children)}"), job

    monkeypatch.setattr("app.domain.generation.create_generation_job", create)
    entity_id = _entity(client, ws)
    with unit_of_work() as db, pytest.raises(WorkflowDomainError) as refused:
        executors.entity_angles(db, _scope(ws), {"entity_id": entity_id})
    assert refused.value.key == "genErr_noDefaultModel" and len(children) == 2
    with unit_of_work() as db:
        assert [(db.get(Job, one).status, db.get(Job, one).error_key) for one in children] == [("failed", "jobErr_cancelled")] * 2

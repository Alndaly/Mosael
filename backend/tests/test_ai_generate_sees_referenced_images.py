"""「AI 生成素材」节点:提示词里**引用到的图片素材**,运行时以「参考图」并进「输入素材」。

大模型节点那一笔(ADR 0067)解决了「提示词里 @ 了一张图,模型从没见过它」。同一个断层在生成节点上还在,
而且更贵:那里发错只是多带一张图,这里**以什么角色发**由模型能力决定 —— 猜错角色就是一次报错或者一次
白花钱的生成。所以这一笔多一道**能力闸**:只有描述符说这个模型收这个角色时,才把引用到的素材并进去;
模型不收时既不硬塞、也不沉默(界面上说清,见 NodeInspector 那一条)。

走真的工作流引擎(`binding.with_referenced_assets` 在 `engine.run_node` 里),只把 `ai_generate` 这一个
执行体换成记录用的假货 —— 它按配置把素材归一、并按内置模型的能力表**再校验一遍**(和生成漏斗提交前
同一个函数):角色错了在这里就炸,不会安静地生成出别的东西。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from app.core.db import SessionLocal
from app.db.models import Job, Workflow
from app.domain.generation.operations import keep_source_group, parse_source_assets, validate_against_capabilities
from app.domain.workflows import NODE_TYPES, create_workflow
from app.domain.workflows import executors as registry
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.revisions import attest_current_revision
from tests.util import fresh_client, insert_asset, user_id

#: 收参考图的图像模型(内置目录:火山 Seedream 4,`source_limits.reference_image = 14`)。
SEEDREAM = {"provider": "bytedance", "model": "doubao-seedream-4-0-250828", "kind": "image"}
#: 图生视频:收**首帧**、不收参考图(参数面里根本没有 `reference_image`)。能力闸那两条用它。
WAN_I2V = {"provider": "alibaba", "model": "wan2.7-i2v", "kind": "video"}
#: 纯文生图:参考图、首帧都不收。
QWEN_TEXT = {"provider": "alibaba", "model": "qwen-image", "kind": "image"}


class Studio:
    """把 `ai_generate` 换成记录用的假货:真的解析、真的按描述符校验,只是不花钱、不落生成任务。"""

    def __init__(self, monkeypatch, workspace_id: str, output_asset: str) -> None:
        self.workspace_id = workspace_id
        self.output_asset = output_asset
        self.calls: list[dict] = []
        monkeypatch.setitem(registry._REGISTRY, "ai_generate", self.generate)

    def generate(self, db, scope, config) -> dict:
        kind = str(config.get("kind") or "image")
        sources = keep_source_group(
            parse_source_assets(config.get("source_assets"), kind=kind),
            str(config.get("source_group") or "all").strip(),
        )
        #: 生成漏斗提交前的那一道,原样再走一遍:参数和素材组合这个模型认不认。
        validate_against_capabilities(
            str(config.get("provider") or ""), str(config.get("model") or ""), kind,
            dict(config.get("parameters") or {}), sources,
        )
        self.calls.append({"config": dict(config), "sources": sources})
        return {"asset_id": self.output_asset, "asset_ids": [], "generation_id": ""}

    def roles(self) -> list[str]:
        """这一次真的发给模型的素材角色,按顺序。"""
        return [one["role"] for one in self.calls[-1]["sources"]]

    def assets(self) -> list[str]:
        return [one["asset_id"] for one in self.calls[-1]["sources"]]


def _stored_config(workflow_id: str) -> dict:
    """库里那一份生成节点的配置(跑完之后)—— 钉住「推导在运行时,不写回库」。"""
    with SessionLocal() as db:
        graph = db.get(Workflow, workflow_id).graph
    for node in graph.get("nodes") or []:
        if node.get("type") == "ai_generate":
            return dict(node.get("config") or {})
    raise AssertionError("图里没有生成节点")


def _run(client, workspace_id: str, studio: Studio, pics: dict[str, str], **ask: object) -> tuple[Job, dict]:
    """跑一次工作流:`pics` 是「节点 id → 素材 id」,`ask` 覆盖生成节点那一格里的键。"""
    config: dict[str, object] = {"prompt": "照这张画一张", **ask}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            *({"id": nid, "type": "asset", "config": {"asset_id": asset}} for nid, asset in pics.items()),
            {"id": "draw", "type": "ai_generate", "config": config},
        ],
        "edges": [
            {"id": f"e{i}", "source": "start", "target": nid}
            for i, nid in enumerate(pics)
        ] + [
            {"id": f"d{i}", "source": nid, "target": "draw"} for i, nid in enumerate(pics)
        ],
    }
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=workspace_id, name="引用即发送", graph=graph, created_by=user_id())
        db.commit()
        workflow = db.get(Workflow, workflow.id)
        workflow_id = workflow.id
        attest_current_revision(db, workflow, attested_by=user_id())
        job_id = start_workflow_job(db, workflow, created_by=user_id()).id
        db.commit()
    for _ in range(200):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                return job, _stored_config(workflow_id)
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def _setup(monkeypatch, **kinds: str) -> SimpleNamespace:
    """一个工作区、几种素材、一个假生成执行体。`kinds`:名字 → 素材种类。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "引用即发送"}).json()["id"]
    assets = {name: insert_asset(workspace_id, kind=kind, name=name, file_key=f"media/ref/{name}") for name, kind in kinds.items()}
    output = insert_asset(workspace_id, kind="image", name="出图", file_key="media/ref/out.png")
    studio = Studio(monkeypatch, workspace_id, output)
    return SimpleNamespace(client=client, workspace_id=workspace_id, studio=studio, **assets)


# ── 先红的那一条:提示词引用了图片,`source_assets` 空着 ────────────────────────────────


def test_提示词里引用了图片素材_以参考图并进输入素材(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="照这张画一张 {{pic.asset_id}}", **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.pic], "提示词引用了图片素材,这一次生成就该带着它"
    assert setup.studio.roles() == ["reference_image"], "默认角色是「参考图」(维护者拍板)"


def test_引用即发送是运行时推导_老图不用改配置(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                       prompt="照 {{pic.asset_id}} 这张画", **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert not stored.get("source_assets"), "同步只在运行时推导,库里那份配置一个 id 都没写进去"
    assert setup.studio.assets() == [setup.pic]


# ── 能力闸:模型不收这个角色,就不许硬塞 ─────────────────────────────────────────────


def test_模型不收参考图_就不并进去(monkeypatch) -> None:
    """图生视频的模型只收首帧:引用到的图**不能**按参考图塞进去 —— 那是提交期的一次报错。

    手动挑的那一份首帧照旧在(排在前),引用来的那张不并。
    """
    setup = _setup(monkeypatch, pic="image", photo="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="动起来 {{pic.asset_id}}", source_assets=[f"{setup.photo}:first_frame"], **WAN_I2V)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.photo], "不收的角色一个都不许塞进去"
    assert setup.studio.roles() == ["first_frame"]


def test_模型什么角色都不收_也不并(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="画一张 {{pic.asset_id}}", **QWEN_TEXT)
    assert job.status == "succeeded", job.error
    assert setup.studio.calls[-1]["sources"] == []


def test_角色改成模型收的那一个_就并进去(monkeypatch) -> None:
    """同一个模型(只收首帧):用户把这条引用的角色改成首帧,那就该发出去 —— 闸按**角色**判,不按字段判。"""
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="动起来 {{pic.asset_id}}", source_assets_roles=["pic.asset_id:first_frame"], **WAN_I2V)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.pic]
    assert setup.studio.roles() == ["first_frame"]


# ── 手动那三条语义 ─────────────────────────────────────────────────────────────────


def test_手动挑的素材保留_排在引用来的前面(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image", photo="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="两张一起看 {{pic.asset_id}}", source_assets=[f"{setup.photo}:reference_image"], **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.photo, setup.pic], "手动挑的在前,引用来的接在后面"


def test_手动删掉自动来的_就不发_下一轮也不再塞回来(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="看图 {{pic.asset_id}}", source_assets_excluded=["pic.asset_id"], **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.calls[-1]["sources"] == [], "点名不要的那条引用不再自动带上"


def test_排除其中一条引用_另一条照发(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image", photo="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic, "photo": setup.photo},
                        prompt="{{pic.asset_id}} 和 {{photo.asset_id}}",
                        source_assets_excluded=["pic.asset_id"], **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.photo]


def test_引用的是视频_跳过不报错(monkeypatch) -> None:
    """参考图那一格收的是**图片**:引用到一段视频时跳过(硬塞进去换来一次 400,而提示词没问题)。"""
    setup = _setup(monkeypatch, clip="video")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"clip": setup.clip},
                        prompt="看看这段 {{clip.asset_id}}", **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.calls[-1]["sources"] == []


def test_引用的是素材的名字不是素材本身_不并(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="这份素材叫 {{pic.name}}", **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.calls[-1]["sources"] == []


def test_同一条引用写两遍_只并一次(monkeypatch) -> None:
    setup = _setup(monkeypatch, pic="image")
    job, _stored = _run(setup.client, setup.workspace_id, setup.studio, {"pic": setup.pic},
                        prompt="{{pic.asset_id}} 和 {{pic.asset_id}}", **SEEDREAM)
    assert job.status == "succeeded", job.error
    assert setup.studio.assets() == [setup.pic]


# ── 声明本身 ───────────────────────────────────────────────────────────────────────


def test_声明成套_有角色就必须有能力闸() -> None:
    """声明了 `ref_assets_role` 的字段必须同时声明 `ref_assets_gate`,而且闸认得这个名字。

    少了闸 = 把引用到的素材**硬塞**给一个未必收的模型(那正是这一笔要防的事);闸的名字打错 =
    注入那一段静默地什么都不做。两种都只有这条测试拦得住。
    """
    from app.domain.workflows.binding import REF_ASSET_GATES

    for node_type, spec in NODE_TYPES.items():
        for key, field in (spec.get("config") or {}).items():
            if not isinstance(field, dict) or not field.get("ref_assets_role"):
                continue
            gate = field.get("ref_assets_gate")
            assert gate in REF_ASSET_GATES, f"{node_type}.{key} 声明的能力闸 {gate!r} 不认识"

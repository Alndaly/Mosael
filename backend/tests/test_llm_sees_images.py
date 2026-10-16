"""大模型节点要能**看着图**回答:提示词里引用到的图片素材(和「要模型看的图片」那一格手动挑的图)
都要和提示词一起发过去(多模态消息)。

此前 LLM 节点只发一段文字 —— 提示词里写 `{{画图.asset_id}}`,模型收到的是一串素材编号,从没见过那张图。
**引用即发送**:提示词(或系统提示词)里引用到的图片素材自动进「要模型看的图片」,不需要用户再手动挑一遍;
老图(config 里没有那一串 id)照样如此 —— 这条推导是运行时的语义本身,不是兼容分支。

走真的工作流引擎,只把最外面那一次对话请求换成桩,看发出去的消息长什么样。
"""

from __future__ import annotations

import base64
import time
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import Job, Workflow
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.revisions import attest_current_revision
from tests.util import add_provider, fresh_client, insert_asset, user_id

#: 一张 1×1 的 PNG。
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
#: 另一张 1×1 的 PNG(手动挑的那张),和上面那张字节不同,发出去的数据 URI 因此分得开。
PNG2 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def setup(monkeypatch):
    from app.domain.workflows.executors import ai

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "看图"}).json()["id"]
    folder = settings.media_dir / "llm-images"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cat.png").write_bytes(PNG)
    (folder / "dog.png").write_bytes(PNG2)
    image = insert_asset(workspace_id, kind="image", name="猫", file_key="media/llm-images/cat.png")
    photo = insert_asset(workspace_id, kind="image", name="狗", file_key="media/llm-images/dog.png")
    video = insert_asset(workspace_id, kind="video", name="一段视频", file_key="media/llm-images/clip.mp4")
    with SessionLocal() as db:
        profile = add_provider(db, name="对话", vendor="openai", base_url="https://a.example/v1", api_key="k",
                               model="chat-a", capability_ids=["chat"], owner_username="tester")
        db.commit()
        profile_id = profile.id

    sent: list[list[dict]] = []
    #: 每次运行里**库里存着的那份图** —— 证明同步是运行时推导出来的,配置没被改写。
    stored: list[dict] = []

    def fake_chat(target, messages, **_kw):
        sent.append(messages)
        return "一只猫"

    monkeypatch.setattr(ai, "chat", fake_chat)

    def run(image_asset_ids: str = "", **ask: object) -> Job:
        """跑一次。`ask` 覆盖大模型节点那一格里的键(prompt / system / image_asset_ids / …)。"""
        config: dict[str, object] = {
            "profile_id": profile_id, "model": "chat-a", "prompt": "图里是什么?", "image_asset_ids": image_asset_ids,
        }
        config.update(ask)
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "pic", "type": "asset", "config": {"asset_id": image}},
                {"id": "clip", "type": "asset", "config": {"asset_id": video}},
                {"id": "ask", "type": "llm", "config": config},
            ],
            "edges": [
                {"id": "e0", "source": "start", "target": "clip"},
                {"id": "e1", "source": "start", "target": "pic"},
                {"id": "e2", "source": "pic", "target": "ask"},
                {"id": "e3", "source": "clip", "target": "ask"},
            ],
        }
        with SessionLocal() as db:
            workflow = create_workflow(db, workspace_id=workspace_id, name="看图", graph=graph, created_by=user_id())
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
                    stored.append(_stored_llm_config(workflow_id))
                    return job
            time.sleep(0.05)
        raise AssertionError("工作流没跑完")

    return SimpleNamespace(run=run, sent=sent, stored=stored, image=image, photo=photo, video=video)


def _stored_llm_config(workflow_id: str) -> dict:
    """库里那一份大模型节点的配置(跑完之后)。"""
    with SessionLocal() as db:
        graph = db.get(Workflow, workflow_id).graph
    for node in graph.get("nodes") or []:
        if node.get("type") == "llm":
            return dict(node.get("config") or {})
    raise AssertionError("图里没有大模型节点")


def _user_turn(messages: list[dict]) -> object:
    return next(one for one in messages if one["role"] == "user")["content"]


def _image_urls(content: object) -> list[str]:
    assert isinstance(content, list), "有图时用户那一条是多模态消息,不是一段字"
    return [part["image_url"]["url"] for part in content if isinstance(part, dict) and part.get("type") == "image_url"]


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def test_接上游的图_图和提示词一起发给模型(setup) -> None:
    job = setup.run("{{pic.asset_id}}")
    assert job.status == "succeeded", job.error
    content = _user_turn(setup.sent[0])
    assert isinstance(content, list), "有图时用户那一条是多模态消息,不是一段字"
    assert content[0] == {"type": "text", "text": "图里是什么?"}
    assert _image_urls(content) == [_data_uri(PNG)], "发过去的是那张图本身,不是素材编号"


def test_不接图_照旧只发一段字(setup) -> None:
    assert setup.run("").status == "succeeded"
    assert _user_turn(setup.sent[0]) == "图里是什么?"


def test_给了视频_当场说清只收图片_不白花一次调用(setup) -> None:
    job = setup.run(setup.video)
    assert job.status == "failed"
    assert "一段视频" in (job.error or "") and "只收图片" in (job.error or ""), job.error
    assert setup.sent == []


def test_不在工作区的图_说清是哪一张(setup) -> None:
    job = setup.run("no-such-asset")
    assert job.status == "failed"
    assert t("wfErr_llmImageMissing", "zh", asset_id="no-such-asset") in (job.error or ""), job.error
    assert setup.sent == []


def test_超过张数上限_当场拦(setup) -> None:
    job = setup.run(",".join([setup.image] * 9))
    assert job.status == "failed" and "最多" in (job.error or ""), job.error
    assert setup.sent == []


# ── 引用即发送:提示词里引用了图片素材,模型就必须看到那张图 ──────────────────────────────


def test_提示词里引用了图片素材_不写进那一格也发给模型(setup) -> None:
    """**先红的那一条**:`image_asset_ids` 空着,提示词里 `{{pic.asset_id}}` 引用了图片素材。"""
    job = setup.run("", prompt="这张图里是什么?{{pic.asset_id}}")
    assert job.status == "succeeded", job.error
    content = _user_turn(setup.sent[0])
    assert _image_urls(content) == [_data_uri(PNG)], "提示词引用了图片素材,模型就该看到那张图"
    assert content[0] == {"type": "text", "text": f"这张图里是什么?{setup.image}"}


def test_引用即发送是运行时推导_老图不用改配置(setup) -> None:
    """跑完再看库里那份配置:一个 id 都没被写进去 —— 推导在运行时,不是保存时同步出来的。"""
    assert setup.run("", prompt="{{pic.asset_id}} 里是什么?").status == "succeeded"
    assert not setup.stored[0].get("image_asset_ids"), "同步只在运行时推导,配置里一个 id 都没写进去"
    assert _image_urls(_user_turn(setup.sent[0])) == [_data_uri(PNG)]


def test_系统提示词里引用的图片素材_也算(setup) -> None:
    job = setup.run("", system="看着 {{pic.asset_id}} 回答", prompt="图里是什么?")
    assert job.status == "succeeded", job.error
    assert _image_urls(_user_turn(setup.sent[0])) == [_data_uri(PNG)]


def test_手动挑的和引用来的都发_手动在前_各一张(setup) -> None:
    job = setup.run(setup.photo, prompt="两张都看:{{pic.asset_id}}")
    assert job.status == "succeeded", job.error
    assert _image_urls(_user_turn(setup.sent[0])) == [_data_uri(PNG2), _data_uri(PNG)]


def test_同一条引用写两遍_只发一张(setup) -> None:
    job = setup.run("", prompt="{{pic.asset_id}} 和 {{pic.asset_id}}")
    assert job.status == "succeeded", job.error
    assert _image_urls(_user_turn(setup.sent[0])) == [_data_uri(PNG)]


def test_引用了视频素材_跳过不报错_也不当成图(setup) -> None:
    """非图片的引用:跳过(视频硬塞进去会报错),照旧只发文字。"""
    job = setup.run("", prompt="看看这段视频 {{clip.asset_id}}")
    assert job.status == "succeeded", job.error
    assert _user_turn(setup.sent[0]) == f"看看这段视频 {setup.video}"


def test_引用的是素材的名字不是素材本身_不发图(setup) -> None:
    job = setup.run("", prompt="这份素材叫 {{pic.name}}")
    assert job.status == "succeeded", job.error
    assert _user_turn(setup.sent[0]) == "这份素材叫 猫"


def test_自动来的图被删掉_就不发_且下一轮不再塞回来(setup) -> None:
    """用户手动删掉一张**自动来的**图:记一条显式排除,运行时的取图认它。"""
    job = setup.run("", prompt="看图 {{pic.asset_id}}", image_asset_ids_excluded=["pic.asset_id"])
    assert job.status == "succeeded", job.error
    assert _user_turn(setup.sent[0]) == f"看图 {setup.image}", "被点名排除的引用不再自动带图"


def test_排除其中一条引用_另一条照发(setup) -> None:
    job = setup.run("", prompt="{{pic.asset_id}} 和 {{pic.name}}", image_asset_ids_excluded=["pic.name"])
    assert job.status == "succeeded", job.error
    assert _image_urls(_user_turn(setup.sent[0])) == [_data_uri(PNG)]

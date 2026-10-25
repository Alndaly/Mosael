"""飞书消息触发工作流:一条匹配的消息起一次运行,其余的照旧(ADR 0065)。

验收那六条各自在这里:

1. 一条匹配的消息 → **起了一次运行**、入参对(`test_一条匹配的消息起一次运行`);
2. 不匹配的消息 → 不起(`test_认不上的消息不起运行_照旧走智能体会话`);
3. 同一条消息重复投递 → **只起一次**(`test_同一条消息重复投递只起一次`);
4. 风暴 → 按限流规则生效(`test_风暴按限流丢掉_而且留痕`);
5. 工作流被删 / 跑不起来 → 按 ADR 定的语义(`test_删工作流时触发器当场停用`、
   `test_跑不起来时留痕并通知主人_群里不喊`);
6. 智能体会话那条链路不受影响(`test_认不上的消息不起运行_照旧走智能体会话`,以及既有的
   `tests/test_feishu.py` 整份)。

还有两条是这一族自己的门面:纯匹配(不碰数据库)与接口的增删改查 / 最近触发。
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import datetime

from sqlalchemy import select

from app.ai.sidecar.pi_client import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentSession, Job, Workflow, WorkflowTrigger, WorkflowTriggerEvent
from app.domain.agent import host
from app.domain.feishu import bindings
from app.domain.jobs import wait_for_idle_jobs
from app.domain.triggers import dispatch, matching
from app.integrations.feishu import client as feishu_client
from app.integrations.feishu import inbound
from tests.util import fresh_client

#: 等一次工作流跑完的预算(秒)。
_RUN_BUDGET = 60


def _unique(prefix: str) -> str:
    return f"{prefix}-{time.time()}-{len(prefix)}"


def _graph(*params: str, required: list[str] | None = None) -> dict:
    """一张最小可跑的图:开始节点(带几个参数)→ 模板节点(把第一个参数原样交出来)。

    没有会花钱的节点 —— 触发器的运行不需要任何供应商连接就能跑完(测试也不该依赖网络)。
    """
    names = list(params) or ["text"]
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {name: "" for name in names}, "required_params": required or []}},
            {"id": "t", "type": "template", "config": {"template": "{{start.%s}}" % names[0]}},
        ],
        "edges": [{"id": "e", "source": "start", "target": "t"}],
    }


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _bound_bot(client, workspace_id: str, *, app_id: str = "cli_trigger") -> tuple[dict, str]:
    """建一个机器人 + 把一个飞书发送者绑到当前账号(触发器只认绑定过的人)。"""
    bot = client.post(
        "/api/feishu/bots", json={"workspace_id": workspace_id, "app_id": app_id, "app_secret": "s3cret"}
    ).json()
    me = client.get("/api/auth/me").json()
    open_id = f"ou_{app_id}"
    with SessionLocal() as db:
        #: 绑到**这台机器人**上:open_id 按飞书应用隔离。
        code, _ = bindings.issue_bind_code(db, workspace_id, me["id"])
        assert bindings.redeem_bind_code(db, workspace_id, bot["id"], open_id, code) is not None
        db.commit()
    return bot, open_id


def _workflow(client, workspace_id: str, *, name: str = "被触发的流", graph: dict | None = None) -> dict:
    return client.post(
        "/api/workflows",
        json={"workspace_id": workspace_id, "name": name, "graph": graph or _graph("text")},
    ).json()


def _trigger(client, workspace_id: str, workflow_id: str, **fields) -> dict:
    body = {
        "workspace_id": workspace_id,
        "workflow_id": workflow_id,
        "name": "群里的视频",
        "message_types": ["text"],
        **fields,
    }
    res = client.post("/api/workflow-triggers", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _incoming(bot_id: str, chat_id: str, message_id: str, sender: str, **kwargs) -> None:
    inbound.handle_incoming(bot_id, chat_id, message_id, sender, **kwargs)


def _runs(client, workflow_id: str) -> list[dict]:
    return client.get(f"/api/workflows/{workflow_id}/runs").json()


def _events(client, trigger_id: str) -> list[dict]:
    return client.get(f"/api/workflow-triggers/{trigger_id}/events").json()


def _job(job_id: str) -> Job:
    with SessionLocal() as db:
        return db.get(Job, job_id)  # type: ignore[return-value]


def _sent_texts(monkeypatch) -> list[tuple[str, str]]:
    """回执走 `send_text`,运行结果走 `send_markdown`(卡片)—— 两边都接进同一份清单。"""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(feishu_client, "send_text", lambda bot, chat_id, text, **k: sent.append((chat_id, text)))
    monkeypatch.setattr(feishu_client, "send_markdown", lambda bot, chat_id, text, **k: sent.append((chat_id, text)))
    return sent


# ---------------- 1. 匹配 → 起一次运行、入参对 ----------------


def test_一条匹配的消息起一次运行(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t1")
    workflow = _workflow(client, ws, name="视频转码", graph=_graph("text"))
    trigger = _trigger(client, ws, workflow["id"], params={"text": "处理:{{trigger.text}}"})
    sent = _sent_texts(monkeypatch)
    agent_ran: list[object] = []
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: agent_ran.append(a))

    _incoming(
        bot["id"], "oc_g", _unique("m"), open_id,
        content_json=json.dumps({"text": "这条视频帮我转一下"}),
    )

    runs = _runs(client, workflow["id"])
    assert len(runs) == 1, "匹配的消息应该起一次运行"
    job = _job(runs[0]["id"])
    #: 入参按映射算:模板里的 {{trigger.text}} 换成了消息文本。
    assert job.payload["params"] == {"text": "处理:这条视频帮我转一下"}
    #: 命中的消息**不再喂给智能体**(ADR 0065 §3)。
    assert agent_ran == []
    #: 回执点了触发器的名字 —— 用户据此看出这次是触发器起的。
    assert sent and "群里的视频" in sent[0][1] and "视频转码" in sent[0][1]

    events = _events(client, trigger["id"])
    assert [one["status"] for one in events] == ["started"]
    assert events[0]["job_id"] == runs[0]["id"]


def test_同名直填_不必配映射(monkeypatch) -> None:
    """开始节点里有个参数正好叫 `text` 时,入参映射可以留空(ADR 0065 §2 那条便利)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t2")
    workflow = _workflow(client, ws, graph=_graph("text"))
    _trigger(client, ws, workflow["id"], params={})
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "原文"}))

    runs = _runs(client, workflow["id"])
    assert len(runs) == 1
    assert _job(runs[0]["id"]).payload["params"] == {"text": "原文"}


# ---------------- 2. 不匹配 → 不起 ----------------


def test_认不上的消息不起运行_照旧走智能体会话(monkeypatch) -> None:
    """筛选不命中时一切如常:智能体那一轮照跑、照回(**这一条守的是"没改坏")**。"""
    client = fresh_client()
    from tests.test_feishu import _configured

    _configured(client)
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t3")
    workflow = _workflow(client, ws)
    #: 关键词与消息不符。
    trigger = _trigger(client, ws, workflow["id"], keywords=["发布"], params={})
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="我是智能体"))

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "随便聊聊"}))

    assert host.wait_for_idle_turns(_RUN_BUDGET)
    assert _runs(client, workflow["id"]) == [], "不匹配就不该起运行"
    assert _events(client, trigger["id"]) == [], "不匹配连事件都不留"
    assert sent == [("oc_g", "我是智能体")], "没被认领的消息照旧交给智能体"


def test_类型不对的消息也不起(monkeypatch) -> None:
    client = fresh_client()
    from tests.test_feishu import _configured

    _configured(client)
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t4")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], message_types=["media"], params={})
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="智能体回的"))

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "只是文字"}))

    assert host.wait_for_idle_turns(_RUN_BUDGET)
    assert _runs(client, workflow["id"]) == [], "只认视频的触发器不该被一条文字叫起来"
    assert _events(client, trigger["id"]) == []
    #: 这条消息照旧被智能体接待(守的是"没改坏")。
    assert sent == [("oc_g", "智能体回的")]


# ---------------- 3. 重复投递 → 只起一次 ----------------


def test_同一条消息重复投递只起一次(monkeypatch) -> None:
    """飞书会重放同一条消息,而**重启之后**进程内那份去重(seen_recently)就没了 ——
    判据因此落在库里((trigger_id, message_id) 唯一约束,ADR 0065 §4)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t5")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    message_id = _unique("dup")
    for _ in range(2):
        _incoming(bot["id"], "oc_g", message_id, open_id, content_json=json.dumps({"text": "同一条"}))
    #: 模拟一次重启:进程内那份去重清掉,库里那行还在。
    with inbound._seen_lock:
        inbound._seen.clear()
    _incoming(bot["id"], "oc_g", message_id, open_id, content_json=json.dumps({"text": "同一条"}))

    assert len(_runs(client, workflow["id"])) == 1, "同一条消息只能起一次"
    assert [one["status"] for one in _events(client, trigger["id"])] == ["started"]
    receipts = [text for _, text in sent if "已按触发器" in text]
    assert len(receipts) == 1, f"只回一次回执:{sent}"


# ---------------- 4. 风暴 → 限流 ----------------


def test_风暴按限流丢掉_而且留痕(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t6")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={}, max_runs_per_minute=2)
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    for index in range(5):
        _incoming(
            bot["id"], "oc_g", _unique(f"storm{index}"), open_id,
            content_json=json.dumps({"text": f"第 {index} 条"}),
        )

    statuses = [one["status"] for one in _events(client, trigger["id"])]
    assert statuses.count("started") == 2, f"限流只放两次,实际 {statuses}"
    assert statuses.count("throttled") == 3, f"超出的那些要留痕,实际 {statuses}"
    assert len(_runs(client, workflow["id"])) == 2


def test_一条消息最多认领三条触发器(monkeypatch) -> None:
    """一个工作区里十条触发器都认同一句话时,一句话不该起十次运行(ADR 0065 §4 的兜底)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t7")
    workflow = _workflow(client, ws)
    triggers = [_trigger(client, ws, workflow["id"], name=f"t{index}", params={}) for index in range(5)]
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("many"), open_id, content_json=json.dumps({"text": "一条消息"}))

    started = sum(1 for one in triggers for event in _events(client, one["id"]) if event["status"] == "started")
    skipped = sum(1 for one in triggers for event in _events(client, one["id"]) if event["status"] == "skipped")
    assert started == 3
    assert skipped == 2


# ---------------- 5. 工作流被删 / 跑不起来 ----------------


def test_删工作流时触发器当场停用(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t8")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    assert client.delete(f"/api/workflows/{workflow['id']}").status_code == 204

    listed = client.get(f"/api/workflow-triggers?workspace_id={ws}").json()
    assert [one["enabled"] for one in listed] == [False], "图没了,触发器不能再自己跑"
    #: 触发器留着(连它的名字和最近触发记录),删不删由人决定。
    assert listed[0]["name"] == trigger["name"]

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "还有人在发"}))
    assert _events(client, trigger["id"]) == [], "停用之后连事件都不该有"


def test_跑不起来时留痕并通知主人_群里不喊(monkeypatch) -> None:
    """配错的自动化**不能**沉默(群里的人以为它跑了),也不能在群里喊(他们改不了它)——
    留痕 + 站内通知主人(ADR 0065 §5)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t9")
    #: 必填的 text,而映射交的是空串 → 开跑前那一道拦下。
    workflow = _workflow(client, ws, graph=_graph("text", required=["text"]))
    trigger = _trigger(client, ws, workflow["id"], params={"text": ""})
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": ""}))
    #: 空文本的消息本来就被丢掉,换个有文本但映射成空的场景:消息文本有,映射不看它。
    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "有内容"}))

    events = _events(client, trigger["id"])
    assert [one["status"] for one in events] == ["refused"], f"该留痕,实际 {events}"
    assert "缺少必填" in events[0]["error"]
    assert _runs(client, workflow["id"]) == []
    assert sent == [], "配置错误不在群里喊"

    notices = client.get(f"/api/notifications?workspace_id={ws}").json()["items"]
    titles = [one["title"] for one in notices]
    assert any("群里的视频" in title for title in titles), f"主人该收到通知,实际 {titles}"


def test_没绑机器人时什么都不发生(monkeypatch) -> None:
    """机器人停用了,消息本来就到不了这一层 —— 静默是对的(没有 bot 就没有入站)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t10")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    sent = _sent_texts(monkeypatch)
    client.patch(f"/api/feishu/bots/{bot['id']}", json={"enabled": False})

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "你好"}))

    assert _events(client, trigger["id"]) == []
    assert sent == []


# ---------------- 附件:图片 / 文件 / 视频 ----------------


def test_视频消息进素材库_并当入参(monkeypatch) -> None:
    """群里丢一条视频 → 它先进素材库,素材 id 按映射交给开始节点(ADR 0065 §2)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t11")
    workflow = _workflow(client, ws, graph=_graph("asset_id"))
    _trigger(
        client, ws, workflow["id"], message_types=["media"],
        params={"asset_id": "{{trigger.asset_id}}"},
    )
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)
    monkeypatch.setattr(feishu_client, "download_message_resource", lambda *a, **k: b"fake-mp4-bytes")

    class _Asset:
        id = "asset-from-feishu"

    monkeypatch.setattr("app.domain.assets.importer.import_binary_asset", lambda *a, **k: _Asset())

    _incoming(
        bot["id"], "oc_g", _unique("m"), open_id, message_type="media",
        content_json=json.dumps({"file_key": "fk_1", "file_name": "clip.mp4", "duration": 3000}),
    )

    runs = _runs(client, workflow["id"])
    assert len(runs) == 1
    assert _job(runs[0]["id"]).payload["params"] == {"asset_id": "asset-from-feishu"}
    assert sent and "视频转码" not in sent[0][1]


def test_文件取不回来就不跑_而且说一句(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t12")
    workflow = _workflow(client, ws, graph=_graph("asset_id"))
    trigger = _trigger(client, ws, workflow["id"], message_types=["file"], params={})
    sent = _sent_texts(monkeypatch)

    def boom(*a, **k):
        raise feishu_client.FeishuError("下载飞书资源失败(404)")

    monkeypatch.setattr(feishu_client, "download_message_resource", boom)

    _incoming(
        bot["id"], "oc_g", _unique("m"), open_id, message_type="file",
        content_json=json.dumps({"file_key": "fk_2", "file_name": "素材.zip"}),
    )

    assert _runs(client, workflow["id"]) == [], "素材就是入参,取不回来不该硬跑"
    assert sent and "没能取回来" in sent[0][1]
    assert _events(client, trigger["id"]) == [], "附件没到,这条消息没被认领过"


def test_没有触发器接的文件消息还是那句看不了(monkeypatch) -> None:
    """`file` / `media` 从「智能体看不了」变成「触发器可能接」之后,没人接时要回到原样。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t13")
    sent = _sent_texts(monkeypatch)

    _incoming(
        bot["id"], "oc_g", _unique("m"), open_id, message_type="media",
        content_json=json.dumps({"file_key": "fk_3", "file_name": "clip.mp4"}),
    )

    assert sent and "看不了视频" in sent[0][1]


# ---------------- 结果发回群 ----------------


def test_跑完之后把结果发回群(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t14")
    workflow = _workflow(client, ws, graph=_graph("text"))
    _trigger(client, ws, workflow["id"], params={"text": "{{trigger.text}}"})
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "写一句话"}))

    assert wait_for_idle_jobs(_RUN_BUDGET), "工作流没在预算内跑完"
    runs = _runs(client, workflow["id"])
    assert runs[0]["status"] == "succeeded", runs
    body = "\n".join(text for _, text in sent)
    assert "写一句话" in body, f"结果没发回群:{sent}"


def test_关掉回群之后只留痕(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t15")
    workflow = _workflow(client, ws, graph=_graph("text"))
    trigger = _trigger(client, ws, workflow["id"], params={"text": "{{trigger.text}}"}, reply_in_chat=False)
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "安静地跑"}))
    assert wait_for_idle_jobs(_RUN_BUDGET)

    assert sent == []
    assert [one["status"] for one in _events(client, trigger["id"])] == ["started"]


# ---------------- 纯匹配:不碰数据库 ----------------


def _fake_trigger(**fields):
    class _Trigger:
        message_types = ["text"]
        bot_id = ""
        chat_id = ""
        only_from_open_ids: list[str] = []
        keywords: list[str] = []

    trigger = _Trigger()
    for key, value in fields.items():
        setattr(trigger, key, value)
    return trigger


def _message(**fields) -> matching.IncomingMessage:
    base = {
        "workspace_id": "w",
        "bot_id": "b",
        "chat_id": "c",
        "message_id": "m",
        "sender_open_id": "ou_1",
        "message_type": "text",
    }
    return matching.IncomingMessage(**{**base, **fields})


def test_匹配的四个筛子() -> None:
    message = _message(text="帮我发一条产品视频")
    assert matching.decide(_fake_trigger(), message) == ""
    #: 富文本对用户来说就是文字。
    assert matching.decide(_fake_trigger(), _message(message_type="post", text="x")) == ""
    assert matching.decide(_fake_trigger(message_types=["image"]), message) == "message_type"
    assert matching.decide(_fake_trigger(bot_id="other"), message) == "bot"
    assert matching.decide(_fake_trigger(chat_id="other"), message) == "chat"
    assert matching.decide(_fake_trigger(only_from_open_ids=["ou_2"]), message) == "sender"
    assert matching.decide(_fake_trigger(keywords=["产品"]), message) == ""
    assert matching.decide(_fake_trigger(keywords=["产品", "无关的"]), message) == ""
    assert matching.decide(_fake_trigger(keywords=["发布"]), message) == "keyword"
    #: 大小写不敏感。
    assert matching.decide(_fake_trigger(keywords=["VIDEO"]), _message(text="make a Video now")) == ""
    #: 认不了的消息类型(语音、表情……)一概不认。
    assert matching.decide(_fake_trigger(), _message(message_type="audio")) == "message_type"


def test_占位符白名单与渲染() -> None:
    assert matching.unknown_placeholders("{{trigger.text}} 和 {{trigger.nope}}") == ["nope"]
    assert matching.bad_placeholders({"a": "{{trigger.text}}", "b": "{{trigger.zzz}}"}) == ["zzz"]
    values = matching.values_of(_message(asset_ids=("a1", "a2")))
    assert matching.render("看:{{trigger.text}}", values) == "看:"
    assert matching.render("{{trigger.asset_id}}/{{trigger.asset_ids}}", values) == "a1/a1,a2"
    #: 认不出的原样留着(保存那一道已经拦过)。
    assert matching.render("{{trigger.nope}}", values) == "{{trigger.nope}}"


def test_入参映射_显式优先_同名直填在后() -> None:
    values = matching.values_of(_message(text="原文", file_name="a.mp4", asset_ids=("a1",)))
    params = matching.render_params({"prompt": "前缀 {{trigger.text}}"}, ["prompt", "text", "file_name"], values)
    assert params == {"prompt": "前缀 原文", "text": "原文", "file_name": "a.mp4"}


def test_开始节点的参数名按图取() -> None:
    assert matching.start_param_names(_graph("topic", "brief")) == ["topic", "brief"]
    assert matching.start_param_names({"nodes": []}) == []


# ---------------- 接口:增删改查 + 最近触发 ----------------


def test_接口的增删改查与最近触发() -> None:
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    created = _trigger(
        client, ws, workflow["id"], name="入库", message_types=["image", "media"],
        keywords=["素材"], params={"text": "{{trigger.text}}"},
    )
    assert created["message_types"] == ["image", "media"]
    assert created["params"] == {"text": "{{trigger.text}}"}
    assert created["enabled"] is True

    listed = client.get(f"/api/workflow-triggers?workspace_id={ws}&workflow_id={workflow['id']}").json()
    assert [one["id"] for one in listed] == [created["id"]]

    patched = client.patch(f"/api/workflow-triggers/{created['id']}", json={"enabled": False, "keywords": []}).json()
    assert patched["enabled"] is False and patched["keywords"] == []

    assert client.get(f"/api/workflow-triggers/{created['id']}/events").json() == []
    assert client.delete(f"/api/workflow-triggers/{created['id']}").status_code == 204
    assert client.get(f"/api/workflow-triggers?workspace_id={ws}").json() == []


def test_配置错误在保存时就拦() -> None:
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    base = {"workspace_id": ws, "workflow_id": workflow["id"], "name": "x", "message_types": ["text"]}

    bad_placeholder = client.post(
        "/api/workflow-triggers", json={**base, "params": {"text": "{{trigger.nope}}"}}
    )
    assert bad_placeholder.status_code == 422
    assert "nope" in bad_placeholder.json()["detail"]

    empty_types = client.post("/api/workflow-triggers", json={**base, "message_types": []})
    assert empty_types.status_code == 422

    bad_kind = client.post("/api/workflow-triggers", json={**base, "message_types": ["sticker"]})
    assert bad_kind.status_code == 422

    bad_limit = client.post("/api/workflow-triggers", json={**base, "max_runs_per_minute": 0})
    assert bad_limit.status_code == 422

    missing_workflow = client.post(
        "/api/workflow-triggers", json={**base, "workflow_id": "nope"}
    )
    assert missing_workflow.status_code == 422


def test_触发器按工作区过闸(monkeypatch) -> None:
    """看得见要先是这个工作区的人,改得了要 `edit`(ADR 0065:配触发器 = 让图在群里自己跑)。"""
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})

    from tests.util import second_client

    other = second_client("outsider")
    assert other.get(f"/api/workflow-triggers?workspace_id={ws}").status_code in (403, 404)
    assert other.patch(f"/api/workflow-triggers/{trigger['id']}", json={"enabled": False}).status_code in (403, 404)


def test_事件行的唯一约束是真的(monkeypatch) -> None:
    """去重靠库,不靠进程内存 —— 直接对库插两行同样的 (trigger, message) 也要被挡住。"""
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})

    from sqlalchemy.exc import IntegrityError

    import pytest

    with SessionLocal() as db:
        for _ in range(2):
            db.add(
                WorkflowTriggerEvent(
                    trigger_id=trigger["id"], workspace_id=ws, message_id="same-message",
                    bot_id="b", chat_id="c", status="started",
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


def test_触发器绑定的是这个工作区里的机器人() -> None:
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    res = client.post(
        "/api/workflow-triggers",
        json={
            "workspace_id": ws, "workflow_id": workflow["id"], "name": "x",
            "message_types": ["text"], "bot_id": "not-a-bot",
        },
    )
    assert res.status_code == 422


def test_绕过接口删掉工作流时_下一次触发留痕并停用自己(monkeypatch) -> None:
    """工作流被**直接删掉**(没走接口那条停用逻辑)时的兜底:这一次记一条 refused、
    顺手停用它自己,下一次不再白试(ADR 0065 §5)。行不随图消失 —— 别处删了图,痕迹要还在。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t17")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    with SessionLocal() as db:
        db.delete(db.get(Workflow, workflow["id"]))
        db.commit()
        #: 图没了,触发器还在(不设外键的取舍,见 model_slices/triggers)。
        assert db.get(WorkflowTrigger, trigger["id"]) is not None

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "还有人在发"}))

    events = _events(client, trigger["id"])
    assert [one["status"] for one in events] == ["refused"]
    assert "已删除" in events[0]["error"]
    assert client.get(f"/api/workflow-triggers?workspace_id={ws}").json()[0]["enabled"] is False


def test_会话链路自己的表没被动过(monkeypatch) -> None:
    """触发器起运行和智能体会话是两条不相干的路:认领之后**不建** AgentSession。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t16")
    workflow = _workflow(client, ws)
    _trigger(client, ws, workflow["id"], params={})
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m"), open_id, content_json=json.dumps({"text": "起一条"}))

    with SessionLocal() as db:
        assert db.scalars(select(AgentSession)).all() == [], "触发器的运行不该开一条智能体会话"


# ---------------- 入站链路 + 触发器的这一笔:八条,逐条先红后绿 ----------------


def _zip_bytes() -> bytes:
    """一份**真的** zip —— 素材库认不出它,`import_binary_asset` 会当场拒收。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "群里丢上来的压缩包")
    return buffer.getvalue()


def test_收不进素材库的文件也要回一句而不是静默(monkeypatch) -> None:
    """[high] 群里丢一个 .zip:下载拿得到,而素材库不收这种文件(`AssetFileTypeError`)。

    此前那条异常冒在 try **之外**,一路穿过 `_run_triggers` / `handle_incoming` 到
    `connections.dispatch` 起的 `feishu-inbound` 线程 —— 那条线程没有 wrapper:没有回执、
    没有事件行、连兜底那句都没有,而 `seen_recently` 已经把它记成"见过"。
    """
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t18")
    workflow = _workflow(client, ws, graph=_graph("asset_id"))
    trigger = _trigger(
        client, ws, workflow["id"], message_types=["file"], params={"asset_id": "{{trigger.asset_id}}"}
    )
    sent = _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)
    #: **不 patch import_binary_asset** —— 让素材库自己判"这不是能收的东西"。
    monkeypatch.setattr(feishu_client, "download_message_resource", lambda *a, **k: _zip_bytes())

    _incoming(
        bot["id"], "oc_g", _unique("zip"), open_id, message_type="file",
        content_json=json.dumps({"file_key": "fk_zip", "file_name": "素材.zip"}),
    )

    assert len(sent) == 1, f"收不进来必须说一句,不能静默:{sent}"
    assert "没能取回来" in sent[0][1]
    assert _runs(client, workflow["id"]) == [], "素材没入库,这一次不该硬跑"
    assert _events(client, trigger["id"]) == [], "附件没到,这条消息不算被认领过"


def _refusing_engine(monkeypatch) -> None:
    """让 `start_workflow_job` 在 `check_runnable` 过了之后抛 —— ADR 0047「这一版要你认可」那一路。"""
    from app.domain.workflows import WorkflowDomainError, engine

    def refuse(*args, **kwargs):
        raise WorkflowDomainError("wfErr_spendNotVouched", params={"workflow": "被触发的流", "revision": 3})

    monkeypatch.setattr(engine, "start_workflow_job", refuse)


def test_起跑失败不在群里喊这次运行失败了(monkeypatch) -> None:
    """[high] `check_runnable` 过了、`start_workflow_job` 却抛:事件记 `failed`,可任务 payload 里
    `trigger_id` / `trigger_event_id` 那两格还在,收尾钩子(`jobs.register_settle_listener` →
    `deliver_trigger_run`)照样把「这次运行失败了」发进群 —— 而那两格本来就是"这次没有运行"的信号。
    ADR 0065 §5:配置错误不喊给一整群人;有回执 = 跑起来了。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t19")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    sent = _sent_texts(monkeypatch)
    _refusing_engine(monkeypatch)

    _incoming(bot["id"], "oc_g", _unique("vouch"), open_id, content_json=json.dumps({"text": "群里来一条"}))

    assert [one["status"] for one in _events(client, trigger["id"])] == ["failed"]
    assert sent == [], f"起跑就失败 = 没有这次运行,群里不该喊(ADR 0065 §5):{sent}"
    notices = client.get(f"/api/notifications?workspace_id={ws}").json()["items"]
    assert any("群里的视频" in one["title"] for one in notices), "主人该在站内收到"


def test_起跑失败的通知每分钟最多一条(monkeypatch) -> None:
    """[medium] `_refuse` 是"写坏事件**之前**判 `_notified_recently`"的,失败那条路漏了这一判 ——
    一个配错的触发器被群里连丢十条,主人收到十条通知(通知本身就是另一种风暴)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t23")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    _sent_texts(monkeypatch)
    _refusing_engine(monkeypatch)

    for index in range(2):
        _incoming(
            bot["id"], "oc_g", _unique(f"vouch{index}"), open_id,
            content_json=json.dumps({"text": f"第 {index} 条"}),
        )

    assert [one["status"] for one in _events(client, trigger["id"])] == ["failed", "failed"]
    notices = client.get(f"/api/notifications?workspace_id={ws}").json()["items"]
    failures = [one for one in notices if "群里的视频" in one["title"]]
    assert len(failures) == 1, f"每分钟最多喊一次主人,实际 {len(failures)} 条"


def test_重投的消息不再重复入库(monkeypatch) -> None:
    """[medium] 附件入库发生在去重**之前**:飞书重投时运行被 `(trigger_id, message_id)` 挡住,
    素材却照样多一份(`import_binary_asset` 自己 commit,回滚也带不走)。"""
    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t20")
    workflow = _workflow(client, ws, graph=_graph("asset_id"))
    trigger = _trigger(
        client, ws, workflow["id"], message_types=["media"], params={"asset_id": "{{trigger.asset_id}}"}
    )
    _sent_texts(monkeypatch)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)
    monkeypatch.setattr(feishu_client, "download_message_resource", lambda *a, **k: b"fake-mp4-bytes")

    imported: list[str] = []

    class _Asset:
        def __init__(self, index: int) -> None:
            self.id = f"asset-{index}"

    def fake_import(*args, **kwargs):
        imported.append("imported")
        return _Asset(len(imported))

    monkeypatch.setattr("app.domain.assets.importer.import_binary_asset", fake_import)

    message_id = _unique("dup-media")
    payload = json.dumps({"file_key": "fk_v", "file_name": "clip.mp4"})
    _incoming(bot["id"], "oc_g", message_id, open_id, message_type="media", content_json=payload)
    #: 模拟一次重启:进程内那份去重清掉,库里那行(真正的判据)还在。
    with inbound._seen_lock:
        inbound._seen.clear()
    _incoming(bot["id"], "oc_g", message_id, open_id, message_type="media", content_json=payload)

    assert len(imported) == 1, f"同一条消息只该入库一次,实际 {len(imported)} 次"
    assert len(_runs(client, workflow["id"])) == 1
    assert [one["status"] for one in _events(client, trigger["id"])] == ["started"]


def test_被限流的消息回落到智能体会话(monkeypatch) -> None:
    """[medium] ADR 0065 §3:筛选不命中(**限流了**)时"一切如常,会话链路一个字节都没变"。
    被限流的那条照旧喂给智能体,面板上那一行 `throttled` 照旧留痕。"""
    client = fresh_client()
    from tests.test_feishu import _configured

    _configured(client)
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t21")
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={}, max_runs_per_minute=1)
    sent = _sent_texts(monkeypatch)
    agent_ran: list[object] = []

    def fake_turn(*args, **kwargs):
        agent_ran.append(args)
        return TurnResult(text="智能体接住了")

    monkeypatch.setattr(host, "run_turn", fake_turn)

    _incoming(bot["id"], "oc_g", _unique("ok"), open_id, content_json=json.dumps({"text": "第一条"}))
    _incoming(bot["id"], "oc_g", _unique("over"), open_id, content_json=json.dumps({"text": "第二条"}))
    assert host.wait_for_idle_turns(_RUN_BUDGET)

    assert len(_runs(client, workflow["id"])) == 1, "限流的那条不该起运行"
    assert sorted(one["status"] for one in _events(client, trigger["id"])) == ["started", "throttled"]
    assert agent_ran, "被限流的消息该回落到智能体会话,而不是两个去处都不去"
    assert "智能体接住了" in "\n".join(text for _, text in sent)


def test_认领的都限流_落选的不算数(monkeypatch) -> None:
    """[medium] 跟上面那条同一件事的边界:五条触发器都认同一句话时,前三条认领、后两条 `skipped`
    —— 前三条全被限流,这条消息仍然该回落到智能体会话(**落选的不是"它起过运行"**)。
    """
    client = fresh_client()
    from tests.test_feishu import _configured

    _configured(client)
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t24")
    workflow = _workflow(client, ws)
    triggers = [
        _trigger(client, ws, workflow["id"], name=f"t{index}", params={}, max_runs_per_minute=1)
        for index in range(5)
    ]
    _sent_texts(monkeypatch)
    agent_ran: list[object] = []

    monkeypatch.setattr(host, "run_turn", lambda *a, **k: agent_ran.append(a) or TurnResult(text="接住了"))

    _incoming(bot["id"], "oc_g", _unique("many1"), open_id, content_json=json.dumps({"text": "第一条"}))
    _incoming(bot["id"], "oc_g", _unique("many2"), open_id, content_json=json.dumps({"text": "第二条"}))
    assert host.wait_for_idle_turns(_RUN_BUDGET)

    statuses = sorted(one["status"] for trigger in triggers for one in _events(client, trigger["id"]))
    #: 第一条:三条起跑、两条落选;第二条:三条限流、两条落选。
    assert statuses == ["skipped", "skipped", "skipped", "skipped", "started", "started", "started", "throttled", "throttled", "throttled"], statuses
    assert len(_runs(client, workflow["id"])) == 3, "限流的那三条不该起运行"
    assert agent_ran, "认领的三条全被限流时,这条消息该回落到智能体会话"


def _receipts_survive_a_failing_send(monkeypatch, failure: BaseException) -> None:
    """两条触发器各回一次执,而第一条发送以 `failure` 失败 —— 第二条照样要发出去。"""
    from app.integrations.feishu import connections

    #: 这条用例只关心回执怎么发,不起真的长连接子进程:它是另一个进程,退出时要写机器人状态,
    #: 而这条用例里第二遍 fresh_client() 会把库重建掉 —— 于是那条泵线程撞上
    #: 「no such table: feishu_bots」(正是 connections.stop_connection 注释里记着的那件事)。
    monkeypatch.setattr(connections, "start_or_report", lambda bot_id: None)

    client = fresh_client()
    ws = _workspace(client)
    bot, open_id = _bound_bot(client, ws, app_id="cli_t22")
    workflow = _workflow(client, ws)
    for index in range(2):
        _trigger(client, ws, workflow["id"], name=f"t{index}", params={})

    attempts: list[str] = []
    delivered: list[str] = []
    first_receipt = {"raised": False}

    def flaky(bot, chat_id, text):
        attempts.append(text)
        if "已按触发器" in text and not first_receipt["raised"]:
            first_receipt["raised"] = True
            raise failure
        delivered.append(text)
        return "om_x"

    monkeypatch.setattr(feishu_client, "send_text", flaky)
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: None)

    _incoming(bot["id"], "oc_g", _unique("m2"), open_id, content_json=json.dumps({"text": "起两条"}))

    name = type(failure).__name__
    receipts = [text for text in attempts if "已按触发器" in text]
    assert len(receipts) == 2, f"{name}:两条触发器各该回一次执:{attempts}"
    assert receipts[1] in delivered, f"{name}:第一条抛了,第二条照样要发:{delivered}"


def test_一条回执发不出去不影响后面几条(monkeypatch) -> None:
    """[low] 机器人被移出群 / 网络抖动:第一条回执抛,不该把后面那条(**其实已经起跑了**的运行
    的回执)一起丢掉,更不该让线程带着未处理异常结束。

    两种抛法都试:飞书自己回的 `FeishuError`,和网络抖动(`RetryingClient` 把连接断开 / 超时 / DNS
    按 `httpx.RequestError` 抛出来,见 core/http_retry —— 那条路不是 FeishuError)。
    """
    import httpx

    _receipts_survive_a_failing_send(
        monkeypatch, feishu_client.FeishuError("feishuErr_sendText", detail="bot was removed from the chat")
    )
    _receipts_survive_a_failing_send(monkeypatch, httpx.ConnectError("connection reset"))


def test_图已删的触发器不能再打开(monkeypatch) -> None:
    """[low] `update` 只在给了 `workflow_id` 时校验图在不在:`{"enabled": true}` 对"图已删"的
    触发器返回 200,直到下一条消息才 refused + 自停 —— 用户在面板上看着它是开着的。"""
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    trigger = _trigger(client, ws, workflow["id"], params={})
    assert client.delete(f"/api/workflows/{workflow['id']}").status_code == 204

    res = client.patch(f"/api/workflow-triggers/{trigger['id']}", json={"enabled": True})
    assert res.status_code == 422, f"图没了就该当场说,而不是等下一条消息:{res.text}"
    #: 422 只挡"打开一条注定跑不起来的自动化":关掉它、改别的字段照旧。
    assert client.patch(f"/api/workflow-triggers/{trigger['id']}", json={"enabled": False}).status_code == 200
    assert client.patch(f"/api/workflow-triggers/{trigger['id']}", json={"name": "改个名"}).status_code == 200


def test_同一刻创建的触发器按_id_排队(monkeypatch) -> None:
    """[low] `created_at` 撞在同一刻时,顺序要有 tiebreaker —— 不然"先配的先跑"由数据库的
    返回顺序说了算,而"前三条认领、后两条落选"的名额也跟着随机。"""
    client = fresh_client()
    ws = _workspace(client)
    workflow = _workflow(client, ws)
    stamp = datetime(2026, 1, 1, 12, 0, 0)
    #: 插入顺序与 id 顺序**相反**:只看 created_at 时拿到的就是插入顺序。
    with SessionLocal() as db:
        for name in ("t-e", "t-d", "t-c", "t-b", "t-a"):
            db.add(
                WorkflowTrigger(
                    id=name, workspace_id=ws, workflow_id=workflow["id"], name=name,
                    message_types=["text"], created_at=stamp,
                )
            )
        db.commit()

    message = matching.IncomingMessage(
        workspace_id=ws, bot_id="b", chat_id="c", message_id="m-tie",
        sender_open_id="ou_1", message_type="text", text="来一条",
    )
    with SessionLocal() as db:
        claimed, skipped = dispatch.claimable(db, message)

    assert claimed == ["t-a", "t-b", "t-c"], f"同一刻创建时按 id 兜底:{claimed}"
    assert skipped == ["t-d", "t-e"]


def test_seen_recently_不看墙上时钟(monkeypatch) -> None:
    """[low] 过期判据换成单调钟:系统时间往前跳一格(校时、夏令时),不该把"刚见过的消息"
    整批放走 —— 那正是飞书重投被当成新消息、再付费跑一次的那一刻。"""
    message_id = _unique("clock")
    assert inbound.seen_recently(message_id) is False

    real_time = time.time
    monotonic_clock = time.monotonic

    class _JumpedClock:
        """只换掉 `inbound` 眼里的那只钟:别处照常用真时间。"""

        @staticmethod
        def time() -> float:
            return real_time() + 3600

        @staticmethod
        def monotonic() -> float:
            return monotonic_clock()

    monkeypatch.setattr(inbound, "time", _JumpedClock)

    assert inbound.seen_recently(message_id) is True


def test_历史上已认领的消息本次只剩限流也不再回落智能体() -> None:
    """T1 以前已经 started,这次重投只剩 T2 被限流:不能再跑一轮智能体(ADR 0065 §3)。"""
    outcome = dispatch.Outcome(trigger_id="t2", trigger_name="T2", status=dispatch.STATUS_THROTTLED)
    assert inbound._left_for_the_agent([outcome], ["t2"], {"t1": dispatch.STATUS_STARTED}) is False

    # 历史上也只是 throttled(从没跑起来)时,仍然允许回落。
    assert inbound._left_for_the_agent([outcome], ["t2"], {"t1": dispatch.STATUS_THROTTLED}) is True

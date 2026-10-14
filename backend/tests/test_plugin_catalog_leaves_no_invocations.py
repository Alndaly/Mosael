"""宿主问目录不留调用记录,调用记录的列表一定有上限 —— 插件页那次反复崩溃的两半。

## 现场

维护者打开插件页(尤其 ComfyUI 那个连接),过一会儿整个界面崩掉、反复崩;删掉连接重建就好了。渲染进程是硬崩
(V8 那一片的 CHECK),崩之前主线程卡了半分钟,而崩之前它要的最后一份东西是
`GET /api/plugins/invocations?instance_id=…`。

那个连接有 1272 条调用记录、输出合计 710MB:其中 1019 条是 `{"op": "tools"}` / `{"op": "models"}` —— 宿主每刷一次
目录就问插件一次,每次都留了一行,每行的输出就是整份清单(一份 ComfyUI 工具清单约 1MB)。`invoke_host` 当年缺省
留记录、靠调用处记得写 `record=False`,这两处漏了。列表接口又不分页,插件页只摆十条却拿回全部 —— 七百多 MB 的
JSON,渲染进程解不动。删连接时记录跟着级联删掉,所以重建之后就不崩了(直到再攒满)。

## 钉的是什么

- `record` 没有缺省:每个调用处都得明说,再漏一处就是 TypeError,不是又一个慢慢攒满的连接;
- 刷目录(工具清单 + 模型清单)一行调用记录都不留;
- 列表接口缺省只回最新十条,最多一百条;
- 迁移把存量的目录记录清掉,别的记录一条不动,再跑一次什么都不变。
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.db.migrations import _drop_plugin_catalog_invocations as migrate
from app.db.models import PluginInvocation
from app.domain.plugins import tools
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"


def _connect(client, url: str) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def _count(instance_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PluginInvocation).where(PluginInvocation.instance_id == instance_id))


def _seed(instance_id: str, inputs: list[dict]) -> None:
    """按给的顺序写进去,越往后越新。"""
    start = datetime(2026, 10, 1, 12, 0, 0)
    with SessionLocal() as db:
        for index, payload in enumerate(inputs):
            db.add(PluginInvocation(instance_id=instance_id, tool_name="comfyui_generation", status="succeeded",
                                    input=payload, output={"n": index}, created_at=start + timedelta(seconds=index)))
        db.commit()


def test_record_没有缺省_每个调用处都得明说() -> None:
    assert inspect.signature(tools.invoke_host).parameters["record"].default is inspect.Parameter.empty


def test_刷目录不留调用记录() -> None:
    client = fresh_client()
    with FakeComfyUI() as comfy:
        instance_id = _connect(client, comfy.url)
        for _ in range(3):
            refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
            assert refreshed.status_code == 200, refreshed.text
        caps = refreshed.json()["capability_status"]
        assert caps["tools"]["error"] == "" and caps["generation"]["error"] == "", "目录要真的刷出来,这条才有意义"
    assert _count(instance_id) == 0
    assert client.get(f"/api/plugins/invocations?instance_id={instance_id}").json() == []


def test_列表缺省只回最新十条_最多一百条() -> None:
    client = fresh_client()
    with FakeComfyUI() as comfy:
        instance_id = _connect(client, comfy.url)
    _seed(instance_id, [{"op": "generate", "prompt": str(index)} for index in range(15)])

    listed = client.get(f"/api/plugins/invocations?instance_id={instance_id}").json()
    assert [row["output"]["n"] for row in listed] == list(range(14, 4, -1)), "最新的十条,新的在前"
    assert len(client.get(f"/api/plugins/invocations?instance_id={instance_id}&limit=100").json()) == 15
    assert client.get(f"/api/plugins/invocations?instance_id={instance_id}&limit=101").status_code == 422


def test_迁移清掉存量的目录记录_别的不动_再跑一次不变() -> None:
    client = fresh_client()
    with FakeComfyUI() as comfy:
        instance_id = _connect(client, comfy.url)
    catalog = [{"op": "tools"}, {"op": "models"}, {"op": "explain", "ids": ["a"]}, {"op": "explain", "tools": ["wf_x"]},
               {"op": "resolve", "url": "https://example.com/m.safetensors"},
               {"op": "search_sources", "filename": "m.safetensors", "folder": "checkpoints"}]
    kept = [{"op": "generate", "model": "builtin:txt2img", "prompt": "猫"}, {"op": "upgrade_marks", "paths": []},
            {"text": "一个用户在插件页试跑的工具,入参里没有 op"}]
    _seed(instance_id, catalog * 3 + kept)

    migrate()
    with SessionLocal() as db:
        left = [row.input for row in db.scalars(select(PluginInvocation).where(PluginInvocation.instance_id == instance_id))]
    assert sorted(json.dumps(one, sort_keys=True) for one in left) == sorted(json.dumps(one, sort_keys=True) for one in kept)

    migrate()
    assert _count(instance_id) == len(kept)

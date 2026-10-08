"""同一个插件节点在几条连接上入参不一样时,节点注册表怎么合(PLG-14)。

节点按包聚合(ADR 0045 §4):同一个包的几条连接提供同一批节点,用哪条是节点配置里的一格。ComfyUI 的工具名取自工作流的
图 id —— 同一个文件拷到两台 ComfyUI 上、各自改过,工具名一样、入参不一样。此前注册表只留第一条连接的那份:绑在第二条上的
节点,表单里是第一条的那几格(插件丢掉认不得的键,填了不生效),它自己多出来的那几格根本填不了。

现在表单取并集,只在部分连接上有的那几格带 `active_when: {instance_id: [那几条]}` —— 节点选了那几条之一才出现、才参与校验
(和别的条件字段同一条规矩,前后端都认)。
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.workflows.field_activation import config_field_active
from tests.fake_comfyui import PORTRAIT_ID, PORTRAIT_UI, FakeComfyUI, comfyui_grants, conn, widget
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"
TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]


def _without_reference_with_lora() -> dict[str, Any]:
    """另一台上的 portrait.json(同一个图 id):参考图那一路(LoadImage → IP-Adapter)删了,模型改经一个 LoRA。"""
    ui = copy.deepcopy(PORTRAIT_UI)
    ui["nodes"] = [one for one in ui["nodes"] if one["id"] not in (10, 12)]
    ui["nodes"].append({"id": 13, "type": "LoraLoader", "widgets_values": ["detail.safetensors", 0.8, 1.0],
                        "inputs": [conn("model", 10), conn("clip", 11), widget("lora_name"), widget("strength_model"),
                                   widget("strength_clip")]})
    links = [link for link in ui["links"] if link[0] not in (1, 10, 11)]
    ui["links"] = [*links, [1, 13, 0, 3, 0, "MODEL"], [10, 4, 0, 13, 0, "MODEL"], [11, 4, 1, 13, 1, "CLIP"]]
    return ui


def _connect(client, comfy: FakeComfyUI, name: str) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"name": name, "config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def test_两条连接上同一张工作流入参不一样_表单取并集_只有一条上有的那几格只在选了那条时出现() -> None:
    with FakeComfyUI() as studio, FakeComfyUI() as laptop:
        laptop.state.workflows["portrait.json"] = _without_reference_with_lora()
        client = fresh_client()
        first = _connect(client, studio, "工作室")
        second = _connect(client, laptop, "笔记本")
        node_types = {one["type"]: one for one in client.get("/api/workflows/node-types").json()}

    config = node_types[f"plugin.{PACKAGE}.{TOOL}"]["config"]
    only_second = [key for key, spec in config.items() if (spec.get("active_when") or {}).get("instance_id") == [second]]
    only_first = [key for key, spec in config.items() if (spec.get("active_when") or {}).get("instance_id") == [first]]
    assert only_second == ["lora_name_13", "strength_model_13", "strength_clip_13"], "笔记本上那张多出来的 LoRA 几格:此前根本填不了"
    assert only_first == ["image_10"], "工作室那张的参考图那一格:绑在笔记本上时不出现(此前照样摆着,填了不生效)"
    assert "active_when" not in config["steps_3"], "两边都有的照常出现"
    assert "active_when" not in config["instance_id"]

    lora = config["lora_name_13"]
    assert config_field_active(lora, {"instance_id": second}, config)
    assert not config_field_active(lora, {"instance_id": first}, config), "绑在工作室那条上:笔记本才有的那一格不参与表单和校验"
    assert not config_field_active(config["image_10"], {"instance_id": second}, config)
    assert config_field_active(config["steps_3"], {"instance_id": second}, config)

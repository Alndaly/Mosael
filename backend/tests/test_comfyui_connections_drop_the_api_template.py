"""`migrate-comfyui-connections-drop-the-api-template`:ComfyUI 插件 1.17.0 撤掉了连接上的「API 模板」(`api_workflow`)。

导出的 API 格式 JSON 直接导进工作流库就会转成界面格式,这一格没用了、清单里删了。存着的连接上这个键再留着,就是一个
没人读、也没人能改的变量,照旧被注入插件进程 —— 迁移把它摘掉;粘过内容的连接记一句日志(删了就没了);别的配置不动;
再跑一次什么都不改。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_comfyui_connections_drop_the_api_template as migrate
from app.db.models import PluginInstance
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"


def _connection(client, url: str, stored: dict) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    #: 升级前存下的样子:清单里还有这一格时,配置里就有它
    with engine.begin() as conn:
        conn.execute(text("UPDATE plugin_instances SET config = :c WHERE id = :i"),
                     {"c": json.dumps(stored, ensure_ascii=False), "i": instance_id})
    return instance_id


def test_连接配置里的API模板摘掉_粘过内容的记一句_再跑不动(caplog) -> None:
    client = fresh_client()
    empty = _connection(client, "http://127.0.0.1:8188", {"server_url": "http://127.0.0.1:8188", "api_workflow": ""})
    pasted = _connection(client, "http://127.0.0.1:8189",
                         {"server_url": "http://127.0.0.1:8189", "api_workflow": '{"1": {"class_type": "SaveImage"}}'})
    clean = _connection(client, "http://127.0.0.1:8190", {"server_url": "http://127.0.0.1:8190"})

    with caplog.at_level(logging.WARNING, logger="app.db.migrations"):
        migrate()
    migrate()

    with SessionLocal() as db:
        configs = {one.id: one.config for one in db.query(PluginInstance).filter_by(package_id=PACKAGE)}
        names = {one.id: one.name for one in db.query(PluginInstance).filter_by(package_id=PACKAGE)}
    assert configs[empty] == {"server_url": "http://127.0.0.1:8188"}
    assert configs[pasted] == {"server_url": "http://127.0.0.1:8189"}
    assert configs[clean] == {"server_url": "http://127.0.0.1:8190"}, "没有这一格的不动"
    warned = [record.getMessage() for record in caplog.records if "API 模板" in record.getMessage()]
    assert len(warned) == 1 and names[pasted] in warned[0] and names[empty] not in warned[0], "只有粘过内容的才说"

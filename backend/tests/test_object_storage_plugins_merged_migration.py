"""`merge-object-storage-plugins`:四个对象存储插件合成随应用内置的「对象存储」,老连接原地搬过去。

喂它一份合并之前的样子 —— 插件目录里装着老的阿里云 OSS 包(按 id 命名的文件夹)和老的 S3 包(手动放进来、
文件夹随便起名),各有一个连接:凭据(落盘是密文)、授过的网络权限、工具开关(有一个被用户关掉)、调用记录、
「设置 → 素材外链」选的默认、一条还没过期的直链缓存、会话里「本会话始终允许」的工具名、工作流(连循环体)
和画板上的工具格 —— 看它全部搬到新包上、别的插件一样不碰、老包的文件夹和记录都不在了,再跑一次什么都不动。
"""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.db.migrations import _merge_object_storage_plugins as migrate
from app.db.migrations import _migrate_workflow_revisions
from app.db.models import (
    AgentSession,
    Board,
    PluginCapability,
    PluginCapabilityDefault,
    PluginCredential,
    PluginInstance,
    PluginInvocation,
    PluginPackage,
    PluginPermissionGrant,
    PluginPublicLink,
    Workflow,
    WorkflowRevision,
    WorkflowRevisionAttestation,
    now,
)
from app.domain.workflows.revisions import current_workflow_revision
from tests.util import fresh_client, make_video_asset, second_client, user_id

NEW = "dev.mosael.object-storage"
OSS, S3 = "dev.mosael.aliyun-oss", "dev.mosael.aws-s3"


def _old_package(package_id: str, folder: str, prefix: str, tool_prefix: str) -> PluginPackage:
    """一个装在插件目录里的老包:文件夹 + 清单 + 包记录(清单里记着它在哪儿,和扫描时一样)。"""
    directory = settings.plugins_dir / folder
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": package_id, "manifest_version": 1, "name": package_id, "version": "0.1.3", "provides": ["public_url"],
        "runtime": {"kind": "process", "entry": "tools/main.py"}, "permissions": [f"network:{tool_prefix}"],
        "instance": {"multiple": True, "config": [{"key": f"{prefix}_BUCKET", "label": "桶"}]},
        "tools": {"expose": "all", "declare": [{"name": f"{tool_prefix}_upload", "provides": ["public_url"]},
                                               {"name": f"{tool_prefix}_list", "read_only": True}]},
    }
    (directory / "mosael.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (settings.data_dir / "plugin-data" / package_id).mkdir(parents=True, exist_ok=True)
    return PluginPackage(id=package_id, name=package_id, version="0.1.3", manifest={**manifest, "_path": str(directory)})


def _legacy(client) -> dict:
    me, mate = user_id("tester"), user_id("mate")
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = make_video_asset(client, workspace)["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "WF"}).json()["id"]
    # 别的插件:文件夹和记录都不能被碰
    other = settings.plugins_dir / "text-toolkit"
    other.mkdir(parents=True, exist_ok=True)
    (other / "mosael.plugin.json").write_text(json.dumps({"id": "dev.mosael.text-toolkit"}), encoding="utf-8")
    with SessionLocal() as db:
        db.add_all([_old_package(OSS, OSS, "OSS", "oss"), _old_package(S3, "my-s3", "S3", "s3")])
        db.flush()
        oss = PluginInstance(owner_user_id=me, package_id=OSS, name="阿里云 OSS · mosael", enabled=True,
                             config={"OSS_BUCKET": "mosael", "OSS_REGION": "", "OSS_ENDPOINT": ""})
        minio = PluginInstance(owner_user_id=me, package_id=S3, name="我的 MinIO", enabled=True,
                               config={"S3_BUCKET": "clips", "S3_REGION": "us-east-1", "S3_ENDPOINT": "minio.lan:9000"})
        db.add_all([oss, minio])
        db.flush()
        db.add_all([
            PluginCredential(instance_id=oss.id, key="OSS_ACCESS_KEY_ID", value="LTAI-fake"),
            PluginCredential(instance_id=oss.id, key="OSS_ACCESS_KEY_SECRET", value="fake-secret"),
            PluginCredential(instance_id=minio.id, key="S3_ACCESS_KEY_ID", value="minio-ak"),
            PluginCredential(instance_id=minio.id, key="S3_SECRET_ACCESS_KEY", value="minio-sk"),
            PluginPermissionGrant(instance_id=oss.id, permission="network:oss", granted=True),
            PluginPermissionGrant(instance_id=minio.id, permission="network:s3", granted=False),
            PluginCapability(instance_id=oss.id, tool_name="oss_upload", exposed=True),
            PluginCapability(instance_id=oss.id, tool_name="oss_list", exposed=False),
            PluginInvocation(instance_id=oss.id, tool_name="oss_upload", status="succeeded", input={}, output={}),
            PluginCapabilityDefault(owner_user_id=me, capability="public_url", instance_id=oss.id),
            PluginPublicLink(asset_id=asset, instance_id=oss.id, url="https://mosael.oss/x?sig",
                             expires_at=now() + timedelta(hours=5)),
            AgentSession(workspace_id=workspace, owner_user_id=me,
                         auto_allow_tools=[f"plugin__{oss.id}__oss_upload", "publish_asset"]),
        ])
        board = db.get(Board, board_id)
        board.canvas = {"items": [
            {"id": "t1", "kind": "text", "x": 0, "y": 0,
             "form": {"producer": f"node:plugin.{OSS}.oss_upload", "config": {"instance_id": oss.id},
                      "bindings": {"asset_id": ["v1"]}}},
            {"id": "t2", "kind": "text", "x": 0, "y": 0, "form": {"producer": "node:plugin.dev.mosael.baidu-pan.pan_list"}},
        ]}
        db.commit()
        ids = {"oss": oss.id, "minio": minio.id, "asset": asset, "board": board_id, "workflow": workflow_id,
               "board_revision": board.revision, "workspace": workspace}
    graph = {"nodes": [
        {"id": "up", "type": f"plugin.{OSS}.oss_upload", "position": {"x": 0, "y": 0},
         "config": {"instance_id": ids["oss"], "asset_id": "{{src.asset_id}}"}},
        {"id": "loop", "type": "loop", "position": {"x": 0, "y": 0}, "config": {"body": {"nodes": [
            {"id": "ls", "type": f"plugin.{S3}.s3_list", "position": {"x": 0, "y": 0}, "config": {"prefix": "a/"}},
        ], "edges": []}}},
        {"id": "note", "type": "text_transform", "position": {"x": 0, "y": 0}, "config": {"text": "{{up.url}}"}},
    ], "edges": [{"source": "up", "target": "note", "kind": "data", "source_output": "url"}]}
    with engine.begin() as conn:
        conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                     {"g": json.dumps(graph, ensure_ascii=False), "id": workflow_id})
    _migrate_workflow_revisions()
    with SessionLocal() as db:
        latest = current_workflow_revision(db, db.get(Workflow, workflow_id))
        latest.created_by = me
        db.add(WorkflowRevisionAttestation(revision_id=latest.id, user_id=mate))
        db.commit()
        ids["revisions"] = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()
    return ids


def test_老连接原地搬进对象存储_引用跟着改_老包不见了_再跑一次什么都不动() -> None:
    client = fresh_client()
    second_client("mate")
    ids = _legacy(client)

    migrate()

    me = user_id("tester")
    with SessionLocal() as db:
        oss, minio = db.get(PluginInstance, ids["oss"]), db.get(PluginInstance, ids["minio"])
        # 连接:id 不变,改挂新包;配置换成新键、写上服务商;空着的地域按老插件的默认补上
        assert (oss.package_id, minio.package_id) == (NEW, NEW)
        assert oss.config == {"STORAGE_PROVIDER": "aliyun-oss", "STORAGE_BUCKET": "mosael",
                              "STORAGE_REGION": "cn-hangzhou", "STORAGE_ENDPOINT": ""}
        assert minio.config["STORAGE_PROVIDER"] == "s3-compatible", "填了非 AWS 接入点的老 S3 连接是 S3 兼容服务"
        assert minio.config["STORAGE_ENDPOINT"] == "minio.lan:9000"
        # 名字:老模板生成的照旧(新模板生成的是同一个),用户改过的不动
        assert (oss.name, minio.name) == ("阿里云 OSS · mosael", "我的 MinIO")
        # 凭据:只改键名,密文原样 —— 读出来还是那一把
        creds = {(row.instance_id, row.key): row.value for row in db.scalars(select(PluginCredential))}
        assert creds[(ids["oss"], "STORAGE_ACCESS_KEY_ID")] == "LTAI-fake"
        assert creds[(ids["oss"], "STORAGE_ACCESS_KEY_SECRET")] == "fake-secret"
        assert creds[(ids["minio"], "STORAGE_ACCESS_KEY_SECRET")] == "minio-sk"
        assert not [key for _, key in creds if not key.startswith("STORAGE_")]
        # 授权:授过的照旧授过,没授的照旧没授
        grants = {(row.instance_id, row.permission): row.granted for row in db.scalars(select(PluginPermissionGrant))}
        assert grants[(ids["oss"], "network:object-storage")] is True
        assert grants[(ids["minio"], "network:object-storage")] is False
        assert not [p for _, p in grants if p in ("network:oss", "network:s3")]
        # 工具开关:用户关掉的还是关着,新工具补上
        exposed = {row.tool_name: row.exposed for row in db.scalars(
            select(PluginCapability).where(PluginCapability.instance_id == ids["oss"]))}
        assert exposed == {"storage_upload": True, "storage_list": False, "storage_presign": True,
                           "storage_fetch": True}
        assert [row.tool_name for row in db.scalars(select(PluginInvocation))] == ["storage_upload"]
        # 素材外链的默认、直链缓存:挂在连接 id 上,原样
        assert db.get(PluginCapabilityDefault, (me, "public_url")).instance_id == ids["oss"]
        assert db.get(PluginPublicLink, (ids["asset"], ids["oss"])) is not None
        session = db.scalars(select(AgentSession)).one()
        assert session.auto_allow_tools == [f"plugin__{ids['oss']}__storage_upload", "publish_asset"]

        # 画板:工具格的产出者改写,别的插件的格不动,revision 往前走
        board = db.get(Board, ids["board"])
        first, second = board.canvas["items"]
        assert first["form"]["producer"] == f"node:plugin.{NEW}.storage_upload"
        assert first["form"]["config"] == {"instance_id": ids["oss"]} and first["form"]["bindings"] == {"asset_id": ["v1"]}
        assert second["form"]["producer"] == "node:plugin.dev.mosael.baidu-pan.pan_list"
        assert board.revision == ids["board_revision"] + 1

        # 工作流:连循环体一起改;数据边和 {{up.url}} 不用动;追加一版修订,作者与认可人沿用上一版
        workflow = db.get(Workflow, ids["workflow"])
        up, loop, note = workflow.graph["nodes"]
        assert up["type"] == f"plugin.{NEW}.storage_upload" and up["config"]["instance_id"] == ids["oss"]
        assert loop["config"]["body"]["nodes"][0]["type"] == f"plugin.{NEW}.storage_list"
        assert note["config"] == {"text": "{{up.url}}"} and workflow.graph["edges"][0]["source_output"] == "url"
        latest = current_workflow_revision(db, workflow)
        assert latest.graph == workflow.graph and latest.source == "migration" and latest.created_by == me
        attesters = {row.user_id for row in db.scalars(select(WorkflowRevisionAttestation).where(
            WorkflowRevisionAttestation.revision_id == latest.id))}
        assert attesters == {user_id("mate")}

        # 老包:记录、文件夹、持久目录都不在了;别的插件的文件夹还在
        assert db.get(PluginPackage, OSS) is None and db.get(PluginPackage, S3) is None
        assert db.get(PluginPackage, NEW) is not None
    assert not (settings.plugins_dir / OSS).exists() and not (settings.plugins_dir / "my-s3").exists()
    assert not (settings.data_dir / "plugin-data" / OSS).exists()
    assert (settings.plugins_dir / "text-toolkit" / "mosael.plugin.json").is_file()

    # 搬过来的连接在新包上真的能用:素材外链的设置里认得它,配好了
    state = client.get("/api/settings/asset-link-storage").json()
    assert state["current"] == ids["oss"]
    assert {o["instance_id"]: o["missing"] for o in state["options"]}[ids["oss"]] == []

    migrate()
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids["workflow"]).count() == ids["revisions"] + 1
        assert db.get(Board, ids["board"]).revision == ids["board_revision"] + 1
        assert db.query(PluginCapability).filter_by(instance_id=ids["oss"]).count() == 4


def test_服务商变了的连接_名字按新模板重生成() -> None:
    """老 S3 连接连的是 R2:服务商变成「S3 兼容服务」,老名字「Amazon S3 · b」不再是新模板会生成的那个。
    照原样留着的话,以后改配置时名字就不再跟着走了(会被当成用户改过的名字)。「Amazon S3」中英文同形,
    按清单的默认语言(zh)生成。"""
    fresh_client()
    with SessionLocal() as db:
        db.add(_old_package(S3, S3, "S3", "s3"))
        db.flush()
        db.add(PluginInstance(owner_user_id=user_id("tester"), package_id=S3, name="Amazon S3 · b", enabled=True,
                              config={"S3_BUCKET": "b", "S3_REGION": "auto",
                                      "S3_ENDPOINT": "acct.r2.cloudflarestorage.com"}))
        db.commit()

    migrate()

    with SessionLocal() as db:
        instance = db.scalars(select(PluginInstance).where(PluginInstance.package_id == NEW)).one()
        assert instance.name == "S3 兼容服务 · b"
        assert instance.config["STORAGE_REGION"] == "auto"


def test_没有老对象存储的库什么都不动() -> None:
    fresh_client()
    with engine.begin() as conn:
        before = conn.execute(text("SELECT id FROM plugin_packages ORDER BY id")).scalars().all()
    migrate()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT id FROM plugin_packages ORDER BY id")).scalars().all() == before

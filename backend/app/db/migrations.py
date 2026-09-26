"""建表与历史数据迁移 —— **依赖序的顶端**,爱 import 谁 import 谁。

从 `app/core/db.py` 搬出来的。那里是被所有人 import 的底座,而迁移必须认识领域层
(声音克隆的共用 venv 往哪搬、插件表怎么拆成包/实例/能力),两者方向相反。挤在一个模块
里的那段时间,这些 import 只能写在函数体里把环推迟到运行时;搬出来之后写在文件顶上即可。

**新增迁移就写在这里,并挂进 `init_db()`** —— 顺序有讲究,函数各自的 docstring 说明了
自己必须排在 create_all 之前还是之后。仓库不用 alembic:每条迁移都先探 schema 再动手
(见各函数开头的 `inspect(engine)`),重复跑是安全的。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from app.core.config import LOGIN_SESSION_TTL, settings
from app.core.db import Base, PARTITION_PREFIX, engine, now
from app.core.tokens import TOKEN_SCHEME, token_digest
from app.db.migration_runner import MigrationPhase, MigrationPlan, MigrationStep
from app.db.safety import DATABASE_SCHEMA_VERSION, mark_database_version, snapshot_before_upgrade

logger = logging.getLogger(__name__)


def _migrate_tool_confirmations_session() -> None:
    """tool_confirmations 新增 session_id 列(确认卡归属于哪次智能体会话)。

    create_all 只建新表,不给**已有**表补列。这列可空:MCP / 飞书等外部智能体没有会话。
    老行留空 → 它们照旧由全局确认中心兜底,不会突然从某个对话里消失。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    if "session_id" in {c["name"] for c in inspector.get_columns("tool_confirmations")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN session_id VARCHAR(64)"))


def _migrate_workflow_revisions() -> None:
    """初始化旧工作流的修订历史，并保持当前投影与最新修订一致。

    新表由前一阶段的 ``create-current-schema`` 建好；这里仅补已有 workflows 表不会被
    ``create_all`` 添加的两列，并为每条老数据写首份快照。摘要算法在迁移内自包含，避免将来
    领域实现变化后重放历史迁移得到不同结果。

    启动迁移没有 alembic 的「只执行一次」账本，因此这里必须真正可重入。已有修订时，当前图
    若等于最新快照，只校正 ``workflows`` 的当前指针；若不等，则把当前图追加成恢复修订，绝不
    覆盖用户数据或旧快照。这个校正也会修复曾被旧版迁移错误重置为 v1 的工作流。
    """

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "workflows" not in tables or "workflow_revisions" not in tables:
        return
    # 完整摘要算法是历史迁移格式，留在本函数内；「哪些字段构成一个版本」则是当前领域规则，
    # 启动自愈必须和保存入口共用同一定义，否则一次纯布局保存会在下次启动时被误升成新版本。
    from app.domain.workflows.revisions import revision_digest

    columns = {column["name"] for column in inspector.get_columns("workflows")}
    with engine.begin() as conn:
        if "revision" not in columns:
            conn.execute(text("ALTER TABLE workflows ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"))
        if "graph_hash" not in columns:
            conn.execute(text("ALTER TABLE workflows ADD COLUMN graph_hash VARCHAR(64) NOT NULL DEFAULT ''"))

        rows = conn.execute(text("SELECT id, graph, revision, graph_hash, created_at FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                graph = {}
            canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            stored_graph = raw_graph if isinstance(raw_graph, str) else json.dumps(graph or {}, ensure_ascii=False)
            latest = conn.execute(
                text(
                    "SELECT revision, graph, graph_hash FROM workflow_revisions "
                    "WHERE workflow_id = :id ORDER BY revision DESC LIMIT 1"
                ),
                {"id": row["id"]},
            ).mappings().one_or_none()

            if latest is None:
                conn.execute(
                    text(
                        """
                        INSERT INTO workflow_revisions
                            (id, workflow_id, revision, graph, graph_hash, source, note, created_by, created_at)
                        VALUES
                            (:id, :workflow_id, 1, :graph, :graph_hash, 'migration', '', NULL, :created_at)
                        """
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "workflow_id": row["id"],
                        "graph": stored_graph,
                        "graph_hash": digest,
                        "created_at": row["created_at"] or datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                current_revision = 1
            else:
                latest_raw_graph = latest["graph"]
                try:
                    latest_graph = json.loads(latest_raw_graph) if isinstance(latest_raw_graph, str) else latest_raw_graph
                except (TypeError, ValueError):
                    latest_graph = {}
                latest_canonical = json.dumps(
                    latest_graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                latest_digest = hashlib.sha256(latest_canonical.encode("utf-8")).hexdigest()

                if latest["graph_hash"] == latest_digest and revision_digest(latest_graph) == revision_digest(graph):
                    # 正常重跑、纯布局保存和旧缺陷的自愈都走这里：图不动，只校正当前指针。
                    current_revision = int(latest["revision"])
                else:
                    # 当前投影没有对应的不可变快照。保住用户眼前的图，并把它提升为最新修订。
                    current_revision = int(latest["revision"]) + 1
                    conn.execute(
                        text(
                            """
                            INSERT INTO workflow_revisions
                                (id, workflow_id, revision, graph, graph_hash, source, note, created_by, created_at)
                            VALUES
                                (:id, :workflow_id, :revision, :graph, :graph_hash,
                                 'migration', 'recovered current projection', NULL, :created_at)
                            """
                        ),
                        {
                            "id": uuid.uuid4().hex,
                            "workflow_id": row["id"],
                            "revision": current_revision,
                            "graph": stored_graph,
                            "graph_hash": digest,
                            "created_at": datetime.now(UTC).replace(tzinfo=None),
                        },
                    )
                    logger.warning("工作流 %s 的当前图没有对应修订，已恢复为 v%d", row["id"], current_revision)

            if row["revision"] != current_revision or row["graph_hash"] != digest:
                conn.execute(
                    text("UPDATE workflows SET revision = :revision, graph_hash = :digest WHERE id = :id"),
                    {"revision": current_revision, "digest": digest, "id": row["id"]},
                )


def _migrate_official_workflow_data_bindings() -> None:
    """Turn exact output references in installed official workflows into native data edges.

    Official templates are editable copies, so regenerating them would erase user changes.  The
    canonicalizer changes only the one representation that is provably equivalent and leaves every
    other node, value and layout coordinate intact.  The following revision migration notices the
    semantic graph change and records it as a new immutable revision.
    """

    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.normalization import canonicalize_data_bindings

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict) or (graph.get("meta") or {}).get("source") != "official":
                continue
            normalized = canonicalize_data_bindings(graph, node_types=NODE_TYPES)
            if normalized == graph:
                continue
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(normalized, ensure_ascii=False), "id": row["id"]},
            )


def _migrate_node_names_are_not_i18n_keys() -> None:
    """把被当成人话写进图里的 `wfNode_*` 节点名清掉。

    `graph_ops.add_node` 此前在没给名字时回退到 `NODE_TYPES[type]["label"]` —— 而那一格存的是
    **i18n key**(目录里存 key、出口才翻)。于是智能体建的节点在画布上从此叫
    `wfNode_scene_render`,而且**随图落库**:这是写进用户数据的错,不只是显示错。

    清成空串就够了:没有名字时显示会回退到**翻译后**的 label,而那正是用户想看到的 ——
    所以这次迁移不是"补一个值",是"把一个不该存在的值拿掉"。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        cleared = 0
        for row in rows:
            raw = row["graph"]
            try:
                graph = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            touched = False
            for node in graph.get("nodes") or []:
                if isinstance(node, dict) and str(node.get("name") or "").startswith("wfNode_"):
                    node["name"] = ""
                    touched = True
            if not touched:
                continue
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(graph, ensure_ascii=False), "id": row["id"]},
            )
            cleared += 1
        if cleared:
            logger.info("清掉了 %d 个工作流里被写成 i18n key 的节点名", cleared)


def _migrate_called_workflows_declare_their_output() -> None:
    """被别的工作流 `call_workflow` 调用、却没有「输出」节点的图,补上一个输出节点。

    ## 为什么要迁移,而不是留一条兼容分支

    `call_workflow` 此前的返回是

        result.get("output") or result.get("context") or {}

    —— 被调图没有输出节点时,退回**整份上下文**。那份上下文是给人看的快照,过了 `_trim_outputs`
    (长字符串截断、列表只留 200 项、对象只留 100 个字段),于是一份长文案、一段 LLM 回答、
    一串 id 列表经这条退路传上去会**安静地少一截**。而「输出」节点的说明写着:被调用时调用方拿的
    就是这个契约 —— 一个契约不能有"契约给不出东西时换一种形状"的退路。

    这条退路是明写的向后兼容分支,而本仓库的规矩是**不写兼容,改形状带迁移**(ADR-0006)。
    所以退路删掉,老数据在这里补齐:给每个终端节点(没有出边的那些)的每一个输出声明一个名字,
    形如 `{节点id}_{输出名}: "{{节点id.输出名}}"`。**这正是老行为的显式版本** —— 暴露的还是
    那些值,只是从此有名有姓、而且不再被裁剪。

    只改 `workflows.graph`(当前图)。修订是不可变快照,不动它们:拿老修订跑的任务会拿到
    `wfErr_calledWorkflowHasNoOutput` 那句明确的话(「加一个输出节点」),而不是一份少了一截
    的数据 —— **说得出口的失败比悄悄错掉好**。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        graphs: dict[str, dict] = {}
        called: set[str] = set()
        for row in rows:
            raw = row["graph"]
            try:
                graph = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            graphs[row["id"]] = graph
            for node in graph.get("nodes") or []:
                if isinstance(node, dict) and node.get("type") == "call_workflow":
                    target = (node.get("config") or {}).get("workflow_id")
                    if isinstance(target, str) and target:
                        called.add(target)

        patched = 0
        for workflow_id in sorted(called):
            graph = graphs.get(workflow_id)
            if graph is None:
                continue
            nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
            if any(node.get("type") == "output" for node in nodes):
                continue
            sources = {
                str(edge.get("source"))
                for edge in (graph.get("edges") or [])
                if isinstance(edge, dict)
            }
            values: dict[str, str] = {}
            for node in nodes:
                nid = str(node.get("id") or "")
                if not nid or nid in sources:
                    continue  # 有出边的不是终端节点
                spec = NODE_TYPES.get(str(node.get("type")))
                for out in (spec or {}).get("outputs") or []:
                    if str(out).startswith("*"):
                        continue  # 运行时才知道名字的,声明不出来
                    values[f"{nid}_{out}"] = f"{{{{{nid}.{out}}}}}"
            if not values:
                continue
            graph["nodes"] = [*nodes, {
                "id": "output_migrated",
                "type": "output",
                "name": "输出",
                "config": {"values": values},
            }]
            graph["edges"] = [*(graph.get("edges") or []), *(
                {"source": nid, "target": "output_migrated"}
                for nid in sorted({key.rsplit("_", 1)[0] for key in values})
                if any(node.get("id") == nid for node in nodes)
            )]
            conn.execute(
                text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(graph, ensure_ascii=False), "id": workflow_id},
            )
            patched += 1
        if patched:
            logger.info("给 %d 个被调用的工作流补上了「输出」节点", patched)


def _migrate_resource_ownership() -> None:
    """五张表补 `owner_user_id`,并给每条已存在的记录建一行「共享给它当前所在的工作区」。

    **升级前后行为完全一致**:今天同工作区的人看得见的,升级之后仍然看得见;而**从此以后新建的
    默认私有**(见 domain/sharing.KINDS)。不这么做的话,升级会把同事的发布账号、浏览器档案、
    对话从他们眼前一次性拿走 —— 那不是收紧权限,那是弄坏了正在用的东西。

    归属回填成**该工作区的 owner**:老数据里没有记谁建的,而工作区的 owner 是现在对它们负责的人。

    ## 共享回填**只能跑一次**,不是「幂等」

    这两件事听起来像一回事,其实相反。共享是**用户随时在改的状态**:第一次跑到这里时「某条记录
    没有共享行」意味着它是拆分之前的老数据、要一次性迁过来;而从此以后,「没有共享行」意味着
    **主人把它收回了**。原先每次启动都补上缺的那些,于是:

      ・新建的账号本该默认私有(domain/sharing.KINDS 明写 False),下次启动就被改成了团队共享;
      ・在界面上点「收回」确实删掉了那一行,重启之后它又回来了 —— 表现为「收回无效」。

    两个症状同一个根因。判据取**这一轮是否真的新加了 `owner_user_id` 列**:加列的那一次就是这台
    机器第一次跑到归属拆分,老数据只在那一刻迁移。全新安装由 create_all 直接建出带列的表,永远
    不走这条路,所以新库里的默认私有是真的默认私有。

    归属回填(owner_user_id)则**照旧每次都跑**:它不是用户可改的状态,是派生值,而 owner 为空的
    记录连主人自己都看不见 —— 那种行该修就修,且修它不会把任何东西暴露给别人。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    kinds = {
        "publish_account": "publish_accounts",
        "browser_profile": "browser_profiles",
        "agent_session": "agent_sessions",
        "generation_session": "generation_sessions",
        "scheduled_task": "scheduled_tasks",
    }
    # 这一轮真正新加了列的表 —— 只有它们的老数据需要一次性迁移共享。
    upgraded: set[str] = set()
    for table in kinds.values():
        if table not in tables:
            continue
        if "owner_user_id" not in {c["name"] for c in inspector.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_user_id VARCHAR(64)"))
            upgraded.add(table)
    if "resource_shares" not in set(inspect(engine).get_table_names()):
        return  # create_all 还没跑到(首次装机),下次启动再补
    with engine.begin() as conn:
        for kind, table in kinds.items():
            if table not in tables:
                continue
            conn.execute(
                text(
                    f"UPDATE {table} SET owner_user_id = ("
                    "SELECT user_id FROM workspace_members "
                    f"WHERE workspace_members.workspace_id = {table}.workspace_id AND role = 'owner' "
                    "LIMIT 1) WHERE owner_user_id IS NULL"
                )
            )
            if table not in upgraded:
                continue  # 列早就在了 = 老数据当年已经迁完;此后的「没有共享行」是主人收回了
            conn.execute(
                text(
                    "INSERT INTO resource_shares (id, kind, resource_id, workspace_id, shared_by, created_at) "
                    f"SELECT lower(hex(randomblob(16))), :kind, {table}.id, {table}.workspace_id, "
                    f"COALESCE({table}.owner_user_id, ''), CURRENT_TIMESTAMP FROM {table} "
                    "WHERE NOT EXISTS (SELECT 1 FROM resource_shares s "
                    f"WHERE s.kind = :kind AND s.resource_id = {table}.id "
                    f"AND s.workspace_id = {table}.workspace_id)"
                ),
                {"kind": kind},
            )


def _migrate_publish_task_options() -> None:
    """publish_tasks 新增 options 列(平台自己的发布选项:可见性、允许评论…)。

    create_all 只建新表,不给已有表补列。老任务留空字典 —— 执行器把「没有这个键」当成用默认值,
    而默认值一律是最保守的那档(可见性 = 私享 / 仅自己可见),所以老数据不会因为升级而突然公开。
    """
    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    if "options" in {c["name"] for c in inspector.get_columns("publish_tasks")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN options JSON NOT NULL DEFAULT '{}'"))


def backfill_dub_tracks() -> None:
    """把**已经存在的**配音轨标出来。

    这个功能上线时已经有人配过音了;不认它们的话,下一次配音会在旁边再建一条,而用户看到的是
    「说好的复用呢」。

    判据是事实,不是猜:一条音频轨上的片段**全部**来自 TTS 产物(asset.source='tts'),且至少
    有一段。BGM / 录音 / 原声轨不会满足;**空轨也不会** —— 空轨恰恰是失败的配音留下的残骸,
    把它认成配音轨等于把垃圾扶正。
    """
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE tracks SET role = 'dub'
            WHERE kind = 'audio'
              AND role = ''
              AND EXISTS (SELECT 1 FROM clips WHERE clips.track_id = tracks.id)
              AND NOT EXISTS (
                    SELECT 1 FROM clips
                    LEFT JOIN assets ON assets.id = clips.asset_id
                    WHERE clips.track_id = tracks.id
                      AND (assets.source IS NULL OR assets.source <> 'tts')
              )
        """))


def _migrate_track_role() -> None:
    """给轨道补 `role` 列。

    配音要能回到**同一条**配音轨上,而不是每配一次多一条空轨。认哪条轨不能靠名字 —— 名字是
    给人看的,用户随时会改成「旁白」「解说」。
    """
    inspector = inspect(engine)
    if "tracks" not in set(inspector.get_table_names()):
        return
    if "role" in {c["name"] for c in inspector.get_columns("tracks")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tracks ADD COLUMN role VARCHAR(24) NOT NULL DEFAULT ''"))
    backfill_dub_tracks()


def _migrate_subtitle_tracks_carry_no_sound() -> None:
    """字幕轨上的独奏 / 闪避标记清掉 —— 字幕轨没有声音,这两个开关在它身上不再存在。

    此前轨道头给字幕轨也摆了独奏按钮。按下去的后果是反的:「有轨在独奏」成立,而字幕轨没有声音,
    于是预览和成片里**所有**声音都被关掉。现在 set_track_state 拒绝给字幕轨设这两个标记,老库里
    已经按下去的那些在这里放回去 —— 结果就是用户本来想要的「什么都没独奏」。
    """
    inspector = inspect(engine)
    if "tracks" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("tracks")}
    if not {"solo", "duck"} <= columns:
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE tracks SET solo = 0, duck = 0 WHERE kind = 'subtitle' AND (solo = 1 OR duck = 1)"))


def _migrate_generation_capability_profiles() -> None:
    """建生成参数模板与逐模型、逐 kind 的声明表。

    `_create_current_schema` 会为全新库建好它;这一步是给**已有库**补上的。建表语句从模型本身
    取(`checkfirst=True`),不手写一遍 DDL —— 手写的那份迟早和模型分岔,而分岔的症状是某一列
    在老库上不存在,只有升级过来的人撞得到。
    """
    from app.db.models import GenerationCapabilityDeclaration, GenerationCapabilityProfile

    GenerationCapabilityProfile.__table__.create(bind=engine, checkfirst=True)
    GenerationCapabilityDeclaration.__table__.create(bind=engine, checkfirst=True)


def _migrate_prompt_requirement_becomes_one_field() -> None:
    """用户写下的参数组里,「提示词要不要写」从两个布尔收成一格 `prompt`(见 catalog.PROMPT_MODES)。

    此前是 `requires_prompt`(必须写)和 `prompt_optional`(可以不写)两个布尔,而且只对音频生效;现在
    是一格三值 `required` / `optional` / `none`,各种生成共用。参数组是用户手填的描述符,校验按白名单
    (见 custom_profiles._KNOWN_KEYS),不搬的话老键会让这份参数组**再也存不回去**。

    - `prompt_optional: true` → `prompt: "optional"`;
    - `requires_prompt: true` → 不写(`required` 就是没写时的意思);
    - 两个布尔一律删掉。已经有 `prompt` 的不覆盖。

    幂等:第二次跑时已经没有这两个键。
    """
    if "generation_capability_profiles" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, capabilities FROM generation_capability_profiles")).mappings().all():
            raw = row["capabilities"]
            try:
                capabilities = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if not isinstance(capabilities, dict) or not {"requires_prompt", "prompt_optional"} & set(capabilities):
                continue
            capabilities.pop("requires_prompt", None)
            if capabilities.pop("prompt_optional", None) is True:
                capabilities.setdefault("prompt", "optional")
            conn.execute(
                text("UPDATE generation_capability_profiles SET capabilities = :c WHERE id = :id"),
                {"c": json.dumps(capabilities, ensure_ascii=False), "id": row["id"]},
            )


def _migrate_provider_model_capability_ref() -> None:
    """给模型行补 `generation_capability_ref` 列。

    生成参数此前只能来自静态目录,而目录按 (provider, model, kind) 精确查 —— 用户手填的别名
    (`gpt-image-2-client`)、经另一条中转配的同一个模型,一律查不到,界面上一个参数都没有。
    这一列是用户写下"只有他知道的事"的地方。**回填不做任何猜测**:老行一律留空 = 跟随目录,
    和它现在的行为一模一样。
    """
    inspector = inspect(engine)
    if "provider_models" not in set(inspector.get_table_names()):
        return
    if "generation_capability_ref" in {c["name"] for c in inspector.get_columns("provider_models")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_models ADD COLUMN generation_capability_ref VARCHAR(200)"))


def _migrate_prepared_publish_tasks() -> None:
    """把老的 `prepared` 发布任务迁成 `cancelled`。

    `prepared`(表单填好、等人确认)只由 dry_run 那条路产生,而 dry_run 从来没有任何办法被触发
    ——后端的认领载荷把它写死成 False。整条路已删,`prepared` 随之退出状态枚举。

    库里可能还留着这个状态的行(本机就有两条)。留着它们等于留下一个**没人认得的状态**:
    界面查不到对应文案、任务总线的终态集合也不含它,于是那些行会永远显示成中间态。
    迁成 cancelled 是诚实的:它们当年停在"等人确认"那一步,而现在没有任何东西会再推它们一把。
    """
    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE publish_tasks SET status = 'cancelled' WHERE status = 'prepared'"))


def _migrate_job_message_i18n() -> None:
    """jobs 新增 message_key / message_params / error_key / error_params(任务文案的多语言)。

    老行留空 —— 它们只留下了当年渲染的那句话,反推不出 key。接口见到空 key 就原样返回 message,
    所以历史任务显示成写入时的语言;**新任务从此跟着请求语言走**。这是数据本身的界限,不是兼容分支。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        if "message_key" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN message_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "message_params" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN message_params JSON NOT NULL DEFAULT '{}'"))
        #: 失败原因同一对。老行同样留空 —— 反推不出 key,接口见到空 key 就原样返回那句话。
        if "error_key" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN error_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "error_params" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN error_params JSON NOT NULL DEFAULT '{}'"))


def _drop_member_perm_overrides() -> None:
    """删掉 workspace_member_perms 整张表(ADR 0008 D4:角色即权限)。

    权限位矩阵退场之后这张表没有读它的代码了 —— 留着一张没人读的表,下一个人会以为它还在起作用,
    而它记录的恰恰是"某人被单独关掉了某项能力"这种最容易被误读的信息。

    删表是不可逆的,但这里可逆的那一半在别处:真需要逐位配置时重新加回来,那时会有真实用例说清楚
    要哪几位 —— 而不是把一张旧形状的表当成需求。
    """
    inspector = inspect(engine)
    if "workspace_member_perms" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE workspace_member_perms"))


def _migrate_deployment_admin() -> None:
    """users 新增 is_deployment_admin,并把**最早创建的账号**提成部署管理员。

    此前「谁对这个部署负责」没有对应物,只能用「在任意工作区里是 admin」去近似 —— 而工作区可以
    自助新建,所以那个近似是自助的。这次把它变成数据。

    回填选最早的账号:单机安装里那就是本人;团队安装里那是当初装起这台后端的人 —— 两种情况下
    都是对的那个人,而且与 `_adopt_orphan_workspaces`(第一个账号继承登录前建的工作区)同一条理由。
    幂等:已经有人持有就不再动(管理员可能已经把它转给了别人)。
    """
    inspector = inspect(engine)
    if "users" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        if "is_deployment_admin" not in {c["name"] for c in inspector.get_columns("users")}:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_deployment_admin BOOLEAN NOT NULL DEFAULT 0")
            )
        already = conn.execute(text("SELECT COUNT(*) FROM users WHERE is_deployment_admin = 1")).scalar()
        if already:
            return
        conn.execute(
            text(
                "UPDATE users SET is_deployment_admin = 1 WHERE id = ("
                "SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1)"
            )
        )


def _migrate_permission_modes() -> None:
    """三档权限模式的两组列(agent_sessions 的模式、tool_confirmations 的留痕)。

    老行取默认值就是正确语义:模式 manual(与此前行为一致)、白名单空、历史卡记为 manual —— 它们
    确实都是人点的,那时还没有自动放行。读取代码里因此不留"有没有这些列"的分支(docs/adr/0006)。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "agent_sessions": [
            ("permission_mode", "ALTER TABLE agent_sessions ADD COLUMN permission_mode VARCHAR(16) NOT NULL DEFAULT 'manual'"),
            ("mode_set_by", "ALTER TABLE agent_sessions ADD COLUMN mode_set_by VARCHAR(64)"),
            ("mode_set_at", "ALTER TABLE agent_sessions ADD COLUMN mode_set_at DATETIME"),
            ("auto_allow_tools", "ALTER TABLE agent_sessions ADD COLUMN auto_allow_tools JSON NOT NULL DEFAULT '[]'"),
        ],
        "tool_confirmations": [
            ("decision_mode", "ALTER TABLE tool_confirmations ADD COLUMN decision_mode VARCHAR(16) NOT NULL DEFAULT 'manual'"),
            ("decided_by", "ALTER TABLE tool_confirmations ADD COLUMN decided_by VARCHAR(64)"),
            ("decision_detail", "ALTER TABLE tool_confirmations ADD COLUMN decision_detail JSON"),
            ("hold_until", "ALTER TABLE tool_confirmations ADD COLUMN hold_until DATETIME"),
        ],
        "workspaces": [
            ("autopilot_rules", "ALTER TABLE workspaces ADD COLUMN autopilot_rules JSON NOT NULL DEFAULT '{}'"),
        ],
    }
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        missing = [sql for name, sql in columns if name not in existing]
        if not missing:
            continue
        with engine.begin() as conn:
            for sql in missing:
                conn.execute(text(sql))


def _migrate_auth_session_expiry() -> None:
    """auth_sessions 新增 kind / expires_at 两列 —— 这张表此前没有过期概念。

    老行分不出哪些是真正的登录、哪些是泄漏的服务令牌(工具通道每次调用留一行,OAuth 刷新、
    查额度、订阅登录也各留一行),所以一律按登录处理,给一个完整周期:**升级不该把任何人踢
    出去**。它们最迟一个周期后自然消失,而增长从这次起就停了。

    `expires_at` 在模型上是 NOT NULL,但这里补列时必须允许为空 —— SQLite 给已有行加 NOT NULL
    列要求常量默认值,而"当前时间 + 周期"不是常量。所以先加列、再回填,回填之后不会再有空值。
    """
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("auth_sessions")}
    with engine.begin() as conn:
        if "kind" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'login'"))
        if "expires_at" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN expires_at DATETIME"))
        # 确认卡的会话归属(§ docs/AGENT_PERMISSION_MODES.md 4.5)。老令牌留空 —— 它们要么是登录
        # 令牌本来就没有会话,要么是上一版铸出来的 turn 令牌,而那些 turn 早就结束了。
        if "agent_session_id" not in columns:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN agent_session_id VARCHAR(64)"))
        # 幂等:只填空值。跑第二次时上面两个分支都不进,这句也改不动任何行。
        horizon = (datetime.now(UTC).replace(tzinfo=None) + LOGIN_SESSION_TTL).isoformat(
            sep=" ", timespec="seconds"
        )
        conn.execute(text("UPDATE auth_sessions SET expires_at = :h WHERE expires_at IS NULL"), {"h": horizon})


def _migrate_tts_pip_index() -> None:
    """tts_config 新增 pip_index 列(装引擎依赖时用的 pip 镜像)。

    create_all 只建新表,不给**已有**表补列——已装机的 tts_config 表没有这列,
    读配置时会直接 OperationalError。加列即可,老行取默认空串(= 官方 PyPI)。
    """
    inspector = inspect(engine)
    if "tts_config" not in set(inspector.get_table_names()):
        return
    if "pip_index" in {c["name"] for c in inspector.get_columns("tts_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tts_config ADD COLUMN pip_index VARCHAR(200) NOT NULL DEFAULT ''"))


def _migrate_provider_capabilities() -> None:
    """加列迁移:provider_profiles 增加 capability_ids(档案级能力覆盖,None=沿用 vendor 默认)。"""
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    if "capability_ids" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN capability_ids JSON"))


def _drop_shared_credentials() -> None:
    """去掉 `provider_credentials.shared`。

    这个位是为了让第 4 步的升级无缝而加的:老库里那把大家共用的钥匙,迁移后仍然大家能用。
    但它**没有任何界面**(等于一个只有迁移能置位的隐藏状态),而且和这张表存在的理由自相矛盾 ——
    钥匙归人,正是为了不再「所有人共用一把、花的是同一个人的钱」。

    已经存在的行不动:它们仍然属于那位部署管理员,只是不再对别人生效。
    """
    inspector = inspect(engine)
    if "provider_credentials" not in set(inspector.get_table_names()):
        return
    if "shared" not in {c["name"] for c in inspector.get_columns("provider_credentials")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_credentials DROP COLUMN shared"))


def _migrate_encrypt_secrets() -> None:
    """把老库里明文躺着的密钥就地加密(见 core/secrets_at_rest)。

    哪些列装秘密登记在 `ENCRYPTED_COLUMNS` 一处;这里按那份清单逐列扫。**只在迁移里判断
    "这串是不是已经加密过的"** —— 运行时不做这种判断,那会变成读取期的两路兼容(ADR 0006)。

    幂等:已经是密文的跳过。解不开的也跳过(不是本部署的密钥,再加一层只会更糟)。
    """
    from app.core.secrets_at_rest import ENCRYPTED_COLUMNS, encrypt, looks_encrypted

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table, column in sorted(ENCRYPTED_COLUMNS):
        if table not in tables:
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as conn:
            # 主键列名各表不同,用 rowid —— SQLite 每张普通表都有。
            rows = conn.execute(
                text(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''")
            ).all()
            for rowid, value in rows:
                raw = str(value)
                if looks_encrypted(raw):
                    continue
                conn.execute(
                    text(f"UPDATE {table} SET {column} = :v WHERE rowid = :r"),
                    {"v": encrypt(raw), "r": rowid},
                )


def _migrate_provider_defaults_per_person() -> None:
    """`provider_defaults` 从「一项能力一行」变成「一个人一项能力一行」。

    老库里那一行是**整个部署共用的默认**,没有主人。它曾被搬成 `owner_user_id = ''`(那时还有
    "部署默认"这一档),而那一档已经删掉了 —— 所以这里**不搬**:一行没有主人的默认,找不到
    任何一个人可以诚实地记在他名下。搬给所有人等于替每个人做了一次他没做过的选择,正是删掉
    这一档要避免的事。升级后每个人第一次用时自己选一个(见 domain/provider_defaults.get_row)。

    SQLite 改不了主键,所以按重建表的老办法:建新表 → 换名。
    """
    inspector = inspect(engine)
    if "provider_defaults" not in set(inspector.get_table_names()):
        return
    if "owner_user_id" in {c["name"] for c in inspector.get_columns("provider_defaults")}:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE provider_defaults_new ("
                "capability VARCHAR(24) NOT NULL, owner_user_id VARCHAR(64) NOT NULL DEFAULT '', "
                "provider_profile_id VARCHAR(64), model VARCHAR(120) NOT NULL DEFAULT '', "
                "provider_model_id VARCHAR(64), updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (capability, owner_user_id))"
            )
        )
        conn.execute(text("DROP TABLE provider_defaults"))
        conn.execute(text("ALTER TABLE provider_defaults_new RENAME TO provider_defaults"))


def _migrate_hash_session_tokens() -> None:
    """把老库里明文存着的会话令牌就地换成哈希。

    令牌就是这个人本人 —— 一次库泄露(或一份被拷走的数据目录)里,所有还没过期的令牌都能直接
    拿去用,受害者这边不会有任何痕迹。密码早就只存哈希了,令牌此前不是。

    **人不掉线**:他手上那串没变,校验时再哈希一次就对得上。

    判据是前缀 `sha256:`,不是长度 —— 原始令牌本身就是 64 位十六进制(token_hex(32)),和裸哈希
    长得一模一样。迁移每次启动都会跑,认错一次就是把所有人哈希两遍、全部掉线。
    """
    if "auth_sessions" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT token FROM auth_sessions")).fetchall()
        for (stored,) in rows:
            if str(stored).startswith(f"{TOKEN_SCHEME}:"):
                continue
            conn.execute(
                text("UPDATE auth_sessions SET token = :hashed WHERE token = :raw"),
                {"hashed": token_digest(str(stored)), "raw": stored},
            )


def _migrate_connections_get_an_owner() -> None:
    """给每条供应商连接补上主人。

    老库里连接是部署级的、没有主人。**归给这台部署的管理员** —— 因为建连接一直需要部署管理员
    权限,所以现存的每一条都是某个管理员建的。多个管理员时取最早那个:库里没记 creator,而"最早
    的那个管理员"是唯一还能猜的答案,猜错的代价也只是他要把连接让给同事(而不是谁的钥匙串了)。

    钥匙本来就是按人的,所以这一步不会让任何人拿到别人的钥匙:连接归了 A,B 在那条连接上的钥匙
    行还在,只是 B 从此看不到那条连接 —— 这正是要的效果(见 tests/test_connections_belong_to_a_person)。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("provider_profiles")}
    with engine.begin() as conn:
        if "owner_user_id" not in columns:
            conn.execute(
                text("ALTER TABLE provider_profiles ADD COLUMN owner_user_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin:
            conn.execute(
                text("UPDATE provider_profiles SET owner_user_id = :uid WHERE owner_user_id = ''"),
                {"uid": admin},
            )


def _migrate_drop_the_knowledge_base() -> None:
    """删掉知识库留下的表和向量库文件。

    功能整块删了(见 tests/test_the_knowledge_base_is_gone)。**表不留**:一张没人读的表不是
    "以后可能有用",是下一个人打开数据库时的一个问号 —— 而它还带着用户以为自己存好了的文档。

    向量库是数据目录下的单文件(milvus-lite),一并删掉;删不掉只记日志,它不该挡住启动。
    """
    names = ("kb_chunks_fts", "kb_chunks", "kb_documents", "kb_datasets", "kb_embedding_config")
    existing = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for name in names:
            if name in existing or name.endswith("_fts"):
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    # **milvus-lite 建的是目录,不是文件** —— 名字叫 kb_vectors.db 很容易看成单文件,而
    # `unlink()` 对目录抛 IsADirectoryError(OSError 的子类),正好被这里的 except 吃掉:
    # 表删干净了、目录原封不动留着。拿真实数据目录验过才发现。
    import shutil

    stale = settings.data_dir / "kb_vectors.db"
    try:
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    except OSError:
        logger.warning("删不掉遗留的向量库:%s", stale)


def _migrate_plugin_instances_get_an_owner() -> None:
    """给每个插件接入补上主人 —— 和连接那条同一个道理(见 _migrate_connections_get_an_owner)。

    老库里接入是部署级的,建它一直需要部署管理员权限,所以现存的每一个都是某个管理员配的。
    多个管理员时取最早那个。
    """
    inspector = inspect(engine)
    if "plugin_instances" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("plugin_instances")}
    with engine.begin() as conn:
        if "owner_user_id" not in columns:
            conn.execute(
                text("ALTER TABLE plugin_instances ADD COLUMN owner_user_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin:
            conn.execute(
                text("UPDATE plugin_instances SET owner_user_id = :uid WHERE owner_user_id = ''"),
                {"uid": admin},
            )


def _migrate_drop_deployment_defaults() -> None:
    """删掉「部署默认模型」那些行 —— 这一档不存在了。

    它看起来温和:只在你没设过时生效。但造成的正是这个应用里反复出现的那种误解 —— 界面上你
    没选过任何模型,回答却来自某个你不知道的模型,花的是你的额度、用的是你的钥匙,而你从没
    同意过。**替人做的选择必须是他自己做的。**

    **不把它下发给每个人**:那样所有人都会"已经有一个默认",而那个默认仍然不是他选的 ——
    只是把同一个问题从一处挪到了每一处。删掉之后他会看到"还没选好模型,去选一个",这句话
    他看得懂,而且知道下一步做什么。

    针对的是已经做过按人拆分那一步的库(比如已经在跑的部署);更老的库在上一个迁移里就不搬了。
    """
    inspector = inspect(engine)
    if "provider_defaults" not in set(inspector.get_table_names()):
        return
    if "owner_user_id" not in {c["name"] for c in inspector.get_columns("provider_defaults")}:
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM provider_defaults WHERE owner_user_id = ''"))


def _migrate_deployment_config() -> None:
    """建部署配置行,并用**环境变量播一次种**。

    老部署可能显式设过 `MOSAEL_OPEN_REGISTRATION=0`,那是它的选择,不该在升级时被默认值
    冲掉。播种只发生一次:库里有行之后环境变量再变也不影响 —— 唯一真相是库。
    """
    import os

    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return  # create_all 还没跑到(首次装机),下次启动再补
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM deployment_config WHERE id = 'default'")).scalar()
        if exists:
            return
        raw = (os.environ.get("MOSAEL_OPEN_REGISTRATION") or "").strip().lower()
        seeded = 0 if raw in ("0", "false", "no", "off") else 1
        conn.execute(
            text(
                "INSERT INTO deployment_config (id, open_registration, updated_at) "
                "VALUES ('default', :open, :now)"
            ),
            {"open": seeded, "now": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")},
        )


def _migrate_client_version() -> None:
    """`auth_sessions` 补 `client_version` / `last_seen_at`:这个人跑的是哪一版、还在不在用。"""
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(auth_sessions)"))}
        if "client_version" not in existing:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN client_version VARCHAR(32) NOT NULL DEFAULT ''"))
        if "last_seen_at" not in existing:
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN last_seen_at DATETIME"))


def _drop_reviews_table() -> None:
    """删掉 `reviews` —— 一个**完整的后端功能,而界面上零入口**。

    表、领域、路由、测试都在,而前端、i18n、MCP 工具、智能体工具**没有任何一处**碰过它:
    `listReviews` / `requestReview` / `decideReview` 三个客户端函数全仓零调用。
    它是由 `test_api_fields_reach_the_screen`(ReviewOut 的六个字段没人读)顺出来的。

    留着的代价和 `linked_clip_id` 一样:下一个人读到它会以为评审已经做好,去查"为什么点不到"。
    2026-09-23 与用户确认后整条删;真要做评审时按那时的需求重新建模,而不是继承一份没人用过
    的形状。活动流里已有的 `review.requested` / `review.decided` 记录**原样留着** ——
    那是发生过的事,不因为功能没了就抹掉。
    """
    inspector = inspect(engine)
    if "reviews" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE reviews"))


def _migrate_browser_action_leases() -> None:
    """`browser_actions` 补 ADR-0002 的租约三件套(lease_worker / lease_token / lease_expires_at)。

    这条通道此前一条都没落:认领不记谁领的、回报不校验令牌、心跳只说"我还在"。单执行器下
    工作正常,而多执行器或执行器崩溃时没有任何东西保证正确 —— 隔壁两条通道都有。

    老行(升级那一刻还停在 queued/running 的)**直接判失败**:它们是上一个进程留下的,
    执行器视图早随那个进程消失了,留着只会让调用方一直等到超时。不给它们补一个空租约 ——
    那等于在读路径上留一条"租约为空怎么办"的永久分支(见 jobs.expire_worker_leases 里记的
    那次教训)。
    """
    inspector = inspect(engine)
    if "browser_actions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(browser_actions)"))}
        for name, ddl in (
            ("lease_worker", "VARCHAR(64)"),
            ("lease_token", "VARCHAR(64)"),
            ("lease_expires_at", "DATETIME"),
        ):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE browser_actions ADD COLUMN {name} {ddl}"))
        conn.execute(
            text(
                "UPDATE browser_actions SET status = 'failed', error = '后端升级导致中断' "
                "WHERE status IN ('queued', 'running')"
            )
        )


def _drop_clip_linked_clip_id() -> None:
    """`clips` 去掉 `linked_clip_id` —— 这一列在**每一台机器上都是 null**。

    它本来要装的是"分离音频之后两段是链接的"(拖一个另一个跟着走、删一个另一个一起删),
    数据形状、接口出参、前端生成类型、撤销还原清单五处都为它让了路 —— 而
    `detach_clip_audio` 那个本该建立配对的操作从头到尾没设过它,全仓零赋值。

    这比没有这个字段更贵:下一个人读到它会以为链接已经实现,去查"为什么没生效",
    而真相是从来没人写过它。功能要做的时候按真实需求重新建模,不留这个空承诺。
    """
    inspector = inspect(engine)
    if "clips" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if "linked_clip_id" in existing:
            conn.execute(text("ALTER TABLE clips DROP COLUMN linked_clip_id"))


def _drop_publish_account_profile_name() -> None:
    """`publish_accounts` 去掉 `profile_name` —— 这一列在**每一台机器上都是 NULL**。

    后端收它、落库、放进 `PublishAccountOut`;而桌面执行器那侧的 `patchAccount` 签名里
    **根本没有这个字段**,从来没人发过。一列永远为空的数据,和一条写在出参里的空承诺。

    按仓库规矩,死字段是删掉而不是留着 —— 留着的代价是下一个人会以为它有数据,照它写
    分支。SQLite 3.35+ 支持 DROP COLUMN;没有这一列的老库(它本来就是后加的)也不需要
    额外分支,下面那句 `in existing` 就是判据。
    """
    inspector = inspect(engine)
    if "publish_accounts" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(publish_accounts)"))}
        if "profile_name" in existing:
            conn.execute(text("ALTER TABLE publish_accounts DROP COLUMN profile_name"))


def _migrate_client_surface() -> None:
    """`auth_sessions` 补 `client_surface`:自报身份里「哪个界面」那一半。

    此前只有一栏 `client_version`,而浏览器扩展往里塞的是产品名 `browser-extension` ——
    管理页照着渲染 `v{...}`,于是那一行写着「vbrowser-extension」。两个问题挤一栏,总会有
    一个客户端把它读成另一个意思。

    老行留空:它们报的是旧语法(裸版本号),新语法认不出来 —— 而"不知道"本来就是这一栏
    的合法状态。用户的客户端升上来之后,下一个请求就把两栏一起写对。
    """
    inspector = inspect(engine)
    if "auth_sessions" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(auth_sessions)"))}
        if "client_surface" not in existing:
            conn.execute(
                text("ALTER TABLE auth_sessions ADD COLUMN client_surface VARCHAR(32) NOT NULL DEFAULT ''")
            )


def _migrate_job_actor() -> None:
    """`jobs` 补 `created_by`:这活儿**替谁干**。

    后台线程手里只有一个 job,没有这一栏就答不出该用谁的钥匙、花谁的额度(见 domain/jobs.create_job
    与 domain/provider_credentials)。老任务回填成 NULL —— 它们跑完了,而"当初是谁要的"这件事
    老数据里确实没有记过,编一个出来比留空更糟。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if "created_by" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN created_by VARCHAR(64)"))


def _encrypted(value: object) -> str | None:
    """迁移里往加密列写值时用。空值原样返回(空不是秘密)。"""
    from app.core.secrets_at_rest import encrypt, looks_encrypted

    if value is None or value == "":
        return value if value is None else ""
    raw = value if isinstance(value, str) else str(value)
    return raw if looks_encrypted(raw) else encrypt(raw)


def _migrate_provider_credentials() -> None:
    """钥匙从 `provider_profiles` 搬到 `provider_credentials`,并把那几列删掉。

    升级前所有人共用档案行上那把钥匙。迁移把它归到**最早那位部署管理员**名下 —— 有主人,而且
    只有他能用。别人各配各的(见 domain/provider_credentials:没有"共享钥匙"这回事,它没有界面,
    而且回退到别人的钥匙正是这张表要消灭的东西)。

    **搬走而不是并存**:密钥列留在档案行上,就等于留着一条不经过解析、读到别人钥匙的路。
    列删掉之后,漏改的读取点会当场炸,而不是悄悄读到不该读的东西。

    `auth_type` 留在档案上 —— 它说的是这条连接怎么鉴权,不是谁的钥匙。幂等:列没了就直接返回。

    **先给 provider_credentials 补列再搬**:`create_all` 只建缺失的**表**,从不给已存在的表加列
    —— 一个装过中途版本的库里,这张表可能已经存在但少几列,直接往里插会当场 OperationalError。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_profiles" not in tables:
        return
    if "provider_credentials" in tables:
        # 查列与加列必须在**同一个连接**上:inspect 可能从池里另一条连接读,而那条连接看到的
        # schema 未必是刚刚 DDL 之后的(tests/util.py 里记过同一种症状 —— duplicate column)。
        with engine.begin() as conn:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_credentials)"))}
            for name, ddl in (
                ("api_key", "ALTER TABLE provider_credentials ADD COLUMN api_key VARCHAR(500) NOT NULL DEFAULT ''"),
                ("oauth_credential", "ALTER TABLE provider_credentials ADD COLUMN oauth_credential JSON"),
                ("secrets", "ALTER TABLE provider_credentials ADD COLUMN secrets JSON NOT NULL DEFAULT '{}'"),
                ("model_catalog", "ALTER TABLE provider_credentials ADD COLUMN model_catalog JSON"),
                (
                    "credential_version",
                    "ALTER TABLE provider_credentials ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 0",
                ),
                ):
                if name not in existing:
                    conn.execute(text(ddl))
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    if "auth_type" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE provider_profiles ADD COLUMN auth_type VARCHAR(20) NOT NULL DEFAULT 'api_key'")
            )
    movable = [c for c in ("api_key", "oauth_credential", "credential_version", "model_catalog") if c in columns]
    if not movable:
        return  # 已经搬过了
    if "provider_credentials" not in tables or "users" not in tables:
        return  # create_all 还没跑到(首次装机),下次启动再补

    with engine.begin() as conn:
        admin = conn.execute(
            text("SELECT id FROM users WHERE is_deployment_admin = 1 ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin is None:
            admin = conn.execute(text("SELECT id FROM users ORDER BY created_at LIMIT 1")).scalar()
        if admin is not None:
            select_cols = ", ".join(movable)
            rows = conn.execute(text(f"SELECT id, {select_cols} FROM provider_profiles")).mappings().all()
            for row in rows:
                api_key = (row.get("api_key") or "") if "api_key" in movable else ""
                oauth = row.get("oauth_credential") if "oauth_credential" in movable else None
                if not api_key and not oauth:
                    continue  # 从来没配过钥匙的连接不用建凭据行
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO provider_credentials "
                        "(profile_id, owner_user_id, api_key, oauth_credential, secrets, model_catalog, "
                        " credential_version, created_at, updated_at) "
                        "VALUES (:pid, :uid, :key, :oauth, '{}', :catalog, :version, :now, :now)"
                    ),
                    {
                        "pid": row["id"],
                        "uid": admin,
                        # 目标列是加密列(见 core/secrets_at_rest):这条迁移自己写密文,
                        # 而不是指望后面那趟 _migrate_encrypt_secrets 来补 —— 每条迁移
                        # 跑完之后库都该是自洽的。
                        "key": _encrypted(api_key),
                        "oauth": _encrypted(row.get("oauth_credential")) if "oauth_credential" in movable else None,
                        "catalog": row.get("model_catalog") if "model_catalog" in movable else None,
                        "version": row.get("credential_version") or 0 if "credential_version" in movable else 0,
                        "now": datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
                    },
                )
        for column in movable:
            conn.execute(text(f"ALTER TABLE provider_profiles DROP COLUMN {column}"))


def _migrate_agent_thinking_level() -> None:
    """加列迁移:agent_sessions 增加 thinking_level。老会话留 'off',与此前行为一致。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("agent_sessions")}
    if "thinking_level" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN thinking_level VARCHAR(10) NOT NULL DEFAULT 'off'"))


def _merge_split_vendors() -> None:
    """把被人为拆开的同一家供应商合回去(只改 vendor 值,档案本身不合并)。

    图像/视频、对话/语音此前各占一个 vendor,理由写在旧注释里:"一处改动不牵连另一处" ——
    那在"一个档案只有一套能力、一个默认模型"的年代成立。供应商⇄模型重构之后一条连接能挂
    任意多个模型、各自带能力,拆分只剩代价:同一把 Key 填两遍,设置页里一个账号占两行。

    **不合并档案本身**:用户可能真的想把图像和视频分开管(不同 Key、不同区域端点),
    那是他的选择;这里只是让"火山方舟"重新变成一个 vendor,两个档案照样并存。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    merges = {
        "bytedance-image": "bytedance",
        # 语音那两个的 vendor id 同时是**持久化的语音引擎 id**,所以合并要连着改
        # tts_config.engine 与历史任务载荷 —— 见 _merge_openai_tts_engine。
        "openai-tts": "openai",
        # openai-compatible-tts 整个退场:它存在的唯一理由是"要填自定义 endpoint",
        # 而 openai 档案本来就有 base_url 字段。
        "openai-compatible-tts": "openai",
    }
    with engine.begin() as conn:
        for old_vendor, new_vendor in merges.items():
            conn.execute(
                text("UPDATE provider_profiles SET vendor=:new WHERE vendor=:old"),
                {"new": new_vendor, "old": old_vendor},
            )


def _merge_openai_tts_engine() -> None:
    """语音引擎 id `openai-tts` / `openai-compatible-tts` → `openai`。

    引擎 id 不只是个显示名:domain/voices/voices.py 拿它当 vendor 去 resolve_connection,所以它同时
    存在于**三处**——tts_config.engine、历史任务的 payload、以及任务结果里记录的"实际用了
    哪个引擎"。只改预设不改这三处,已有配置会在下次合成时找不到档案。

    迁移在启动时跑完,读取代码里因此**不留旧 id 的别名** —— 那种别名是一笔永久的税
    (见 docs/adr/0006),而这里三处都改到了,没有第四处会读到旧串。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    legacy = ("openai-tts", "openai-compatible-tts")
    with engine.begin() as conn:
        if "tts_config" in tables:
            conn.execute(
                text("UPDATE tts_config SET engine='openai' WHERE engine IN ('openai-tts','openai-compatible-tts')")
            )
        if "jobs" in tables:
            # 载荷是 JSON 字符串,SQLite 的 json_set 能就地改;比读出来再写回省一趟,
            # 也不必把整张 jobs 表读进内存。
            for column in ("payload", "result"):
                for old_id in legacy:
                    conn.execute(
                        text(
                            f"UPDATE jobs SET {column} = json_set({column}, '$.engine', 'openai') "
                            f"WHERE json_valid({column}) AND json_extract({column}, '$.engine') = :old"
                        ),
                        {"old": old_id},
                    )


def _adopt_deepseek_vendor() -> None:
    """把明确指向 api.deepseek.com 的「OpenAI 兼容端点」档案改挂 deepseek 预设。

    通用预设为了覆盖各种自建网关声明了 chat/image/embedding,而模型行没显式设能力时会把三样
    全继承 —— DeepSeek 的对话模型于是会出现在「AI 绘图」的可选项里。判据取 base_url 而不是
    名字:域名是确定的,名字是用户随便起的。只改 vendor,base_url/密钥/模型行一概不动。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE provider_profiles SET vendor='deepseek' "
                "WHERE vendor='openai-compatible' AND base_url LIKE '%api.deepseek.com%'"
            )
        )


def _drop_generation_models() -> None:
    """删表:generation_models 退场。

    它曾是"有哪些模型可以生成"的第二个答案 —— 设置页看 provider_models、生成页看这张表,
    两边永远对不齐(ComfyUI 的工作流只在这张表里,而且是个叫 `workflow` 的假模型 id)。
    表里的行全部由 BUILTIN_MODELS 播种、用户改不了,所以直接删,没有需要保留的用户数据;
    那份"某模型支持哪些生成参数"的知识退化成 domain/generation/catalog.capabilities_for
    的一张查表(它本来就是关于供应商 API 的静态知识,不是用户配置)。
    """
    inspector = inspect(engine)
    if "generation_models" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE generation_models"))


def _migrate_generation_job_message_keys() -> None:
    """把生成任务里那句**被当成 key 的英文**换成真正的 key。

    `create_job(message=...)` 收的是 i18n key,而生成流程一直传的是字面量
    "Queued for generation provider" —— 它被原样存进 message_key,而接口是按 key 重翻的,
    于是这些任务**从建出来到跑完**返回的都是这一句:任务早就成功了,界面还写着"已提交给
    生成服务"。用户据此以为任务卡在排队里(真机反馈)。

    新任务由代码修好了(runner 全部走 say());这里把已经落库的那些按终态补上正确的 key。
    只认那一句字面量,认不出的不动 —— 别人手写的自由文本本来就该原样留着。
    """
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("jobs")}
    if "message_key" not in columns:
        return
    mapping = {
        "succeeded": "jobMsg_generationDone",
        "failed": "jobMsg_generationFailed",
        "running": "jobMsg_generationRunning",
        "queued": "jobMsg_generationQueued",
    }
    with engine.begin() as conn:
        for status, key in mapping.items():
            conn.execute(
                text(
                    "UPDATE jobs SET message_key = :key "
                    "WHERE message_key = 'Queued for generation provider' AND status = :status"
                ),
                {"key": key, "status": status},
            )


def _migrate_agent_session_groups() -> None:
    """agent_sessions 新增 group_id —— 会话分组。

    **必须排在 create_all 之前**没有硬要求(它只加一列),但排在前面语义更顺:create_all 建出
    agent_session_groups 那张新表时,成员列已经在了。

    列上**不加外键**:老库用 ALTER TABLE 加列,SQLite 没法事后补约束,新老两种库会长得不一样。
    删分组时由领域层显式把成员置空(见 domain/session_groups.delete_group),两种库行为一致。
    """
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("agent_sessions")}
    if "group_id" in existing:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN group_id VARCHAR(64)"))


def _migrate_session_groups_serve_both() -> None:
    """分组从「对话专属」变成「会话通用」:表改名 + 加 kind,生成会话补 group_id。

    **必须排在 create_all 之前**:否则 create_all 会照新模型建一张空的 session_groups,
    旧的 agent_session_groups 原地留着没人认领 —— 用户建过的分组当场消失。

    kind 的回填是 "agent":这张表此前只装对话分组,没有第二种可能。生成分组是从此刻起
    才建得出来的东西。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "agent_session_groups" in tables:
            # 两张表同时在:说明有谁先跑了 create_all(开发时的 --reload 就会),建出一张空的
            # session_groups,而真正的分组还在旧表里。空表没有任何东西可丢,扔掉它再改名。
            # **不能用「新表不存在才改名」当守卫** —— 那样这些分组会安安静静地留在一张
            # 再没人查的表里,界面上表现为「我建的分组不见了」,而迁移本身一声不吭地成功了。
            if "session_groups" in tables:
                if conn.execute(text("SELECT count(*) FROM session_groups")).scalar_one():
                    raise RuntimeError(
                        "session_groups 和 agent_session_groups 同时有数据 —— 拒绝猜哪份是真的,请人工合并"
                    )
                conn.execute(text("DROP TABLE session_groups"))
            conn.execute(text("ALTER TABLE agent_session_groups RENAME TO session_groups"))
            tables = {"session_groups"} | (tables - {"agent_session_groups"})
        if "session_groups" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("session_groups")}
            if "kind" not in columns:
                conn.execute(text("ALTER TABLE session_groups ADD COLUMN kind VARCHAR(24) NOT NULL DEFAULT 'agent'"))
        if "generation_sessions" in tables:
            columns = {c["name"] for c in inspect(engine).get_columns("generation_sessions")}
            if "group_id" not in columns:
                conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN group_id VARCHAR(64)"))


def _migrate_source_assets_get_a_role() -> None:
    """生成请求里的 `source_asset_ids` → `source_assets`,每一项带上角色。

    此前是一个裸 id 列表,谁是首帧靠「第 0 个」这条约定,于是尾帧/参考视频没地方放。
    老数据的角色按 kind 还原成它当初**实际被当成什么用**:视频那边取的是首帧
    (providers/contracts/generation.first_frame_value 读 source_files[0]),图片那边当的是参考图
    (seedream / qwen-edit / openai-edit 都是这么用的)。这不是猜,是把当时的行为写明。
    """
    inspector = inspect(engine)
    if "generation_jobs" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, kind, request FROM generation_jobs")).fetchall()
        for row in rows:
            try:
                request = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(request, dict) or "source_asset_ids" not in request:
                continue
            ids = request.pop("source_asset_ids") or []
            role = "first_frame" if row[1] == "video" else "reference_image"
            request["source_assets"] = [{"asset_id": str(one), "role": role} for one in ids if str(one).strip()]
            conn.execute(
                text("UPDATE generation_jobs SET request = :request WHERE id = :id"),
                {"request": json.dumps(request, ensure_ascii=False), "id": row[0]},
            )


def _migrate_workflow_source_assets() -> None:
    """工作流 generate 节点的 `source_asset_ids` 配置项 → `source_assets`。

    和上面同一件事的另一半:节点配置里存的也是裸 id(模板字段,可能是换行分隔的字符串)。
    只改键名 —— 值的形态解析器两种都认(见 domain/generation/operations.parse_source_assets),
    角色按节点自己的 kind 兜底,和迁移前的行为一致。
    """
    inspector = inspect(engine)
    if "workflows" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).fetchall()
        for row in rows:
            try:
                graph = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            except (TypeError, ValueError):
                continue
            nodes = graph.get("nodes") if isinstance(graph, dict) else None
            if not isinstance(nodes, list):
                continue
            touched = False
            for node in nodes:
                config = node.get("config") if isinstance(node, dict) else None
                if isinstance(config, dict) and "source_asset_ids" in config:
                    config["source_assets"] = config.pop("source_asset_ids")
                    touched = True
            if touched:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(graph, ensure_ascii=False), "id": row[0]},
                )


def _migrate_plugin_registry_url() -> None:
    """deployment_config 新增 plugin_registry_url(插件市场索引地址)。

    create_all 只建新表,不给**已有**表补列。空串 = 用内置默认。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "plugin_registry_url" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN plugin_registry_url VARCHAR(500) NOT NULL DEFAULT ''"))


def _migrate_shared_host_folders() -> None:
    """deployment_config 新增 shared_host_folders(管理员共享给成员的本机文件夹)。

    create_all 只建新表,不给**已有**表补列。空列表 = 一个都没共享:非管理员读不到本机任何路径,
    只能用素材库里的文件(见 domain/host_files)—— 升级前谁都能填本机路径,那正是要收的口子。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "shared_host_folders" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN shared_host_folders JSON NOT NULL DEFAULT '[]'"))


def _backfill_workflow_revision_authors() -> None:
    """给说不出作者的工作流修订补上作者:这条工作流的创建者,找不到就是它所在工作区的 owner。

    一次运行用私有发布账号 / 浏览器档案 / 本机文件时,被执行那一版的作者(或认可过它的人)也得
    用得了(见 domain/authority)。此前 `created_by` 可空:迁移、官方模板改写落下的修订都没有作者,
    更早的版本里写入路径也不总是填它 —— 不补的话,升级之后每条老工作流的定时任务都会停下来
    要人认可,而单机用户根本不知道在认可什么。

    「创建者」取这条工作流**最早一版里有记录的作者**;一版都没有记录时取工作区 owner(最早加入的
    那位)。都找不到的留空 —— 那一版没有担保人,借不到任何人的私有资源,直到有人认可它。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"workflow_revisions", "workflows", "workspace_members"} <= tables:
        return
    with engine.begin() as conn:
        workflows = conn.execute(
            text(
                "SELECT DISTINCT w.id, w.workspace_id FROM workflows w "
                "JOIN workflow_revisions r ON r.workflow_id = w.id WHERE r.created_by IS NULL"
            )
        ).all()
        for workflow_id, workspace_id in workflows:
            author = conn.execute(
                text(
                    "SELECT r.created_by FROM workflow_revisions r JOIN users u ON u.id = r.created_by "
                    "WHERE r.workflow_id = :id ORDER BY r.revision LIMIT 1"
                ),
                {"id": workflow_id},
            ).scalar()
            if author is None:
                author = conn.execute(
                    text(
                        "SELECT user_id FROM workspace_members WHERE workspace_id = :ws AND role = 'owner' "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"ws": workspace_id},
                ).scalar()
            if author is None:
                continue
            conn.execute(
                text("UPDATE workflow_revisions SET created_by = :author WHERE workflow_id = :id AND created_by IS NULL"),
                {"author": author, "id": workflow_id},
            )


def _cleanup_orphan_resource_shares() -> None:
    """清掉指向已删资源的共享记录。

    `resource_shares.resource_id` 是多态引用(同一列指向五张表),建不了外键、也就没有级联,
    而删除路径此前没人清 —— 记录留在库里指向一个不存在的 id,越攒越多。真库里撞见的时候,
    19 条 generation_session 记录里有 16 条是这样的。

    删除路径现在都会清了(由 tests/test_sharing_forgets_on_delete.py 钉住),这一条只处理
    存量。**每次启动都跑**:它按 kind 逐张表反查,没有孤儿时是几条空查询。
    """
    tables = {
        "publish_account": "publish_accounts",
        "browser_profile": "browser_profiles",
        "agent_session": "agent_sessions",
        "generation_session": "generation_sessions",
        "scheduled_task": "scheduled_tasks",
    }
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    if "resource_shares" not in present:
        return
    with engine.begin() as conn:
        for kind, table in tables.items():
            if table not in present:
                continue
            removed = conn.execute(
                text(
                    f"DELETE FROM resource_shares WHERE kind = :kind "  # noqa: S608 — 表名来自上面那张常量表
                    f"AND resource_id NOT IN (SELECT id FROM {table})"
                ),
                {"kind": kind},
            ).rowcount
            if removed:
                logger.info("清掉 %d 条指向已删 %s 的共享记录", removed, kind)


def _migrate_agent_notice_envelope_out_of_content() -> None:
    """把跨会话通知的**信封**从正文里剥出来,来源改记进 payload。

    这句信封(「【来自另一个智能体会话的通知】发起会话 id:<32位>」)是写给模型的,此前被拼进
    了 content —— 而 content 正是用户在对话里看到的那一份,于是界面上就多出一行方括号标签
    加一串十六进制。现在信封只在拼提示词时加(见 domain/agent/prompt.agent_notice_envelope),
    「谁发来的」在库里只留一个表示:payload.from_agent_session。

    存量这么写的消息在这里一次性改正,而不是让前端去认那个前缀 —— 靠字符串匹配认信封,正是
    这件事一开始就该避免的做法。
    """
    import json
    import re

    inspector = inspect(engine)
    if "agent_messages" not in set(inspector.get_table_names()):
        return
    pattern = re.compile(r"^【来自另一个智能体会话的通知】发起会话 id:(\S+)\n\n", re.S)
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, content, payload FROM agent_messages WHERE role='user' AND content LIKE '【来自另一个智能体会话的通知】%'")
        ).fetchall()
        for row in rows:
            match = pattern.match(row.content or "")
            if not match:
                continue
            origin = match.group(1)
            payload = {}
            if row.payload:
                try:
                    payload = json.loads(row.payload) or {}
                except (TypeError, ValueError):
                    payload = {}
            # id 未知的那批(工具当时取不到自己的会话)只剥前缀,不编一个来源出来。
            if origin != "(未知)":
                payload["from_agent_session"] = origin
            conn.execute(
                text("UPDATE agent_messages SET content=:c, payload=:p WHERE id=:i"),
                {"c": row.content[match.end():], "p": json.dumps(payload, ensure_ascii=False), "i": row.id},
            )


def _migrate_agent_session_order() -> None:
    """删掉 agent_sessions.sort_order —— 对话不再支持手动拖排序。

    这一列曾经存"手动拖出来的位次",列表按 (sort_order, updated_at desc) 取。拖排序这个能力
    去掉之后它就没有读者了,顺序回落到纯粹的「最近更新在前」;留着一个没人读的列,下次有人看到
    它只会去猜它还有没有用。

    SQLite 从 3.35 起支持 DROP COLUMN;删不掉就跳过 —— 一个没人读的列不影响任何行为(同
    provider_profiles 那几处的取舍)。
    """
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    if "sort_order" not in {c["name"] for c in inspector.get_columns("agent_sessions")}:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agent_sessions DROP COLUMN sort_order"))
    except Exception:  # noqa: BLE001 —— 老 SQLite 不支持,留着无害
        pass


def _migrate_agent_session_plan() -> None:
    """加列迁移:agent_sessions 增加 plan(任务计划)。老会话留 NULL = 还没有计划。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    if "plan" in {col["name"] for col in inspector.get_columns("agent_sessions")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN plan JSON"))


def _backfill_provider_models() -> None:
    """把「一档案一模型」的老数据搬成模型行。

    每个已有档案生成一行 provider_models:model_id 取它的 default_model,能力取档案上的覆盖
    (为空则留空列表,由后续解析回落 vendor 预设,语义一致)。迁移后用户看到的是"连接展开后
    有一个模型",一比一,没有任何东西消失。

    只在表为空时跑一次 —— 这是一次性的形状迁移,不是每次启动的同步。default_model 为空的
    档案不生成行:凭空造一个空模型只会让选择器里多出一个选不了的条目。

    **用裸 SQL 而不是 ORM 构造**,与本文件其它回填一致:迁移不属于任何领域,直接 new 领域
    模型会绕过归属约束(见 domain/ownership.py 与数据归属棘轮测试)。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_models" not in tables or "provider_profiles" not in tables:
        return
    # 只有**老库**才有 default_model 这列可读。新库由 create_all 直接建成没有它的形状,
    # 此时无从回填也无需回填 —— 不加这道判断,全新安装会在启动时直接崩在这条 SELECT 上。
    if "default_model" not in {col["name"] for col in inspector.get_columns("provider_profiles")}:
        return
    from app.db.models import new_id

    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM provider_models LIMIT 1")).first() is not None:
            return
        rows = conn.execute(
            text("SELECT id, default_model, capability_ids FROM provider_profiles WHERE default_model != ''")
        ).fetchall()
        for row in rows:
            capabilities = row[2] if isinstance(row[2], str) else json.dumps(row[2] or [], ensure_ascii=False)
            conn.execute(
                text(
                    "INSERT INTO provider_models "
                    "(id, provider_profile_id, model_id, display_name, capability_ids, enabled, source, created_at, updated_at) "
                    "VALUES (:id, :pid, :model, '', :caps, 1, 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": new_id(), "pid": row[0], "model": row[1], "caps": capabilities},
            )


def _migrate_provider_default_model_fk() -> None:
    """provider_defaults 增加 provider_model_id 并回填。

    老行存的是 (provider_profile_id, model) 这一对字符串 —— 行为一致,但没法引用、没法查询
    "哪一行是 image 的默认"。回填时按这对去 provider_models 里找对应行;找不到就留空,由
    resolve_default 退回"该能力下第一个可用模型",不会变成未配置。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "provider_defaults" not in tables or "provider_models" not in tables:
        return
    columns = {col["name"] for col in inspector.get_columns("provider_defaults")}
    with engine.begin() as conn:
        if "provider_model_id" not in columns:
            conn.execute(text("ALTER TABLE provider_defaults ADD COLUMN provider_model_id VARCHAR(64)"))
        if "provider_profile_id" in columns and "model" in columns:
            conn.execute(
                text(
                    "UPDATE provider_defaults SET provider_model_id = ("
                    "  SELECT pm.id FROM provider_models pm"
                    "  WHERE pm.provider_profile_id = provider_defaults.provider_profile_id"
                    "    AND pm.model_id = provider_defaults.model"
                    ") WHERE provider_model_id IS NULL"
                )
            )
            # 搬完就删:同一件事留两份,总有一份会漂移成错的。
            for legacy in ("provider_profile_id", "model"):
                conn.execute(text(f"ALTER TABLE provider_defaults DROP COLUMN {legacy}"))


def _drop_legacy_profile_columns() -> None:
    """删掉 provider_profiles 上退役的 default_model / capability_ids。

    两者都是"一档案一模型"时代的字段:default_model 不区分能力(对话档案的默认模型被拿去当
    生图模型用过),capability_ids 挂在连接上导致同一个端点只能二选一。能力与模型现在都在
    provider_models 行上,读取点已全部切走(见 domain/provider_models)。

    SQLite 从 3.35 起支持 DROP COLUMN;删不掉就跳过 —— 留着一个没人读的列不影响任何行为,
    而在启动路径上抛异常会让应用起不来。
    """
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    for name in ("default_model", "capability_ids", "model_overrides"):
        if name not in columns:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE provider_profiles DROP COLUMN {name}"))
        except Exception:  # noqa: BLE001 — 老版本 SQLite 不支持;留着无害
            logger.info("provider_profiles.%s 未能删除(SQLite 版本不支持 DROP COLUMN),留着无害", name)


def _migrate_job_parent() -> None:
    """加列迁移:jobs 增加 parent_job_id —— 工作流派生的子任务归到父工作流下,
    任务中心不再把子任务与父工作流平铺成两行。老行留 NULL 即顶层任务,语义正确。"""
    inspector = inspect(engine)
    if "jobs" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    if "parent_job_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN parent_job_id VARCHAR(64)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_parent_job_id ON jobs (parent_job_id)"))


def _migrate_browser_pool() -> None:
    """浏览器池:browser_sessions / publish_accounts 增加 profile_id(加列,保留既有数据)。
    browser_profiles 表本身由 create_all 建;发布账号→档案的回填在 create_all 之后跑
    (见 _backfill_browser_pool),那时表才存在。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "browser_sessions" in tables:
            if "profile_id" not in {c["name"] for c in inspector.get_columns("browser_sessions")}:
                conn.execute(text("ALTER TABLE browser_sessions ADD COLUMN profile_id VARCHAR(64)"))
        if "publish_accounts" in tables:
            if "profile_id" not in {c["name"] for c in inspector.get_columns("publish_accounts")}:
                conn.execute(text("ALTER TABLE publish_accounts ADD COLUMN profile_id VARCHAR(64)"))


def _backfill_browser_pool() -> None:
    """给还没挂档案的发布账号,按其分区 persist:<prefix>-<id> 建一个 browser_profiles 档案并
    回填 profile_id。组合(不合并):发布账号表保留,只多一个指针。幂等——只处理 profile_id 为空的
    账号。分区与 Electron 的约定一致 → 打开同一分区,发布登录态不丢。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "publish_accounts" not in tables or "browser_profiles" not in tables:
        return
    from app.db.models import new_id

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, workspace_id, name, proxy, enabled FROM publish_accounts WHERE profile_id IS NULL")
        ).fetchall()
        for acc in rows:
            pid = new_id()
            conn.execute(
                text(
                    'INSERT INTO browser_profiles (id, workspace_id, name, "partition", proxy, enabled, created_at, updated_at) '
                    "VALUES (:id, :ws, :name, :part, :proxy, :enabled, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": pid, "ws": acc.workspace_id, "name": acc.name, "part": f"persist:{PARTITION_PREFIX}-{acc.id}", "proxy": acc.proxy, "enabled": acc.enabled},
            )
            conn.execute(
                text("UPDATE publish_accounts SET profile_id = :pid WHERE id = :aid"),
                {"pid": pid, "aid": acc.id},
            )


def _migrate_drop_local_publish_accounts() -> None:
    """清掉 platform 为 folder / webhook 的「发布账号」及其空壳浏览器档案。

    这两个从来不是账号:没有登录身份、没有平台、没有风控,却因为 create_account 无条件建档,
    每存在一个就在浏览器池里留一个永远不会有登录态的空壳,还占一个永远不会被使用的 Chromium
    分区名。它们代表的能力(拷到目录 / POST 给外部自动化)已从产品中移除,所以这里直接清理,
    而不是搬到别处。

    幂等:匹配不到就什么都不做,可反复跑。
    """
    inspector = inspect(engine)
    if "publish_accounts" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, profile_id FROM publish_accounts WHERE platform IN ('folder', 'webhook')")
        ).mappings().all()
        if not rows:
            return
        for row in rows:
            if row["profile_id"]:
                conn.execute(text("DELETE FROM browser_profiles WHERE id = :pid"), {"pid": row["profile_id"]})
        conn.execute(text("DELETE FROM publish_accounts WHERE platform IN ('folder', 'webhook')"))
        logger.info("清理 %d 个 folder/webhook 发布账号及其空壳浏览器档案", len(rows))


def _rewrite_scene_shots_as_cameras(content: dict) -> bool:
    """把一份场景内容里的 `shots[].frames` 搬成相机物体的 `track`。改了返回 True。

    每个镜头长出一台同名的相机物体:静态位置取第一帧(没有轨的时候按它渲),`track` 就是原来
    那串 frames。镜头只留 `camera_id`。
    """
    from uuid import uuid4

    shots = content.get("shots")
    objects = content.get("objects")
    if not isinstance(shots, list) or not isinstance(objects, list):
        return False
    if not any(isinstance(shot, dict) and "frames" in shot for shot in shots):
        return False
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        frames = shot.pop("frames", None) or [{}]
        first = frames[0] if isinstance(frames[0], dict) else {}
        camera_id = uuid4().hex
        objects.append({
            "id": camera_id,
            "name": shot.get("name") or "机位",
            "kind": "camera",
            "position": first.get("position", [8, 5, 8]),
            "target": first.get("target", [0, 1, 0]),
            "fov": first.get("fov", 45),
            # 单帧的镜头是"固定机位":没有运动就不必留一条轨,静态位置已经说完了。
            "track": frames if len(frames) > 1 else [],
        })
        shot["camera_id"] = camera_id
    return True


def _migrate_scene_cameras_become_objects() -> None:
    """相机从「镜头里的一串关键帧」变成**场景里的物体**。

    此前 `shots` 和 `objects` 是两个平行数组,而整份内容里唯一带 time 的字段是
    `shots[].frames[].time` —— 于是"随时间变化"只有相机享受得到,相机自己又不是物体:
    在视口里选不中、拖不动、不能编组。见 docs/design/scene-time-and-cameras.md。

    **历史版本的快照也要一起改写。** 它们平时是原样返回的(不过校验),但"恢复某个版本"
    会把快照送回保存那条路 —— 不改写的话,升级之后所有旧版本都恢复不了,而报错会出现在
    很远的地方(一次 422,说的是 shots 缺 camera_id)。

    读取代码里不保留"老形状"这条分支(ADR-0006):迁移跑完,`shots[].frames` 就不存在了。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "scenes_3d" not in tables:
        return
    scenes = 0
    with engine.begin() as conn:
        for scene_id, raw in conn.execute(text("SELECT id, content FROM scenes_3d")).fetchall():
            try:
                content = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(content, dict) or not _rewrite_scene_shots_as_cameras(content):
                continue
            conn.execute(text("UPDATE scenes_3d SET content = :c WHERE id = :i"),
                         {"c": json.dumps(content, ensure_ascii=False), "i": scene_id})
            scenes += 1
        if "scene_3d_revisions" in tables:
            rows = conn.execute(text("SELECT scene_id, revision, snapshot FROM scene_3d_revisions")).fetchall()
            for scene_id, revision, raw in rows:
                try:
                    snapshot = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    continue
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
                    continue
                if not _rewrite_scene_shots_as_cameras(snapshot["content"]):
                    continue
                conn.execute(
                    text("UPDATE scene_3d_revisions SET snapshot = :s WHERE scene_id = :i AND revision = :r"),
                    {"s": json.dumps(snapshot, ensure_ascii=False), "i": scene_id, "r": revision})
    if scenes:
        logger.info("把 %d 个 3D 场景的镜头改写成了相机物体", scenes)


def _migrate_scene_models_to_disk() -> None:
    """把 3D 模型的字节从 `scene_3d_models.data` 挪到磁盘。

    留在库里的代价是实测出来的:一份 100 MB 的模型进出一次约 400 MB 峰值 RSS、300 MB 的约
    1.6 GB —— 字节要经过 Python bytes、sqlite3 绑定、页缓存、再读回,每一步一份。而下载那条
    此前是 `Response(model.data)`,整份进内存、**每个并发请求各付一次**。

    **一行一行搬**,不要 `SELECT id, data FROM …` 一次拿完:那等于把所有模型同时读进内存,
    正是这次要消除的那个毛病。峰值因此只被最大的那一份模型限制住。

    文件落在 `media/scene-models/<workspace>/<scene>/<model>.<fmt>` —— 在 media 下面是因为
    备份打包的正是它(BACKUP_DIRECTORIES),另起顶层目录会让备份悄悄不含 3D 模型。

    搬完才 DROP 那一列:中途失败的话,下次启动重跑,已经写好的文件被原样覆盖(内容一样),
    没有半个状态。
    """
    #: 当年那一版的目录形状,**照抄在这里**:后来模型改归工作区、目录不再按场景分
    #: (见 _migrate_scene_models_to_workspace),而迁移写的是它那个年代的布局 ——
    #: 跟着 paths.py 变的话,这一步会把老数据搬到一个下一步不认识的地方。
    def legacy_slot(workspace_id: str, scene_id: str) -> Path:
        return settings.media_dir / "scene-models" / workspace_id / scene_id

    inspector = inspect(engine)
    if "scene_3d_models" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("scene_3d_models")}
    if "data" not in columns:
        return
    with engine.begin() as conn:
        for name, ddl in (("file_key", "TEXT NOT NULL DEFAULT ''"), ("size", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                conn.execute(text(f"ALTER TABLE scene_3d_models ADD COLUMN {name} {ddl}"))

    rows = [
        (row[0], row[1], row[2])
        for row in engine.connect().execute(text(
            "SELECT m.id, m.format, s.workspace_id || '/' || s.id FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        ))
    ]
    moved = 0
    for model_id, fmt, location in rows:
        workspace_id, _, scene_id = location.partition("/")
        with engine.connect() as conn:   # 一次一份,避免把所有模型同时读进内存
            data = conn.execute(text("SELECT data FROM scene_3d_models WHERE id = :id"), {"id": model_id}).scalar()
        if data is None:
            continue
        directory = legacy_slot(workspace_id, scene_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{model_id}.{fmt}").write_bytes(data)
        key = str(Path("media") / "scene-models" / workspace_id / scene_id / f"{model_id}.{fmt}")
        with engine.begin() as conn:
            conn.execute(text("UPDATE scene_3d_models SET file_key = :key, size = :size WHERE id = :id"),
                         {"key": key, "size": len(data), "id": model_id})
        moved += 1
        del data
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE scene_3d_models DROP COLUMN data"))
    if moved:
        logger.info("把 %d 份 3D 模型的字节从数据库挪到了 %s", moved, settings.media_dir / "scene-models")


def _migrate_scene_models_to_workspace() -> None:
    """3D 模型从「归场景」改成「归工作区」:表上的 scene_id → workspace_id,文件从
    `media/scene-models/<ws>/<scene>/` 提到 `media/scene-models/<ws>/`。

    为什么要改:模型挂在场景下面时,同一件道具在每个场景里都得重新导一份,而**工作流每跑
    一次都新建一个场景** —— 于是在 Blender 里建好的产品模型永远进不了自动成片的布景:那个
    场景还不存在,模型就没处挂。工作区才是它真正的边界(和素材、字体、LUT 一样)。

    顺序是**先搬文件再换表**:文件搬到一半崩了,下次启动重跑,已经在新位置的那些按
    "在新位置就跳过"处理,没有半个状态;表还没换,所以旧的 file_key 仍然指得到东西。

    scene 已经不在了的孤儿行跟着丢掉 —— 它们的场景没了,没有任何入口能再看到它们。
    """
    inspector = inspect(engine)
    if "scene_3d_models" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("scene_3d_models")}
    if "scene_id" not in columns:   # 已经搬过了
        return

    with engine.connect() as conn:
        rows = list(conn.execute(text(
            "SELECT m.id, m.format, m.file_key, s.workspace_id FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        )))
    keys: dict[str, str] = {}
    for model_id, fmt, file_key, workspace_id in rows:
        target_dir = settings.media_dir / "scene-models" / workspace_id
        target = target_dir / f"{model_id}.{fmt}"
        keys[model_id] = str(Path("media") / "scene-models" / workspace_id / f"{model_id}.{fmt}")
        if target.is_file():
            continue
        source = settings.data_dir / file_key if file_key else None
        if source is None or not source.is_file():
            continue   # 文件本来就不在了;行照样搬,界面上会说"模型文件已不在,请重新导入"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE scene_3d_models_new ("
            " id VARCHAR(64) NOT NULL PRIMARY KEY,"
            " workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,"
            " name VARCHAR(160) NOT NULL,"
            " format VARCHAR(10) NOT NULL,"
            " file_key VARCHAR(512) NOT NULL DEFAULT '',"
            " size INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "INSERT INTO scene_3d_models_new (id, workspace_id, name, format, file_key, size) "
            "SELECT m.id, s.workspace_id, m.name, m.format, m.file_key, m.size FROM scene_3d_models m "
            "JOIN scenes_3d s ON s.id = m.scene_id"
        ))
        for model_id, key in keys.items():
            conn.execute(text("UPDATE scene_3d_models_new SET file_key = :key WHERE id = :id"),
                         {"key": key, "id": model_id})
        conn.execute(text("DROP TABLE scene_3d_models"))
        conn.execute(text("ALTER TABLE scene_3d_models_new RENAME TO scene_3d_models"))
        conn.execute(text("CREATE INDEX ix_scene_3d_models_workspace_id ON scene_3d_models (workspace_id)"))

    # 空下来的按场景分的目录收掉,免得备份里留着一堆空壳。
    root = settings.media_dir / "scene-models"
    if root.is_dir():
        for workspace in root.iterdir():
            if not workspace.is_dir():
                continue
            for leftover in workspace.iterdir():
                if leftover.is_dir() and not any(leftover.iterdir()):
                    leftover.rmdir()
    if rows:
        logger.info("把 %d 份 3D 模型从「归场景」改成了「归工作区」", len(rows))


def init_db() -> None:
    """Prepare storage, then execute the validated startup migration plan."""

    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    plan = migration_plan()
    # **先问要不要拍快照,再跑。** 判据是"有没有待跑的一次性迁移",不是版本号相不相等 ——
    # 后者要人记得改一个常量,而它整整十四个迁移没被改过(见 db/safety 顶上那段)。
    snapshot_before_upgrade(
        settings.db_path, target_version=DATABASE_SCHEMA_VERSION, pending=len(plan.pending())
    )
    plan.run()
    mark_database_version(settings.db_path, DATABASE_SCHEMA_VERSION)


def _migrate_board_canvas_state() -> None:
    """Move pre-``run`` board state into the current node shape.

    Board JSON is owned data, so it is upgraded in place rather than forcing every current reader
    to understand top-level ``job_id``/``error`` forever. This historical transform intentionally
    carries its own old-shape rules instead of depending on the evolving domain validator.
    """
    inspector = inspect(engine)
    if "boards" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, canvas FROM boards")).fetchall()
        for row in rows:
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict):
                    continue
                if item.get("run") is None:
                    job_id = item.get("job_id")
                    error = item.get("error")
                    if isinstance(job_id, str) and job_id.strip():
                        item["run"] = {"status": "running", "job_id": job_id.strip()}
                        touched = True
                    elif isinstance(error, str):
                        run: dict[str, str] = {"status": "failed"}
                        if error.strip():
                            run["error"] = error.strip()[:300]
                        item["run"] = run
                        touched = True
                if item.get("form") is None and item.get("kind") in {"image", "video", "audio"}:
                    prompt = item.get("text")
                    if isinstance(prompt, str) and prompt:
                        item["form"] = {"prompt": prompt}
                        touched = True
                for legacy_key in ("job_id", "error"):
                    if legacy_key in item:
                        item.pop(legacy_key)
                        touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_trim_slots_record_their_source() -> None:
    """画板上截出来的那一格,把「截的是哪一份、哪一段」记到表单的 `trim` 上。

    此前截取只在表单里记了 `parameters: {start, end, mute}`,没记截的是哪份素材。截挂了的那一格
    于是和一格生成挂了的视频/音频长得一样:选中它挂的是生成面板,而要重截也不知道截的是哪一份。
    现在截取写的是 `form.trim = {asset_id, start, end, mute}`(见 boards.actions.trim_on_board)。

    **来历按任务认,不按参数长相猜**:截取任务的 payload 里记着原素材(`asset_id`)和回执落在哪张板
    的哪一格。找得到那一格、它表单上正是这次截取的范围,才改;任务已经被清掉的,没法知道截的是
    哪一份,原样留着(那几格要么已经有产出,要么本来就只剩一个空槽)。
    """
    tables = set(inspect(engine).get_table_names())
    if "boards" not in tables or "jobs" not in tables:
        return

    def loads(raw: Any) -> Any:
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None

    with engine.begin() as conn:
        sources: dict[tuple[str, str], str] = {}
        for row in conn.execute(text("SELECT payload FROM jobs WHERE kind = 'trim'")).fetchall():
            payload = loads(row[0])
            receipt = payload.get("receipt") if isinstance(payload, dict) else None
            if not isinstance(receipt, dict) or receipt.get("kind") != "board_item":
                continue
            asset_id = payload.get("asset_id")
            if isinstance(asset_id, str) and asset_id and receipt.get("board_id") and receipt.get("item_id"):
                sources[(str(receipt["board_id"]), str(receipt["item_id"]))] = asset_id
        boards = {board_id for board_id, _ in sources}
        for board_id in boards:
            row = conn.execute(text("SELECT canvas FROM boards WHERE id = :id"), {"id": board_id}).fetchone()
            canvas = loads(row[0]) if row else None
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict):
                    continue
                asset_id = sources.get((board_id, str(item.get("id"))))
                form = item.get("form")
                parameters = form.get("parameters") if isinstance(form, dict) else None
                if not asset_id or not isinstance(parameters, dict) or "trim" in form:
                    continue
                start, end = parameters.get("start"), parameters.get("end")
                if not all(isinstance(one, (int, float)) and not isinstance(one, bool) for one in (start, end)):
                    continue
                rest = {key: value for key, value in parameters.items() if key not in ("start", "end", "mute")}
                trimmed = {key: value for key, value in form.items() if key != "parameters"}
                if rest:
                    trimmed["parameters"] = rest
                trimmed["trim"] = {
                    "asset_id": asset_id,
                    "start": float(start),
                    "end": float(end),
                    "mute": parameters.get("mute") is True,
                }
                item["form"] = trimmed
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": board_id},
                )


def _migrate_board_sources_record_their_upstream() -> None:
    """表单槽位里顺着连线挂上的那几份素材,记下是从哪一格来的(`from`)。

    「哪一份是从上游来的」此前只活在前端:每次画布变化拿「上一次每一格从连线拿到什么」去比,
    断开的那份才摘掉。服务端不知道这件事 —— 智能体删掉上游那一格、删掉一根线,下游表单里那份
    引用原样留着。现在出处记在那一份自己身上,由服务端一处判定(见 boards.canvas._drop_detached_bindings)。

    这里按**迁移前前端的口径**补:下游某一份的素材,正是一根连进来的线另一端那一格给出的素材
    (图片/视频/音频/3D 场景那一格上的 asset_id),就记成从那一格来的 —— 和前端当时把它当成
    「从连线来」的判据相同。连不上的照旧当手动挂的。这份口径是迁移那一刻的快照,不跟着领域层走。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    offers = {"image", "video", "audio", "scene"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = [item for item in canvas["items"] if isinstance(item, dict)]
            by_id = {str(item.get("id")): item for item in items}
            #: 每一格顺着线能拿到的素材 → 给出它的那一格(按线的先后,先连的算)。
            upstream: dict[str, dict[str, str]] = {}
            for edge in canvas.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                source = by_id.get(str(edge.get("source")))
                if not source or source.get("kind") not in offers or not source.get("asset_id"):
                    continue
                upstream.setdefault(str(edge.get("target")), {}).setdefault(str(source["asset_id"]), str(source["id"]))
            touched = False
            for item in items:
                form = item.get("form")
                sources = form.get("source_assets") if isinstance(form, dict) else None
                fed = upstream.get(str(item.get("id")))
                if not isinstance(sources, list) or not fed:
                    continue
                for one in sources:
                    if isinstance(one, dict) and "from" not in one and str(one.get("asset_id")) in fed:
                        one["from"] = fed[str(one["asset_id"])]
                        touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_frame_names_become_titles() -> None:
    """分组框的名字从 `text` 搬到每一格都有的 `title`。

    此前只有分组框能起名,名字借住在 `text` 里;现在每一格都能起名,名字统一放在 `title`
    (见 boards.canvas.normalize_canvas)。搬过去时按 title 的口径收拾:空白收成单个空格、
    首尾去掉、超过 120 字截断(这份口径是迁移那一刻的快照,不跟着领域层走)——
    不截的话,这张板下一次保存会被「名字太长」整个拒掉。搬空的(只有空白)就是没起名。
    分组框身上不再留 `text`:它没有正文。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "frame" or "text" not in item:
                    continue
                name = item.pop("text")
                touched = True
                if isinstance(name, str) and not item.get("title"):
                    title = " ".join(name.split())[:120]
                    if title:
                        item["title"] = title
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_forms_name_their_producer() -> None:
    """画板上每一格的表单写明是哪个产出者的(`form.producer`,ADR 0021)。

    此前挂哪块面板由前端按种类猜(boardItemState.composerFor):便签挂写字;图片/视频/音频
    还没产出时,表单上记着 trim 的挂截取,否则音频挂念字、图片视频挂生成。现在产出者是一格自己的
    事实,面板照 `form.producer` 挂,推断删掉 —— 所以已有的格子要按**当时的那条推断**写上
    (这份口径是迁移那一刻的快照,不跟着领域层走):

    · 有表单的便签/图片/视频/音频:note → write;表单上有 trim → trim;audio → speak;
      image/video → generate;
    · 没表单、但此前会挂面板的(便签;还没产出的图片/视频/音频):补一张只写着产出者的表单。

    已经写了 producer 的不动(幂等)。`producer` 排在表单最后,和服务端摆占位时写的位置一致。

    **改到的板版本号 +1**:升级那一刻还开着这张板的客户端手里是没写产出者的旧快照,它存回来
    该撞 409、拉最新的那份,而不是把刚写上的产出者整张盖掉。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    by_kind = {"note": "write", "audio": "speak", "image": "generate", "video": "generate"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") not in by_kind:
                    continue
                kind = item["kind"]
                form = item.get("form")
                if isinstance(form, dict):
                    if "producer" in form:
                        continue
                    producer = by_kind[kind] if kind == "note" or form.get("trim") is None else "trim"
                    item["form"] = {**form, "producer": producer}
                    touched = True
                elif form is None and (kind == "note" or not item.get("asset_id")):
                    item["form"] = {"producer": by_kind[kind]}
                    touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_empty_slots_name_their_producer() -> None:
    """升级之后新建的、还没写明产出者的空槽,补上产出者。

    `migrate-board-forms-name-their-producer` 只跑过一次;它之后,3D 场景页「拿去生成」建的画板自己拼格子,
    生成那一格带着提示词和参考却没写 `form.producer` —— 选中了什么面板都不挂。现在画布的每一次写入都由
    normalize_canvas 补齐(boards.producer_ids.missing_slot_producer),可已经存进库、之后再没存过的板不会
    经过它,所以这里按**同一条规则**补一遍(这份口径是迁移那一刻的快照,不跟着领域层走):

    · 便签、以及还没有产出(没有 asset_id)的图片/视频/音频,表单上没写 producer 的:
      note → write、audio → speak、image/video → generate(截取那一格一向由服务端写明 trim,不在此列);
    · 没有表单的就补一张只写着产出者的表单。

    已经写了 producer 的、有了产出的媒体格不动(幂等)。`producer` 排在表单最后,和 normalize 补的位置一致。
    **改到的板版本号 +1**:升级那一刻还开着这张板的客户端手里是旧快照,存回来该撞 409、拉最新的那份。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    by_kind = {"note": "write", "audio": "speak", "image": "generate", "video": "generate"}
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") not in by_kind:
                    continue
                kind = item["kind"]
                if kind != "note" and item.get("asset_id"):
                    continue
                form = item.get("form")
                if form is None:
                    form = {}
                if not isinstance(form, dict) or form.get("producer") is not None:
                    continue
                item["form"] = {**form, "producer": by_kind[kind]}
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_wiring_tools_become_notes() -> None:
    """画板上跑流程控制 / 数据处理节点的工具格,改成一张写明「这一步归工作流」的便签(ADR 0021 修订)。

    画板上只放内容变换:调用工作流、HTTP 请求、文本模板、JSON 提取、文本处理、检索笔记不再是
    画板上的工具(它们撤掉了 `surfaces: ["board"]`)。已经摆在画板上的这几种工具格,跑是跑不了了
    (注册表里没有它们,运行时回 boardErr_nodeNotOnBoard),留着就是一格永远「用不了」的死格子。

    **改成便签,不删**:
    · 同一个 id、同一个位置和大小、起过的名字照留 —— 连进来的线(上游 → 它)和它连出去的线
      (它 → 跑出来的那几格产出)都还连得上,不留一根悬空的线;便签能当上游,也能被连;
    · 它跑出来的产出(右边那几格)本来就是独立的格子,一格不动;
    · 正文写明这一步挪去了工作流,并把原来的设置(节点配置)照原样附在后面 —— 模板里写的字、
      请求的地址、检索的关键词不丢,要在工作流里重搭时照着抄。绑定(接的是哪几格上游)由保留的
      连线看得出来,不另记。
    · 挂上便签的产出者(`write`),和手放的便签一样能让 AI 改写。

    文字用部署缺省的中文(迁移时没有请求,也就没有读的人的语言,见 core/i18n 开头那段);节点名
    和那句话是迁移那一刻的快照,不跟着领域层走。插件工具不在这里:它合不合格随清单变(连接、
    ComfyUI 上的工作流),运行时由注册表说清楚为什么(boardErr_toolNotOnBoard)。

    改到的板版本号 +1:升级那一刻还开着这张板的客户端,手里的旧快照要撞 409,不能把工具格存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    labels = {
        "node:call_workflow": "调用工作流",
        "node:http_request": "HTTP 请求",
        "node:template": "文本模板",
        "node:json_extract": "JSON 提取",
        "node:text_transform": "文本处理",
        "node:note_search": "检索笔记",
    }
    limit = 20_000
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            touched = False
            for index, item in enumerate(canvas["items"]):
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                label = labels.get(str(form.get("producer") or ""))
                if label is None:
                    continue
                body = f"「{label}」这一步已经不在画板上了:画板只放把内容变成新内容的工具,流程控制和数据处理归工作流 —— 需要的话在工作流里用它。"
                config = form.get("config")
                if isinstance(config, dict) and config:
                    body += "\n\n原来的设置:\n" + json.dumps(config, ensure_ascii=False, indent=2)
                if len(body) > limit:
                    body = body[: limit - 1] + "…"
                note = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
                canvas["items"][index] = {**note, "kind": "note", "text": body, "form": {"producer": "write"}}
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_scene_render_shot_is_picked() -> None:
    """画板上「渲染白模参考」的镜头和项目不再接便签 / 文档,改成从清单里挑。

    这两格此前是随手写字的模板字段,于是能接便签和文档的字(画板的 binding_sink 按「能写字」判)——
    必填的镜头还会**默认接上第一张连进来的便签**。现在它们声明了选项来源(场景的镜头、工作区的
    项目),不再是写字的地方:存着的这种绑定运行时一律不认(tools.resolve_bindings 跳过接不了的字段),
    面板上却还显示成「已接上游」,点开是一排接不上的空芯片。

    · 绑定摘掉(只摘这两格,别的字段、连线一概不动);
    · 镜头绑的是便签、表单里又没手填过镜头的,把便签上那段字(去掉两头空白)填进表单 ——
      那正是上次运行时它取到的值,摘了绑定照样渲同一个镜头。文档的正文当不了镜头 id,不搬;
      项目也不搬(接便签的项目本来就填不对,留空 = 不归档)。

    改到的板版本号 +1:升级那一刻还开着这张板的客户端要撞 409,不能把旧绑定存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    fields = ("shot_id", "project_id")
    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = {str(item.get("id")): item for item in canvas["items"] if isinstance(item, dict)}
            touched = False
            for item in canvas["items"]:
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form")
                if not isinstance(form, dict) or form.get("producer") != "node:scene_render":
                    continue
                bindings = form.get("bindings")
                if not isinstance(bindings, dict) or not any(key in bindings for key in fields):
                    continue
                config = dict(form.get("config")) if isinstance(form.get("config"), dict) else {}
                refs = bindings.get("shot_id") if isinstance(bindings.get("shot_id"), list) else []
                if not str(config.get("shot_id") or "").strip():
                    for ref in refs:
                        source = items.get(str(ref.get("from") if isinstance(ref, dict) else ""))
                        written = str((source or {}).get("text") or "").strip() if (source or {}).get("kind") == "note" else ""
                        if written:
                            config["shot_id"] = written
                            break
                item["form"] = {
                    **form,
                    "config": config,
                    "bindings": {key: value for key, value in bindings.items() if key not in fields},
                }
                touched = True
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_scene_cells_render_themselves() -> None:
    """画板上渲白模改成 3D 场景格自己做的事,「渲染白模参考」工具格撤掉。

    此前一格场景格(引用一个场景、导出缩略图)旁边还要放一格工具格(`node:scene_render`),在工具格上挑
    场景、挑镜头、挑渲什么 —— 同一件事分成两半摆在桌上。现在场景格挂内置产出者 `scene_render`
    (和视频 / 音频格上的「剪一段」同一个样子),工作流节点撤掉了 `surfaces: ["board"]`。存着的画布:

    · **每一格场景格写明产出者** `scene_render`(面板照它挂;新放下的场景格由 normalize 补,见
      producer_ids.SLOT_PRODUCERS)。
    · 工具格的场景**接的是**(绑定、且那根线还在)或**填的是**这张板上某一格场景格的场景:它的设置(镜头、
      渲什么、归档项目;`{{…}}` 引用、不在选项里的值不搬)写进那一格场景格的 `form.config`,工具格删掉。
      它跑出来的产出一格不动,**连向产出的线改从场景格连出**(同一对已经连着就不再多一根);连进工具格的线
      随它去掉。一格场景格被好几格工具格接着时,第一格的设置搬过去;后面设置不同的那几格照下一条改成便签
      (它们的镜头选择不能悄悄丢)。
    · 其余(没接、没填,或填的场景这张板上没有格子):**改成一张便签**,同一个 id、位置、大小、名字,正文
      写明渲染挪到了场景格上并附上原来的设置 —— 和 `migrate-board-wiring-tools-become-notes` 同一种做法:
      进出它的线都还连得上,产出不动。

    文字用部署缺省的中文(迁移时没有读的人的语言)。改到的板版本号 +1:升级那一刻还开着这张板的客户端
    手里的旧快照要撞 409,不能把工具格存回来。
    """
    if "boards" not in set(inspect(engine).get_table_names()):
        return
    fields = ("shot_id", "render", "project_id")
    renders = ("stills", "video", "both")
    limit = 20_000

    def settings_of(config: dict) -> dict:
        out = {}
        for key in fields:
            value = config.get(key)
            if not isinstance(value, str) or not value.strip() or "{{" in value:
                continue
            if key == "render" and value.strip() not in renders:
                continue
            out[key] = value.strip()
        return out

    def note_of(item: dict, config: dict) -> dict:
        body = ("「渲染白模参考」这一格不在画板上了:渲白模现在是 3D 场景格自己会做的事 —— 把场景放上画板,"
                "选中它,挑一个镜头就能渲出首尾帧或运镜视频。")
        if config:
            body += "\n\n原来的设置:\n" + json.dumps(config, ensure_ascii=False, indent=2)
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
        return {**kept, "kind": "note", "text": body, "form": {"producer": "write"}}

    with engine.begin() as conn:
        for row in conn.execute(text("SELECT id, canvas FROM boards")).fetchall():
            try:
                canvas = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                continue
            items = [item for item in canvas["items"] if isinstance(item, dict)]
            edges = [edge for edge in canvas.get("edges") or [] if isinstance(edge, dict)]
            by_id = {str(item.get("id")): item for item in items}
            wired = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
            scenes = [item for item in items if item.get("kind") == "scene"]
            touched = False

            for scene in scenes:
                form = scene.get("form") if isinstance(scene.get("form"), dict) else {}
                if not form.get("producer"):
                    scene["form"] = {**form, "producer": "scene_render"}
                    touched = True

            moved: dict[str, str] = {}
            filled: set[str] = set()
            for index, item in enumerate(canvas["items"]):
                if not isinstance(item, dict) or item.get("kind") != "action":
                    continue
                form = item.get("form") if isinstance(item.get("form"), dict) else {}
                if form.get("producer") != "node:scene_render":
                    continue
                touched = True
                item_id = str(item.get("id"))
                config = form.get("config") if isinstance(form.get("config"), dict) else {}
                bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
                host = None
                for ref in bindings.get("scene_id") if isinstance(bindings.get("scene_id"), list) else []:
                    source = str(ref.get("from") if isinstance(ref, dict) else "")
                    if (by_id.get(source) or {}).get("kind") == "scene" and (source, item_id) in wired:
                        host = by_id[source]
                        break
                wanted = config.get("scene_id")
                if host is None and isinstance(wanted, str) and wanted.strip():
                    host = next((one for one in scenes if one.get("scene_id") == wanted.strip()), None)
                settings = settings_of(config)
                if host is not None:
                    host_id = str(host.get("id"))
                    host_form = host.get("form") if isinstance(host.get("form"), dict) else {}
                    current = host_form.get("config") if isinstance(host_form.get("config"), dict) else {}
                    if host_id not in filled and not current:
                        rest = {key: value for key, value in host_form.items() if key not in ("config", "producer")}
                        host["form"] = {**rest, **({"config": settings} if settings else {}), "producer": "scene_render"}
                        filled.add(host_id)
                        moved[item_id] = host_id
                        continue
                    if settings == current or (not settings and not current):
                        moved[item_id] = host_id
                        continue
                canvas["items"][index] = note_of(item, config)

            if moved:
                taken = {str(edge.get("id")) for edge in edges}
                pairs = {(str(edge.get("source")), str(edge.get("target"))) for edge in edges}
                kept_edges = []
                for edge in edges:
                    source, target = str(edge.get("source")), str(edge.get("target"))
                    if target in moved:
                        continue
                    if source not in moved:
                        kept_edges.append(edge)
                        continue
                    host_id = moved[source]
                    if target == host_id or target in moved or (host_id, target) in pairs:
                        continue
                    edge_id = f"{host_id}->{target}"
                    suffix = 1
                    while edge_id in taken:
                        suffix += 1
                        edge_id = f"{host_id}->{target}-{suffix}"
                    taken.add(edge_id)
                    pairs.add((host_id, target))
                    kept_edges.append({**edge, "id": edge_id, "source": host_id})
                canvas["edges"] = kept_edges
                canvas["items"] = [item for item in canvas["items"]
                                   if not (isinstance(item, dict) and str(item.get("id")) in moved)]
            if touched:
                conn.execute(
                    text("UPDATE boards SET canvas = :canvas, revision = revision + 1 WHERE id = :id"),
                    {"canvas": json.dumps(canvas, ensure_ascii=False), "id": row[0]},
                )


def _migrate_board_revision() -> None:
    """Add the optimistic concurrency token to existing boards.

    ``create_all`` creates it for new databases but cannot alter an existing table. Existing
    projections all start at revision 1; the first accepted write advances them to 2.
    """

    inspector = inspect(engine)
    if "boards" not in set(inspector.get_table_names()):
        return
    if "revision" in {column["name"] for column in inspector.get_columns("boards")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE boards ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"))


def _migrate_confirmation_summary_i18n() -> None:
    """已装机的库补上 `tool_confirmations.summary_key` / `summary_params`。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。

    **存量卡不回填。** 它们的 `summary` 就是当时那句话,而当时那句话是中文写死的 —— 没有
    key 可以反推。出口见到 key 为空就原样返回它(和 `JobOut` 对老任务的处理一字不差:
    历史记录保持它当时的原话,而从此以后新写的都是 key)。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("tool_confirmations")}
    with engine.begin() as conn:
        if "summary_key" not in columns:
            conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN summary_key VARCHAR(80) NOT NULL DEFAULT ''"))
        if "summary_params" not in columns:
            conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN summary_params JSON NOT NULL DEFAULT '{}'"))


def _migrate_publish_task_claimed_by() -> None:
    """已装机的库补上 publish_tasks.claimed_by。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。
    """

    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("publish_tasks")}
    if "claimed_by" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN claimed_by VARCHAR(64) NOT NULL DEFAULT ''"))


def _migrate_publish_task_post() -> None:
    """已装机的库补上 publish_tasks.post(发出去的那条作品的平台 ID 与链接)。

    `create_all` 只建缺失的**表**,从不给已存在的表加列。老任务发的时候没记,这一列就是空 dict ——
    那些作品的 ID 当时没抓,事后补不出来,不假装有。
    """

    inspector = inspect(engine)
    if "publish_tasks" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("publish_tasks")}
    if "post" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN post JSON NOT NULL DEFAULT '{}'"))


def _migrate_agent_pending_view() -> None:
    """已装机的库补上 agent_sessions.pending_view。

    `create_all` 只建缺失的**表**,从不给已存在的表加列 —— 少了这一步,新装机一切正常,
    升级的机器上后端起不来(no such column)。
    """

    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("agent_sessions")}
    if "pending_view" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN pending_view VARCHAR(96) NOT NULL DEFAULT ''"))


def _migrate_comment_canvas_context() -> None:
    """Preserve spatial anchors and rich-text documents for existing comment tables."""

    inspector = inspect(engine)
    if "comments" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("comments")}
    with engine.begin() as conn:
        if "anchor" not in columns:
            conn.execute(text("ALTER TABLE comments ADD COLUMN anchor JSON NOT NULL DEFAULT '{}'"))
        if "body_document" not in columns:
            conn.execute(text("ALTER TABLE comments ADD COLUMN body_document JSON NOT NULL DEFAULT '{}'"))


def _backfill_activity_events() -> None:
    """Project existing actor-bearing history into the unified workspace activity stream.

    The source pair is unique, so startup remains idempotent. The original rows stay authoritative
    for workflow replay, sequence undo and job execution; ActivityEvent is their human-facing audit
    projection, not a replacement for domain history.
    """

    tables = set(inspect(engine).get_table_names())
    if "activity_events" not in tables:
        return
    with engine.begin() as conn:
        if {"workflows", "workflow_revisions"}.issubset(tables):
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), w.workspace_id, r.created_by,
                           'workflow.revision_created', 'workflow', r.workflow_id,
                           CASE WHEN r.source = 'restore' THEN '恢复了工作流版本' ELSE '保存了工作流版本' END,
                           json_object('revision', r.revision, 'source', r.source),
                           'workflow_revision', r.id, r.created_at
                    FROM workflow_revisions r JOIN workflows w ON w.id = r.workflow_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'workflow_revision' AND e.source_id = r.id
                    )
                    """
                )
            )
        if "sequence_operations" in tables:
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), o.workspace_id, o.actor_id,
                           'sequence.operation', 'sequence', o.sequence_id, '编辑了时间线',
                           json_object('kind', o.kind, 'revision_before', o.revision_before,
                                       'revision_after', o.revision_after),
                           'sequence_operation', o.id, o.created_at
                    FROM sequence_operations o
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'sequence_operation' AND e.source_id = o.id
                    )
                    """
                )
            )
        if "jobs" in tables:
            conn.execute(
                text(
                    """
                    INSERT INTO activity_events
                        (id, workspace_id, actor_id, action, subject_type, subject_id, summary,
                         payload, source_type, source_id, created_at)
                    SELECT lower(hex(randomblob(16))), j.workspace_id, j.created_by,
                           'job.created', 'job', j.id, '发起了任务',
                           json_object('kind', j.kind, 'status', j.status),
                           'job', j.id, j.created_at
                    FROM jobs j
                    WHERE NOT EXISTS (
                        SELECT 1 FROM activity_events e
                        WHERE e.source_type = 'job' AND e.source_id = j.id
                    )
                    """
                )
            )


def _migrate_shared_venvs() -> None:
    """一个引擎一个运行环境。分开之前那个共用 venv 搬到它实际服务的引擎名下 —— 不留兼容路径,
    因为"一个环境被两个引擎装东西"正是「装一边弄坏另一边」的机制本身。"""

    # **在函数里 import,不在模块顶层。** 这两个迁移动作住在被迁移的那一侧(venv 归运行时管),
    # 而 db 是比它们更底的一层 —— 顶层 import 会让"加载一个迁移模块"连带拉起半个应用
    # (实测:app.ai / app.ai.runtime / app.domain / app.domain.voices 全被带起来)。
    # 迁移只在 init_db 那一刻跑一次,它对上层的需要是**运行时的**,不该固化成加载时的绑定。
    from app.ai.runtime import asr_models, config as tts_config

    tts_config.migrate_shared_venv()
    asr_models.migrate_shared_venv()


def _migrate_thumbnails_keep_transparency() -> None:
    """缩略图从 JPEG 换成 WebP(JPEG 没有透明通道,透明 PNG 的缩略图四角发黑、边缘起毛)。

    逐个素材换掉旧文件;做法住在 media/thumbnails(同 _migrate_shared_venvs 的理由,函数内 import)。
    """
    from app.media.paths import resolve_key
    from app.media.thumbnails import migrate_jpeg_thumbnail

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT kind, file_key FROM assets WHERE file_key IS NOT NULL AND file_key != ''")).all()
    for kind, file_key in rows:
        source = resolve_key(file_key)
        migrate_jpeg_thumbnail(source, kind, source.parent)


def _migrate_mov_videos_become_mp4() -> None:
    """已经在库里的 .mov 视频原样换成 .mp4 容器(不重编码),与导入时的做法一致。

    为什么换见 media/probe.repackage_as_mp4:QuickTime 容器在界面里拖进度条会卡好几秒。
    文件换好了才改行;换好了但行还没改(上次中途断了)时,下次看到同名 .mp4 就只改行。
    """
    from app.media.paths import resolve_key
    from app.media.probe import REPACKAGED_SUFFIXES, repackage_as_mp4

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, original_filename, file_key FROM assets WHERE kind = 'video' AND file_key != ''")
        ).all()
    for asset_id, name, original, file_key in rows:
        key = Path(file_key)
        if key.suffix.lower() not in REPACKAGED_SUFFIXES:
            continue
        source = resolve_key(file_key)
        target = source.with_suffix(".mp4")
        if source.is_file() and repackage_as_mp4(source) is None:
            continue  # 编码放不进 mp4(ProRes 之类):留着 .mov
        if not target.is_file():
            continue
        renamed = str(Path(original or key.name).with_suffix(".mp4"))
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE assets SET file_key = :key, original_filename = :original, name = :name WHERE id = :id"),
                {
                    "key": str(key.with_suffix(".mp4")),
                    "original": renamed,
                    # 名字还是默认的文件名时一起换;用户改过的名字不动。
                    "name": renamed if name == original else name,
                    "id": asset_id,
                },
            )


def _migrate_frame_rate_is_not_a_time_base() -> None:
    """浏览器录的 webm 以毫秒计时,此前探测把 1000/1 当成了帧率(素材详情写着「1000fps」)。

    帧率超过 media/probe.MAX_PLAUSIBLE_FPS 的视频按现在的探测重算一遍;重算不出来就去掉这个值,
    界面上不显示比显示一个错的好。
    """
    from app.media.paths import resolve_key
    from app.media.probe import MAX_PLAUSIBLE_FPS, probe_media

    inspector = inspect(engine)
    if "assets" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, file_key, media_info FROM assets WHERE kind = 'video' AND file_key != ''")).all()
    for asset_id, file_key, raw in rows:
        info = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        fps = info.get("fps")
        if not isinstance(fps, (int, float)) or fps <= MAX_PLAUSIBLE_FPS:
            continue
        source = resolve_key(file_key)
        fixed = probe_media(source).get("fps") if source.is_file() else None
        if fixed is None:
            info.pop("fps", None)
        else:
            info["fps"] = fixed
        with engine.begin() as conn:
            conn.execute(text("UPDATE assets SET media_info = :info WHERE id = :id"),
                         {"info": json.dumps(info, ensure_ascii=False), "id": asset_id})


def _drop_venvs_built_on_another_python() -> None:
    """托管 venv 是用另一个次版本的解释器建的,就删掉,让引擎回到「未安装」。

    随包的解释器会随应用升级换次版本(这一次是 3.12 → 3.13),而 venv 不能跨次版本用 —— 留着它,
    引擎看起来「装好了」却一跑就炸。这是**对账**不是一次性迁移:下一次换次版本时同样的事会
    再发生,判据(venv 的版本 ≠ 现在建 venv 用的解释器的版本)也不随哪一次升级而变。
    """
    from app.ai.runtime import asr_models, config as tts_config, separation_models
    from app.core.interpreter import drop_venvs_built_on_another_python

    for venv in drop_venvs_built_on_another_python((
        tts_config.MANAGED_TTS_ROOT, asr_models.MANAGED_ASR_ROOT, separation_models.MANAGED_SEPARATION_ROOT,
    )):
        logger.info("删掉用另一个 Python 次版本建的托管运行环境,用到时按现在的解释器重装:%s", venv)


def _migrate_browser_boolean_options() -> None:
    """三个浏览器节点的是非选项从「否 / 是」迁成「false / true」。

    选项**值**会原样存进图里,也会原样显示在下拉框上 —— 目录里其余选项一律是中性标识符
    (`true` `GET` `image` `precise`),只有这三处写的是中文,于是英文界面上那三个下拉框
    永远是「否 / 是」,而且没有任何出口能把它翻掉:那是值,不是文案。

    值本身改掉之后,库里已有的图还留着旧值 —— 在这里迁,而不是让读取端认两套。
    **对里写死**是有意的:迁移是历史的快照,不该跟着后面还会变的目录走。
    """
    inspector = inspect(engine)
    if "workflows" not in set(inspector.get_table_names()):
        return
    pairs = {("browser_click", "exact"), ("browser_extract", "all"), ("browser_wait", "gone")}

    def fix(graph: Any) -> bool:
        """→ 改动过没有。子图(循环体 / 子流程)也要走进去。"""
        touched = False
        if not isinstance(graph, dict):
            return False
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            config = node.get("config")
            if not isinstance(config, dict):
                continue
            for field in [key for key in config if (node.get("type"), key) in pairs]:
                if config[field] in ("是", "否"):
                    config[field] = "true" if config[field] == "是" else "false"
                    touched = True
            for value in config.values():
                if isinstance(value, dict) and value.get("nodes") is not None:
                    touched = fix(value) or touched

        return touched

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).fetchall()
        for row in rows:
            try:
                graph = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (TypeError, ValueError):
                continue
            if fix(graph):
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(graph, ensure_ascii=False), "id": row[0]},
                )


def _migrate_comfyui_connections_become_plugin_instances() -> None:
    """ComfyUI 从内核供应商搬成随应用发的插件(ADR 0020):每条 `comfyui` 连接 → 同一个人的 ComfyUI
    插件实例,**连接原地改成插件连接**,存着的引用改成新写法。

    **连接 id 不变**,于是模型行、默认模型、生成历史、用量、定价这些挂在连接上的外键一个都不用动。
    连接上的地址和粘贴的模板搬进实例配置(`server_url` / `api_workflow`),`network:comfyui` 直接授予
    —— 他早就配过这台服务器,升级不该让他再点一次。

    模型与引用的新写法(和插件目录说的是同一套 id):

    - 选过 ComfyUI 里保存的工作流(`parameters.workflow` = 路径)→ **那个工作流就是模型**,
      动态参数表 `workflow_params: {节点: {输入: 值}}` 拍平成 `<节点>.<输入>`;
    - 假模型 `workflow`:连接粘过模板的 → `api-workflow`;没粘的图像 → `builtin:txt2img`(内置文生图);
      没粘模板的视频原来就跑不了(没有内置视频图),**保持原样**,运行时明确报「这个模型不可用」;
    - 指向旧目录档案的参数声明(`comfyui-image` / `comfyui-video` / `model:comfyui/workflow`)和这些连接上
      的参数模板删掉:那是对旧 Adapter 的断言,插件连接的参数由插件目录说。

    改写的地方:生成任务与任务表里的回执、产出记录、用量与定价、生成会话、定时任务、画板上的生成格、
    工作流(连同循环体 / 子图;改过的追加一版修订,作者和认可人沿用上一版 —— 机械改写不换担保人)。
    引用到的模型行不在就补上,插件目录刷新时再对齐。

    幂等:第二次跑时已经没有 `comfyui` 连接、也没有 `comfyui` 的引用。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"provider_profiles", "provider_models", "plugin_instances", "plugin_packages"} <= tables:
        return
    package_id = "dev.mosael.comfyui"
    vendor = f"plugin:{package_id}"
    obsolete_refs = ("profile:comfyui-image", "profile:comfyui-video", "model:comfyui/workflow")

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    # 和 SQLAlchemy 的 DateTime 在 SQLite 里存的是同一种写法;直接传 datetime 走的是已弃用的默认适配器。
    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as conn:
        profiles = conn.execute(text(
            "SELECT id, owner_user_id, name, base_url, extra, enabled FROM provider_profiles WHERE vendor = 'comfyui'"
        )).mappings().all()
        if profiles and conn.execute(text("SELECT 1 FROM plugin_packages WHERE id = :id"), {"id": package_id}).first() is None:
            raise RuntimeError("the bundled ComfyUI plugin is not installed; ComfyUI connections cannot be migrated yet")

        #: 这次搬过的连接 → 它有没有粘过模板(决定假模型 `workflow` 改成什么)。
        templated: dict[str, bool] = {}
        for profile in profiles:
            extra = loads(profile["extra"], {}) or {}
            template = str(extra.get("workflow_template") or "").strip()
            templated[profile["id"]] = bool(template)
            instance_id = uuid.uuid4().hex
            config = {"server_url": (profile["base_url"] or "").strip() or "http://127.0.0.1:8188", "api_workflow": template}
            conn.execute(
                text(
                    "INSERT INTO plugin_instances (id, owner_user_id, package_id, name, enabled, config,"
                    " discovered_tools, capability_status, created_at, updated_at)"
                    " VALUES (:id, :owner, :package, :name, :enabled, :config, '[]', '{}', :now, :now)"
                ),
                {"id": instance_id, "owner": profile["owner_user_id"] or "", "package": package_id,
                 "name": profile["name"], "enabled": int(bool(profile["enabled"])), "config": dumps(config), "now": stamp},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_permission_grants (instance_id, permission, granted, created_at, updated_at)"
                    " VALUES (:id, 'network:comfyui', 1, :now, :now)"
                ),
                {"id": instance_id, "now": stamp},
            )
            conn.execute(
                text(
                    "UPDATE provider_profiles SET vendor = :vendor, plugin_instance_id = :instance, base_url = '',"
                    " extra = '{}' WHERE id = :id"
                ),
                {"vendor": vendor, "instance": instance_id, "id": profile["id"]},
            )
            # 免密钥的连接不该有钥匙行;有的话(随手敲过几个字骗过旧判据)也没有任何意义了。
            conn.execute(text("DELETE FROM provider_credentials WHERE profile_id = :id"), {"id": profile["id"]})
            if "generation_capability_declarations" in tables:
                conn.execute(
                    text(
                        "DELETE FROM generation_capability_declarations WHERE provider_model_id IN"
                        " (SELECT id FROM provider_models WHERE provider_profile_id = :id)"
                    ),
                    {"id": profile["id"]},
                )
            if "generation_capability_profiles" in tables:
                conn.execute(text("DELETE FROM generation_capability_profiles WHERE provider_profile_id = :id"),
                             {"id": profile["id"]})
            conn.execute(text("UPDATE provider_models SET generation_capability_ref = NULL WHERE provider_profile_id = :id"),
                         {"id": profile["id"]})
            # 假模型 `workflow` 改名。目标那一行已经在(用户早就加过)就把默认模型挪过去再删掉这一行。
            for row in conn.execute(
                text("SELECT id, capability_ids FROM provider_models WHERE provider_profile_id = :id AND model_id = 'workflow'"),
                {"id": profile["id"]},
            ).mappings().all():
                capabilities = loads(row["capability_ids"], []) or []
                if template:
                    target = "api-workflow"
                elif "image" in capabilities or not capabilities:
                    target = "builtin:txt2img"
                else:
                    continue  # 没有模板的视频:原来就跑不了,保持原样
                existing = conn.execute(
                    text("SELECT id FROM provider_models WHERE provider_profile_id = :p AND model_id = :m"),
                    {"p": profile["id"], "m": target},
                ).scalar()
                if existing:
                    if "provider_defaults" in tables:
                        conn.execute(text("UPDATE provider_defaults SET provider_model_id = :new WHERE provider_model_id = :old"),
                                     {"new": existing, "old": row["id"]})
                    conn.execute(text("DELETE FROM provider_models WHERE id = :id"), {"id": row["id"]})
                else:
                    conn.execute(text("UPDATE provider_models SET model_id = :m, source = 'plugin' WHERE id = :id"),
                                 {"m": target, "id": row["id"]})

        if "generation_capability_declarations" in tables:
            conn.execute(
                text("DELETE FROM generation_capability_declarations WHERE catalog_ref IN (:a, :b, :c)"),
                dict(zip(("a", "b", "c"), obsolete_refs)),
            )
        conn.execute(
            text("UPDATE provider_models SET generation_capability_ref = NULL WHERE generation_capability_ref IN (:a, :b, :c)"),
            dict(zip(("a", "b", "c"), obsolete_refs)),
        )

        #: 引用里用到、而连接下还没有行的模型:(连接, 模型 id) → 种类。最后补上。
        wanted: dict[tuple[str, str], str] = {}

        def rewrite(ref: dict[str, Any]) -> dict[str, Any] | None:
            """一份存着的引用 `{provider?, provider_profile_id?, model, kind?, parameters?}` → 新写法;
            跟 ComfyUI 无关的回 None(不动它)。"""
            profile_id = str(ref.get("provider_profile_id") or "")
            if ref.get("provider") != "comfyui" and profile_id not in templated:
                return None
            out = dict(ref)
            if "provider" in out:
                out["provider"] = vendor
            parameters = dict(out.get("parameters") or {}) if isinstance(out.get("parameters"), dict) else {}
            workflow = str(parameters.pop("workflow", "") or "").strip()
            nested = parameters.pop("workflow_params", None)
            if isinstance(nested, dict):
                for node_id, inputs in nested.items():
                    if isinstance(inputs, dict):
                        for name, value in inputs.items():
                            parameters[f"{node_id}.{name}"] = value
            kind = str(out.get("kind") or "image")
            model = str(out.get("model") or "")
            if workflow and workflow not in ("builtin", "custom"):
                model = workflow
            elif model == "workflow" and templated.get(profile_id):
                model = "api-workflow"
            elif model == "workflow" and kind == "image":
                model = "builtin:txt2img"
            out["model"] = model
            if "parameters" in out or parameters:
                out["parameters"] = parameters
            if profile_id and model and model != "workflow":
                wanted.setdefault((profile_id, model), kind)
            return out

        # 生成任务:列上的 provider / model,请求里的参数。
        if "generation_jobs" in tables:
            for row in conn.execute(text(
                "SELECT id, provider, provider_profile_id, model, kind, request FROM generation_jobs"
                " WHERE provider = 'comfyui' OR provider_profile_id IN (SELECT id FROM provider_profiles WHERE vendor = :v)"
            ), {"v": vendor}).mappings().all():
                request = loads(row["request"], {}) or {}
                changed = rewrite({"provider": row["provider"], "provider_profile_id": row["provider_profile_id"],
                                   "model": row["model"], "kind": row["kind"], "parameters": request.get("parameters") or {}})
                if changed is None:
                    continue
                conn.execute(
                    text("UPDATE generation_jobs SET provider = :p, model = :m, request = :r WHERE id = :id"),
                    {"p": changed["provider"], "m": changed["model"],
                     "r": dumps({**request, "parameters": changed["parameters"]}), "id": row["id"]},
                )
        if "jobs" in tables:
            for row in conn.execute(text("SELECT id, payload FROM jobs WHERE kind = 'ai_generation'")).mappings().all():
                payload = loads(row["payload"], {}) or {}
                request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
                changed = rewrite({"provider": payload.get("provider"), "provider_profile_id": payload.get("provider_profile_id"),
                                   "model": payload.get("model"), "kind": payload.get("kind"),
                                   "parameters": request.get("parameters") or {}})
                if changed is None:
                    continue
                payload.update(provider=changed["provider"], model=changed["model"])
                if request:
                    payload["request"] = {**request, "parameters": changed["parameters"]}
                conn.execute(text("UPDATE jobs SET payload = :p WHERE id = :id"), {"p": dumps(payload), "id": row["id"]})
        for table in ("generated_assets", "provider_usage_events", "provider_pricing_rules"):
            if table in tables:
                conn.execute(text(f"UPDATE {table} SET provider = :v WHERE provider = 'comfyui'"), {"v": vendor})
        if "generation_sessions" in tables:
            for row in conn.execute(text(
                "SELECT id, provider_profile_id, model, kind FROM generation_sessions WHERE model = 'workflow'"
                " AND provider_profile_id IN (SELECT id FROM provider_profiles WHERE vendor = :v)"
            ), {"v": vendor}).mappings().all():
                changed = rewrite({"provider_profile_id": row["provider_profile_id"], "model": row["model"], "kind": row["kind"]})
                if changed is not None and changed["model"] != row["model"]:
                    conn.execute(text("UPDATE generation_sessions SET model = :m WHERE id = :id"),
                                 {"m": changed["model"], "id": row["id"]})
        if "scheduled_tasks" in tables:
            for row in conn.execute(text("SELECT id, payload FROM scheduled_tasks")).mappings().all():
                payload = loads(row["payload"], {}) or {}
                if not isinstance(payload, dict) or not ("provider" in payload or "provider_profile_id" in payload):
                    continue
                changed = rewrite(payload)
                if changed is not None and changed != payload:
                    conn.execute(text("UPDATE scheduled_tasks SET payload = :p WHERE id = :id"),
                                 {"p": dumps(changed), "id": row["id"]})
        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                    continue
                touched = False
                for item in canvas["items"]:
                    form = item.get("form") if isinstance(item, dict) else None
                    if not isinstance(form, dict):
                        continue
                    changed = rewrite({**form, "kind": item.get("kind")})
                    if changed is not None:
                        changed.pop("kind", None)
                        if changed != form:
                            item["form"] = changed
                            touched = True
                if touched:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(canvas), "id": row["id"]})
        if "workflows" in tables:

            def rewrite_graph(graph: Any) -> Any:
                if not isinstance(graph, dict):
                    return graph
                nodes = []
                for node in graph.get("nodes") or []:
                    if not isinstance(node, dict):
                        nodes.append(node)
                        continue
                    config = dict(node.get("config") or {})
                    if node.get("type") == "ai_generate":
                        changed = rewrite(config)
                        if changed is not None:
                            config = changed
                    for key, value in config.items():
                        if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                            config[key] = rewrite_graph(value)
                    nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
                return {**graph, "nodes": nodes}

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            has_revisions = "workflow_revisions" in tables
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                if not isinstance(graph, dict):
                    continue
                rewritten = rewrite_graph(graph)
                if rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " 'ComfyUI 搬进插件:模型与参数改成插件的写法', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )

        # 引用到的模型在连接下还没有行的,补上 —— 否则插件目录刷新之前,那些画板和工作流选不到它。
        for (profile_id, model), kind in wanted.items():
            known = conn.execute(
                text("SELECT 1 FROM provider_models WHERE provider_profile_id = :p AND model_id = :m"),
                {"p": profile_id, "m": model},
            ).first()
            is_plugin = conn.execute(
                text("SELECT 1 FROM provider_profiles WHERE id = :p AND vendor = :v"), {"p": profile_id, "v": vendor}
            ).first()
            if known or not is_plugin:
                continue
            conn.execute(
                text(
                    "INSERT INTO provider_models (id, provider_profile_id, model_id, display_name, capability_ids, enabled,"
                    " source, created_at, updated_at) VALUES (:id, :p, :m, :name, :caps, 1, 'plugin', :now, :now)"
                ),
                {"id": uuid.uuid4().hex, "p": profile_id, "m": model[:160],
                 "name": (model[:-5] if model.endswith(".json") else model)[:160],
                 "caps": dumps([kind if kind in ("image", "video") else "image"]), "now": stamp},
            )
    if profiles:
        logger.info("把 %d 条 ComfyUI 连接搬成了 ComfyUI 插件的连接", len(profiles))


def _migrate_blender_host_is_ipv4() -> None:
    """Blender 连接的主机 `::1` 改成 `127.0.0.1`。

    清单里原先有 `::1` 这一项,而它从来连不上:mcp-for-blender 2.0.3 的 MCP 服务和 Blender 里的 Add-on
    两头都开 IPv4 套接字(`socket.AF_INET`),拿 `::1` 去连报「nodename nor servname provided」,界面上
    说的却是「Add-on 没开」。这一项删了;存着它的连接改成同一台机器的 IPv4 回环 —— 用户选 `::1` 的意思
    正是「本机」。**写死包 id 与取值**:迁移是历史的快照,不跟着清单走。幂等。
    """
    if "plugin_instances" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, config FROM plugin_instances WHERE package_id = 'dev.mosael.blender'")
        ).fetchall()
        for instance_id, raw in rows:
            try:
                config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (TypeError, ValueError):
                continue
            if isinstance(config, dict) and config.get("BLENDER_HOST") == "::1":
                config["BLENDER_HOST"] = "127.0.0.1"
                conn.execute(text("UPDATE plugin_instances SET config = :c WHERE id = :i"),
                             {"c": json.dumps(config, ensure_ascii=False), "i": instance_id})


def _remove_minimax_music_models() -> None:
    """MiniMax 音乐撤掉(见 ADR 0022 的补充):它 2026-08-20 起不再向新用户开放,接口留着只会让新用户配好之后
    在第一次付费调用时被对面拒掉。代码里的 Adapter、目录里的三个模型和两份能力档案都删了,这里清掉**存着的指向**。

    - 模型行(`minimax` 连接下的 `music-3.0` / `music-2.6` / `music-cover`)删掉,连同它们的参数声明、指着它们的
      默认模型(置空 = 没设)和这三个模型的价格规则;
    - 别的模型行上指向已删档案 / 模型的「参数按什么来」(`profile:minimax-music*`、`model:minimax/music-*`)清空,
      指着它们的参数声明删掉 —— 留着的话解析回 None,界面显示成「还没认出来」,不如直接回到跟随目录;
    - 存着的**模型选择**清掉:生成会话(AI 工作台)、画板上的生成格、工作流的 `ai_generate` 节点(连同循环体 / 子图,
      改过的追加一版修订,作者和认可人沿用上一版)、定时任务。清掉的是 provider / 连接 / 模型三项,提示词、歌词、
      素材这些用户写下的东西不动 —— 再打开时重新选一个模型就能接着用。**定时任务同时停用**:清掉模型的任务会落到
      默认模型上跑,那是在用户不知道的情况下换了一家花钱;
    - 生成历史、任务回执、产出记录和用量是**发生过的事**,原样保留。

    幂等:第二次跑时这三个模型已经没有行、也没有任何引用。
    """
    tables = set(inspect(engine).get_table_names())
    if "provider_profiles" not in tables:
        return
    models = ("music-3.0", "music-2.6", "music-cover")
    refs = ("profile:minimax-music", "profile:minimax-music-cover", *(f"model:minimax/{one}" for one in models))
    in_models = ", ".join(f":m{index}" for index in range(len(models)))
    in_refs = ", ".join(f":r{index}" for index in range(len(refs)))
    model_params = {f"m{index}": one for index, one in enumerate(models)}
    ref_params = {f"r{index}": one for index, one in enumerate(refs)}

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as conn:
        minimax = set(conn.execute(text("SELECT id FROM provider_profiles WHERE vendor = 'minimax'")).scalars().all())

        def points_at_music(ref: dict[str, Any]) -> bool:
            """一份存着的选择 `{provider?, provider_profile_id?, model}` 指的是不是被撤掉的那三个。"""
            if str(ref.get("model") or "").strip() not in models:
                return False
            return ref.get("provider") == "minimax" or str(ref.get("provider_profile_id") or "") in minimax

        def cleared(ref: dict[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in ref.items() if key not in ("provider", "provider_profile_id", "model")}

        if "provider_models" in tables and minimax:
            profile_params = {f"p{index}": one for index, one in enumerate(sorted(minimax))}
            in_profiles = ", ".join(f":{key}" for key in profile_params)
            doomed = conn.execute(
                text(f"SELECT id FROM provider_models WHERE provider_profile_id IN ({in_profiles})"
                     f" AND model_id IN ({in_models})"),
                {**profile_params, **model_params},
            ).scalars().all()
            for row_id in doomed:
                if "generation_capability_declarations" in tables:
                    conn.execute(text("DELETE FROM generation_capability_declarations WHERE provider_model_id = :id"),
                                 {"id": row_id})
                if "provider_defaults" in tables:
                    conn.execute(text("UPDATE provider_defaults SET provider_model_id = NULL WHERE provider_model_id = :id"),
                                 {"id": row_id})
                conn.execute(text("DELETE FROM provider_models WHERE id = :id"), {"id": row_id})
            if "provider_pricing_rules" in tables:
                conn.execute(
                    text(f"DELETE FROM provider_pricing_rules WHERE model IN ({in_models})"
                         f" AND (provider = 'minimax' OR provider_profile_id IN ({in_profiles}))"),
                    {**profile_params, **model_params},
                )
        elif "provider_pricing_rules" in tables:
            conn.execute(text(f"DELETE FROM provider_pricing_rules WHERE provider = 'minimax' AND model IN ({in_models})"),
                         model_params)
        if "generation_capability_declarations" in tables:
            conn.execute(text(f"DELETE FROM generation_capability_declarations WHERE catalog_ref IN ({in_refs})"), ref_params)
        if "provider_models" in tables and "generation_capability_ref" in {
            column["name"] for column in inspect(conn).get_columns("provider_models")
        }:
            conn.execute(
                text(f"UPDATE provider_models SET generation_capability_ref = NULL WHERE generation_capability_ref IN ({in_refs})"),
                ref_params,
            )

        if "generation_sessions" in tables and minimax:
            for row in conn.execute(text(
                f"SELECT id, provider_profile_id, model FROM generation_sessions WHERE model IN ({in_models})"
            ), model_params).mappings().all():
                if points_at_music(dict(row)):
                    conn.execute(text("UPDATE generation_sessions SET model = NULL, provider_profile_id = NULL WHERE id = :id"),
                                 {"id": row["id"]})
        if "scheduled_tasks" in tables:
            for row in conn.execute(text("SELECT id, payload FROM scheduled_tasks")).mappings().all():
                payload = loads(row["payload"], None)
                if isinstance(payload, dict) and points_at_music(payload):
                    conn.execute(text("UPDATE scheduled_tasks SET payload = :p, enabled = 0 WHERE id = :id"),
                                 {"p": dumps(cleared(payload)), "id": row["id"]})
        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                if not isinstance(canvas, dict) or not isinstance(canvas.get("items"), list):
                    continue
                touched = False
                for item in canvas["items"]:
                    form = item.get("form") if isinstance(item, dict) else None
                    if isinstance(form, dict) and points_at_music(form):
                        item["form"] = cleared(form)
                        touched = True
                if touched:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(canvas), "id": row["id"]})
        if "workflows" in tables:

            def rewrite_graph(graph: Any) -> Any:
                if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
                    return graph
                nodes = []
                for node in graph["nodes"]:
                    if not isinstance(node, dict) or not isinstance(node.get("config"), dict):
                        nodes.append(node)
                        continue
                    config = dict(node["config"])
                    if node.get("type") == "ai_generate" and points_at_music(config):
                        config = cleared(config)
                    for key, value in config.items():
                        if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                            config[key] = rewrite_graph(value)
                    nodes.append({**node, "config": config} if config != node["config"] else node)
                return {**graph, "nodes": nodes}

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            workflow_columns = {column["name"] for column in inspect(conn).get_columns("workflows")}
            has_revisions = "workflow_revisions" in tables and {"revision", "graph_hash"} <= workflow_columns
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                rewritten = rewrite_graph(graph)
                if not isinstance(graph, dict) or rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " 'MiniMax 音乐已撤掉:清掉指向它的模型选择', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )


def _merge_object_storage_plugins() -> None:
    """四个对象存储插件(阿里云 OSS / Amazon S3 / 腾讯云 COS / 火山引擎 TOS)合成一个随应用内置的「对象存储」
    插件(`dev.mosael.object-storage`),连哪一家成了连接的配置(`STORAGE_PROVIDER`)。

    **连接 id 不变**,于是「素材外链」的默认(plugin_capability_defaults)、直链缓存(plugin_public_links)、
    工作流和画板上选定的连接(`instance_id`)一个都不用动。在原地改的:

    - 连接:改挂新包;配置 `<家>_BUCKET / _REGION / _ENDPOINT` → `STORAGE_*`,并写上服务商。老 S3 插件填了
      非 amazonaws.com 接入点的(MinIO、R2)归到「S3 兼容服务」。地域空着的按老插件的默认值补上 —— 老代码
      就是这么补的,迁过来行为不变。名字还是老模板生成的那个时,按新模板重生成(新模板对四家生成的正是同一个
      名字;S3 兼容服务那一格除外),这样以后改配置时名字照旧跟着走;用户改过的名字不动;
    - 凭据:**只改键名,不解密**(`value` 是整格密文,和键名无关);
    - 授权:`network:oss|s3|cos|tos` → `network:object-storage`,授过的照旧是授过的;
    - 工具:`oss_upload` → `storage_upload`(presign / fetch / list 同理)。工具开关、调用记录、会话里
      「本会话始终允许」的名字(`plugin__<连接>__<工具>`)和确认卡上的工具名跟着改;新工具缺开关的补上
      (清单是 `expose: all`,全开);
    - 工作流(连同循环体 / 子图)与画板工具格上的节点类型 `plugin.<老包>.<老工具>` → 新写法。入参和出参的
      名字没变(asset_id / key / expires / url / public_url …),数据边与 `{{节点.url}}` 引用不用动。改过的
      工作流追加一版修订,作者和认可人沿用上一版 —— 机械改写不换担保人;
    - 老包的记录删掉,插件目录里老包的文件夹和持久目录删掉 —— 否则下一次扫描会把它们重新登记回来。

    新包由 `install-bundled-plugins`(每次启动的对账,排在前面)装好;有连接要搬而它不在就报错,不搬半截。
    幂等:第二次跑时已经没有老包的连接、记录和目录。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"plugin_packages", "plugin_instances"} <= tables:
        return
    new_package = "dev.mosael.object-storage"
    #: 老包 → (服务商, 配置键前缀, (ID 凭据键, 密钥凭据键), 老权限, 老工具前缀, 老地域默认, 老名字前缀 zh / en)
    legacy: dict[str, tuple[str, str, tuple[str, str], str, str, str, tuple[str, str]]] = {
        "dev.mosael.aliyun-oss": ("aliyun-oss", "OSS", ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"), "network:oss",
                                  "oss", "cn-hangzhou", ("阿里云 OSS", "Alibaba Cloud OSS")),
        "dev.mosael.aws-s3": ("aws-s3", "S3", ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"), "network:s3",
                              "s3", "us-east-1", ("Amazon S3", "Amazon S3")),
        "dev.mosael.tencent-cos": ("tencent-cos", "COS", ("COS_SECRET_ID", "COS_SECRET_KEY"), "network:cos",
                                   "cos", "ap-guangzhou", ("腾讯云 COS", "Tencent Cloud COS")),
        "dev.mosael.volcengine-tos": ("volcengine-tos", "TOS", ("TOS_ACCESS_KEY", "TOS_SECRET_KEY"), "network:tos",
                                      "tos", "cn-beijing", ("火山引擎 TOS", "Volcengine TOS")),
    }
    #: 新清单里服务商的显示名(zh, en)—— 和 name_template `{STORAGE_PROVIDER:label} · {STORAGE_BUCKET}` 同一份。
    labels = {"aliyun-oss": ("阿里云 OSS", "Alibaba Cloud OSS"), "aws-s3": ("Amazon S3", "Amazon S3"),
              "tencent-cos": ("腾讯云 COS", "Tencent Cloud COS"), "volcengine-tos": ("火山引擎 TOS", "Volcengine TOS"),
              "s3-compatible": ("S3 兼容服务", "S3-compatible service")}
    actions = ("upload", "presign", "fetch", "list")
    #: 节点类型 / 画板产出者的新旧写法。
    node_types = {
        f"plugin.{package}.{spec[4]}_{action}": f"plugin.{new_package}.storage_{action}"
        for package, spec in legacy.items() for action in actions
    }
    node_types.update({f"node:{old}": f"node:{new}" for old, new in list(node_types.items())})

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def safe(name: str) -> str:
        """智能体工具名里的一段(agent.tool_manifest.agent_tool_name 同一条折叠规则)。"""
        return re.sub(r"[^A-Za-z0-9_]+", "_", name)

    def renamed(value: Any) -> Any:
        """把一份 JSON 里**恰好等于**某个老节点类型的字符串换掉(键不动)。"""
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        if isinstance(value, list):
            return [renamed(item) for item in value]
        return node_types.get(value, value) if isinstance(value, str) else value

    stamp = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    old_ids = tuple(legacy)
    marks = ", ".join(f":p{index}" for index in range(len(old_ids)))
    by_index = {f"p{index}": one for index, one in enumerate(old_ids)}
    with engine.begin() as conn:
        instances = conn.execute(
            text(f"SELECT id, package_id, name, config FROM plugin_instances WHERE package_id IN ({marks})"), by_index
        ).mappings().all()
        if instances and conn.execute(text("SELECT 1 FROM plugin_packages WHERE id = :id"),
                                      {"id": new_package}).first() is None:
            raise RuntimeError("the bundled object-storage plugin is not installed; storage connections cannot be merged yet")

        #: 这次改了名的智能体工具名:`plugin__<连接>__oss_upload` → `plugin__<连接>__storage_upload`。
        agent_tools: dict[str, str] = {}
        for row in instances:
            provider, prefix, (id_key, secret_key), permission, tool_prefix, region_default, (zh, en) = legacy[row["package_id"]]
            old = loads(row["config"], {}) or {}
            bucket = str(old.get(f"{prefix}_BUCKET") or "").strip()
            region = str(old.get(f"{prefix}_REGION") or "").strip() or region_default
            endpoint = str(old.get(f"{prefix}_ENDPOINT") or "").strip()
            if provider == "aws-s3" and endpoint and "amazonaws.com" not in endpoint.lower():
                provider = "s3-compatible"
            config = {"STORAGE_PROVIDER": provider, "STORAGE_BUCKET": bucket, "STORAGE_REGION": region,
                      "STORAGE_ENDPOINT": endpoint}
            name = row["name"] or ""
            if name == f"{zh} · {bucket}":
                name = f"{labels[provider][0]} · {bucket}"
            elif name == f"{en} · {bucket}":
                name = f"{labels[provider][1]} · {bucket}"
            conn.execute(
                text("UPDATE plugin_instances SET package_id = :package, config = :config, name = :name, updated_at = :now"
                     " WHERE id = :id"),
                {"package": new_package, "config": dumps(config), "name": name, "now": stamp, "id": row["id"]},
            )

            def move(table: str, column: str, old_value: str, new_value: str, instance_id: str = row["id"]) -> None:
                """把这个连接的一行从老键改到新键;新键已经有了就删掉老的(第二次跑、或者用户手动补过)。"""
                if table not in tables:
                    return
                taken = conn.execute(
                    text(f"SELECT 1 FROM {table} WHERE instance_id = :id AND {column} = :new"),
                    {"id": instance_id, "new": new_value},
                ).first()
                verb = f"DELETE FROM {table}" if taken else f"UPDATE {table} SET {column} = :new"
                conn.execute(text(f"{verb} WHERE instance_id = :id AND {column} = :old"),
                             {"id": instance_id, "old": old_value, "new": new_value})

            move("plugin_credentials", "key", id_key, "STORAGE_ACCESS_KEY_ID")
            move("plugin_credentials", "key", secret_key, "STORAGE_ACCESS_KEY_SECRET")
            move("plugin_permission_grants", "permission", permission, "network:object-storage")
            for action in actions:
                move("plugin_capabilities", "tool_name", f"{tool_prefix}_{action}", f"storage_{action}")
                if "plugin_invocations" in tables:
                    conn.execute(
                        text("UPDATE plugin_invocations SET tool_name = :new WHERE instance_id = :id AND tool_name = :old"),
                        {"id": row["id"], "old": f"{tool_prefix}_{action}", "new": f"storage_{action}"},
                    )
                agent_tools[f"plugin__{safe(row['id'])}__{tool_prefix}_{action}"] = f"plugin__{safe(row['id'])}__storage_{action}"
                if "plugin_capabilities" in tables and conn.execute(
                    text("SELECT 1 FROM plugin_capabilities WHERE instance_id = :id AND tool_name = :tool"),
                    {"id": row["id"], "tool": f"storage_{action}"},
                ).first() is None:
                    conn.execute(
                        text("INSERT INTO plugin_capabilities (instance_id, tool_name, exposed) VALUES (:id, :tool, 1)"),
                        {"id": row["id"], "tool": f"storage_{action}"},
                    )

        if agent_tools and "agent_sessions" in tables:
            for session in conn.execute(text("SELECT id, auto_allow_tools FROM agent_sessions")).mappings().all():
                allowed = loads(session["auto_allow_tools"], []) or []
                if isinstance(allowed, list) and any(name in agent_tools for name in allowed):
                    conn.execute(text("UPDATE agent_sessions SET auto_allow_tools = :v WHERE id = :id"),
                                 {"v": dumps([agent_tools.get(name, name) for name in allowed]), "id": session["id"]})
        if agent_tools and "tool_confirmations" in tables:
            for old_name, new_name in agent_tools.items():
                conn.execute(text("UPDATE tool_confirmations SET tool = :new WHERE tool = :old"),
                             {"old": old_name, "new": new_name})

        if "boards" in tables:
            board_columns = {column["name"] for column in inspect(conn).get_columns("boards")}
            for row in conn.execute(text("SELECT id, canvas FROM boards")).mappings().all():
                canvas = loads(row["canvas"], None)
                rewritten = renamed(canvas)
                if isinstance(canvas, dict) and rewritten != canvas:
                    bump = ", revision = revision + 1" if "revision" in board_columns else ""
                    conn.execute(text(f"UPDATE boards SET canvas = :c{bump} WHERE id = :id"),
                                 {"c": dumps(rewritten), "id": row["id"]})

        if "workflows" in tables:

            def digest(graph: Any) -> str:
                canonical = json.dumps(graph or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            workflow_columns = {column["name"] for column in inspect(conn).get_columns("workflows")}
            has_revisions = "workflow_revisions" in tables and {"revision", "graph_hash"} <= workflow_columns
            for row in conn.execute(text("SELECT id, graph FROM workflows")).mappings().all():
                graph = loads(row["graph"], None)
                rewritten = renamed(graph)
                if not isinstance(graph, dict) or rewritten == graph:
                    continue
                if not has_revisions:
                    conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                                 {"g": dumps(rewritten), "id": row["id"]})
                    continue
                latest = conn.execute(
                    text("SELECT id, revision, created_by FROM workflow_revisions WHERE workflow_id = :id"
                         " ORDER BY revision DESC LIMIT 1"),
                    {"id": row["id"]},
                ).mappings().first()
                revision = int(latest["revision"]) + 1 if latest else 1
                revision_id = uuid.uuid4().hex
                conn.execute(
                    text(
                        "INSERT INTO workflow_revisions (id, workflow_id, revision, graph, graph_hash, source, note,"
                        " created_by, created_at) VALUES (:id, :workflow, :revision, :graph, :hash, 'migration',"
                        " '对象存储四个插件合成一个:节点改用「对象存储」的工具', :author, :now)"
                    ),
                    {"id": revision_id, "workflow": row["id"], "revision": revision, "graph": dumps(rewritten),
                     "hash": digest(rewritten), "author": latest["created_by"] if latest else None, "now": stamp},
                )
                if latest and "workflow_revision_attestations" in tables:
                    for attester in conn.execute(
                        text("SELECT user_id FROM workflow_revision_attestations WHERE revision_id = :id"),
                        {"id": latest["id"]},
                    ).scalars().all():
                        conn.execute(
                            text("INSERT INTO workflow_revision_attestations (id, revision_id, user_id, created_at)"
                                 " VALUES (:id, :revision, :user, :now)"),
                            {"id": uuid.uuid4().hex, "revision": revision_id, "user": attester, "now": stamp},
                        )
                conn.execute(
                    text("UPDATE workflows SET graph = :g, revision = :r, graph_hash = :h WHERE id = :id"),
                    {"g": dumps(rewritten), "r": revision, "h": digest(rewritten), "id": row["id"]},
                )

        conn.execute(text(f"DELETE FROM plugin_packages WHERE id IN ({marks})"), by_index)

    # 文件夹最后删:库里的事务提交之后。删之前认两件事 —— 它是插件目录的**直接子目录**,里面那份清单的 id
    # 确实是老包之一(不按文件夹名猜:手动放进来的包可以叫任何名字)。
    plugins_dir = settings.plugins_dir
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            manifest = child / "mosael.plugin.json"
            if not child.is_dir() or not manifest.is_file():
                continue
            try:
                package_id = json.loads(manifest.read_text(encoding="utf-8")).get("id")
            except (OSError, ValueError, AttributeError):
                continue
            if package_id in legacy:
                shutil.rmtree(child)
    for package_id in legacy:
        shutil.rmtree(settings.data_dir / "plugin-data" / package_id, ignore_errors=True)
    if instances:
        logger.info("把 %d 个对象存储连接合进了「对象存储」插件", len(instances))


def _install_bundled_plugins() -> None:
    """随应用发的插件(`plugins/bundled/`)装进插件目录并登记包记录。

    **对账,不是迁移**:每个版本带的插件都可能变,判据是内容指纹(见 domain/plugins/bundled)。
    在这里而不是 lifespan:把老数据搬到插件上的迁移(ComfyUI 连接 → ComfyUI 插件实例)要先有
    这个包;而且不跑 lifespan 的入口(TestClient、脚本)拿到的也该是装好的系统。
    """
    from sqlalchemy.orm import Session

    from app.domain.plugins import bundled

    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    with Session(engine) as db:
        bundled.install(db, settings.plugins_dir)


def _forget_comfyui_run_workflow_tool() -> None:
    """ComfyUI 插件 1.4.0 删掉了通用的「按 id 跑工作流」(`run_workflow`):它连要跑哪张图都不知道,表单却要人填
    参数;它能跑的每一种图(保存的工作流、粘贴的 API 模板、内置文生图)都有了自己的工具。

    **存着的节点不在这里改。** 工作流里、画板工具格上的 `plugin.dev.mosael.comfyui.run_workflow` 要改成哪张图的
    工具、入参怎么改名,只有插件报出的工具清单说得出(`replaces`,图在 ComfyUI 里);那是每次启动和每次清单刷新都跑
    的对账 `rewrite-replaced-plugin-tools` 的事 —— 老工具不在了,对不上的格子由它丢掉并记进修订说明。定时任务
    只指着工作流,工作流改好就是改好了。选的那张图在 ComfyUI 里已经删了的节点无从改起,留着,运行前检查报「未知的
    节点类型」—— 和一个指向已删工作流的 `wf_…` 节点是同一种状态。

    这里清的是**只挂着工具名、没有别的去处**的几样,它们不用等清单:

    - `plugin_capabilities` 里这个工具的开关(工具不在了,开关没有意义;以后要是再有同名工具,不该继承它);
    - 会话里「本会话始终允许」的 `plugin__<连接>__run_workflow`(折叠规则同 agent.tool_manifest.agent_tool_name)。
      不转给每张图的工具:允许过「按 id 跑任意一张」不等于允许过哪一张。

    调用记录和确认卡是历史,不动。幂等:第二次跑时已经没有这些行。
    """
    tables = set(inspect(engine).get_table_names())
    if not {"plugin_instances", "plugin_capabilities"} <= tables:
        return
    package_id = "dev.mosael.comfyui"

    def safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", value)

    with engine.begin() as conn:
        instance_ids = conn.execute(
            text("SELECT id FROM plugin_instances WHERE package_id = :p"), {"p": package_id}
        ).scalars().all()
        if not instance_ids:
            return
        for instance_id in instance_ids:
            conn.execute(
                text("DELETE FROM plugin_capabilities WHERE instance_id = :id AND tool_name = 'run_workflow'"),
                {"id": instance_id},
            )
        if "agent_sessions" not in tables:
            return
        retired = {f"plugin__{safe(instance_id)}__run_workflow" for instance_id in instance_ids}
        for session in conn.execute(text("SELECT id, auto_allow_tools FROM agent_sessions")).mappings().all():
            raw = session["auto_allow_tools"]
            try:
                allowed = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if isinstance(allowed, list) and retired & set(allowed):
                conn.execute(
                    text("UPDATE agent_sessions SET auto_allow_tools = :v WHERE id = :id"),
                    {"v": json.dumps([name for name in allowed if name not in retired], ensure_ascii=False),
                     "id": session["id"]},
                )


def _migrate_generation_capabilities_need_evidence() -> None:
    """生成能力要有正面证据(见 domain/provider_models.evidenced_capabilities):把**没写能力**的模型行按新规则
    认出来的能力**写进** `capability_ids`,让设置页的能力标签和选择器看的是同一份、看得见也改得了。

    此前行上没写能力时兜底的是整个供应商预设:OpenAI 兼容连接(147ai、Ollama)上的每个对话模型都是生图模型,
    Evolink 上一个认不出的模型同时是图像、视频和音乐模型 —— 画板的出图下拉里于是列着 `claude-opus-4-6`。

    - **写过能力的行一概不碰**:那是用户的话,哪怕和新规则不一致;
    - 没写的行,落成新规则的结果:目录认得的按目录,连接声明过 / 用户写过参数契约的按那几种,单能力供应商按
      那一种,其余只剩对话(多能力预设里有对话的话)。聚合连接上认不出的模型因此变成**只当对话模型**;
    - 但**用户用行动说过**它能做的那几种,照旧保留(只限旧规则当时确实给了的那几种):
        · 他把这一行设成了这种能力的**默认模型**;
        · 这一行在这种生成上**真的出过东西**(生成历史里有产出、或那一趟任务成功了);
        · 他在这一行上写过旧版的「参数按什么来」(`generation_capability_ref`),而它解析得到这种生成。
      于是一个在中转上跑通了的生图模型不会因为名字没登记就从下拉里消失;
    - 新规则什么都认不出、也没有用户证据的行(Evolink 上认不出的模型)留空 —— 空就是"按规则认",而规则
      认不出它,它不进任何下拉,设置里标上能力即可;
    - 存着的**模型选择**(画板格、工作流节点、定时任务、AI 工作台会话)不改:指着一个不再能做这件事的模型时,
      选择器显示「选择模型」,生成漏斗报「没有标上这项能力」(genErr_modelLacksKind_*),不会崩。

    规则本身取领域里那一份,不在这里抄:这一步的意思就是"把现在这条规则的答案写下来",抄一份只会让两边
    分岔。幂等:第二次跑时这些行都已经写了能力,第一条就跳过;留空的那些再算一遍还是空。
    """
    tables = set(inspect(engine).get_table_names())
    if "provider_models" not in tables or "provider_profiles" not in tables:
        return
    from app.domain.generation.catalog import GENERATION_KINDS, resolve_capability_ref
    from app.domain.provider_models import evidenced_capabilities, infer_capabilities
    from app.domain.providers import ALL_CAPABILITY_IDS, capability_ids_for_vendor

    def loads(raw: Any, fallback: Any) -> Any:
        if raw is None:
            return fallback
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            return fallback

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT m.id, m.model_id, m.capability_ids, m.declared_capabilities, m.generation_capability_ref,"
                " m.provider_profile_id, p.vendor FROM provider_models m"
                " JOIN provider_profiles p ON p.id = m.provider_profile_id"
            )
        ).mappings().all()

        declaration_kinds: dict[str, set[str]] = {}
        if "generation_capability_declarations" in tables:
            for model_row_id, kind in conn.execute(
                text("SELECT provider_model_id, kind FROM generation_capability_declarations")
            ).all():
                declaration_kinds.setdefault(str(model_row_id), set()).add(str(kind))

        #: 用户用行动说过的:模型行 id → 能力。
        acted: dict[str, set[str]] = {}
        if "provider_defaults" in tables:
            for capability, model_row_id in conn.execute(
                text("SELECT capability, provider_model_id FROM provider_defaults WHERE provider_model_id IS NOT NULL")
            ).all():
                acted.setdefault(str(model_row_id), set()).add(str(capability))
        produced: set[tuple[str, str, str]] = set()
        if "generation_jobs" in tables:
            succeeded = " OR g.job_id IN (SELECT id FROM jobs WHERE status = 'succeeded')" if "jobs" in tables else ""
            for profile_id, model_name, kind in conn.execute(
                text(
                    "SELECT DISTINCT g.provider_profile_id, g.model, g.kind FROM generation_jobs g"
                    f" WHERE g.provider_profile_id IS NOT NULL AND (g.result_asset_id IS NOT NULL{succeeded})"
                )
            ).all():
                produced.add((str(profile_id), str(model_name), str(kind)))
        custom_profiles: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        if "generation_capability_profiles" in tables:
            for template_id, profile_id, kind, capabilities in conn.execute(
                text("SELECT id, provider_profile_id, kind, capabilities FROM generation_capability_profiles")
            ).all():
                by_kind = custom_profiles.setdefault(str(profile_id), {}).setdefault(str(kind), {})
                by_kind[str(template_id)] = loads(capabilities, {}) or {}

        written = narrowed = 0
        for row in rows:
            own = [one for one in (loads(row["capability_ids"], []) or []) if one in ALL_CAPABILITY_IDS]
            if own:
                continue
            row_id = str(row["id"])
            vendor = str(row["vendor"] or "")
            model_name = str(row["model_id"] or "")
            profile_id = str(row["provider_profile_id"])
            declared = loads(row["declared_capabilities"], {}) or {}
            evidence = set(declaration_kinds.get(row_id, set()))
            if isinstance(declared, dict):
                evidence |= {str(kind) for kind in declared}
            capabilities = evidenced_capabilities(vendor, model_name, declared_kinds=evidence)

            before = infer_capabilities(vendor, model_name) or capability_ids_for_vendor(vendor)
            ref = str(row["generation_capability_ref"] or "").strip()
            for capability in before:
                if capability in capabilities:
                    continue
                if (
                    capability in acted.get(row_id, set())
                    or (profile_id, model_name, capability) in produced
                    or (
                        bool(ref)
                        and capability in GENERATION_KINDS
                        and resolve_capability_ref(
                            ref, capability, custom=custom_profiles.get(profile_id, {}).get(capability)
                        )
                        is not None
                    )
                ):
                    capabilities.append(capability)
            lost = [one for one in before if one not in capabilities and one in (*GENERATION_KINDS, "tts")]
            if lost:
                narrowed += 1
                logger.info(
                    "模型 %s(%s 连接)没有「能做 %s」的证据,不再出现在对应的生成入口里;要用它就在设置里标上",
                    model_name, vendor, "/".join(lost),
                )
            if not capabilities:
                continue
            conn.execute(
                text("UPDATE provider_models SET capability_ids = :caps WHERE id = :id"),
                {"caps": json.dumps(capabilities), "id": row_id},
            )
            written += 1
        if written or narrowed:
            logger.info("模型能力落成显式标签:%d 行写下了能力,其中 %d 行收窄了生成能力", written, narrowed)


def _rewrite_replaced_plugin_tools() -> None:
    """工作流里、画板工具格上存着的、已被插件运行时报出的新工具取代的老插件节点,改写成新工具(见
    domain/workflows/plugin_references 与 domain/boards/plugin_references)。ComfyUI 的 `run_workflow` + 某张工作流 → 那张工作流自己的工具。
    老工具已经从插件里删掉了的(ComfyUI 的 `run_workflow` 就是),新工具上没有位置的格子丢掉、记进修订说明 ——
    留着一个跑不起来的节点不是保住了用户的值。

    **对账,不是一次性迁移**:依据是插件上一次报出的工具清单(缓存在 `plugin_instances.discovered_tools`),
    清单会变(用户在 ComfyUI 里新存了工作流),新出现的对应关系下次启动也该迁;清单刷新时同一个函数也会跑。
    没有可迁的就什么都不做。

    画板上还多一件:工具声明了 `mirrors`(和一个生成模型是同一件事)、连接的主人用得上那个模型时,工具格改写成
    那种素材的生成格(见 domain/boards/plugin_references 的「被生成取代的工具格」)。同一个道理是对账:`mirrors`
    只在插件报出清单之后才有。
    """
    from sqlalchemy.orm import Session

    from app.domain.boards import plugin_references as board_references
    from app.domain.workflows import plugin_references

    if not {"plugin_instances", "workflows", "workflow_revisions", "boards"} <= set(inspect(engine).get_table_names()):
        return
    with Session(engine) as db:
        plugin_references.rewrite_replaced_tools(db)
        board_references.reconcile_plugin_tool_cells(db)


def _migrate_plugin_generation_columns() -> None:
    """插件可以是生成供应商(ADR 0020)要的三列。

    - `provider_profiles.plugin_instance_id`:这条连接**是**哪个插件实例(外键,实例删掉连接跟着删);
    - `provider_models.declared_capabilities`:连接自己声明的生成参数描述符(插件目录刷新时写);
    - `plugin_instances.capability_status`:这个实例替宿主做的事上一次做得怎么样(几个模型、失败原因)。

    `create_all` 不给已有的表加列,所以在它之前。表不在(还没建过)的跳过 —— 那种库由
    `create-current-schema` 直接建成带这几列的样子。
    """
    with engine.begin() as conn:
        def columns(table: str) -> set[str]:
            return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}

        profile_columns = columns("provider_profiles")
        if profile_columns and "plugin_instance_id" not in profile_columns:
            conn.execute(text(
                "ALTER TABLE provider_profiles ADD COLUMN plugin_instance_id VARCHAR(64) "
                "REFERENCES plugin_instances (id) ON DELETE CASCADE"
            ))
        if profile_columns:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_provider_profiles_plugin_instance_id "
                "ON provider_profiles (plugin_instance_id)"
            ))
        model_columns = columns("provider_models")
        if model_columns and "declared_capabilities" not in model_columns:
            conn.execute(text("ALTER TABLE provider_models ADD COLUMN declared_capabilities JSON"))
        instance_columns = columns("plugin_instances")
        if instance_columns and "capability_status" not in instance_columns:
            conn.execute(text(
                "ALTER TABLE plugin_instances ADD COLUMN capability_status JSON NOT NULL DEFAULT '{}'"
            ))


def _migrate_plugin_authorization_rejected() -> None:
    """`plugin_instances.authorization_rejected_at`:插件上一次说「对方不再接受已存的令牌」是什么时候。

    `create_all` 不给已有的表加列,所以在它之前。表不在的跳过 —— 那种库由 `create-current-schema`
    直接建成带这一列的样子。可空、没有缺省:老连接一律「没被拒过」,和它们的真实状态一致。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(plugin_instances)"))}
        if columns and "authorization_rejected_at" not in columns:
            conn.execute(text("ALTER TABLE plugin_instances ADD COLUMN authorization_rejected_at DATETIME"))


def _migrate_plugin_instances() -> None:
    """插件从「一行 = 一个包 = 一次接入」拆成「包 → 实例 → 能力」三层。

    旧表 plugins 里的每一行都是"装了并且配好了的一次接入",所以逐行搬成:一个 package +
    一个 instance,凭据 / 授权 / 调用记录改挂 instance。

    **已发现的工具全部勾上**,不套新的"默认不暴露"。升级不该改变用户已经在界面上看到的
    东西 —— 那条规矩只对之后新建的实例生效。

    必须在 create_all **之前**跑重命名(否则 create_all 会建一张空的 plugin_packages,
    旧数据留在 plugins 里无人认领),但实例表要等 create_all 建好才能填 —— 所以这个函数
    只做重命名和列的准备,填充留给 _backfill_plugin_instances。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "plugins" not in tables or "plugin_packages" in tables:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plugins RENAME TO plugin_packages"))
        # 旧的子表按 plugin_id 挂着,重命名到一边等回填改挂 instance_id。
        for table in ("plugin_permission_grants", "plugin_credentials", "plugin_invocations"):
            if table in tables:
                conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_legacy"))


def _backfill_plugin_instances() -> None:
    """给每个包建一个默认实例,把旧的凭据 / 授权 / 调用记录搬过去。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "plugin_packages_legacy_done" in tables or "plugin_permission_grants_legacy" not in tables:
        return
    with engine.begin() as conn:
        packages = conn.execute(text("SELECT id, name FROM plugin_packages")).fetchall()
        enabled_col = "enabled" in {c["name"] for c in inspector.get_columns("plugin_packages")}
        for package_id, name in packages:
            enabled = 0
            if enabled_col:
                row = conn.execute(
                    text("SELECT enabled FROM plugin_packages WHERE id = :id"), {"id": package_id}
                ).fetchone()
                enabled = int(bool(row[0])) if row else 0
            instance_id = uuid.uuid4().hex
            tools = conn.execute(
                text("SELECT json_extract(manifest, '$._discovered_tools') FROM plugin_packages WHERE id = :id"),
                {"id": package_id},
            ).scalar()
            conn.execute(
                text(
                    "INSERT INTO plugin_instances (id, package_id, name, enabled, config, discovered_tools,"
                    " created_at, updated_at) VALUES (:i, :p, :n, :e, '{}', :t, :now, :now)"
                ),
                {"i": instance_id, "p": package_id, "n": name, "e": enabled, "t": tools or "[]", "now": now()},
            )
            # 已发现的工具全部勾上:升级不改变用户已经看到的东西。
            for tool in json.loads(tools or "[]"):
                if isinstance(tool, dict) and tool.get("name"):
                    conn.execute(
                        text("INSERT INTO plugin_capabilities (instance_id, tool_name, exposed) VALUES (:i, :t, 1)"),
                        {"i": instance_id, "t": tool["name"]},
                    )
            conn.execute(
                text(
                    "INSERT INTO plugin_permission_grants (instance_id, permission, granted, created_at, updated_at)"
                    " SELECT :i, permission, granted, created_at, updated_at"
                    " FROM plugin_permission_grants_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_credentials (instance_id, key, value, created_at, updated_at)"
                    " SELECT :i, key, value, created_at, updated_at"
                    " FROM plugin_credentials_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
            conn.execute(
                text(
                    "INSERT INTO plugin_invocations (id, instance_id, tool_name, status, input, output, error,"
                    " created_at) SELECT id, :i, tool_name, status, input, output, error, created_at"
                    " FROM plugin_invocations_legacy WHERE plugin_id = :p"
                ),
                {"i": instance_id, "p": package_id},
            )
        for table in ("plugin_permission_grants", "plugin_credentials", "plugin_invocations"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table}_legacy"))
        if enabled_col:
            conn.execute(text("ALTER TABLE plugin_packages DROP COLUMN enabled"))


def _migrate_line_fields_are_lists() -> None:
    """声明为「行列表」的字段(`"lines": True`,目前是生成节点的输入素材)从多行文本改成列表。

    规范形状变了(见 workflows/normalization.canonicalize_line_fields):某一行可以是一整串引用
    (`{{角色三视图.results}}`),插值后是一组,多行文本装不下它。保存和导入已经只写列表;库里已存的
    在这里一次转好,编辑器只认列表,不为旧的多行文本留分支。

    只改表示、不改语义(按行拆开,空行丢掉)。排在修订迁移之前:它会发现图变了,追加一份修订并
    校正摘要,不覆盖旧快照。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.normalization import canonicalize_line_fields

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            normalized = canonicalize_line_fields(graph, node_types=NODE_TYPES)
            if normalized != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(normalized, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_condition_literals_are_json() -> None:
    """条件节点两边手写的 `True` / `False` 改写成 `true` / `false`。

    值当文字用时此前是 `str()`:上游交来的布尔在条件里读作 `True`,用户照着看到的写了 `True`
    才对得上。现在统一写成 JSON(见 workflows.as_text),布尔读作 `true` —— 库里那些照旧写法
    写好的条件会从此永远不等。这里一次改好,条件节点不为旧写法留分支。

    只改**整格**就是这个字面量的(带引用、带别的字的不动),循环体 / 子图体里的一并改。排在修订
    迁移之前:它会发现图变了,追加一份修订。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    literals = {"True": "true", "False": "false"}

    def rewrite(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            if node.get("type") == "condition":
                for side in ("left", "right"):
                    value = config.get(side)
                    if isinstance(value, str) and value.strip() in literals:
                        config[side] = literals[value.strip()]
            for key, value in config.items():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes}

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            rewritten = rewrite(graph)
            if rewritten != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]},
                )


def _migrate_condition_edges_use_source_handle() -> None:
    """边上的 `branch` 键改写成 `source_handle`。

    全片生成模板里五条条件边写的是 `"branch": "true"`,而没有任何代码读 `branch`:它们能按
    「真」那一支跑,只是因为没写 handle 的条件边缺省就是真;画布上也就没有真 / 假的标记。
    模板已经改成 `source_handle`;从它装出来的那些工作流在这里一次改好,编辑器和引擎只认
    `source_handle` 一种写法。

    从会分支的节点出发、还没写 handle 的,`branch` 的值搬进 `source_handle`;其余的只是把这个
    没人读的键删掉。循环体 / 子图体里的一并改。

    **改完自己把修订对上。** 排在修订迁移之前只在「两步同一次启动里都没跑过」时有用;修订迁移
    早已记过账的机器上它不会再跑,而当前图和最新快照的摘要对不上的工作流是**跑不起来的**
    (wfErr_revisionDigestMismatch)。修订迁移本身是可重入的(图变了就追加一份修订),改完就调它。
    """
    if "workflows" not in set(inspect(engine).get_table_names()):
        return
    from app.domain.workflows import BRANCHING_NODE_TYPES

    def rewrite(graph: Any) -> Any:
        if not isinstance(graph, dict):
            return graph
        types = {
            str(node.get("id")): str(node.get("type"))
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        }
        edges = []
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict) or "branch" not in edge:
                edges.append(edge)
                continue
            moved = {key: value for key, value in edge.items() if key != "branch"}
            if types.get(str(edge.get("source"))) in BRANCHING_NODE_TYPES and not edge.get("source_handle"):
                moved["source_handle"] = str(edge["branch"])
            edges.append(moved)
        nodes = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                nodes.append(node)
                continue
            config = dict(node.get("config") or {})
            for key, value in config.items():
                if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                    config[key] = rewrite(value)
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
        return {**graph, "nodes": nodes, "edges": edges}

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, graph FROM workflows")).mappings().all()
        for row in rows:
            raw_graph = row["graph"]
            try:
                graph = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (TypeError, ValueError):
                continue
            if not isinstance(graph, dict):
                continue
            rewritten = rewrite(graph)
            if rewritten != graph:
                conn.execute(
                    text("UPDATE workflows SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps(rewritten, ensure_ascii=False), "id": row["id"]},
                )
    _migrate_workflow_revisions()


def _disable_tasks_bound_to_deleted_workflows() -> None:
    """绑着一张**已经删掉**的工作流、却还是「启用」的定时任务,停用。

    删工作流此前不管定时任务:任务仍是启用的,排程的到点照样触发、手动的照样能点「立即运行」,
    每一次都落一条「工作流不存在」的失败。删除路径现在会当场把它们停掉(scheduler.stop_tasks_bound_to_workflow),
    启用、触发也都先问一句跑不跑得起来 —— 库里已经留下的那些在这里一次停掉。

    只动开关和下次触发时刻,任务和它的运行记录都留着:删不删由人决定。别的工作区的同 id
    工作流不算「在」—— 执行体也不会去跑它。
    """
    present = set(inspect(engine).get_table_names())
    if not {"scheduled_tasks", "workflows"} <= present:
        return
    with engine.begin() as conn:
        existing = {(row[0], row[1]) for row in conn.execute(text("SELECT id, workspace_id FROM workflows"))}
        rows = conn.execute(
            text("SELECT id, workspace_id, payload FROM scheduled_tasks WHERE kind = 'workflow' AND enabled = 1")
        ).mappings().all()
        for row in rows:
            raw = row["payload"]
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                payload = None
            workflow_id = str(payload.get("workflow_id") or "") if isinstance(payload, dict) else ""
            if (workflow_id, row["workspace_id"]) in existing:
                continue
            conn.execute(
                text("UPDATE scheduled_tasks SET enabled = 0, next_run_at = NULL WHERE id = :id"),
                {"id": row["id"]},
            )
            logger.info("定时任务 %s 绑的工作流已不在,停用", row["id"])


def _migrate_job_keys_are_keys() -> None:
    """jobs 的 message_key / error_key 里只能是**文案 key**(或空)。

    改正之前(见 core/i18n.is_message_key),`WorkflowDomainError(str(exc))` 把第三方报错原文当 key,
    `blame()` 截成 80 字写进 error_key;读的时候拿它当模板 format,花括号一炸,整个执行历史接口 500。
    写入端已经不会再这么写了 —— 库里已有的那些在这里一次改掉,读取端只认新形状,不为旧行留分支。

    顺手救回失败原因:当年写 `error` 时,原文里花括号之后的部分被当成"填不上的占位符"抹掉了
    (只剩「调用 LLM失败:Error: 403」),而那半截"key"里还留着原文的前 80 个字 —— 比 `error`
    完整,就挪回 `error`。

    每次启动都跑、幂等:不变式是 key ∈ 文案表 ∪ {""},将来删掉某条文案时,引用它的旧行也会在
    这里被清掉(显示退回到落库时渲好的那句 message/error)。
    """
    from app.core.i18n import MESSAGES

    if "jobs" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, message_key, error_key, error FROM jobs WHERE message_key != '' OR error_key != ''")
        ).fetchall()
        for job_id, message_key, error_key, error in rows:
            if message_key and message_key not in MESSAGES:
                conn.execute(
                    text("UPDATE jobs SET message_key = '', message_params = '{}' WHERE id = :id"), {"id": job_id}
                )
            if error_key and error_key not in MESSAGES:
                recovered = error_key if len(error_key) > len(error or "") and error_key.startswith(error or "") else error
                conn.execute(
                    text("UPDATE jobs SET error_key = '', error_params = '{}', error = :error WHERE id = :id"),
                    {"error": recovered, "id": job_id},
                )


def _migrate_job_worker_leases() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if not columns:
            return
        for name, ddl in (
            ("lease_token", "ALTER TABLE jobs ADD COLUMN lease_token VARCHAR(64)"),
            ("lease_worker", "ALTER TABLE jobs ADD COLUMN lease_worker VARCHAR(64)"),
            ("lease_expires_at", "ALTER TABLE jobs ADD COLUMN lease_expires_at DATETIME"),
        ):
            if name not in columns:
                conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_status_lease_expires ON jobs(status, lease_expires_at)"))
        # **把最后半步走完。** 只加列不回填的话,那些"租约列还不存在时就已经 running"的行
        # 永远没有租约,于是读路径要长一条 `lease_expires_at IS NULL` 的兼容分支 ——
        # 而本仓库的规矩是不写兼容、旧数据用迁移(ADR-0006)。迁移停在最后一环之前,
        # 剩下的半步就变成了读路径上一条永久的税。
        #
        # 结局和 `expire_worker_leases` 对它们的处置一致:它们的执行器早就不在了
        # (这次升级重启过后端),判失败并说清原因。**不是重跑** —— 可能带副作用的活儿
        # 不自动重复,那是 jobs 模块从头就定的规矩。
        from app.domain.jobs import external_kinds

        #: `publish` 不在内:它有自己的一套认领(见 publish/worker),不走 job 的租约。
        kinds = [kind for kind in external_kinds() if kind != "publish"]
        if kinds and "error_key" in columns:
            placeholders = ", ".join(f":k{i}" for i in range(len(kinds)))
            conn.execute(
                text(
                    f"UPDATE jobs SET status = 'failed', error_key = 'jobErr_leaseExpired' "
                    f"WHERE status IN ('queued', 'running') AND lease_expires_at IS NULL "
                    f"AND kind IN ({placeholders})"
                ),
                {f"k{i}": kind for i, kind in enumerate(kinds)},
            )


def _migrate_model_structured_output() -> None:
    """模型行记得下「这个端点支不支持 json_schema」。

    此前没有任何地方写得下这件事,于是不支持的端点上 Schema 只是个事后本地校验,而用户看不出来 ——
    他在节点里写着 strict,实际跑的却是纯文本(见 domain/structured_output)。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_models)"))}
        if columns and "structured_output" not in columns:
            conn.execute(text("ALTER TABLE provider_models ADD COLUMN structured_output BOOLEAN"))


def _migrate_clip_offline_asset() -> None:
    """片段记住"素材曾经是什么"。

    在此之前,被时间线引用的素材**删不掉**(接口直接 422,让用户先去每条序列里找出来删掉)。
    现在删得掉了,引用它的片段转成脱机占位 —— 而占位要显示成什么,全靠这一列里的那份快照。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if columns and "offline_asset" not in columns:
            conn.execute(text("ALTER TABLE clips ADD COLUMN offline_asset JSON"))


def _migrate_browser_profile_start_url() -> None:
    """通用档案记下下次从哪一页开(见 BrowserProfile.start_url)。老档案留空 —— 它们从没记过。"""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(browser_profiles)"))}
        if columns and "start_url" not in columns:
            conn.execute(text("ALTER TABLE browser_profiles ADD COLUMN start_url VARCHAR(2000)"))


def _migrate_usage_unpriced_reason() -> None:
    """用量事件记下「为什么没能定价」(见 ProviderUsageEvent.unpriced_reason)。

    老事件留空 —— 它们当时没问过这个问题,也补不出来。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_usage_events)"))}
        if columns and "unpriced_reason" not in columns:
            conn.execute(text("ALTER TABLE provider_usage_events ADD COLUMN unpriced_reason VARCHAR(40)"))


def _migrate_pricing_time_prices() -> None:
    """计价规则带上分时段价格(见 domain/price_schedule)。

    老规则一律是「全天一个价」:时段为空列表、时区为空 —— 这正是它们一直以来的含义,不必猜。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(provider_pricing_rules)"))}
        if not columns:
            return
        if "time_prices" not in columns:
            conn.execute(text("ALTER TABLE provider_pricing_rules ADD COLUMN time_prices JSON NOT NULL DEFAULT '[]'"))
        if "time_zone" not in columns:
            conn.execute(text("ALTER TABLE provider_pricing_rules ADD COLUMN time_zone VARCHAR(64) NOT NULL DEFAULT ''"))


def _drop_plugin_packages_that_break_the_manifest_rules() -> None:
    """插件清单的形状收紧了(id / 声明的工具名 / 配置与凭据的键,见 domain/plugins/manifest):库里存着的包记录
    若违反新规矩,`manifest_of` 读它就抛 —— 插件页、智能体工具表、工作流节点面板对**所有人**报错。

    这样的包本来也跑不了:id 是插件目录名(`../x` 会装到插件目录外面)、带点的工具名进不了节点类型、
    叫 `path` 的配置项会顶掉插件进程的 PATH。删掉包记录(它的连接、凭据、授权、调用记录随外键级联),
    每删一个记一条警告说是哪个、为什么。**磁盘上的目录不动**:作者改好清单之后重新扫描,它就回来。

    规矩在这里原样写一份(迁移体是那一刻的快照,不随以后的清单规矩变)。幂等:删过的不会再出现。
    """
    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    import re

    plugin_id = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    tool_name = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    field_key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    reserved = {
        "PATH", "HOME", "LANG", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    }

    def why_broken(package_id: str, raw: Any) -> str:
        if not isinstance(raw, dict):
            return "manifest is not an object"
        declared_id = raw.get("id")
        for one in (package_id, declared_id.strip() if isinstance(declared_id, str) else ""):
            if not plugin_id.match(one):
                return f"invalid id {one!r}"
        tools = raw.get("tools")
        seen_tools: set[str] = set()
        for tool in (tools.get("declare") or []) if isinstance(tools, dict) else []:
            name = tool.get("name") if isinstance(tool, dict) else None
            if not isinstance(name, str):
                continue
            if not tool_name.match(name):
                return f"invalid tool name {name!r}"
            if name in seen_tools:
                return f"duplicate tool {name!r}"
            seen_tools.add(name)
        instance = raw.get("instance")
        seen_keys: set[str] = set()
        for group in ("config", "credentials"):
            fields = instance.get(group) if isinstance(instance, dict) else None
            for field in fields if isinstance(fields, list) else []:
                key = str(field.get("key") or "").strip() if isinstance(field, dict) else ""
                if not field_key.match(key):
                    continue  # 解析时本来就丢掉的键
                upper = key.upper()
                if upper in reserved or upper.startswith("MOSAEL_"):
                    return f"key {key!r} overrides a host environment variable"
                if upper in seen_keys:
                    return f"keys collide as {upper!r}"
                seen_keys.add(upper)
        return ""

    with engine.begin() as conn:
        for package_id, stored in conn.execute(text("SELECT id, manifest FROM plugin_packages")).all():
            try:
                raw = json.loads(stored) if isinstance(stored, str) else stored
            except ValueError:
                raw = None
            reason = why_broken(str(package_id), raw)
            if reason:
                logger.warning("插件包 %s 的清单不合新规矩(%s),删掉它的记录;改好清单后重新扫描即可", package_id, reason)
                conn.execute(text("DELETE FROM plugin_packages WHERE id = :id"), {"id": package_id})


def _create_current_schema() -> None:
    """The single boundary between migrations for existing tables and new-table creation."""

    Base.metadata.create_all(bind=engine)


def _steps(phase: MigrationPhase, *operations: Any) -> tuple[MigrationStep, ...]:
    """Give private Python operations stable, log-friendly migration identities.

    默认是**一次性**的:跑成功就记进 schema_migrations,下次启动跳过(见 migration_runner)。
    """

    return tuple(
        MigrationStep(operation.__name__.lstrip("_").replace("_", "-"), phase, operation)
        for operation in operations
    )


def _recurring(phase: MigrationPhase, *operations: Any) -> tuple[MigrationStep, ...]:
    """**对账**,不是迁移:每次启动都要跑,不记账。

    判据是「它处理的东西还会再出现」:孤儿共享记录会随新的删除再产生;job 的消息键要跟着
    文案表变;当前 schema 要为新表跑 create_all。而「把某列的旧形状转成新形状」只会有一次。
    """

    return tuple(
        MigrationStep(operation.__name__.lstrip("_").replace("_", "-"), phase, operation, once=False)
        for operation in operations
    )


def migration_plan() -> MigrationPlan:
    """Declare startup migration order in one validated plan.

    The function bodies remain historical snapshots next to the data shapes they understand.  This
    plan is the one place that decides *when* they run.  In particular, table renames and column
    additions that must see the old schema cannot accidentally drift past ``create-current-schema``.
    """

    return MigrationPlan(
        (
            *_steps(
                MigrationPhase.BEFORE_SCHEMA,
                # **它必须排在所有读 `users.is_deployment_admin` 的迁移之前。** 三条迁移
                # (connections-get-an-owner、plugin-instances-get-an-owner、provider-credentials)
                # 用「谁是部署管理员」回填归属,而加这一列的正是这一步 —— 它此前排在它们后面。
                # 在一个老到还没有这一列的库上,后端**启动就炸**在 `no such column:
                # is_deployment_admin`;这一路此前没有任何测试跑过(见
                # test_schema_migrations_cover_the_models)。它只碰 users,没有前置。
                _migrate_deployment_admin,
                _migrate_provider_capabilities,
                _migrate_provider_defaults_per_person,
                # It scans ENCRYPTED_COLUMNS; migrations above must first expose those columns.
                _migrate_encrypt_secrets,
                _migrate_deployment_config,
                _migrate_drop_deployment_defaults,
                _migrate_connections_get_an_owner,
                _migrate_plugin_instances_get_an_owner,
                _migrate_drop_the_knowledge_base,
                _migrate_hash_session_tokens,
                _migrate_client_version,
                _migrate_client_surface,
                _drop_publish_account_profile_name,
                _drop_clip_linked_clip_id,
                _migrate_browser_action_leases,
                _drop_reviews_table,
                _migrate_job_actor,
                _migrate_provider_credentials,
                _drop_shared_credentials,
                _migrate_tool_confirmations_session,
                _migrate_auth_session_expiry,
                _migrate_permission_modes,
                _drop_member_perm_overrides,
                _migrate_tts_pip_index,
                _migrate_agent_thinking_level,
                _migrate_agent_session_plan,
                _migrate_agent_session_groups,
                _migrate_session_groups_serve_both,
                # 它 ALTER 表并搬文件。**必须在 SCHEMA 之前** —— create_all 不会给已有的表补列,
                # 而 SCHEMA 之后 ORM 上的 Scene3DModel 已经指望 file_key 存在了。
                _migrate_scene_models_to_disk,
                # 紧跟着上一步:它搬的是上一步刚落到磁盘上的那些文件,而且同样要在 SCHEMA
                # 之前 —— create_all 不会把已有表的 scene_id 换成 workspace_id。
                _migrate_scene_models_to_workspace,
                _migrate_scene_cameras_become_objects,
                _migrate_source_assets_get_a_role,
                _migrate_workflow_source_assets,
                _migrate_plugin_registry_url,
                _migrate_generation_job_message_keys,
                _migrate_agent_session_order,
                _migrate_agent_notice_envelope_out_of_content,
                _drop_generation_models,
                _adopt_deepseek_vendor,
                _merge_split_vendors,
                _merge_openai_tts_engine,
                _migrate_job_parent,
                _migrate_job_worker_leases,
                _migrate_browser_pool,
                _migrate_clip_offline_asset,
                _migrate_model_structured_output,
                _migrate_browser_profile_start_url,
                _migrate_usage_unpriced_reason,
                _migrate_pricing_time_prices,
                _migrate_shared_host_folders,
                # Must precede schema creation or an empty plugin_packages table hides legacy data.
                _migrate_plugin_instances,
                # 排在上一步之后:它可能刚把 plugin_instances 建出来。
                _migrate_plugin_generation_columns,
                _migrate_plugin_authorization_rejected,
            ),
            #: create_all 每次启动都要跑 —— 新版本加的表靠它建出来,记账跳过就再也建不了。
            *_recurring(MigrationPhase.SCHEMA, _create_current_schema),
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_drop_local_publish_accounts,
                _migrate_board_revision,
                _migrate_comment_canvas_context,
                _migrate_agent_pending_view,
                _migrate_publish_task_claimed_by,
                _migrate_publish_task_post,
                _migrate_confirmation_summary_i18n,
                _migrate_board_canvas_state,
                _migrate_board_trim_slots_record_their_source,
                _migrate_board_sources_record_their_upstream,
                _migrate_board_frame_names_become_titles,
                _migrate_board_forms_name_their_producer,
                _migrate_board_wiring_tools_become_notes,
                _migrate_board_scene_render_shot_is_picked,
                # 排在上一步之后:它把镜头绑定搬进了表单,这一步再把表单搬到场景格上。
                _migrate_board_scene_cells_render_themselves,
                _backfill_browser_pool,
                _backfill_provider_models,
                _migrate_provider_default_model_fk,
                # The legacy columns are inputs to the two provider backfills above.
                _drop_legacy_profile_columns,
                _backfill_plugin_instances,
                _migrate_resource_ownership,
                _migrate_publish_task_options,
                _migrate_job_message_i18n,
                _migrate_prepared_publish_tasks,
                _migrate_track_role,
                _migrate_subtitle_tracks_carry_no_sound,
                _migrate_provider_model_capability_ref,
                _migrate_generation_capability_profiles,
                _migrate_prompt_requirement_becomes_one_field,
                _migrate_browser_boolean_options,
                _migrate_official_workflow_data_bindings,
                # 必须在 _migrate_workflow_revisions 之前:补完输出节点,下面那一步才会把
                # 这次语义改动记成一条新的不可变修订。
                _migrate_node_names_are_not_i18n_keys,
                _migrate_called_workflows_declare_their_output,
                _migrate_line_fields_are_lists,
                _migrate_condition_literals_are_json,
                _migrate_condition_edges_use_source_handle,
                _migrate_workflow_revisions,
                _disable_tasks_bound_to_deleted_workflows,
                # 排在所有会落修订的迁移之后:它们写下的那几版也要有作者。
                _backfill_workflow_revision_authors,
                # Projection comes last so rows synthesized by earlier migrations are visible
                # immediately, rather than waiting for the next application startup.
                _backfill_activity_events,
            ),
            #: 这两条是**对账**不是迁移:孤儿共享会随以后的删除再产生,job 的消息键要跟着文案表变。
            *_recurring(
                MigrationPhase.AFTER_SCHEMA,
                _cleanup_orphan_resource_shares,
                _migrate_job_keys_are_keys,
                # 随应用发的插件每个版本都可能变(见 domain/plugins/bundled)。排在所有一次性迁移
                # 之后、而且在要用到它的包记录的那些迁移之前。
                _install_bundled_plugins,
            ),
            #: 要用到上一步刚装好的 ComfyUI 插件包(ADR 0020)。
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_comfyui_connections_become_plugin_instances,
                # MiniMax 音乐撤掉(ADR 0022 补充):清掉存着的指向。
                _remove_minimax_music_models,
                # Blender 连接的 `::1` 从来连不上(上游两头都是 IPv4 套接字),改成 127.0.0.1。
                _migrate_blender_host_is_ipv4,
                # 清单形状收紧之后,库里违反新规矩的包记录删掉(否则读它就抛,插件页对所有人报错)。
                _drop_plugin_packages_that_break_the_manifest_rules,
                # 四个对象存储插件合成随应用内置的「对象存储」:要用到上面刚装好的那个包。
                _merge_object_storage_plugins,
                # ComfyUI 插件删掉了通用的 run_workflow:清掉只挂着这个工具名的开关和会话放行;
                # 存着的节点由下面的对账按插件报出的清单改。
                _forget_comfyui_run_workflow_tool,
                # 生成能力要有正面证据:没写能力的模型行按新规则落成显式标签。排在 ComfyUI 那几步之后 ——
                # 插件连接的模型行由它们建好、自带能力,这里一概不碰。
                _migrate_generation_capabilities_need_evidence,
                # 3D 场景页建的画板绕开了新建格子的缺省,空槽没写产出者:按 normalize 那条规则补一遍。
                _migrate_board_empty_slots_name_their_producer,
            ),
            #: 对账:插件报出的新工具取代了老工具时,存着的老节点改写过去(依据是缓存的工具清单,它会变)。
            *_recurring(MigrationPhase.AFTER_SCHEMA, _rewrite_replaced_plugin_tools),
            *_steps(
                MigrationPhase.FILESYSTEM,
                _migrate_shared_venvs,
                _migrate_thumbnails_keep_transparency,
                _migrate_mov_videos_become_mp4,
                _migrate_frame_rate_is_not_a_time_base,
            ),
            #: 对账:随包解释器换次版本后,旧 venv 跑不起来了。放在搬共用 venv 之后,搬过来的也要过这一道。
            *_recurring(MigrationPhase.FILESYSTEM, _drop_venvs_built_on_another_python),
        )
    )

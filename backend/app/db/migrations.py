"""建表与历史数据迁移 —— **依赖序的顶端**,爱 import 谁 import 谁。

从 `app/core/db.py` 搬出来的。那里是被所有人 import 的底座,而迁移必须认识领域层
(声音克隆的共用 venv 往哪搬、插件表怎么拆成包/实例/能力),两者方向相反。挤在一个模块
里的那段时间,这些 import 只能写在函数体里把环推迟到运行时;搬出来之后写在文件顶上即可。

**新增迁移就写在这里,并挂进 `init_db()`** —— 顺序有讲究,函数各自的 docstring 说明了
自己必须排在 create_all 之前还是之后。仓库不用 alembic:每条迁移都先探 schema 再动手
(见各函数开头的 `inspect(engine)`),重复跑是安全的。

**只保留滚动支持窗口内的迁移**:最早支持版本是最新公开版往前 8 个版本序号(见
`app.db.support_window`)。更早版本已经跑过的步骤在发版推进门槛时退休,不在读取期保留分支。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.db import Base, PARTITION_PREFIX, engine
from app.db.migration_runner import MigrationPhase, MigrationPlan, MigrationStep
from app.db.safety import DATABASE_SCHEMA_VERSION, mark_database_version, snapshot_before_upgrade

logger = logging.getLogger(__name__)


def _migrate_tool_confirmations_make_tool_calls_idempotent() -> None:
    """一次对话里的一个 tool_call_id 只能开一张卡；空 id 的外部调用不受限制。

    旧版本可能已经留下重复卡。保留最早那张的关联，其余历史卡仍在，但不再冒充那次调用的
    唯一确认单；这样升级能建立唯一索引，新重试也不会再放大旧重复。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    if "tool_call_id" not in {column["name"] for column in inspector.get_columns("tool_confirmations")}:
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE tool_confirmations SET tool_call_id = NULL "
            "WHERE session_id IS NOT NULL AND tool_call_id IS NOT NULL "
            "AND rowid NOT IN ("
            "SELECT MIN(rowid) FROM tool_confirmations "
            "WHERE session_id IS NOT NULL AND tool_call_id IS NOT NULL "
            "GROUP BY session_id, tool_call_id)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_confirmations_session_tool_call "
            "ON tool_confirmations (session_id, tool_call_id) "
            "WHERE session_id IS NOT NULL AND tool_call_id IS NOT NULL"
        ))


def _migrate_tool_confirmations_feishu_message_id() -> None:
    """tool_confirmations 新增 feishu_message_id:工具确认卡发到飞书后的消息 id。

    回调超时、应用内批准、会话过期时用它把原卡换成结果态。老卡留空 —— 没有消息 id
    就无法安全地就地更新,不猜、不回填。
    """
    inspector = inspect(engine)
    if "tool_confirmations" not in set(inspector.get_table_names()):
        return
    if "feishu_message_id" in {c["name"] for c in inspector.get_columns("tool_confirmations")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tool_confirmations ADD COLUMN feishu_message_id VARCHAR(128)"))


def _migrate_agent_questions_feishu_message_id() -> None:
    """agent_questions 新增 feishu_message_id:选择卡发到飞书后的消息 id。

    回答、跳过、过期时用它把原卡换成结果态;老问题卡留空。
    """
    inspector = inspect(engine)
    if "agent_questions" not in set(inspector.get_table_names()):
        return
    if "feishu_message_id" in {c["name"] for c in inspector.get_columns("agent_questions")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_questions ADD COLUMN feishu_message_id VARCHAR(128)"))


def _migrate_update_feed_url() -> None:
    """deployment_config 新增 update_feed_url(应用更新包下载根地址)。空串 = 只用 GitHub Releases。

    create_all 只建新表,不给已有表补列;加列要在 SCHEMA 之前。幂等。
    """
    inspector = inspect(engine)
    if "deployment_config" not in set(inspector.get_table_names()):
        return
    if "update_feed_url" in {c["name"] for c in inspector.get_columns("deployment_config")}:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN update_feed_url VARCHAR(500) NOT NULL DEFAULT ''"))


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


def _migrate_bound_profiles_use_the_account_partition() -> None:
    """把「绑定了发布账号的浏览器档案」的分区改回**那个账号的规范分区**。

    现场(2026-10-22):同一个抖音账号有两份分区 —— 发布账号登录落在
    `persist:mosael-<accountId>`(真正的 sessionid 就在这儿),而浏览器池档案的 `partition`
    还指着一个历史前缀 `persist:openstudio-<accountId>`(里面只有 `sid_guard` 这类不认证的票据)。
    于是:账号池卡片显示「已登录」(那是发布账号的 binding_status)、点「打开」走发布账号的视图
    也是登录态,但**智能体经浏览器池开会话**打开的是那份旧分区 —— 平台让他登录。

    这正是 contracts/shared-constants.json 里 `publish_partition_prefix` 警告过的那种事故:
    改前缀之后,已登录账号的 cookie「凭空消失」,而且不会有任何报错。

    幂等:只改「挂着的账号还在、且分区不等于规范值」的那几行。
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "publish_accounts" not in tables or "browser_profiles" not in tables:
        return
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT a.id AS account_id, a.profile_id AS profile_id, p.\"partition\" AS partition "
                "FROM publish_accounts a JOIN browser_profiles p ON p.id = a.profile_id "
                "WHERE a.profile_id IS NOT NULL"
            )
        ).fetchall()
        for row in rows:
            canonical = f"persist:{PARTITION_PREFIX}-{row.account_id}"
            if (row.partition or "") == canonical:
                continue
            conn.execute(
                text('UPDATE browser_profiles SET "partition" = :part, updated_at = CURRENT_TIMESTAMP WHERE id = :pid'),
                {"part": canonical, "pid": row.profile_id},
            )


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


def _upgrade_stored_plugin_manifests() -> None:
    """包记录里存着的清单跟着清单迁移链(mosael_formats.plugin_manifest_upgrade)升到当前版本。

    **对账,不是迁移**:清单版本随哪一版应用都可能 +1。磁盘上的清单只在扫描时升,而扫描要人点「扫描插件」
    或装包才跑;在那之前读的一直是记录里存的那份。清单规则收紧时(Manim 0.2 的 `PIP_INDEX_URL` 配置项成了
    宿主占着的名字),那份就解析不过 —— 插件页、智能体会话、工作流一碰到插件就 500。

    只动记录:`_path` 是扫描写进去的运行时字段,迁移链会清掉它,这里放回去。磁盘那份下次扫描时由同一串步骤改。
    """
    from app.domain.plugins.manifest import PATH_KEY
    from app.domain.plugins.migrations import upgrade

    if "plugin_packages" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as conn:
        for package_id, stored in conn.execute(text("SELECT id, manifest FROM plugin_packages")).fetchall():
            try:
                raw = json.loads(stored) if isinstance(stored, str) else dict(stored or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            path = raw.get(PATH_KEY)
            if not upgrade(raw):
                continue
            if path:
                raw[PATH_KEY] = path
            conn.execute(
                text("UPDATE plugin_packages SET manifest = :m WHERE id = :i"),
                {"m": json.dumps(raw, ensure_ascii=False), "i": package_id},
            )


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


def _rewrite_replaced_plugin_tools() -> None:
    """工作流里、画板上(内容格的能力、空格子上的生成器)存着的、已被插件运行时报出的新工具取代的老插件节点,改写成新工具(见
    domain/workflows/plugin_references 与 domain/boards/plugin_references)。ComfyUI 的 `run_workflow` + 某张工作流 → 那张工作流自己的工具。
    老工具已经从插件里删掉了的(ComfyUI 的 `run_workflow` 就是),新工具上没有位置的格子丢掉、记进修订说明 ——
    留着一个跑不起来的节点不是保住了用户的值。

    **对账,不是一次性迁移**:依据是插件上一次报出的工具清单(缓存在 `plugin_instances.discovered_tools`),
    清单会变(用户在 ComfyUI 里新存了工作流),新出现的对应关系下次启动也该迁;清单刷新时同一个函数也会跑。
    没有可迁的就什么都不做。

    画板上还多一件:工具声明了 `mirrors`(和一个生成模型是同一件事)、连接的主人用得上那个模型时,空格子上存着的
    这个生成器改挂生成、选那个模型(见 domain/boards/plugin_references 的「被生成取代的生成器」)。同一个道理是对账:
    `mirrors` 只在插件报出清单之后才有。
    """
    from sqlalchemy.orm import Session

    from app.domain.boards import plugin_references as board_references
    from app.domain.workflows import plugin_references

    if not {"plugin_instances", "workflows", "workflow_revisions", "boards"} <= set(inspect(engine).get_table_names()):
        return
    with Session(engine) as db:
        plugin_references.rewrite_replaced_tools(db)
        board_references.reconcile_plugin_tool_cells(db)


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


def _migrate_publish_tasks_get_content_shape() -> None:
    """发布任务从「一份视频」变成「三种内容形状」(ADR 0076,见 domain/publish)。

    **迁移一次、之后只有一种形状**:`content_kind` 一律有值(默认 video),`asset_ids` 一律装
    着这份任务的素材(单份视频就是它自己的 id)。此前读的一侧还带着「`asset_ids` 为空就回退到
    `[asset_id]`」的运行时分支 —— 那让"老任务"永远活着,读代码的人得同时想两种数据。
    现在回填到底,读的一侧只认 `asset_ids`。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(publish_tasks)"))}
        if not columns:
            return
        if "content_kind" not in columns:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN content_kind VARCHAR(20) NOT NULL DEFAULT 'video'"))
        if "asset_ids" not in columns:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN asset_ids JSON NOT NULL DEFAULT '[]'"))
        if "body" not in columns:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN body TEXT NOT NULL DEFAULT ''"))
        if "media_meta" not in columns:
            conn.execute(text("ALTER TABLE publish_tasks ADD COLUMN media_meta JSON NOT NULL DEFAULT '{}'"))
        #: 回填:`asset_ids` 为空而有 `asset_id` 的行,把那一份写进去(单素材任务的唯一形状)。
        rows = conn.execute(
            text("SELECT id, asset_id, asset_ids, content_kind FROM publish_tasks"),
        ).fetchall()
        for task_id, asset_id, raw_ids, content_kind in rows:
            #: 这一行是**裸文本**(迁移直接走 SQL,不经过 ORM 的 JSON 列):`'[]'` 是个非空字符串,
            #: 拿它当布尔判会以为"已经有素材了"。先解成列表再看。
            try:
                current_ids = json.loads(raw_ids) if raw_ids else []
            except (TypeError, ValueError):
                current_ids = []
            updates: dict[str, Any] = {}
            if (not current_ids) and asset_id:
                updates["asset_ids"] = json.dumps([asset_id])
            if not content_kind:
                updates["content_kind"] = "video"
            if updates:
                assignments = ", ".join(f"{key} = :{key}" for key in updates)
                conn.execute(text(f"UPDATE publish_tasks SET {assignments} WHERE id = :id"), {**updates, "id": task_id})
        #: 迁移之后这两种形状不该再出现:出现了就是这条迁移的漏洞,当场说出来,别留给运行时猜。
        leftovers = conn.execute(
            text("SELECT COUNT(*) FROM publish_tasks WHERE asset_ids = '[]' AND asset_id IS NOT NULL"),
        ).scalar()
        if leftovers:
            #: 迁移内部的硬失败(不是给用户看的报错):留给运行时猜更糟,宁可启动时就炸。
            raise RuntimeError(
                f"publish_tasks migration incomplete: {leftovers} row(s) have asset_id but empty asset_ids",
            )


def _migrate_workflow_publish_nodes_get_content_kind() -> None:
    """工作流里的发布节点补上 `content_kind`(ADR 0076)。

    节点声明里有默认值,但那是**新建节点**的默认;已经存下来的图里没有这个键。执行器不再写
    「没填就当 video」这种回退(回退会让"旧图"永远活着,读代码要同时想两种),所以在这里一次补齐:
    没有 `content_kind` 的发布节点写成 `video` —— 它们当初只能是视频。
    """
    with engine.begin() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "workflows" not in tables:
            return
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(workflows)"))}
        json_columns = [name for name in ("graph", "nodes", "definition") if name in columns]
        for column in json_columns:
            for workflow_id, raw in conn.execute(text(f"SELECT id, {column} FROM workflows")).fetchall():
                if not raw:
                    continue
                try:
                    doc = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                changed = _backfill_publish_nodes(doc)
                if changed:
                    conn.execute(
                        text(f"UPDATE workflows SET {column} = :doc WHERE id = :id"),
                        {"doc": json.dumps(doc, ensure_ascii=False), "id": workflow_id},
                    )


def _backfill_publish_nodes(doc: Any) -> bool:
    """把一处 JSON 文档里所有 publish 节点的 `config.content_kind` 补成 `video`;返回有没有改动。"""
    if isinstance(doc, dict):
        changed = False
        if doc.get("type") == "publish":
            config = doc.get("config")
            if isinstance(config, dict) and not config.get("content_kind"):
                config["content_kind"] = "video"
                changed = True
        for value in doc.values():
            changed = _backfill_publish_nodes(value) or changed
        return changed
    if isinstance(doc, list):
        return any(_backfill_publish_nodes(one) for one in doc)
    return False


def _migrate_browser_profiles_pin_identity() -> None:
    """档案记下自己的浏览器身份(见 BrowserProfile.identity)。

    已有的档案**留空** —— 空 = 跟着平台的规矩走,与迁移前行为一致。这一列是给「把身份钉在账号上」
    留的入口:全局改一次身份会把所有已登录账号的样子一起换掉(2026-10-22 两次事故的根)。
    """
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(browser_profiles)"))}
        if columns and "identity" not in columns:
            conn.execute(text("ALTER TABLE browser_profiles ADD COLUMN identity VARCHAR(20)"))


def _rewrite_workflow_graphs(rewrite: Any, note: Any, *, only: Any = None) -> int:
    """把每个工作流的当前图过一遍 `rewrite`(连同循环体 / 子图,由 `rewrite` 自己走);变了的追加一版修订。

    修订表建好之后的图迁移都得这么落(`workflows.graph` 是最新修订的投影,只改投影会让两边对不上):
    作者沿用上一版,认可过上一版的人照样为这一版担保 —— 机械改写不换担保人,也不该让跑得好好的流程停下来等人认可
    (同 domain/workflows/plugin_references)。`only(workflow)` 给了的话,只看它说是的那些。`note` 可以是一个函数
    (改写前的图 → 说明),说明里要点名这一张图里的哪几个节点时用。
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Workflow, WorkflowRevisionAttestation
    from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision, revision_vouchers

    changed = 0
    with Session(engine) as db:
        for workflow in db.scalars(select(Workflow)).all():
            if only is not None and not only(workflow):
                continue
            if rewrite(json.loads(json.dumps(workflow.graph))) == workflow.graph:
                continue
            previous = current_workflow_revision(db, workflow)
            vouchers = revision_vouchers(db, previous)
            revision = commit_graph_revision(
                db, workflow, rewrite, source="migration", created_by=previous.created_by,
                note=note(workflow.graph) if callable(note) else note,
            )
            if revision is not None:
                for user in vouchers - {revision.created_by}:
                    db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=user))
                changed += 1
        db.commit()
    return changed


def _plugin_array_inputs_follow_their_declarations() -> None:
    """对账:插件节点的数组入参还存成「名字 → 值」对象的,按插件**此刻**报出的声明改成值的列表。

    一次性的那条(migrate-plugin-array-inputs-are-lists)只改得了它跑的那一刻认得出的 —— 那一刻连接停着、
    工具清单还没报上来的,节点原样留下,跑的时候交给插件的还是一个对象。清单会变,所以这是对账:每次启动按
    当前的声明(plugins.nodes 的节点类型,数组是 `"type": "list"`)走一遍规范化里的同一步
    (normalization.canonicalize_list_fields);没有可改的就什么都不做。改了的落一版修订,作者和担保人沿用上一版。
    """
    if not {"workflows", "workflow_revisions", "plugin_instances"} <= set(inspect(engine).get_table_names()):
        return
    from sqlalchemy.orm import Session

    from app.domain.plugins.nodes import plugin_node_types
    from app.domain.workflows.normalization import canonicalize_list_fields

    with Session(engine) as db:
        types = plugin_node_types(db)
    if not any(
        isinstance(spec, dict) and spec.get("type") == "list"
        for declared in types.values()
        for spec in (declared.get("config") or {}).values()
    ):
        return
    _rewrite_workflow_graphs(
        lambda graph: canonicalize_list_fields(graph, node_types=types),
        "插件节点的数组入参改成一行一项:存成「名字 → 值」的,按顺序改成值的列表",
    )


def _reindex_record_references() -> None:
    """引用表(record_references)是派生数据:抽取规则一变,整张按新规则重建。"""
    from app.db.references import reindex

    with engine.begin() as conn:
        reindex(conn)


def _create_current_schema() -> None:
    """The single boundary between migrations for existing tables and new-table creation."""

    from app.db.agent_turn_events import TURN_EVENTS

    Base.metadata.create_all(bind=engine)
    #: 事件表故意不进 Base.metadata(它不是领域实体),但新装机也必须有;旧库已存在时 checkfirst 空操作。
    TURN_EVENTS.create(engine, checkfirst=True)
    for index in TURN_EVENTS.indexes:
        index.create(engine, checkfirst=True)


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
    """Startup migration plan inside the rolling v2.0.0+ support window.

    Only migrations added after the oldest supported Release remain one-time steps; older
    shapes are already reached by upgrading through that Release. Recurring reconciliation
    stays. See ADR-0006 and CONTEXT.md for the eight-release support window.
    """
    return MigrationPlan((
        *_steps(
            MigrationPhase.BEFORE_SCHEMA,
            _migrate_update_feed_url,
            _migrate_publish_tasks_get_content_shape,
            _migrate_workflow_publish_nodes_get_content_kind,
            _migrate_browser_profiles_pin_identity,
            _migrate_tool_confirmations_make_tool_calls_idempotent,
            _migrate_tool_confirmations_feishu_message_id,
            _migrate_agent_questions_feishu_message_id,
        ),
        *_recurring(
            MigrationPhase.SCHEMA,
            _create_current_schema,
        ),
        *_recurring(
            MigrationPhase.AFTER_SCHEMA,
            _cleanup_orphan_resource_shares,
            _migrate_job_keys_are_keys,
            _upgrade_stored_plugin_manifests,
            _install_bundled_plugins,
            _rewrite_replaced_plugin_tools,
            _plugin_array_inputs_follow_their_declarations,
        ),
        *_steps(
            MigrationPhase.AFTER_SCHEMA,
            _migrate_bound_profiles_use_the_account_partition,
        ),
        *_recurring(
            MigrationPhase.AFTER_SCHEMA,
            _reindex_record_references,
        ),
        *_recurring(
            MigrationPhase.FILESYSTEM,
            _drop_venvs_built_on_another_python,
        ),
    ))

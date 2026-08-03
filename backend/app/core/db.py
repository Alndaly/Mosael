from __future__ import annotations

import logging
from collections.abc import Generator

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import LOGIN_SESSION_TTL, settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


#: 发布账号登录分区的命名前缀(完整分区名 = persist:<PARTITION_PREFIX>-<accountId>)。
#: 与 electron/publish/accountViews.ts 的同名约定必须一致——两边拼的是同一个磁盘目录。
PARTITION_PREFIX = "openstudio"
#: 更名前的完整分区前缀。**别把它跟着全局替换一起改掉** —— 它是迁移的"匹配老数据"那一侧,
#: 改成新名会让迁移变成一条什么都不匹配的空语句(已经踩过一次,由测试兜住)。
_LEGACY_PARTITION_PREFIX_FULL = "persist:mibu-"


settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()




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


def _migrate_resource_ownership() -> None:
    """五张表补 `owner_user_id`,并给每条已存在的记录建一行「共享给它当前所在的工作区」。

    **升级前后行为完全一致**:今天同工作区的人看得见的,升级之后仍然看得见;而**从此以后新建的
    默认私有**(见 domain/sharing.KINDS)。不这么做的话,升级会把同事的发布账号、浏览器档案、
    对话从他们眼前一次性拿走 —— 那不是收紧权限,那是弄坏了正在用的东西。

    归属回填成**该工作区的 owner**:老数据里没有记谁建的,而工作区的 owner 是现在对它们负责的人。
    幂等:只填空的那些,共享行靠唯一约束去重。
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
    for table in kinds.values():
        if table not in tables:
            continue
        if "owner_user_id" not in {c["name"] for c in inspector.get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_user_id VARCHAR(64)"))
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

    老库里那一行是**整个部署共用的默认**,迁移把它就地变成 `owner_user_id = ''` 那一行 ——
    也就是"还没设过的人用这个"。升级前后行为一致:所有人看到的默认还是同一个;而从此以后
    每个人可以设自己的(见 db.models.ProviderDefault)。

    SQLite 改不了主键,所以按重建表的老办法:建新表 → 搬数据 → 换名。
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
        conn.execute(
            text(
                "INSERT INTO provider_defaults_new "
                "(capability, owner_user_id, provider_profile_id, model, provider_model_id, updated_at) "
                "SELECT capability, '', provider_profile_id, model, provider_model_id, updated_at "
                "FROM provider_defaults"
            )
        )
        conn.execute(text("DROP TABLE provider_defaults"))
        conn.execute(text("ALTER TABLE provider_defaults_new RENAME TO provider_defaults"))


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

    升级前所有人共用档案行上那把钥匙。迁移把它变成**最早那位部署管理员的一条共享凭据**,于是
    升级前后所有人照样能用;而从此以后每个人可以带自己的(见 domain/provider_credentials)。

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
                ("shared", "ALTER TABLE provider_credentials ADD COLUMN shared BOOLEAN NOT NULL DEFAULT 0"),
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
                        " credential_version, shared, created_at, updated_at) "
                        "VALUES (:pid, :uid, :key, :oauth, '{}', :catalog, :version, 1, :now, :now)"
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

    引擎 id 不只是个显示名:audio/voices.py 拿它当 vendor 去 resolve_profile,所以它同时
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


def _migrate_partition_rename() -> None:
    """更名:登录分区 persist:mibu-<id> → persist:openstudio-<id>。

    分区名是登录态的地址(Electron 把 cookie/localStorage 存在 userData/Partitions/<名字> 下),
    所以这里只改「数据库里记的地址」,**磁盘目录由 Electron 在真正用到该分区的那一刻惰性改名**
    (见 electron/publish/accountViews.ts)。分两处、按需迁移,而不是要求两个进程同时改完——
    否则谁先谁后都可能出现"库里指向新名、磁盘还是老名"的空窗,表现为全部平台登录失效。
    幂等:只匹配老前缀。"""
    inspector = inspect(engine)
    if "browser_profiles" not in set(inspector.get_table_names()):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                'UPDATE browser_profiles SET "partition" = :new || substr("partition", :cut) '
                'WHERE "partition" LIKE :old'
            ),
            {
                "new": f"persist:{PARTITION_PREFIX}-",
                "cut": len(_LEGACY_PARTITION_PREFIX_FULL) + 1,
                "old": f"{_LEGACY_PARTITION_PREFIX_FULL}%",
            },
        )


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


def init_db() -> None:
    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    _migrate_provider_capabilities()
    _migrate_provider_defaults_per_person()
    # 最后跑:它按 ENCRYPTED_COLUMNS 扫列,前面的迁移得先把列都补齐。
    _migrate_encrypt_secrets()
    _migrate_job_actor()
    _migrate_provider_credentials()
    _migrate_tool_confirmations_session()
    _migrate_auth_session_expiry()
    _migrate_permission_modes()
    _migrate_deployment_admin()
    _drop_member_perm_overrides()
    _migrate_tts_pip_index()
    _migrate_agent_thinking_level()
    _migrate_agent_session_plan()
    _drop_generation_models()
    _adopt_deepseek_vendor()
    _merge_split_vendors()
    _merge_openai_tts_engine()
    _migrate_job_parent()
    _migrate_browser_pool()
    # 重命名必须在 create_all 之前:否则它会建一张空的 plugin_packages,旧数据无人认领。
    _migrate_plugin_instances()
    Base.metadata.create_all(bind=engine)
    _migrate_partition_rename()
    _migrate_drop_local_publish_accounts()
    _backfill_browser_pool()
    # 必须在 create_all 之后:provider_models 是新表,之前还不存在。
    _backfill_provider_models()
    _migrate_provider_default_model_fk()
    # 回填与外键都落定之后再删旧列 —— 它们正是回填的输入。
    _drop_legacy_profile_columns()
    # 实例表由 create_all 建好之后才能填。
    _backfill_plugin_instances()
    # 必须在 create_all 之后:resource_shares 是新表。
    _migrate_resource_ownership()


def now() -> datetime:
    return datetime.utcnow()


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


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

"""建表与历史数据迁移 —— **依赖序的顶端**,爱 import 谁 import 谁。

从 `app/core/db.py` 搬出来的。那里是被所有人 import 的底座,而迁移必须认识领域层
(声音克隆的共用 venv 往哪搬、插件表怎么拆成包/实例/能力),两者方向相反。挤在一个模块
里的那段时间,这些 import 只能写在函数体里把环推迟到运行时;搬出来之后写在文件顶上即可。

**新增迁移就写在这里,并挂进 `init_db()`** —— 顺序有讲究,函数各自的 docstring 说明了
自己必须排在 create_all 之前还是之后。仓库不用 alembic:每条迁移都先探 schema 再动手
(见各函数开头的 `inspect(engine)`),重复跑是安全的。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, text

from app.core.config import LOGIN_SESSION_TTL, settings
from app.core.db import Base, PARTITION_PREFIX, engine, now
from app.core.tokens import TOKEN_SCHEME, token_digest
from app.db.migration_runner import MigrationPhase, MigrationPlan, MigrationStep

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
    """jobs 新增 message_key / message_params(任务消息的多语言)。

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
    加一串十六进制。现在信封只在拼提示词时加(见 ai/agent/host.agent_notice_envelope),
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


def init_db() -> None:
    """Prepare storage, then execute the validated startup migration plan."""

    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    migration_plan().run()


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


def _create_current_schema() -> None:
    """The single boundary between migrations for existing tables and new-table creation."""

    Base.metadata.create_all(bind=engine)


def _steps(phase: MigrationPhase, *operations: Any) -> tuple[MigrationStep, ...]:
    """Give private Python operations stable, log-friendly migration identities."""

    return tuple(
        MigrationStep(operation.__name__.lstrip("_").replace("_", "-"), phase, operation)
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
                _migrate_job_actor,
                _migrate_provider_credentials,
                _drop_shared_credentials,
                _migrate_tool_confirmations_session,
                _migrate_auth_session_expiry,
                _migrate_permission_modes,
                _migrate_deployment_admin,
                _drop_member_perm_overrides,
                _migrate_tts_pip_index,
                _migrate_agent_thinking_level,
                _migrate_agent_session_plan,
                _migrate_agent_session_groups,
                _migrate_session_groups_serve_both,
                _migrate_source_assets_get_a_role,
                _migrate_workflow_source_assets,
                _migrate_plugin_registry_url,
                _cleanup_orphan_resource_shares,
                _migrate_generation_job_message_keys,
                _migrate_agent_session_order,
                _migrate_agent_notice_envelope_out_of_content,
                _drop_generation_models,
                _adopt_deepseek_vendor,
                _merge_split_vendors,
                _merge_openai_tts_engine,
                _migrate_job_parent,
                _migrate_browser_pool,
                # Must precede schema creation or an empty plugin_packages table hides legacy data.
                _migrate_plugin_instances,
            ),
            MigrationStep(
                "create-current-schema",
                MigrationPhase.SCHEMA,
                _create_current_schema,
            ),
            *_steps(
                MigrationPhase.AFTER_SCHEMA,
                _migrate_drop_local_publish_accounts,
                _migrate_board_canvas_state,
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
                _migrate_browser_boolean_options,
            ),
            *_steps(MigrationPhase.FILESYSTEM, _migrate_shared_venvs),
        )
    )

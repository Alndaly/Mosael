from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


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


def _migrate_kb_schema() -> None:
    """KB 彻底重写(Dify 式 datasets):项目未上线,旧 kb 表直接删表重建。
    以「kb_documents 是否有 dataset_id 列」判定旧结构 —— 比按表存在判定更稳,
    能修复「kb_datasets 已建但 kb_documents 仍是旧列」的半迁移中间态。create_all 随后重建。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "kb_documents" not in tables:
        return
    columns = {col["name"] for col in inspector.get_columns("kb_documents")}
    if "dataset_id" not in columns:  # 旧结构 → 全量删表重建
        with engine.begin() as conn:
            for table in ("kb_chunks_fts", "kb_chunks", "kb_documents", "kb_datasets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


def _migrate_generation_job_detach() -> None:
    """generation_jobs.job_id 从 CASCADE 改 SET NULL + 可空。

    生成记录是创作历史;此前挂在 job 上级联,任务中心「清空已完成」一删 job,
    整段生成历史跟着蒸发(真丢过)。SQLite 改不了既有外键,整表重建搬运。
    pragma foreign_keys 在事务内改无效,走底层 DBAPI 连接手动收发事务。"""
    inspector = inspect(engine)
    if "generation_jobs" not in set(inspector.get_table_names()):
        return
    with engine.connect() as conn:
        fks = conn.exec_driver_sql("PRAGMA foreign_key_list(generation_jobs)").fetchall()
        # 行结构: (id, seq, table, from, to, on_update, on_delete, match)
        job_fk = next((fk for fk in fks if fk[3] == "job_id"), None)
        if job_fk is None or str(job_fk[6]).upper() == "SET NULL":
            return
        raw = conn.connection.dbapi_connection
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            raw.execute("BEGIN")
            raw.execute(
                """
                CREATE TABLE generation_jobs_new (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    workspace_id VARCHAR NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    session_id VARCHAR(64) REFERENCES generation_sessions(id) ON DELETE CASCADE,
                    job_id VARCHAR REFERENCES jobs(id) ON DELETE SET NULL,
                    provider_profile_id VARCHAR(64) REFERENCES provider_profiles(id) ON DELETE SET NULL,
                    provider VARCHAR(80) NOT NULL,
                    model VARCHAR(120) NOT NULL,
                    kind VARCHAR(24) NOT NULL,
                    request JSON NOT NULL,
                    result_asset_id VARCHAR REFERENCES assets(id) ON DELETE SET NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            raw.execute(
                "INSERT INTO generation_jobs_new SELECT id, workspace_id, session_id, job_id, provider_profile_id,"
                " provider, model, kind, request, result_asset_id, created_at, updated_at FROM generation_jobs"
            )
            raw.execute("DROP TABLE generation_jobs")
            raw.execute("ALTER TABLE generation_jobs_new RENAME TO generation_jobs")
            raw.execute("COMMIT")
        except Exception:
            raw.execute("ROLLBACK")
            raise
        finally:
            raw.execute("PRAGMA foreign_keys=ON")


def _migrate_agent_sessions() -> None:
    """加列迁移(保留对话历史):agent_sessions 增加 provider_profile_id / model。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("agent_sessions")}
    with engine.begin() as conn:
        if "provider_profile_id" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN provider_profile_id VARCHAR(64)"))
        if "model" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN model VARCHAR(120)"))
        if "adapter_state" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN adapter_state JSON"))
        if "analysis_video_mode" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN analysis_video_mode VARCHAR(16) DEFAULT 'auto' NOT NULL"))


def _migrate_provider_capabilities() -> None:
    """加列迁移:provider_profiles 增加 capability_ids(档案级能力覆盖,None=沿用 vendor 默认)。"""
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("provider_profiles")}
    if "capability_ids" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN capability_ids JSON"))


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
    """给还没挂档案的发布账号,按其**既有分区** persist:mibu-<id> 建一个 browser_profiles 档案并
    回填 profile_id。组合(不合并):发布账号表保留,只多一个指针。幂等——只处理 profile_id 为空的
    账号。分区沿用不变 → Electron 打开同一分区,发布登录态不丢。"""
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
                {"id": pid, "ws": acc.workspace_id, "name": acc.name, "part": f"persist:mibu-{acc.id}", "proxy": acc.proxy, "enabled": acc.enabled},
            )
            conn.execute(
                text("UPDATE publish_accounts SET profile_id = :pid WHERE id = :aid"),
                {"pid": pid, "aid": acc.id},
            )


def init_db() -> None:
    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    _migrate_user_profile()
    _migrate_kb_schema()
    _migrate_agent_sessions()
    _migrate_generation_sessions()
    _migrate_generation_job_detach()
    _migrate_clip_transform()
    _migrate_tts_config()
    _migrate_provider_extra()
    _migrate_provider_capabilities()
    _migrate_job_parent()
    _migrate_browser_pool()
    Base.metadata.create_all(bind=engine)
    _backfill_browser_pool()


def _migrate_user_profile() -> None:
    """账户页已经把昵称/个性签名变成 User 模型字段。

    本地 dev 数据库可能是在该字段加入前创建的；若不在启动时补列,
    /api/auth/login 查询 User 会直接因缺列 500,但 /api/health 仍返回 ok,
    Electron dev 就会复用一个看似健康、实际无法登录的后端进程。
    """
    inspector = inspect(engine)
    if "users" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "display_name" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(120) NOT NULL DEFAULT ''"))
            conn.execute(text("UPDATE users SET display_name = username WHERE display_name = ''"))
        if "signature" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN signature TEXT NOT NULL DEFAULT ''"))
        if "avatar_key" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar_key VARCHAR(200) NOT NULL DEFAULT ''"))


def _migrate_generation_sessions() -> None:
    """加生成会话表,并给生成链路补 profile/model 字段。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "generation_sessions" not in tables:
            conn.execute(
                text(
                    """
                    CREATE TABLE generation_sessions (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        workspace_id VARCHAR NOT NULL,
                        title VARCHAR(200) NOT NULL DEFAULT '新生成',
                        provider_profile_id VARCHAR(64),
                        model VARCHAR(120),
                        kind VARCHAR(24),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                        FOREIGN KEY(provider_profile_id) REFERENCES provider_profiles (id) ON DELETE SET NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_generation_sessions_ws_updated "
                    "ON generation_sessions (workspace_id, updated_at)"
                )
            )
        if "generation_sessions" in tables:
            session_cols = {c["name"] for c in inspector.get_columns("generation_sessions")}
            if "provider_profile_id" not in session_cols:
                conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN provider_profile_id VARCHAR(64)"))
            if "model" not in session_cols:
                conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN model VARCHAR(120)"))
            if "kind" not in session_cols:
                conn.execute(text("ALTER TABLE generation_sessions ADD COLUMN kind VARCHAR(24)"))
        if "generation_jobs" in tables:
            cols = {c["name"] for c in inspector.get_columns("generation_jobs")}
            if "session_id" not in cols:
                conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN session_id VARCHAR(64)"))
            if "provider_profile_id" not in cols:
                conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN provider_profile_id VARCHAR(64)"))
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN created_at DATETIME"))
                conn.execute(
                    text(
                        """
                        UPDATE generation_jobs
                        SET created_at = COALESCE(
                            (SELECT jobs.created_at FROM jobs WHERE jobs.id = generation_jobs.job_id),
                            CURRENT_TIMESTAMP
                        )
                        WHERE created_at IS NULL
                        """
                    )
                )
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE generation_jobs ADD COLUMN updated_at DATETIME"))
                conn.execute(
                    text(
                        """
                        UPDATE generation_jobs
                        SET updated_at = COALESCE(
                            (SELECT jobs.updated_at FROM jobs WHERE jobs.id = generation_jobs.job_id),
                            created_at,
                            CURRENT_TIMESTAMP
                        )
                        WHERE updated_at IS NULL
                        """
                    )
                )


def _migrate_tts_config() -> None:
    """加列迁移:tts_config 增加 Fish Speech 的源码目录 / 模型目录列。"""
    inspector = inspect(engine)
    if "tts_config" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("tts_config")}
    with engine.begin() as conn:
        if "fish_repo_dir" not in cols:
            conn.execute(text("ALTER TABLE tts_config ADD COLUMN fish_repo_dir VARCHAR(500) NOT NULL DEFAULT ''"))
        if "fish_model_dir" not in cols:
            conn.execute(text("ALTER TABLE tts_config ADD COLUMN fish_model_dir VARCHAR(500) NOT NULL DEFAULT ''"))


def _migrate_provider_extra() -> None:
    """加列迁移(保留已配置的供应商):provider_profiles 增加 extra。
    ADD COLUMN 会把老行留成 NULL,而读取端按 dict 用 → 必须回填 '{}'。"""
    inspector = inspect(engine)
    if "provider_profiles" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("provider_profiles")}
    if "extra" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_profiles ADD COLUMN extra JSON"))
        conn.execute(text("UPDATE provider_profiles SET extra = '{}' WHERE extra IS NULL"))


def _migrate_clip_transform() -> None:
    """加列迁移(保留时间线):clips 增加 transform,sequences 增加 reframe。
    ALTER ADD COLUMN 会把老行留成 NULL,而 Out schema 要 dict → 必须回填 '{}'。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "clips" in tables:
            if "transform" not in {c["name"] for c in inspector.get_columns("clips")}:
                conn.execute(text("ALTER TABLE clips ADD COLUMN transform JSON"))
            conn.execute(text("UPDATE clips SET transform = '{}' WHERE transform IS NULL"))
        if "sequences" in tables:
            seq_cols = {c["name"] for c in inspector.get_columns("sequences")}
            if "reframe" not in seq_cols:
                conn.execute(text("ALTER TABLE sequences ADD COLUMN reframe JSON"))
            conn.execute(text("UPDATE sequences SET reframe = '{}' WHERE reframe IS NULL"))
            if "subtitle_style" not in seq_cols:
                conn.execute(text("ALTER TABLE sequences ADD COLUMN subtitle_style JSON"))
            conn.execute(text("UPDATE sequences SET subtitle_style = '{}' WHERE subtitle_style IS NULL"))
        if "tracks" in tables:
            track_cols = {c["name"] for c in inspector.get_columns("tracks")}
            if "solo" not in track_cols:
                conn.execute(text("ALTER TABLE tracks ADD COLUMN solo BOOLEAN NOT NULL DEFAULT 0"))
            if "duck" not in track_cols:
                conn.execute(text("ALTER TABLE tracks ADD COLUMN duck BOOLEAN NOT NULL DEFAULT 0"))


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

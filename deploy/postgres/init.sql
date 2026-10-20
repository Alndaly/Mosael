# 只在 Postgres 数据卷**为空**(首次初始化)时执行一次。
# 库和角色由 compose 的 POSTGRES_DB / POSTGRES_USER 建好(默认 UTF8);这里只做两件小事:
#   1. 编码不是 UTF8 就直接失败,免得悄悄建出一个存不了中文的库;
#   2. 把库的默认时区钉成 UTC —— cloud/ 的时间都是朴素 UTC,避免服务器本地时区影响清理判断。
#
# 表结构不在这里建:Cloud 启动时执行 cloud/migrations/ 里的 Alembic 迁移(全新库直接到 head)。

DO $$
BEGIN
  IF current_setting('server_encoding') <> 'UTF8' THEN
    RAISE EXCEPTION 'MosaelCloud 需要 UTF8 数据库,当前编码是 %', current_setting('server_encoding');
  END IF;
END
$$;

-- 库名与 deploy/docker-compose.yml 里的 POSTGRES_DB 一致。
ALTER DATABASE mosael SET timezone TO 'UTC';

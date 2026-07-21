# 数据边界靠归属规约维持,不拆 models.py

全部 SQLAlchemy 模型留在单文件 `app/db/models.py`(对人和 AI 的导航都友好,改表结构一目了然),但「谁能写」有主:每张表归一个领域模块所有(`app/domain/ownership.py`),行创建只发生在拥有方,跨领域需要新行时调用拥有方的领域函数。边界由 AST 棘轮测试强制(`tests/test_data_ownership_ratchet.py`):存量越界冻结在 allowlist 只减不增,新表必须登记归属。

**Considered options**:按领域拆 models 文件 — 拒绝:文件边界不等于写边界,拆完照样可以跨 import,反而丢了单文件总览;ORM 层拦截(session 事件校验)— 拒绝:运行时才报错,棘轮在测试期就挡住,且零运行时成本。

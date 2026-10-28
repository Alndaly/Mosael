"""工作流节点的数据库连接预算:引擎、画板、资产详情页跑一个节点都从这里取。

**叶子模块。** 引擎、执行器(等待时把预算交还)、画板和资产详情页单独跑一个节点都要用同一份预算;
它写在引擎里的话,执行器为了还一次预算就得回头 import 引擎,而引擎要按注册表找执行器 —— 成了环
(见 tests/test_import_layering)。

调用方按 `node_budget.NODE_CONNECTIONS` 取,不要 `from … import NODE_CONNECTIONS`:测试会把它换成一个更小的预算。
"""

from __future__ import annotations

import threading

from app.core.db import POOL_RESERVE, pool_capacity

#: **同时能有多少个节点占着数据库连接。**
#:
#: 这是全仓"先拿槽再开会话"那条规矩(见 domain/jobs 的 RENDER_SLOTS 那段注释)在工作流这一层
#: 的落地 —— 而此前它在这一层**不存在**:`MAX_PARALLEL_NODES = 8`、循环体的 4、嵌套深度 8,
#: 三个常数写在三个文件里,每一个单看都克制,**而它们是相乘的**。一个"8 个并行节点、每个都是
#: call_workflow"的图就要 8 + 8 ×(子驱动 + 子节点)条连接,而池子只有 15。越线之后是
#: `QueuePool limit of size 5 overflow 10 reached`,由 blame() 原样记进 job.error。
#:
#: **嵌套天然被压住**:这是模块级的一个信号量,子图的节点和父图的节点从同一份预算里取,
#: 所以乘积进不来。数从池子自己算出来(见 core/db.pool_capacity),不另写一个。
#:
#: 同一份预算里取,就不能有人攥着它等别人:在等的节点(executors.common.wait_until)和跑体的
#: 容器节点(循环 / 子图,见 engine.run_node)都把它交还 —— 只有真在用数据库的叶子占着它。
NODE_CONNECTIONS = threading.Semaphore(max(1, pool_capacity() - POOL_RESERVE))

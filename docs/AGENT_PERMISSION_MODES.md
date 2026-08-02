# 智能体三档权限模式 —— 实施计划

> 状态:**待实施**。设计见 [ADR 0007](adr/0007-agent-permission-modes.md);本文是它的落地方案,
> 并**修正**其中三处经复验站不住的部分(见 §2)。ADR 记「决定了什么」,本文记「怎么做、按什么顺序、
> 拿什么钉住」。
>
> 前置的四条修复已经落地(§1),它们改变了本方案的可行范围 —— 其中一条正是自动放行的阻塞项。

## 0. 一句话

按**权限档**分三档(手动 / auto / bypass);闸门放在服务端唯一的开卡入口;档位由 payload **派生**
而不是查静态表;bypass 绕过的是「用户同意」,不是「他有没有这个权限」。

---

## 1. 前置(已完成)

四条都是先用测试复现、再修的,与三档解耦,但三档依赖它们成立。

| # | 缺陷 | 复现结果 | 对本方案的意义 |
| --- | --- | --- | --- |
| 1 | `edit_workflow` 的卡绕过 code 节点门禁 | editor 落库了 code 节点(`['start','code']`) | auto 档下 `edit` 直接放行,这条会变成一条无人值守的本机执行路径 |
| 2 | 批准的 `edit` 校验依赖请求级 ContextVar | viewer 在后台线程批准成功,序列 revision 1→2 | **自动放行必须在请求线程之外跑**,这条不修就没法做 |
| 3 | 每次工具调用铸一个永不过期的令牌 | 3 次只读调用 → `auth_sessions` 1→4 行 | 会话归属要挂在令牌上(§5.2),挂在会泄漏的行上没有意义 |
| 4 | `AuthSession` 没有过期概念 | —— | 同上;根因修掉之后令牌是有周期的凭据 |

修完之后,`authorize_and_approve` 显式校验 `edit`,**从后台线程调用它是安全的** —— 这是本方案
和上一版最大的差别。

---

## 2. 对 ADR 0007 的三处修正

### 2.1 `browser_pool_open` 是错档,必须改成 `external`

它做的事是把智能体接到用户**真实登录的身份**上;`confirmations.py` 自己的注释写着「跨信任边界…
用户逐次显式授权」。而它现在归在 `edit`(可撤销)档 —— 按 ADR 的表,auto 一开它就直接放行,
等于智能体不吭声就能拿用户的登录态开会话。

### 2.2 档位不能查静态表,必须从 payload 派生

`run_workflow` 挂在 `ai-cost` 上,但工作流节点里有 `code` / `http_request` / `publish` /
`browser_*` / `plugin_tool` —— 一张 `ai-cost` 卡可以执行以上全部,而摘要只说「可能产生 AI/渲染
消耗」。`edit_workflow` 同理:它是 `edit` 档,却可以往图里写 code 节点。

**档位一旦不可靠,三档放开的就是错的东西。** 见 §4.2。

### 2.3 「AI 判断」建议第一版不做

三条理由:

1. **它买到的东西最少**。用户点得最多的是 `edit_timeline` 和 `generate_*`;`external` 一共三个
   工具,一次任务出现零到一次。
2. **它对一半的 `external` 工具是瞎的**。`publish_asset` 的 payload 只有 `{account_id, asset_id,
   title}` —— 判断者看不到要发出去的内容是什么,它能依据的只有「这个账号在不在白名单」,
   那是规则引擎,不是 LLM。
3. **它是唯一需要异步判定的东西**。纯规则判定是本地 DB 操作(微秒级),可以同步做;引入模型调用
   就要多一个「判定中」状态,而这个仓库里**没有任何启动期回收卡住状态的先例** —— 进程一崩,
   卡永久停在那儿,表现是模型干等 590 秒后超时。

**这一条需要产品所有者拍板**(ADR 里它是已决定项)。建议:auto 档的 `external` 照常弹卡;
真有人要「发布也自动」时,先做结构化白名单,判断者作为叠在白名单之上的**否决层**再议。

---

## 3. 保持不变的部分

- 按**权限档**分,不按工具。54 个工具让用户逐个勾,没人会配;权限档已经决定了卡片措辞和徽标。
- **模式必须常驻可见**,不能藏进设置弹层。
- **自动放行必须留痕**,而且要能一眼看出是哪一档放的。
- bypass 全放行是产品所有者的明确决定。

---

## 4. 设计

### 4.1 闸门位置:`POST /api/confirmations`

它是全项目**唯一**的开卡入口(路由注释自己确认过:「request_confirmation 全项目只有这一个调用
方」)。放这里,四件事同时成立:

- **协议零改动**。已验证:sidecar 只把 `executed` / `rejected` / `failed` 当终态,看到 `approved`
  继续轮询;前端两个确认面都只拉 `status=pending`,`approved` 天然不显示,不闪。
- **身份天然正确**。每次 turn 都为真实 User 铸了服务令牌,所以开卡请求里的 `CurrentUser` 就是
  行动人。自动放行走 `authorize_and_approve(db, user, card)` —— 三道闸一道不少。
- **留痕免费**。`ToolConfirmation` 行照建,只是 `pending` 这一步被跳过。
- **飞书 / MCP 一并覆盖**,不用第二套实现。

同时**删掉前端那套 localStorage 自动批准**。授权路径上并存「客户端一套、服务端一套」,比
`authorize_and_approve` 的 docstring 当初批评的「两处手抄」更糟:聊天面板一关组件就卸载,
同一个「模式」的行为取决于某个 React 组件在不在。

### 4.2 档位派生

新增 `effective_permission(db, tool, payload) -> str`,`TOOL_DEFS` 里的值降级为**下限**:

| 工具 | 静态 | 派生规则 |
| --- | --- | --- |
| `browser_pool_open` | `edit` | 恒为 **`external`** |
| `run_workflow` | `ai-cost` | 扫 graph:含外部节点 → **`external`**,否则 `ai-cost` |
| `edit_workflow` | `edit` | 扫 **ops 应用后**的图(复用已有的 `_graph_to_persist`) |
| `create/update_workflow` | `edit` | 扫 `payload["graph"]` |
| 其余 | —— | 不变 |

**外部节点集**:`code`、`http_request`、`publish`、`browser_*`、`plugin_tool`,以及
`call_workflow`(它按 id 引用另一张图,`privileged_nodes_in_graph` 不跟过去 —— 已验证返回
`set()`;跟过去要查库递归,第一版保守处理)。

摘要同步补齐:`run_workflow` 要像 `edit_workflow` 一样点名图里有什么。
[`test_confirmation_disclosure.py`](../backend/tests/test_confirmation_disclosure.py) 已经为
`edit_workflow` 立过这个规矩,同样的理由对 `run_workflow` 一字不差地成立。

**这一节对手动档也是净收益**(卡上的措辞终于对了),所以它可以先发,不必等三档。

### 4.3 三档语义

| 模式 | `edit` | `ai-cost` / `render-cost` | `external` |
| --- | --- | --- | --- |
| **手动**(默认) | 确认卡 | 确认卡 | 确认卡 |
| **auto** | 直接放行 | **上限内放行,超了弹卡** | 确认卡 |
| **bypass** | 直接放行 | 直接放行 | 直接放行 |

**为什么计费档用次数而不是金额**:仓库里没有本地预算这套东西(`provider_quota` 查的是**上游
供应商的余额**),而 `ProviderUsageEvent` 是**事后**记账 —— 智能体可以在任何一条账目落地之前
连开二十个生成。`render-cost` 更是本地 ffmpeg,不产生 provider 事件,用钱衡量它没有意义。

**上限怎么计**:自**上次人工决定以来**、本会话自动放行的计费卡数量 ≥ N → 这一张弹卡。
用户批了它,计数自然归零。这样上限约束的是「无人值守连开」,而不是「一天总共能花多少」——
后者需要的是账单,不是闸门。

### 4.4 作用域与归属

- 模式落在 `AgentSession` 上,与 `thinking_level` / `analysis_video_mode` 同类。
- **`mode_set_by` 不是行动人 → 退回手动**。飞书群聊共用一个 external session
  (`get_or_create_external_session` 按 `external_key` 取),群里任何人发消息都跑在同一个会话上;
  没有这条,A 开的 bypass 会替 B 做决定。而 `AgentSession` 本身不记 owner。
- **没有会话的卡(MCP 直连、飞书外部智能体)永远手动**。它们没有会话可挂模式;让它们继承任何
  全局默认,就是「授权范围逃逸」换个地方重演。
- **`origin="feishu"` 的会话不给 bypass**;bypass 每次会话显式开启,不做持久默认。
- 改模式要过 `ensure_workspace_perm(..., "ai")`;切到 bypass 额外要求 `role >= admin` ——
  它等价于「让智能体替我在这台机器上跑代码」,而那本来就是 instance-admin 级别的能力。
- **智能体自己不能改模式**,不提供对应工具。不写下来,迟早有人加一个 `set_permission_mode`。

### 4.5 会话归属必须是认证出来的,不能是声明的

`ConfirmationCreate.session_id` 来自请求体。今天它只影响「这张卡显示在哪个对话里」,填错无非
显示错位;一旦它决定**要不要自动放行**,一个拿着同一份 token 的外部智能体只要填上那个开了
bypass 的会话 id,就能让自己的动作被自动执行。

这不是跨用户提权(攻击者已经有这个用户的凭据了),是**同一份凭据内部的混淆代理**:用户为
「我在这个对话里盯着」授的权,被一个他没盯着的通道用掉了。

**做法**:`AuthSession` 加一列 `agent_session_id`,在 `post_user_message` 铸 turn 令牌时写上
(那里正好知道是哪个会话);开卡时**从令牌反查**会话,请求体里那个字段降级为仅供外部智能体
标注、且永不享受自动放行。工具调用现在复用调用方凭据,所以归属自动一路传到开卡处,不需要
任何传播逻辑。

### 4.6 判定同步,执行异步

**判定**(查会话模式、派生档位、数计数、查工具白名单)全是本地 DB 操作,同步做,不新增状态。

**执行**必须在请求线程之外。已验证:`_execute` 是同步阻塞的(1.5s 的执行器让批准请求整整阻塞
1.51s),而 `run_http` 超时 60s、工具体回连客户端 `timeout=30` —— **60 > 30**,慢请求必然产出
「已执行但报超时」:副作用发生了,状态说没发生。

所以自动放行在后台线程里调 `authorize_and_approve`。这不是第二套执行实现 —— 它和 HTTP 路由、
飞书回调调的是同一个函数,只是线程不同。**前置修复 #2 正是让这件事变得安全的那一条。**

线程要起名字并提供排空助手(照 `wait_for_idle_turns` 的样子),供 `fresh_client` 在重建 schema
前调用;否则就是那种「看机器速度和用例顺序随机红」的失败。

### 4.7 留痕

`ToolConfirmation` 加三列:

```
decision_mode    TEXT   -- manual | session-allow | auto | bypass
decided_by       TEXT   -- user_id;自动放行也记行动人
decision_detail  JSON   -- 命中的规则 / 计数快照 / 派生出的档位
```

- **卡片上**:自动放行的动作在对话时间线里就地标出来(工具调用条目挂权限徽标 + 「auto 放行」),
  不另开一个列表 —— 卡和工具调用本来就是同一个动作。
- **事后可查**:确认记录按会话可列(现有的 `GET /api/confirmations` 已经支持按 `session_id` 和
  `status` 过滤,补一个入口即可)。**事后能查是 bypass 唯一可接受的前提。**

### 4.8 「本会话始终允许」怎么迁

现在是客户端策略(localStorage + React 组件挂载期间轮询自动批)。迁成 `AgentSession` 上的一个
JSON 列 `auto_allow_tools`,和模式在**同一个判定函数**里求值:先看工具白名单,再看档位。
不新增表,不新增第二个判定点。语义保持不变(它是用户读过卡之后逐个点的),但留痕里标成
`session-allow`,与 `auto` 区分开 —— 两者不是一回事。

---

## 5. 数据模型改动

```
agent_sessions
  + permission_mode   TEXT NOT NULL DEFAULT 'manual'   -- manual | auto | bypass
  + mode_set_by       TEXT NULL                        -- user_id
  + mode_set_at       DATETIME NULL                    -- 计数的起点
  + auto_allow_tools  JSON NOT NULL DEFAULT '[]'

tool_confirmations
  + decision_mode     TEXT NOT NULL DEFAULT 'manual'
  + decided_by        TEXT NULL
  + decision_detail   JSON NULL

auth_sessions
  + agent_session_id  TEXT NULL                        -- 令牌属于哪次对话(§4.5)
```

全部走启动迁移(`core/db.py` 的 `_migrate_*`),读取代码里**不留旧形状的分支** —— 老行取默认值
即正确语义(手动档、无自动放行记录),迁移跑完就没有第二种形状。见
[ADR 0006](adr/0006-migrate-instead-of-branching.md)。

---

## 6. 分期

| # | 内容 | 能不能独立发 |
| --- | --- | --- |
| 1 | 档位派生 + 摘要披露 + `browser_pool_open` 改档 | 能。手动档下就是净收益 |
| 2 | turn 令牌携带会话归属(§4.5) | 能。它也让确认卡的归属不再可伪造 |
| 3 | 三档本体:schema + 判定 + 后台执行 + 留痕 + 常驻 UI + 「始终允许」迁移 | 本体 |
| 4 | (待拍板)结构化白名单 → 判断者 | 3 之前 auto 档的 `external` 一律弹卡 |

---

## 7. 测试棘轮

缺了这些,方案里最容易腐烂的正是它们:

1. `run_workflow` 指向含 `code` / `publish` 节点的工作流 → 派生档位是 `external`,且摘要点名。
2. 图里出现 `call_workflow` → 保守判为 `external`。
3. `browser_pool_open` 在 auto 档下仍然弹卡。
4. bypass 下 editor 加 code 节点 → 依然 403(**bypass 不绕授权**)。
5. 没有 `session_id` 的卡,在任何模式下都停在 pending。
6. A 设 auto、B 在同一会话行动 → B 弹卡。
7. 请求体里伪造一个别人会话的 `session_id` → 不享受自动放行。
8. 自动放行的卡带 `decision_mode` / `decided_by`,且不出现在 `status=pending` 列表里。
9. 计费卡连续自动放行到上限 → 下一张弹卡;人工批一张后计数归零。
10. 后台执行线程能被 `fresh_client` 排空。

---

## 8. 需要产品所有者拍板

**auto 档的 `external` 第一版走不走 AI 判断?** 建议不走(§2.3)。ADR 里这是已决定项,所以这条
我改不了,只能给判断。

---

## 9. 明确不做

- **不给 39 个直接执行的工具做模式**。但要记下这条路存在:`read_only` 的定义是「不在
  `CONFIRMATION_TOOLS` 里」,于是 `browser_type` / `browser_click` / `browser_evaluate` 全算只读;
  `browser_pool_open` 批准之后,智能体可以用真实登录身份点、填、提交,整个过程一张 `external` 卡
  都不会出现;写类插件工具同样无卡。**在把批准变便宜之前,值得先确认被卡住的集合确实是危险的
  集合** —— 但那是另一个 ADR 的题目。
- **不做沙箱**(ADR 已否掉,同意:那是另一个功能,不该塞进权限模式里当它的前提)。
- **不给智能体改模式的工具**。

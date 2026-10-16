# ADR 0066:飞书是工作流里的一等公民 —— 通知目标显式化 + 四个飞书能力节点

## Status

Accepted — 2026-10-16。改「等人确认」的飞书那一面(写明 `channel` / `bot` / `to`,而不是自动猜)并新增
四个节点:`feishu_message`(发飞书消息)、`feishu_take_resource`(取回飞书附件)、`feishu_reaction`(回个表情)、
`feishu_chats`(列出机器人所在的群)。**两族节点共用同一份"发飞书"原语。**

## Context

### 「发到哪」此前是自动猜的,而且节点上看不见

ADR 0064 的 `await_approval` 把卡片发到飞书的哪里,是 `route_for_approval` 里两条 `if` 决定的:

1. 这一次运行**来自飞书会话**(任务载荷里的回执指着一次 `origin="feishu"` 的智能体会话)→ 发回那个会话;
2. 否则**发起人绑过飞书** → 私聊他;
3. 两条都不成立 → 只站内。

判断本身是合理的,问题是它**只能这么办**:节点上一个飞书字段都没有,使用的人既看不出这个门会发卡、
也看不出发给谁,更没有一个"这次就是不发飞书"的档 —— 而"没发飞书"与"发不出去"在代码里长得一模一样
(都是 `return None`)。

### 四个飞书动作在工作流里没有对应物

飞书集成这一侧(`integrations/feishu/client.py`)已经有租户令牌、发文字 / 卡片、加表情、取回消息资源;
工作流里却一个都用不上:想"跑完把结果发到群里"只能借道 `notify`(站内通知),想取一份附件是做不到的。

### 各自的诱惑:各写一套

最省事的做法是让四个新节点各自 `import client`、各自拼地址、各自挑机器人。那样"发到哪"就有了**五份**
实现(加 ADR 0064 那一处),而它们迟早会在细节上分家 —— 重试、token 刷新、`receive_id_type` 的取值、
以及"工作区里没有机器人时该怎么办"。

## Decision

### 1. 通知目标写在节点上

`await_approval` 与 `feishu_message` 各有一个 `channel`,取值 `origin` / `user` / `chat`(`feishu_message`
多一个 `raw`),「等人确认」多一个 **`none`**:

- `origin`(**缺省**)逐字沿用上面那两条自动路由 —— 所以**旧的图行为不变**;
- `user` / `chat` 由 `to` 那一格说发给谁(私聊一个**已绑定**的人 / 发到一个群);
- `raw` 手填收件 id 与类型(`feishu_message` 专属:它的收件人没有"下拉里一定找得到"这一说);
- `none` 是**"只站内,一个字都不发飞书"这个明确选择**,不是"发不出去就算了"。

`bot` 那一格点名用工作区里的哪一个机器人;留空 = 自动挑最早启用的那个(和改之前同一把尺)。

### 2. 一份原语,两族节点共用

- **谁收**:`app/domain/feishu/routing.py`。`resolve()` 解出 `(机器人, 收件 id, 收件 id 的类型)`,
  并给一个说得清的 `reason`(`none` / `no-bot` / `no-origin` / `not-bound` / `no-target`);
  `session_origin` / `run_origin` / `pick_bot` / `requester_binding` 都在这里。
- **怎么发**:`app/domain/feishu/gateway.py` 是一道**缝**(领域层不认识集成层,见
  tests/test_import_layering),实现唯一落在 `app/integrations/feishu/gateway.py`,底层是 `client.py`。
  组装根(`app.main._wire_seams`)在导入期登记 —— 和 ADR 0064 的 `_RUN_CARD_SENDER` 同一条规矩。

「等人确认」的卡片和四个节点的文字 / 卡片都从这两处走:卡片**长什么样**是两回事(确认卡带按钮回调,
节点卡只带一个链接),**发出去**这件事只有一份实现。

### 3. 发不出去时怎么办:两族**刻意不同**

- 「等人确认」**降级**成站内。一个门禁的用处是拦住"没人看着就往下走",不是拦住自己 —— 这一点 ADR 0064
  已经定下,这里只把"为什么没发飞书"从沉默改成**显式**(日志里说清是节点上写了 `none`,还是解不出来
  以及为什么)。
- 四个飞书节点**失败**(`wfErr_feishuNoBot` / `wfErr_feishuNoTarget` / …),而且**开跑之前**就先问一遍
  (preflight)。「发飞书消息」整个存在的意义就是把一句话送出去 —— 送不出去却"成功",等于让整条自动化
  假装做完了,而发现它没做是在很久以后。

### 4. 检查器里那几格是选择器

`options_from` 三个新来源:`feishu_bots`(这个工作区的机器人)、`feishu_targets`(「收件人」一格,
按父字段 `channel` 在"已绑定的人 / 机器人所在的群"之间换源)。群清单是**现问飞书**的(和 `feishu_chats`
节点同一份调用),一律 best-effort:问不到就空着,声明里的 `allow_custom` 让人仍能填 id。

### 5. 节点上看不见的那一半补上

画布卡片上多一行(前端 `feishuChannel`):「飞书 · 群 oc_xxx」「飞书 · 私聊 发起人」「仅站内」。
说的是**节点上写的那个选择** —— 不点开检查器就知道这个门怎么通知,而配置在检查器里改。

## Consequences

- **旧的图行为不变**:`channel` 缺省是 `origin`,而 `origin` 就是改之前那两条路。
- 「发到哪」只剩一份实现;`domain/workflows/approvals.bot_for_user` 随之删掉(它是第二份"挑机器人")。
- 四个节点的 `message_id` / `raw_id` 声明成 `data_type: "external_id"`:它们是飞书那个系统里的编号,
  这个工作区里给不出选择器(tests/test_entity_fields_have_a_picker 按这句声明放行)。
- 「有智能体工具或写明豁免」那条棘轮里,这四个节点都走**豁免**(见 tests/test_agent_workflow_parity):
  智能体在飞书里的**回复本身就是那条消息**,而工作流没有对话可回。

## 补记(2026-10-17):"怎么看得出它到底连上没有""失败时飞书自己那句话去哪了"

§2–§5 的语义一条没动。这一笔补的是**这一层底下的三件基础设施** —— 它们各自的失败方式都很安静,
错的时候界面照样是绿的、任务照样报"失败"而原因里只有一句英文。

### 1. 三处机械 bug(`ad6775dcb`,都在"节点上写的那几格怎么解")

- **`limit = 0` 明确拒绝**(`wfErr_belowMin`):0 在「列出机器人所在的群」那个节点上只能是"一个群都不列",
  而它的用处正是交出清单。当 0 用会和原有的 `max(1, …)` 兜底打架,而"悄悄换成 1"又是新的静默兜底。
- **认不出的 `channel` 当场说清**(`wfErr_feishuUnknownChannel`,带值 + 允许的 `origin / user / chat / raw`)。
  实测旧行为是把消息**发给了发起人**并返回 `sent: true` —— 一条 `chatroom` 的笔误把话交给了错的人。
  **做成 opt-in**(`routing.channel_of(..., strict=True)`):「等人确认」那条路遇到发不出去**可以退回站内**
  (ADR 0069),默认严格化会改掉它的降级语义,所以只有「发飞书消息」的执行器与它的 preflight 传 `strict`,
  `approvals` 那几个调用处逐字未变,`channel: none`(仅站内)语义未动。
- **`raw` 的收件类型按 id 前缀判**(`oc_` → `chat_id`、`ou_` → `open_id`):认不出前缀 → `wfErr_feishuRawId`;
  和那一格写的类型对不上 → `wfErr_feishuRawType`。此前认不出就回 `chat_id` —— 填错的 id 要等飞书回一句
  英文报错,而"发给一个群"和"发给一个人"错一次就是把话交给了错的对象。**唯一放宽的一处**(已在代码里标注):
  类型那一格空着时按前缀判(旧实现以 `no-target` 拒),因为手改的图里那格常常没有值,而前缀已经证明类型成立。

### 2. 客户端:飞书自己那句话不再被吞掉,重发只对"不会留下可见副本"的调用开(`455ba6945`)

飞书的业务错误大多是 **HTTP 200 + code≠0**,但限流 / 网关 / 令牌失效是真非 2xx
(消息 API 限流是 `code 230020` + HTTP 429)。`integrations/feishu/client.py` **先把 body 解出来**:
非 2xx 也当成一次回答来读,`code` / `msg` / HTTP 状态码一起进 `FeishuError`(它是 `LocalizedError`,
执行器那层翻得动)。此前是先 `raise_for_status()` 再 `json()`,于是非 2xx 一律变成 httpx 的
`HTTPStatusError`:飞书写的 code/msg 一个都没读,`except LocalizedError` 也接不住,任务失败原因里
只剩一句英文的 `Client error '429 Too Many Requests' for url …`。

**重发预算是按"会不会留下可见副本"分的**(`_resend_budget`):

- **发消息 / 改卡片 / 加表情一律 0 次** —— 重发一遍就是群里多一条消息、多一个表情,而飞书消息 API
  最常见的限流回法恰好是 HTTP 429 + code 230020,仓库那条判据
  (`core/http_retry.status_resend_is_safe`)对 429 是**放行**的(它判的是"供应商会不会多做一次并多收一次钱",
  不是"用户会不会看到两条");
- **列群 / 下载是 GET**(幂等,遇 429 / 5xx 都重发),**上限写死 `FEISHU_MAX_RESENDS = 2`**,不跟设置页
  那个 `max_retries` 走 —— 那个数是 AI 连接的,跟着它在这里表现为"群列表多转几十秒"。
- **令牌失效**:`99991663`(租户令牌无效)与 `99991664`(应用访问令牌无效)都换一次令牌再来一遍;
  多花的只是"再取一次令牌",**不会多发一条消息**。

### 3. 「在线」由**真的连上了**驱动(`ad6775dcb`)

此前设置页的绿色是"进程起来满 8 秒"这个定时器写出来的 —— 凭据错、SDK 卡在内部重连,页面照样变绿。
如实说明:**lark_oapi 的 ws.Client 没有公开的"初次连上"回调**(`on_reconnecting` / `on_reconnected`
只在 `_reconnect()` 里触发),所以挂的是它唯一可观测的真状态 `_conn`(端点那次 HTTP POST 与 websocket
握手都成功之后才被赋值,掉线时清回 `None`)。

**私有属性改名的失败方向是安全的**:`_conn` 若被 SDK 改名,这里会**一直不报在线**(绿不了),
而不是报一个假的绿 —— 宁可不说,不说谎。另接两个公开钩子:掉线 → `connecting` + 原因,重连 → `online`。
配套三处:autostart 失败落 `error` + **异常原文**;后端启动把库里所有残留的 `connecting` / `online`
**归零**(上一次进程被杀留下的状态,与它启不启用无关);子进程异常退出带上 worker 最后报的原因
(不再被一句"进程退出(code N)"盖掉)。

验收:`backend/tests/test_feishu_connection_status_tells_the_truth.py`(297 行)、
`backend/tests/test_feishu_client_http.py`(339 行)、`backend/tests/test_feishu_workflow_nodes.py`。

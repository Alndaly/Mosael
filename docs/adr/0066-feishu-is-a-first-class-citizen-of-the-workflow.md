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

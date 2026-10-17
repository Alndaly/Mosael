# ADR 0070:飞书绑定是**某个应用**的绑定 —— 键加上机器人这一维、说不清归属就删掉、机器人绝不把绑定码发给外人

## Status

Accepted — 2026-10-17。修的是 ADR 0066 那族飞书能力底下**认人**那一层:`feishu_bindings` 的键从
`(workspace_id, open_id)` 改成 `(workspace_id, bot_id, open_id)`(数据库 **29 → 30 → 31**)。ADR 0064 §4 的
「发起人绑没绑飞书」、ADR 0065 §4 的「只有绑定了 Mosael 账号的人能驱动触发器」、ADR 0069 §2 的
`not_attempted / not-bound` 都经过这一层,所以这一条**谁都不改语义**,只把"是谁"这个问题答对。
31 是收尾:30 给"说不清归属"的老行留下的空串哨兵 + `stale_reason` 被整段删掉 —— 那是**一段迁移
没走完的中间态,不是一等状态**(见 §1、§2)。本文档里两处**取舍**是维护者拍板的结果,记在 §5、§6。

## Context

### 飞书的 `open_id` 按应用隔离

官方《用户身份概述》的原话是「不要在跨应用的数据通信中使用 open_id」:同一个人在 A 应用和 B 应用里
是**两串不同的 open_id**,而 `chat_id` 也一样。这个仓库把飞书接进来时,键上只有工作区:

```
feishu_bindings(workspace_id, open_id) → user_id
```

三个后果都是维护者真撞到的:

1. **换过应用之后,旧行的 open_id 永远匹配不上新事件里的 `sender_open_id`**。机器人回「你还没有绑定」,
   而设置页照样把那一行列成"已绑定" —— 同一份数据在两个地方给出相反的答案。
2. **同一个人在两台机器人上是两行**,面板按工作区列出来就是"重复用户"。
3. **`requester_binding` 取哪一行由存储顺序定**:它挑"最早启用那台机器人",却拿**另一行**的 open_id
   去发 —— 拿 A 应用眼里的 id 配 B 应用的 token,飞书直接拒(而且报的是一句和原因无关的话)。

### 「创建完自动绑定了」是一只错觉

面板列的是**整个工作区**的绑定,所以新机器人建出来、面板里显示着几条绑定,看起来就是"它已经认识这些人了"。
数据里一行都没为它写过。键上没有机器人这一维时,这个错觉无法从数据上被证伪 —— 只有等到那个人发消息、
被回一句「你还没有绑定」才暴露。

## Decision

### 1. 键加一维,`bot_id` 是名正言顺的外键

```sql
feishu_bindings(workspace_id, bot_id, open_id)   -- 主键
  bot_id VARCHAR(64) NOT NULL REFERENCES feishu_bots(id) ON DELETE CASCADE   -- 无 default
```

**不变式交给 schema,不写显式删。** `bot_id` 指着 `feishu_bots` 并 `ON DELETE CASCADE`:
`(bot, open_id) -> user` 随机器人一起没有意义 —— 那台应用没了之后,它眼里的那串 open_id 不再有
任何应用解释得了,留着就是一行谁都匹配不上的死行。所以 `bots.delete_bot` 只剩 `db.delete(bot)`,
级联由外键承担(与 `delete_workspace` / 删发布账号 / 卸载插件同一条既有做法;本仓显式扫列删
只出现在**故意不设外键**的列上)。

**为什么当初不是外键、后来为什么是。** 30 那一步要给"说不清归属"的老行留一个位置,而那个位置是
空串 `bot_id = ''` + `stale_reason = 'unknown-app'` —— 空串指不到任何一行,`bot_id` 那时**不可能**
是外键。31 把那件事想清了:那些行的 open_id 属于**已经不存在的应用**,永远匹配不上任何东西,
「说不清归属」只是**一段迁移没走完的中间态**,不是一等状态。于是这一步直接
`DELETE FROM feishu_bindings WHERE bot_id = ''`,空串哨兵随列定义一起消失,`bot_id` 才成为真外键 ——
而且 `NOT NULL`、**没有 default**。

### 2. 迁移 29 → 30 → 31:归属判据只有一条,绝不默默归属,判不出来的删掉

`migrate-feishu-bindings-know-their-app`(`db/migrations.py`,BEFORE_SCHEMA 里的一步、幂等 ——
SQLite 改主键只能重建表,所以只在 `bot_id` 还不在的时候整张重建):

> **绑定落库的那一刻,这个工作区里只有一台机器人存在**(按 `feishu_bots.created_at` 判)。

- 那一刻**恰好一台** → 回填它的 id;
- 那一刻**一台都没有**(那台应用已经删了 / 这张单比机器人还早 —— 换过应用那一族)或**不止一台**
  (说不清是哪台的) → `bot_id = ''` + `stale_reason = 'unknown-app'`(这是**当时**的形状,见 §1)。

**紧接着的 31 把它们删了。** `migrate-feishu-bindings-drop-stale-rows` 一句
`DELETE FROM feishu_bindings WHERE bot_id = ''`,再把表重建成 §1 现在的形状:没有 `stale_reason`、
`bot_id` `NOT NULL` 而且**没有默认值**。「说不清归属」只在 30 到 31 之间活了一版。

**旧数据绝不默默归到"现在那台"机器人。** 那正是上面那只错觉的成因,而按它回填等于把错觉写进库、
以后再也没人分得清哪一行是真的。代价明确:这些行的人要在**还在的那台**机器人上重绑一次(见 Consequences)。

只搬父行(工作区 / 用户)还在的行:主键那两列都是外键,搬一条死引用会当场
`FOREIGN KEY constraint failed` 把启动卡死 —— 这条在种子的老库上真撞到过。31 重建时 join 又多一张
`feishu_bots`:`bot_id` 从那时起是**真外键**,指着一台已经不在了的机器人的行同样没有读者,一样是死行。

### 3. 每一个认人的入口都带 `bot_id`,一处都不例外

`app/domain/feishu/bindings.py`:`resolve_sender` / `bind_member` / `redeem_bind_code` /
`list_bindings` / `remove_binding`;`app/domain/feishu/routing.py`:`requester_binding` / `_is_bound` /
`resolve`;`app/integrations/feishu/approvals.py`:`handle_card_action`。调用点逐个更新(入站两条、
待批卡、工具确认卡、路由、用例)。

- **`requester_binding` 改成"他绑过的那台"**:点名了机器人就用它的那一行;没点名时挑**他绑过的**
  那台(启用中、创建时间最早的那个,`ORDER BY`),不再"挑机器人 + 随便取一行 open_id"。
- **两个路由真的按机器人**(`app/api/routes/feishu.py`):列表只列**这台**的(`bot_id` 精确 `==`,
  一行不多);删除只删**这台**的那一行。此前只拿 `bot_id` 推出 `workspace_id` ——
  拿 A 的 URL 能把 B 那条绑定删掉,这是一条越权面。
- **写绑定只有 `bind_member` 一条路**:成员自己兑码和"扫码创建完自动绑发起人"(§4)都走它。

### 4. 删机器人:**外键级联删,不标任何状态**

`bots.delete_bot` 只剩 `db.delete(bot)` —— `bot_id` 上的 `ON DELETE CASCADE` 把它名下的绑定一起带走
(§1 那条既有做法)。不写显式扫列删,也不留行:这台应用没了之后,它眼里的那些 open_id 不再有任何
应用解释得了,留着就是一行**谁都匹配不上**的死行。

**「这个人以前绑过这台」不靠这张活跃表留。** 它是**历史**,归审计表(见 §9)。塞回活跃表换来的
正是这套刚删掉的状态:一个空串哨兵、一个"请重新绑"的界面分支、一行谁都匹配不上的记录。

### 5. 取舍之一:**机器人绝不把绑定码发给未绑定的人**

绑定码(`redeem_bind_code`)的语义是「成为**发码那个成员**飞书身份的持有者凭证」:谁把它发给机器人,
机器人就把**谁的** open_id 绑到**发码那个人**身上。所以当一个**未绑定**的发消息者收到"你还没绑定"时,
机器人**不能**顺手回一张新码 —— 后端此刻根本不知道他是谁,当场发一张码给任意陌生人等于
**把某个成员的身份凭证公开发出去**。

按这条,现在的回复是:说清**是哪台机器人**、指到**这台**的面板去生成新码
(`feishuUnboundSender` / `feishuUnboundCodeRefused` 两条文案,`core/messages/integrations.py`),
并把"你那张码为什么不算数"(过期 / 用过 / 是为**另一个应用**的机器人生成的)分开说。

### 6. 取舍之二:**反向配对暂不做**

要字面做到"回复里带一张码",需要的是**反向配对**:机器人在群里给一张码,成员在 Mosael 里输入它,
这才把「这台机器人」和「这个成员」连起来,而凭证的方向是"成员认机器人"而不是反过来。
**维护者已定暂不做** —— 它要新增一条配对流程和一套状态,而 §5 那两条回复已经把"下一步做什么"
说清楚了。

### 7. 扫码创建完就把**发起人**绑上

`integrations/feishu/onboarding.py`:`begin` 那一步用 `request_user_info=open_id` 要到扫码那个人的
`user_info`,并记下**是谁发起的**(路由里的 `CurrentUser` → `begin_onboarding(ws, user_id)`);成功那一次
在**同一个事务**里 `create_bot` + `bindings.bind_member(...)`。

**归属不猜。** 官方没写 `user_info.openId` 是"新建应用眼里的那个人"还是"注册平台视角的人",所以照实写:
归属若不对,这个人第一条消息就会 `resolve_sender(bot, open_id)` 认不出 —— 而那是**可见的失败**
(§5 那两句回复说清是哪台、指回面板),不是静默的成功。**不做任何猜测性回填。**
回包里没有 open_id / 没有发起人 / 发起人已不是成员这三种**只记日志、不报错**(机器人已经建好了)。

### 8. 由此带出的三处前端

- **绑定面板按 Mosael `user_id` 归并**(不是 open_id、不是名字 —— open_id 按应用隔离,照它一行一条
  就是"重复用户"的来路):一个成员一条,他名下每条绑定各占一行并真读 `binding.bot_id` 说明是哪台。
  列表本身就是**这台机器人**的(`bot_id` 精确 `==`),所以没有"要排在最后的那种行",也没有 `stale` 这一格。
- **选收件人时把"哪台机器人"一并写进 `bot`**:选项带上 `bot_id`(`field_options._feishu_bound_users`
  / `_feishu_chats`),前端 `NodeConfigForm` 的 `optionBotWrite` 在选中时一次
  `onPatchConfig(key, {to, bot})`;**清单没带就什么都不写**(不按名字猜机器人)。
- **画布卡片显示名字**(`features/workflows/feishuTargets.ts`):只对图里真用得上的档现查
  `feishu_targets` 目录,查不到照旧显示原值 —— **不编名字**。

### 9. 补记:**「谁曾绑过」落在审计表,不落回活跃表**

机器人删掉之后,"这个人以前绑过这台"这件事该落在哪?现有的落点是**审计表** `activity_events`
(模型 `backend/app/db/model_slices/collaboration.py`,写入入口 `record_activity()`
在 `backend/app/domain/collaboration/__init__.py`):`actor_id` 是 `users.id` 上的 `SET NULL`
(**人走了痕迹还在**)、`subject_type` / `subject_id` 一起说明这条记的是谁、`payload` 是 JSON、
`created_at` 只增不改。写入大概长这样:

```python
record_activity(
    db, workspace_id=ws, actor_id=user_id, action="feishu.binding.removed",
    subject_type="feishu_binding", subject_id=bot_id,
    summary="解除了飞书绑定", payload={"bot_id": bot_id, "app_id": app_id, "bot_name": name, "open_id": open_id},
)
```

三个关键点:

- **它不指向 `feishu_bots`。** `subject_id` 是一段字符串,不是外键,所以机器人删了、`feishu_bots`
  那一行没了,这条痕迹**照样在** —— 这正是活跃表做不到的事(它必须跟着级联)。
- **它不参与授权。** 认人(`bindings.resolve_sender`)与面板(`bindings.list_bindings`)都只读
  **活跃**那张表;审计表只出现在工作区动态流(`GET /api/activity`)那条读路径里,没有任何
  "从历史推出现在谁能驱动机器人"的判断 —— 历史是历史,现状以活跃表为准。
- **删机器人时每一条** `feishu.binding.removed` **各记一条**,否则"删了就查无此事"。

**已落实现**(写入在 `app/domain/feishu/bindings.py` 的 `record_removed`):显式解绑
(`remove_binding`,解绑路由走它)与删机器人(`bots.delete_bot`)**两条路**各记这一条;删机器人在
`db.delete(bot)` **之前**把它名下每条绑定读出来、记一条,级联删完痕迹仍在。`subject_id` 那一列
模型上写的是 `String(64)`,而 `bot_id`(32 位 hex)加 `open_id`(真实值约 35 字符)拼起来约 68 字符
会顶到边界 —— 所以落实现时 `subject_id` **只放 `bot_id`**,`open_id` 进 `payload`(JSON,没有这个
上界)。

## Consequences

- **数据库 29 → 30 → 31。** 30 把能无歧义归属的行回填到那一台机器人(维护者的真库上那唯一一行正是
  这么**正确回填**的);说不清归属的那些行在 31 里被**删掉** —— 那部分人要在还在的那台机器人上重绑
  一次。这是本条最直接的代价,而它换掉的是"面板与机器人各说各话"。
- **多一台机器人 = 多一套身份。** 同一个人要在每台机器人上各绑一次。这不是实现选择,是飞书的模型
  (open_id 按应用隔离);把它藏起来才是不诚实。
- **删机器人会连带删掉它名下的绑定,"谁曾绑过它"因此在活跃表里没有痕迹**。那些 open_id 属于一个
  没有了的应用,留着没有读者;要留痕是**审计表**的事(见 §9),不是把历史塞回活跃表。
- **`_is_bound` / `handle_card_action` 多一个参数**:飞书回调那边由 `worker.card_action` 把
  `bot_id` 一起带过来(点击的回调本来就来自某一条连接)。
- **`field_options` 的选项多一格 `bot_id`**:这正是把 ADR 0045 的"两层名字"顺带修好的那一笔
  (见 ADR 0045「修订之三」)——响应模型的 `extra="ignore"` 此前会把它一起吞掉。

## 验收

- `backend/tests/test_feishu_bindings_know_their_app_migration.py`:喂旧形状(含同人不同应用四行),
  验新主键序、回填、标 stale、丢死引用、再跑一次不变 —— 那一步的身体**冻着**,这条验的是 30 当时
  搬成了什么样(历史快照),不是现在的形状。
- `backend/tests/test_feishu_bindings_drop_stale_rows_migration.py`:喂**真 v30 形状**并走真升级路径,
  验 `bot_id=''` 的死行没了、留下的原样(含 `created_at`)、列定义逐字、主键序、
  `PRAGMA foreign_key_list` 里有 `(feishu_bots, bot_id, id, CASCADE)`、模型上没有默认值,再跑一次全等。
- `backend/tests/test_feishu_binding.py`:签名(少了 `bot_id` 就报)、"拿 A 的 open_id 配 B"被拒、
  面板不串台、拿 B 的 URL 删不掉 A 那条、**删机器人时它名下的绑定一起没了**。
- `backend/tests/test_feishu_onboarding.py`:建完绑发起人;回包缺 open_id / 缺发起人 / 发起人已不在
  三种都不写、不报错。
- `frontend/src/features/settings/FeishuSection.bindings.dom.test.tsx`(按人归并)、
  `frontend/src/features/workflows/feishuTargetNames.dom.test.tsx`(查不到显示原值)、
  `backend/tests/test_workflow_field_option_shape_over_http.py`(选项带着 `bot_id` 穿过 HTTP)。

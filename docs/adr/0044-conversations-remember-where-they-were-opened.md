# ADR 0044:对话记住在哪开的 —— 每一处各接各的对话

## Status

Accepted — 2026-10-07。下面「已拍板」的 1–7 条由维护者照推荐拍板(「按推荐来」)。第 8 条(工具跟着地方走)是 ADR 0042
第一步收尾时冒出来的预算问题,和第 1 条同一个根(后端分不出一段对话是在哪说的),照本 ADR 的规矩给了推荐、按定了写;各处边角的
「推荐」也一样。维护者要改哪条再改。分四步做,第 3 步要排在 ADR 0042 第二步之前(§11)。

## Context

维护者(2026-10-07):剪辑、笔记、画板、工作流、3D 场景,还有 ComfyUI 工作台新加的「助手」页签 —— 各页面的智能体对话历史互相干扰。

### 现在怎么做的:一个工作区只有一个「当前会话」

`frontend/src/features/agent/currentAgentSession.ts` 开头那段注释写着为什么统一成一个:此前 AI Studio、画布助手、免提浮标、智能体
发起的跳转四处各读各的 —— 面板回落到清单第一条却不告诉别人,对浮标说话新建了第二条,智能体要求的跳转没人执行。统一之后:

- **只存一样**:用户明确选过的会话 id(localStorage,键 `mosael.agent.session.<工作区 id>`,见 `sessionSelection.ts`)。「当前会话」由它和
  会话清单现算:选过的那条在清单里就是它,否则是**自己的**最近一条。同一窗口靠模块里的广播、跨窗口靠 `storage` 事件。
- **回落不写回,用上才写回**:只是看着第一条时不记成选择(写回的是推导值,清单可能是旧的,两个窗口会来回抢);发消息、对浮标说话、
  改会话设置都经 `ensureAgentSession`,那一刻才记下。同一工作区同时只跑一个 ensure。
- **共享来的只能看**:`isViewOnly` 只判一次;回落只落在自己的对话上;`ensureAgentSession` 遇到只读的当前会话就拒(`ViewOnlySessionError`),
  不悄悄另建一条。

这三条都对,本 ADR 原样留着;错的是「一个工作区只有一个答案」。各页面之间的差别只剩每条消息附的那段看不见的 `contextLine`:在剪辑里
聊完打开一篇笔记,接着的是同一段对话,两边的上下文交错在一起;在一处点「新对话」,别处全跟着换;历史也看不出哪段是在哪聊的。
笔记页甚至把它写成了特性(`features/notes/NotesView.tsx`:「换一篇笔记不换会话」)。

### 谁在读、写「当前会话」

| 入口 | 在哪 | 做什么 |
| --- | --- | --- |
| AI Studio | `features/ai-studio/ChatWorkspace.tsx`、`SessionList.tsx` | 读、选、新建、删后回落(`forget`)、发送前 `ensure`;列表有分组(`group_id`)、分享 |
| 页面上的助手面板 | `features/agent/CanvasAgentChat.tsx`,挂在 `EditorView`、`NotesView`(由 `app/pages.tsx` 交进去)、`BoardsView`、`WorkflowEditor`、`SceneStudio` | 同上;标题处的 `AgentSessionSwitcher` 列的是整个工作区的对话 |
| 工作台「助手」 | 分支 `worktree-agent-a809-adr0042`:`features/plugins/workbench/AssistantPanel.tsx` | 同一个 `CanvasAgentChat`(停靠、不浮不关)。上下文是这台 ComfyUI 和画布上开着的那张 —— `workbenchSnapshot().state.workflow`:`path` 存过的相对路径,`key` 认哪一张(没存过的形如 `workflows/Unsaved Workflow (2).json`),`temporary`。注释写着「会话和 AI 工作台是同一个池子」 |
| 免提浮标 | `features/agent/VoiceDock.tsx`,挂在 `app/App.tsx` | 对当前会话说话,没有就 `ensure` 建一条 |
| 智能体带你去 | `mcp_server.open_view` → `use_cases.set_pending_view` 写会话行的 `pending_view`(`view` 或 `view:id`)→ `useAgentNavigation`(挂在 `App.tsx` 的 Studio 那层)轮询**当前会话**,跳完 DELETE | 共享来的那条不跟。`id` 只认剪辑、笔记、3D 场景、素材库、画板;给工作流的 id 被忽略(`#/workflows?workflow=` 这条深链其实早就有) |
| 会话设置 | `useUpdateAgentSession`(模型、权限、思考档位、分析方式) | 没有会话时先 `ensure` |
| 设置 → 技能 | `features/settings/AgentSkillsSection.tsx` 的 `openAgentSession` | 写选择、跳到 AI Studio(「智能体起草」那个来源标签) |
| 内嵌浏览器「交给智能体」 | `features/browser-pool/session-tools/useStartTools.ts` 的 `startNewAgentSession` | 新建并选中、跳到 AI Studio、填草稿 |
| 确认卡 | `features/agent/ConfirmationCenter.tsx` + `confirmSurface.ts` | 不读当前会话:内联面登记「哪些会话有人在管」,没人管的卡(那段对话没开着、外部智能体)落到右上角的全局中心。卡上看不出是哪段对话的 |
| 飞书 | `integrations/feishu/inbound.py` | 每个飞书会话一条(`origin="feishu"`、`external_key`),不进界面清单(`use_cases.list_sessions` 只列 `origin == "ui"`),没有「当前」 |
| MCP | `backend/mcp_server.py` | 直连的客户端没有会话(`open_view` 回「跳不了」);`list_agent_sessions` / `notify_agent_session` 让一段对话找、通知另一段 —— 列出来的只有标题和状态 |
| 共享 | `domain/agent/sessions.py`、`domain/sharing` | 对话默认私有,主人可以共享给工作区看;`is_mine` 由后端标 |

### 会话行上已有的(`db/model_slices/agent.py` 的 `AgentSession`)

- `project_id`:外键到 `projects`(删项目时置空)。唯一的读者是系统提示里的记忆(`prompt.build_system_prompt` →
  `memory_prompt(db, workspace_id, session.project_id)`:「工作区级 + 这个项目级」)。**界面从没设过它**(`createAgentSession({ workspace_id })`),
  所以智能体用 `remember(project_id=…)` 记下的项目级记忆,今天在哪段对话里都注入不进去。
- `group_id`:AI Studio 列表里人自己建的分组(文件夹),和在哪开的无关。
- `origin`:`ui` / `feishu`,还有一种死掉的 `workflow` —— `api/routes/workflows.py` 的三条 `/workflows/{id}/agent-session(s)`,按
  `external_key = "workflow:<id>[:后缀]"` 给每个工作流开会话。前端 2026-07-21 用过(`8bbbb77d2`「工作流 AI 面板支持多会话」),07-31
  当死代码删了前端这侧(`a596ab165`),后端路由留着、只有测试在调。那几天建的行走的是 `host.create_session`、没走 `sharing.claim`,主人是空的
  —— 对谁都看不见。
- `pending_view`:见上;没有时间,所以不知道是什么时候要求的。
- 列表一次最多 50 条(`SESSION_LIST_LIMIT`),最近活跃在前。

### 工具定义的预算(ADR 0042 第一步带出来的)

- 工具定义每轮重发。sidecar 每一轮开始时用这一轮的服务令牌取 `GET /api/agent/tools`(`agent-sidecar/src/tools.ts` 的 `buildAllTools`),
  而令牌铸的时候就记着是哪段对话(`core/security.mint_service_session(agent_session_id=…)`)—— **工具清单本来就能按对话、按这一轮来裁**,
  只是现在没裁。水位(`host.session_context` → `tool_definition_tokens(db, owner)`)按人算。
- 预算:工具定义加系统提示不超过本机回退窗口(64K)的六成,即 38.4K(`backend/tests/test_tool_definitions_budget.py`,棘轮)。它只量了
  「一段挂在本机模型上、没接 ComfyUI 的对话」这一种。
- 0042 第一步给智能体加了九个 `comfy_*`。它分不出哪段对话是工作台的,只能按人裁(`@tool(needs="workflow_library")`:没接 ComfyUI 的人不发),
  和 0042 §4「都只在工作台的会话里给」对不上。接了 ComfyUI、用本机模型的人,固定开销约 39.4K,超了;预算测试量的不是这种,所以是绿的。

## Decision

### 已拍板(维护者,2026-10-07,「按推荐来」)

| # | 问题 | 定了 |
| --- | --- | --- |
| 1 | 对话记不记在哪开的 | **记**。「家」= 一种地方 + 那样东西的 id:剪辑项目、笔记、画板、工作流、3D 场景、ComfyUI 连接 + 工作流(路径;没存过的用画布标签页的 key)、AI Studio。会话表加列,带自动迁移;老对话的家全是 AI Studio;不写兼容代码。飞书 / MCP 来的照常能用(家见 §9) |
| 2 | 多细 | **每样东西各一份**:每篇笔记、每块画板、每个剪辑项目、每个工作流、每张 ComfyUI 工作流都有自己的对话 |
| 3 | 面板显示哪段 | **这一处的**:接着这一处明确选过的那段,没选过就是家在这里的最近一段;选择按东西记。一段都没有就空着,第一句话建一段、家在这里。「新对话」只换这一处 |
| 4 | 面板里的历史 | 两组:「这里的对话」在前,「其他对话」收着。从「其他对话」里挑一段,就**在这里接着聊**(成了这一处的选择),它的家不变 |
| 5 | AI Studio | **列全部**,每行写着在哪开的(「在剪辑《A》里开的」),能跳回那一页 |
| 6 | 跳页 | **智能体带着走**:对话中途它 `open_view` 带你去哪,那一处就接上这段对话,多页面的活不断;**你自己点过去的**,面板显示那一页自己的对话 |
| 7 | 免提浮标 | 在有面板的页面,对那一页的当前对话说;别处对 AI Studio 的当前对话说 |
| 8 | 工具跟着地方走(推荐,§8) | `comfy_*` 只在**这一轮是在 ComfyUI 工作台里说的**时候发;改 Mosael 自家画布的那一份在工作台里不发。预算按每一处量 |

### 1. 地方和家

**地方**(place)是一个种类加一个 id。界面上的每一处、会话的家、每条消息在哪说的,都用这同一个形状:

| `kind` | id | 哪一处 |
| --- | --- | --- |
| `studio` | 空 | AI Studio;以及「页面上没打开哪样东西」的时候(见下) |
| `project` | 项目 id | 剪辑 |
| `note` | 笔记 id | 笔记 |
| `board` | 画板 id | 创意画板 |
| `workflow` | 工作流 id | 工作流编辑器 |
| `scene` | 场景 id | 3D 场景 |
| `comfyui` | `<连接 id>/<路径>`(存过的)、`<连接 id>#<标签页 key>`(没存过的)、`<连接 id>`(画布上一张都没开) | ComfyUI 工作台 |

- 连接 id 里没有 `/`、`#`,从左边第一个 `/` 或 `#` 切开就分得清;路径是 `workflows/` 下的相对路径(桥报的 `path`),和工作流库(ADR 0035)同一种写法。
- **页面上没打开具体的东西**(笔记页没选哪篇)时,那一处就是 `studio` —— 不另造「笔记页」这种页面级的地方。ComfyUI 例外:工作台开着而画布上
  一张都没有时,那一处仍是那个连接(`<连接 id>`):在那里要新建工作流,得有 ComfyUI 那份工具(§8)。

**会话表加三列**(`agent_sessions`):

- `home_kind VARCHAR(16) NOT NULL DEFAULT 'studio'`、`home_id VARCHAR(700) NOT NULL DEFAULT ''` —— 在哪开的。建的那一刻定,**之后不变**
  (唯一的例外是 ComfyUI 工作流改名、挪位置、第一次存盘,§9)。不设外键:一列指六种表,而且要的正是「东西删了,对话照旧」。
- `pending_view_at DATETIME NULL` —— `pending_view` 是什么时候要求的(§6)。
- 索引 `idx_agent_sessions_ws_home (workspace_id, home_kind, home_id, updated_at)`:面板按「家在这里」取清单,不在全工作区前 50 条里碰运气
  —— 一篇三周前聊过的笔记,它的对话早掉出前 50 了。

**每条用户消息记下是在哪说的**:`payload["place"] = {kind, id}`(和 `quote`、`skills` 一样落在 payload 里,不加列)。飞书、另一段对话发来的
通知、老消息没有。它只有一个用处:这一轮发哪些工具(§8)。

**`project_id` 由家代替,删掉**。它唯一的用处(项目级记忆)改成读家:家是 `project` 时注入那个项目的记忆。剪辑里开的对话从此真的带上项目级
记忆 —— 这是行为变化,好的那种。

**`group_id` 不动**:分组是人在 AI Studio 里自己收拾的文件夹,和在哪开的是两回事;面板里不显示分组。

**家里那样东西删了**(推荐:**家照记,写「已删除的…」,不回落到 AI Studio**):

- 对话照常能用,AI Studio 和各处的「其他对话」里都在;只是不会再出现在哪一处的「这里的对话」里 —— 没有页面会显示一样删掉的东西。
- 名字现查(§2),查不到就写「已删除的笔记」。不在六个领域的删除路径上各挂一个「把对话的家改掉」:那是六处耦合;而且笔记从回收站恢复回来,
  对话就该跟着回来,回落到 AI Studio 会把这件事永远抹掉。
- 回收站里的笔记算还在(名字照写),恢复了一切照旧。

**迁移**(`backend/app/db/migrations.py`,一次性,带测试):

1. `_migrate_agent_sessions_remember_where_they_were_opened`(SCHEMA 之前,ORM 要指望列在):加三列和索引。老行全部 `studio` —— 维护者定的。
   同一步里两种例外,都是**记着的事实**,不是猜:
   - `project_id` 不空的(只能是经接口建的):家记成那个项目 —— 它当初就是冲着这个项目开的,项目级记忆也照旧注入;
   - `origin = 'workflow'` 的(上面那批死掉的):`origin` 改成 `ui`,家记成 `external_key` 里那个工作流,`external_key` 清空,主人记成那个工作流
     的主人(工作流已删的记工作区的 owner,和 `_migrate_resource_ownership` 当年的近似一样)。它们从此在 AI Studio 和那个工作流的面板里看得见。
2. `_drop_agent_sessions_project_id`(SCHEMA 之后):SQLite 的 `DROP COLUMN` 对外键列直接报错,`provider_profiles` 那种「删不掉就跳过」在这里是
   **永远**跳过。所以按 SQLite 文档的十二步重建这张表:**先关外键**(`PRAGMA foreign_keys=OFF`,在事务外)→ 照现在的 ORM 建
   `agent_sessions_new` → 搬数据 → 删旧表 → 改名 → 补索引 → `PRAGMA foreign_key_check` → 开外键。不关外键就删旧表,`agent_messages` 的
   `ON DELETE CASCADE` 会把全部消息一起删掉 —— 测试要钉死这一条(§12)。这是库里第一次重建一张被别的表引用着的表,写成通用的
   `_rebuild_dropping(table, columns)`,以后再删外键列用同一个。

### 2. 接口

- **建**:`POST /api/agent/sessions` 的 `home: {kind, id}` **必填** —— 不给就 422,没有「缺省当 AI Studio」这条兼容的路;`project_id` 字段删掉。
  校验:种类在表里;那样东西存在、他看得见(笔记、画板、项目、工作流、场景各按自己的读闸);ComfyUI 的连接是他能用的,路径只校验形状(那台
  机器上有没有这个文件不问 —— 要连过去,而且没存过的本来就不在)。
- **列**:`GET /api/agent/sessions?workspace_id=…&home_kind=…&home_id=…` 只列家在这里的(仍按最近活跃、50 条);不带 `home_*` 照旧列全部。
  读闸照旧(`sharing.visible_filter`,共享来的也在),`origin == "ui"` 照旧。
- **出**:`AgentSessionOut` 多 `home_kind`、`home_id`、`home_name`(现查的名字)、`home_state`(`ok` / `deleted` / `hidden`)。名字按**看的人**查:
  同事共享给你的对话,家是一篇你看不见的笔记,就是 `hidden` —— 只说「在一篇笔记里开的」,标题不漏出来。查名字是每种地方一个「按 id 批量
  取名字」的函数,登在 `domain/agent/places.py` 的一张表上(和 `domain/sharing.KINDS` 一样摊成表,agent 不去一个个 import 各领域的分支),
  一页 50 条每种地方一次查询。ComfyUI 的名字取路径里的文件名(不连那台机器),连接删了是 `deleted`。
- **发消息**:`AgentMessageCreate` 多 `place: {kind, id} | null`。只校验形状:它只决定这一轮发哪些工具,不替任何东西开权限。
- **家跟着挪**:`POST /api/agent/homes/move {workspace_id, kind: "comfyui", from_id, to_id}` —— 只收 `comfyui`(Mosael 自家的东西按 id 认,
  永远不用挪),只挪他自己的对话。见 §9。
- **不加**「在这里接着」的接口:每一处接着哪段,和今天一样是这台机器上的界面状态(§3);后端要知道的只有「这一句是在哪说的」,它已经跟着每条消息来了。
- **删**:`/api/workflows/{id}/agent-session`、`/api/workflows/{id}/agent-sessions`(GET、POST)三条,连同它们的测试和
  `tests/test_remote_rate_limit.py` 里那条分类。
- `open_view` 的 `id` 也认工作流(打开 `#/workflows?workflow=<id>`);`set_pending_view` 同时写 `pending_view_at`。
- `list_agent_sessions` 每条多一个 `where`(「在笔记《B》里开的」那句):智能体找该通知谁时,看得出哪段是哪儿的。
- 重新导出 `openapi.json`、生成前端类型。

### 3. 前端:每一处一个「当前」

`currentAgentSession.ts` 那一套原样推广,**键从「工作区」变成「工作区 + 地方」**:

- **选择**:还是只存「明确选过的会话 id」。AI Studio 那一处的键**就是现在这个** `mosael.agent.session.<工作区 id>` —— 迁移后老对话的家全是
  AI Studio,这个键原来的意思正好就是「AI Studio 那一处选过的」,不用搬、不留旧键。别的地方是
  `mosael.agent.session.<工作区 id>.<地方键>`(`note:<id>`、`comfyui:<连接 id>/<路径>`……)。同一窗口广播、跨窗口 `storage` 事件,照旧。
- **现算**:这一处选过的那段还在(他看得见)就是它 —— 家在哪都行,那是在这里接着的;否则是**家在这里、自己的**最近一段;都没有就是空。
  清单是 `["agent-sessions", 工作区, 地方键]`(家在这里的);选过的那段家在别处时,读它自己的 `["agent-session", id]`(面板本来就在轮询它),
  不依赖全工作区那 50 条。
- **回落不写回,用上才写回**:照旧。`ensure` 写回的是**这一处**的选择;一段都没有时建一段,**家就是这一处**。同一处同时只跑一个 ensure。
- **只能看的**:照旧 —— 回落只落在自己的上;明确挑了一段共享来的就看它;`ensure` 遇到只读的就拒。
- **在这里接着**(拍板 4)、**智能体带过来**(拍板 6)、**AI Studio 的「回到那里」**(拍板 5)是同一个动作:`adoptAgentSession(工作区, 地方, 会话 id)`
  —— 写这一处的选择,不碰家。
- **删了**:`forget` 把指着这几段的选择全清掉(扫这个工作区前缀的键)。

**页面怎么说自己在哪**:一个 hook,`useAgentPlace(place)`,在**页面**那一层调(不是面板那一层 —— 面板收起来时浮标和跳转也要知道你在哪),
返回同一个 `place` 交给 `CanvasAgentChat` 的 `place`(必填)。它同时把这一处登记成「这个窗口眼下在哪」:一个模块级的栈(和 `confirmSurface`
的登记处一样小),后挂上的在上面 —— 工作台盖在页面上时是工作台,关了退回页面;栈空就是 `studio`。`useActivePlace()` 读栈顶,浮标和跳转用它。

| 页面 | `place` |
| --- | --- |
| 剪辑 `EditorView` | `{kind: "project", id: project.id}` |
| 笔记 `NotesView` | 开着一篇 → `{kind: "note", id}`;没开 → `studio` |
| 创意画板 `BoardsView` | `{kind: "board", id: board.id}` |
| 工作流 `WorkflowEditor` | `{kind: "workflow", id: workflow.id}` |
| 3D 场景 `SceneStudio` | `{kind: "scene", id: initial.id}` |
| 工作台 `ComfyWorkbench`(登记)→ `AssistantPanel`(收 `place`) | `comfyPlace(target.instanceId, state.workflow)`:换标签页就换地方 |

`CanvasAgentChat` 不再有别的会话来源;页面传的 `contextLine` 照旧只管给模型看的那段话。

### 4. 面板(拍板 3、4)

- 标题(`AgentSessionSwitcher`)是当前这段的名字;它的家不在这里时,标题下一行小字「这段对话是在剪辑《A》里开的」。
- 下拉:搜索框;「这里的对话」(家在这里的,最近在前);「其他对话」默认收着,展开是全工作区其余的(每行一句「在…里开的」)。搜索两组一起搜,
  命中「其他对话」就自动展开。挑「其他对话」里的一段 = 在这里接着(`adoptAgentSession`):之后打开这一处就是它,它的家不变,AI Studio 里照旧写着
  原来那个地方。全工作区那份清单只在下拉展开时取。
- 「新对话」:在这一处建一段,家在这里,只换这一处。
- 空态(这一处一段都没有):页面原来那句「能干什么」(`emptyHint`)下面加一句「这里还没有对话,发第一句话就开一段」;工作区里有别的对话时再给
  一个「接着别处的对话」,点了打开下拉、展开「其他对话」。
- 每条发出去的消息带 `place`(面板这一处)。

### 5. AI Studio(拍板 5)

- 列表照旧列全部(`origin == "ui"`、最近 50 条、分组、分享都不变),每行标题下一行「在剪辑《A》里开的」。**家在 AI Studio 的那些行不写**
  —— 在 AI Studio 里每行都说「在 AI Studio 里开的」只是噪音。这比「每行写着在哪开的」少了一种,推荐如此,特此说明。
- 行上多一颗「回到那里」:`adoptAgentSession(它的家, 这段)` 再跳到那一页(剪辑、笔记、画板、工作流、场景用现有的深链;ComfyUI 的打开工作台、
  打开那张)。家已删除、看不见、或是没存过的 ComfyUI 标签页(回不去了)的,不给这颗。
- 在 AI Studio 里点开哪段,就是在 AI Studio 这一处接着它(写 AI Studio 的选择,不改家)。AI Studio 没选过时显示**家在 AI Studio 的**最近一段
  —— 和各处同一条规则,不是全工作区最近的一段;不然刚在笔记里聊完,进 AI Studio 又接着那段,干扰又回来了。
- `openAgentSession`(技能的来源标签)= 在 AI Studio 接着它;`startNewAgentSession`(「交给智能体」)= 在 AI Studio 建一段,家是 AI Studio。

### 6. 智能体带着走(拍板 6)

**接力**:`useAgentNavigation` 盯的是**眼下这一处的当前对话**(`useActivePlace()` 那一处的,只读的不盯)。看到 `pending_view` 时:

1. 记一根接力棒:「这段对话要跟过去」(模块级,10 秒有效);
2. 跳(和今天一样;`workflows` 多认 id);
3. **跳过去之后第一个变成「眼下这一处」的地方接住它** —— `adoptAgentSession(那一处, 这段)`,棒子用掉;
4. DELETE `pending_view`。

不在 App 里另写一张「哪个视图 + id 对应哪个地方」的表:跳过去的页面自己会登记它在哪,地方由页面说了算 —— 不带 id 的
`open_view("editor")` 落在剪辑页实际打开的那个项目上,也自然对。

- **跳到没有面板的页面**(素材、发布、设置……,推荐):那里的「眼下」是 `studio`,于是 **AI Studio 那一处接住这段对话** —— 浮标和跳转在那种页面上
  看的就是 AI Studio 的当前对话,接住了免提对话才不断,它下一次 `open_view` 也还有人跟。代价是之后打开 AI Studio 看到的是这段 —— 那正是你刚才在聊的。
- **跳到同一处**(已经在那篇笔记里):地方没变,棒子过期作废,本来就是它。
- **你自己点过去**:没有棒子,面板显示那一处自己的对话。
- **过期的「带我过去」不跟**(推荐):`pending_view_at` 超过 30 秒的,前端清掉、不跳。原来只有一个当前会话,它要求的跳转总有人在盯;现在一段对话可能
  在你离开的那一处接着跑、要求跳转时没人盯 —— 你一分钟后回去看结果,不该被拽走。
- **工作台里开新标签页**(ADR 0042 第二步的 `comfy_canvas_new`):画布上的动作走「后端 → 主进程 → 页面」,不走 `pending_view`。工作台动作带上是哪段
  对话发起的,主进程开好新标签页后随状态报回一次 `openedBy`,工作台据此让新标签页那一处接住这段对话。不靠轮询赛跑:新标签页一出现,「眼下这一处」
  就换了,`pending_view` 那条路会接不着。

### 7. 免提浮标(拍板 7)

浮标对 `useActivePlace()` 那一处的当前对话说话 —— 页面登记了就是那一页(面板开没开都算),没登记就是 AI Studio;一段都没有就在那一处建一段。
每句带 `place`。当前那段是只读的,照旧说清楚、不另建。

### 8. 工具跟着地方走(推荐)

- **这一轮在哪**:这一轮要回答的用户消息里最新一条的 `place`;没有(飞书、另一段对话的通知、老消息)就用这段对话的家。
- **工具分三份**,在 `mcp_server.tool` 上声明 `kit`:
  - 不声明 —— 通用,哪儿都发:素材、生成、笔记、技能、记忆、计划、`open_view`、浏览器、任务……以及各种「列出 / 读」;
  - `kit="comfyui"` —— `comfy_*`(0042 第一步的九个,第二、三步加的改图、新建、装节点包、试跑也进这一份):**只在这一轮在 ComfyUI 工作台**时发。
    `needs="workflow_library"` 照旧叠在上面:没接 ComfyUI 的人在哪都不发;
  - `kit="canvas"` —— 改 Mosael 自家画布的那一份:`edit_board`、`get_board`、`run_board_item`、`list_board_producers`、`edit_timeline`、`edit_scene`、
    `view_scene`、`render_scene_references`、`list_scene_models`、`edit_workflow`、`update_workflow`、`list_workflow_node_types`、`blender_*`。
    **工作台以外哪儿都发**,工作台里不发。
- **为什么这样分**:ComfyUI 工作台是另一个世界,那里要的是 ComfyUI 的图,不是 Mosael 的画板和时间线;反过来,AI Studio 和 Mosael 各页面之间
  串门是常事(在画板里让它建一条时间线),那几样不按页面拆。按 main 的注册表量,`canvas` 这一份约占工具定义的 27%(约 8K token),
  `comfy_*` 九个约 7K:**工作台里约 31.5K、别处约 32.5K**,都在 38.4K 以内,还给 0042 后两步要加的 `comfy_*` 留了地方。名单以预算测试为准。
- 在工作台以外问 ComfyUI 的事,它手里没有那份工具:ComfyUI 插件带的技能(`comfyui-workflows`)说明里写一句「在 ComfyUI 工作台里用」;
  要改图,请他到工作台里说。
- **实现**:`/api/agent/tools` 由令牌认出对话(本来就认得),按「这一轮在哪」裁;水位改成 `tool_definition_tokens(db, session)`,用同一个函数、
  同一个答案 —— 面板上的水位就是这一处这一轮真发出去的。没有对话的调用方(MCP 直连、界面拉工具清单)照旧全给。
- 换了地方的那一轮工具清单变了,供应商那边的提示缓存会断一次(工具在请求最前面);只在换地方时发生,接受。历史里调过、这一轮没发的工具,
  模型看得到调用记录,再调会被 pi 回「没有这个工具」。
- 预算测试按每一处量(§12)。

### 9. 边角(推荐,按定了写)

| 情形 | 定了 |
| --- | --- |
| ComfyUI 没存过的那张,后来存盘了 | 家跟着挪。桥在**同一个标签页**(前端的同一个工作流对象)换了路径时,随下一次状态报一次 `renamedFrom`;工作台调 `/agent/homes/move` 把 `<连接>#<key>` 挪到 `<连接>/<路径>`,这一处的选择键一起改。ComfyUI 存一张临时工作流是给它改名再存,对象不变;「另存为」是新对象、新地方,对话留在原来那张。「存临时那张对象不变」要在测试场的 0.39 / 前端 1.53.10 上实测 |
| ComfyUI 工作流改名、挪文件夹 | 两条路:在 ComfyUI 里改的走桥的 `renamedFrom`(同上);在 Mosael 工作流库(ADR 0035)里改名、挪、移进回收目录的,后端那个用例在同一个事务里调 `places.move`。工作台没开着时在 ComfyUI 里改的,Mosael 看不见 —— 那几段对话留在旧路径上、显示原来的文件名,只出现在「其他对话」里;接受,不丢 |
| ComfyUI 没存过的那张关了,后来新开的一张正好同名(key 复用) | 新的那张会把旧的那几段当成「这里的对话」。ComfyUI 不告诉我们标签页关了;没存过的东西本来就是临时的,接受。要避免就先存盘 |
| Mosael 的工作流改名、挪动 | 按 id 认,什么都不用做;名字现查 |
| 复制一篇笔记(画板、项目、工作流同) | 对话不跟着复制;新的那份从空开始 |
| 两个窗口开着同一处 | 同一个选择键:两边显示同一段、一起换(在其中一个点「新对话」,另一个跟着换 —— 那是同一处)。开着不同的地方,各显示各的。接力棒每个窗口自己的;两个窗口都在盯那段对话时,两个都跟过去(和今天一样) |
| 跳到没有面板的页面 | AI Studio 那一处接住(§6) |
| 离开时那段对话还在跑 | 照跑,不停;它仍是那一处的选择,回来就看到进度。它的确认卡那时没有内联面在管,落到右上角全局中心(今天就是这样)—— 卡上加一行「在笔记《B》里开的」和「回到那里」,不然好几段同时在跑时看不出是谁在问。它在你离开期间要求的跳转,30 秒后作废(§6)。浮标跟着你走,不再对它说话 |
| 同事共享来的对话 | 只能看,规矩不变。家在你看得见的地方时,也列进那一处的「这里的对话」(带眼睛),但回落永远不落在它上面;家的名字按看的人查,看不见就不写名字 |
| 飞书的会话(含群聊) | 家是 AI Studio(列的默认值)。它们本来就不进界面清单;消息没有 `place`,工具按家发(通用 + Mosael 画布那份) |
| MCP | 直连的客户端没有会话,不受影响;`notify_agent_session` 发进去的那条没有 `place`,对方那一轮按它自己的家发工具 |
| `project_id` / `group_id` | `project_id` 由家代替、删列(§1);`group_id` 留着,是另一回事 |
| 浮标所在的那一处一段都没有 | 在那一处建一段(和面板发第一句话一样) |

### 10. 界面用词

| 用在哪 | 中文 |
| --- | --- |
| 下拉第一组 | 这里的对话 |
| 下拉第二组(默认收着) | 其他对话 |
| 当前这段的家不在这里(标题下一行) | 这段对话是在剪辑《A》里开的 |
| 空态 | 这里还没有对话,发第一句话就开一段 |
| 空态里的链接 | 接着别处的对话 |
| 「新对话」的悬停说明 | 在这里开一段新对话(面板上这颗现在叫「新开会话」,改成和 AI Studio 一样的「新对话」) |
| AI Studio 行上 | 在剪辑《A》里开的 / 在笔记《B》里开的 / 在创意画板《C》里开的 / 在工作流《D》里开的 / 在 3D 场景《E》里开的 / 在 ComfyUI 的《F》里开的(没存过的:在 ComfyUI 没存过的《F》里开的;一张都没开:在 ComfyUI「家里那台」里开的) |
| 家删了 | 在已删除的笔记里开的(项目、画板……同);连接删了:在已删除的 ComfyUI 连接里开的 |
| 家看不见 | 在一篇笔记里开的 / 在一个剪辑项目里开的 …… |
| 行上、全局确认卡上的按钮 | 回到那里 |

英文照这个意思写(`Opened in Edit "A"`、`Here`、`Elsewhere`……)。

### 11. 分四步(和 ADR 0042 的次序)

0042 第一步正要合进 main,第二、三步在后面。

1. **后端:家**(不依赖 0042,紧跟 0042 第一步合):三列、索引、迁移(含 `origin='workflow'` 那批、`project_id` 转家、重建删列)、建会话必须带家、
   按家列、出参的家和名字、消息的 `place`、`/agent/homes/move`、记忆读家、删三条工作流会话路由、`open_view` 认工作流 id、`pending_view_at`、
   `list_agent_sessions` 的 `where`。前端这一步只让所有建会话的地方传 `studio`、类型过得去 —— 合进去以后行为和今天一样。
2. **前端:每一处各接各的**(要 0042 第一步已合 —— 工作台的 `AssistantPanel` 在那):地方和登记栈、`currentAgentSession` 按地方、`CanvasAgentChat`
   的 `place` 和两组下拉、空态、五个页面和工作台说自己在哪、消息带 `place`、浮标、跳转接力和 30 秒作废、AI Studio 行上的「在…里开的」和
   「回到那里」、全局确认卡上那一行。删掉笔记页「换一篇笔记不换会话」和 `AssistantPanel`「和 AI 工作台同一个池子」的说法。
3. **工具跟着地方走**(紧跟第 2 步,**排在 0042 第二步之前**):`kit` 声明、`/api/agent/tools` 和水位按这一轮在哪裁、按每一处量的预算测试、
   ComfyUI 技能说明那一句。之后 0042 第二、三步加的 `comfy_*` 一律进 `kit="comfyui"`,有预算测试替它们看着。
4. **ComfyUI 的家跟着走**(并进 0042 第二步 —— 它本来就要升桥的版本、加 `comfy_canvas_new`):桥报 `renamedFrom` 和 `openedBy`、工作台调
   `/agent/homes/move`、工作流库改名 / 挪动的用例里挪家、新标签页接住发起它的那段对话。

**工作台的「助手」从哪拿到地方**:`ComfyWorkbench` 手里有连接(`target.instanceId`)和画布上开着的那张(`state.workflow` 的 `path` / `key`),
在它那一层调 `useAgentPlace(comfyPlace(…))`,把返回的 `place` 交给 `AssistantPanel` → `CanvasAgentChat`。换标签页(`workflowKey` 变了)就是换地方,
面板跟着换成那一张的对话;每条消息带这个 `place`,这一轮就有 `comfy_*`。

### 12. 测试

**前端单元**(`currentAgentSession.dom.test.tsx` 扩写,新增 `places.test.ts`):
- 地方键:每种地方 ↔ 键来回一致;ComfyUI 的三种 id 切得开(路径里带 `#`、`/` 也行);
- 各记各的:A 处选了 s1,B 处现算不受影响;A 处「新对话」不改 B 的键;
- 回落只落在家在这里、自己的最近一段;家在别处的不回落过来;不写回(回落之后键还是空的);
- `ensure` 建的那段家是这一处、只写这一处的键;同一处并发只建一段,不同处并发各建各的;
- 在这里接着:挑一段家在别处的 → 这一处的当前是它,`PATCH` 一次都没调(家不变);
- 只读:回落跳过共享来的;明确挑了共享来的 → `readOnly`;`ensure` 拒;
- `forget` 清掉所有指着它的选择;
- 登记栈:页面 → 工作台盖上去 → 关掉,`useActivePlace` 依次是页面、工作台、页面;都卸了是 `studio`。

**迁移**(新增 `tests/test_agent_sessions_remember_where_they_were_opened.py`):拿老形状的库(带 `project_id` 外键、`origin='workflow'` 的行,
以及消息、确认卡、技能的 `agent_session_id`、`auth_sessions.agent_session_id` 指着这些对话)跑一遍:
- 普通的行家是 `studio`;`project_id` 不空的家是那个项目;`workflow` 那批成了 `ui`、家是那个工作流、有了主人、`external_key` 空;
- `project_id` 列没了;**消息、确认卡、技能、登录会话上指着对话的,一条都没少**(故意不关外键重建时这一条要红);`PRAGMA foreign_key_check` 干净;
- 再跑一遍什么都不变;两步都在 `migration_plan()` 里。

**接口**:建会话不带家 422、家是看不见的东西 404、连接不是他的 422;`home_kind` / `home_id` 只列家在这里的,能列出掉出前 50 的老对话;
出参的 `home_state` 三种(同事共享来、家是你看不见的笔记:响应里没有那个标题);`/agent/homes/move` 只收 `comfyui`、只挪自己的;消息的 `place`
落进 payload;`open_view("workflows", id)`;删掉的三条路由 404。

**工具和预算**(`test_tool_definitions_budget.py` 扩写):
- **接了 ComfyUI + 本机模型,按每一处量**:`studio`、`project`、`note`、`board`、`workflow`、`scene`、`comfyui` 各建一段家在那里的对话,水位里的
  工具 + 系统提示都不超过 64K 的六成;`test_量到的是真东西` 也按每一处跑;
- `comfy_*` 在且只在 `comfyui` 那一处;`canvas` 那一份在且只在 `comfyui` 以外;
- 家在 AI Studio、最新一条消息在工作台说的 → 这一轮有 `comfy_*`、没有 `canvas`;再在 AI Studio 说一句 → 反过来;
- 没有对话的调用方(MCP 直连)全给;没接 ComfyUI 的人,在工作台那一处也没有 `comfy_*`。

**DOM**(新增 `CanvasAgentChat.places.dom.test.tsx`,扩写 `useAgentNavigation.dom.test.tsx`、`VoiceDock.dom.test.tsx`):断言**面板里画出来的那段对话**
(消息正文)和**消息发进了哪段**(POST 的地址、带的 `place`),不只看键 —— 标记落在空容器上,断言天然成立:
- 换页不带对话:在剪辑 A 聊着 s1 → 打开笔记 B,B 的面板是空态、没有 s1 的消息;在 B 发第一句,建会话的请求带 `home={note, B}`;回到 A 还是 s1;
- 智能体带着走:A 的当前 s1 上出现 `pending_view = notes:B` → 跳到 B,B 的面板显示 s1,下一句发进 s1、带 `place={note, B}`;接着**自己**点开笔记 C
  → C 是空的;
- 带到素材页 → AI Studio 那一处接住;
- `pending_view_at` 是 40 秒前的 → 不跳,DELETE 了;
- 「其他对话」里挑 s9 → 这一处接着 s9,AI Studio 列表里 s9 的家没变;
- 「新对话」只换这一处:A、B 两个面板同时挂着,在 A 点,B 不动;
- 浮标:在有面板的页面(面板收着)说话 → 发进那一页的当前;在素材页说 → 发进 AI Studio 的当前;
- 工作台换标签页 → 面板换成那一张的对话;`renamedFrom` 来了 → 调一次 `/agent/homes/move`,面板还是那段。

**变异检查**(在隔离的后端和前端上做,不碰 8800 那台开着 `--reload` 的 dev 服务器;前端带 `VITE_MOSAEL_API_URL`):逐条故意改坏,确认上面有测试变红 ——
- 现算时不看地方(回落到全工作区最近一段)→「换页不带对话」红;
- 回落写回 → 单元「不写回」红;
- 棒子不接,或接到上一处 →「智能体带着走」红;
- `ensure` 建会话不带这一处的家 → 单元和 DOM 红;
- 挑「其他对话」时顺手 PATCH 了家 →「在这里接着」红;
- 工具清单不看这一轮在哪 → 按每一处的预算、「`comfy_*` 在且只在」红;
- 重建删列时不关外键 → 迁移测试红;
- 不看 `pending_view_at` →「过期不跳」红;
- 列表忽略 `home_*` 参数 → 接口测试红。

## 这一版不做

- 在服务端记「每一处接着哪段」(跨设备、网页版和桌面版之间同步):今天的选择就是这台机器上的界面状态,这一版不变。
- AI Studio 按「在哪开的」筛选、分组,按地方翻页。
- 把一段对话的家改到别处(ComfyUI 改名、存盘那种跟着走除外)。
- 消息气泡上标「这句是在哪说的」(`place` 已经存着,要显示以后再做)。
- 技能目录跟着地方走(ComfyUI 那份技能在别处也列着,只在说明里写「在工作台里用」)。
- `blender_*` 按有没有接 Blender 来裁(和 `comfy_*` 的 `needs` 同一种做法);这一版只把它们放进 `canvas` 那一份。
- 生成页的会话(`generation_sessions`,`generationSessionSelectionKey`)不在此列。

## Consequences

- 每一处有了自己的对话:在笔记里聊的不再接着剪辑里那段,「新对话」只换这一处;AI Studio 成了看全部、认得出每段在哪开的、能跳回去的地方。
- 「唯一来源、回落不写回、共享只能看」三条原样留着,只是键多了一维。代价是同一时刻可能有好几段对话在不同的地方跑 —— 所以全局确认卡要写明是
  哪段的,过期的跳转作废。
- 智能体跨页面的活不断:它带到哪,哪一处就接着这段;你自己走过去的不受打扰。
- 工具清单第一次按「这一轮在哪」裁:接了 ComfyUI 的本机模型用户回到预算以内,0042 §4「只在工作台的会话里给」第一次真的成立;工作台里的对话
  不再背着画板、时间线那一整套编辑工具。换地方的那一轮会断一次提示缓存。
- 剪辑里开的对话第一次带上项目级记忆。
- 会话行第一次指向六种东西而不设外键:名字靠现查,删了的写「已删除的…」;ComfyUI 的路径要在改名、存盘时挪 —— 漏掉的(工作台没开着时在
  ComfyUI 里改名)只会落进「其他对话」,不丢。
- **删掉的代码**:三条工作流会话路由和它们的测试;`AgentSessionCreate.project_id` 和 `start_session` / `host.create_session` 的 `project_id` 参数;
  `agent_sessions.project_id` 列;只按工作区的 `useCurrentAgentSession` / `ensureAgentSession` 签名(调用方全部改成带地方);笔记页「换一篇笔记
  不换会话」、`AssistantPanel`「和 AI 工作台同一个池子」的说法。没有任何「没带家就当 AI Studio」的分支。
- 库里第一次重建一张被别的表引用着的表;留下的 `_rebuild_dropping` 以后删外键列照用。

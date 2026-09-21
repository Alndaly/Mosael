# 前端架构审计:同一件事,在前端这几条路上都成立吗

> 日期:2026-09-21 · 基准提交:`e58190f2`(工作区干净)· 范围:`frontend/src/`
> (不含后端、Electron 壳、agent-sidecar、website;后端只作为"另一侧的事实"被读,不作结论)
>
> 方法沿用 [`2026-09-21-chain-audit.md`](2026-09-21-chain-audit.md):不通读 131,244 行,而是挑
> 出「同一份语义要在多处成立」的地方逐条走。凡写"实测",都是当场跑过或数过的。
>
> 这一份专查那份审计归纳出的两类失败在**前端范围内**还成立不成立:
>
> 1. 一个属性由多处累加/各写一遍决定 —— 判据不是"现在看着对"(§3 第四处就是两个数碰巧相等);
> 2. 断在最后一环 —— 后端给了而前端没人消费,或前端读了一个后端不保证的字段。

---

## 0. 结论先写

前端的架构纪律同样在执行,而且比后端更"可见":`design/` 下 14 道棘轮 + `features/featureBoundaries.test.ts`
+ `api/queryKeys.test.ts` + 8 份 `*.parity.test.ts`,每一道开头都写着它因为什么事故存在。实测几条
最容易出事的链条都是**通的**:功能模块依赖图无环(任意长度)、React Query 的失效键没有一处比
取数键长、11 份契约语料两侧都有人跑。

**但棘轮本身出现了同一类漏洞,而且形状和它们要防的东西一模一样:规则写下来了,扫描范围没跟上。**

- `design/unlayeredGlobals.test.ts` 因为"不分层的 CSS 压死整族工具类"栽过两次而立,**只读 `tokens.css` 一个文件**;
  而 `features/scenes/scenes.css`(1400+ 行)和 `features/notes/notes.css` **一条 `@layer` 都没有**。
- `lib/typeScale.test.ts` 禁止写死字号,**只扫 `.ts`/`.tsx` 且只认 `text-[Npx]`**;
  而 `scenes.css` 里有 12 处 `font-size: <n>px`(10/11/12/13/14/16/22),同一个文件里另有 40 处规规矩矩用 `var(--text-ui-*)`。
- `features/featureBoundaries.test.ts` 的断言是"没有**两个**功能互相依赖" —— 三环及以上它不会响(实测当前无环,所以它今天是对的,但它的沉默不构成证据)。

另有两条完整的断链(`ClipOut.linked_clip_id` 四层全有、无人写入无人消费;`WorkspaceSummaryOut`
八个用量字段后端算完没人读),以及一处**同一段流式协议被两个页面各实现一遍、已经分岔**。

---

## 1. 逐条走过的关键链条

判据统一:链条上每一环都要么能指出消费点,要么能指出它为什么不需要。

| # | 链条 | 结论 |
| --- | --- | --- |
| 1.1 | 素材导入 → 代理转码 → `media_info.proxy_status` → 预览遮罩 → 重试按钮 | **成立**(一处配置死角,见 §2.7) |
| 1.2 | 时间线拖拽 → `dragDraft` → 服务端回包 → 落位动画 | **成立**,`settling` 那段收敛得很干净 |
| 1.3 | 分离音频 → 视频片段 + 音频片段配对 → 一起移动/删除 | **断**:`linked_clip_id` 从未被写入,也从未被读(§2.1) |
| 1.4 | 序列 → 导出参数 → `/api/sequences/{id}/export` | **成立**,但类型是手抄的一份影子(§2.5) |
| 1.5 | 预览 ↔ 导出画面一致(ADR-0004) | **成立**:8 份 `*.parity.test.ts`,契约语料两侧同跑 |
| 1.6 | 后端算用量/费用 → `WorkspaceSummaryOut` → 统计页 | **断在最后一环**:8 个字段没有任何消费点(§2.2) |
| 1.7 | 智能体一轮 → SSE `{text, done, timeline}` → 两个聊天面板 | **断**:`done` 两处都不读;两处实现已经分岔(§2.3) |
| 1.8 | 自动放行(autopilot)判定 → `decision_mode` / `mode_set_by` → 界面 | **断在最后一环**:前端只查 `status=pending`(§2.4) |
| 1.9 | 笔记被改 → 画板上的文档节点 → 生成时带上原文 | **成立**:键里带 `note_revision`,内容寻址,改版自动换键 |
| 1.10 | 素材导入 → 各页素材列表失效 | **成立**:`assetKeys` 收口 + 棘轮;实测全仓无失效键长于取数键的家族 |
| 1.11 | 画布标记(两块画布)→ React Flow 节点 → 汇出成两份列表 | **成立但两处各写一遍,且已分岔**(§2.6) |
| 1.12 | 按需加载 → 页面私有副作用 | **CSS 分层这一环断了**(§2.8);JS 侧干净(实测无模块级裸调用) |
| 1.13 | `contracts/shared-constants.json` 的 56px 四处实现 | **成立**,四处实测都是 56;但校验只跑在 `backend/tests`(§2.11) |
| 1.14 | 功能模块依赖图 | **成立**:9 条边、0 个环(长度 2..5 全枚举) |

---

## 2. 问题清单(按严重度)

### 2.1 【高】`linked_clip_id` 四层都有,而没有任何一处写它

**现象**。`Clip` 上有一个 `linked_clip_id`,它出现在:

- `backend/app/db/model_slices/sequences.py:74`(表列)
- `backend/app/api/schemas/sequences.py:36`(接口 out)
- `frontend/src/api/generated/schema.d.ts:7381`(生成的前端类型)
- `backend/app/domain/sequences/operations.py:1556`(`RESTORABLE_CLIP_FIELDS`,撤销要还原它)
- `backend/app/domain/sequences/undo/rows.py:48`(重建行时读它)

实测全仓 grep:**没有任何一处赋值**。`detach_clip_audio`(`operations.py:835`)正是那个本该建立配对的
操作 —— 它新建一个音频片段、把原片段静音,然后结束,不设这个字段。前端侧 `frontend/src/` 内除
生成的 `schema.d.ts` 外**零命中**。

**为什么看不出来**。它永远是 `null`,所以每一层读它都"正常工作"。
`operations.py:1560` 那段注释甚至认真论证了它为什么不该进 `INHERITED_CLIP_FIELDS`
(「那配对的是两个具体的行,而切出来的是新行」)—— 一个从不存在的配对,被精心地排除在继承之外。

**为什么是架构问题**。用户对"分离音频"的期待来自 PR/DaVinci:分离出来的两段是**链接**的,拖一个
另一个跟着走,删一个另一个一起删。这套语义的落点就是这个字段。现在的状态是:数据形状宣称
支持它,五处代码为它让路,而行为一处也没有 —— 于是下一个人读到这个字段会以为链接已经实现,
去查为什么"没生效";而真相是从来没人写过它。这比没有这个字段更贵。

**建议**。二选一,不要留第三态:

- 要这个功能:`detach_clip_audio` / `separate_audio` 落对子,前端在移动、删除、裁剪三条路上
  各查一次配对,并**补一条棘轮**——"声明了配对字段的操作,必须有一处消费它"(同 `test_executor_outputs_are_declared.py` 的形状:静态对一遍"谁写 / 谁读")。
- 不要:连列带 schema 一起删,按仓库规矩配一支迁移(不写兼容分支)。

---

### 2.2 【高】首页要"一次给全一屏",给了八样没人看的

**现象**。`backend/app/api/schemas/dashboard.py:73` 的 `WorkspaceSummaryOut` 里,下列字段在
`frontend/src/` 非测试代码中**一次都没被读过**(脚本扫全部 97 个被前端消费的 schema,逐字段
对全仓源码做词边界匹配):

```
publish_accounts, usage_cost_micros, usage_duration_seconds,
usage_token_count, usage_cache_read_tokens, usage_cache_write_tokens,
usage_by_capability, usage_by_provider
```

唯一的消费者 `frontend/src/features/statistics/StatisticsView.tsx` 读的是**逐日序列**
(`usage_daily`、`usage_token_daily`)和几个计数,不读任何**合计**与**分组**。最刺眼的一处:
「AI 用量」那块磁贴显示的是 `usage_event_count`(调用了几次),而同一个回包里躺着
`usage_cost_micros`(花了多少钱)和它配套的 `usage_currency` —— 而 `usage_currency` 是被读的,
它被传给了费用图表。也就是说**"货币单位"用上了,"钱数"没用上**。

**为什么看不出来**。多返回几个字段不会让任何东西变红;而 `usage_by_capability` / `usage_by_provider`
带 `Field(default_factory=dict)`,连"空"都是合法值,后端自己也无从判断有没有人要。

**为什么是架构问题**。这个 schema 的 docstring 写着「一次请求给全一屏,避免首页发 N 个列表请求
做 `.length` 聚合」—— 它的存在理由就是"前端要什么,这里一次给齐"。八个没人要的字段让这句话
不再成立:现在没人知道这个回包里哪些是界面需要的、哪些是历史残留,于是**下一次改统计页的人
既不敢删也不敢信**。而按供应商/能力分组的聚合在后端是有成本的(近 14 天的用量事件join 价格规则),
每次打开首页都算一遍扔掉。

**建议**。把"后端算了什么"和"界面看什么"对齐,两个方向都可以:要么统计页把合计与分组用起来
(费用磁贴显示钱而不是次数,费用图下面加一行按供应商的分布),要么从 schema 里删掉。
配一条同形棘轮:**接口 out schema 的字段 → 前端消费点**,静态扫一遍,白名单里写清楚哪些字段
是给别的运行时(agent-sidecar / MCP)而不是给界面的。这正是上一份审计 §5.1 点名要补的第二条。

---

### 2.3 【高】同一条流式协议,两个聊天面板各实现一遍,已经分岔

**现象**。`/api/agent/sessions/{id}/stream` 的事件体由后端在
`backend/app/api/routes/agent.py:309-317` 组装,形状是 `{text, done, timeline}`。前端有**两个**
消费者,各自手写一份断言:

| | 文件:行 | 断言的形状 | 一轮结束时 |
| --- | --- | --- | --- |
| AI 工作台 | `features/ai-studio/ChatWorkspace.tsx:142-146` | `{text, done, timeline?}` | `await Promise.all([...])` 两条失效**一起 settle**(:165) |
| 画布助手 | `features/agent/CanvasAgentChat.tsx:334-337` | `{text, timeline?}` —— **没有 `done`** | `void` 各发各的(:352) |

两件事:

1. **`done` 谁都不读。** 后端明确发了一个结束信号,两个客户端都靠"流关了"来推断结束
   (功能上等价,因为 `agent.py:317` 发完 `done` 就 break)。一个字段在协议里、在一侧的类型断言里,
   而没有任何一处 `payload.done`。
2. **收尾那一步已经分岔。** ChatWorkspace 那边有一段很长的注释解释为什么必须 `await`:
   「让 running 转 false(临时气泡消失)与正式消息出现落在同一帧 …… 无空白也无重复」。
   CanvasAgentChat 走的是没修之前的写法 —— 也就是说**画布助手每答完一句仍会闪一下**,
   而那个 bug 在隔壁文件里被诊断、被注释、被修好了。

**为什么看不出来**。`as {...}` 断言绕过类型检查:少写一个字段不报错,多写一个也不报错。
而那一闪只有 1 帧,在画布助手这种浮窗里更不容易被当成 bug。

**为什么是架构问题**。这两个面板是同一个东西的两个入口 —— 它们已经共享了 20+ 个
`@/features/agent/*` 组件(`AgentTurnContent`、`ChatComposer`、`InlineConfirmations`…),
**唯独"连流 → 攒状态 → 收尾失效"这段状态机各写一遍**。修一处漏一处是必然的,这次是收尾,
下次是断线重连或取消。

**建议**。把这段收进 `features/agent/` 的一个 hook(`useAgentTurnStream(sessionId)`),返回
`{streamText, streamTimeline}`,收尾逻辑只有一份;协议形状从生成的 schema 取,不再手写断言
(见 §2.5)。`done` 要么读(用它来结束,而不是靠流关闭),要么从后端删掉 —— 留着的代价是
下一个人以为它有用。

---

### 2.4 【中高】自动放行留了痕,而人看不到

**现象**。后端为"这次写操作是谁批的、怎么批的"准备了完整的一套:

- `ConfirmationOut.decision_mode`(`backend/app/api/schemas/agent.py:248`):`manual` / `auto` / `bypass` / `session-allow`
- `ConfirmationOut.resolved_at`(:251)
- `AgentSessionOut.mode_set_by`(`schemas/agent.py:148`)

前端对 `/api/confirmations` 只有两个调用点,`features/agent/InlineConfirmations.tsx:59` 和
`features/agent/ConfirmationCenter.tsx:25`,**两个都写死 `status=pending`**。于是
`ConfirmationOut` 里"决策之后"的那一半(`decision_mode` / `resolved_at`)在界面上不存在。
`mode_set_by` 同理:`frontend/src/` 零命中。

后果两处:

- **自动放行的写操作和普通工具调用在界面上长得一样。** 用户在某次对话里开了 auto 档,
  之后智能体每做一次被闸门管着的写操作,卡片开出来即被判定放行(`domain/agent/autopilot.py:decide`),
  用户看到的只是"它做了这件事",看不到"这件事本来要问你,是你之前那个开关替你答的"。
- **`mode_set_by` 是一道授权闸门,而它的拒绝理由到不了人。** `autopilot.py:82` 明写
  「模式是**授权动作**,只对做出授权的那个人生效」(飞书群聊共用会话的场景)。于是 B 看到
  会话开着 auto,而他的每一次调用照样弹卡 —— 界面没有任何地方能告诉他"这是 A 开的"。

**为什么看不出来**。两处都不会报错:一个是"少显示了一行字",一个是"开关看着是开的但不生效"。
后者用户多半会归结为"这功能不稳定"。

**为什么是架构问题**。这是上一份审计 §2 那条规律的第三例:**"给模型的"和"给人的"被当成两件事**。
授权链路上每一个决策后端都记了,记得很讲究(`session-allow` 和档位分开留痕,注释写明理由),
而这条链的最后一环 —— 人回头查"刚才那一串操作是谁准的" —— 没接上。一个知情同意的机制,
只在"问"的那一刻可见,不在"已经发生"的时候可见,它就只是一个弹窗。

**建议**。
1. 时间线上被自动放行的工具行挂一枚小标(读 `decision_mode`),点开说明是哪一档、谁开的;
2. `SessionSettingsMenu` 里的档位开关,当 `mode_set_by !== me` 时显示"由 xxx 开启,对你不生效"而不是一个看着能用的开关;
3. 长期:往 `payload` / 工具结果里加信息时按上一份审计 §5.2 问一句"人在界面上从哪儿看到它"。

---

### 2.5 【中】`api/domains/*` 里 14 个手写接口,是生成类型的影子

**现象**。写脚本比对 `api/domains/*.ts` 里的 `export interface` 与 `api/generated/schema.d.ts`,
字段集合 100% 重合的有 14 个:

```
assets.ts        RemoteEntry ≈ RemoteEntryOut        UrlProbe ≈ UrlProbeResponse
boards.ts        Board ≈ BoardOut
collaboration.ts CollaborationActor ≈ ActorOut       ActivityEvent ≈ ActivityOut
                 CollaborationComment ≈ CommentOut   CollaborationReview ≈ ReviewOut
                 CollaborationCommentAnchor ≈ CanvasCommentAnchor
editor.ts        ExportParams ≈ ExportRequest        Lut ≈ LutOut        Font ≈ FontOut
generation.ts    PromptOptimizeResult ≈ PromptOptimizeResponse
speech.ts        TtsEngineChoice ≈ TtsEngineChoiceOut  TtsVoice ≈ TtsVoiceOut
```

同一份文件里另有 `Asset = components["schemas"]["AssetOut"]`、`Clip`、`Sequence`、`Track` 等
走生成类型的写法 —— **两种约定并存,而 `design/apiSeam.test.ts` 只管路径写在哪里,不管类型从哪来**。

`ExportParams`(`api/domains/editor.ts:295`)是最干净的例子:三个字段、枚举值、可空 fps,
和 `ExportRequest`(`backend/app/api/schemas/sequences.py:131`)一字不差。今天它是对的,
理由和 §3 第四处一样:**两个数碰巧相等**。

**为什么看不出来**。后端加一个导出选项(比如码率档),`openapi.json` 和 `schema.d.ts` 都会长出来,
而手写那份不会 —— 前端编译通过、测试全绿,只是那个选项在界面上**不存在**。反方向更糟:后端
改窄一个枚举,前端照旧能构造出旧值,变成一个 422。

**为什么是架构问题**。生成类型这条路的全部价值就是"接口一变,前端编译就知道"。只要还有第二条
手写的路,这个保证就退化成"看谁碰巧用了哪条"。而 14 个里已经有一个走散的邻居:`F5Model`
(`api/domains/speech.ts:133`,15 个字段)对着的是
`backend/app/api/routes/voices.py:161` 的 `def list_f5_models(...) -> list[dict]` —— **没有
`response_model`**,所以生成出来的类型是 `{[key: string]: unknown}[]`,压根没有可比的对象。
实测那 15 个字段此刻和 `f5_models.status()`(`backend/app/ai/runtime/f5_models.py:278`)完全一致,
但这份一致由两边的人手工维持,任何一侧改名都不会有人喊。全仓这样"返回裸 dict 且无
`response_model`"的路由有 54 条,其中被前端用手写接口接住的还有 `ComfyWorkflow` / `ComfyParam`
(`api/domains/generation.ts:22`、`:28`)—— 后者更悬,它的形状实际由**外部 ComfyUI 服务器**决定,
两侧都不拥有。

**建议**。
1. 加一道棘轮(和 `apiSeam.test.ts` 同形的"只减不增"):`api/domains/*` 里的 `export interface`
   如果同名/近名的 schema 存在,就必须改成 `components["schemas"][...]`;基线设成当前的 14,只减不增。
2. 给前端真正在用的那几条裸 dict 路由补 `response_model`(`list_f5_models`、
   `comfyui/workflows`、`comfyui/workflow-params`、`autopilot-rules`),补完前端那几个手写接口就能自动收口。

---

### 2.6 【中】「旗子在最上面」这条规则,两块画布各写了一个数,而两个数不一样

**现象**。画板和工作流是两块 React Flow 画布,共用 `features/markers/`(`MAX_MARKERS`、
`newMarkerId`、`nextMarkerName`、快捷键归一化,后者还有跨端契约 `contracts/marker-shortcut-cases.json`)。
但"标记怎么变成一个 React Flow 节点"这件事各写一遍:

| | 画板 | 工作流 |
| --- | --- | --- |
| id 前缀 | `BoardCanvas.tsx:100` `const MARKER_PREFIX = "marker:"` | `workflowCanvasModel.ts:55` `export const MARKER_PREFIX = "marker:"` |
| 建节点 | `toMarkerNodes()`(:102) | `toMarkerFlowNodes()`(:56) |
| 注释 | 「不带前缀的话,一个和画板项重名的标记会把它顶掉」 | 「不带前缀的话,一个和节点重名的标记会把它顶掉」 |
| 叠放 | `zIndex: 2` | `zIndex: 950` |
| 节点表 | `{ ...BOARD_NODE_TYPES, marker: MarkerPin }` | `{ ...WORKFLOW_NODE_TYPES, marker: MarkerPin }` |

两个前缀碰巧相等(§3 第四处的原文形状),两句注释是**同一句话被写了两遍**,而叠放的两个数
已经分岔 —— 不是因为谁错了,是因为"最上面"在两块画布里各自是一个凭手感挑的常数,没有任何
地方写下"旗子要压在所有内容之上"这条规则。实测全仓 `features/` + `components/` 里字面量
`zIndex: <数>` 只有这两处,它们就是那对不一致的数。

**为什么看不出来**。前缀分岔的表现是"标记读不回来了 / 和节点重名互相顶掉",叠放分岔的表现是
"某种节点会盖住旗子,点不到"。两者都不报错,而且只在特定内容下才出现。

**为什么是架构问题**。共享层就在旁边(`features/markers/markers.ts`),前缀和建节点没进去,
只是因为它们被当成"画布自己的事"。于是第三块画布(或者画板加一种新节点类型)就会重复整轮:
抄一个前缀、挑一个 z 值、把那句注释再写一遍。

**建议**。`features/markers/markers.ts` 里加 `MARKER_PREFIX`、`toMarkerNodes(markers, zIndex)`、
`markerNodeTypes(base)`;两块画布各自只传自己的 z 值,**并把那个 z 值和本画布其它层的 z 值
写在同一处**(现在画板的 0/1/2 写在注释里,工作流的 950 没有参照系)。配一条棘轮:
`features/` 下不许再出现字面量 `zIndex:`,要给就从一张表里取。

---

### 2.7 【中】关掉代理生成,预览永远停在「转码中」,还每 2 秒问一次

**现象**。预览只走 WebCodecs + 代理一条路(ADR-0004),画不出来时必须给一个说得清的状态
(`features/editor/playback/previewReadiness.ts` 开头写得很清楚)。判定是:

```ts
// previewReadiness.ts:28-40
if (asset.kind === "image") return "ready";
const status = proxyStatus(asset);            // media_info.proxy_status,缺省是 ""
if (status === "ready")  return undecodable.has(asset.id) ? "undecodable" : "ready";
if (status === "failed") return "failed";
return "transcoding";                          // "pending"、空、没见过的值都算还在转
```

而后端 `backend/app/domain/assets/proxies.py:56`:

```py
if not settings.generate_proxies or asset.kind != "video" or not asset.file_key:
    return None        # 不建任务,也不写 proxy_status
```

`generate_proxies` 默认 `True`,所以日常没事。一旦部署把它关掉(或素材没有 `file_key`),
视频素材的 `media_info` 里永远没有 `proxy_status` → 前端永远读到 `""` → 永远
`"transcoding"` → `Monitor.tsx:316-320` 那个"转码中就轮询素材"的 effect 永远不停,每 2 秒
一次 `onRefreshAssets()`。而遮罩上写的是「转码中,等一会儿就好」—— 一件永远不会发生的事。

(`asset.kind === "audio"` 这条路**不受影响**:`Monitor.tsx:284` 只把 video/image 交给判定。
这一处是对的,值得记一笔 —— 它正是"调用方只传当前播放头下真正要画的素材"那条约定在起作用。)

**为什么看不出来**。缺省值 `""` 落进了"未知一律当作还在转"那一档,而那一档的设计理由
(注释写了:把未知显示成错误会让用户去点一个其实不需要的重试)在这里刚好反过来 —— 用户
需要知道的恰恰是"这台后端根本不生成代理"。

**为什么是架构问题**。`generate_proxies` 是一个**后端才知道、前端无从得知**的开关,而前端的
整条预览路径建立在"代理总会有"这个前提上。遮罩上那个「重新生成代理」按钮
(`PreviewUnavailable.tsx:41`)打的 `/api/assets/{id}/proxy` 在这种配置下同样是空操作 ——
自救手段也失效。

**建议**。把 `generate_proxies` 纳入某个前端已经在拉的 capability/health 回包,
`assetPreviewState` 增加一档 `"proxies-disabled"`:文案说清"这台后端没有开启代理生成",
不给重试按钮,不轮询。判据是**前端不再用缺省值去猜后端的配置**。

---

### 2.8 【中】两份页面样式表在 `@layer` 外面 —— 而项目正为这件事立过棘轮

**现象**。

| 样式表 | `@layer` 数 | 写死的 `font-size: Npx` |
| --- | --- | --- |
| `features/editor/editor.css` | 1(整份包在 `@layer components`) | 0(全走 `var(--text-ui-*)`) |
| `app/styles.css` | 有 | 0 |
| **`features/scenes/scenes.css`** | **0** | **12**(10/11/11/12/12/13/13/13/14/16/22/9) |
| **`features/notes/notes.css`** | **0** | **3**(17/21/26) |

`design/unlayeredGlobals.test.ts` 开头写着这个项目**在同一个坑里栽过两次**:
`* { border-color }` 不分层 → 全项目 `border-*` 失效;`button,input { font: inherit }` 不分层 →
实测 60 组控件 class 里 40 组的字号字重**一句不算数**。结论是「不分层的 CSS 胜过任何分层 CSS,
和特异性无关」。而这道棘轮 `const CSS = fs.readFileSync(path.join(__dirname, "tokens.css"))`
—— **只读 `tokens.css` 一个文件**。

于是在 3D 场景页和笔记页里,凡是被这两份样式表选中的元素,TSX 上写的 Tailwind 工具类一律不算数。
具体一条:`scenes.css:134-136`

```css
.scene-studio button,
.scene-library button,
.scene-studio input { transition: background-color 160ms ease, ... }
```

这是一条不分层的、命中**整页所有按钮**(含 `components/ui/button` 渲染出来的)的规则;
紧接着 `:142` 的 `:focus-visible { outline: 2px solid var(--primary) }` 同样不分层,压过通用按钮
自己那套 `focus-visible:outline-*`。

同时 `lib/typeScale.test.ts` 的扫描器 `sourceFiles()` 只收 `.ts`/`.tsx`,正则只认 `text-\[([0-9.]+px)\]`
—— CSS 文件里的 `font-size: 13px` 它一个也看不见。`scenes.css` 里 40 处用了
`var(--text-ui-*)`、12 处写死像素,**两种做法在同一个文件里并存**,正是那道棘轮描述的
「8 种相近尺寸混着用 …… 那半个像素的差别不是设计决定」的复发。

**为什么看不出来**。两道棘轮都是绿的,因为它们扫不到这两个文件。而"工具类不算数"这件事
在页面里表现成"改了 class 没反应",人会以为是自己写错了选择器。

**为什么是架构问题**。这是上一份审计 §1.3 点名的那个形状:**一条在它该响的那次保持沉默的棘轮,
比没有更坏。** 两道规则都写对了,只是扫描范围停在了写它们那天碰过的文件上;而项目此后长出了
三份页面样式表,其中两份没被纳入。并且它和按需加载叠加:这两份样式表跟着各自的页面分块走,
所以"我的工具类算不算数"还取决于本次会话有没有进过那一页 —— 和 `vendorStyles.test.ts` 记的
React Flow 那次是同一种随机性。

**建议**。
1. `unlayeredGlobals.test.ts` 的扫描面从 `tokens.css` 扩到**所有 `src/**/*.css`**,断言"每条规则都在某个 `@layer` 里";把 `scenes.css` / `notes.css` 整份包进 `@layer components`(editor.css 已经是这样,照抄即可)。
2. `typeScale.test.ts` 同时扫 `.css` 的 `font-size: <n>px`,`ALLOWED` 那张白名单两边共用 —— 例外要看得见,不能分 TSX 一份、CSS 一份。

---

### 2.9 【中低】`--scene-row-bleed` 收敛了一次,又被三个字面量兜回去

**现象**。上一份审计 §3 第四处把"整行底色比文字宽出多少"收敛成
`scenes.css:653` 的 `--scene-row-bleed: 8px`。但它的三个使用点全都带着**字面量兜底**:

```
653:  --scene-row-bleed: 8px;                                  ← 唯一定义
671:  --row-bleed: var(--scene-row-bleed, 8px);
831:  padding: 8px var(--scene-row-bleed, 8px);
832:  margin-inline: calc(var(--scene-row-bleed, 8px) * -1);
```

也就是说这个 8 仍然写了**四遍**。实测这三处今天都落在 `.scene-panel-body` 里
(`ScenePanel.tsx:18` → `SceneCameraPanel.tsx:64` / `SceneStudio.tsx:1528`),兜底取不到,
所以现在是对的 —— 又一次"两个数碰巧相等"。

钉它的那条测试 `features/scenes/objectTree.test.ts:161-163` 断言的是**引用存在**
(`toContain("var(--scene-row-bleed")`),不是**字面量不存在**。

**为什么看不出来**。把 653 改成 10px,今天所有用点都会跟着变(因为都在面板里),看着完全正确;
直到某天有人把行列表搬到面板外(浮层里的列表、dope sheet 里的行),那一处**静默回到 8px**。

**为什么是架构问题**。兜底值就是第二处定义。§3 的判据是「加第四个元素时还用不用改别处」——
现在的答案是"不用改,但可能悄悄不一样"。

**建议**。把 `--scene-row-bleed` 提到 `.scene-library, .scene-studio`(页面根,和
`--scene-side-gutter` 同一处),三处去掉 `, 8px`;`objectTree.test.ts` 改成断言这三条规则里
**不含**裸 `8px`。

---

### 2.10 【中低】`selectedClipId` 与 `selectedClipIds` 是同一件事的两份

**现象**。`stores/editorStore.ts:50-51` 同时存了单选 id 和多选 id 列表。三个写入口
(`:107` `selectClip`、`:113` `toggleSelectClip`、`:115` `selectClips`)每一个都手工把两者
写成一致 —— 恒等式是 `selectedClipId === selectedClipIds.at(-1) ?? null`。消费侧:
`selectedClipId` 6 处、`selectedClipIds` 23 处。

**为什么看不出来**。三个写入口今天都写对了,所以两者永远一致。`useEditorStore.setState` 在
非测试代码里零命中,所以目前也绕不过这三个口。

**为什么是架构问题**。一个派生值被当成独立状态存了下来,一致性由"每个写入口都记得"维持。
第四个写入口(比如"选中某轨全部片段"、"撤销后恢复选区")只要漏一个,两个读者就会看到不同的
选中态 —— 而那表现成"属性面板显示的是另一个片段",没有任何东西报错。

**建议**。`selectedClipId` 改成选择器(`const selectedClipId = (s) => s.selectedClipIds.at(-1) ?? null`),
store 里只留列表。改完那三个写入口各少一行,这就是"改对了"的标志。

---

### 2.11 【低】`api/client.ts` 这个桶少了两块,而校验它的测试是手写清单

**现象**。`api/domains/` 下 18 个模块,`api/client.ts` 再导出 16 个 —— **`notes.ts` 和
`scenes.ts` 不在里面**,它们只能直接 import(实测:`@/api/domains/scenes` 22 处、
`@/api/domains/notes` 18 处)。而 `boards` / `assets` / `collaboration` 是**两条路都有**
(桶里有,也被直接 import 了 5 / 3 / 2 处)。

校验这个桶的 `api/clientAssembly.test.ts` 是一份**手抄的清单**:15 个 `import * as`,
`collaboration` 和 `plugins` 在 `client.ts` 里但不在测试里。新增一个 domain 忘了加进桶、
或加进桶忘了加进测试,都不会红。

**为什么是架构问题**。两种 import 约定并存,没有一句话说清哪种是对的;新来的人抄哪一处都"对"。

**建议**。要么桶收全(把 notes / scenes 加进去),要么废掉桶只留直接 import ——
后者其实更合当前趋势(scenes/notes 的用法)。无论哪种,`clientAssembly.test.ts` 改成
**读目录**而不是手抄清单:`readdirSync("api/domains")` 逐个断言,这样它才扫得到"新加的那一个"。

---

### 2.12 【低】`contracts/shared-constants.json` 的校验只跑在后端

**现象**。这份契约钉的 56px 在四处实现,**两处是前端文件**
(`frontend/src/app/App.tsx:113` `PUBLISH_BAR_HEIGHT`、`frontend/src/lib/windowChrome.ts:2`
`WINDOW_CHROME_HEIGHT`)。实测四处都是 56,链条成立。但跑它的是
`backend/tests/test_shared_constants_parity.py`(用正则去读那两个 TS 文件)。

前端有 8 份 `*.parity.test.ts`,唯独这一份没有前端侧的跑手。一次只改前端的提交,
按仓库习惯跑的是 `pnpm lint` 和前端 vitest —— 这条契约不会被触发。

**建议**。在 `frontend/src/lib/` 加一份薄的 `sharedConstants.parity.test.ts`,读同一个 json,
断言 `PUBLISH_BAR_HEIGHT` 和 `WINDOW_CHROME_HEIGHT` 等于契约值。成本几行,补的是
"改这个文件的人会跑到的那个套件"。

---

### 2.13 【低】`featureBoundaries` 只拦二元环

**现象**。`features/featureBoundaries.test.ts:57` 的判据是
`if (edges.get(other)?.has(feature) && feature < other)` —— 只检测 A↔B。三环及以上通过。

实测当前依赖图(9 条边)**无环**,所以它今天没有漏报:

```
agent → media, notes
ai-studio → agent, notes, voice
boards → agent, ai-studio, collaboration, markers, media, notes, scenes, voice
browser-pool → publish
editor → agent, media, notes, voice
home → media
scenes → agent
settings → agent, voice
workflows → agent, collaboration, markers, notes
```

**为什么仍值得记**。测试的第二条 case 叫「这道棘轮扫得到东西 —— 别变成空转」,说明作者
在意的正是"它在该响的时候会不会响"。二元判据在 A→B→C→A 时保持沉默,而那种环恰恰更难
靠读代码发现。顺带:`agent` 被 6 个功能依赖,它事实上已经是一层公共基建而不是一个平级功能
(`ai-studio` 从它那里拿走 20+ 个模块)。

**建议**。判据换成图上找环(DFS,任意长度),报出整条路径;顺便考虑把 `features/agent/`
里真正通用的那部分(`agentRow`、`ToolCalls`、`ChatComposer`、`stickToBottom`)提到
`components/` 或一个 `features/agent-kit/`,让"谁是底座"在目录结构上说得清。

---

## 3. 没有发现问题的地方(也是结论)

沿链条走过、确认处处成立的:

- **React Query 的键。** 写脚本抽出全仓 `queryKey: [...]` 字面量,按首段分成 67 个家族,
  逐族比对"最短取数键"与"最长失效键":**没有一族的失效键比取数键长**。
  `api/queryKeys.ts` + 棘轮把素材那族收住了,其余家族恰好都是单段/双段的同形键。
- **笔记引用的新鲜度。** `noteReferenceQuery`(`api/domains/notes.ts:33`)的键里带
  `note_revision` —— 内容寻址,所以"从不失效"是对的而不是漏了;
  `BoardCanvas.tsx:441-450` 的手动刷新改的是 `note_revision`,换键即换内容,链条闭合。
- **画板的 `node.data` 取值。** React Flow 的 `data` 是无类型袋,取 `item` 的地方有 11 处,
  逐处核过:要么先按 id 过滤、要么 `node.type !== "marker"`、要么走
  `boardItems()`(`BoardCanvas.tsx:172`,注释记着它因为"加一枚标记整张画板就打不开了"而收口)。
  没有一处会真的读到 `undefined.kind`。(残留风险见 §2.6 的建议:类型上没有判别联合,靠 11 处人工守卫。)
- **功能模块依赖图无环**(任意长度,实测,见 §2.13)。
- **音频素材不会被预览遮罩挡住。** `Monitor.tsx:284` 只把 video/image 交给判定,
  和 `previewReadiness.ts:49` 那条"只传当前播放头下真正要画的素材"的约定一致。
- **按需加载的 JS 侧副作用。** 实测 `features/` `components/` `lib/` `design/` `stores/` 下
  **没有一处模块级裸调用**(`installWindowChrome()` 只在 `app/main.tsx` 入口);
  `@xyflow/react/dist/style.css` 在入口且只在入口(`vendorStyles.test.ts` 在管);
  `react-photo-view` 的样式表跟着 `components/app/image-preview`,而它被 `App.tsx:53` 静态
  import 进外壳,不随任何一页走。CSS 的**分层**这一环是断的,见 §2.8。
- **契约语料。** 11 份,前端侧 8 份有 `*.parity.test.ts` / 直接读语料的测试
  (marker-shortcut、scene-3d、scene、subtitle、transform、clip-appearance、
  free-element-geometry、workflow-field-activation);context-meter 在 agent-sidecar,
  shared-constants 由后端反向读前端源码(§2.12 只是位置问题,不是缺失)。
- **导出参数链路。** 前端 `ExportParams` 与后端 `ExportRequest` 字段、枚举、可空性逐项一致
  (类型来源的隐患见 §2.5,值本身没问题)。
- **`design/` 的 14 道棘轮本身**都能扫到东西、都带着"因为什么事故而立"的说明;
  问题只出在其中两道的**扫描面**(§2.8),不在判据。

---

## 4. 给下一次的建议

1. **棘轮要连同"扫哪些文件"一起复核。** 本次两处漏洞都不是判据错了,是范围停在写它那天。
   凡是 `readFileSync(<某个具体文件>)` 或 `/\.(ts|tsx)$/` 的棘轮,值得问一句:
   这条规则管的那类东西,今天还只住在这些文件里吗。
2. **手写的接口类型要按"影子"看待。** §2.5 的 14 个今天全对,而"全对"正是它们活下来的原因。
   判据不是对不对,是**后端改了它会不会自己变**。
3. **"两块画布 / 两个聊天面板"这种并列结构,要主动去找它们各写一遍的那几样。**
   §2.3 和 §2.6 都是这么找到的:先列出两边共享了什么,剩下没共享的就是候选。

---

## 附:本次涉及的关键文件

**前端 · 共享层**
- `frontend/src/api/client.ts`、`frontend/src/api/transport.ts`、`frontend/src/api/queryKeys.ts`
- `frontend/src/api/domains/editor.ts`(`ExportParams`:295)、`speech.ts`(`F5Model`:133)、`generation.ts`(`ComfyWorkflow`:22)、`notes.ts`(`noteReferenceQuery`:33)
- `frontend/src/api/generated/schema.d.ts`(`linked_clip_id`:7381)
- `frontend/src/stores/editorStore.ts`(选中态两份:50-51、107-115)
- `frontend/src/design/tokens.css`、`unlayeredGlobals.test.ts`、`vendorStyles.test.ts`、`apiSeam.test.ts`、`agentTypeScale.test.ts`、`layering.test.ts`
- `frontend/src/lib/typeScale.test.ts`、`frontend/src/lib/windowChrome.ts`
- `frontend/src/app/main.tsx`、`App.tsx`(`PUBLISH_BAR_HEIGHT`:113)、`pageChunks.test.ts`
- `frontend/src/features/featureBoundaries.test.ts`

**前端 · 剪辑台**
- `frontend/src/features/editor/playback/previewReadiness.ts`、`PreviewUnavailable.tsx`
- `frontend/src/features/editor/Monitor.tsx`(:284、:294-320)
- `frontend/src/features/editor/timeline/Timeline.tsx`、`frontend/src/features/editor/editor.css`

**前端 · 两块画布**
- `frontend/src/features/boards/BoardCanvas.tsx`(`MARKER_PREFIX`:100、`toMarkerNodes`:102、`boardItems`:172)
- `frontend/src/features/workflows/workflowCanvasModel.ts`(`MARKER_PREFIX`:55、`toMarkerFlowNodes`:56)
- `frontend/src/features/boards/canvasHistory.ts` 与 `frontend/src/stores/workflowGraphStore.ts`(两套撤销)
- `frontend/src/features/markers/markers.ts`

**前端 · 智能体两个入口**
- `frontend/src/features/ai-studio/ChatWorkspace.tsx`(:142-171)
- `frontend/src/features/agent/CanvasAgentChat.tsx`(:334-356)
- `frontend/src/features/agent/InlineConfirmations.tsx`(:59)、`ConfirmationCenter.tsx`(:25)
- `frontend/src/features/agent/agentRow.ts`、`ToolCalls.tsx`

**前端 · 场景 / 笔记 / 统计**
- `frontend/src/features/scenes/scenes.css`(:653、:671、:831-832、:134-146)、`objectTree.test.ts`
- `frontend/src/features/notes/notes.css`
- `frontend/src/features/statistics/StatisticsView.tsx`
- `frontend/src/features/workflows/WorkflowRevisionHistory.tsx`

**后端(只作为另一侧的事实)**
- `backend/app/db/model_slices/sequences.py:74`、`backend/app/api/schemas/sequences.py:36`、`backend/app/domain/sequences/operations.py:835,1556`
- `backend/app/api/schemas/dashboard.py:73-110`
- `backend/app/api/schemas/agent.py:148,236-252`、`backend/app/domain/agent/autopilot.py:70-96`、`backend/app/api/routes/agent.py:296-317`
- `backend/app/domain/assets/proxies.py:25-72`、`backend/app/core/config.py:92`
- `backend/app/api/routes/voices.py:160-184`、`backend/app/ai/runtime/f5_models.py:278`
- `contracts/shared-constants.json`、`backend/tests/test_shared_constants_parity.py`

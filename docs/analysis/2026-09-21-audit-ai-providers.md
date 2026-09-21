# 只读架构审计:AI 供应商三层、生成契约、本机运行时

> 日期:2026-09-21 · 基准:`main` @ `e58190f2`,工作区干净 · 方法与
> [`2026-09-21-chain-audit.md`](2026-09-21-chain-audit.md) 相同:**沿链条走**,凡结论都给
> `文件:行号`。本次**没有改动任何代码**,只写了这一份报告。
>
> 范围:`backend/app/ai/`(供应商三层、适配器、生成契约、本机运行时)+
> `domain/provider*.py`、`domain/model_limits.py`、`domain/structured_output.py`、
> `domain/thinking.py`、`domain/ai_chat.py`、`domain/generation/`、`domain/usage.py`
> 里与之直接相邻的部分。不含工作流引擎本体、剪辑内核、智能体宿主、前端、Electron。

---

## 0. 结论先写

链条审计那份的判断在这块领域同样成立,而且更尖锐:

**这一层的纪律是真的在执行**(契约、棘轮、ADR-0019、PROCESS_STATE 都落到了代码里),
**而本次找到的六条问题里有五条是同一个形状** —— 一份值在链条的 N-1 环都在,最后一环没接上,
两边都不报错。

但这一次多出了一个**新的形状**,而且比链条断裂更难发现:

> **同一条语义有两条执行通道(直连 HTTP / pi sidecar),而新做的那几张「查证过的事实」表
> 只接到了其中一条上。**

`model_limits`、`thinking`、`structured_output` 三张表今天刚加,它们都只流到
`provider_runtime.sidecar_provider()` → pi 这一侧。而 `domain/ai_chat.chat()` 这条直连路上
挂着**八个调用点**(翻译、素材分析、工作流 LLM 节点、工作流 AI 编排、发布文案、提示词优化、
画板写作、放行判断),它们一个都读不到。设置页上那个「实际会用的输出额度」在这八条路上是
**一句不成立的话**。

这不是"忘了接",而是**两条通道从来没有被要求对齐过** —— 没有任何棘轮问「同一个模型设置,
在两条执行通道上是不是同一份参数」。链条审计 §5 建议的「把链条末端当成一等检查项」,
在这里要升级成「**把第二条通道当成一等检查项**」。

---

## 1. 关键链条逐条结论

### 1.1 一次生成请求的完整链条

分两条通道走,**两条的结论不一样**。

#### (A) 直连 HTTP(`ai_chat.chat`)—— 八个调用点

| 环 | 在哪 | 成立? |
| --- | --- | --- |
| 界面/节点选了模型 | `workflows/executors/ai.py:341`、各调用点 | ✅ |
| 解析成连接 + 模型 | `ai_chat.target_for:73`,`provider_models.model_id_for:234` | ✅ 解析不出当场报错,不发空 model |
| 上下文窗口 | —— | ❌ **这条路根本不查**。`model_limits.resolve` 在这条链上一次都没被调用 |
| 最大输出 | `executors/ai.py:223` 只读节点上的 `max_tokens` | ❌ 模型行上的「最大输出 Token」到不了 |
| 思考档位 | —— | ❌ `reasoning_effort` / `thinking_level_map` 只发得进 sidecar |
| `response_format` | `executors/ai.py:236`,`ai_chat.chat:163-180` | ✅ 拼得对 |
| 发给适配器 | `ai_chat.chat:191-201` | ✅ 统一重试、脱敏、空密钥处理 |
| 回包翻成领域对象 | `ai_chat.chat:214-226`,`executors/ai.py:287` | ✅ |
| 计费 | `usage.billable:644` | ⚠️ 八个调用点里 **judge 那一个没有记账**(见 §2.3) |

**断点是「上下文窗口 / 最大输出 / 思考档位」那三行。**详见 §2.1。

#### (B) pi sidecar(智能体轮次 + OAuth 网关补全)

| 环 | 在哪 | 成立? |
| --- | --- | --- |
| 解析成连接 + 模型 | `agent/host.py:100-125` | ✅ 不再"替他挑第一个",理由写在注释里 |
| 上限合并 | `provider_runtime.py:34-45` → `model_limits.resolve:239` | ✅ **唯一的合并处**,override → catalog → builtin → fallback |
| 思考档位 | `provider_models.runtime_limits:195-199` → `sidecar/adapters.py:348` | ✅ |
| `response_format` | `ai_chat._chat_gateway:300-314` 塞进 `samplingParams` | ⚠️ 塞进去了,但**降级链在这条路上整个不存在**(见 §2.2) |
| 多轮消息 | `ai_chat._gateway_prompt:246-282` | ❌ 角色结构被压平成一段带【用户】【助手】标签的文本;超过 8 张或 8MB 的图**静默丢弃** |
| 回包 → 领域对象 | `_chat_gateway:337-345` | ✅ |
| 计费 | `_chat_gateway:337-344` | ⚠️ `call.describe` 在**成功之后**才调(直连那条在发请求**之前**,`chat:194`)——
网关调用失败时那条账没有供应商和模型名 |

**结论:链条 (B) 的上限那一段是成立的;链条 (A) 的同一段断了。**

### 1.2 「查证过的事实」与「猜的」有没有混在一起

三张表自己都守规矩:

- `structured_output.known_support:48` —— 查不到返回 `None`,中转刻意不写,理由在模块头。
- `thinking.profile_for:158` —— 查不到走 `UNKNOWN`,`qwen` / `GLM` **明写为什么不在表里**
  (发不出去的档位不声明),这是我见过最诚实的一种"不知道"。
- `model_limits.known_limits:163` —— 最长前缀赢,一律向下取整,拿不准不写。

消费点上**有一处把 None 当成了 False**:

`model_limits.resolve:280-286` 用
`any(mapped is not None for mapped in profile.level_map.values())` 当作「这是不是思考模型」。
那个判据回答的是「**我们发不发得出思考档位**」,而 `output_budget` 要问的是
「**这个模型会不会把输出额度烧在思考上**」—— 两个不同的问题。详见 §2.4。

其余消费点都对:
`_honour_structured_output:249` 写的是 `if supported is not False: return payload`
(而不是 `if not supported`),`runtime_limits:193` 只带显式设过的键,
`cached_models:132` 的文档明写 `None` 和 `[]` 是两回事。

### 1.3 失败与降级有没有被记录下来

**没有。一处都没有。** 降级链共有三档触发点,三处都是纯静默:

| 触发点 | 位置 | 记了什么 |
| --- | --- | --- |
| 已知不支持 → 预先降到 `json_object` | `executors/ai.py:238-253` | 什么都没记 |
| 400 说不支持 → 降一档重发 | `ai_chat.py:205-213` | 什么都没记 |
| 200 但 content 为空 → 再降一档 | `ai_chat.py:221-225` | 什么都没记 |

`ai_chat.py:44` 有一个 `logger`,**全文件一次都没用过**。节点的
`outputs` 是 `["text", "json"]`(`workflows/__init__.py:451`),没有第三项。
`_json_result` 写进 `details` 的 `response_format` 取的是 `config.get(...)`
(`executors/ai.py:290`)—— 那是**配置的那一档,不是实际跑的那一档**。详见 §2.2。

### 1.4 付费动作的边界(ADR-0019 / `billable`)

**这一条是本次审计里质量最高的部分。**

- 回执一出现就落库:`contracts/generation.py:368-372`,经 contextvar 传,不经过适配器 —— 理由
  (「让每家都记得去报,等于让每家都有机会忘记」)写在 `RemoteTaskWatch:311` 上。
- 轮询上限 6 小时,明写「只防供应商永远不回话,不是我们等烦了」:`generation.py:434`。
- 超时消息带上远端任务号:`generation.py:383`。
- 重启接着取而不是判失败:`runner.py:73-92` + `register_resumer`(`runner.py:372`)。
- 棘轮:`tests/test_paid_generations_are_never_abandoned.py:91` 逐条盯着
  「调了 `poll_until_ready` 就必须 resumable」。七家异步适配器全部 `supports_resume = True`。
- 取消、超时、异常三条路都记账:`runner.py:210-219`,幂等键是
  `generation:{id}:{status}`(`runner.py:355`)—— **稳定键**,重放不会重复入账。
- 智能体轮次同样:成功/失败/崩溃三条路各记一条,幂等键是 `agent-message:{id}`
  (`agent/host.py:596`、`652`、`682`),失败轮次显式 `mark_failed()`。

**两处边界没守住**:放行判断这条路完全不记账(§2.3),`billable` 的兜底幂等键把时间戳编进
了键里(§2.6)。

### 1.5 兼容分支

**没有找到一处。** 全范围搜 `兼容 / legacy / backward / deprecat / 老版本`,命中的全是:

- OpenAI **兼容端点**(专有名词,不是版本兼容);
- 一次性迁移:`runtime/config.py:115-142`、`runtime/asr_models.py:135-157`
  (两处都明写「**不留作兼容候选**」并说明为什么);
- `db/migrations.py:2099` 的 `_migrate_model_structured_output` —— 加列迁移,不是读时分支;
- `contracts/generation.py:422` 的「兼容别名」指的是 `video_url` 这类 **URL 参数别名**,
  而且收敛在 `ROLE_URL_PARAMETERS:389` 一张表里,不是历史版本分支。

仓库规矩在这一层是成立的。

### 1.6 托管 venv / 工作进程池 vs「后端是单进程」

**这一条也是成立的,而且有棘轮。**

`docs/PROCESS_STATE.md` 把每一处模块级可变状态按「多进程就是错的 / 功能不在 / 启动装配 /
纯缓存 / 导入期注册表」五类交代清楚,由
`tests/test_process_state_inventory.py`(AST 静态扫描)钉住。本范围内的
`model_catalog._cache`、`remote_size._cache`、各 `_probes` / `_store`、
`tts_daemon._POOL` / `asr_daemon._POOL`、`sidecar/adapters._LIVE` 全部在册且归类正确。

生命周期本身也是撞出来的、写下来的:
- 回收判据是「**闲着**」而不是「上次用完过了多久」(`worker_pool.py:67-70`,首次加载权重
  511 秒比闲置超时还长);
- `stderr` 必须一直排空,否则子进程卡在 `write` 上(`worker_pool.py:86-104`);
- 超时靠**杀进程**兑现而不是循环里检查(`worker_pool.py:133-139`);
- 串行化的锁放在 worker 自己身上而不是交给 N 个调用方(`worker_pool.py:34-43`)——
  这条的理由("一个不变量交给 N 个调用方各自记得,迟早有一个不记得")正是本文 §0 那条规律。
- 一个引擎一个 venv,理由是 fish 钉 torch 2.8 而 f5 要 2.13(`runtime/config.py:48-53`)。

**一处窄的崩溃恢复缺口**见 §2.5。

---

## 2. 问题清单(按严重度排序)

### 2.1 🔴 模型设置里的上限与思考档位,在直连那条通道上一个字节都发不出去

**现象**
用户在「模型设置」里填「最大输出 Token = 384000」「上下文窗口 = 1000000」,或勾上
「推理模型」、选了 `reasoning_effort` —— 这些值只进两个地方:
`provider_runtime.sidecar_provider:46` 拼给 pi 的那份 payload,和设置页自己回显的那几行
(`api/routes/settings/provider_models.py:82-105`)。

而 `domain/ai_chat.chat()` 这条直连 HTTP 通道从头到尾**没有 import 过 `model_limits`**。
全文件唯一出现 `max_tokens` 的地方是 `ai_chat.py:303`、`310-312`,两处都只是把**调用方已经
放进 payload 的值**转给网关。真正往 payload 里写 `max_tokens` 的只有一处:
`workflows/executors/ai.py:223-225`,取的是**工作流节点上那一格**,不是模型行。

受影响的调用点(八个,全部走直连或自动化直连):
`translate.py:109`、`analysis/service.py:209`、`workflows/executors/ai.py:377`、
`workflows/ai_edit.py:104`、`publish/copy.py:96`、`generation/prompt_optimizer.py:148`、
`boards/actions.py:241`、`agent/judge.py:106`。

**为什么看不出来**
设置页显示的 `effective_max_output_tokens` 来自
`model_limits.Resolved`(`model_limits.py:236`),而那个 dataclass 的文档字符串写着
「`effective_*` 是**运行时真正会用的数**」(`model_limits.py:233`)。这句话在智能体那条路上
是真的,在这八条路上是假的 —— **而界面上两者长得一模一样**。不填 `max_tokens` 时供应商用
自己的默认值,通常能跑出结果,只是结果比用户要求的短;`model_limits` 模块头记录的那个真实
故障(deepseek-v4-flash 按 16,384 发、"一轮思考还没说完就报已用完输出额度")在这八条路上
**根本没被修过**,只是从"发错的数"变成了"不发"。

**为什么是架构问题而不是一个 TODO**
`model_limits.resolve` 的文档写着「**唯一的合并处**」(`model_limits.py:249`),这句话成立 ——
问题不是有第二处合并,而是**有一条通道根本不经过它**。`provider_runtime.py` 的模块头说
「Agent turns and tool-free Gateway completions share this exact runtime description.
Keeping it in one Module prevents ... from drifting between the two execution surfaces」——
它把「两条执行通道」定义成了 agent 和 gateway,而真正的第三条(直连 HTTP)不在它的视野里。
`RUNTIME_FIELDS`(`provider_models.py:27-37`)声明了七个「可被用户覆盖的运行时参数」,其中
**五个**(`context_window`、`max_output_tokens`、`reasoning`、`reasoning_effort`、
`developer_role`)在直连通道上没有任何消费点。一个声明了却只有一半消费者的枚举,是这种
断链最典型的温床。

**建议修法**
1. 把 `ChatTarget`(`ai_chat.py:54`)补上 `context_window` / `max_output_tokens`
   两个字段,在 `target_for` 里调同一个 `model_limits.resolve`(它已经是纯函数,
   只要 `base_url` / `vendor` / `model_id` 与两个 override)。`chat()` 在
   `payload.setdefault("max_tokens", target.max_output_tokens)` —— **`setdefault`**,
   让节点上那格继续优先。
2. 上棘轮,形状抄 `test_executor_outputs_are_declared.py`:
   **`RUNTIME_FIELDS` 里的每一个键,要么在两条通道上都有消费点,要么在一张
   `SIDECAR_ONLY` 表里写明为什么**(`developer_role` 确实只有 pi 用得上,那就写下来)。
   这条棘轮问的是「第二条通道接上了吗」,正是链条审计 §5 建议的下一条。

---

### 2.2 🔴 降级是静默的:三处触发点,零处记录

**现象**
一次 LLM 节点调用可能实际跑在三档中的任意一档,而用户和模型都看不出是哪一档:

- `executors/ai.py:238-253` `_honour_structured_output`:已查证不支持时**预先**降到
  `json_object`。返回的是改过的 payload,没有第二个返回值。
- `ai_chat.py:205-213`:400 且能识别为能力错误时降一档,`continue` 重发。
- `ai_chat.py:221-225`:200 但 `content` 为空时再降一档,`continue` 重发。

三处都没有 `logger` 调用(`ai_chat.py:44` 的 logger 全文件零引用)、没有回传、没有进节点
输出、没有进 `ProviderUsageEvent.raw_usage`。节点的输出声明是
`["text", "json"]`(`workflows/__init__.py:451`),而落进失败详情的那个 `response_format`
取自 `config`(`executors/ai.py:290`)—— 是**配置的那一档**。

**为什么看不出来**
降级成功的时候一切正常:JSON 解析得出来、Schema 本地校验也过了
(`executors/ai.py:302-317`),节点绿着跑完。只有当模型在没有硬约束的情况下答歪了,用户才
会看到一句 `$.shots[8].duration_seconds 不符合 Schema` —— 而他节点上明明写着
`json_schema` + strict,于是他会以为是模型笨,而不是"那份图纸从来没被强制执行过"。
`structured_output` 模块头记的两次真实失败(字段越界、JSON 没闭合)就是这个。

**为什么是架构问题**
「给模型的」和「给人的」是同一件事的两个读者 —— 链条审计 §5 第 2 条刚写过。这里连
「给模型的」那一半都只做了一部分:`_downgrade_response_format_payload:407` 会把 Schema 正文
贴进提示词(做得很好),但**没人告诉调用方这件事发生过**,于是本地那次 Schema 校验
(`_json_result:303`)在"本来就没有硬约束"和"有硬约束却违反了"这两种完全不同的情况下
报的是同一句话。诊断信息在这一环被抹平了。

顺带:`_chat_gateway` 这条路**整个没有降级链**。`chat():181` 在任何 fallback 逻辑之前就
`return _chat_gateway(...)`,而且没有把 `allow_response_format_fallback` 传下去
(`ai_chat.py:182-190`)。后果:同一个工作流 LLM 节点,连的是 API Key 连接就会优雅降级,
连的是订阅授权(OAuth → `surface="automation"` → gateway)就是一个硬 400。
**同一个节点、同一份配置、两种行为**,而界面上这两种连接长得一样。

**建议修法**
1. `chat()` 改成返回 `(text, ChatOutcome)`,或者让调用方传一个
   `on_downgrade(from_tier, to_tier, reason)` 回调(后者改动面更小)。
2. LLM 节点把实际档位作为**声明过的输出**接出去(`response_format_used`),
   `test_executor_outputs_are_declared.py` 会强制它同时出现在 `NODE_TYPES` 里 ——
   那条棘轮已经在了,直接受益。
3. 记进 `ProviderUsageEvent.raw_usage`:降级这件事有成本(多一个往返),账上该看得见。
4. 网关那条路要么接上同一条降级链,要么在
   `_chat_gateway` 里**显式拒绝** `allow_response_format_fallback=True` 并说明 ——
   静默忽略一个"我已经允许你降级"的承诺是最坏的一种。

---

### 2.3 🟠 放行判断每次都真花钱,而账上一条都没有

**现象**
`agent/judge.ask:88` 是自动驾驶模式下「规则既没允许也没拒绝」时的那一次模型调用
(`autopilot.py:158-165` 起线程调它)。它走的是完整的付费对话:

```python
raw = chat(target, request.as_messages(), temperature=0.0,
           timeout=JUDGE_TIMEOUT_SECONDS, json_object=True, label="放行判断")
```
`backend/app/domain/agent/judge.py:106-113`

**没有 `call=` 参数,外面也没有 `billable(...)` 块** —— 这是全仓八个 `chat()` 调用点里
唯一一个。

**为什么看不出来**
判断跑在后台线程上,它的产物是一张确认卡的放行/拦截,用户感知不到"刚才打了一次模型"。
而 `billable` 那条「归属不了就 warning」的保护(`usage.py:695-697`)在这里也不会响 ——
**压根没进那个上下文管理器**。首页的 Token 图和成本统计缺的这部分,不会以任何形式提示。

**为什么是架构问题**
`ai_chat` 的模块头把「用量:一条都不记」列为它当初存在的四个理由之一
(`ai_chat.py:14-15`),而 judge 是在那之后新加的调用点,**原样复现了被消灭的那个毛病**。
根因是 `chat()` 的 `call` 参数是**可选**的:一个默认不记账的付费接口,靠每个调用点记得传,
就是 §1.6 里那条「一个不变量交给 N 个调用方各自记得」的同一个形状 —— 而那条在
`worker_pool` 里已经被正确地解决过一次(锁放在 worker 自己身上)。

顺带一条同形的:网关路径的 `call.describe` 在**成功之后**才调(`ai_chat.py:339`),
直连路径在**发请求之前**(`ai_chat.py:194`)。所以网关调用失败时那条账没有
provider / model,会落进 `UsageSummary.unpriced`(`usage.py:46-49`)里那堆"没能定价"的
记录 —— 而那一栏存在的意义恰恰是告诉用户"你少配了哪条价格规则",现在它会混进
根本不该在那儿的行。

**建议修法**
1. 给 judge 包一层 `billable(capability="chat", operation="agent_judge", ...)`,
   归属取确认卡所在会话的 workspace。
2. **把 `call` 变成必需的**,或者在 `chat()` 里 `if call is None: logger.warning(...)`。
   更彻底的做法是让 `chat()` 自己开 `billable`(调用方只传归属),这样"新加一个调用点"
   这件事不再有忘记记账的选项。
3. 网关路径的 `describe` 提到调用之前,和直连对齐。

---

### 2.4 🟠 「发不出思考档位」被当成了「这个模型不思考」

**现象**
`model_limits.resolve:280-286`:

```python
profile = thinking.profile_for(vendor, model_id)
effective_output = output_budget(..., thinking=any(mapped is not None for mapped in profile.level_map.values()))
```

`thinking.profile_for` 的语义写得很明确:查不到返回 `UNKNOWN`,而
`UNKNOWN.level_map` 是全 `None`(`thinking.py:73`)。所以任何一个**我们没查证过思考格式**的
模型,在这里都会被当成 `thinking=False`,拿到 `FALLBACK_MAX_OUTPUT_TOKENS = 4096`
(`model_limits.py:202-204`),而不是推理模型那档 32,768。

同时,模型行上用户可以显式勾的 `reasoning` 布尔
(`provider_models.RUNTIME_FIELDS:31`、`sidecar/adapters.py:344`)**没有被传进
`model_limits.resolve`** —— 它的签名里根本没有这个参数(`model_limits.py:239-247`)。

实际受影响的是「上限表里查不到输出额度 **且** 思考格式也没查证过」的交集:中转/本地端点上
挂的推理模型(Ollama 上的 `deepseek-r1` 蒸馏版、`qwq`、自定义名的推理模型)。用户勾了
「推理模型」,窗口也认出来了,**输出额度还是 4096**。

**为什么看不出来**
`thinking.py` 的注释把它自己的判据说得非常清楚(「查不到的模型走 UNKNOWN:不声明任何档位,
界面据此说'这条连接发不出思考档位'」),而 `model_limits.py:280` 那行注释写的是
「和 `provider_models.runtime_limits` 同一条判据:**有一档能发得出去,才算思考模型**」——
它诚实地记录了自己在复用哪条判据,**但那条判据回答的是另一个问题**。
`runtime_limits` 问的是「我发不发 `thinkingLevelMap`」(发不出去就别声明,对的);
`output_budget` 问的是「输出额度会不会被思考吃掉」。两个问题的答案在 qwen / GLM /
未知推理模型上是相反的 —— 而 `thinking.py:158` 的文档**明写**了 qwen 和 GLM 不在表里
"不是漏了",是因为发不出去。发不出去 ≠ 不思考。

**为什么是架构问题**
这是三张新表里唯一一处 **None → False**,而它之所以发生,是因为两个不同的问题共用了一个
数据结构。`ThinkingProfile` 描述的是「**我们能怎么控制它**」,而预算计算需要的是
「**它的行为是什么**」。把控制能力当成行为描述,是这一类表最容易踩的坑 ——
而且踩了之后每一处注释单看都是对的。

**建议修法**
1. 给 `model_limits.resolve` 加一个 `reasoning: bool | None = None` 参数,
   三个调用点(`provider_runtime.py:35`、`api/.../provider_models.py:82`、任何新加的)
   把模型行上的 `reasoning` 传进去;`None` 时才回落到现在这条推断。
2. 或者更干净:在 `thinking` 里分出第二个谓词
   `burns_output_budget(vendor, model_id) -> bool | None`,让「行为」和「控制能力」
   各有一份定义,`None` 时由 `reasoning` 覆盖决定,都没有才保守取 False。
3. `tests/test_model_limits.py` 补一条:**勾了「推理模型」的未知模型,
   `effective_max_output_tokens` 必须大于 `FALLBACK_MAX_OUTPUT_TOKENS`。**

---

### 2.5 🟠 本地 / 无鉴权端点永远拿不到模型目录 —— 同一条规矩只修在了一处

**现象**
`model_catalog.fetch_models:104-110` 无条件发 `Authorization`:

```python
resp = httpx.get(f"{base}/models",
                 headers={"Authorization": f"Bearer {api_key}"},
                 timeout=_FETCH_TIMEOUT)
```

`api_key` 为空时这个头的值是 `"Bearer "`(带尾随空格)。**实测**(本次当场跑的):
`h11` 在发送时抛 `LocalProtocolError: Illegal header value b'Bearer '`。而 112 行是
`except Exception` 全捕获,于是它被当成「这个端点没有目录」,还会往缓存里写一条**失败记录**
(`model_catalog.py:113-115`)。

而同一条规矩在一个模块之外被正确实现了:

```python
def _auth_headers(api_key: str) -> dict[str, str]:
    """空密钥(本地 / 无鉴权端点)不发 Authorization —— 否则 'Bearer ' 是非法头值,httpx 直接抛。"""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}
```
`backend/app/domain/ai_chat.py:437-439`

**后果链**(四处,全部静默):
1. 设置页的模型选择器对 Ollama / LM Studio / vLLM **永远是空的**
   (`api/routes/settings/provider_models.py:47`);
2. 价格预填拿不到目录报价(`provider_pricing.py:61` → `usage.prefill_model_pricing`);
3. `sidecar_provider` 的 `cached_model` 恒为 `None`(`provider_runtime.py:34`),于是
   本地模型的窗口一律落到 `LOCAL_FALLBACK_CONTEXT_WINDOW = 32000` —— 一个 128K 的
   本地 qwen3 会被提前四倍开始压缩上下文;
4. 每 60 秒重试一次并再次失败(`_FAILURE_TTL_SECONDS = 60`,`model_catalog.py:26`)。

**为什么看不出来**
三条后果的表现都是"本来就该这样":本地端点不列模型看着很正常(很多确实不列),
32K 窗口看着也像个合理的保守值 —— 而设置页显示的
`context_window_source` 正是 `"fallback"`,**它说的是真话,只是没说"我压根问不出来"**。
`tests/test_model_catalog.py:86` 只断言了"填了 key 时 key 要发到端点"
(`test_api_key_reaches_the_endpoint`),**没有反面那一条**。

**为什么是架构问题**
这是标准的"同一份语义要在多处成立"—— 链条审计 §0 数过 11 份契约语料都两侧各跑一遍,而
「空密钥不发 Authorization」这条同样是跨模块语义,却**没有语料、没有棘轮,只有一处注释**。
两处都写得对(`ai_chat` 那处甚至写了理由),但第二处根本不知道第一处存在。

**建议修法**
1. 把 `_auth_headers` 从 `ai_chat` 提到共享层(`app/core/http_retry` 或
   `ai/providers/contracts`),两处都 import 它。**收敛到一处**,判据是"加第三个 OpenAI
   兼容调用点时用不用再想一遍"。
2. `test_model_catalog.py` 补对称的那一条:**空 key 时请求里不许出现 `Authorization`**。
3. 顺带:`model_catalog.py:112` 的 `except Exception` 把"端点不实现 /models"和
   "我们自己发了个非法请求"混成同一个结论。至少 `logger.debug` 出异常类型 ——
   本次这个 bug 之所以能活着,就是因为这行把证据吞了。

---

### 2.6 🟡 兜底幂等键把时间戳编进了键里,文档承诺的事做不到

**现象**
`usage.billable:699`:

```python
key = idempotency_key or f"{operation}:{call.source_id or id(call)}:{int(began * 1000)}"
```

而 `billable` 的文档写着「**幂等**:不给就按 operation + source 生成。重放同一次调用不会
重复入账」(`usage.py:672`),`record_usage` 的 docstring 也写着
「source modules can safely call this after a retry or crash recovery without
double-booking」(`usage.py:217-219`)。

时间戳在键里,意味着**任何重放都会生成新键**,于是必然重复入账 —— 兜底键实际上等于"不去重"。
另外 `id(call)` 是内存地址,对象回收后会被复用,理论上可能撞键(方向相反:该记的没记)。

**为什么看不出来**
所有**真正需要幂等**的调用点都显式传了稳定键:
`generation:{id}:{status}`(`runner.py:355`)、`agent-message:{id}`(`host.py:596/652/682`)。
兜底键只服务于翻译、分析、提示词优化、画板写作这类"一次性、不会重放"的调用。
所以今天没有人被它坑到 —— 但文档给出的是一个**通用承诺**,而下一个需要重放保护的调用点
很可能就照着文档不传键。

**为什么是架构问题**
一个"在它该生效的那次不生效"的保护,比没有保护更坏 —— 链条审计 §1.3 用一条棘轮说过同一句话。
这里是同一个形状:承诺写在接口文档上,实现只对显式传键的调用方成立。

**建议修法**
两条选一,不要折中:
- 要么把兜底键做成真的幂等(`operation + source_type + source_id + 一个调用方给的轮次号`),
- 要么**把承诺改掉**:文档明说"兜底键只保证唯一,不保证幂等;需要重放保护的必须显式传键",
  并在 `record_usage` 的签名上把 `idempotency_key` 标成"调用方的责任"。

---

### 2.7 🟡 worker 进程写管道失败时,那个 worker 可能永远留在池子里且永远 busy

**现象**
`worker_pool.ResidentWorker._request_locked:128-131` 先把 `busy = True`,然后
`stdin.write(...)`。`WorkerPool.request:219-227` 只捕获 `RuntimeError` 来把死掉的 worker
踢出池子。

而 `stdin.write` 在子进程已经关掉 stdin 时抛的是 `BrokenPipeError`(`OSError` 的子类),
**不是 `RuntimeError`**。于是:

- worker 留在 `self._workers` 里;
- `busy` 永远是 `True`,`_reap_once:279-281` 明确跳过 busy 的,所以**闲置回收永远不会碰它**;
- 如果进程只是管道坏了而本体还活着(`alive` 为 True,`worker_pool.py:107`),
  `_ensure:256-258` 会把同一个坏 worker 一直发回去 —— 每次请求都 `BrokenPipeError`,
  十几 GB 显存也一直挂着。

**为什么看不出来**
子进程整个死掉是常见情况,而那一路是对的(`alive` 为 False → `_ensure` 换一个新的)。
"进程活着但管道坏了"要少见得多,而它的表现是"配音这功能一直报一句看不懂的错、重启才好" ——
指向不了进程池。

另一条窄的:`request()` 里 `with self._pipe_lock` **没有超时**(`worker_pool.py:118`)。
第二个调用方会无条件等满第一个的 `timeout`(默认 1800 秒),期间不检查取消。

**为什么是架构问题**
这个类的每一条约束都是撞出来的、并且写下了理由(见 §1.6),质量很高;缺的是
**"异常类型"这一条没有被同等对待** —— `except RuntimeError` 是在描述"我们自己抛的那种",
而池子要防的是"这个 worker 不能再用了",两者不是一回事。判据应该是
**"请求失败了就假定 worker 不可信"**,而不是"失败的类型对不对得上"。

**建议修法**
1. `_request_locked` 用 `try/finally` 保证 `busy` 归位。
2. `WorkerPool.request` 的 `except RuntimeError` 放宽成 `except Exception`(排除
   `KeyboardInterrupt`/`SystemExit`),注释写明判据是"失败即不可信"。
3. `_pipe_lock` 给一个 `acquire(timeout=...)`,拿不到就报"这个引擎正忙",而不是无声地等半小时。

---

## 3. 没有发现问题的地方(也是结论)

沿链条走过、确认处处成立的:

- **ADR-0019「付费的远端工作从不被放弃」** —— 回执落库走 contextvar 不走适配器、
  6 小时上限只防供应商、重启 resume 而不是判失败、超时消息带远端任务号、七家适配器
  全部 `supports_resume`,而且有棘轮
  (`tests/test_paid_generations_are_never_abandoned.py:91`)盯着"调了轮询就必须能接着取"。
  取消/超时/异常三条路**都记账**,幂等键稳定。这是本次读到的最扎实的一段。
- **「不写兼容分支,改数据形状就带迁移」** —— 全范围零命中。两处 `LEGACY_SHARED_VENV`
  都是一次性迁移,而且各自明写"不留作兼容候选"及理由。
- **三张「只写查证过的」表自身** —— `known_support` / `profile_for` / `known_limits`
  都严格返回 `None` / `UNKNOWN` / 空 `Limits()`,而且**把"为什么不写"也写下来了**
  (`thinking.py:158` 那段 qwen/GLM 的说明尤其好:少一个能用的开关,比一个点了会让对话
  失败的开关好)。消费点里只有一处把 None 当 False(§2.4)。
- **生成参数校验** —— `operations.validate_against_capabilities:341` 是四条入口
  (界面/智能体/工作流/定时)的唯一汇合处,理由写在注释里;
  `allowed_parameter_keys:291` 被校验器和棘轮**共用**,防的正是"两边分头演进";
  描述符查不到的模型放行而不是猜着拦。
- **素材角色语义** —— 首尾帧 / 参考 / 视频输入 / 驱动音频四组互斥,
  `KEYFRAME_ROLES` vs `REFERENCE_ROLES`(`contracts/generation.py:84-88`)按供应商硬约束
  建模;`image_url` 这个无角色别名按 kind 解释,收敛成一条规则
  (`generation.py:452-458`)而不是让每个适配器各自解释。
- **多产出** —— `GenerationResult.output_paths` 是一串(`generation.py:120`),
  `source_values` 取全部而不是第一份(`generation.py:461`),runner 每一份都登记
  (`runner.py:167-176`)。"用户选了 4 张、按 4 张计了费、库里只多一张"那条已经修干净。
- **进程内状态与单进程前提** —— `docs/PROCESS_STATE.md` 五类分册 +
  `tests/test_process_state_inventory.py` AST 棘轮。本范围内每一处模块级可变状态都在册
  且归类正确;托管 venv 一引擎一份、安装进度的事实源在盘上、探测带代次。
- **密钥不外泄** —— `_sanitize`(`ai_chat.py:442`)与
  `sanitize_adapter_error`(`generation.py:390`)两处形状一致,错误消息进日志和界面前都过一遍。
- **智能体轮次的记账** —— 成功/失败/崩溃三条路各记一条、失败轮次显式
  `mark_failed()`、每轮的服务令牌在 `finally` 里吊销(`host.py:697`)。

---

## 4. 给下一次的一条建议

链条审计 §5 的三条仍然有效。本次要补第四条,它比前三条更贵:

> **4. 把「第二条执行通道」当成一等检查项。**
>
> 这个仓库有两条对话执行通道(直连 HTTP / pi sidecar),两条生成执行通道(同步 / 异步轮询),
> 两条素材供给通道(素材库 / 外链)。后两组都做对了 —— 因为它们**在代码里汇到了同一个函数**
> (`source_url_values`、`poll_until_ready`)。第一组没有汇合点,于是 §2.1 那五个参数
> 只接到了一条上,而两条通道的差别在界面上完全不可见(同一个节点、同一份配置、
> 换一条连接就换一种行为)。
>
> 判据不是"两条都跑通了",而是**"同一份设置在两条通道上产生同一个请求形状吗"**。

---

## 附:本次涉及的关键文件

**供应商三层与契约**
- `backend/app/ai/providers/contracts/generation.py` —— 生成适配器契约、素材角色、
  `poll_until_ready`、`RemoteTaskWatch`
- `backend/app/ai/providers/registry.py` —— 适配器注册
- `backend/app/ai/model_catalog.py` —— 端点 `/models` 目录与 TTL 缓存(§2.5)
- `backend/app/ai/sidecar/adapters.py` —— pi sidecar 的 `run_turn` / `gateway_complete` 帧

**领域侧**
- `backend/app/domain/ai_chat.py` —— 直连对话补全的唯一实现(§2.1 / §2.2 / §2.3)
- `backend/app/domain/provider_runtime.py` —— 发给 pi 的那份 provider payload
- `backend/app/domain/provider_models.py` —— `RUNTIME_FIELDS` / `runtime_limits`
- `backend/app/domain/model_limits.py` —— 内置上限表与唯一合并处(§2.4)
- `backend/app/domain/structured_output.py` —— 哪家支持 `json_schema`
- `backend/app/domain/thinking.py` —— 思考档位表
- `backend/app/domain/usage.py` —— `BillableCall` / `billable` / `record_usage`(§2.6)
- `backend/app/domain/agent/judge.py` —— 放行判断(§2.3)
- `backend/app/domain/generation/runner.py` —— 生成任务执行与记账
- `backend/app/domain/generation/operations.py` —— 参数与素材的唯一校验处
- `backend/app/domain/workflows/executors/ai.py` —— LLM 节点(§2.1 / §2.2)

**本机运行时**
- `backend/app/ai/runtime/worker_pool.py` —— 常驻 worker 进程池(§2.7)
- `backend/app/ai/runtime/config.py`、`backend/app/ai/runtime/asr_models.py` ——
  托管 venv 与一次性迁移
- `backend/app/ai/runtime/install_state.py`、`backend/app/ai/runtime/download_state.py` ——
  安装/下载进度与探测缓存

**规约与棘轮**
- `docs/adr/0019-paid-remote-work-is-never-abandoned.md`
- `docs/PROCESS_STATE.md` + `backend/tests/test_process_state_inventory.py`
- `backend/tests/test_paid_generations_are_never_abandoned.py`
- `backend/tests/test_model_limits.py`、`backend/tests/test_structured_output.py`、
  `backend/tests/test_thinking_profiles.py`、`backend/tests/test_model_catalog.py`

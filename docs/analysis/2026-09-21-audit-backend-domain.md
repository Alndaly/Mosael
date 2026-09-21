# 后端领域层审计:同一件事,在这一层的每一环上都成立吗

> 日期:2026-09-21 · 基准:`e58190f2` 的干净工作区 · 范围:`backend/app/domain/`
> (**不含** `backend/app/ai/`、前端、Electron、测试体系)
> 方法:接着 [2026-09-21 链条审计](2026-09-21-chain-audit.md) 的三类失败模式往下走 ——
> 断在最后一环 / "给模型的"和"给人的"只做一半 / 错位的数据边界长出绕路。
> 只读审计,**没有改动任何代码**。凡本文写"证据",都是当场读到的 `文件:行号`;
> 读不出来的猜测一律没写进来。

---

## 0. 结论先写

上一轮的判断在这一层同样成立:纪律是真在执行的。领域异常而非 HTTPException(notes /
scenes / blender / permissions 四处同构)、数据归属地图 + 棘轮、CAS 而不是读-改-写、
"先拿槽再开会话"、回执挂在状态跳变而不是某个函数上 —— 这些都不是文档里的愿望,代码里
能一条条查到。

但这一层的失败方式和上一轮**一模一样**,而且能数出来:

- **断在最后一环** 4 条(AI 编排那条一断三处、任务消息的 i18n、子工作流的输出契约、
  节点 label 当人话用);
- **"给模型的"和"给人的"只做一半** 2 条(确认卡的措辞、AI 编排拿到的注册表);
- **错位/缺位的边界长出绕路或空洞** 3 条(删除时的引用完整性三种答案、并发预算没人管、
  时间线算子清单自称全集)。

**最值得记的一条不是某个 bug,而是一道棘轮的盲区**:`test_nobody_writes_prose_into_job_message`
专门为"别把中文直接写进任务消息"而写,而它扫的是 `job.message = "中文"` 这种赋值 ——
扫不到 `say(job, "中文")`。于是任务总线自己那一处违例安安静静地活着。这和上一轮 §1.3
的教训是同一句话:**一条在它该响的那次保持沉默的棘轮,比没有更坏。**

---

## 1. 沿链条走过的结论

| # | 链条 | 结论 |
| --- | --- | --- |
| 1 | `model_warnings`:领域 → 接口 schema → 节点 outputs → MCP 工具文档 → 模型真的看得见 | **成立**(上一轮修的那条,这次逐环复核过,含 `_with_images` 不吞非图片字段) |
| 2 | 任务文案:`say()` → `message_key/params` 落库 → `JobOut` 按请求语言重翻 → 界面 | **断在写入端**:`jobs.py:680` 传了一句中文字面量(§2.4) |
| 3 | 任务失败原因:`blame()` → `error_key/params` → `JobOut._translate_error` | **只有一个写入方**;总线自己的三条终态全是冻死的中文(§2.4) |
| 4 | 工作流节点目录:`NODE_TYPES` → 接口出口翻译 → 画布 | **成立**(`routes/workflows.py:104-118`) |
| 5 | 同一份目录 → **AI 编排**的提示词 / 校验 | **三处都断**(§2.3) |
| 6 | 同一份目录 → 节点的显示名 / 执行事件 | **断**:key 被当人话落库(§2.7) |
| 7 | 子工作流输出契约:`output` 节点 → `job.result.output` → `call_workflow` 返回 | **断**:`or` 回退把"空"和"没有"混成一件事,而且退路是被截断的值(§2.2) |
| 8 | 确认卡:领域算出 summary → 落库 → 界面 / 模型 | **半成品**:写入时冻结语言,与 `Job.message` 的教训相反(§2.5) |
| 9 | 删除的引用完整性:模型 / 笔记 / 场景 | **三种答案**,只有前两种是想过的(§2.6) |
| 10 | 并发:节点并行度 / 循环并发 / 嵌套深度 ↔ SQLite 连接池 | **没人对过账**,最坏情况超池上限一个数量级(§2.1) |
| 11 | 时间线算子:领域函数 → `EDIT_OP_KINDS` → 派发 → 智能体工具 / 工作流节点说明 | **清单是子集而自称全集**,且两份手写无比对(§2.9) |
| 12 | Blender 互通:`warnings` → transfer record → `summary()` → 接口 | **成立** |
| 13 | worker 协议:claim/lease/report(通用) ↔ publish 那一套 | **两套并存**,且各带一条兼容分支(§2.8) |

---

## 2. 问题清单(按严重度)

### 2.1 【高】工作流引擎抱着数据库连接等嵌套的活儿,而并行度从没按连接池预算过

**现象**

连接池是 5 + 10 溢出、30 秒取用超时 —— 这不是我算的,是仓库自己写下的
(`app/domain/assets/proxies.py:80-88`),并且为它立过规矩:**先拿信号量,再开会话**
(`app/domain/jobs.py:112-121`),还上了测试(`tests/test_worker_admission.py:78-116`)。

工作流引擎是唯一反着做的一层:

- `engine.py:237-241` —— 每个节点 `with SessionLocal() as node_db:` 先 `node_db.get(Workflow, …)`
  (连接就此取出),然后**握着它**调 `handler(node_db, wf, config)`;
- `engine.py:238` —— 在那个 `with` **里面**又调 `is_cancelled()`,而它
  (`engine.py:175-180`)自己再开一个 `SessionLocal()`。所以每个节点起步的一瞬间占 **2 条**;
- `engine.py:40,251` —— `MAX_PARALLEL_NODES = 8`。8 × 2 + 驱动线程那一条 = **17 > 15**,
  顶层单独就能越线;
- 更糟的是握着连接等的那几类 handler:
  - `executors/common.py:15-36` `wait_for_job` —— 明写"没有超时这一条",子任务跑多久就等多久;
  - `executors/subworkflow.py:97-101` `call_workflow` 走的正是它,嵌套上限
    `MAX_NEST_DEPTH = 8`(`subworkflow.py:20`);
  - `executors/loops.py:33,158` —— 循环体再开自己的线程池(并发上限 4),每一项又是一整套
    `execute_graph`。

一个"8 个并行节点,每个是 `call_workflow`"的图,就要 8(父节点握住)+ 8 ×(子驱动 + 子节点)
条连接。池子是 15。越线之后是 `TimeoutError: QueuePool limit of size 5 overflow 10 reached`,
由 `blame()` 原样记进 job.error —— 用户看到的是一句 SQLAlchemy 的英文。

**为什么看不出来**

三个常数分别写在三个文件里,每一个单看都克制(`MAX_PARALLEL_NODES = 8`、
`LOOP_FOREACH_MAX_CONCURRENCY = 4` 旁边甚至写着"外层 4 × 内层 4 就是 16 路"的提醒、
`MAX_NEST_DEPTH = 8`),**而它们是相乘的,没有任何一处写下它们的乘积要小于什么**。
`docs/analysis/backend.md:231` 和 `architecture.md:246` 都记着 `MAX_PARALLEL_NODES=8`,
两处都没提连接池。小图跑起来一切正常,规模上去才崩,而崩的那一刻错误指向的是随便哪个节点。

**为什么是架构问题而不是小 bug**

"先拿槽再开会话"这条规矩在这个仓库里是**被付过账才立起来的**(60 个视频丢 45 个任务),
并且写进了注释和测试。但那条测试守的是 job worker 这一层;工作流节点是另一层,它既不
走 `RENDER_SLOTS` 这类准入,也没有自己的准入。于是同一条规矩在一层强制、在另一层不存在 ——
而这两层现在是同一条执行路径上的上下游(工作流节点派生 job,job 又可能是工作流)。
把它当 bug 修(比如调小 8)只会把崩溃推迟到下一次嵌套变深。

**建议修法**

1. 最便宜的一刀:`run_node` 里的 `is_cancelled()` 复用 `node_db`,别再开第二条 ——
   这一步就把顶层从 17 压回 9;
2. 真正的修法是**给连接开一份预算**,并让它成为唯一的那一处:引擎按池容量派发(拿一个
   `Semaphore(池容量 - 保留)`,**在 `SessionLocal()` 之前拿**),而不是按 `MAX_PARALLEL_NODES`;
   嵌套时子图从同一个信号量取,所以乘积天然被压在预算里;
3. 会长时间等待的 handler(`call_workflow` / 循环)在进入等待之前**交还**连接 ——
   `wait_for_job` 本来就自己开会话轮询,父会话在等待期间没有任何用处;
4. 上一条同形的棘轮:仿 `test_worker_admission.py`,断言"一张满并发的嵌套图跑完之后
   `engine.pool.checkedout() == 0`,且没有节点死于 QueuePool"。

---

### 2.2 【高】子工作流的输出契约有一条 `or` 回退,把"空"和"没有"混成一件事,而退路给的是被截断的值

**现象**

`executors/subworkflow.py:101`:

```python
# 优先给「输出」节点声明的具名输出;没有则退回整份上下文(向后兼容)。
return {"output": result.get("output") or result.get("context") or {}}
```

两个问题叠在一起:

1. `or` 判的是真假不是有无。被调工作流**有** `output` 节点、但这次跑出来的具名输出恰好是
   空字典(条件分支没走到、上游返回空),`result.get("output")` 为假 → 掉进整份上下文。
   调用方拿到的是**完全不同的形状**:从"我声明的那几个名字"变成"被调图里每个节点 id 的全部产出";
2. 退路那一份是**被裁剪过的**。`engine.py:347-353` 里,`"output": output_values` 是原值,
   而 `"context": {nid: _trim_outputs(out) …}` 过了 `_trim_output_value`
   (`engine.py:368-400`):顶层字符串超过 2000 字**截断并加 `…`**、列表只留 200 项、
   对象只留 100 个字段。于是一份长文案、一段 LLM 回答、一串 id 列表,经这条退路传给上游时
   会安静地少一截。

**为什么看不出来**

裁剪是为"事件体积有上限"做的,它的本意是给**人**看的快照;而 `job.result.context` 同时
被当成了**给机器用的**数据源。两个读者共用一份字段,而只有一个读者需要有界。
再加上 `or` 回退只在"空"的时候才走,测试里的被调工作流总是返回非空,这条路平时不亮。

**为什么是架构问题而不是小 bug**

`output` 节点的说明写得很清楚:"被 `call_workflow` 调用时,调用方拿的就是这个契约"
(`engine.py:336`)。一个契约不能有一条"契约给不出东西时换一种形状"的退路 —— 那等于
没有契约。而且这条退路是明写的**向后兼容分支**,违反本仓库"不写兼容,改形状带迁移"的规矩:
没有 `output` 节点的旧工作流,该由一次迁移补上 `output` 节点(或在保存时要求它),
而不是让每一次调用都在运行时猜。

**建议修法**

- 判有无而不是判真假:`result["output"] if "output" in result else …`;
- 去掉 `context` 退路。被调图没有 `output` 节点时**明确报错**(`wfErr_calledWorkflowHasNoOutput`),
  并带一次迁移:给存量里被别人 `call_workflow` 过、却没有 `output` 节点的图补上一个;
- 顺带把 `job.result` 里"给人看的快照"和"给机器用的产出"分成两个字段名 ——
  现在它们共用 `context`,而只有前者该被裁剪。

---

### 2.3 【高】AI 编排是工作流这条链的最后一环,三处都断

`domain/workflows/ai_edit.py` 把"节点类型注册表 + 当前图"喂给 LLM,让它改图。同一份注册表
在接口那条路上被小心地处理过(`routes/workflows.py:95-118`,注释里专门写了为什么排序和翻译
都放在后端),而 AI 编排这条路上三处各断一次。

**(a) 给模型的是 i18n key,不是人话**

`ai_edit.py:55`:

```python
{key: {"label": meta["label"], "config": meta["config"], "outputs": meta["outputs"]} …}
```

而 `NODE_TYPES` 里 `label` / `description` 存的是 **key**
(`domain/workflows/__init__.py:905-915`:`"label": "wfNode_scene_render"`、
每个配置字段的 `"description": "wfNode_scene_render_scene_id"`),由
`test_backend_i18n.py:261` 这道棘轮强制"这里出现中文就是有人又直接写文案了"。
所以模型收到的系统提示里,每个节点的说明就是一串 `wfNode_scene_render_desc`
(`core/i18n.py` 里这类 key 有 269 个)。接口那条路是 `t(meta["label"], locale)`
(`routes/workflows.py:113-118`),AI 编排这条路没有。

**(b) 注册表里没有插件节点**

接口那条路是 `registry = {**NODE_TYPES, **plugin_node_types(db, user.id)}`
(`routes/workflows.py:104`),并且注释写着"插件节点跟内置节点走同一条路出去……前端因此不需要
知道这一项是插件来的"。AI 编排那条路只有 `NODE_TYPES.items()` —— 模型不知道插件节点存在。

**(c) 校验不带 `extra_types`,于是含插件节点的工作流一律编排失败**

`ai_edit.py:80` 是 `validate_graph(new_graph, require_config=False)`,没有 `extra_types`。
而保存(`__init__.py:1716,1750`)和运行(`engine.py:53`)那两条都带。
规则 4 又要求模型"保留用户没让你改的部分" —— 于是那个插件节点原样留在输出里,
`known_types`(`__init__.py:1407`)里没有它,`_unknown_type_error`
(`__init__.py:1409-1417`)报出:**"节点 X 来自插件「…」的工具 …,该插件未安装或未启用"**。
两次重试都会这样,最后抛 `wfErr_aiEditInvalidGraph`,`reason` 就是那句话。
插件明明装着、开着,画布上跑得好好的。

**为什么看不出来**

三处都不会报错,只会"效果差"或"报一个错误的原因"。(a) 的表现是模型编排质量下降 ——
没人会把它归因到提示词里少了翻译;(c) 的表现是一条**指向别处**的错误消息,用户会去插件页
找问题。而 `validate_graph` 的 `extra_types` 是可选参数,少传一个不会有任何提示。

**为什么是架构问题而不是小 bug**

同一份"可用节点类型"被组装了两次:一次在接口层(翻译 + 插件 + 排序),一次在 AI 编排里
(什么都没有)。这正是上一轮总结的"两处各实现一遍同一个语义,而没有契约钉住"。
`plugin_node_types` 的存在本身就是为了让插件节点"和内置节点没有区别",而这里它有区别。

**建议修法**

1. 把"给调用方的节点注册表"收敛成领域层的**一个函数**(带 `locale` 和 `db`),
   接口层和 AI 编排都调它;
2. `ai_edit_graph` 收 `extra_types` 并原样传给 `validate_graph`;
3. 棘轮:静态断言"所有 `validate_graph(` 调用点要么传了 `extra_types`,要么在一份写明理由的
   豁免清单里"(纯图校验如 `validate_body_graph` 拿不到 db,属于合理豁免)。
   形状与 `test_executor_outputs_are_declared.py` 完全一致。

---

### 2.4 【中高】任务总线自己有一句翻不了的中文,而那道棘轮扫不到它

**现象**

`domain/jobs.py:680`:

```python
say(job, "执行器失联")
```

`"执行器失联"` 不在 `MESSAGES` 里(查过)。按 `say()` 自己的规则
(`jobs.py:158-164` + `core/i18n.is_message_key`),这会把 `message_key` 写成空串、
把这句中文当**字面量**落库;`JobOut._translate`(`api/schemas/jobs.py:78-81`)见 key 为空
就原样返回。于是英文用户的任务列表里,这一条永远是中文。

全仓约 50 处 `say(` 调用里,**只有这一处**传了中文字面量;其余全是 `jobMsg_*` 或
一个从别处传下来的变量。

失败原因那一半更彻底。`error_key` / `error_params` 这套东西是完整的:列在
(`db/model_slices/jobs.py:60`)、迁移在(`db/migrations.py:382,2050`)、出口校验器在
(`api/schemas/jobs.py:83-87`)、`blame()` 在(`jobs.py:167-185`)。而 `blame()` 全仓
**只有一个调用方**:`workflows/engine.py:105`。总线自己的三条终态全是写死的中文:

- `jobs.py:538` `job.error = "后端重启导致任务中断,请重新发起"`;
- `jobs.py:556` `job.error = "已取消"`;
- `jobs.py:679` `error="执行器失联,任务已停止；请检查产出后重新发起"`。

前两句在 `MESSAGES` 里**本来就有对应的 key**(`jobMsg_interrupted` / `jobMsg_cancelled`,
`core/i18n.py:168-169`),只是只用在 `message` 那一列上 —— 同一句话,一列是 key,
另一列是冻死的文本。

**为什么看不出来**

`tests/test_backend_i18n.py:240` 那道棘轮 `test_nobody_writes_prose_into_job_message`
就是为这件事写的,它的文档还写着"没有任何东西会提示写的人 —— 这条棘轮就是那个提示"。
但它的判据是 `".message = " in line and CJK.search(line) and "job.message" in line` ——
**扫的是赋值语句**。`say(job, "执行器失联")` 既没有 `.message = ` 也没有 `job.message`,
一个字都不匹配。`job.error = "已取消"` 同理:扫描范围里根本没有 `.error`。

**为什么是架构问题而不是小 bug**

这不是"漏了一处文案",是**棘轮的判据和它要守的不变量对不上**。不变量是"落库的任务文案
不能冻住语言";棘轮实现成了"不能给 job.message 直接赋中文"。后者是前者当时唯一的违反方式,
而 `say()` 的入参和 `job.error` 是另外两个入口。上一轮 §1.3 付过同样的账(棘轮第一版只认
`return {字面量}`)。

**建议修法**

1. 补两个 key(`jobMsg_leaseExpired` / `jobErr_*` 三条),`_cancel_job_row` /
   `reconcile_orphaned_jobs` / `expire_worker_leases` 改走 key + `blame` 同构的写法;
2. 把棘轮的判据换成**按不变量写**:AST 扫一遍 —— (i) 传给 `say()` 的第一个参数若是字符串
   常量,必须在 `MESSAGES` 里;(ii) 赋给 `job.error` / `error=` 的字符串常量若含中文,
   必须同时写 `error_key`。写完先故意把 `jobs.py:680` 留着验证它会红。

---

### 2.5 【中】确认卡的措辞是写入时冻结的中文 —— 和 `Job.message` 的教训正好相反

**现象**

`ToolConfirmation.summary` 是一个 `String(500)` 的普通文本列
(`db/model_slices/agent.py:193`),在建卡那一刻由 `spec.summarize(db, payload)` 算出来
(`domain/agent/confirmations.py:68`),之后再也不重算。所有 `_summarize_*`
(`confirmable/media.py:70,87,113,174,216,263` 等)返回的都是写死的中文。

而 `Job.message` 的注释把这件事的代价写得很清楚(`jobs.py:154-157`):
"**这一列落库**,任务记录活得比一次请求久,写入时就翻会把语言冻死在那一刻 —— 用户切成英文后
历史任务仍是中文,**而那正是这次要修的毛病**"。确认卡是同一层、同样落库、同样活得比请求久
的另一份"给人看的文案",没有跟着改。

半截的痕迹就在旁边:`confirmable/graphs.py:72-79` 的 `external_warning` 特地
`t(节点label, get_current_locale())` 把节点名翻了,**包着它的那句话仍然写死中文**:

```python
return f"  ⚠️ 含{'、'.join(labels)}节点(后果在本应用之外,撤不回)"
```

而且这条路上 `get_current_locale()` 恒为 `zh`:语言只在 HTTP 中间件里从 Accept-Language
取(`app/main.py:291-297`),而确认卡由 sidecar / MCP 调进来,那条路不带这个头(查过
`agent-sidecar/` 与 `mcp_server.py`,零命中)。所以那个 `t()` 实际上是一条走不到的分支。

**为什么看不出来**

摘要是"这次调用要做什么"的一句话,它**看起来**像数据而不像文案,所以不会有人去问
"它是哪种语言"。而 `t()` 那半截让这处看上去像是已经处理过了。

**为什么是架构问题而不是小 bug**

确认卡是**授权界面**:用户点"批准"之前唯一会读的就是这一行(`graphs.py:63-68` 自己这么写)。
一个英文用户读不懂的授权提示,等于没有提示。更重要的是:同一条"落库的文案存 key、出口才翻"
的规矩,在任务总线上执行、在确认卡上不存在,而两者是同一层的两个姐妹。规矩只在一处生效时,
下一个新增的"给人看的落库文案"会按哪一份写,取决于作者先看到哪个文件。

**建议修法**

- `summary` 改成 `summary_key` + `summary_params`(带迁移:存量卡的 `summary` 原样搬进
  一个 `summaryLiteral` 之类的空 key 分支,或者干脆只迁移未决的卡、已决的按历史原样留着);
- 出口(`ConfirmationOut`)按请求语言翻,与 `JobOut` 同构;
- 顺手删掉 `external_warning` 里走不到的 `get_current_locale()`,或者让确认相关的接口
  在出口重算这句话。

---

### 2.6 【中】"删掉一个还被引用的东西"在同一层里有三种答案,只有两种是想过的

**现象**

| 被删的东西 | 行为 | 位置 |
| --- | --- | --- |
| 导入模型 | **拒绝**,并点名还有哪几个场景在用 | `domain/scenes.py:336-351` |
| 笔记 | **允许**;画板上那条坏引用仍可移动、可删除(专门留了 `retained` 豁免) | `domain/boards/canvas.py:347-350` |
| 3D 场景 | **允许**,且没有任何人检查画板 | `api/routes/scenes.py:109-117` |

第三条的后果是可验证的:画板项可以是 `kind: "scene"` 并带 `scene_id`
(`canvas.py:58,244-248`);保存画板时 `_validate_scene_references`
(`canvas.py:339-345`)要求每个 `scene_id` 都属于本工作区,否则抛
`BoardDomainError('3D 场景不属于当前工作区')`。场景删掉之后,引用它的那张画板
**此后任何一次保存都 422** —— 哪怕用户只是挪了一张便签。而错误里不说是哪一个节点,
唯一的出路是自己找到那个 3D 节点删掉。笔记那条路专门为这个情形留了豁免
(注释:"Existing broken references remain movable/removable after a source is deleted"),
场景这条路没有。

**为什么看不出来**

`domain/ownership.py` 那份归属地图和它的棘轮管的是**建行**("表的行创建只能发生在拥有它的
领域模块里",`ownership.py:4-9`),而且 `EXEMPT_PREFIXES` 明确豁免了 `app/api/routes/`
(`ownership.py:117`)。删除既不在地图的语义里,路由层又被豁免 —— 所以
`routes/scenes.py:115` 那句裸的 `db.delete(scene)` 不会被任何东西看见。
`domain/scenes.py` 里根本没有 `delete_scene` 这个函数,删除的"引用完整性决定"就这样
整个落在了一个被豁免的层里。

**为什么是架构问题而不是小 bug**

`delete_model` 的 docstring 把这件事想得很透("删掉就是在别处留一个加载失败的空位,
而那个空位没有任何线索说明它本来是什么")—— 那段推理对场景一字不差地成立,只是没人把它
搬过去,因为**场景的删除不在领域层**。三种答案不是三次权衡的结果,是两次权衡加一次空缺。

**建议修法**

1. 把删除搬进领域:`domain/scenes.delete_scene(db, workspace_id, scene_id)`,和
   `delete_model` 同构 —— 先问"还有谁在用"(画板、以及任何将来会引用场景的东西),
   再决定拒绝还是放行;
2. 在领域层写下**一条**"被引用者被删除时怎么办"的规矩(拒绝 + 点名 / 允许 + 坏引用可清理),
   让三处都指向它,而不是各答各的;
3. 归属地图扩一栏"谁能删这张表的行",棘轮跟着扫 —— 路由的豁免对**建**行成立
   (薄转译),对"删一行并因此决定别处的完整性"不成立。

---

### 2.7 【中】`NODE_TYPES` 的 label 是 i18n key,有两处把它当人话落了库

**现象**

- `domain/workflows/graph_ops.py:71`:
  `"name": str(op.get("name") or NODE_TYPES[node_type]["label"])` ——
  智能体 `add_node` 不带 name 时,节点的**显示名**就成了 `wfNode_scene_render`,
  而且它随图落库,画布上从此就叫这个;
- `domain/workflows/engine.py:183`:`node_label()` 同样回退到 `["label"]`,
  这个值进 `workflow.node.started / finished / skipped / failed` 事件的 payload
  (`engine.py:268,274,291,299,308`),落进 `task_events`,前端
  `frontend/src/features/workflows/runSteps.ts:54-78` 原样 `p.name ?? nid` 显示在执行历史里。

前端**没有任何 `wfNode_` 的字典**(全仓 `frontend/src` 搜 `wfNode_`,0 处命中),
所以这些 key 只会被原样画出来。

**为什么看不出来**

目录从"存中文"改成"存 key"时,出口那一处(`routes/workflows.py:113`)翻了,并且上了棘轮
(`test_backend_i18n.py:261`)—— 棘轮守的是"目录里不许出现中文",守不到"读目录的人有没有翻"。
而这两处的回退分支平时走不到:模板和手工建的节点都有名字,只有智能体建的、或者名字被清空的
才会露出来。

**为什么是架构问题而不是小 bug**

`graph_ops.py:71` 那一处把 key **写进了用户数据**,而不只是显示错。改对翻译之后,
存量里那些叫 `wfNode_*` 的节点还得靠迁移救回来。这是"同一份目录,一处知道它是 key、
另一处以为它是文案"的典型,而两处都在同一个包里。

**建议修法**

- `graph_ops` 不写名字(让 `name` 留空,显示时才回退到翻译后的 label),或者在那里就 `t()`;
- `engine.node_label()` 在**发事件那一刻**翻(`t(label, DEFAULT_LOCALE)`),与 `say()` 同构:
  事件 payload 里同时存 `name_key` 和渲染好的 `name`,出口按读的人的语言重翻;
- 棘轮补一条:"凡是读 `NODE_TYPES[...]['label' | 'description' | 'category']` 的地方,
  同一行必须出现 `t(`" —— 静态可查,豁免写理由。

---

### 2.8 【中】两处残留兼容分支,按本仓库的规矩都该是迁移或删除

**(a) 租约的 NULL 回退**(`domain/jobs.py:663-670`)

```python
legacy_kinds = set(external_kinds()) - {"publish"}
candidates = … or_(
    Job.lease_expires_at <= now,
    and_(Job.lease_expires_at.is_(None), Job.kind.in_(legacy_kinds), Job.updated_at <= now - …),
)
```

变量名就叫 `legacy_kinds`。这条分支伺候的是"租约列还不存在时就已经 running 的行"。
而迁移 `_migrate_job_worker_leases`(`db/migrations.py:2084-2096`)**只加列、不回填** ——
它停在最后一环之前,把剩下的半步留给了读路径。

**(b) "老执行器不报身份"**(`domain/publish/worker.py:75`,
`api/routes/publish_worker.py:26-28`)

```python
mine = task.claimed_by == worker if worker else True
```

注释写着"`worker` 为空 = 老执行器不报身份。那时保持原样(单执行器部署行为不变)"。
但执行器就在这个仓库里、跟后端同一个安装包发布,而且
`electron/publish/publishBackend.ts:95-120` 里 `readWorkerId()` 永远返回一个非空 id
(环境变量 → 落盘的文件 → 现生成一个 uuid)。所以这条分支在这个产品里**永远走不到**,
它只是把"两个执行器会互相把对方的任务判成孤儿"这个已经想清楚的问题,留了一个假的例外口。

**为什么看不出来**

两处都带着"向后兼容"的正当理由,而兼容代码的特征就是**它看起来永远是对的** ——
没有输入能证伪它,只能靠"这份数据/这个客户端还可能是旧的吗"这个仓库外的事实来判断。

**为什么是架构问题而不是小 bug**

本仓库明确的规矩是"不写兼容代码,旧数据用迁移"。(a) 是迁移写了一半;(b) 是给一个
**同包发布**的客户端留版本分支 —— 一旦接受这个理由,worker 协议以后每加一个字段都会
再长一条。

**建议修法**

- (a) 迁移里补一句回填:把 `status='running'` 且 `lease_expires_at IS NULL` 的 external
  job 直接判失败(和 `expire_worker_leases` 的结局一致,理由 `worker_lease_expired`),
  然后删掉读路径那条 `or_` 分支;
- (b) 把 `ClaimRequest.worker` 改成必填,删掉 `if worker else True`;两个执行器的归属判据
  只剩"认领者说了算"这一条。

---

### 2.9 【中低】时间线算子清单自称是全集,实际是 28 取 10,而且两份手写没有比对

**现象**

`domain/sequences/operations.py:1785-1788` 的注释:
"**这是『能对时间线做什么』的清单**,不是某一个界面的清单 —— 智能体的 `edit_timeline`、
工作流的时间线节点、将来任何别的入口,认的都是这一份。"

实际上 `EDIT_OP_KINDS` 有 10 项,而同一个文件里的变更操作有 28 个。缺席的包括
`set_clip_speed`(773)、`set_clip_gain`(800)、`split_clip`(1125)、
`detach_clip_audio`(837)、`set_clip_text`(711)、`set_subtitle_style`(1089)、
`move_clips_batch`(257)、`ripple_delete_clip`(445)、`set_sequence_reframe`(1018)……
于是"把这段调成 1.5 倍速"、"把这条字幕的样式改一下"在对话里和工作流里都做不到 ——
而领域层做得到。

清单和派发(`apply_edit_operations`,1801-1836)是两份手写的 `if/elif` 与元组,
现在恰好对得上,没有任何测试比对它们。加一项忘了另一边:加在元组里 → 运行时
"不认识的时间线操作";加在派发里 → 校验(`confirmable/media.py:66`)先把它拦掉。

**为什么看不出来**

两份列表现在是一致的,所以"看着对"。这正是上一轮 §3 第四处的形状
("两个数碰巧相等,所以一直没人发现")。而"清单不全"的表现是**功能缺失**,不是报错 ——
用户只会觉得"智能体不会调速",不会觉得这里有一处断链。

**建议修法**

1. 先把注释改成实话(它现在是**智能体/工作流这条路支持的子集**),或者把清单补全 ——
   两者都行,不能维持"声称是全集"的现状;
2. 棘轮:`EDIT_OP_KINDS` 与 `apply_edit_operations` 的分支集合必须相等(AST 或运行时探测都行);
3. 更进一步:让派发表成为唯一的那一份数据(`{kind: (dataclass, fn)}` 的字典),
   `EDIT_OP_KINDS = tuple(表)` —— 那时两份就不可能漂。

---

### 2.10 【低】`questions.answer` 的 docstring 声称了一道它并不做的校验

**现象**

`domain/agent/questions.py:92-116`。docstring 写着:

> 只认**这次问的那些问题**里出现过的选项 —— 界面之外的调用方(或者一个改坏了的前端)
> 塞进来的东西,不该变成模型看到的"用户说的话"。

代码里 `allowed` 确实算出了每个问题的合法 label 集合(100 行),但 `labels` 只被用来
判断"这个问题问过没有"(104-105),**从没拿来比对选项**。107 行的注释解释了原因
(「其它」走自由文本),但它和上面的 docstring 直接矛盾,而 docstring 在上面。

顺带:自由文本没有任何长度上限 —— `api/schemas/agent.py:73` 是
`answers: dict[str, list[str]]`,没有 `max_length`;107 行的注释说"只有一条
(自由文本不是多选)",代码也没有强制。这条文本会经 `_as_user_words`
(180-191)原样变成对话里的一条用户消息喂给模型。

**为什么看不出来**

一个算出来却没用上的变量,既不会被 ruff/oxlint 报(它在 `is None` 判断里被用了),
也不会有任何行为差异 —— 它唯一的证据是那段与代码不符的 docstring。

**为什么不是小 bug**

它本身危害有限(调用方是已鉴权的本工作区成员)。列在这里是因为它的**形状**值得记:
仓库里到处是"注释即契约"的写法,而这是一处注释说了一件代码不做的事。注释是这个仓库
最主要的设计载体,一处失真比一处 bug 更贵。

**建议修法**

- 把 docstring 改成实话("问题必须是问过的;选项允许自由文本,因为有「其它」"),
  并把自由文本的约束**写成代码**:单条、有长度上限(仓库里已有 `MAX_TEXT_CHARS` 这个约定);
- schema 上给 `answers` 的值加 `max_length`。

---

## 3. 没有发现问题的地方(这同样是结论)

沿链条走过、逐环确认成立的:

- **`model_warnings` 那条链**(上一轮刚修的)—— 领域返回(`scenes.py:472,505`)→
  接口 schema(`api/schemas/scenes.py:54`)→ 节点 outputs(`workflows/__init__.py:917-918`)→
  MCP 工具文档(`mcp_server.py:1357-1359,1481-1482`)→ 模型真的读得到
  (`mcp_server.py:323-335` 的 `_with_images` 只摘走 `images`,其余字段原样留在文字块里)。
  **五环都在。**
- **Blender 互通的 `warnings`** —— `bridge.py:277` 记进 transfer record,
  `summary()`(`bridge.py:146-147`)把它列在返回字段里,路由不套 schema 所以不会被吞。
- **并发写的 CAS** —— 三处独立实现,三处都是条件 UPDATE 而不是读-改-写,而且都写了理由:
  `notes.save_note`(`notes.py:106-111`)、`sequences._record_operation`
  (`operations.py:1741-1747`)、`agent.confirmations._claim`(`confirmations.py:158-175`)、
  `scenes.save_scene`(`scenes.py:130-134`)。`jobs.lock_active_job`(`jobs.py:188-204`)
  同一个手法,并且 `finish_job`(207-234)明写了"先看手里这一份再去库里对"的理由。
- **回执挂在状态跳变上,不挂在某个函数上** —— `_note_settled_jobs`(`jobs.py:255-274`)
  用 ORM 的 attribute history 认"从非终态进终态"这一次跳变,`_deliver_settled_receipts`
  (277-307)在 `after_commit` 里用**新 session** 送信。两处的理由都写下来了,
  而且确实覆盖了直接 `job.status = …` 的那些领域(它们不走 `finish_job`)。
- **数据归属地图**(`ownership.py`)—— 对**建行**这件事是成立的;它的局限见 §2.6,
  那不是它错了,是它没覆盖删除。
- **执行器输出棘轮**(`test_executor_outputs_are_declared.py`)—— 读过实现,
  它认得本仓库最常见的 `out = {...}` / `out["k"] = v` / `return out` 写法,
  也顺着单层透传找下去,豁免清单三条各有理由且有"只减不增"的守卫。
- **publish 的认领排除** —— `claim_next_pending`(`publish/worker.py:114-121`)排除的是
  "**任何人**正在跑的账号",不是调用方自报的那些;`reclaim_orphaned_running`
  (58-89)把"只有认领者能判孤儿"和"超时是全局判据"分得很清楚。
- **`wait_for_job` 没有超时**(`executors/common.py:15-25`)—— 这是**故意的**,
  理由(放弃等待不会让供应商停下来、只会让钱白花)写得完整,是对的。
  它带来的连接占用问题见 §2.1,那是另一件事。
- **插件清单的"老文件名"**(`backend/app/domain/plugins/packages.py:25-27,109-121`)—— 看着像兼容分支,
  实际不是:老名字只用于**发现目录**,发现后立刻 `migrate_directory` 就地改写
  (`packages.py:38-39`),之后的代码只认一种形状。符合"兼容负担在升级那一刻付一次"。
- **确认卡的协议措辞**(`tool_manifest.py:82-112` 与 `mcp_server.py:338-345`)——
  看着像"两处说了相反的话",逐条对过之后是对的:阻塞那条路由 sidecar 代等,模型看不到
  `confirmation_id`;直连 MCP 那条才会读到 `_confirmation_reply` 里的轮询说明。
  两份文案各自对应一条真实运行时,正是 `_CONFIRMATION_PROTOCOL` 注释所解释的那个设计。

---

## 4. 给下一次的建议

1. **棘轮要按不变量写,不要按"上一次的违反方式"写。** §2.4 是这一条最干净的例子:
   棘轮的文档说的是不变量("落库的任务文案不能冻住语言"),判据写的是那一次的形状
   (`job.message = "中文"`),于是同一个不变量的另外两个入口(`say()` 的入参、`job.error`)
   全是盲区。写完一道棘轮,值得再问一句:**这个不变量还能从哪几个入口被破坏?**
2. **上一轮建议的"领域返回的键 → 接口 schema"那条棘轮仍然值得补**,但这次审计发现
   更缺的是另一条同形的:**"同一份目录/注册表的所有组装点"**。§2.3 和 §2.7 都是
   `NODE_TYPES` 被组装/读取了多次,只有一处做对了。
3. **并发常数要有一处写下它们的乘积。** §2.1 里三个常数各自克制、相乘越线,而没有任何
   文件写着"它们的积必须 ≤ 连接池"。和上一轮 §3"视觉属性只能有一处说了算"是同一条规律 ——
   只是这次累加的不是像素,是连接。
4. **"删除"和"创建"要同等对待。** 归属地图只管建行,而删除才是做引用完整性决定的那一刻
   (§2.6)。下一次扩这份地图时,把"谁能删"一起写上。

---

## 附:本次用到的关键文件

**任务总线**
- `/Users/kinda/Developer/Mosael/backend/app/domain/jobs.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/schemas/jobs.py`
- `/Users/kinda/Developer/Mosael/backend/app/core/i18n.py`
- `/Users/kinda/Developer/Mosael/backend/app/core/db.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/assets/proxies.py`
- `/Users/kinda/Developer/Mosael/backend/tests/test_worker_admission.py`
- `/Users/kinda/Developer/Mosael/backend/tests/test_backend_i18n.py`

**工作流**
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/engine.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/__init__.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/ai_edit.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/graph_ops.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/normalization.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/executors/subworkflow.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/executors/loops.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/workflows/executors/common.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/workflows.py`
- `/Users/kinda/Developer/Mosael/backend/tests/test_executor_outputs_are_declared.py`

**场景 / 画板 / 笔记**
- `/Users/kinda/Developer/Mosael/backend/app/domain/scenes.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/scenes.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/schemas/scenes.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/boards/canvas.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/notes.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/blender/bridge.py`

**智能体**
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/confirmations.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/confirmable/graphs.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/confirmable/media.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/questions.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/agent/tool_manifest.py`
- `/Users/kinda/Developer/Mosael/backend/app/db/model_slices/agent.py`
- `/Users/kinda/Developer/Mosael/backend/mcp_server.py`

**时间线 / 发布 / 归属**
- `/Users/kinda/Developer/Mosael/backend/app/domain/sequences/operations.py`
- `/Users/kinda/Developer/Mosael/backend/app/domain/publish/worker.py`
- `/Users/kinda/Developer/Mosael/backend/app/api/routes/publish_worker.py`
- `/Users/kinda/Developer/Mosael/electron/publish/publishBackend.ts`
- `/Users/kinda/Developer/Mosael/backend/app/domain/ownership.py`
- `/Users/kinda/Developer/Mosael/backend/app/db/migrations.py`
- `/Users/kinda/Developer/Mosael/frontend/src/features/workflows/runSteps.ts`

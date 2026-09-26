# ADR 0020: 插件可以是生成供应商 —— ComfyUI 从内核搬进插件

## Status

Accepted — 2026-09-25。修订 [ADR 0019](0019-paid-remote-work-is-never-abandoned.md) 的最后一条
Consequence(「本地引擎保留自己的截止时间」),其余不变。沿用 [ADR 0005](0005-plugin-package-instance-capability.md)
的包 / 实例 / 能力三层、[ADR 0010](0010-provider-contracts-adapters-registry.md) 的契约 / Adapter / Registry
三层、[ADR 0015](0015-generation-parameters-come-from-the-adapter.md) 的「参数面由 Adapter 说」。

## Context

ComfyUI 在内核里是一家「供应商」(`ai/providers/adapters/comfyui/`),但它和别的供应商不是一类东西:

1. **它没有模型,只有工作流。** 目录里给它登记了一个叫 `workflow` 的假模型 id;真正选哪张图靠参数
   `workflow`(文件路径)+ `workflow_params`(`{节点id: {输入名: 值}}`)夹带进去。于是模型选择器里
   永远只有一个「ComfyUI · workflow」,选完还要在 AI 工作台里**另开一个 ComfyUI 专用区**再选一次
   工作流、再拉一次它的参数表 —— 那个区只有 AI 工作台有,画板和工作流节点里根本选不了工作流。
2. **它的参数面随工作流变。** 每张图有自己的采样器、步数、CFG、帧数;内核描述符只能写死
   `size / seed / steps` 那几个,其余靠前端专用代码(`provider === "comfyui"`)和两条专用路由
   (`/generation/comfyui/workflows`、`/generation/comfyui/workflow-params`)。
3. **它是用户机器上的第三方服务**,知识(UI 图 → API 图的转换、widget 对齐、输出收集、interrupt)
   每次跟着 ComfyUI 的版本变,却写在内核里、跟着应用发版。
4. **参考图接不进去。** LoadImage 节点要先 `/upload/image` 再按文件名接线,内核 Adapter 从没做过。

而插件体系(ADR 0005)恰好有「第三方能力、按实例配置、进程隔离、自带文案」的全部骨架,缺的只是
**「一个插件能替宿主做成一次生成」** 这一种能力 —— 就像 `provides: public_url` 让插件替宿主把本地
素材换成公网直链。

## Decision

### 1. 生成是插件可以声明的一项宿主能力

```jsonc
{
  "provides": ["generation"],
  "runtime": { "kind": "process", "entry": "tools/main.py" },
  "tools": { "declare": [
    { "name": "comfyui_generation", "provides": ["generation"], "timeout_seconds": 21600, "input_schema": {"type": "object"} }
  ] }
}
```

和 `public_url` 同一个规矩:**包上的 `provides` 说「能做」,工具上的 `provides` 说「这件事归我」**。
额外三条:

- **只给进程形态。** MCP 是别人的协议,我们不往里加字段(和 artifact / state 同一条)。
- **只能有一个工具认领,而且它只给宿主调。** 它说的是下面那套协议,不是一次普通调用;暴露给智能体或
  工作流等于留一条绕开生成任务、用量台账和回执的后门(和 `internal: true` 同一个理由,这里由能力
  本身决定,不必再写一遍)。
- **预算按能力给。** 这个工具的 `timeout_seconds` 上限是 6 小时(`POLL_TIMEOUT_SECONDS`,和远端任务
  同一个数),不写就是 1 小时 —— 普通工具那条 60 秒 / 1800 秒上限管不了一段长视频。

### 2. 协议:一次调用两种 `op`,生成那种是流式的

同一个进程入口,`input.op` 分两种:

**`models` —— 这个实例现在有哪些模型。** 普通的一问一答(60 秒预算)。回 `{"models": [...]}`,每一项:

```jsonc
{
  "id": "portrait.json",                 // 实例内稳定;会被存进画板、工作流、默认模型
  "label": {"zh": "人像", "en": "Portrait"},
  "kind": "image",                       // image | video(宿主今天只接这两种;别的照常列出但不进选择器)
  "modes": ["text-to-image", "image-to-image"],
  "parameters": {                        // 键 → JSON Schema 片段
    "seed": {"type": "integer"},
    "size": {"type": "string", "enum": ["1024x1024", "832x1216"], "default": "1024x1024"},
    "3.cfg": {"type": "number", "title": "KSampler · cfg", "default": 7, "minimum": 0, "maximum": 100, "x-advanced": true}
  },
  "inputs": [{"role": "reference_image", "max": 2}],   // 角色取自宿主的 SOURCE_ROLES
  "max_outputs": 1,
  "prompt_dialect": "sd-tags"            // 可选:提示词优化按哪种写法改
}
```

宿主把它**翻成**内核自己的能力描述符(`parameter_keys` / `sizes` / `duration_seconds` / `boolean_parameters` /
`parameter_choices` / `source_limits` / `max_num_images`),宿主词汇以外的键进 `parameter_schema`,由三个界面
用同一个通用控件渲染。插件说的是 JSON Schema,不用学我们的描述符;描述符也不因为插件而多出一种方言。

**`generate` —— 做一次。** 请求:

```jsonc
{"op": "generate", "model": "portrait.json", "kind": "image",
 "prompt": "…", "negative_prompt": "…", "parameters": {"seed": 7, "3.cfg": 6.5},
 "inputs": [{"role": "reference_image", "path": "/…/inputs/01-reference_image.png"}],
 "resume": null}
```

stdout 是**一行一个 JSON 对象**(NDJSON),最后一行是和普通协议同形的结果:

```
{"event": "progress", "progress": 0.42, "message": "KSampler 12/20"}
{"event": "task", "task": {"prompt_id": "…"}}
{"ok": true, "output": {"outputs": [{"path": "a.png"}], "usage": {"images": 1}}}
```

- **`progress`**:0..1 加一句话,进任务中心(封顶 0.95 —— 1.0 属于入库那一步)。
- **`task`**:远端回执。宿主**收到的那一刻落库**(`Job.payload.remote_task`,ADR 0019 的同一格)。发了它就等于
  承诺:重启后宿主会带着 `"resume": <task>` 再调一次,插件要接着等那个任务,**不再提交**。
- **取消**:宿主建一个文件,路径在 `MOSAEL_PLUGIN_CANCEL_FILE`。插件看到它就去停远端的活(ComfyUI 是
  `/interrupt` + 删队列)再退出;30 秒不退就杀。用文件不用信号:Windows 上没有可靠的信号,而「检查一个
  文件在不在」任何语言一行就写完。
- **预算用完**按取消处理(先建取消文件、给宽限、再杀),报错带上回执,好让人去对面找回那一份。
- **输入文件**:宿主把素材库里的那份**拷一份**进暂存目录再给路径(和 `format: "asset"` 同一条:给副本不给原件;
  只拷素材库里、本工作区的文件 —— 宿主在交出去之前核对它落在媒体目录里)。
- **输出文件**:写进 `MOSAEL_PLUGIN_OUTPUT_DIR`,或给 url 让宿主去下 —— 和 `artifact` 同一套规则、同一个上限。
  宿主把它们交给生成执行器,由它登记成素材。

### 3. 宿主把插件包成一家普通的供应商

**不给生成领域加第二种「连接」。** 生成的一切 —— 选择器、默认模型、画板、工作流节点、智能体工具、生成历史、
任务中心、回执、用量与定价 —— 都指向 `ProviderProfile`(连接)和 `ProviderModel`(模型)这两张表,外键在
七八张表上。让它们各自认识「也可能是个插件实例」,是七八处 `if 插件 elif 连接`。

所以反过来:**一个提供生成能力的插件实例,就是一条连接。**

- `provider_profiles.plugin_instance_id` 指向它(外键,实例删掉连接跟着删,模型跟着删,默认模型置空,
  历史任务的连接置空 —— 全是既有外键在做)。vendor 是 `plugin:<包 id>`:导出到别的机器也稳定,和节点类型
  `plugin.<包id>.<工具>` 绑包不绑实例是同一个理由。
- 这一行是**把手**,不是副本:配置和凭据仍只在插件实例上;连接上只有身份(归谁、叫什么、开没开)。
  由一个函数(`generation/plugin_connections.sync`)保持同步,插件实例的每次变动经插件域的能力钩子
  (`plugins/host_capabilities`)通知它 —— 插件域不认识生成域,方向和 `media_bridge` 一样。
- 模型行就是插件目录的缓存:每刷新一次,按 `models` 的结果增删改(`source = "plugin"`),插件声明的
  描述符存在 `provider_models.declared_capabilities`。解析顺序:用户声明 → **连接声明** → 内置目录 → 兜底。
  插件说自己的模型收什么,正是 ADR 0015「参数面由 Adapter 说」—— 这里 Adapter 就是插件。
- `ai/providers/registry` 多一个**动态来源**:`plugin:` 开头的 vendor 由插件域登记的解析器给出
  `PluginGenerationAdapter`。内置 Adapter 的精确登记与重复检查不变。
- 免密钥这件事从「vendor 预设写着 keyless」变成结构事实:**插件连接的凭据在插件实例上**,所以不需要连接
  上的钥匙。`keyless` 预设字段只有 ComfyUI 一家在用,随它一起删掉。
- 归属照旧:连接归实例的主人,选择器只列**他自己的**实例提供的模型(`models_for_capability(user_id=…)`),
  和 `plugins/nodes.instances_for_node(user_id=…)` 是同一条规矩。

目录什么时候刷新:实例新建、改配置、启停、授权 / 凭据变化、插件页点「刷新」,以及后端启动时在后台刷一遍。
结果(几个模型、刷新时间、失败原因)记在 `plugin_instances.capability_status`,插件页看得到。

### 4. ComfyUI 是随应用发的第一方插件

- 源码在 `plugins/bundled/comfyui/`,随后端一起打包(PyInstaller `--add-data`),**每次启动对账**:插件目录里
  没有或版本不同就装上(`install-bundled-plugins`,recurring 迁移步骤)。它不进市场索引 —— 发它的是应用本身。
  内置的插件不能卸载(卸了下次启动又装回来,那比不让卸更让人困惑)。
- 一个实例 = 一台 ComfyUI 服务器(`server_url`);多台就建多个实例。
- **每个保存的工作流就是一个模型**(id = 它在 ComfyUI 里的路径),kind 按输出节点判(视频容器输出 → video,
  否则 image);可调的字面量输入成为参数(`<节点id>.<输入名>`),提示词 / 反向 / 种子 / 尺寸对到宿主自己的
  控件上;**LoadImage 节点成为参考图槽位**(接到 `start_image` 这类输入的在视频图里是首帧),生成时先
  `/upload/image` 再接线。
- 另有两个模型:**内置文生图**(服务器上至少有一个 checkpoint 时)和**粘贴的 API 模板**(实例配置
  `api_workflow`,多行;老版本在连接上粘过模板的,迁移搬到这里,`{{prompt}}` 等占位符照旧)。
  模板留下是因为转换是「尽力而为」:认不出的非常规工作流总得有条退路。
- 进度走 ComfyUI 的 WebSocket(`/ws?clientId=…`,标准库手写的最小客户端);连不上就退回轮询 `/history` + `/queue`。
- 取消是真的:`/interrupt` + 从队列删掉。回执是 `prompt_id`,重启后接着等。

### 5. 内核里的 ComfyUI 全部拿掉,数据迁移过去

- 删 `adapters/comfyui/`、目录里的 `comfyui:workflow:*` 和 `comfyui-image/video` 档案、`comfyui` 预设、
  `/generation/comfyui/*` 路由、前端所有 `provider === "comfyui"` 分支。不留兼容分支(ADR 0006)。
- 迁移 `migrate-comfyui-connections-become-plugin-instances`(一次性、幂等):每条 `comfyui` 连接
  → 同一个人的 ComfyUI 插件实例(地址、模板、启用状态、授权)**并原地改成插件连接**(连接 id 不变,于是
  模型行、默认模型、生成历史、用量的外键全都还指着它)。模型 `workflow` 按有无模板改名成 `api-workflow` /
  `builtin:txt2img`;画板、工作流(连同一份新修订,作者沿用上一版)、定时任务、生成会话、生成历史、用量里的
  `comfyui` 与 `parameters.workflow / workflow_params` 改写成「那个工作流就是模型、参数拍平成
  `<节点>.<输入>`」;指向旧档案的参数声明删掉(那是对旧 Adapter 的断言)。认不出来的(没有模板的
  `workflow` 视频)保持原样,运行时明确报「这个模型不可用」。

### 6. ADR 0019 的修订

「本地引擎保留自己的截止时间」一条作废。那条的理由是「本地卡住的队列与其等,不如早报」—— 而那时我们既看
不到真实进度也停不下它。现在进度是真的(WebSocket)、取消是真的(interrupt),本地的活和远端的活一样:
**结束只有两种 —— 对面给出终态,或者用户取消**;6 小时上限只防一个永远不回话的对面。

## Consequences

- ComfyUI 的模型在 AI 工作台、画板、工作流节点、智能体、默认模型里和别家**一模一样**地出现;选工作流
  就是选模型,不再有专用区。
- 插件作者可以写别的生成供应商(本地 SD WebUI、自建推理服务),不用改内核一行。
- 连接表上多了一种来源。设置页的供应商列表把插件连接显示成「由插件管理」,改地址、换名字都去插件页。
- 目录是缓存:ComfyUI 里新存一个工作流,要等下一次刷新才出现。刷新时机见下面的补充 —— 插件给了指纹的,
  一分钟内自动出现。
- ComfyUI 的知识跟着插件走,但插件仍随应用发版 —— 这一步换来的是边界,不是独立发版;独立发版等市场
  支持「内置包的更新」再说。

## 补充(2026-09-25):目录指纹、工具、参数的名字

落地之后用户的第一句反馈是「ComfyUI 插件的能力太少了」—— 插件页上只有「2 个模型」,一个工具都没有。补了四件事,
**都在框架里做成通用能力**,ComfyUI 特有的知识仍只在 `plugins/bundled/comfyui/` 里:

- **目录变了就刷新。** `op: models` 可以带一个 `fingerprint`,插件再支持一个便宜的 `op: fingerprint`(只列目录,
  不拉任何一张图)。宿主每分钟问一次指纹(不留调用记录),变了才重新 `op: models`。拒绝了「每次打开选择器现问」
  的理由不变(一个 ComfyUI 上百张工作流);这里问的只是一个哈希。
- **参数的名字按语言分、在给人看时再挑。** 目录在后台刷新,刷新那一刻的语言不是看的人的语言;`title` /
  `description` 可以是 `{"zh", "en"}`,原样存进描述符,`/generation/options` 出口按请求的语言挑。
- **插件页列出它提供的模型**(`host_capabilities.register(…, listing=…)`,生成那一侧读模型行):宿主能力的
  「做出来的东西」有了一个通用的列法,插件域仍不认识生成域。
- **生成以外的活走工具。** 「原样跑一张工作流、交回全部产出」不是一次生成(没有提示词也行、产出不止一种),
  做成普通工具,为此给工具加了三样通用能力:**流式**(`stream: true`,进度经 `jobs.report_progress` 成为工作流
  节点事件,取消先建取消文件)、**一次交出几份文件**(`artifacts`)、**收一串素材**(素材数组)。工具不跨重启续等、
  上限仍是 30 分钟;要跑更久的走生成。
- 宿主的素材角色多了 `mask`(局部重绘的蒙版),不是 ComfyUI 专用 —— 哪一家生成接口收蒙版都用它。

## 补充(2026-09-26):工具也可以在运行时报出

第二句反馈是「运行工作流的参数是写死的吗?每个工作流应该参数是不同的吧」。`run_workflow` 的入参是清单里写死的
一张表,不管选哪张工作流都一样。**决定:插件可以在运行时报出工具**(宿主能力 `tools`,和 `generation` 同一套
「认领 + op + 指纹」),而不是给 ComfyUI 开一个特例:

- 报出的工具存进 `plugin_instances.discovered_tools` —— MCP 连接从服务拉来的清单本来就存在这里,一个连接只有一份
  「运行时知道的工具」,开关、执行、节点类型、智能体工具表全都不用分支;
- ComfyUI:每张保存的工作流(和粘贴的模板)一个工具 `wf_<id>`,名字取 ComfyUI 写在工作流文件里的 id(改名不变),
  入参、输出都从那张图推;通用的 `run_workflow` 留给智能体当退路(`wait: false` + `import_outputs`),不再默认开放;
- 存着的 `run_workflow` 节点由插件声明 `replaces`、宿主通用地改写(`domain/workflows/plugin_references`):每次清单刷新,
  以及每次启动的对账步骤 `rewrite-replaced-plugin-tools`。它依赖插件报出的清单(ComfyUI 的图只在 ComfyUI 里),
  所以不是一次性迁移;对不上的节点原样留着,老工具仍在,不会坏;
- 目录巡检从生成域挪到插件域(`plugins/catalog_watch`),对每项给过指纹的能力一视同仁;
- 插件页「试一下」和工作流节点用**同一个表单组件**、同一份字段声明,素材数组有了挑选控件。

被否掉的:**给 run_workflow 的表单按选中的工作流动态换字段**(依赖字段、`options_from`)—— 那只修了插件页,
工作流节点、智能体看到的仍是一张写死的表;而且节点的输出口也没法按工作流声明。

## 补充(2026-09-26):模型说自己要不要提示词

ComfyUI 的放大工作流当生成模型用时,三个界面都逼人先敲一句用不上的提示词(图像 / 视频「必须有提示词」写死在
契约层)。**决定:提示词要不要写是描述符的一格 `prompt`(`required` / `optional` / `none`,没写就是 `required`)**,
内置目录、用户参数组、插件共用;插件在 `op: models` 的每个模型上说,宿主只收认得的那三个值。生成漏斗
(`operations.validate_text_inputs`)是唯一的判据 —— `none` 带着提示词当场拒,`optional` 空着放行,`required`
空着拒(会唱歌词的模型只给歌词也行);契约层那条按种类写死的检查删掉。ComfyUI 插件从图里读:没有文字喂进
采样器 / 引导器是 `none`,提示词节点里存着话是 `optional`(空着就用那一句,插件不再把它清成空串),存的是空的
或模板里是 `{{prompt}}` 是 `required`。AI 工作台、画板、工作流节点照它把提示词框藏起来 / 标可选 / 标必填;工作流**点运行时**(建任务之前、连同循环体)
按每个生成节点选中的模型用同一条规矩判一遍字面量提示词,不等前面的付费节点跑完才报;
智能体从 `list_generation_models` 看到它,开卡时按同一套规矩判。音频此前的 `requires_prompt` / `prompt_optional`
两个布尔并进这一格,用户参数组里存着的由迁移 `migrate-prompt-requirement-becomes-one-field` 改写。

## Considered options

- **生成领域认两种连接**(ProviderProfile 或 PluginInstance)—— 拒绝:外键在七八张表上,每处都要分支,
  漏一处不会报错,只会让某一条路径(默认模型、定价、定时任务)对插件静默失效。
- **插件模型单独一张表、选择器合并两份清单** —— 拒绝:同上,外加「选择器列什么」又有了第二个答案
  (resolution.py 当初就是为了收掉第二个答案)。
- **每次打开选择器都现问插件** —— 拒绝:一个 ComfyUI 上百个工作流,每个要拉一次图;选择器一天打开几百次。
  目录缓存在模型行上,刷新时机明确。
- **生成当成普通工具、结果走 artifact** —— 拒绝:没有进度、没有取消、60 秒预算,也绕开了生成任务的回执与计量。
- **取消用信号** —— 拒绝:Windows 上 SIGTERM 就是 TerminateProcess,插件没有机会去 interrupt 对面。
- **保留 ComfyUI 内核 Adapter、只把「工作流即模型」做进去** —— 拒绝:问题 3(知识跟着 ComfyUI 变)和问题 4
  (参考图)仍在内核里,而下一家本地引擎还得再进一次内核。

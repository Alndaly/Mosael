# ADR 0038:ComfyUI 工作台 —— 画布用 ComfyUI 自己的,面板是 Mosael 的;挑出几项就是一个「应用」

## Status

Accepted — 2026-10-05。1.10.0 的主功能,1.9.1 发版之后开工。维护者拍板:「待拍板」七项都按推荐(A);同一天另定了模型库预览图的分档与 NSFW(§9),一并放进 1.10.0。

## Context

维护者:「关于 ComfyUI 插件工作流能力,请重构优化工作流编辑交互,参考 RunningHub 那样,补充一个优化过后的、集成了一些
模型选择能力的 ComfyUI 界面」。已经定下的几条:

- **画布用 ComfyUI 自己的**(内嵌),每个自定义节点照常能用,Mosael 的面板停靠在旁边;不重写画布。
- 面板:**模型库**(选中一个加载节点,按它收的目录筛模型,带缩略图、底模、触发词,点一下填进去,缺的就下载)、
  **缺失项**(缺的节点和模型放一起,一键装)、**运行与结果**(每张结果标出来自哪个节点;「以后只要这张」记成这张工作流的结果)。
- **应用那一半**(对应 RunningHub 的「AI 应用」):作者挑出要给别人填的几项,存成这张工作流的一张精简表单;AI 工作台、
  画板、工作流节点选这张工作流时都用这张表。
- 两半共用一份「工作流 → 能填的项」的理解。

### 现在有什么

| 哪块 | 代码 | 做到哪 |
| --- | --- | --- |
| 工作流库(ADR 0035) | `plugins/bundled/comfyui/tools/workflow_library.py`、`plugins/bundled/comfyui/tools/workflow_import.py`;界面 `frontend/src/features/plugins/WorkflowLibrary.tsx`、`WorkflowImport.tsx` | 列表、图摘要、识别出的输入 / 参数 / 输出、缺节点和缺模型、复制 / 改名 / 回收、导入(JSON、带工作流的图片、链接)、装节点包、重启 |
| 模型库(ADR 0034) | `plugins/bundled/comfyui/tools/library.py`、`families.py`、`sources.py`;界面 `frontend/src/features/plugins/ModelLibrary.tsx` | 按目录列文件、预览图、底模家族、触发词、谁在用、三条下载路;生成表单里选模型文件的下拉带缩略图(`x-model-folder`,`frontend/src/components/generation/ModelFilePicker.tsx`) |
| 「能填的项」 | `plugins/bundled/comfyui/tools/graph.py` 的 `describe` | **全自动**:写提示词的格(`text_slots`)、种子、画布尺寸、跑几遍(`counts_runs`)、读素材的节点(`slots`)、其余每个字面量输入(`tunable`,名字和常用与否看 `labels.py`)、输出节点(`output_nodes`)和缺省结果(`final_outputs`) |
| 表单 | 插件目录 → `backend/app/domain/plugins/generation.py` 收形状 → `backend/app/domain/generation/plugin_connections.py` 的 `descriptor` 变成描述符 → 前端 `frontend/src/lib/generationCapabilities.ts` 的 `declaredParameters` / `frontend/src/components/generation/parameterPanel.tsx` 渲染 | AI 工作台、画板、工作流节点三处同一个描述符、同一套控件,参数键是 `<节点 id>.<输入名>` |
| 工具 | `plugins/bundled/comfyui/tools/tooling.py` | 每张工作流一个工具,入参同一套推导;`mirrors` 让画板只留生成那一个入口 |
| 跑 | `plugins/bundled/comfyui/tools/run.py` | 提交、WebSocket / 轮询进度、只停自己的任务(`stop`)、带回执重启后接着等、跑几遍(`run_repeated`) |
| 内嵌编辑器 | `electron/publish/comfyEditor.ts`(写死的脚本)、`electron/publish/publishWorker.ts` 的 `openComfyWorkflow`、契约 `electron/ipc-contract.cjs` 的 `parseComfyWorkflow`、前端 `frontend/src/features/plugins/workflowEditor.ts` | 浏览器池那套内嵌视图(`electron/publish/accountViews.ts`,分区 `persist:pool-comfyui-<连接 id>`)打开这台 ComfyUI,主进程注入脚本:等 `window.app.extensionManager.workflow` 就绪,`getWorkflowByPath` 取那一张,`app.loadGraphData` 打开 |
| 存回 ComfyUI | 同上 | **Mosael 自己不写这张图**:用户在内嵌的 ComfyUI 里 Ctrl+S,是 ComfyUI 前端自己覆盖写回 `workflows/`。视图收起时 Mosael 重拉一遍目录、工作流库、模型库(`workflowEditor.ts` 的 `onReturn`;ADR 0035 §4 写的「每 5 秒看一次改动时间」实际没做成这样)。Mosael 经插件写的(导入、复制)一律 `overwrite=false` |

动手前在维护者那台 ComfyUI 上只读核对(0.38.0,前端 1.53.10,单用户模式 `GET /users` → `{"storage": "server"}`;
没有排任何任务):

- **自动推出来的表单太长**。17 张工作流按现在的 `describe` 推,每张 9–115 项参数,中位 24 项,其中一半以上标成「高级」
  (`moodyKrea24KHD` 115 项、`controlnet` 55 项、`beautiful girl` 45 项);`YZ金鱼` 有 10 个读图节点,在表单上是同一个
  角色「参考图 ×10」,分不出哪张是哪张(插件的 `slots` 知道每个槽的节点标题,但目录里的 `inputs` 一个角色只有一项,宿主收的 `label`
  也是一个角色一个,`descriptor` 还没传下去)。
- **ComfyUI 前端照原样存回工作流里的扩展数据**。那 16 张 JSON 的顶层 `extra` 里有别的扩展写的键(`ue_links`、`VHS_*`、
  `0246.VERSION`、`pixaromaGroups`),节点 `properties` 里有 `ue_properties`、`widget_ue_connectable`、`models`……
  它们经这版前端存过还在。
- **桥要用到的前端名字都在**。取前端的静态脚本(239 个块)查过:`app.graphToPrompt`、`app.loadGraphData`、
  `app.refreshComboInNodes`、`registerExtension`、`getWorkflowByPath`、`selected_nodes` / `selectedItems`、命令
  `Comfy.SaveWorkflow`、事件 `executing` / `executed` / `execution_cached`、`isModified` / `changeTracker`、`window.comfyAPI`。
  自定义节点包的前端脚本就是靠 `window.app` 这一套写的(那台机器装了 11 个带前端脚本的包),它变了整个生态都要改。

### 哪里不够

- 改工作流仍是「回 ComfyUI 原样的界面」:选大模型 / LoRA 是一长串文件名(那台机器 530 个模型文件),Mosael 的模型库、
  缺失项、运行结果都在另一个窗口。
- 表单是推出来的,作者说不了「只给用户这三项」,也起不了名字;两个读图节点都叫「参考图」。
- 缺省结果是 1.12.2 规则**猜**的,猜错了只能每次手选「结果取自」;一张结果来自哪个节点,Mosael 里看不到。
- 经 Mosael 跑出来的图只带 API 格式的 `prompt`,拖回 ComfyUI 没有布局(ADR 0035 已记)。

### RunningHub 那边,公开资料能核实到哪

- **能核实**(官方 API 文档 [doc-8287469](https://www.runninghub.ai/runninghub-api-doc-en/doc-8287469)):一个 AI 应用
  按 `webappId` 调;`GET /api/webapp/apiCallDemo` 列出这个应用能改的项,每项是 `nodeId` + `fieldName`(加
  `nodeName`、`fieldValue`、`description`);提交 `POST /task/openapi/ai-app/run` 带 `nodeInfoList`,查结果
  `POST /task/openapi/outputs`。**能填的项就是「节点 + 输入名」**,和我们的 `<节点 id>.<输入名>` 是同一种锚点。
- **只在第三方转载里看到**([runninghub-studio](https://github.com/Waym1ng/runninghub-studio) 收的文档):每项还有
  `fieldType`(`IMAGE` / `STRING` / `LIST`…)、`fieldData`(可选值);图先上传拿 `fileName` 再填进 `fieldValue`;
  结果每项带 `fileUrl`、`fileType`、`nodeId`。
- **核实不了**:发布对话框里怎么挑节点、能不能改名 / 排序 / 收窄可选值、工作流改了之后应用怎么办、编辑器旁边的
  模型库长什么样 —— 都在登录后的界面里,公开的只有宣传文案(「模型库 2000+」「一键发布为 AI 应用」)。下面的设计
  不依赖这些细节。

## Decision

### 1. 一份「能填的项」,两半共用

插件把今天 `describe` 里推导的那几步收成一个函数 `items(api, object_info)`,交回**这张图全部能填的项**,每项:

| 字段 | 说什么 |
| --- | --- |
| `node`、`input` | 锚点:节点 id + 输入名(图级的项 —— 种子、尺寸、跑几遍 —— 没有节点) |
| `kind` | `text` / `media`(带 `role`:参考图、首帧、蒙版、视频、音频…)/ `model`(带 `folder`)/ `number` / `choice` / `toggle` / `seed` / `size` / `runs` |
| `title`、`schema`、`common` | 人话名字、类型和范围、常用与否 —— 就是今天 `tunable` / `labels.py` 算的那些 |

`describe`(生成目录)、`tooling`(工具入参)、工作台的应用面板都从它出发,不各推各的。

### 2. 应用表单存在工作流文件里,锚在节点上

作者挑出来的那几项写进**这张工作流的 JSON**,和别的 ComfyUI 扩展同一个做法(见上:前端照原样存回):

- 节点上:`properties.mosael = {"expose": {<输入名>: {"label": …, "order": n, "main": true?, "choices": […]?}}, "result": true?}`
  —— 这个输入给用户填、叫什么、排第几、是不是「主提示词」、(可选)只许从这几项里挑;`result` 见 §5。
- 图上:`extra.mosael = {"version": 1, "app": {"title": …, "description": …, "graph_items": {"seed": {…}, "runs": {…}, "size": {…}}}}`。

**为什么存在文件里、不存 Mosael 的库**:标记跟着节点走 —— 复制、改节点号、挪进别的工作流都还在,节点删了标记一起没,
不会留下指着不存在节点的配置;工作流导出、分享、拷到另一台 ComfyUI 时表单跟着走;连同一台 ComfyUI 的每个人看到的是
同一张应用(和 RunningHub 一个作者发布、大家用是同一回事)。每个人自己填过的值照旧存在各自的画板格子、工作流节点里。

**有效性**:插件每次描述时核对每一项 —— 节点还在、还在会跑的那部分图里(`graph.live`)、那个输入还是一个字面量 widget
(没被拉成连线)、`choices` 还在下拉里。对不上的项不进表单,工作流库和工作台里列出来「这几项失效了」,一键去掉。

**参数键不变**:目录里仍是 `<节点 id>.<输入名>`(和今天一样,画板、工作流节点存着的值不用迁);节点号变了,存着的那一格值
对不上就不用(今天就是这样)。

**版本**:`extra.mosael.version` 只认当前这一版。形状要变时,插件随新版本带一个改写那台机器上工作流文件的 op,
宿主在工作流库里列出要升级的几张、确认一次改写(和 ADR 0035 的写操作同一套确认);读的那一侧不留认旧版的分支 ——
没升级的那几张按「没有应用表单」处理并提示升级。

**谁来写**:
- 工作台里画布开着:面板改的是画布上那几个节点的 `properties`(经桥,§3),存盘是 ComfyUI 自己的保存(Ctrl+S,或面板上
  「保存」调前端的 `Comfy.SaveWorkflow` 命令)—— 和用户在 ComfyUI 里改别的东西是同一次保存。
- 画布没开(网页版、AI 工作台里点「以后只要这张」):插件新 op `annotate` —— 读文件,改 `extra.mosael` / 节点的
  `properties.mosael`,**带着读到时的改动时间**写回;那台机器上的文件在这之间被改过就拒绝,说「它刚在 ComfyUI 里改过,
  重新打开再改」。这是 Mosael 第一次覆盖写一张已有的工作流,所以确认框写明改哪台服务器上的哪个文件、只改这几处标记。
- 同一张图画布开着、又有没存的改动时,不走 `annotate`,改在画布上、提醒先保存。

### 3. 和内嵌画布怎么通话:主进程注入写死的脚本(选 A)

| | A. 主进程往内嵌视图注入脚本(用 `window.app`) | B. 插件带一个 ComfyUI 前端扩展(装进 custom_nodes) | C. 改 JSON 再重载 |
| --- | --- | --- | --- |
| 跨前端版本 | 靠 `window.app` 那一套 —— 自定义节点生态都在用;每个调用先探测,缺了只关掉那个面板功能 | 官方扩展钩子最正规;但服务器上的扩展版本和 Mosael 里的插件版本会错开 | 只依赖文件格式,最稳 |
| 安全 | 脚本是宿主写死的(`comfyEditor.ts` 同一条规矩:渲染层只传 JSON 编码的数据),只在视图停在这个连接的来源上时执行 | Mosael 的代码常驻在别人的服务器上,所有用那台 ComfyUI 的浏览器都加载它 | 要覆盖写文件 |
| 局域网 / 远端 | 视图打得开就行,和今天的「在编辑器里打开」一样 | 装节点要过 Manager 的安全等级(ADR 0034:监听 0.0.0.0 的那台会拒),还要重启 | 可以 |
| 能做的事 | 选中、填值、刷新下拉、导出当前图、跑的事件 | 同 A,还能加侧栏 | 看不到选中什么、跑到哪;重载丢掉没存的改动 |

**选 A**,C 的做法只留给画布没开时的 `annotate`(§2)。B 不做:要改用户的 ComfyUI 安装、要重启、版本两头对不齐,
而 A 用的那套名字它自己也得用。

桥的样子:
- 主进程在这个连接的视图里注入一段写死的脚本(和 `comfyEditor.ts` 放在一起),定义一个带版本号的 `window.__mosaelWorkbench`:
  探测能力、读当前选中的节点(类型、widget 名字和值)、把一个值填进某个 widget(先查它在下拉里)、`refreshComboInNodes`、
  导出当前图(界面格式 + `graphToPrompt` 的 API 格式 + 前端的 `clientId`)、是否有没存的改动、执行保存命令;
  订阅前端 `api` 的 `executing` / `executed` / `progress` / `execution_error`,存进一个有上限的队列。
- **只拉不推**:主进程每 300ms 取一次队列和选中状态,页面里没有任何能调到 Mosael 的口子。页面和自定义节点的脚本在同一个
  世界里,所以从页面拿到的一律当**提示**:形状不对的丢掉;定论(这次跑出了什么、哪张来自哪个节点)以插件读的历史为准。
- 新 IPC 通道照 `parseComfyWorkflow` 的规矩:分区由主进程按连接 id 拼,载荷逐项校验,渲染层送不进代码。
- 面板是 Mosael 渲染层自己的 DOM,画在内嵌视图旁边:视图让出右边那一块(`accountViews.ts` 已经有给侧栏、页面列表让位的
  `shellInsetRight` / `setPagesInset`),不往 ComfyUI 的页面里加任何界面。样子:顶栏是连接名、工作流名、有没有没存的改动、
  「保存」「运行」;左边整块是 ComfyUI 的画布;右边一列四个标签 —— 模型库、缺失项、应用、运行与结果 —— 能收起。
- 能力探测失败(前端改名了):那个面板说「这版 ComfyUI 前端不支持 X」,画布照常是一个能用的 ComfyUI。

### 4. 应用表单:每种项怎么进目录

有 `extra.mosael.app` 的工作流,目录里**只有作者挑的那几项**,按 `order` 排,用作者起的名字;没有的,和今天一样全自动
推(那就是「缺省的应用」)。三处界面不认识「应用」,它们读的还是同一个描述符:

| 表单项 | 来自 | 目录里是 |
| --- | --- | --- |
| 主提示词 / 反向提示词 | 标了 `main` 的文字项(同一角色几处,写同一句话,和今天一样) | `prompt` / `negative_prompt`(宿主控件) |
| 别的文字 | 字面量 STRING | `<节点>.<输入>`,`x-multiline` |
| 图 / 视频 / 音频 / 蒙版 | 读素材的节点 | `inputs` 的角色;**每个槽有自己的名字**(见下) |
| 模型 / LoRA | 选模型文件的下拉 | 枚举 + `x-model-folder`(已有,带缩略图);`choices` 收窄可选值 |
| 数字 / 选择 / 开关 | 字面量 INT / FLOAT / COMBO / BOOLEAN | 声明参数 |
| 种子 / 尺寸 / 跑几遍 | 图级的项 | `seed` / `size` / `num_images`(跑几遍,1.12.3) |
| 结果 | 输出节点 | `output_node` 的缺省(§5) |

- **没挑的项照工作流原样跑**:不进表单,也不被写 —— 包括文字:没标 `main` 的提示词格保留工作流里存的那句。插件在有应用
  表单时只认表单里的键,画板格子里存着的旧键不再写进图。
- **宿主要补的一处**:读素材的槽位按顺序带名字。今天目录里一个角色一项(`{role, max, required, label}`),`label` 一个角色
  一个、`descriptor` 也没传下去;改成插件给 `{role, max, labels: [按槽位顺序的名字]}`(作者起的名字,没起就用节点标题),
  描述符多一格 `source_labels`,三处界面的槽位用它当提示。这是通用改动,别的插件也能用。
- 应用的标题、说明换掉模型下拉里那一项的名字和说明;模型 id 仍是文件路径。
- 工具(`tooling`)的入参同样只剩表单那几项 —— 一张工作流的工具和生成说的是同一张表。

### 5. 结果:标出来自哪个节点,「以后只要这张」

- 每份产出带上它来自的节点(插件已经知道,`all_outputs` 里有 `node`):产出的 `parameters` 里多一格 `source_node`,
  宿主照记进生成记录(`output_parameters`)和素材的生成参数;界面按目录里的节点名字标「来自 PreviewImage #17」。不叫
  `output_node`:那是「结果取自」的参数键,记进素材的生成参数后,「用同样的参数再来一次」会被当成选了那一个节点。
- 「以后只要这张」:在那个输出节点上记 `properties.mosael.result = true`、清掉别的节点上的(写法见 §2)。
- 和缺省规则的关系:**有标记就听标记**,「结果取自」的缺省是标了的那几个(选项名「你选的结果(节点名)」),
  `final_outputs` 的猜测只在一个都没标时用;保存节点也能标(两个保存节点只要高清那张)。「结果取自」照旧能每次改。
  缺省结果从「猜一次」变成「猜一次、用户改一次就记住」。

### 6. 面板的数据怎么走

- **模型库**:桥报选中的节点 → 宿主问插件(`model_library` 新 op `node_folders`:节点类型 + 输入名 → 模型目录,
  就是 `labels.py` 的 `model_folder`)→ 面板用已有的模型库数据按目录筛,可再按「和当前大模型同一家族」筛
  (`families.py`)→ 点一个 → 桥把文件名填进那个 widget。缺的模型走已有的下载(`model_download` 任务、三条路);下完
  桥调 `refreshComboInNodes`,新文件出现在下拉里。
- **缺失项**:桥导出画布上**当前**的图(含没存的)→ 插件已有的 `inspect_import`(缺的节点、对应节点包、缺的模型和
  下载地址)→ 一张清单;一键:节点包走 `install_nodes`、模型走下载,装完提示重启 ComfyUI(`reboot`,再确认一次)。
  重启前提醒先保存:ComfyUI 前端会恢复开着的工作流,但这不是我们能担保的事。
- **运行**:面板上的「运行」跑**画布上现在这张**:桥给出 `graphToPrompt` 的 API 图、界面格式和前端的 `clientId` →
  宿主建一个普通的生成任务(模型 = 这张工作流;图放在任务的载荷里,不进生成参数)→ 插件 `generate` 收一个可选的
  `graph`:不从文件读、直接提交,
  `client_id` 用前端的那个(画布上照常亮起正在跑的节点、出预览),`extra_pnginfo.workflow` 带上界面格式(产出拖回 ComfyUI
  有布局)。插件这一侧按历史轮询跟到完成(`follow_poll`),不另开 WebSocket 抢那个 `clientId`(ComfyUI 一个 `clientId`
  只留一条连接,后连的会把画布那条挤掉);面板上的细进度(跑到哪个节点、第几步)直接看桥的事件,任务本身的进度按轮询。
  取消、重启后接着等、用量、素材入库都是生成任务已有的那一套。
- **结果**:这次会话跑的每一次,产出按节点分组、标节点名;点「以后只要这张」。用户按 ComfyUI 自己的「Queue」跑的不是
  Mosael 的任务,面板只读列出来(`/history`),给「收进素材库」(已有的 `import_outputs`)。

### 7. 谁的 ComfyUI、谁的模型、局域网

- 工作台开的是**点它的那个人自己的连接**(钥匙归人,和插件工具同一条):视图分区按连接分,登录、Cookie 互不相干。连接配了
  访问凭据(反向代理后面的 Basic / Bearer)时,主进程只给这个视图、只对这个来源的请求带上它。
- 工作流文件、应用表单、「以后只要这张」都在**那台 ComfyUI 上**:几个人各自连同一台,看到的是同一份(团队共用的应用);
  每个人填过的值在自己的格子、节点里。
- 模型在那台机器上,下载落到那台机器(ADR 0034 的路和提醒不变)。
- 改动那台机器的仍只有用户点的那几下:保存(ComfyUI 自己的,或 `annotate`)、装节点、重启、下载 —— 每次写明哪台服务器。
  插件不多要权限:桥是宿主的代码,只对这个连接的来源动手。
- ComfyUI 的多用户模式(`--multi-user`,userdata 按用户分)这一版不支持:探测到就说明工作台用的是缺省用户。

### 8. 分三刀交付(都在 1.10.0)

1. **应用这一半(不依赖画布,网页版也有)**:`items`;读 `extra.mosael` / `properties.mosael`、有效性检查;工作流库详情里的
   「应用」页 —— 列出全部能填的项,勾选、起名、排序、收窄可选值,右边用 `parameterPanel` 实时预览表单;`annotate`;
   槽位名字(`source_labels`);产出标节点、「以后只要这张」、标记进「结果取自」。
2. **工作台壳 + 模型库面板**:从工作流库、AI 工作台的模型旁「在工作台里打开」全屏打开;内嵌画布 + 右侧停靠面板;
   桥(探测、选中、填值、刷新下拉、导出、脏标记、保存命令);模型库面板筛选、点选、下载;应用面板改在画布上的节点里。
3. **缺失项 + 运行与结果面板**:当前图的缺失项和一键装;用画布上的图跑、前端 `clientId`、取消 / 重启接着等、按节点分组的结果。

**测试**:
- 插件:用脱敏夹具(已有的两遍出图那张,再加一张多读图节点的)测 `items`、应用表单读写、失效项、标记优先于猜测;
  `annotate` 对着假 ComfyUI 测改动时间对不上就拒绝、只改标记;`generate` 收 `graph` / `client_id`。
- 宿主:描述符带 `source_labels`;三处界面的槽位名字、只剩表单那几项(DOM 测试)。
- 桥:脚本对着一个假的 `window.app` 跑(和 `electron/publish/comfyEditor.test.ts` 一样),再用一张模仿前端接口的本地页面
  在真内嵌视图里过一遍探测 / 选中 / 填值 / 导出 / 事件队列。
- 真 ComfyUI:在维护者那台上只读核对探测、选中、填值(不保存)、导出;**只在最后、经维护者同意跑一次**端到端。插件
  README 记下测过的前端版本。

### 9. 模型信息:预览图分档、NSFW 单独管、原链接

维护者:「模型这个预览图开启关闭我希望分多档 还要支持 nsfw 预览开启/关闭」。今天只有一个开关(全部模糊,悬停或点开才看清),
而且模型库里**没有任何 NSFW 标记** —— 分不出哪张该另管。

- **两组设置,都记在这台电脑上**(和今天的开关一样,看场合的事不跟着账号走):**预览图**:清晰 / 轻度模糊 / 重度模糊 / 不显示
  (只画类型图标);**NSFW 预览**:照常 / 模糊 / 不显示 —— 独立生效,比如「预览图清晰 + NSFW 不显示」。悬停、点开单张仍可临时看清。
  工作台的模型库面板、生成表单里带缩略图的模型 / LoRA 选择器、应用表单都用同一套。
- **NSFW 从哪来(四种来源都要,维护者拍板)**,合成一个「是不是 NSFW、凭什么」,界面上悬停看得到依据:
  1. **手动标记**:卡片和详情页「标为 NSFW / 取消」,记在这条连接上,压过下面三种(自动判错了能改);
  2. **元数据推断**:LoRA 训练标签里的成人标签、文件名和标题里的 nsfw 等关键词 —— 不联网、不要额外模型,会漏;
  3. **下载时记下 Civitai 的标记**:经 Mosael 从 Civitai 下的模型,把 Civitai 自己的 NSFW 标记记下来;
  4. **本地识别预览图**:一个几 MB 的小模型在本机看预览图本身,不依赖元数据。识别模型怎么带(随应用打包还是首次用时下载)、
     在主进程还是渲染进程跑、识别结果缓存在哪,开工前补一节。
- **原链接**(维护者:「模型信息那里我希望有对应模型的原链接」):详情页写明这个模型的出处,点开是原站的那一页(Civitai 的模型 /
  版本页、HuggingFace 的仓库或文件页、ModelScope 的模型页)。来源和 NSFW 是同一份数据:经 Mosael 下载的,下载时就记下解析出的那一页
  (今天下载框已经解析出来源,只是没留下);不是经 Mosael 下的,从文件自带的元数据里找(`modelspec`、训练元数据里的地址),都找不到
  就不写 —— 不按文件名去猜一个链接。用户也可以手动填一个。
- **没有预览图的模型,插件自己去取**(维护者:「如果模型本身用户没有下载预览图片 插件也要支持获取预览图片 便于用户预览」)。
  原链接、NSFW、预览图是**同一次查询**的结果:拿模型文件的哈希问 Civitai(`/api/v1/model-versions/by-hash/{sha256}`),一次拿到
  来源页、每张示例图的 `nsfwLevel` 和图本身。
  - **哈希从哪来**:ComfyUI 核心不给文件哈希。装了 ComfyUI-Custom-Scripts(pysssss)时用它的 `/pysssss/metadata/{目录}/{文件}?hash`
    (服务器上算整份文件的 SHA256,并缓存在模型旁),精确对版本;没装时退到「Civitai 上记录的原始文件名精确相等」,标「按文件名匹配」,
    存回 ComfyUI 之前要用户确认。核心 `/view_metadata` 里的 kohya 哈希(`sshs_model_hash`)实测 Civitai 认不出,不用。
  - **先只在 Mosael 里显示**:取到的图缓存在 Mosael 本机(和 ComfyUI 给的预览图同一套缓存、同一套缩略图),模型库里照常显示,
    角上标「来自 Civitai」;挑哪一张跟着 NSFW 那组设置走(缺省等级最低的一张)。这一步不改 ComfyUI 那边任何文件。
  - **存回 ComfyUI**:「存为预览图」和「为缺预览图的模型补图」(批量)把图写到模型旁边 —— 走 pysssss 自己「Use as preview」那条路
    (`/upload/image` 进 temp,再 `/pysssss/save/{目录}/{文件}`)。没有能写的接口时这一项灰掉、说清缺什么。
  - **示例只有视频的,预览就是视频**(维护者:「示例视频的话可以直接下载视频 也要支持预览」):Civitai 上不少视频模型(Wan、
    MiniMax H3、各类视频 LoRA)的示例只有 mp4。缓存一份缩到 512 宽的转码视频(`transcode=true,width=512`),卡片上显示首帧、
    悬停时静音循环播放,详情页可以播放。存回 ComfyUI 时**直接存这段视频**(`<模型名>.mp4`,维护者:「这个不要用帧了吧 直接用视频当预览就好」),
    不另截首帧图 —— Mosael 认这个视频;代价是 ComfyUI 自带的模型列表和 pysssss 只认图,在那边看不到这类模型的预览。分档与 NSFW
    那组设置对视频同样生效(模糊 / 不显示,不自动播放)。
  - 2026-10-05 在维护者那台 ComfyUI 上手动跑过一遍这套流程(约 115 个缺图的模型):按 SHA256 对得上的补上了 512 宽的图;
    文件名带 `[ ]` 的,图写进去了但 ComfyUI 的预览接口按通配符找不到它 —— 这是 ComfyUI 那边的限制,Mosael 取图时要绕开
    (直接按文件名读,或在 Mosael 的缓存里认这张图)。
- 存放:手动标记和 Civitai 标记跟着模型文件走(和 §2 一样,优先写在 ComfyUI 那边能留住的地方;写不了的记在 Mosael 库里按
  (连接, 文件)存),推断和识别的结果只是缓存,随时可重算。

#### 本地识别怎么带(2026-10-06,第三刀开工前补)

第四种来源「本地看预览图本身」要一个识别模型。开工前查了几个小的、可商用的 NSFW 图片分类模型,许可都按仓库里的 LICENSE
文件或 HuggingFace 模型卡核对过(2026-10-06):

| 候选 | 许可 | 多大 | 跑起来要什么 | 看法 |
| --- | --- | --- | --- | --- |
| NudeNet v3 | **AGPL-3.0** | 几十 MB(ONNX) | onnxruntime | 不用:AGPL 会牵连随应用发的代码 |
| opennsfw2 | 代码 MIT;权重是 Yahoo open_nsfw 的移植,BSD-2-Clause | 约 24 MB | TensorFlow / Keras(几百 MB) | 2016 年按照片训的,对画出来的、AI 出的图不熟;运行时太重 |
| GantMan nsfw_model | MIT | 约 17 MB(MobileNetV2) | Keras / TF.js | 分了 drawings / hentai 两类,但运行时同样是 TensorFlow 一家 |
| Falconsai/nsfw_image_detection | Apache-2.0 | 343 MB(ViT-base) | transformers + torch | 太大 |
| AdamCodd/vit-base-nsfw-detector | Apache-2.0 | 88 MB(int8 ONNX)/ 344 MB | onnxruntime | 还是 ViT-base |
| **Marqo/nsfw-image-detection-384** | **Apache-2.0** | **22.4 MB**(safetensors) | timm 的 ViT-tiny(570 万参数、12 层、192 宽、3 个头,输入 384) | 训练集有照片、画、Rule 34、AI 出的图,正合 ComfyUI 模型预览图;模型卡自报准确率 98.56%,比上面两个 ViT-base 都高 |

**选 Marqo/nsfw-image-detection-384**,定下这几条:

- **怎么带**:不进安装包。第一次用时下载那一个 22.4 MB 的权重文件,地址钉死在 HuggingFace 的一个版本上
  (`0c26ec22111b83f106d72a55f611ec35962bcb65`),下完按固定的 SHA-256(`6bf2e0f6…eeefce`)校验,对不上就拒装 ——
  和降噪引擎 DeepFilterNet 同一套(`ai/runtime/install_state` 记进度、`download_to_path` 下载、校验通过才挪到正式位置)。
  落在 `<数据目录>/nsfw-classifier/`,卸载时一个目录删掉。入口在模型库「预览图」设置里一行「本地识别」:没下就写多大、
  点了才下;下好之后才开始识别。
- **在哪跑**:后端。**不另装推理运行时**:ViT-tiny 一次前向就是十二层 192 宽的注意力,用后端本来就带着的 numpy 写一份前向
  (照 timm 的 VisionTransformer:pre-norm、精确 GELU、cls token、LayerNorm eps 1e-6),Pillow 做预处理(短边缩到 384、
  居中裁 384,均值 / 方差 0.5)。不要 torch、onnxruntime,不起 venv。动手前对着 timm 核对过:同一张图两边的 logits 差在
  1e-5 以内;测试用一份随机小权重的夹具锁住这份前向,数是 timm 算的。
- **性能**:识别宿主已经缩好的缩略图(长边 512,见 ADR 0034 §1),不碰原图;一张 0.1–0.3 秒(M 系列 CPU)。结果按**预览图
  内容的 SHA-256** 记在磁盘缓存里 —— 同一张图换了名字、换了连接都不再算;全进程同时只识别一张,在后台线程里跑,
  列模型库不等它:列出来时缓存里有结果就带上,没有的排队去算,下次列出就有。视频预览识别它的首帧(卡片上那张)。
- **隐私**:图、模型、结果都不出这台电脑;不联网,除了第一次下那个权重文件。
- **只是提示**:识别结果是第四种来源,排在手动标记之下(手动标了就听手动的,两头都能改);阈值取模型自己的 0.5,悬停时
  写「本机识别:NSFW 的可能 87%」。识别不出(图坏了、权重没下)就不说话,不当成「安全」。

#### 第三刀做成了什么(2026-10-06,实现记录)

照上面做了,几处落地时定下的、和上面写法不同的:

- **存放**:ComfyUI 那边没有能写「这个文件是不是 NSFW」的地方(pysssss 的写回只写预览图),所以**手动标记记在 Mosael 库里**
  (新表 `model_file_marks`,按(连接, 目录, 文件名);连接删掉随之删);Civitai 查到的(版本、来源页、NSFW、示例图、底模)和
  经 Mosael 下载时记下的来源记在**插件的持久目录**里(按服务器 + 目录 + 名字 + 大小,文件换了不算数);推断、识别、宿主取回的
  示例图和视频都只是缓存。
- **合成**:手动标了就听手动的;没标时 Civitai、本机识别、元数据任一种说是就算是 —— 这个判断是拿来「当众打开时先藏起来」的,
  宁可多藏一张。显示的是 Civitai 的示例图时,那一张自己的分级(`nsfwLevel` ≥ 4 算)代替模型那一条。
- **挑哪一张**:「NSFW 预览」是照常时要作者排在最前的那张,别的要分级最低的;有图就在图里挑,示例只有视频的才用视频。
- **在 Civitai 上找**是一个后台任务(任务中心看得到、能取消):单个文件「在 Civitai 上找」/「从 Civitai 取预览图」,或「为缺预览图
  的模型补图」(先确认);补图时那台服务器上有预览图的跳过,按哈希对上的存回,按文件名对上的不替你存、做完列出来。查不到也记一笔,
  一阵子内不再让那台机器算哈希。存为预览图前先确认(写明哪台服务器、哪个目录;按文件名对上的多说一句);那台服务器上已经有预览图
  的不写(pysssss 那条路会覆盖同名文件);写回后列表马上标成「那台服务器上的」。
- **Civitai 的底模细分家族**(新的来源 `civitai`):元数据、权重只看得出 SDXL / Wan / Flux 这一层时换成 Civitai 说的那一支;
  元数据、权重已经认出一支的不改。
- **视频**:宿主取回后用 ffmpeg 转成宽不超过 512、静音、最长 10 秒的 mp4 缓存(Civitai 没转好时给的是原片,十来 MB、带声音);
  卡片是首帧,悬停静音循环播,模糊 / 不显示时不播;详情能播;看大图按视频放。模型旁边的 `.mp4` / `.webm`、文件名带 `[ ]` 的那几种
  图,按名字经 `/pysssss/view/` 直接读。
- **看大图**(共用灯箱):点的是看得清的那张时,当前筛出来的、看得清的成组翻;点的是模糊着、不显示的那张时只开它 —— 翻到别的
  就等于没经同意替人把它们都看清了。工作台的模型库面板同一条。
- **悬停 / 聚焦看清**只认键盘聚焦(`:focus-visible`):右键菜单关上会把焦点还给卡片,刚标成 NSFW 的那张不该因此露着。
- **右键菜单**(维护者 2026-10-06 追加):网格卡片、列表行、表格行右键,悬停 / 聚焦时的「⋯」,Shift+F10 / 菜单键,同一份:
  打开详情、用它生成…、复制文件名 / 完整路径、在用的工作流、打开原链接、在 Civitai 上找、存为预览图、查看大图、标为 / 不是 NSFW、
  改回自动判断;缺失页能下载同名缺失的。点不了的写为什么;不提供删除那台服务器上的模型文件。
- **本机识别**按「本地识别怎么带」那一节做:识别的是宿主缩好的缩略图,结果按缩略图内容的 SHA-256 记在
  `<数据目录>/nsfw-classifier/scores-<版本>.json`;缩略图新缩出来就排进队,列的时候还没结果的也排进去;「预览图」设置里那一行
  盯着进度,下好了、排着的认完了让模型库重新列一遍。下载权重只给部署管理员。
- 旧的「模糊预览图」开关一次性迁移(开 → 预览图重度模糊,关 → 清晰),旧键删掉,不留兼容分支。

**这一版没做**:手动填原链接(上面说「用户也可以手动填一个」)。应用表单的模型下拉就是生成表单里那个,照这两组设置走。

**核对**(2026-10-06,隔离环境):维护者那台 ComfyUI 只发 GET(哈希只算了 6 个文件):一个只有预览视频的 Wan 2.2 LoRA 按 SHA256
对上 Civitai 版本页,家族从 Wan 细分到 Wan 2.2,Civitai 标着 NSFW,旁边的 `.mp4` 转成 512 宽、卡片是首帧;两个文件名带 `[ ]` 的
LoRA 读到了旁边的图。那台服务器上没有「缺预览图又能在 Civitai 对上」的文件了(维护者已经补过),Civitai 示例图的显示、存为预览图、
视频示例在扩展过的演示 ComfyUI(`website/scripts/demo-comfyui.py`,两个模型的哈希是真的 Civitai 版本)上走通,真问 Civitai。
本机识别经界面真下了权重(校验通过),对那台服务器上已经缩好的 23 张缩略图识别:12 张过 0.5,按哈希对上 Civitai 的那个两边都说是。

## 这一版不做

- 自己画画布、在 Mosael 里重排节点和连线。
- 子图里面的节点暴露成表单项(子图节点上提升出来的 widget 可以)。
- 应用的封面、分享链接、市场;应用的多个版本。
- ComfyUI 多用户模式;网页版的画布那一半(网页版只有应用这一半,画布仍是新标签页打开 ComfyUI)。

## 已拍板(2026-10-05)

七项都选 A:应用表单存在工作流文件里(节点 `properties` + `extra`);主进程往内嵌画布注入写死的脚本;有应用表单时没挑的项不出现、
照工作流原样跑;工作台的「运行」跑画布上现在这张(含没存的改动);「以后只要这张」记在工作流里;允许 `annotate` 覆盖写已有工作流
(只改 `mosael` 那几处标记、核对改动时间、每次确认);入口是工作流库详情和 AI 工作台模型旁的「在工作台里打开」,全屏。

## Consequences

- 「能填的项」从各处各推一遍变成一份(`items`),应用表单是它上面的一层选择;三处界面一行不认识「应用」,只是描述符变短了。
- Mosael 开始往用户的工作流文件里写自己的标记(`mosael` 这个键),并且第一次会覆盖写一张已有的工作流(只在 `annotate`)。
- 内嵌画布从「打开一下」变成长时间协作的界面,依赖 ComfyUI 前端的 `window.app` 那一套;探测失败时退回成普通的 ComfyUI,
  不会更糟。前端大改时,桥是唯一要跟着改的地方。
- 经工作台跑出来的图带上了界面格式的工作流,拖回 ComfyUI 有布局。

# ADR 0042:工作台里的智能体 —— 在 ComfyUI 画布旁边让 Mosael 的智能体搭图、改图、找问题

## Status

Accepted — 2026-10-07。下面七条由维护者于 2026-10-07 拍板:第 6 条改成**子图也能改**,其余照推荐;另加两样 —— 智能体能拿到
这台 ComfyUI 装了哪些自定义节点包,能**搜索、分析、下载安装**节点包(§7)。分三步做,都进 1.9.4。第一步(读和诊断)已实现,见文末的实现记录。

## Context

维护者(2026-10-06,发 1.9.3 时):「在 ComfyUI 工作台内,用户可以通过 Mosael 的智能体对工作流进行编辑 —— 比如创建一个
Qwen-Image 2.1 编辑图片的工作流;或者提问工作流存在的问题。」

### 现在有什么

- **工作台**(ADR 0038):桌面版全屏,左边是 ComfyUI 自己的画布(内嵌视图),右边一列四个页签 —— 模型库、缺失项、应用、运行与结果。
- **工作台的桥**(`electron/publish/comfyWorkbench.ts`,`WORKBENCH_VERSION = 3`):主进程往页面里注入写死的脚本,挂一个冻结的
  `window.__mosaelWorkbench`。宿主能调的只有七样 —— `setWidget`、`refreshCombos`、`export`、`save`、`setMarks`、`locate`、
  `runControls`;状态靠主进程每 300 ms `poll` 一次拉回来(工作流名、改没改、`revision`、选中的节点、运行事件),页面从不主动推。
  **能改的只有控件的值和标记,不能加删节点、不能连线。** 用到的前端接口:`app.graphToPrompt`、`app.loadGraphData`(只在打开一张
  存着的工作流时)、`extensionManager.workflow.activeWorkflow.changeTracker`(`checkState` 记一步撤销)、`extensionManager.command.execute`
  (`Comfy.SaveWorkflow`、`Comfy.NewBlankWorkflow`)、`canvas.selectItems` / `centerOnNode`。
- **智能体**:pi 跑在 sidecar 里,工具全在 `backend/mcp_server.py` 一张表上(105 个,`reads` / `writes` / `confirms` 三种),要人点头的走
  确认卡。**没有一个工具碰得到工作台**;也没有「在界面里执行、把结果交回智能体」的工具。最接近的是浏览器那一组(`browser_*`):后端
  排一条动作,Electron 主进程的 worker(`electron/publish/browserWorker.ts`)领走、在内嵌页面里执行、把结果报回去 —— 后端 → 主进程 →
  页面的来回已经有现成的样子。
- **对话面板**:`frontend/src/features/agent/CanvasAgentChat.tsx` 一个面板给工作流、画板、剪辑、3D 场景、笔记共用 —— 用工作区当前的会话,
  每条消息带一段看不见的页面上下文(`contextLine`,上限 4000 字),输入框里打「/」点技能。
- **ComfyUI 插件**会的:`convert.py`(界面格式 → API 格式,和前端 `graphToPrompt` 同一套规矩)、`workflow_import.py`(缺哪些节点类型、
  哪些节点包能补、哪些模型不在下拉里;API 格式 → 界面格式并自动排版)、`graph.py`(结果节点、执行报错拆到节点)。每个操作现取
  `/object_info`,不缓存。**没有一处读 ComfyUI 的官方模板**,也没有「连线类型对不对、必填的有没有连」这类检查 —— 那是交给 `/prompt`
  报错时才知道。
- **技能**(ADR 0040):内置「搭工作流」讲的是 **Mosael 自己的工作流**(`edit_workflow` 那一套),不是 ComfyUI。插件能带技能,ComfyUI 插件还没带。
- **运行报错**:工作台「运行」的报错落在任务的 `job.error`(一段字,带 `#节点号`),智能体用 `get_job` 读得到;桥收到的
  `execution_error` 事件只在界面里用来清进度。

### 外部事实(2026-10-07 查证,ComfyUI 0.39.0 / 前端 1.53.10 / 模板包 0.11.76)

- **官方模板随 ComfyUI 装**(pip 包 `comfyui_workflow_templates*`),服务器在 `/templates/{路径}` 上提供:`index.json`(按类别分组,
  每张写着标题、说明、`models`、`tags`、`minComfyUIVersion`、模型总大小 `size`、输入输出 `io`)、`index.zh.json` 等各语言版、
  **`index.mcp.json`(给智能体读的那一份:任务、模型、新旧、推荐程度、输入输出一句话)**,和每一张 `<名字>.json`(界面格式,能直接
  载进画布)。0.39 的官方索引里有 **592 张**,其中就有维护者举的例子 `image_qwen_image_2_1_image_edit`(「Qwen Image 2.1: Image Edit」,
  要 0.37.0 起,模型合计约 26.7 GB)。节点包自带的模板在 `/workflow_templates`(按包列)、文件在 `/api/workflow_templates/<包>/…`。
  维护者那台 Windows(2026-10-07 已升到 0.39.0、模板包 0.11.76)只读核实过:`index.mcp.json`、`index.zh.json`、那张 Qwen-Image 2.1
  编辑模板、`/workflow_templates`(10 个节点包带了模板,Impact Pack、KJNodes、WanVideoWrapper、IPAdapter plus 等)都在。
- **前端能整图载入**:`app.loadGraphData(图, …)`;**能新开一张空白画布**:命令 `Comfy.NewBlankWorkflow`;**能记一步撤销**:
  `changeTracker.checkState()`(Ctrl+Z 退回到上一次记的状态);节点和连线由 LiteGraph 管(`window.LiteGraph`、`LiteGraph.createNode`、
  `graph.add`、`node.connect`)。这些在 1.53.10 的前端里都在,具体怎么组合成「一批改动只占一步撤销」要在测试场上实测。

## Decision

### 已拍板(维护者,2026-10-07)

| # | 问题 | 选项 | 定了 |
| --- | --- | --- | --- |
| 1 | 对话放哪 | A:工作台右栏第五个页签「助手」;B:浮在画布上的对话窗;C:回 Mosael 主界面的 AI 工作台说 | **A** —— 和另外四个页签同一列,画布照样整块露着 |
| 2 | 「新建一张」从哪来 | A:**官方模板优先** —— 按任务和模型找模板,照这台机器上有的模型改好,在新标签页打开;找不到合适的才从节点搭;B:总是从节点搭 | **A** —— 模板是 ComfyUI 官方调好的图,比模型现搭可靠得多 |
| 3 | 改当前这张要不要先点头 | A:先在对话里摆出改动清单(加了哪几个节点、连了哪几根线、改了哪几格),点「应用」才改到画布上,应用后一次 Ctrl+Z 就退回;B:直接改,靠 Ctrl+Z | **A** —— 当前这张可能是你调了很久的;新建是开新标签页、不动现有的,不用点头 |
| 4 | 缺的模型和节点 | A:智能体能发起下载 / 安装,走确认卡(写明多大、装到哪台机器);B:只列出来,你去「缺失项」点 | **A** —— 和现在缺失项的下载、装节点同一套,只是由它起头 |
| 5 | 试跑 | A:智能体能发起一次试跑(确认卡),跑完读报错接着改;B:只让你自己点「运行」 | **A** —— 「跑一下 → 看报错 → 改」是它最有用的地方;本机 GPU 不花钱,远程那台用的是别人的显卡,所以要点头 |
| 6 | 子图 | A:只改根图,子图里的东西能读、能诊断、不能改;B:子图也改 | **B**(维护者改的;原推荐 A)—— 子图里面也能加删节点、连线、改值,见 §6 |
| 7 | 网页版 | A:只做桌面版工作台(要画布那座桥);B:网页版也做,改的是存着的工作流文件 | **A** |

另外两件不用拍板、照现有规矩:**用哪个模型**是你的默认对话模型(页签里能换,同 AI 工作台);**都不自动保存**,存盘还是你点
ComfyUI 的保存或工作台顶栏的「保存」。

### 1. 智能体怎么碰到画布:走「后端 → 主进程 → 页面」那条现成的路

画布的桥活在 Electron 主进程里(`WorkbenchSessions`),后端和 sidecar 够不着。照浏览器工具的样子:智能体调一个画布工具 → 后端排一条
「工作台动作」→ 主进程的 worker 领走,经 `WorkbenchSessions.call` 在那个连接的工作台页面里执行 → 把结果报回后端 → 交还给智能体。
不另造「在渲染层里执行的工具」:渲染层可能正停在别的页面上,而主进程才是一直握着那个内嵌视图的一方。工作台没开着时,画布工具
直接说「先在工作台里打开这台 ComfyUI」。

### 2. 桥多三样(`WORKBENCH_VERSION` 升到 4)

- **`readGraph`**:当前这张的界面格式整图(子图的定义在 `definitions.subgraphs` 里,一并读出)(`graphToPrompt().workflow`)加选中的节点、改没改。智能体读到的是插件压缩过的一份摘要
  (节点号、类型、标题、控件的值、谁连着谁),不是几百 KB 的原文。
- **`applyOps`**:一批改动(每一条可以带 `graph`:改哪一层,缺省是根图,子图按 §6 的写法指)—— `add_node`(类型、临时名、控件值、放在谁旁边)、`remove_node`、`connect` / `disconnect`(按输入输出的
  **名字**,不按槽位号)、`set_widget`、`set_title`、`bypass` / `mute`。整批要么全成、要么一样不改;成了只记**一步**撤销(`checkState`);
  新节点按连着的节点就近排开,不叠在一起。每批改动先经插件对着 `/object_info` 校验(类型在不在、输入输出名字对不对、类型配不配、
  下拉值在不在列表里),不过就不往页面里送。
- **`openWorkflow`**:新开一张空白画布(`Comfy.NewBlankWorkflow`),把一整张界面格式的图载进去(`loadGraphData`),起个名字,**不存盘**。

这三样和现有七样一样是写死的脚本、带版本号,这版前端缺哪个接口就在能力里报「不支持」,工作台照常能用。

### 3. 插件多几个只读的操作(ComfyUI 的知识放插件里)

- **`templates`**:读 `/templates/index.mcp.json`(和界面语言那份 `index.<语言>.json` 合起来),按任务、模型、关键词找;每条带它要的
  模型、合计大小、最低 ComfyUI 版本,以及**这台机器上已经有哪几个、缺哪几个**(对着模型库)。节点包自带的模板(`/workflow_templates`)一并列。
- **`template`**:取一张模板的整图,交给智能体之前先按这台机器改好能改的(同名模型在别的目录、同底模的另一个文件)。
- **`node_types`**:在 `/object_info` 里按名字、类别、说明找节点类型,回它的输入(类型、必填、下拉选项、默认值)和输出。缓存一份,
  `/object_info` 变了(装了节点包、重启)才重取。
- **`check_graph`**:**「这个工作流有什么问题」靠它**。一份图进去,出一张按节点列的问题单,每条带严重程度、原因、改法:
  - 缺的节点类型、缺的模型(就是缺失项现在那一套);
  - 连线类型对不上、必填的输入没连、下拉值不在列表里、数值超出范围;
  - 加载节点选的底模和 LoRA / ControlNet 的底模对不上(用模型库认出来的家族);
  - 尺寸不是 8 / 16 的倍数、批次和显存明显不配这类常见坑;
  - 有上一次运行的报错时,把 `job.error` 拆到具体节点、说人话(`graph.py` 已经会拆)。

### 4. 智能体的工具(都只在工作台的会话里给)

| 工具 | 做什么 | 要不要点头 |
| --- | --- | --- |
| `comfy_canvas_read` | 读当前这张的摘要和选中的节点 | 不用 |
| `comfy_node_types` / `comfy_templates` / `comfy_template` | 查节点、找模板、取模板 | 不用 |
| `comfy_check` | 诊断当前这张(或一张提议中的图) | 不用 |
| `comfy_canvas_edit` | 把一批改动应用到当前这张 | **要**(拍板 3):卡上是改动清单,点「应用」才改 |
| `comfy_canvas_new` | 在新标签页打开一张整图 | 不用(不动现有的,不存盘) |
| `comfy_locate` | 在画布上选中、居中某个节点(指给人看),子图里的会先打开那一层 | 不用 |
| `comfy_node_packs` | 这台 ComfyUI 装了哪些节点包、各什么版本、开没开、各提供哪些节点 | 不用 |
| `comfy_node_pack_search` | 按名字、用途或「缺的这个节点类型」找节点包 | 不用 |
| `comfy_node_pack_info` | 分析一个节点包(§7) | 不用 |
| `comfy_node_pack_install` | 装一个节点包,装完重启那台 ComfyUI | **要**(拍板 4):卡上写分析结果和要重启 |
| 下载模型、装节点包 | 现有的下载 / 装节点那一套,由它起头 | **要**(拍板 4) |
| 试跑 | 现有的工作台「运行」,跑完把结果和报错交回来 | **要**(拍板 5) |

`comfy_canvas_edit` 应用前再跑一次 `check_graph`,改完的图要是比改之前多出问题就不交,把问题说给智能体让它重改。

### 5. 「助手」页签

- 就是 `CanvasAgentChat` 那个面板放进工作台右栏(拍板 1),上下文写这台 ComfyUI、版本、当前这张的名字和路径、改没改、选中了谁、上次运行
  有没有报错 —— 不把整张图塞进上下文,要看时它调 `comfy_canvas_read`。
- 诊断结果每条带「定位」(选中那个节点)和「照这个改」(转成一次 `comfy_canvas_edit` 的提议);改动清单里的每个节点也能点了定位。
- 新建完给一句「在新标签页里打开了『…』,还缺这几个模型(合计 xx GB)」,带「去下载」。

### 6. 子图怎么改(拍板 6)

- **改的是定义**:ComfyUI 里一个子图是一份定义(`definitions.subgraphs` 里的一项)加若干个用它的节点。往子图里加删节点、连线、改控件,
  改的是那份定义 —— **这张图里所有用它的地方一起变**。改动清单上写明「子图『…』在这张图里用了 N 处,都会变」。
- **怎么指哪一层**:`graph` 写从根图往里走的节点号路径(`["12"]` 是根图 12 号节点那个子图里面,`["12", "5"]` 再往里一层),
  或者直接写子图定义的 id;两种都转成定义 id 再改,同一批里可以改好几层。
- **子图的边界**:连到子图自己的输入 / 输出用 `@in.<名字>` / `@out.<名字>`;`add_subgraph_input` / `add_subgraph_output` /
  `remove_subgraph_io` 加删边界上的口,外面用它的节点跟着多出 / 少掉那个口(连着的线一起断,清单上写明)。
- **提升出来的控件**(子图里面的值提到外面那个节点上):值改在**外面那个节点**上(`set_widget` 指外面的节点),不改定义;
  要不要把一个控件提升出来 / 收回去,是 `promote_widget` / `unpromote_widget`。
- **打包和拆开**:`to_subgraph`(把几个节点打包成一个子图)、`unpack_subgraph`(把一个子图节点拆回原样),这版前端有对应命令时才给,
  没有就在能力里报不支持。
- 校验同根图:子图里面的连线类型、必填、下拉值一样先对 `/object_info` 查过才落;一批跨几层的改动仍只占一步撤销。
- 诊断(`check_graph`)本来就展开子图查,报出来的问题带「在子图『…』里」,「定位」会先打开那一层。

### 7. 自定义节点包:列出、搜索、分析、安装(维护者加的)

**现有的**(2026-10-07 对维护者那台 Manager V4.2.1 只读核实):`GET /v2/customnode/installed`(装了哪些包:注册表 id、版本、
开没开)、`GET /v2/customnode/getmappings`(每个包提供哪些节点类型,约 1.5 MB);装包走 `/v2/manager/queue/task`(插件已有
`install_nodes`,工作流库补缺节点就用它)。V4 没有 `getlist` 了(404)—— 搜包改查 **Comfy 官方注册表**(`api.comfy.org`,公开、
只读,核实过):`/nodes/search?search=…`(下载量、GitHub 星数、发布者、许可证、最新版本)、`/nodes/<id>`、`/nodes/<id>/versions`
(每个版本带 `status`:`Active` / `Flagged` / `Banned`、`deprecated`、`dependencies`、支持的系统 / 加速 / ComfyUI 版本)——
例如 rgthree-comfy 最新那一版此刻就是 `NodeVersionStatusFlagged`。

- **`comfy_node_packs`**:列出装了的包(名字、版本、开没开、来自注册表还是 git 地址)和各自提供的节点类型;当前这张图用到的节点各来自哪个包。
- **`comfy_node_pack_search`**:按关键词、用途,或者「这几个节点类型缺了,谁提供」(先查 getmappings,再查注册表)找包,按下载量、
  星数、最近更新排,标出已经装了的。
- **`comfy_node_pack_info`(分析)**:装之前看清楚 ——
  - 注册表里的状态:这一版是不是被标记(`Flagged`)或封禁(`Banned`)、是不是弃用;发布者、许可证、下载量、星数、最近一次发版;
  - 它提供的节点,能补上当前这张图缺的哪几个;
  - 依赖:`dependencies` 里的 pip 包,**会不会动到 torch / torchvision / xformers 这类核心包**(动到就标高风险:可能把这台机器的
    PyTorch 换掉);
  - 和这台机器合不合:支持的系统、加速(CUDA / MPS)、要的 ComfyUI 最低版本;
  - 已经装了的话:装的是哪一版、新版改了什么(注册表的 changelog)。
- **`comfy_node_pack_install`(下载安装)**:只装**注册表里的、状态正常的版本**(`Flagged` / `Banned` 不装,说明原因);git 地址的包
  智能体不发起(Manager 的安全档本来也拦,要装请人在 Manager 里自己装)。确认卡上是分析的要点(谁发的、多少人用、依赖风险、要不要
  重启);装完重启那台 ComfyUI —— 本机服务的走宿主重启(ADR 0041),远程那台走 Manager 的重启;重启完对 `/object_info` 重取,
  缺失项和诊断跟着刷新。
- 这一版不做:卸载、停用、更新已装的包(要的话以后加,同样走确认卡)。

### 8. 技能随 ComfyUI 插件带

一份 `skills/comfyui-workflows/SKILL.md` 放进 ComfyUI 插件(ADR 0040 §9 插件带技能):先找模板、再照这台机器的模型改、改之前先读图、
每次改完先 `comfy_check`、缺东西先说大小、不要自己存盘、子图只读……智能体在工作台里用到时才读。ComfyUI 的做法跟着插件走,宿主里不写。

### 9. 分三步(都在 1.9.4)

1. **读和诊断**:「助手」页签、`readGraph`(含子图定义)、`node_types` / `templates` / `template` / `check_graph`、诊断的「定位」;
   节点包的列出、搜索、分析(§7);技能。
2. **改和新建**:`applyOps`(一批一步撤销,根图和子图,§6)、`openWorkflow`、改动清单确认卡与「应用」、「照这个改」。
3. **补全和试跑**:由智能体起头的下载模型、装节点包(§7)、试跑(确认卡),跑完读报错接着改。

**测试**:
- 桥的三样新操作(含子图:改定义、边界口、提升控件)对着一个假的 `window.app` / LiteGraph 跑(和 `comfyEditor.test.ts` 一样),再在测试场那台真 ComfyUI 0.39 上实测:
  一批改动只占一步撤销、新标签页不存盘、校验不过的改动一样都不落;维护者那台 0.38 能连上时补一遍。
- 插件的模板、节点、诊断对着测试场的 `/object_info` 和模板包录的夹具测;诊断用几张故意弄坏的图(连错类型、缺必填、底模不配、尺寸不对)。
- 端到端用真模型跑两段对话(订阅的 Kimi,不花钱):「建一个 Qwen-Image 2.1 编辑图片的工作流」(应当从官方模板来、说清缺哪些模型和多大)、
  「这个工作流有什么问题」(对着一张坏图)。

## 这一版不做

- 网页版(拍板 7)。
- 卸载、停用、更新节点包;装 git 地址的节点包。
- 智能体替你存盘、覆盖已有的工作流文件。
- 自动下载模型、自动装节点、自动跑(都要点头)。
- 把画布的改动实时同步给同时开着这张图的另一个人(ComfyUI 自己也不做)。

## Consequences

- 工作台从「人改、Mosael 帮着看」变成「能让智能体动手」:最常见的「我想要一个 X 的工作流」先落到官方模板上,而不是让模型现编一张。
- 桥第一次能改图的结构,改动范围因此变大 —— 所以一批一步撤销、先校验再落、改当前这张要点头,三道一起守着。
- ComfyUI 插件多了模板、节点目录、诊断三样,这些对工作台之外也有用(以后导入工作流、AI 工作台挑工作流时都能用上诊断)。
- `/object_info` 第一次有了缓存,插件要在「装了节点包、重启了」时让它失效。

## 第一步做成了什么(2026-10-07,实现记录)

**读和诊断**全部落地;改、新建、下载、装、试跑留给第二、三步。

- **画布那条路**(§1):复用浏览器动作那一套,不另造。工具在这个工作区对这个连接开一个会话类型为 `workbench` 的浏览器会话(分区
  `persist:pool-comfyui-<连接>`,和工作台视图同一个),排一条 `workbench` 动作;桌面端的浏览器执行器认出会话类型,**不开视图、不挂面板**,
  把调用先经渲染层那个口子同一个解析器(`parseComfyWorkbenchCall`)查过,交给 `publishWorker` 那个连接开着的工作台会话,桥的回答原样
  报回。租约、排队 15 秒、运行 75 秒、执行器掉线、空闲收回(`close` 对工作台会话什么都不拆)都是那一套。工作台没开着(桥说
  `closed` / `missing` / `elsewhere` / `notReady`)、执行器不在(网页版)都说「先在工作台里打开这台 ComfyUI」。实测一次读画布约 1 秒,
  大头是执行器认领的轮询间隔(1.2 秒)。**局限**:同一个账号开着两台桌面端时,谁先领到谁做 —— 领到的那台没开着工作台就说没开着。
- **桥第 4 版**(§2 的第一样):`readGraph` 交回 `graphToPrompt().workflow`(含 `definitions.subgraphs`)、选中的节点、改没改、画布停在
  哪一层、开着哪一张,和导出同一个上限、同一套规整;`locate` 认从根图往里走的路径(`12:5`,最多 16 层),先回根图再一层层打开子图;
  轮询多报那台 ComfyUI 和它前端的版本(注入时问一次 `/system_stats`,只收像版本号的)。
- **插件**(§3、§7):八个只读 op 挂在工作流库那个工具上(`canvas_summary`、`check_graph`、`templates`、`template`、`node_types`、
  `node_packs`、`node_pack_search`、`node_pack_info`),插件 1.17.0,多申报 `network:comfy-registry`。节点写法全程是 API 图的
  「外层:里层」(`12:5`),摘要、问题单、定位、选中都用它。
  - `/object_info`:诊断、改模板只按图里用到的类逐个问 `/object_info/<类>`(维护者那台整份 5.9 MB、十几秒,单个类 0.07 秒);按名字找
    节点类型要整份,**只在 `node_catalog.catalog` 一处取**,`HEAD /object_info` 的长度当指纹,变了才重取。
  - 模板目录(`index.mcp.json` + 界面语言那份)按 `installed_templates_version` 和语言缓存;改模板认「同一个文件在别的子目录」
    「同一个模型的另一种精度」(维护者那台上 `qwen_image_2.1_int8_convrot` 换成了 `qwen_image_2.1_bf16`),缺的用 HEAD 问大小。
  - 注册表经宿主给的出网代理;大小写不对的包 id 注册表回 302,跟过去。
- **工具**(§4 里只读的那九个):`comfy_canvas_read`(交插件压的摘要,不交原文)、`comfy_locate`、`comfy_check`(给了任务号就把那次的
  报错拆到节点)、`comfy_templates`、`comfy_template`(整图不交)、`comfy_node_types`、`comfy_node_packs`、`comfy_node_pack_search`、
  `comfy_node_pack_info`。连接只认调用的人自己接的,只接了一台可以不说是哪一台。
  **和 §4「只在工作台的会话里给」不同**:智能体的会话池是共用的(工作台的「助手」、AI Studio、免提浮标是同一批会话),认不出哪一轮
  在工作台里,所以九个工具在所有会话里都给 —— 只问插件的在哪都能用,碰画布的两件在工作台没开着时说清楚。只按「这个人接了
  ComfyUI」收窄:工具声明 `needs="workflow_library"`,没接的人每一轮不发这九个的定义(工具定义每轮重发,本机模型的回退窗口里
  有预算,见 test_tool_definitions_budget);接了的人多约 1.6k token(说明已经写紧,详细的做法在技能里)。
- **「助手」页签**(§5):共用的 `CanvasAgentChat` 停靠在列里(不浮、不关);页面上下文发送那一刻才取:连接 id 和名字、ComfyUI 和前端
  的版本、开着哪一张(名字、路径)、改没改、选中了谁、上次运行有没有报错(工作台里跑的带任务号;在 ComfyUI 里点的看画布的事件,之后又
  跑成了就不提),不放整张图。回复里的 `#12`、`#12:5` 渲染成能点的定位(Markdown 多一层「页面引用」`markdownRefs`,代码、链接、网址里
  的不动)。诊断结果卡片上的「定位」「照这个改」按钮没做 —— 第一步里定位靠回复里的 `#12`,「照这个改」等第二步的 `comfy_canvas_edit`。
- **技能**(§8):`skills/comfyui-workflows/SKILL.md` 写明这一版只读不改。**随 Mosael 一起发的插件(`plugins/bundled`)带的技能默认开着**,
  和内置技能一样(市场装的、扔进文件夹的照旧默认关)—— 不然工作台的「助手」一打开就照不到 ComfyUI 的做法。
- **顺带修的两处原生视图的毛病**:
  - 整窗浮层让开画布前铺的那张画面,按 Element Timing 报的「画上屏了」才挪开视图。逐帧实测:只等 `load` 再等一帧,视图第 92 毫秒挪走、
    画面第 274 毫秒才上屏;等 `decode()` 再一帧仍差一两帧;按 Element Timing,画面第 110 毫秒上屏、视图第 111 毫秒挪走。
  - **原生视图亮着时渲染层一定画着它那一圈**(维护者截图:插件页上压着一块没有工作台顶栏和那一列的画布)。渲染层重新加载时漏了主进程
    补播的那一帧视图状态(应用是动态 import 的,订阅得晚)—— preload 记着最新的一帧、订阅时补发;工作台那一页是渲染层自己的状态、
    新文档认领不了,主窗口换文档(或渲染进程没了)时主进程收起工作台的视图、停掉工作台会话;整窗的错误边界接住错误时也收起视图。

**实测**:测试场 ComfyUI 0.39.0 / 前端 1.53.10(隔离的桌面端整条走通:工作台里打开一张故意弄坏的图,经后端的工具口读画布、诊断、
定位;在工作台里跑一次被 ComfyUI 拒绝,`comfy_check` 带任务号把报错拆到 #3、#7、#8);维护者那台 0.39.0 + Manager V4.2.1 只读 GET
(模板、节点定义、装了的包、映射);Comfy 注册表(rgthree-comfy 最新一版 `Flagged`,建议的版本是最近一个 Active 的)。

**真模型端到端**(隔离的桌面端,Kimi Code 订阅新登一次,模型 k3,在工作台的「助手」里发):
- 「这个工作流有什么问题?」(开着故意弄坏的那张):先 `use_skill` 读技能,再并行 `comfy_canvas_read` + `comfy_check`(各约 1.4 秒),
  按严重程度列出 5 个错误、2 个警告(缺 FaceDetailer 及出自 Impact Pack、steps 0、采样器不在列表、#7 的 clip 没连、#8 的 vae 接成了
  CLIP、SD 1.5 的 LoRA 配 Illustrious 底模、宽 1001),每条带 #编号;点回复里的 #8,画布上选中了 VAEDecode。
- 「我想做一个用 Qwen-Image 2.1 编辑图片的工作流」:`comfy_templates`(两次)→ `comfy_template`,推荐官方「Qwen Image 2.1:图像编辑」,
  说清版本够、不缺节点、缺 4 个模型合计约 26.7 GB(逐个写目录和大小,点明第四个只有开提示词增强才要),说明这一版不能替他打开、下载。
- 「rgthree-comfy 能装或者升级吗?」:`comfy_node_pack_info` → `comfy_node_packs`,结论是已经装着最近一个正常的版本、更新的两版都被标记
  (Flagged)不建议升级,发布者、星数、下载量、不碰 torch、和这台机器兼容都说到了,还指出画布上缺的 #11 不是它提供的。

**留给第二、三步**:`applyOps` / `openWorkflow` 照 `readGraph` 的样子加进桥(版本升 5)、`parseComfyWorkbenchCall` 和
`CALL_BUDGET_MS` 各加一项;`comfy_canvas_edit` 是第一个要确认卡的工作台工具,应用前后各跑一次 `check_graph`(问题单的 `kind` 可以
直接比);节点包的安装走已有的 `install_nodes`,装之前把 `node_pack_info` 的 `install_version`、`dependency_risk` 写上确认卡。

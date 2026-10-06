# ADR 0035 · 工作流库:在 Mosael 里看、管、导入一台 ComfyUI 上的工作流

- 状态:已采纳(2026-10-05,维护者:「ComfyUI模型能力当前不错了 但是ComfyUI插件在ComfyUI工作流方面的能力还是很弱」)
- 相关:ADR 0020(插件做生成供应商)、ADR 0032(宿主能力只有一张表)、ADR 0033(目录类能力不进工具表)、
  ADR 0034(模型库 —— 同一套界面骨架、同一条下载路)、`plugins/bundled/comfyui`(第一个实现)

## 背景:现在能做什么、那台 ComfyUI 实际给了什么

ComfyUI 插件把那台机器上**存好的**每张工作流当成一个生成模型 / 一个工具来跑(ADR 0020)。除此之外 Mosael 对工作流什么都
做不了:看不到它长什么样,不能新建、导入、复制、改名、删除;缺节点、缺模型时只会在跑的时候报错。任何改动都得回 ComfyUI。

动手前在用户那台 ComfyUI 上实测(0.38.0,Windows,前端 1.53.10,模板包 0.11.76,ComfyUI-Manager V4.2.1,`--listen 0.0.0.0`),
**只读**:列目录、取文件、取前端的静态脚本;写 / 移动 / 删除接口照 ComfyUI 的源码(`app/user_manager.py`)核对,没有在那台
机器上调。

| 要什么 | 接口 | 实测 / 源码 |
| --- | --- | --- |
| 列工作流 | `GET /api/userdata?dir=workflows&recurse=true&full_info=true` | 17 个文件(16 张 JSON + 1 个 zip),每个带 `path`、`size`、`modified`(毫秒)、`created`;`GET /api/v2/userdata?path=workflows` 另给目录项 |
| 读一张 | `GET /api/userdata/{workflows%2F名字.json}` | 原文;路径里的 `/` 要编码 |
| 写一张 | `POST /api/userdata/{file}?overwrite=false&full_info=true`,正文是文件原文 | `overwrite=false` 且已存在 → **409**;写临时文件再 `os.replace`(原子);父目录不存在会建 |
| 改名 / 移动 | `POST /api/userdata/{file}/move/{dest}?overwrite=false` | 目标已存在 → 409;源不存在 → 404;目标的父目录会建;两边都限制在这个用户的目录里(`..` 出不去) |
| 删除 | `DELETE /api/userdata/{file}` | `os.remove`,**硬删**,204。ComfyUI 没有回收站,它自己的前端删除也是硬删 |
| 回收目录 | 没有 | `workflows/.trash`、`subgraphs` 都是 404 |
| 官方模板 | `GET /templates/index.json` → `/templates/{名字}.json`、缩略图 `/templates/{名字}-1.webp` | 按类别分组,每张带标题、说明、媒体类型、标签 |
| 自定义节点带的示例 | `GET /api/workflow_templates` → `{节点包: [名字]}`,取 `/api/workflow_templates/{包}/{名字}.json` | impact-pack、kjnodes、nunchaku 等带了 |
| 子图蓝图 | `GET /api/global_subgraphs` → `{id: {source, name, info.node_pack}}` | 全是模板包带的;用户自己的蓝图目录不存在。用户的 16 张里 2 张含子图(`definitions.subgraphs`) |
| 节点类型 → 节点包 | Manager `GET /v2/customnode/getmappings?mode=cache` | 5683 个包:`{包: [[节点类型…], {title_aux, nodename_pattern?}]}` |
| 已装的节点包 | Manager `GET /v2/customnode/installed` | `{包: {ver, cnr_id, aux_id, enabled}}` |
| 装节点包 | Manager `POST /v2/manager/queue/task`(`kind: "install"`,`params` = 包 id、版本、`mode`、`channel`)+ `POST /v2/manager/queue/start`,结果在 `queue/history?ui_id=` | 安全等级 `middle+` —— 和 ADR 0034 的装模型一样,只有监听回环地址、或 Manager 的 `network_mode = personal_cloud` 时放行;**这台机器现在会拒**。POST 要 JSON(`reject_simple_form_post`,防 CSRF) |
| 重启 ComfyUI | Manager `POST /v2/manager/reboot` | 安全等级 `middle`;重启期间连接断开 |
| 缺的节点 | `object_info`(2424 个类型)对工作流里的 `type` | 16 张里出现 26 种 object_info 里没有的类型。**一大半不是缺**:rgthree 的 Fast Groups Bypasser / Label / Bookmark、KJNodes 的 SetNode / GetNode 是只在前端的虚拟节点,后端永远没有;真缺的如 `VRGDG_MiniMaxH3AudioDrive`(→ comfyui-vrgamedevgirl)、`CR Prompt Text`(→ ComfyUI_Comfyroll_CustomNodes);有的映射到不止一个包(`UltimateSDUpscale` → comfyui_ultimatesdupscale / comfyui-promptchain),有的一个都映射不到 |
| 工作流声明的模型 | 节点 `properties.models: [{name, url, directory}]`;新格式还有顶层 `models` | 16 张里 7 张带,共 26 条,全是 huggingface.co、都带目录;没有顶层 `models` |
| 图片里嵌的工作流 | PNG `tEXt`:`workflow`(界面格式)、`prompt`(API 格式);WebP 走 EXIF:`0x010F`(Make)= `workflow:<JSON>`、`0x0110`(Model)= `prompt:<JSON>` | 那台机器的历史现在是空的;拿之前经 Mosael 跑出来的 3 张 PNG 看:**只有 `prompt`** —— 插件提交时没带 `extra_pnginfo.workflow`,所以经 Mosael 出的图拖回 ComfyUI 没有布局 |
| 用地址打开一张存好的工作流 | 前端 1.53.10 的路由 | 只认 `?template=&source=`(打开模板)、`?share=`(Comfy 云的分享)、`#<图 id>`(只对**已经打开**的图)。存好的工作流**没有**地址能直接打开;前端暴露的 `window.app.extensionManager.workflow`(工作流仓库,`getWorkflowByPath`)和 `app.loadGraphData` 能做到 |

## 决定

### 1. 一项新的目录类能力 `workflow_library`

和 `model_library` 一样是目录类(ADR 0033 §1):回答「这个连接上有哪些工作流」、替宿主改那台机器上的工作流文件,不是一次能交给
智能体的调用,不进工具表。ComfyUI 插件由 `comfyui_generation` 一并认领。宿主按 `op` 问:

| op | 做什么 | 改动那台机器 |
| --- | --- | --- |
| `library` | 全部工作流:路径、名字、大小、改动时间;画缩略图用的**图摘要**(节点的位置 / 大小 / 种类 / 是否旁路、连线、分组;节点多时截断);识别出的输入、参数、输出(和跑它的生成模型 / 工具同一份 `inspect`);用到的模型文件(在不在);缺的节点(排除虚拟节点)和对应的节点包候选;声明了下载地址又缺的模型;转不过来的原因 | 否 |
| `get` | 一张的原文(导出、编辑器用) | 否 |
| `save` | 存一张(导入、复制):**只新建、不覆盖**(`overwrite=false`,409 → 回「同名」和一个建议名) | 是 |
| `rename` | 改名 / 挪目录:`move` + `overwrite=false` | 是 |
| `trash` | 「删除」:挪进回收目录(见 §3),不硬删 | 是 |
| `restore` | 从回收目录挪回原处(原处被占了就要求换名) | 是 |
| `inspect_import` | 一份要导入的东西(JSON 原文 / 图片 / 链接)→ 认出格式、换成界面格式、图摘要、识别出的参数、缺的节点和模型 | 否 |
| `node_packs` | 一串节点类型 → 节点包候选、装没装 | 否 |
| `install_nodes` | 流式:经 Manager 装节点包,报进度,装完说要重启 | 是 |
| `reboot` | 经 Manager 重启 ComfyUI | 是(连接会断一会儿) |

宿主这边不认识 ComfyUI:任何认领 `workflow_library` 的连接,插件页上就有「工作流库」。列表不存库,每次现问(插件把每张的扫描
结果按「路径 + 大小 + 改动时间」记在持久目录里,和模型库同一个做法)。

宿主自己补两样插件不知道的:
- **最近一次的产出**:生成记录里这个连接 + 这个模型(工作流的 id)最近一条成功的产出素材,给缩略图;
- **Mosael 里谁在用它**:工作流节点、画板格子里选的生成模型是它的。引用表(`record_references`)加一种目标
  `generation_model`(连接 id + 模型 id 的摘要,列宽 64),工作流节点的 `config` 和画板格子的 `form` 里写着
  `provider_profile_id` + `model` 的都抽进来;抽取规则改了,`EXTRACTOR_VERSION` 加一,启动时整表重建(引用表本来的规矩)。

### 2. 界面:和模型库同一套骨架(LibraryBrowser)

插件页那个连接的标题行上一颗「工作流库」(和「模型库」并排)→ 大弹窗:

- 左边一列:「全部」、各个子目录(按数量)、钉在底部的特殊项「缺节点或模型」(带数量)和「回收站」(有才出现);
- 顶上工具条:搜索(名字、节点类型、模型名)、按种类筛(图像 / 视频 / 音频 / 转不过来的)、排序(名字 / 改动时间 / 节点数)、
  显示方式(大卡片 / 小卡片 / 列表,记在本机)、「导入」;
- 一张卡:节点图缩略预览(按工作流里节点的位置和连线画成 SVG,不截 ComfyUI 的图;API 格式没有位置,按依赖分层自动排)、
  名字、种类、缺什么的标记;大卡片多一行最近产出和「N 处在用」;
- 详情页(LibraryDetail):固定头是名字、种类 · 节点数 · 改动时间,右边「用它生成」(交给 AI 工作台,沿用模型库那条交接)、
  「在编辑器里打开」、「更多」(复制、改名、导出 JSON、删除);左栏大一号的节点图,右栏:识别出的输入 / 参数 / 输出、
  用到的模型(点了跳到模型库那一项)、缺的节点(节点包、一键安装)和缺的模型(有下载地址的一键下载)、最近的产出、
  Mosael 里谁在用它(点了跳过去)。

模型库那边反过来:详情「在用的工作流」点了跳到工作流库那一项(此前是直接用它生成)。

### 3. 写操作:每次确认,不覆盖,删除进回收目录

改的是**用户那台机器上的文件**,所以:

- **每次都确认**,确认框写明改哪台服务器(连接名 + 地址)上的哪个文件,改成什么;
- **不覆盖**:保存、改名、恢复一律 `overwrite=false`;撞名(409)时说清楚,给一个建议名(`名字 (1).json`),不提供「覆盖」;
- **删除默认不做硬删**:挪进 `<用户目录>/.mosael-trash/workflows/<删除时刻 YYYYMMDD-HHMMSS>/<原来的相对路径>`。放在 `workflows/`
  外面:ComfyUI 的工作流侧栏只列 `workflows/`,插件也只把 `workflows/` 里的当模型 —— 删了的不会还出现在两边的列表里;
  按时刻分层,同一个名字删两次不撞。Mosael 的「回收站」列出它们,能恢复;**Mosael 不提供清空**:真要删掉,在那台机器上删
  那个目录。删除前确认框写明 Mosael 里谁在用它(工作流节点、画板格子,点得开),删了之后它们跑的时候会说找不到这个模型;
- 导出只是把原文交给浏览器下载,不碰那台机器。

改动那台机器的操作就这几样:保存(导入、复制)、改名、挪进 / 挪出回收目录、装节点包、重启 ComfyUI、下载模型(ADR 0034)。
每一样改完,宿主让这个连接的生成目录和工具清单马上重拉一遍(`host_capabilities.notify(refresh=True)`),不等那一分钟的指纹。

### 4. 在编辑器里打开

前端不能用地址直接打开一张存好的工作流(见上表),所以:

- **桌面版**:复用浏览器池那套内嵌视图(`AccountViewManager.openView`),分区 `persist:pool-comfyui-<连接 id>`,打开这个连接的
  ComfyUI 地址;页面就绪后,主进程执行**一段写死的脚本**:等 `window.app.extensionManager.workflow` 出现,取
  `getWorkflowByPath("workflows/<路径>")`,载入后 `app.loadGraphData(…, workflow)` —— 和在它左边「工作流」里点开是同一件事,
  Ctrl+S 存回原文件。路径由主进程 JSON 编码进脚本,渲染层只传路径,传不进代码;只对这个连接的地址(同源)执行。前端哪天改了
  这几个名字、脚本失败,就停在 ComfyUI 首页,提示「在左边『工作流』里点开 X」。
- **网页版**:新标签页打开这个连接的 ComfyUI,同样提示点开哪张(给一个复制名字的按钮)。
- **存完自动刷新**:编辑器开着时,宿主每 5 秒看一次那张工作流的改动时间,变了就刷新这个连接的生成目录、工具清单、
  模型库和工作流库。

(2026-10-07 起)桌面版不再有不带面板的「在编辑器里打开」:打开一张、「新建」开的都是工作台(同一个内嵌视图、同一段写死的
脚本,外加 Mosael 的面板,见 ADR 0038「桌面版只剩工作台一个入口」);网页版这一条改叫「在 ComfyUI 里打开」,照旧是新标签页。

### 5. 导入并补齐

- **认什么**:拖进来或贴进来的工作流 JSON —— 界面格式(`nodes` / `links`)和 API 格式(`{节点 id: {class_type, inputs}}`);
  带工作流元数据的 PNG / WebP(优先界面格式的 `workflow`,只有 `prompt` 时按 API 格式);链接(能直接取到 JSON 或图片的,
  插件去取;Civitai / HuggingFace 页面这类不是文件的,说清楚)。
- **API 格式没有布局**:插件按 `object_info` 把输入排回 `widgets_values`、按连线重建 `links`、按依赖分层自动排位置,存成界面
  格式 —— ComfyUI 自己的侧栏才打得开、插件才认得;预览里写明「这份是 API 格式,没有布局,位置是自动排的」。
- **导入前先预览**:节点图、识别出的参数、缺的节点和模型;确认后存进那台 ComfyUI 的 `workflows/`,同名不覆盖(建议新名)。
- **缺模型**:有下载地址的(节点 `properties.models` / 顶层 `models`,只认 huggingface.co、civitai.com,和模型库同一份白名单)
  接模型库一键下载 —— 同一个下载框、同一条路(Manager / 同一台机器)和那些提醒。
- **缺节点**:列出缺的节点类型和对应的节点包。判据:类型不在 `object_info` 里,**且**不是只在前端的虚拟节点(一张已知清单:
  Note、MarkdownNote、Reroute、PrimitiveNode、rgthree 的那几个、KJNodes 的 SetNode / GetNode……),**且**它所属的包没装(装了还
  没有说明是虚拟节点或没加载成功,标「装了但没加载」而不是「缺」);包从 Manager 的映射查,一个都查不到就说「不知道是哪个
  节点包」,查到几个就都列出来让人挑。装了 Manager 的,确认后一键安装:确认框写明「会改动那台机器:装进它的 custom_nodes,
  装完要重启 ComfyUI 才生效,重启期间正在跑的任务会中断」;装完给「重启 ComfyUI」(再确认一次)。Manager 拒绝(安全等级,
  见上表)时说人话和下一步,和装模型同一套。**测试时绝不在用户那台机器上真装节点**:用假 Manager 验证流程。

落地时定下的几处细节:

- **链接只取插件声明过网络权限的地方**:HuggingFace、Civitai、ModelScope 和这台 ComfyUI 自己的地址(带着这个连接的访问凭据)。
  别的站(GitHub、OpenArt……)说清楚、让人下载下来拖进来 —— 多申报一项网络权限,已有的连接会先停用、等人授权,不划算;
  网页(`text/html`)不是文件也当场说。
- **API → 界面格式**照 `convert` 读 `widgets_values` 的同一套顺序排回去(seed 后面「生成后怎样」那一格写 `fixed`,导进来的值
  不被前端换掉;上传按钮占位;定义里不是常见 widget 类型、API 里却是一个值的 —— 新版的 `COMFY_DYNAMICCOMBO_V3` —— 当
  widget);缺的节点按连线补出输出口。拿那台机器的 object_info 和几张真工作流验过:界面 → API → 界面 → API 和第一次一样,
  换回来的界面格式在用户那版前端(1.53.10)里载得进去。
- **存进去的原文以 JSON 字符串交给插件**:调用记录只留截断的一段,不把整张图存进记录。导入的图换一个新的图 id。
- **装节点包**:Manager 映射的键,registry 上的是包名(`selected_version = latest`),只在仓库上的是仓库地址(按仓库名、
  `unknown`,和 Manager 4.2.1 的 `resolve_node_spec` / `install_by_id` 一致);一个后台任务 `node_install`,装完结果里写着要
  重启。界面上「装好了、重启之后才加载」只对这次打开之后、上次重启之后装的说;重启过还缺,说「装了却没加载」。

### 6. 分两步交付

1. 工作流库:列表、详情、图预览、用它生成、复制 / 改名 / 删除(回收目录)/ 恢复、导出、在编辑器里打开、谁在用它;
2. 导入并补齐:拖 / 贴 / 链接、预览、API 格式转换、缺模型下载、缺节点安装与重启。

## 后果

- ComfyUI 插件多认领一项能力、多几个 op;清单的权限不变(`filesystem:write` 已经申报过,这次写的都是经 ComfyUI 的接口)。
- 对那台机器的写操作第一次进了 Mosael:都经 ComfyUI / Manager 自己的接口(不碰文件系统),都确认、不覆盖,删除可恢复。
- 经 Mosael 跑出来的图只带 API 格式的 `prompt`;以后插件提交时可以带上 `extra_pnginfo.workflow`,让产出能原样拖回 ComfyUI ——
  不在这次范围。
- 官方模板、自定义节点的示例、子图蓝图读得到,「从模板新建」留到以后(同一个 `save`)。

## 后续:文件夹和右键菜单(2026-10-06,插件 1.13.0)

维护者:「ComfyUI这里的工作流只有全部 不支持分组 也没有右键菜单」。原因是左栏只认工作流路径里的**一层**目录、按数量排,而他那台
机器上 17 张工作流(和 1 个压缩包)都在 `workflows/` 顶上(只读看过:`/api/userdata` 列出 18 个文件、没有子目录,`/api/v2/userdata?path=workflows`
在 0.38.0 上有)—— 于是只剩一个「全部」;卡片上也只有点开,没有别的入口。

**文件夹就是 `workflows/` 里的子目录**,和 ComfyUI 自己的工作流侧栏(它照 `/api/userdata` 的文件路径摆文件夹)同一份,Mosael 不另记
分组。照 `app/user_manager.py` 核对过的几条约束决定了做法:

| 要做的 | ComfyUI 给的 | 做法 |
| --- | --- | --- |
| 列出空文件夹 | `/api/userdata` 是 glob,只列文件、跳过隐藏的;`GET /api/v2/userdata?path=…` 用 os.walk,目录和文件都列 | 列表多一份 `folders`:有文件的各级父目录 ∪ v2 列出的目录(隐藏的不算);老版本没有 v2 就只有前一半 |
| 新建 | 没有建目录的接口;写文件时会建父目录 | 写一个隐藏的占位文件 `workflows/<路径>/.mosael-folder`(`overwrite=false`)。ComfyUI 的侧栏和插件都不列隐藏文件;空文件夹在 ComfyUI 那边要等挪进去一张才出现(它本来就不列空目录) |
| 改名 / 挪 | `move` 是 `shutil.move`,源可以是目录;`overwrite=false` 时目标存在就 409 | 整个目录一次挪;已经有了(不分大小写比 —— 用户那台是 Windows)回撞名和建议名,不合并;不能挪进自己里面;只改大小写先挪到临时名字 |
| 删除 | `DELETE` 是 `os.remove`,删不了目录(而且是硬删) | 挪进回收目录,和删一张工作流同一个地方 |

**删除只删空的**(里面没有一个看得见的文件;空的子文件夹不算,一起挪走)。另一种是「不空也删,里面的东西进回收站」,没选,因为:

1. 一下子带走一整个文件夹的工作流,每一张都可能是 Mosael 里某个工作流节点、画板格子在用的生成模型;删一张时确认框会列出谁在用它,
   删一个文件夹就得列一大串,太容易一眼扫过去点了确认;
2. 文件夹里不是工作流的文件(拷进去的压缩包)也会跟着进回收目录,而回收站只列得出工作流 —— 它们在 Mosael 里就找不回来了;
3. 撤销要一张张恢复;
4. 空不空是插件**挪之前现查**那台机器的:这期间在 ComfyUI 里往里面存了一张,就不删、回 `not_empty` 和个数(宿主 409),而不是把它一起
   扫进回收目录。

要删一个不空的文件夹,先把里面的挪走或一张张删(各自确认、各自能恢复)。菜单上那一项灰着,写着还有几个文件。

**其余几处**:

- 选一个文件夹看它和它下面的(数量也连同子文件夹),搜索 / 种类 / 排序都在里面起作用,搜索框写着在哪、几张;文件夹按名字排,不按
  数量 —— 拖卡片过去时目标不能挪来挪去。
- **移动**就是 `rename_workflow`(名字不变、换上级):卡片拖到左栏的文件夹(或「全部」= 顶层)上松手、或菜单里「移动到…」,都先弹
  同一个确认框(拖过来的那个文件夹已经选好),撞名给建议名;Mosael 里在用它的说一声(换了路径,它们会说找不到这个模型)。
- 改之前都现查:要挪的那张不在了(ComfyUI 回 404)说「已经没有了」而不是一句 HTTP 404;改名、删文件夹没成也重新列一遍。
- **右键菜单**:卡片、列表的一行上右键,悬停 / 聚焦时出现的 ⋯,Shift+F10 / 菜单键(macOS 上浏览器不自己发 `contextmenu`,补发一个)
  打开同一份清单(`ActionMenu` 加了可选的分组名):打开详情、在工作台 / 编辑器里打开 | 编辑应用表单… | 复制…、改名…、移动到…、
  导出 JSON | 复制路径 | 下载缺的模型、装缺的节点(缺什么才有,打开详情停到那一节)| 删除…。点不了的灰着,下面一行写着为什么。
- 「最近打开」没做:ComfyUI 不提供(它前端开过哪几张记在浏览器自己的存储里),Mosael 也没记;按改动时间排序已经能看到最近改过的。

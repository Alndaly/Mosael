# ADR 0034 · 模型库:看得见一台 ComfyUI 上的模型,缺的下到那台机器上

- 状态:已采纳(2026-10-04,维护者:「进一步优化 要支持模型的可视化、下载模型等等操作」)
- 相关:ADR 0020(插件做生成供应商)、ADR 0032(宿主能力只有一张表)、ADR 0033(目录类能力不进工具表)、
  `plugins/bundled/comfyui`(第一个实现)

## 背景:那台 ComfyUI 实际给了什么

此前 Mosael 对一台 ComfyUI 上的模型文件只有一个只读工具 `list_models`(按目录列文件名)。要知道一个 LoRA 是给哪个底模的、
触发词是什么、哪几张工作流在用它,得回到 ComfyUI 自己的界面里翻;缺一个模型,只能去那台机器上手动下。

动手前在用户那台 ComfyUI 上实测过(0.38.0,Windows,`--listen 0.0.0.0 --enable-manager`,ComfyUI-Manager V4.2.1,
530 个模型文件分在 17 个非空目录里)。只读请求,除了一次装模型的试探(见下表最后几行,没有写下任何文件):

| 要什么 | 接口 | 实测 |
| --- | --- | --- |
| 有哪些模型目录 | `GET /experiment/models` | 49 个目录,每个带磁盘上的绝对路径(可能几处)和认的扩展名 |
| 一个目录里的文件 | `GET /experiment/models/{folder}` | `name`(可带子目录,Windows 上是 `bbox\face_yolov8m.pt`)、`pathIndex`、`size`、`modified`、`created` |
| 预览图 | `GET /experiment/models/preview/{folder}/{pathIndex}/{name}` | 同名的 png / jpg / webp,或 safetensors 头里的封面,统一转成 webp;没有就 404 |
| 元数据 | `GET /view_metadata/{folder}?filename=` | 只认 safetensors,读的是文件头的 `__metadata__`,一次约 40ms。LoRA 大多有(抽 40 个,39 个带 `ss_*` / `modelspec.*`);大模型多半是空的或只有合并配方 |
| 服务端下载 | 没有 | `/api/assets` 回 503 `SERVICE_DISABLED`(要 `--enable-assets` 启动,且其中没有下载接口);官方前端缺模型时也只是在浏览器新标签页里打开链接,桌面版走 Electron 自己的下载 —— 都不是经 HTTP 能叫的 |
| Manager 装模型 | `POST /v2/manager/queue/install_model` + `queue/start`,结果在 `queue/history?ui_id=` | 安全等级 `middle+`:只有 ComfyUI 监听回环地址、或 Manager 的 `config.ini` 里 `network_mode = personal_cloud` 时才放行。这台监听 0.0.0.0 → 任务记 `failed`、`messages: ["failed"]`,真正的原因只在日志里(`/internal/logs/raw`):「security_level must be `normal or below`, and network_mode must be set to `personal_cloud`」。没有写下任何文件 |
| 剩余磁盘空间 | 没有 | `/system_stats` 只有内存、显存 |
| 工作流声明的下载地址 | 节点 `properties.models: [{name, url, directory}]`(官方模板就这么写);新格式还有顶层 `models` | 用户存的 12 张 JSON 里 6 张带(都是节点上的,共 23 条,全是 huggingface.co) |

## 决定

### 1. 一项新的目录类能力 `model_library`

和 `generation`、`tools` 一样是**目录类**(ADR 0033 §1):认领它的工具回答「这个连接上有哪些模型文件」,替宿主把一个模型下到
那台服务器上 —— 本身不是一次能交给智能体的调用,不进工具表。ComfyUI 插件由已经认领生成和工具清单的 `comfyui_generation`
一并认领。宿主按 `op` 问:

| op | 回什么 |
| --- | --- |
| `library` | 全部模型文件(目录、名字、大小、改动时间、推断的底模家族、触发词、哪几张工作流在用、预览图地址)、各目录的数目、工作流缺的模型、这台服务器下载走哪条路 |
| `detail` | 一个文件的完整元数据(文件头里的全部标量;训练标签按出现次数取前几十个) |
| `resolve` | 一个链接 → 直链、文件名、大小、建议放进哪个目录、底模家族、触发词、同名文件在不在 |
| `download` | 流式:下到那台服务器上,边下边报进度,宿主取消时停下 |

宿主这边不认识 ComfyUI:任何认领 `model_library` 的连接,插件页上都有一行「模型库」。列表不缓存在库里(530 个文件每次现问,
插件把逐个读的元数据按「服务器 + 目录 + 名字 + 大小 + 改动时间」记在自己的持久目录里,第二次打开只读目录);预览图由宿主
按插件给的地址取回、记在磁盘缓存里(`<数据目录>/cache/model-previews/`)再交给界面 —— 和插件交回 `url` 的产出是同一个
「插件给地址、宿主去取、走这个连接的出站决定」的规矩。下载是一个后台任务(`model_download`):任务中心里看得到、能取消;
下完宿主让这个连接的目录重新拉一遍(`host_capabilities.notify(refresh=True)`),生成表单里选模型的下拉马上有它。

### 2. 列出来的每一个模型有什么

- **名字、目录、大小、改动时间**:目录给的原样;
- **预览图**:有就用;没有就是按目录分的占位(大模型、LoRA、VAE、放大……各一个图标),不留白;
- **底模家族**:按下面的顺序认,**认到为止**,每一条记下凭的是什么(`metadata` / `filename`),界面上看得到:
  1. 文件头里的 `ss_base_model_version`(kohya 训练脚本写的,`sdxl_base_v1-0`、`sd_v1`、`flux1`……)—— 它最具体:训练脚本
     不认识的底模(实测有 `anima`),`modelspec.architecture` 会照默认写成 `stable-diffusion-v1`,不能信后者;
  2. 没有它时看 `modelspec.architecture`(SAI 的模型规范,`stable-diffusion-xl-v1-base/lora`、`flux-1-dev/lora`……);
  3. 认出是 SDXL 之后,训练用的底模名 `ss_sd_model_name` 或文件名里带 illustrious / noob / pony 的,细分成那一支;
  4. 文件名(连子目录)里的关键词:`illustrious` / `_il` → Illustrious、`noob` → NoobAI、`pony` → Pony、`flux` → Flux、
     `wan2.2` / `wan22` → Wan 2.2、`wan` → Wan 2.1、`sdxl` / `_xl` → SDXL、`sd15` / `v1-5` → SD 1.5、`qwen` → Qwen-Image、
     `hunyuan` → HunyuanVideo、`ltx` → LTX-Video、`z_image` / `z-image` → Z-Image……(全表在插件 README);
  5. 元数据里写了、表里没有的值(实测有 `anima`、`krea2`)原样显示,**不往认得的家族上靠**;什么都没有就空着,不猜。
- **触发词**:`modelspec.trigger_phrase` 或 `ss_trigger_words`;都没有时取训练标签(`ss_tag_frequency`)里出现最多的前几个,
  标明「来自训练标签」—— 它们是常见词,不一定是作者指定的触发词;
- **哪几张工作流在用**:插件扫一遍这台服务器上保存的工作流,节点的输入值里写着这个文件名的就算(和 ComfyUI 自己找文件的规矩
  一样,按「目录内的相对路径」比);
- **缺的模型**:工作流声明了下载地址(节点 `properties.models` 或顶层 `models`)、这台服务器上又没有的,单列一组。只算**节点
  当前真在用**的那一条:节点改选了别的文件,声明就过期了,不列。

不做:删除、改名、移动模型文件。

### 3. 下载走哪条路(按优先级,前一条走不通才试下一条)

1. **ComfyUI 自己的下载接口**:0.38.0 没有(见上表)。将来 ComfyUI 在服务端给了,加在最前面;今天不去探测不存在的接口。
2. **ComfyUI-Manager 的装模型接口**(`/v2/manager/version` 回 V4 时):提交 `install_model`(目录 = 选定的模型目录、
   文件名 = 确认过的名字),再 `queue/start`,按 `ui_id` 轮询历史。Manager 不报字节进度,只能说「ComfyUI-Manager 正在下载」;
   它也没有取消单个任务的接口 —— 取消时 Mosael 不再等,并明说「那台机器上的下载还会继续」,不去清别人的队列。
   失败时读提交之后的日志,认出安全策略的拒绝就说人话和下一步(「在那台机器上把 ComfyUI-Manager 的 config.ini 里
   `network_mode` 改成 `personal_cloud`,重启 ComfyUI」)。拒绝记在插件的持久目录里:模型库在下载前就提醒,下一次照样再试
   (配置可能已经改了)。
3. **ComfyUI 和 Mosael 在同一台机器上**:`/experiment/models` 给的那个目录在本机存在、且本机列出来的文件和 ComfyUI 报的一致
   (光路径存在不够:两台机器可能恰好有同一个路径)→ 插件直接写进去:先写 `<名字>.mosael-part`,下完再挂成正式的名字;按字节
   报进度;取消时停下并删掉**自己的**这个半截文件;开始前查剩余空间(`shutil.disk_usage`),不够就不下,说差多少。
4. **都走不通**:如实说明,并给出能做的那一步 —— 装 ComfyUI-Manager、改它的 `network_mode`,或者把文件放进那台机器的
   `models/<目录>` 里(给出完整的直链和文件名,复制就能用)。

剩余空间只有第 3 条查得到;前两条是那台机器自己下,Mosael 问不到它还剩多少,确认框里明说「查不到」。

**不覆盖任何已有文件**:确认前就查同名文件(`resolve` 回 `exists`),在的话界面要求换一个名字(给一个建议名),不提供「覆盖」;
写入时再查一遍,本机那条路用硬链接挂正式名字(目标已存在就失败,没有竞态窗口)。

### 4. 链接认什么

- **HuggingFace**:`/blob/` 和 `/resolve/` 的文件链接(换成 `/resolve/`);`HEAD` 取大小(`x-linked-size` / `content-length`);
  401/403 且 `X-Error-Code: GatedRepo` 是要先在网页上同意条款的仓库 —— 说清楚,并提示在连接上填 HuggingFace 令牌;
- **Civitai**:模型页(带不带 `modelVersionId`)、`/api/download/models/{版本}`、`/api/v1/model-versions/{版本}` → 版本接口给
  主文件的名字、大小、直链,模型类型定目录(Checkpoint → checkpoints、LORA / LoCon / DoRA → loras、TextualInversion →
  embeddings、VAE → vae、Controlnet → controlnet、Upscaler → upscale_models、Hypernetwork → hypernetworks),`baseModel` 定家族,
  `trainedWords` 是触发词;
- **其他直链**:`HEAD` 取 `content-disposition` 里的文件名和大小,没有就取地址最后一段。

目录:Civitai 按模型类型定;HuggingFace 文件的路径里正好有这台服务器上的某个目录名时建议它(官方的拆分仓库按 ComfyUI 的目录名放文件:`split_files/vae/ae.safetensors`);别的由用户选(列出这台服务器上的全部模型目录),建议的也能改。文件名去掉路径分隔符和 `..`,扩展名保留。

**工作流里声明的地址**只认 `https://huggingface.co/` 和 `https://civitai.com/`(和 ComfyUI 官方前端的白名单同一份):工作流
文件来自四面八方,一键下载不该替一个陌生链接背书;粘贴的链接是用户自己给的,任何 http(s) 都行,确认框里写明来自哪个站。

### 5. 凭据

连接上加两格**可选**凭据:`civitai_token`、`huggingface_token`。和已有的访问凭据一样按密钥存、只注入这个连接的插件进程;
不进调用记录、产出和报错,任务里记的是不带令牌的原链接。Manager 那条路只能把 Civitai 令牌拼进地址(它不收请求头),
于是会留在那台机器的 Manager 任务历史里;HuggingFace 要令牌的文件走不了 Manager,说清楚。

### 6. 界面放在哪

插件页上那个连接的卡片里,「生成模型」下面一行「模型库」→ 一个大弹窗:左边目录(带数目),上面搜索、按家族筛、「下载模型」,
中间卡片网格,点开是详情(大图、完整元数据、触发词、在用的工作流);工作流缺的模型在最上面一组,一键下载;下载中的任务带
进度条和取消。放在连接上,是因为模型文件属于**一台服务器**:两个连接指着两台 ComfyUI,各有各的模型。生成表单里选大模型、
LoRA 的下拉不在这次范围里加缩略图(见「后续」)。

## 安全

- 写盘只在第 3 条路:目标目录是 ComfyUI 自己报的那个模型目录(按用户选的目录名查,不收任意路径),文件名不含分隔符;
  不覆盖;半截文件是 Mosael 自己的 `.mosael-part`,只删它;
- 不装自定义节点、不改 Manager 的配置、不重启 ComfyUI —— 这些都是用户那台机器上的决定,Mosael 只说该怎么做;
- 插件如实申报它要做的事(见「后续」):连 ComfyUI、连 HuggingFace / Civitai、同一台电脑时写 ComfyUI 的 models 目录。
  粘贴的别的直链也会去连 —— 那是用户自己给的地址,确认框里写着来自哪个站。

## 后续(2026-10-04,维护者按建议拍板,插件 1.9.0)

- **如实申报权限**:清单声明 `network:huggingface`、`network:civitai`(照现有插件的写法:`network:<服务>`)和
  `filesystem:write`。已有的连接升级后停用、等用户重新授权 —— 这是预期的;宿主把「为什么停」说清楚:停用原因点名缺哪几项
  并说明是插件更新后多要的(之前授予的不受影响),连接卡片最上面一条「授予这几项」,插件列表标「待授权」;
- **生成表单里选模型文件的缩略图**:插件在选模型文件的参数上写 `x-model-folder`(按输入名认,同名输入按节点分),宿主照传、
  生成选项带上插件连接 id;AI 工作台、画板、工作流节点从那个连接的模型库取缩略图(没有就按目录分的占位)、底模和触发词,
  选中 LoRA 能一键把触发词加进提示词;
- **经 Manager 下载时下载框先说清楚**:要带 Civitai 令牌时它会留在那台机器的任务记录里、看不到按字节的进度、开始后取消停不下
  那边的下载。解析 Civitai 链接先不带令牌问,对方要登录才带;
- 用户那台 ComfyUI 要不要经 Manager 下载(把 `network_mode` 改成 `personal_cloud` 并重启)由用户在那台机器上决定。

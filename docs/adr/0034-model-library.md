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
按插件给的地址取回、记在磁盘缓存里(`<数据目录>/model-previews/<连接>/`)再交给界面 —— 和插件交回 `url` 的产出是同一个
「插件给地址、宿主去取、走这个连接的出站决定」的规矩。卡片、列表和选模型的下拉要的是宿主由原图缩出来的缩略图
(`/model-library/thumbnail`,长边 512 的 WebP,记在原图旁边),详情页的大图才要原图;同一个连接同时只去那台服务器取两张,
排队的请求不攥着数据库连接,浏览器掐掉的(滚出去了)排到时不取。下载是一个后台任务(`model_download`):任务中心里看得到、能取消;
下完宿主让这个连接的目录重新拉一遍(`host_capabilities.notify(refresh=True)`),生成表单里选模型的下拉马上有它。

### 2. 列出来的每一个模型有什么

- **名字、目录、大小、改动时间**:目录给的原样;
- **预览图**:有就用;没有就是按目录分的占位(大模型、LoRA、VAE、放大……各一个图标),不留白;
- **底模家族**:按下面的顺序认,**认到为止**,每一条记下凭的是什么(`metadata` / `filename`),界面上看得到(2026-10-06 改:中间加了「权重结构」一档、不适用的目录单独标出,见文末「后续」):
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
- 插件如实申报它要做的事(见「后续」):连 ComfyUI、连 HuggingFace / Civitai / ModelScope、同一台电脑时写 ComfyUI 的 models 目录。
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

## 后续(2026-10-05,插件 1.10.0):ModelScope(魔搭)

维护者:「modelscope 上面也有很多好用的模型 也得要支持」。和 HuggingFace、Civitai 并列,规矩照旧。动手前对真站点只读核对过
(2026-10-05):

| 要什么 | 接口 / 实测 |
| --- | --- |
| 模型信息 | `GET /api/v1/models/{仓库}` → `{"Code":200,"Data":{…},"Success":true}`;`Name`、`ChineseName`、`Revision`(默认分支,`master`)、AIGC 专区的 `AigcType`(只有 Checkpoint / LoRA / VAE 三种,官方 SDK 的 `AigcModel.AIGC_TYPES` 同一份)、`VisionFoundation`(登记的底模类型:SD_XL、FLUX_1、QWEN_IMAGE_20_B、WAN_VIDEO_2_2_I2V_A_14_B、KREA_2……)、`BaseModel`(底模仓库,可带 `@版本`)、`TriggerWords` |
| 文件列表 | `GET /api/v1/models/{仓库}/repo/files?Revision=&Recursive=&Root=` → `Data.Files[]`:`Path`、`Size`、`Sha256`、`Type`(blob / tree)。分支不对回 404,目录不存在回 200、`Files: null` |
| 下载 | `/models/{仓库}/resolve/{版本}/{路径}`:HEAD 回 200 和 `X-Linked-Etag`(就是 sha256),**不给长度**;GET 小文件直接回,LFS 文件 302 到签好名的 CDN(`cdn-lfs-cn-1.modelscope.cn` / `cdn-lfs-ap-1.modelscope.ai`),那边给长度和 `content-disposition` |
| 没有的 | 模型不存在:404 + `Code 10010205001`;文件不存在:HEAD 404、GET 500 |
| 认证 | 官方 SDK(modelscope_hub)把访问令牌既当 `Authorization: Bearer` 发(新接口),又当会话 cookie `m_session_id` 发(`/api/v1` 老接口和下载);它对 404 的说明是「不存在,或者是要登录的私有仓库」 |
| 国际站 | `modelscope.ai` 接口一样,但**是另一个站**:SDXL base、实测的 LoRA 在 .cn 有、在 .ai 404;同名仓库两边的数据也不一样;SDK 找不到时才去另一个站找,令牌也分站(「这个令牌在另一个站有效」) |

- **链接**:模型页 `/models/{仓库}`(及 `/summary`、`/files` 这些页签)、目录页 `/tree/{版本}/{目录}`、文件页
  `/file/view/{版本}/{路径}`(路径里的斜杠常被编码成 `%2F`)、直链 `/resolve/{版本}/{路径}`、SDK 的
  `/api/v1/models/{仓库}/repo?Revision=&FilePath=`。文件链接直接解析那一个;模型页 / 目录页里只有一个模型文件
  (`.safetensors`、`.sft`、`.ckpt`、`.pt`、`.pth`、`.bin`、`.gguf`)就是它,好几个就列出候选(最多十个)请用户贴具体文件的
  地址 —— 比 HuggingFace 贴仓库页只说「去 Files 页」多走一步。大小取文件列表里的 `Size`(HEAD 不给长度);
- **目录与家族**:`AigcType` Checkpoint / LoRA / VAE → checkpoints / loras / vae(这台服务器没有那个目录就不建议);推不出就
  像 HuggingFace 那样看路径里有没有这台服务器上的目录名(Comfy-Org 在魔搭上也有拆分仓库的镜像)。家族只认 AIGC 专区登记的:
  `VisionFoundation` 和 `BaseModel` 都是架构名的写法,接文件头底模的同一张表(为它把 `wan_video_2_2`、`sd_2` 两种写法补进表里);
  SDXL 再按底模仓库名、它自己的仓库名和文件名细分 Illustrious / NoobAI / Pony(ModelE/Illustrious-XL 登记的是 SD_XL 上的
  Checkpoint,底模写 SDXL base);表里没有的原样交出底模仓库名。普通仓库不猜;
- **两个站各认各的**:`www.` 换掉(`www.modelscope.cn` → `modelscope.cn`),`.ai` 不改写成 `.cn` —— 和 Civitai 的别名不同,
  它们不是同一个站;
- **令牌**:清单加 `modelscope_token`,只发给 `modelscope.cn` / `modelscope.ai`(CDN 那一跳不带),两样一起发
  (Bearer + `m_session_id`,和 SDK 一样)。解析时先不带,回 401 / 403 **或 404**(私有模型看不到时它回 404)且填了令牌才
  带上再问;下载那一步和 HuggingFace、Civitai 一样,填了就带给 ModelScope 自己。一个连接只有一格:令牌是哪个站的,就只在那个
  站上管用,说明里写明;
- **Manager**:V4 的装模型接口不挑站点(除 HuggingFace / GitHub 走它自己的下载器外,别的地址一律按浏览器 UA 跟着跳转下),
  只看安全策略 —— ModelScope 的直链照样能交给它。它不收请求头,ModelScope 的令牌只走请求头和 cookie(没有放进地址的用法,SDK 也不这么用),所以经 Manager
  带不过去,下载框像 HuggingFace 那样说清楚;
- **工作流里声明的地址**:可信来源加上 `https://modelscope.cn/`、`https://modelscope.ai/`(先换成规范域名再比)。这一条比
  ComfyUI 官方前端的白名单宽 —— 魔搭是国内用户最常用的模型站;
- **权限**:清单加 `network:modelscope`,已有连接升级后照 1.9.0 的规矩先停用、等授予这一项。

## 后续(2026-10-06,插件 1.13.0):底模从权重结构认,修订 §2

维护者:「现在有太多模型都认不出底模」。拿维护者那台 ComfyUI 只读核对(全新缓存):528 个文件认出 361 个。认不出的几类:

- **合并出来的大模型和不少 LoRA 一点元数据都没有**,名字是作者随手起的(`dessertModels_donuts`、`pieModels_honeyPie`);
  但文件头里的**张量名和形状**一看就知道是什么网络 —— 而且读得起:ComfyUI-Custom-Scripts 的 `/pysssss/view/{目录}/{名字}`
  认 Range,开头 8 个字节是头长度、再读那么长就是整段 JSON,一个文件几十毫秒(头 90–365 KB);
- **Civitai 式的驼峰名字**(`novaAnimeXL_ilV160`、`flatbreadIL_v50`)按「两头非字母」的规矩认不出 XL、IL;
- **表里缺的家族**:Krea 2、Anima、MiniMax H3 / Music、Qwen-Image 2;元数据里的 `anima`、`krea2` 原样显示成小写;
- **老 kohya LoRA** 只有 `ss_sd_model_name` 和 `ss_v2`,没有底模版本;
- **缓存记的是结论**:改了规矩,缓存过的文件照旧;
- 文本编码器、放大、检测这些**本来就不讲底模**的,界面上也写「认不出底模」;
- ComfyUI-GGUF 把 `unet_gguf` / `clip_gguf` 登记在和 `diffusion_models` / `text_encoders` 同一批文件夹上,**同一个文件列两遍**
  (实测 23 个,含 Impact Pack 的 `ultralytics` 和 `ultralytics_bbox` / `_segm`)。

决定:

- **认的先后改成:元数据 > 权重结构 > 文件名**。权重结构(`family_source: "weights"`,界面写「从权重结构认出」)用插件自己
  的一张特征表(`tools/weights.py`):张量名去掉外层包装(`model.diffusion_model.`、`lora_unet_`、`transformer.`……)、点换
  下划线后按表从上往下认 —— 有独门部件的在前(Krea 2 的 attn.gate、Anima 的 llm_adapter、Flux.2 共用的调制、HiDream 的
  双 / 单流块、AuraFlow 的 joint_transformer_blocks —— Pony V7 的 diffusers 式 LoRA 因此不会说成 Flux……),只能靠维度
  分的在后(SD 1 / 2 / XL 看交叉注意力吃的文本宽度 768 / 1024 / 2048,Z-Image 和 Lumina 看 3840 / 2304,Wan 看
  1536 / 3072 / 5120)。LoRA 照抄底模的层名,大模型、UNet、LoRA、ControlNet、文本反演、IP-Adapter 用同
  一张表;LoRA 只看 down / A 那一半的宽度(up / B 的第二维是秩)。**分不清的少说**:Wan 14B 的 2.1 和 2.2 结构一样,就说 Wan。
  表是照公开的网络结构、对着实际文件写的,不照搬 ComfyUI 的 model_detection.py(GPL);
- **元数据和权重对不上架构时信权重**(实测有 Flux 的 LoRA 写着 `ss_base_model_version: sd_1.5`);元数据更细(权重只看得出
  SDXL,元数据说 Pony)时用元数据;元数据是表里没有的值时也用权重;
- **细分**从「SDXL → Illustrious / NoobAI / Pony」推广到 SDXL → Kolors、Wan → 2.1 / 2.2、Flux → Kontext / Chroma、
  AuraFlow → Pony V7:训练用的底模名、标题,再是文件名;细分用的关键词比单凭文件名猜时宽(`ILL`、`illu`、high noise / low noise),因为那时已经知道是哪一层。Civitai 在线训练
  在 `ss_sd_model_name` 里写的是底模的版本号(`889818.safetensors`),Illustrious、Pony、NoobAI 的官方版本号记在表里;
- **文件名**:驼峰拆开再认(XL、IL、ZIT 单独出现才算),补上 Krea 2、Anima、MiniMax H3 / Music、Qwen-Image 2、Kolors、单独的
  qwen、HiDream 的写法(Kolors 也算 SDXL 下细分的一支:它的 LoRA、IP-Adapter 和 SDXL 的层一模一样,大模型多一层
  encoder_hid_proj);`anima` 要两头非字母(animagine 不算),`illustri` 认 Illustrious 和 illustrij(illustration 不算),
  `hunyuan` 只认 hunyuan_video(混元的图像模型是别的结构);
- **元数据**:`anima` → Anima、`krea2` → Krea 2、`qwen_image_2` → Qwen-Image 2、光写 `wan` 的 → Wan;没有底模版本的老
  kohya LoRA(有 `ss_network_*`)按 `ss_v2` 认 SD 1 / SD 2。Civitai 的 baseModel 补上 Krea 2、Anima、MiniMax H3 / Music 3、
  Qwen 2 / 2.1(→ Qwen-Image 2)、ZImageTurbo、Pony V7(AuraFlow 结构,不并进 Pony),「Other」等于没说;
- **读文件头**:Range 读开头 64 KB,头更长再补读,超过 8 MB 不读;并发照旧 4 个,第一个文件先单独读。**不下整个文件**:对方
  没有那个地址(404)或不认 Range(回 200)时立刻挂断,这一趟剩下的文件不再试,退回 `/view_metadata` 只拿元数据;
  GGUF 读张量表(各维倒回 PyTorch 的顺序)走同一张表,认不出时看 `general.architecture`;文本编码器目录里的 GGUF 不读(头里
  是整张词表);
- **缓存记原料**:元数据里认底模、触发词、标题要用的那几项,训练标签里最多的几个,权重认成的家族,GGUF 的架构名;家族每次列出
  时现推。缓存带版本(格式 + 权重表的指纹),对不上整份扔掉重读 —— 它是缓存,不留兼容分支。读的时候没有读头地址的文件,下次
  有了再补认;
- **不适用**:文本编码器、CLIP 视觉、放大、检测 / 分割、抠图、语音和大语言模型这些目录(`ultralytics*`、`mmdets*`、
  `instantid`……)报 `family_source: "not_applicable"`、`family` 空着,宿主照传,界面写「不适用」,不算「认不出」;
- **去重**:按 `/experiment/models` 报的磁盘位置(斜杠统一、`.` 段去掉,Windows 路径不分大小写)认同一个文件,留在先登记的
  目录 —— ComfyUI 自己的目录先登记,自定义节点的在后;只有别名目录列着的(`.gguf`)照旧留在那儿。各目录的数目按去重后的算;
  「工作流缺不缺」仍按 ComfyUI 自己的列法(UnetLoaderGGUF 按 `unet_gguf` 找)。

同一台服务器、全新缓存再核对:505 个文件(去掉 23 个重复)认出 485 个(元数据 274、权重结构 131、文件名 80),19 个不适用,
1 个认不出(一个 `.pt` 的文本反演,没有可读的文件头,名字里也没有线索);第一次读十来秒,之后一秒。假装那台没装
ComfyUI-Custom-Scripts(读头地址 404,只试了一次)时认出 408 个。和 Civitai 上登记的 baseModel 对了 73 个:59 个一致;其余是我们说得更少
(SDXL 对 Illustrious 4 个、Wan 对 Wan 2.2 3 个)、文本编码器标了不适用(5 个),或我们更细(2 个 VAE),没有说错的。

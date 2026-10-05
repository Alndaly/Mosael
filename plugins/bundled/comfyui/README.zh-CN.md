# ComfyUI

把一台 ComfyUI(本机或局域网里的另一台)接进 Mosael。**随 Mosael 一起发**,装好就在插件页里,不用去市场找。
一个连接带来两样东西:**模型**(保存的每张工作流都是一个图像 / 视频生成模型)和**工具**(智能体和工作流直接用)。

## 怎么接

1. 插件页 → ComfyUI → 「新建连接」,填服务器地址(本机默认 `http://127.0.0.1:8188`)。放在要登录的反向代理或
   ComfyUI-Login 后面的,把 `用户名:密码`(Basic)或令牌(Bearer)填进凭据「访问凭据」,HTTP 和 WebSocket 都带上。
2. 授予它要的权限,打开连接(1.10.0 起如实申报五项):
   - `network:comfyui`:连这台 ComfyUI;
   - `network:huggingface`、`network:civitai`、`network:modelscope`:模型库解析链接、下载模型时连这几个站;
   - `filesystem:write`:ComfyUI 和 Mosael 在同一台电脑上时,把下载的模型写进它的 models 目录。

   **从旧版本升级**:升上来的连接会**先停用**,等你授予新增的那几项 —— 从 1.9 升上来的多一项 `network:modelscope`
   (1.10.0),从 1.8 及更早升上来的多四项。连接卡片最上面写着多要了哪几项,点「授予这 N 项」马上恢复,之前授予的
   不受影响;插件列表上它标着「待授权」。
3. 它在 ComfyUI 里**保存的每张工作流**会作为一个模型出现在 AI 工作台、画板、工作流「AI 生成素材」节点的
   模型选择器里;新存的工作流一分钟内出现(宿主每分钟问一次清单的指纹),等不及就在插件页点「刷新模型」。

多台服务器就建多个连接,各自一串模型。

**连不上时**(1.9.2),报错的第一行只说该做什么 ——「连不上这台 ComfyUI,确认它在运行、地址填对」;地址和原文
(`[Errno 61] Connection refused` 这类)在下一行,Mosael 收进「详情」或悬停说明里。
从 1.12.1 起,失败原因中英两种都交给 Mosael:连接卡片上的出错原因按你此刻的界面语言显示 —— 哪怕是在另一种语言下、
或者后台(启动时、目录变了)刷新出来的。

## 一张工作流变成一个模型时

| 工作流里的东西 | 在 Mosael 里 |
| --- | --- |
| 采样器 / 引导器上游写提示词的节点(CLIPTextEncode 及 Flux、SDXL 的变体,MiniMax H3 这类把提示词放在条件节点 `prompt` 上的,连进来的一段文字节点) | 主提示词、反向提示词 |
| 没有认得的采样器时(合作方 API 节点:MiniMax / 海螺、Kling、Veo…,WanVideoWrapper 这类自带采样器的包):接到产出上的节点里**多行**的 `prompt` / `prompt_text` / `positive_prompt`(1.6.0) | 主提示词;同一个节点上的 `negative_prompt` 是反向提示词 |
| 采样器的 seed、RandomNoise 的 noise_seed | 「随机种子」(不填每次随机) |
| 生成画布的节点(EmptyLatentImage、Wan / Hunyuan 的视频潜空间节点…)的宽高 | 「尺寸」(不选就用工作流自己的;工作流自己的尺寸和几档常用尺寸只是推荐,任意「宽x高」都收,每边四舍五入到 8 的倍数、至少 16,和工具的宽高同一个规矩,1.7.0) |
| 画布节点的 batch_size | 「张数」(最多 4,没选就是 1),几张全部交回 |
| 没有画布(局部重绘、图生图这类从读进来的图出发的)、但有种子的出图工作流 | 「张数」照样有(1.7.0):**循环提交 N 次**,一次跑完再提交下一次,每次换一个种子 —— 给了种子就从它开始依次 +1,没给就每次随机;每张的种子跟着产出交回(进生成记录 / 工具结果的 `seeds`)。取消时剩下的不再提交、在跑的那次中断;某一次失败,出来的照样交回,并说明「N 张里出了几张、第几张为什么没出来」;Mosael 重启时接着等在跑的那一次、再把剩下的跑完。没有种子的(放大)跑 N 遍也是同一张,不给张数 |
| 这一种的保存节点(一个都没存就是预览节点) | 一次交回几份(`outputs_per_run` = 节点数,× 张数),宿主据此一次摆好占位;不止一个时「参数」里有一项「结果取自」(节点标题,缺省「全部」),选了一个就只交回它的,别的保存节点不跑(1.6.0) |
| 其余可调的字面量输入 | 参数表里的一项:认得的输入用人话起名(`labels.py`:采样器、步数、LoRA…),撞名才带上节点标题或「第 2 个 KSampler」;常用的在前,其余收进「高级」;原始的「节点 · 输入名」在说明里 |
| LoadImage 节点 | 参考图;视频图里接到 `start_image` / `first_frame` / `start_frame` / `first_frame_image`…的是首帧,`end_image` / `last_frame` / `end_frame`…的是尾帧(先过一道缩放、裁切再接进去的也算;图生视频的首帧必须给,1.6.1) |
| LoadImageMask,或只用了 LoadImage 蒙版那一路的 | 蒙版(`mask`) |
| LoadVideo / VHS_LoadVideo | 待编辑的视频(`source_video`,模式 `video-edit`);接在 `ref_videos.*` 这类**参考**口上的是参考视频 |
| LoadAudio / VHS_LoadAudioUpload | 驱动音频(视频图)/ 参考音频;接在参考口上的是参考音频 |
| 视频输出节点(VHS_VideoCombine、SaveVideo…;CreateVideo 只是把帧合成一段交下去,不算) | 这是一个视频模型 |

没有提示词、也没有画布的图(放大、抠图):图是必须给的,模式只有 `image-to-image`。文件名前缀这类
ComfyUI 那一侧的输入不列出来。

只看 ComfyUI **真会跑**的那部分图(1.6.1):能跑的输出节点和它们的上游。悬空的画布节点不是「尺寸」「张数」,
下游全被旁路的读图节点不是一格输入,上游被静音断了线的预览不算进「一次交回几份」;rgthree 的 Relay / Repeater
这类前端虚拟节点不进图。

**只预览预处理结果的预览节点不是产出**(1.7.0):图里有解码节点(类名带 `Decode`:VAEDecode、VAEDecodeTiled、
WanVideoDecode…,说明这是一张会生成东西的图),而一个 PreviewImage / PreviewAudio 的上游一个解码节点都没经过 ——
它看的是 LoadImage 读进来的原图,或预处理器(OpenPose 骨架、Canny 线稿、深度图)从它算出来的东西,采样没参与。
它不算输出,不跑,它上游那条预处理的支路(和只喂给它的读图节点)也随之不在图里。只看连线,不看节点标题;整张图
都没有解码节点的(放大、抠图、合作方 API 节点)不判,预览照旧是产出。

另有两个模型:**内置文生图**(服务器上至少有一个 checkpoint 时)和**API 模板**(连接配置里粘贴了
「导出 (API)」的 JSON 时,`{{prompt}}` `{{negative}}` `{{seed}}` `{{width}}` `{{height}}` `{{steps}}`
占位符照旧;这个配置项是 `type: "json"`,插件页给代码编辑器并在保存前校验)。

## 工具

**每张工作流一个工具**(`wf_<id>`,「工作流 · 名字」,见 `tools/tooling.py`):插件在 `op: tools` 里报给宿主
(宿主能力 `tools`,和 `generation` 由同一个 `comfyui_generation` 认领),入参、输出都从那张图推 ——
提示词、每个读素材的节点(`image_10`、`mask_11`、`video_1`…)、每个可调参数(`steps_3`…,和生成参数同一套名字)、
种子 / 尺寸 / 张数(高级;张数缺省 1,和生成一致,1.7.0);输出按输出节点(`image_9`、`text_40`…),外加给工作流连线用的 `asset_id` / `asset_ids` /
`texts` / `summary` / `prompt_id`(声明成 `wiring_outputs`:画板上只落每个输出节点自己的产出,`board_outputs`)。
名字取 ComfyUI 写在工作流文件里的 id(改名、挪目录不变),没有的退到路径哈希;模板是 `wf_api_template`,内置文生图是
`wf_builtin_txt2img`。

**和生成模型是同一件事的图声明 `mirrors`**:模型目录里有的每张工作流(交得出文件的,`graph.media_outputs`)的工具都带着
`{"generation_model": <模型 id>, "kind": …}` 和入参到生成表单的对照(提示词、素材角色、alpha 的蒙版 → `mask`、
`steps_3` → `3.steps` 这类参数键;宽高对不过去)。宿主据此在画板上只留生成那一个入口(图片 / 视频格的模型下拉里),
「…」里不再列「工作流 · 名字」、存着的工具格改写成生成格;工作流、智能体里这个工具照旧在(它多做的 —— 交回全部输出
节点、显示出来的文字、预览 —— 留在那边)。1.6.0 起几个保存节点的图(生成那一路有「结果取自」)、拿 alpha 当蒙版的图
(模型有蒙版槽)也声明;1.5.x 只在「一个存下来的输出节点、没有文字、没拿 alpha 当蒙版」时才声明,两个保存节点的图于是
画板上两个入口。**只交出一段字的图(打标签、反推提示词)不进模型目录**,只是工具,画板上照旧是格子的一项能力。

以前还有一个通用的 `run_workflow`(按 id 跑,入参是写死的一张表):它不知道要跑哪张图,表单却要人填参数,
1.4.0 删掉了。它能跑的每一种图在上面都有自己的工具;每个工具带着 `replaces`,宿主据此把存着的 `run_workflow`
节点和画板工具格改写过来(`values` 按节点 id 或节点标题写的都认;新工具里没有位置的几格丢掉,记进修订说明)。

固定的那几个:

| 工具 | 只读 | 流式 | 默认开 | 做什么 |
| --- | --- | --- | --- | --- |
| `list_workflows` | ✓ | | ✓ | 每张工作流收什么(哪个节点读哪种素材)、能调什么、交出什么、`features`(upscale / inpaint / img2img / remove-background / …),以及跑它的工具(`tool`);转不过来的也列,带原因;工作流目录里的压缩包这类非 .json 文件也列出来,说为什么用不了(1.6.1) |
| `import_outputs` | | ✓ | ✓ | 按任务号(可等 `wait_seconds`)或最近 `last` 次,把历史里的产出收进素材库。任务号声明成 `format: "external_id"`:这是按 ComfyUI 里的编号取东西,不是内容变换,只在工作流和对话里用,不上画板 |
| `server_status` | ✓ | | ✓ | 版本、显卡与空闲显存、内存、队列 |
| `list_models` | ✓ | | ✓ | `/models` 下的模型文件;老版本没有这个接口时看加载节点的下拉 |
| `interrupt` | | | ✓ | 停下正在跑的;给了 `prompt_id` 只停那一个 |
| `clear_queue` | | | | 清掉排队中的(别人的也会被清) |
| `free_memory` | | | | `/free`:卸载模型、释放显存 |

工作流的工具一次最多跑 30 分钟(`timeout_seconds: 1800`),交回**全部**产出(`artifacts` → 宿主换成 `assets` /
`asset_ids`)、文字产出、按节点分的摘要;占的是显卡,标 `effects: "paid"` —— 智能体调它先开确认卡,批准后在后台跑,
不占智能体那一次调用的等待时间。更久的走生成(6 小时、有回执、能续等)。

## 模型库(1.8.0)

插件页上这个连接的「模型库」:这台 ComfyUI 上的全部模型文件,按目录分页签、按底模筛、能搜;有预览图的用预览图(同名的
png / jpg / webp,或 safetensors 里的封面),没有的是按目录分的占位。点开一个看完整的元数据、触发词、哪几张工作流在用。
决策见 Mosael 仓库的 ADR 0034。

**底模家族怎么认**(认到为止,界面上写明凭的是什么;规矩在 `tools/families.py`):

1. 文件头里的 `ss_base_model_version`(kohya 训练脚本写的,最具体)。训练脚本不认识的底模(实测有 anima),
   `modelspec.architecture` 会照默认写成 `stable-diffusion-v1` —— 所以先看它;
2. 没有时看 `modelspec.architecture`;
3. 认出是 SDXL 的,训练用的底模名(`ss_sd_model_name`)或文件名里带 illustrious / noob / pony 的,细分成那一支;
4. 都没有时看文件名(连子目录)里的关键词:`illustrious` / 单独的 `IL` → Illustrious、`noob` → NoobAI、`pony` → Pony、
   `kontext` → Flux Kontext、`flux` → Flux、`wan2.2` → Wan 2.2、`wan2.1` → Wan 2.1、`qwen_image` → Qwen-Image、
   `z_image` → Z-Image、`hunyuan` → HunyuanVideo、`ltx` → LTX-Video、`sdxl` / 单独的 `xl` → SDXL、`sd15` / `v1-5` → SD 1.5……
   只在放「给某个底模用的东西」的目录里按名字猜(checkpoints、loras、diffusion_models、controlnet、embeddings、vae……),
   文本编码器、放大、检测模型不猜;
5. 元数据里写了、表里没有的值(anima、krea2)原样显示;什么都没有就空着。

**触发词**:作者写在文件头里的(`modelspec.trigger_phrase` / `ss_trigger_words`);没有时取训练标签(`ss_tag_frequency`)
里出现最多的几个,并标明「不一定是作者指定的触发词」。**在用的工作流**:保存的工作流里,节点输入写着这个文件名的。
**工作流缺的模型**:工作流声明了下载地址(节点 `properties.models`,或新格式的顶层 `models`)、节点当前真在用、这台服务器
上又没有的;只认 `https://huggingface.co/`、`https://civitai.com/`(ComfyUI 官方前端的白名单)和 ModelScope 的
`https://modelscope.cn/`、`https://modelscope.ai/` 的地址(1.10.0)。
Civitai 的另外几个域名(`civitai.red`、`civitai.green`)是同一个站:贴进来的链接、工作流里写的地址都先换成 `civitai.com`
再解析和下载,令牌也只交给 `civitai.com`(1.9.1);ModelScope 带 `www.` 的同样先去掉。

逐个读的元数据按「服务器 + 目录 + 名字 + 大小 + 改动时间」记在插件的持久目录里:第一次几百个文件要几秒,之后只读目录。

**下载**:贴一个链接 —— HuggingFace 的文件(`/blob/` 或 `/resolve/`)、Civitai 的模型页(带不带 `modelVersionId`)或
下载链接、ModelScope(魔搭)的模型页或文件、别的直链 —— 先解析出文件名、大小、建议放进哪个目录(Civitai 按模型类型定;
ModelScope AIGC 专区的模型按登记的类型定;HuggingFace / ModelScope 文件路径里正好有这台服务器上的某个目录名时建议它;
别的自己选),确认后下到**那台 ComfyUI** 上。

**ModelScope**(1.10.0):认模型页 `/models/{仓库}`(及「模型文件」这些页签)、目录页 `/tree/{版本}/{目录}`、文件页
`/file/view/{版本}/{路径}`、直链 `/resolve/{版本}/{路径}`,以及官方 SDK 的下载地址 `/api/v1/models/{仓库}/repo?FilePath=`。
贴的是模型页或目录页时,里面只有一个模型文件(`.safetensors`、`.ckpt`、`.gguf`、`.pt`、`.pth`、`.bin`)就是它;有好几个
就列出候选、请你贴具体那个文件的地址。AIGC 专区的模型:类型 Checkpoint / LoRA / VAE → checkpoints / loras / vae,登记的
底模类型(`VisionFoundation`)和底模仓库(`BaseModel`)按上面同一张家族表认,作者写的触发词、中文名一并带上;普通仓库
不猜家族。国际站 `modelscope.ai` 是另一个站(接口一样,模型和账号各是各的),各问各的,不互相改写。下载走 `/resolve/`
直链(大文件它会跳到签好名的 CDN 地址,那一跳不带令牌)。

下载按优先级走:

1. ComfyUI 自己的下载接口 —— 0.38.0 没有;
2. **ComfyUI-Manager(V4)**:那台机器自己下,看不到字节进度,开始之后停不下(Manager 没有停单个任务的接口,取消只是
   Mosael 不再等)。它的安全策略只在 ComfyUI 监听本机地址、或 `user/__manager/config.ini` 里 `network_mode = personal_cloud`
   时才放行 —— 用 `--listen 0.0.0.0` 开着的局域网 ComfyUI 默认不让,插件把日志里的原因说成人话,并记下来,下次在模型库里
   提前提醒;
3. **ComfyUI 就在这台电脑上**(它报的模型目录在本机存在,且本机的文件和它报的一致):直接写进去,先写 `名字.mosael-part`、
   下完挂上正式的名字;按字节报进度、能取消(只删自己的半截文件);开始前查剩余空间,不够就不下;
4. 都不行:说清楚,并给出能做的那一步(装 Manager、改 `network_mode`、或手动把直链下到 `models/<目录>/`)。

**不覆盖任何已有文件**:同名的先要求换名(给一个 `名字 (1).扩展名` 的建议),写盘时再查一遍(硬链接挂正式名字,目标已在就失败)。
不删、不改名、不移动模型文件;不装自定义节点、不改 Manager 的配置。

**生成表单里选模型文件**(1.9.0):工作流里选大模型、LoRA、VAE、文本编码器……的那一格,模型参数上写明是哪个模型目录的
文件(`x-model-folder`,按输入名认,同名输入按节点分:CLIPLoader 的 `clip_name` 是 text_encoders,CLIPVisionLoader 的
是 clip_vision)。AI 工作台、画板、工作流节点据此从这个连接的模型库取:下拉里每一项有缩略图(没有就是按目录分的
占位)、底模和前几个触发词,也能按它们搜;选中带触发词的 LoRA,下面一行列出触发词,点「加进提示词」接在提示词末尾
(已经有的不重复加)。

**经 ComfyUI-Manager 下载时**,下载框里先说清楚:要带 Civitai 令牌时它会拼进下载地址、留在那台机器的 Manager 任务
记录里;HuggingFace、ModelScope 的令牌带不过去(Manager 不收请求头,这两个站的令牌又没有放进地址的用法),
要令牌才能下的文件会失败;看不到按字节的进度;开始之后取消,那台机器上的下载还会继续。Manager V4 装模型不挑站点
(只看它的安全策略),ModelScope 的直链它照样下。解析 Civitai、ModelScope 链接时先不带令牌问(公开的模型不用登录),对方说要登录才再带上
(ModelScope 对看不到的私有模型回 404,所以 404 时也带上再问一次)。

**凭据**:要同意条款或私有的 HuggingFace 仓库,在连接上填「HuggingFace 令牌」;要登录的 Civitai 模型填「Civitai 令牌」;
私有或要授权的 ModelScope 模型填「ModelScope 令牌」(在 modelscope.cn/my/myaccesstoken 拿;按 `Authorization: Bearer`
和会话 cookie `m_session_id` 两样发,和官方 SDK 一样;国际站的账号和令牌另算)。令牌只发给它自己那个站(ModelScope 的
发给 modelscope.cn / modelscope.ai;跳转到别处的存储时不带),不进结果和报错;经 Manager 下 Civitai 时只能拼进下载地址,
会留在那台机器的 Manager 任务记录里。

## 工作流库(1.11.0)

插件页上这个连接的「工作流库」:这台 ComfyUI 上存着的全部工作流(ADR 0035),和模型库同一套界面 —— 左边按子目录,
上面搜索、按种类筛、排序、三档显示方式。每张一张卡:节点图的缩略预览(照工作流里节点的位置和连线画,不截 ComfyUI 的图;
API 格式的图没有位置,按依赖自动排)、识别出的输入 / 参数 / 输出、用到的模型(在不在)、缺的节点(和它出自哪个节点包,
Manager 的映射查得到就列)、声明了下载地址又缺的模型。

缺节点的判据:节点类型不在这台 ComfyUI 的 object_info 里,**且**不是只在前端的节点(Note、Reroute、PrimitiveNode、
KJNodes 的 Set / Get、rgthree 的 Fast Groups Bypasser / Label / Bookmark 这类,后端永远没有),子图实例也不算。

在 Mosael 里能直接改那台机器上的工作流文件,都经 ComfyUI 自己的 userdata 接口、**不覆盖**:

- 复制(副本换一个新的图 id —— 两张同 id 的图,插件给它们起的工具名会撞)、改名 / 挪目录:目标已经有了就说撞名,给一个
  建议名;
- 删除**不硬删**(ComfyUI 的 DELETE 是硬删,插件从不调):挪进用户目录下的 `.mosael-trash/workflows/<删除时刻 UTC>/<原路径>`,
  在 `workflows/` 外面,ComfyUI 的侧栏和插件的模型清单都不列它;Mosael 的「回收站」能恢复,原处被占了就要求换名。真要
  删掉,在那台机器上删这个目录;
- 每次改完,宿主让这个连接的模型和工具清单马上重拉一遍。

「在编辑器里打开」(1.11.1):列出时插件顺带报这台 ComfyUI 的网页地址。Mosael 桌面版在这个连接自己的内嵌浏览器里打开
它的界面,页面就绪后经 ComfyUI 前端自己的工作流列表打开那一张(ComfyUI 的地址只认模板、分享和图 id,打不开一张存着的
工作流);网页版开一个新标签页,说清楚在左边「工作流」里点开哪一张。在 ComfyUI 里存好、回到 Mosael,工作流库和这个连接
的模型、工具清单跟着重拉。ComfyUI 放在要登录的反向代理后面时,第一次要在那个内嵌浏览器里登一次。

## 导入并补齐(1.12.0)

工作流库里的「导入」:拖进来、选文件、贴 JSON 或链接都行。

- **认得什么**:ComfyUI 界面里「保存 / 导出」的 JSON、「导出 (API)」的 JSON;ComfyUI 存出来的 PNG / WebP(图里嵌着工作流,
  有界面格式就用界面格式,只有 API 格式的那份就按 API 格式);压缩包(取第一张,别的写在说明里);链接只取 HuggingFace、
  Civitai、ModelScope 和这台 ComfyUI 自己的地址(插件声明过的网络权限就这几处),网页不是文件会说清楚。
- **API 格式没有布局**:按这台 ComfyUI 的节点定义把值排回去、按连线接好、按依赖从左往右排位置,存成界面格式 —— ComfyUI
  的侧栏才打得开,插件才认得;预览里写明位置是自动排的。经 Mosael 跑出来的图里只有 API 格式(插件提交时没带界面格式的
  那份),拖回来导入也是这样。
- **存之前先预览**:节点图、识别出的参数、缺的节点和节点包、缺的模型;存进 `workflows/` 不覆盖(撞名给建议名),换一个新的
  图 id(和原来那张的工具名不撞)。
- **缺的节点包**:装了 ComfyUI-Manager(V4)的,确认后经它一个个装(registry 上有的按最新版,只在 git 上的按 git 装);装完要
  重启 ComfyUI 才加载,重启也经 Manager(再确认一次,正在跑的任务会中断)。Manager 的安全策略:装节点包要 ComfyUI 只监听
  本机、或 `network_mode = personal_cloud`;重启要 `security_level` 不比 normal 严 —— 被拒时会说怎么改、或者怎么手动装。
- **缺的模型**:声明了下载地址的,在模型库里一键下载(同一个下载框、同一条路)。

## 进度、取消、重启

- 进度来自 ComfyUI 的 WebSocket:哪个节点在跑(用界面上的节点名)、采样器第几步、第几个节点;连不上就退回轮询。
  新版 ComfyUI 的 `progress_state` 也认。
- 取消(生成任务、流式工具)时,插件会让 ComfyUI 停下**这一个**任务(在跑的 interrupt,在排队的从队列删掉),
  不会掐掉同一台机器上别人的任务。
- Mosael 重启时正在跑的生成会接着等(按任务号),不会重新提交。
- 提交之前先对着 object_info 看这台 ComfyUI 有没有这张图要的节点和模型文件,缺的一次列全、什么都不排上;一部分输出
  校验不过时 ComfyUI 会照样排上、只跑过了的那几个 —— 插件把它撤掉并说出原因,不把剩下那个预览当成结果(1.6.1)。

## 代码

`tools/` 只用 Python 标准库:

- `convert.py` —— 保存的工作流(UI 图)→ `/prompt` 吃的 API 图,照 ComfyUI 前端 graphToPrompt 的语义:widget 值按
  节点定义排(老版本前端存的图也认)、静音的断开、旁路的直通、Reroute / PrimitiveNode / Get·Set 这些前端节点消掉、
  子图展开成「外层 id:里层 id」;
- `graph.py` —— 看出提示词 / 种子 / 尺寸 / 槽位 / 输出节点、描述成模型、填图、收产出;
- `labels.py` —— 可调输入的人话名字、顺序、常用与否、不在 Mosael 里调的那几个;
- `models.py` —— 有哪些模型、一个模型 id 背后是哪张图、清单的指纹;
- `run.py` —— 传素材、提交、跟进度、取消、取回(生成与工作流的工具共用);
- `workflows.py` —— `list_workflows` / `import_outputs`,以及交回产出的那一段;
- `tooling.py` —— 每张工作流一个工具:从图推入参和输出、按当前的图跑;
- `server.py` —— `server_status` / `list_models` / `interrupt` / `clear_queue` / `free_memory`;
- `library.py` / `families.py` / `model_files.py` —— 模型库:列出模型文件、读元数据、认底模家族、找在用的和缺的;
- `sources.py` / `install.py` —— 解析 HuggingFace / Civitai / ModelScope / 直链,按 Manager → 同一台机器 → 说清楚 的顺序下载;
- `comfy_http.py` / `ws.py` —— 和 ComfyUI 说话。

协议见 Mosael 仓库的 `docs/PLUGIN_MANIFEST.md`「替宿主做生成」「流式工具」「一次交出几份」。

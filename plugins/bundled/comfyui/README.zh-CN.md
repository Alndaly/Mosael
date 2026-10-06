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
| 画布节点的 batch_size | 一遍出几张:**按工作流原样**,存着 4 就是一遍 4 张(1.12.3 起不再被「张数」改写) |
| 有种子的出图工作流(有没有画布都一样) | 「跑几遍」(参数键仍是 `num_images`,最多 4,没选就是 1,1.12.3):**循环提交 N 次**,一遍跑完再提交下一遍,每遍按工作流原样、换一个种子 —— 给了种子就从它开始依次 +1,没给就每次随机;每份产出带着它那一遍的种子(进生成记录 / 工具结果的 `seeds`)。一共交回「跑几遍 × 一遍几张」。取消时剩下的不再提交、在跑的那遍中断;某一遍失败,出来的照样交回,并说明「跑了 N 遍、出来几遍、第几遍为什么没出来」;Mosael 重启时接着等在跑的那一遍、再把剩下的跑完。表单上这一格叫「跑几遍」,下面写着一遍出几张、这次一共几张。没有种子的(放大)跑几遍都是同一张,没有这一格;视频图也没有 |
| 这一种的保存节点(一个都没存就是预览节点) | 跑一遍交回几张(`outputs_per_run` = 缺省交回的那几个节点各自收到的批量加起来,判不出批量的按 1;宿主乘上跑几遍一次摆好占位);不止一个时「参数」里有一项「结果取自」(节点标题),选了一个就只交回它的,别的保存节点不跑(1.6.0),每一项跑一遍交回几张写在 `x-outputs-per-run` 上。缺省「全部」;预览节点里有中间一步、控制图时缺省「最终结果」(1.12.2,见下) |
| 其余可调的字面量输入 | 参数表里的一项:认得的输入用人话起名(`labels.py`:采样器、步数、LoRA…),撞名才带上节点名或「第 2 个 K 采样器」;不认得的叫「节点名 · ComfyUI 给这一格的名字」;常用的在前,其余(和 ComfyUI 标了 `advanced` 的)收进「高级」,ComfyUI 标了 `hidden` 的不列;原始的「节点 · 输入名」在说明里 |
| LoadImage 节点 | 参考图;视频图里接到 `start_image` / `first_frame` / `start_frame` / `first_frame_image`…的是首帧,`end_image` / `last_frame` / `end_frame`…的是尾帧(先过一道缩放、裁切再接进去的也算;图生视频的首帧必须给,1.6.1);一个角色几个读图节点时(或者给节点起过名),每个槽位按顺序带名字(节点标题,没起名的是「加载图像 #10」这种节点名加节点号),AI 工作台、画板、工作流节点上标着(1.13.0) |
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

**缺省只交回最终结果**(1.12.2):只接了预览节点、图里有解码节点的工作流,「结果取自」缺省「最终结果(节点标题)」,
只交回最后那一个结果节点的图(几路各有最后一个时是那几个),一遍几张按它收到的批量。不是最终结果的有两种,在选项里标着:

- **中间一步**:一个预览显示的东西被**接着做下去**、成了另一个输出的图 —— 两遍出图(潜空间放大、像素放大后重绘)的
  第一遍、修脸(FaceDetailer)和放大之前的那张、拿去当 IP-Adapter 参考的那张、喂给 ControlNet 的控制图。显示的是解码
  出来的图时,第二遍接着采样那份潜空间也算;同一份潜空间换个解码节点再解一遍不算(看的还是同一遍)。
- **控制图、蒙版**:ControlNet 预处理器(comfyui_controlnet_aux,object_info 里类别是 `ControlNet Preprocessors`)
  算出来的骨架、深度图、线稿 —— MeshGraphormer 没认出手时那张手部深度图整张是黑的 —— 以及把一张蒙版(`MASK`)画成的图。
  它们从不当结果,也不让成图变成「中间一步」:从成图里抠一张蒙版、算一张深度图拿去看,成图照样是结果。

只看连线和节点定义(类别、插口类型),不看节点标题。中间一步、控制图、蒙版缺省不跑;要每个都交回就选「全部」,只要其中一个
就选它。目录里的 `outputs_per_run` 说的是缺省那一项的份数,没带「结果取自」的请求(AI 工作台只发动过的参数、智能体、
工作流节点)按同一个判据交回,摆的占位和「N×」对得上。**保存节点不挑**(工作流作者明说要存的,第一遍也存着的照样
交回),存下来的照旧压过预览;整张图都没有解码节点的(放大、预处理工具、合作方 API 节点)不挑。工作流工具
(「工作流 · 名字」)照旧原样交回全部输出节点。

另有两个模型:**内置文生图**(服务器上至少有一个 checkpoint 时)和**API 模板**(连接配置里粘贴了
「导出 (API)」的 JSON 时,`{{prompt}}` `{{negative}}` `{{seed}}` `{{width}}` `{{height}}` `{{steps}}`
占位符照旧;这个配置项是 `type: "json"`,插件页给代码编辑器并在保存前校验)。

## 工具

**每张工作流一个工具**(`wf_<id>`,「工作流 · 名字」,见 `tools/tooling.py`):插件在 `op: tools` 里报给宿主
(宿主能力 `tools`,和 `generation` 由同一个 `comfyui_generation` 认领),入参、输出都从那张图推 ——
提示词、每个读素材的节点(`image_10`、`mask_11`、`video_1`…)、每个可调参数(`steps_3`…,和生成参数同一套名字)、
种子 / 尺寸 / 跑几遍(高级;入参键仍是 `num_images`,缺省一遍,和生成同一个意思:每遍按工作流原样、换一个种子,1.12.3);输出按输出节点(`image_9`、`text_40`…),外加给工作流连线用的 `asset_id` / `asset_ids` /
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

插件页上这个连接的「模型库」:这台 ComfyUI 上的全部模型文件,左边一列按目录、按底模筛、能搜;有预览图的用预览图(同名的
png / jpg / webp,或 safetensors 里的封面),没有的是按目录分的占位。点开一个看完整的元数据、触发词、哪几张工作流在用。
决策见 Mosael 仓库的 ADR 0034。

**底模家族怎么认**(界面上写明凭的是什么;规矩在 `tools/families.py`,权重结构那张表在 `tools/weights.py`):

1. **元数据**:文件头里的 `ss_base_model_version`(kohya 训练脚本写的,最具体)。训练脚本不认识的底模(实测有 anima、
   krea2)它照写,`modelspec.architecture` 却照默认写成 `stable-diffusion-v1` —— 所以先看它;没有时看
   `modelspec.architecture`;都没有、又是 kohya 训的(有 `ss_network_*`)老 LoRA 只写了 `ss_v2`:`False` 是 SD 1,`True`
   是 SD 2。写法规整成家族名(`anima` → Anima、`krea2` → Krea 2、`qwen_image_2` → Qwen-Image 2);
2. **权重结构**(界面上写「从权重结构认出」):合并出来的大模型、不少 LoRA 一点元数据都没有,但文件头里的张量名和形状
   一看就知道是什么网络 —— SD 1 / SD 2 / SDXL 看交叉注意力吃的文本宽度(768 / 1024 / 2048),Flux 有 double_blocks /
   single_blocks,Flux.2 共用一份调制,Krea 2 的注意力多一个 gate,Anima 带 llm_adapter,Wan 的块里是 `self_attn.q` 和
   `ffn.0`,Z-Image 和 Lumina 同一种结构、宽度不同(3840 / 2304)……LoRA 照抄底模的层名,kohya、diffusers / peft、
   ComfyUI、LyCORIS 几种写法都认;GGUF 读张量表,认不出时看 `general.architecture`。和元数据对得上(一样,或元数据更细:
   权重只看得出 SDXL,元数据说 Pony)用元数据;**对不上架构时信权重**(实测有 Flux 的 LoRA 写着 sd_1.5)。分不清的少说:
   Wan 14B 的 2.1 和 2.2 结构一样,就说 Wan;AuraFlow(Pony V7 用的结构)的 diffusers 式 LoRA 也有
   single_transformer_blocks,认得出不是 Flux;
3. 认出的是 SDXL / Wan / Flux / AuraFlow 这一层时再细分:训练用的底模名(`ss_sd_model_name`,Civitai 在线训练写的是
   底模的版本号,Illustrious、Pony、NoobAI 的官方版本认得)、标题,再是文件名里的 illustrious / `IL` / `ILL` →
   Illustrious、noob → NoobAI、pony → Pony、kolors → Kolors、`wan2.2` / high noise / low noise → Wan 2.2、kontext →
   Flux Kontext、pony v7 → Pony V7;
4. 都没有时看**文件名**(连子目录,驼峰拆开 —— `novaAnimeXL_ilV160` 里的 XL、il 才算单独出现):`illustrious` / 单独的
   `IL` → Illustrious、`noob` → NoobAI、`pony` → Pony、`kontext` → Flux Kontext、`flux` → Flux、`krea2` → Krea 2、
   单独的 `anima` → Anima(animagine 不算)、`minimax_h3` → MiniMax H3、`qwen_image_2` / `qwen21` → Qwen-Image 2、
   `qwen` → Qwen-Image、`kolors` → Kolors、`wan2.2` → Wan 2.2、`wan2.1` → Wan 2.1、`z_image` / 单独的 `ZIT` → Z-Image、
   `hunyuan_video` → HunyuanVideo、`ltx` → LTX-Video、`sdxl` / 单独的 `xl` → SDXL、`sd15` / `v1-5` → SD 1.5……只在放「给某个底模用的东西」
   的目录里按名字猜(checkpoints、loras、diffusion_models、controlnet、embeddings、vae……);
5. 元数据里写了、表里没有、权重也认不出的值原样显示;什么都没有就空着(「认不出底模」)。
6. 文本编码器、CLIP 视觉、放大、检测 / 分割这类目录里的文件不是给某一个底模做的:不猜,标「不适用」(`family_source`
   是 `not_applicable`),和「认不出」分开。

**读文件头**:走 ComfyUI-Custom-Scripts 的 `/pysssss/view/`,按 Range 只读开头(safetensors 的头一般几十到几百 KB,
超过 8 MB 不读),一个文件几十毫秒、几个并发。没装它(404)或那台不认 Range(回 200 要整个发)时,第一个文件试过就不再试、
立刻挂断,退回 ComfyUI 的 `/view_metadata` 只拿元数据 —— 那样就认不了权重结构,装上之后下次打开会补认。

**同一个文件只列一次**:ComfyUI-GGUF 把 `unet_gguf` / `clip_gguf` 登记在和 `diffusion_models` / `text_encoders` 同一批文件夹
上,Impact Pack 的 `ultralytics` 包着 `ultralytics_bbox` / `ultralytics_segm` —— 按磁盘上的位置认,留在先登记的目录
(ComfyUI 自己的先登记);只有别名目录列着的(`.gguf`)照旧在那儿。

**触发词**:作者写在文件头里的(`modelspec.trigger_phrase` / `ss_trigger_words`);没有时取训练标签(`ss_tag_frequency`)
里出现最多的几个,并标明「不一定是作者指定的触发词」。**在用的工作流**:保存的工作流里,节点输入写着这个文件名的。
**工作流缺的模型**:工作流声明了下载地址(节点 `properties.models`,或新格式的顶层 `models`)、节点当前真在用、这台服务器
上又没有的;只认 `https://huggingface.co/`、`https://civitai.com/`(ComfyUI 官方前端的白名单)和 ModelScope 的
`https://modelscope.cn/`、`https://modelscope.ai/` 的地址(1.10.0)。
Civitai 的另外几个域名(`civitai.red`、`civitai.green`)是同一个站:贴进来的链接、工作流里写的地址都先换成 `civitai.com`
再解析和下载,令牌也只交给 `civitai.com`(1.9.1);ModelScope 带 `www.` 的同样先去掉。

逐个读到的原料(认底模、触发词、标题要用的那几项元数据,权重认成的家族,GGUF 的架构名)按「服务器 + 目录 + 名字 + 大小 + 改动时间」记在插件的持久目录里:第一次几百个文件要十来秒,之后只读目录。家族每次列出时现推,认的规矩改了马上生效;权重那张表一改,记着的整份作废、重读。

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
2. **ComfyUI 就在这台电脑上**(它报的模型目录在本机存在,且本机的文件和它报的一致):直接写进去,先写 `名字.mosael-part`、
   下完挂上正式的名字;按字节报进度、能取消(只删自己的半截文件);开始前查剩余空间,不够就不下。装了 ComfyUI-Manager
   也先走这条(1.13.2):Manager 那条路看不到进度、停不下,令牌还得拼进它的下载地址;
3. **ComfyUI-Manager(V4)**,ComfyUI 在另一台机器上时:那台机器自己下,看不到字节进度,开始之后停不下(Manager 没有停
   单个任务的接口,取消只是 Mosael 不再等)。它的安全策略只在 ComfyUI 监听本机地址、或 `user/__manager/config.ini` 里
   `network_mode = personal_cloud` 时才放行 —— 用 `--listen 0.0.0.0` 开着的局域网 ComfyUI 默认不让,插件把日志里的原因说成
   人话,并记下来,下次在模型库里提前提醒;
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

### 模型信息:NSFW、出处、在 Civitai 上找、预览视频(1.13.0)

决策见 Mosael 仓库 ADR 0038 §9。插件这一头交原料,宿主合成判断、取图、缓存、写回前确认。

- **NSFW 依据**(`nsfw_signals`,`tools/nsfw.py`):**元数据推断** —— 训练标签(`ss_tag_frequency`)里成人标签占到训练图的
  一成才算(偶然一两张不算),文件名、标题里的词(驼峰拆开)也算;**Civitai** —— 按哈希对上、或经 Mosael 从 Civitai 下的
  版本,模型标着 `nsfw`。宿主再加上手动标记和本机识别(都在 Mosael 那边),任一种说是就算是,手动的压过全部。
- **出处**(`source`,`tools/provenance.py`):经 Mosael 下载时记下的来源页(HuggingFace / ModelScope 的文件页、Civitai 的
  版本页),否则文件元数据里写着的、在 Civitai 上按哈希对上的。按「服务器 + 目录 + 名字 + 大小」记在持久目录里;文件换了
  (大小变了)就不算数。不按文件名猜一个链接。
- **在 Civitai 上找**(`{"op": "lookup"}`,`tools/lookup.py`):装了 ComfyUI-Custom-Scripts 时让那台机器算 SHA256
  (`GET /pysssss/metadata/<目录>%2F<名字>`,第一次要把整个文件读一遍,它把结果记在模型旁边的 `.sha256` 里),问 Civitai
  `/api/v1/model-versions/by-hash/{SHA256}` —— 对上的精确到版本;没装时在 Civitai 上按文件名搜,只认「Civitai 记的原始
  文件名一字不差、大小差不过 1 KB」**恰好一个**版本(标 `filename`,存回之前要用户确认),几个都像不认。查不到也记一笔,
  一阵子内不再让那台机器算一遍。对上的交来源页、模型的 NSFW 标记、Civitai 登记的底模(把只认到 SDXL / Wan / Flux 这一层的
  家族细分成 Illustrious、Wan 2.2……,凭的写 `civitai`)和几张示例(`remote_previews`:512 宽的图;示例只有视频的交
  `transcode=true,width=512` 的转码视频)。Civitai 的公开接口不要 API Key,请求带浏览器式的 User-Agent(默认的会被 403)。
- **存为预览图**(`{"op": "save_preview", "folder", "name", "path"}`,`tools/previews.py`):宿主把要存的那张(缩成
  512 宽的 PNG,或那段 512 宽的 mp4)放在 `path`,插件经 `/upload/image` 传进 temp,再 `POST /pysssss/save/<目录>%2F<名字>`
  `{"filename", "type": "temp"}` —— pysssss 把它拷到模型旁边,名字是模型的名字换上传那一份的扩展名(`x.png` / `x.mp4`)。
  这条路会覆盖同名的文件,所以宿主只在那台服务器上**没有**预览图时才调;那台 ComfyUI 没装 ComfyUI-Custom-Scripts 时
  `preview_tools.save` 是 false、`save_note` 说缺什么,界面置灰。看装没装:`GET /extensions` 里有没有它的
  `betterCombos.js`(写回、按名字读)和 `modelInfo.js`(算哈希)。
- **旁边的预览文件**(`sidecars`):和模型同名的 `.mp4` / `.webm` 预览视频,以及文件名带 `[ ]` 时的那几种图(ComfyUI 的
  预览接口按通配符找,带方括号的名字找不到)—— 列成相对 `sidecar_base`(`/pysssss/view/`)的一段,宿主在预览接口说没有
  之后按名字直接读。没装 pysssss 时不列。

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

文件夹(1.13.0):左边那一列是 `workflows/` 里的子目录树 —— 和 ComfyUI 自己的工作流侧栏同一份,不另记。列出时插件多报一份
`folders`(相对 `workflows/` 的全部子目录,`GET /api/v2/userdata?path=workflows` 列得出空的;老版本 ComfyUI 没有这个接口,
就只有装着文件的那几个)。三个 op 改它们,都不覆盖、改之前现查那台机器:

- `make_folder`:ComfyUI 没有建目录的接口 —— 往里面写一个隐藏的占位文件 `.mosael-folder`(写文件时 ComfyUI 建出父目录;
  ComfyUI 的侧栏和插件都不列隐藏文件)。已经有了(不分大小写比,那台机器可能是 Windows)回撞名和建议名;
- `rename_folder`:整个目录一次 `move`(ComfyUI 那边是 `shutil.move`,目录也挪得动),里面的工作流跟着换路径;目标已经有了
  回撞名,不合并进去;不能挪进自己里面;只改大小写时先挪到一个临时名字再挪过去(不分大小写的磁盘上目标「已经存在」);
- `trash_folder`:**只删空的**(里面没有一个看得见的文件,空的子文件夹不算),挪进回收目录 —— ComfyUI 删不了目录,插件也
  不硬删;里面还有文件回 `{"not_empty": true, "count": 几个}`,什么都不动。要删的文件夹里有工作流,先挪走或一张张删
  (各自确认、各自能恢复):一下子带走整个文件夹太容易误伤,里面不是工作流的文件(压缩包)进了回收目录,回收站也列不出来。

挪一张工作流到别的文件夹就是 `rename_workflow`(目标文件夹没有会被建出来);那张已经不在了(ComfyUI 回 404)说清楚,不报一句
HTTP 404。

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

## 应用表单(1.13.0)

对应 RunningHub 的「AI 应用」(ADR 0038 第一刀):作者从一张工作流**全部能填的项**里挑出要给别人填的几项、起名、排序、
收窄可选值,标哪个输出节点是结果,存成这张工作流的一张精简表单。AI 工作台、画板、工作流节点选这张工作流时都用这张表;
没有应用表单的工作流照旧全自动列出全部能填的项(那就是「缺省的应用」)。

- **在哪编**:工作流库 → 一张工作流的详情 →「应用」→「编辑应用表单」。左边「工作流里能填的」按节点分组、写着现在的值,点「+」
  放进表单;中间是表单卡片(拖动或 ↑ ↓ 排序、就地改名、设置里定主提示词和收窄可选值,空着时「按推荐先挑一版」)和「结果取自」;
  右边用生成面板同一套控件实时预览。网页版也能编,不依赖内嵌画布;工作台的「应用」面板是同一个编辑器,分成「挑项 / 表单 / 预览」
  三个标签。
- **节点叫什么**(`labels.node_name`,1.13.0):用户在 ComfyUI 里起的标题;没起就是 ComfyUI 给这类节点的名字 —— `/i18n` 里按语言的
  翻译(自定义节点包带的 locales)、常见核心节点的中文名(`CORE_NODE_ZH`,ComfyUI 的接口不带核心节点的中文)、object_info 的
  `display_name`;都没有才是类名。读 object_info 时顺手取一次 `/i18n` 并进去(`labels.with_i18n`),所以能填的项、撞名的提示、
  读素材的槽位、「结果取自」里的节点、工具的输出名说的是同一个名字。能填的项另带 `node_label`(编辑器按节点分组)和 `hint`
  (ComfyUI 给这一格的 `tooltip`,按语言);节点号、类名只给悬停的排错细节。
- **能填的项**(`graph.items`):此前生成目录、工具入参各推各的那几步收成一份。每项的锚点是 `<节点 id>.<输入名>`(图级的种子、
  尺寸、跑几遍没有节点),参数键和此前一样,画板、工作流节点里存着的值不用迁。子图里面的节点这一版不能放进表单。
- **表单里的项怎么进目录**:标了「主提示词」的文字格是 Mosael 的提示词框(同一角色几格写同一句话);别的文字、模型、数字、下拉、
  开关是参数表里的一项,用你起的名字、按你排的顺序,都在第一屏;收窄了可选值的下拉只剩那几项;读素材的节点是输入槽位,**每个
  槽位按顺序带名字**(你起的,没起就是节点名);种子、尺寸、跑几遍用 Mosael 自己的控件。应用名换掉模型下拉里那一项的名字。
- **没挑的项照工作流原样跑**:不进表单,也不被写 —— 没标主提示词的提示词格保留工作流里存的那句,没挑种子就照工作流自己的设定
  (固定的留着、每次随机的换一个),画板格子里存着的旧键不再写进图。工具(「工作流 · 名字」)的入参同样只剩表单那几项。
- **结果**:标成结果的输出节点就是「结果取自」的缺省(「你选的结果(节点名)」),不再猜;保存节点也能标(两个保存节点只要
  高清那张)。「结果取自」照旧能每次改。生成交回的每份产出带着它来自的节点(产出参数里的 `source_node`)。
- **存在哪**:这张工作流自己的 JSON —— 节点上 `properties.mosael`(`expose`:名字、顺序、主提示词、收窄的可选值;`result`)、
  图上 `extra.mosael`(`version`、应用名、说明、种子 / 尺寸 / 跑几遍)。ComfyUI 前端照原样存回这些扩展数据,所以复制、改节点号、
  导出、拷到另一台 ComfyUI 时表单跟着走,节点删了标记一起没;连同一台 ComfyUI 的每个人看到的是同一张表。
- **写回**:这是 Mosael **唯一一处覆盖写一张已有工作流**(`annotate`):只改 `mosael` 那几处标记,别的扩展写的键、节点、连线
  一个字都不动;每次都先确认,写明哪台服务器上的哪个文件;带着读到时的改动时间去,那张在这之间被改过(在 ComfyUI 里存过)就
  不写,说「它刚在 ComfyUI 里改过,重新打开再改」。它要是正开在 ComfyUI 里、又有没存的改动,在那边存的时候会盖掉这次改的。
- **失效的项**:每次描述都核对 —— 节点还在会跑的那部分图里(没静音、没旁路、接到了输出上)、那一格还是一个能填的值(没被拉成
  连线)、收窄的可选值还在下拉里。对不上的不进表单,工作流库的详情里列出来、能一键去掉。
- **版本**:`extra.mosael.version` 只认 `1`。别的版本按「没有应用表单」处理并提示;形状以后要变时,插件随新版本带一个改写那台
  机器上工作流文件的操作、确认一次改写 —— 读的一侧不认旧版。没有 `extra.mosael` 的图,节点上的标记不算(从别的工作流拷过来的
  节点带着的)。

## 工作台(1.13.0)

ADR 0038 的第二刀:Mosael 桌面版在这个连接自己的内嵌浏览器里全屏打开 ComfyUI 自己的画布(每个自定义节点照常能用),Mosael 的
面板停在右边 —— 模型库、缺失项、应用、运行与结果。和画布通话的是 Mosael 主进程注入的一段写死的脚本(只拉不推),插件这一侧
只多了几个不碰那台机器上文件的 op:

- `node_folders`:画布上选中的节点那几格(节点类型 + 输入名)各选的是哪个模型目录的文件 —— 和生成表单的 `x-model-folder`
  同一张对照(`labels.model_folder`),只查表。
- `search_sources`:缺的模型工作流里没写下载地址时,按文件名(完整的名字 → 去掉扩展名 → 再去掉精度后缀)去 Civitai、HuggingFace、
  ModelScope 搜,交回候选(哪家、仓库、确切的文件名、大小、底模、能交给下载的链接);文件名一致的在前、标 `exact`,相近的从不标。
  一家没搜成放进 `failed`,别的照常;结果在插件数据目录里记 10 分钟。不碰那台 ComfyUI。
- `app` 带 `content`:读的是画布上现在这张(含没存的改动),回答和读文件一样,没有路径和改动时间。
- `app_marks`:应用表单 / 结果标记写进画布要改成的那几处(每个带标记的根图节点上的 `properties.mosael`、图上的 `extra.mosael`)。
  和 `annotate` 写文件是同一个函数(`app_form.apply`),标记的格式只在一处;改画布、存盘是 ComfyUI 自己的保存。
- `generate` 带 `graph`(`prompt` / `workflow` / `client_id`):跑画布上现在这张,不读文件、不填参数;提交前照样查一遍缺的节点
  和模型;`client_id` 用前端的那个(画布上照常亮起正在跑的节点),`extra_pnginfo.workflow` 带上界面格式(产出拖回 ComfyUI 有布局);
  只按历史轮询跟到完成,**不开 WebSocket** —— ComfyUI 一个 `client_id` 只留一条连接,后连的会把画布那条挤掉。交回这一种的全部产出,
  各带来自哪个节点(`source_node`),工作台按节点分组、给「只要这个节点的图」。重启后接着等照旧按任务号。

测过的前端版本:ComfyUI 0.38.0 / 前端 1.53.10(只读核对:桥的注入、探测、选中、导出、`graphToPrompt`、脏标记,以及「触控板 /
鼠标」那个设置的键名和它要写回服务器的两条请求;没有排任务、没有存任何东西)。前端缺了桥要用的哪一样,对应的面板说「不支持」,
画布照常能用。

## 本机 ComfyUI:选目录,由 Mosael 起停(1.14.0)

装过 ComfyUI 的,不用再开终端:连接页「在哪跑」选「用我自己装的」,填它的目录(ADR 0041)。

- **先确认再运行**:点「检查并使用」先问一次(会在这台机器上运行那个目录里的代码),确认后插件认一遍目录 —— 有 `main.py` 和
  `comfy/` 的那一层;Windows 便携版选外层的 `ComfyUI_windows_portable` 或里面的 `ComfyUI` 都行。解释器按顺序找:你指定的、
  便携版自带的 `python_embeded\python.exe`、目录里或上一层的 `venv` / `.venv`(Windows 是 `Scripts\python.exe`)。试跑一次
  `import torch`(30 秒上限),摆出 ComfyUI 版本、Python、PyTorch、显卡(MPS / CUDA / 只有 CPU)和显存、Manager(pip 包 / 老式
  节点 / 没装)、pysssss;导入不了 torch 就不让用。torch 能导入还不够:ComfyUI 的 requirements.txt 里必需的包
  缺哪几个也查(只认装没装,不比版本),缺了同样不让用,写明在哪个环境里 `pip install -r requirements.txt`。
- **起的命令**:`python main.py --listen 127.0.0.1 --port <端口>`,装了 Manager 的 pip 包(`comfyui_manager`)才加
  `--enable-manager`,便携版照它自己的启动脚本加 `-s`;「高级」里的附加参数接在后面(端口、监听地址不许写在那里)。不改它的任何文件。
  端口 Mosael 建的时候选(8189 往上第一个空的)、写进服务器地址;改端口时插件把按旧地址存的本地数据(模型库缓存、工具对照)搬过去。
- **用到时起、退出时停**,崩了 Mosael 自己重起;装完节点包要重启时,本机这台由 Mosael 停了再起,不经 Manager 的重启。
- **补装 pysssss**:没装就在连接页上说明少了什么;点「补装」并确认后,下载钉死的提交(`609f3af`,按 sha256 校验)解到
  `custom_nodes/ComfyUI-Custom-Scripts`,下次启动生效。
- **本机发现**:插件页上探一下本机 8188 和 8000(官方 Desktop 的缺省端口)的 `/system_stats`,有 ComfyUI 就提示「要连上吗」——
  建的是「连一台服务器」那一种。

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
- `graph.py` —— 看出提示词 / 种子 / 尺寸 / 槽位 / 输出节点,收成一份能填的项(`items`)和表单(`Form`)、描述成模型、填图、收产出;
- `app_form.py` —— 应用表单:读、核对、写工作流里 `mosael` 那几处标记;
- `workbench.py` —— 工作台要插件回答的:选中节点那一格是哪个模型目录、应用表单写进画布要改的那几处标记;
- `labels.py` —— 可调输入的人话名字、顺序、常用与否、不在 Mosael 里调的那几个;
- `models.py` —— 有哪些模型、一个模型 id 背后是哪张图、清单的指纹;
- `run.py` —— 传素材、提交、跟进度、取消、取回(生成与工作流的工具共用);
- `workflows.py` —— `list_workflows` / `import_outputs`,以及交回产出的那一段;
- `tooling.py` —— 每张工作流一个工具:从图推入参和输出、按当前的图跑;
- `service.py` —— 本机服务:认目录(便携版、venv、试跑 torch)、给出启动命令、补装 pysssss、本机发现、改端口时搬数据;
- `server.py` —— `server_status` / `list_models` / `interrupt` / `clear_queue` / `free_memory`;
- `library.py` / `families.py` / `weights.py` / `model_files.py` —— 模型库:列出模型文件、读文件头(元数据、张量表)、认底模家族(元数据、权重结构、文件名)、找在用的和缺的;
- `sources.py` / `install.py` —— 解析 HuggingFace / Civitai / ModelScope / 直链,按 同一台机器 → Manager → 说清楚 的顺序下载;
- `civitai.py` / `lookup.py` / `nsfw.py` / `provenance.py` / `previews.py` —— 模型信息:Civitai 的接口和回答的形状、按哈希或
  文件名找、NSFW 依据、出处、旁边的预览文件和写回预览图;
- `json_style.py` —— 照工作流原来的排版写回(`annotate` 只改 `mosael` 那几处标记,别的字节一个不变);
- `comfy_http.py` / `ws.py` —— 和 ComfyUI 说话。

协议见 Mosael 仓库的 `docs/PLUGIN_MANIFEST.md`「替宿主做生成」「流式工具」「一次交出几份」。

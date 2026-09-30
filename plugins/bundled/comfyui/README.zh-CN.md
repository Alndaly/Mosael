# ComfyUI

把一台 ComfyUI(本机或局域网里的另一台)接进 Mosael。**随 Mosael 一起发**,装好就在插件页里,不用去市场找。
一个连接带来两样东西:**模型**(保存的每张工作流都是一个图像 / 视频生成模型)和**工具**(智能体和工作流直接用)。

## 怎么接

1. 插件页 → ComfyUI → 「新建连接」,填服务器地址(本机默认 `http://127.0.0.1:8188`)。放在要登录的反向代理或
   ComfyUI-Login 后面的,把 `用户名:密码`(Basic)或令牌(Bearer)填进凭据「访问凭据」,HTTP 和 WebSocket 都带上。
2. 授权 `network:comfyui`,打开连接。
3. 它在 ComfyUI 里**保存的每张工作流**会作为一个模型出现在 AI 工作台、画板、工作流「AI 生成素材」节点的
   模型选择器里;新存的工作流一分钟内出现(宿主每分钟问一次清单的指纹),等不及就在插件页点「刷新模型」。

多台服务器就建多个连接,各自一串模型。

## 一张工作流变成一个模型时

| 工作流里的东西 | 在 Mosael 里 |
| --- | --- |
| 采样器 / 引导器上游写提示词的节点(CLIPTextEncode 及 Flux、SDXL 的变体) | 主提示词、反向提示词 |
| 采样器的 seed、RandomNoise 的 noise_seed | 「随机种子」(不填每次随机) |
| 生成画布的节点(EmptyLatentImage、Wan / Hunyuan 的视频潜空间节点…)的宽高 | 「尺寸」(不选就用工作流自己的) |
| 画布节点的 batch_size | 「张数」(最多 4),几张全部交回 |
| 其余可调的字面量输入 | 参数表里的一项:认得的输入用人话起名(`labels.py`:采样器、步数、LoRA…),撞名才带上节点标题或「第 2 个 KSampler」;常用的在前,其余收进「高级」;原始的「节点 · 输入名」在说明里 |
| LoadImage 节点 | 参考图;视频图里接到 `start_image` / `end_image` 的是首帧 / 尾帧 |
| LoadImageMask,或只用了 LoadImage 蒙版那一路的 | 蒙版(`mask`) |
| LoadVideo / VHS_LoadVideo | 待编辑的视频(`source_video`,模式 `video-edit`) |
| LoadAudio / VHS_LoadAudioUpload | 驱动音频(视频图)/ 参考音频 |
| 视频输出节点(VHS_VideoCombine、SaveVideo…) | 这是一个视频模型 |

没有提示词、也没有画布的图(放大、抠图):图是必须给的,模式只有 `image-to-image`。文件名前缀这类
ComfyUI 那一侧的输入不列出来。

另有两个模型:**内置文生图**(服务器上至少有一个 checkpoint 时)和**API 模板**(连接配置里粘贴了
「导出 (API)」的 JSON 时,`{{prompt}}` `{{negative}}` `{{seed}}` `{{width}}` `{{height}}` `{{steps}}`
占位符照旧;这个配置项是 `type: "json"`,插件页给代码编辑器并在保存前校验)。

## 工具

**每张工作流一个工具**(`wf_<id>`,「工作流 · 名字」,见 `tools/tooling.py`):插件在 `op: tools` 里报给宿主
(宿主能力 `tools`,和 `generation` 由同一个 `comfyui_generation` 认领),入参、输出都从那张图推 ——
提示词、每个读素材的节点(`image_10`、`mask_11`、`video_1`…)、每个可调参数(`steps_3`…,和生成参数同一套名字)、
种子 / 尺寸 / 张数(高级);输出按输出节点(`image_9`、`text_40`…),外加给工作流连线用的 `asset_id` / `asset_ids` /
`texts` / `summary` / `prompt_id`(声明成 `wiring_outputs`:画板上只落每个输出节点自己的产出,`board_outputs`)。
名字取 ComfyUI 写在工作流文件里的 id(改名、挪目录不变),没有的退到路径哈希;模板是 `wf_api_template`,内置文生图是
`wf_builtin_txt2img`。

**和生成模型是同一件事的图声明 `mirrors`**(1.5.0):只有一个**存下来的**输出节点、交出的是图 / 视频 / 音频、没有
文字产出、没有「拿 LoadImage 的 alpha 当蒙版」那一格的工作流(1.5.2 起预览节点不算:PreviewImage、关了 `save_output`
的视频合成写的是临时文件,生成跑完不交回它们(`graph.collect_outputs`),工具缺省也不交回 —— 判据是
`graph.generation_nodes`,和生成收文件的是同一条;「保存 + 看一眼线稿的预览」的 ControlNet 图因此也是生成模型),工具带着 `{"generation_model": <模型 id>, "kind": …}` 和入参到生成表单的对照
(提示词、素材角色、`steps_3` → `3.steps` 这类参数键;宽高对不过去)。宿主据此在画板上只留生成那一个入口、把存着的
工具格改写成生成格;工作流里两个都在。**只交出一段字的图(打标签、反推提示词)不进模型目录**(`graph.media_outputs`),
只是工具。

以前还有一个通用的 `run_workflow`(按 id 跑,入参是写死的一张表):它不知道要跑哪张图,表单却要人填参数,
1.4.0 删掉了。它能跑的每一种图在上面都有自己的工具;每个工具带着 `replaces`,宿主据此把存着的 `run_workflow`
节点和画板工具格改写过来(`values` 按节点 id 或节点标题写的都认;新工具里没有位置的几格丢掉,记进修订说明)。

固定的那几个:

| 工具 | 只读 | 流式 | 默认开 | 做什么 |
| --- | --- | --- | --- | --- |
| `list_workflows` | ✓ | | ✓ | 每张工作流收什么(哪个节点读哪种素材)、能调什么、交出什么、`features`(upscale / inpaint / img2img / remove-background / …),以及跑它的工具(`tool`);转不过来的也列,带原因 |
| `import_outputs` | | ✓ | ✓ | 按任务号(可等 `wait_seconds`)或最近 `last` 次,把历史里的产出收进素材库。任务号声明成 `format: "external_id"`:这是按 ComfyUI 里的编号取东西,不是内容变换,只在工作流和对话里用,不上画板 |
| `server_status` | ✓ | | ✓ | 版本、显卡与空闲显存、内存、队列 |
| `list_models` | ✓ | | ✓ | `/models` 下的模型文件;老版本没有这个接口时看加载节点的下拉 |
| `interrupt` | | | ✓ | 停下正在跑的;给了 `prompt_id` 只停那一个 |
| `clear_queue` | | | | 清掉排队中的(别人的也会被清) |
| `free_memory` | | | | `/free`:卸载模型、释放显存 |

工作流的工具一次最多跑 30 分钟(`timeout_seconds: 1800`),交回**全部**产出(`artifacts` → 宿主换成 `assets` /
`asset_ids`)、文字产出、按节点分的摘要;占的是显卡,标 `effects: "paid"` —— 智能体调它先开确认卡,批准后在后台跑,
不占智能体那一次调用的等待时间。更久的走生成(6 小时、有回执、能续等)。

## 进度、取消、重启

- 进度来自 ComfyUI 的 WebSocket:哪个节点在跑(用界面上的节点名)、采样器第几步、第几个节点;连不上就退回轮询。
  新版 ComfyUI 的 `progress_state` 也认。
- 取消(生成任务、流式工具)时,插件会让 ComfyUI 停下**这一个**任务(在跑的 interrupt,在排队的从队列删掉),
  不会掐掉同一台机器上别人的任务。
- Mosael 重启时正在跑的生成会接着等(按任务号),不会重新提交。

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
- `comfy_http.py` / `ws.py` —— 和 ComfyUI 说话。

协议见 Mosael 仓库的 `docs/PLUGIN_MANIFEST.md`「替宿主做生成」「流式工具」「一次交出几份」。

"""后端自己的多语言。

**为什么不是"后端发 key、前端翻"**:后端这些文案的消费者不止前端 —— 智能体的工具返回、
飞书机器人推的消息、任务中心的通知标题、失败原因文本,都不经过前端的 messages.ts。
发 key 会让它们变成一串 `publishOpt_visibility`,比现在糟。

**语言从哪来**:这是个多租户、可远程部署的后端,没有"服务端语言"这回事 —— 每个消费者都得
拿到自己的那一种。按优先级:请求头 Accept-Language → (将来)用户偏好 → 部署默认 zh。
飞书/定时任务这类**没有请求上下文**的场景走后两条。

**文案存 key、出口翻译**:领域里的目录(平台、引擎…)存 key,序列化那一层才翻。这样
PLATFORM_OPTIONS 这种被后端校验、前端渲染、执行器消费的表不必知道语言。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

#: 支持的语言。第一个是缺省。
LOCALES = ("zh", "en")
DEFAULT_LOCALE = LOCALES[0]

#: key → {语言: 文案}。**每个 key 两种语言都必须有**(见 tests/test_backend_i18n.py 的棘轮)。
MESSAGES: dict[str, dict[str, str]] = {
    # ---- 发布平台 ----
    "platformDesc_douyin": {
        "zh": "由桌面端发布器用你已登录的抖音创作者账号自动上传;首次使用需在弹出的窗口里登录。",
        "en": "Uploads with your signed-in Douyin creator account via the desktop publisher; sign in once in the window it opens.",
    },
    "platformDesc_xiaohongshu": {
        "zh": "由桌面端发布器用已登录的小红书账号自动上传;首次使用需登录。",
        "en": "Uploads with your signed-in Xiaohongshu account via the desktop publisher; sign in on first use.",
    },
    "platformDesc_weixinChannels": {
        "zh": "由桌面端发布器用已登录的视频号助手账号自动上传;支持短标题。",
        "en": "Uploads with your signed-in WeChat Channels account via the desktop publisher; supports a short title.",
    },
    "platformDesc_bilibili": {
        "zh": "由桌面端发布器用已登录的 B 站账号自动上传;首次使用需登录。",
        "en": "Uploads with your signed-in Bilibili account via the desktop publisher; sign in on first use.",
    },
    "platformDesc_tiktok": {
        "zh": "由桌面端发布器用已登录的 TikTok 账号自动上传;首次使用需登录,境内需要可用的代理。",
        "en": "Uploads with your signed-in TikTok account via the desktop publisher; sign in on first use, and you may need a working proxy.",
    },
    "platformDesc_youtube": {
        "zh": (
            "由桌面端发布器用已登录的 YouTube 账号上传;首次使用需登录,境内需要可用的代理。"
            "默认发为私享,确认无误后再自行改公开。"
            "登录时若卡在通行密钥(passkey)验证,点「试试其他方式」改用密码或短信——内嵌浏览器不支持通行密钥。"
        ),
        "en": (
            "Uploads with your signed-in YouTube account via the desktop publisher; sign in on first use, "
            "and you may need a working proxy. Published as Private by default — switch it to Public yourself once you've checked it. "
            "If sign-in stalls on passkey verification, choose \"Try another way\" and use a password or SMS — the embedded browser has no passkey support."
        ),
    },
    # ---- 发布选项 ----
    "publishOpt_visibility": {"zh": "可见性", "en": "Visibility"},
    "publishOpt_whoCanSee": {"zh": "谁可以看", "en": "Who can see this"},
    "publishOpt_madeForKids": {"zh": "面向儿童的内容", "en": "Made for kids"},
    "publishOpt_original": {"zh": "原创声明", "en": "Declare as original"},
    "publishOptDesc_ytVisibility": {
        "zh": "默认私享。自动发布误发公开收不回,想公开发完再改一次即可。",
        "en": "Private by default. An accidental public post can't be taken back; switch it to public after you've checked it.",
    },
    "publishOptDesc_madeForKids": {
        "zh": "YouTube 的必答项。选「是」会关掉评论等一批功能,按素材实际情况填。",
        "en": "Required by YouTube. Choosing yes disables comments and other features — answer for what the video actually is.",
    },
    "publishOptDesc_privateFirst": {
        "zh": "默认仅自己可见,确认无误后再改公开。",
        "en": "Only you by default; make it public once you've checked it.",
    },
    "publishOptDesc_original": {
        "zh": "勾了就是向平台声明这条笔记为原创,按实际情况填。",
        "en": "Turning this on declares the post as original to the platform — answer truthfully.",
    },
    "publishVis_ytPrivate": {"zh": "私享(仅自己)", "en": "Private (only you)"},
    "publishVis_ytUnlisted": {"zh": "不公开列出(有链接可看)", "en": "Unlisted (anyone with the link)"},
    "publishVis_public": {"zh": "公开", "en": "Public"},
    "publishVis_publicVisible": {"zh": "公开可见", "en": "Public"},
    "publishVis_onlyMe": {"zh": "仅自己可见", "en": "Only you"},
    "publishVis_friends": {"zh": "好友", "en": "Friends"},
    "publishVis_friendsVisible": {"zh": "好友可见", "en": "Friends"},
    "publishVis_mutuals": {"zh": "仅互关好友可见", "en": "Mutual follows only"},
    "publishVis_everyone": {"zh": "所有人", "en": "Everyone"},
    # ---- 模型/引擎的状态句 ----
    "modelMsg_asrReady": {"zh": "已安装,转写即刻可用", "en": "Installed — transcription is ready to use"},
    "modelMsg_asrNoRuntime": {
        "zh": "模型已在磁盘上,但还没有能运行它的 Python 环境",
        "en": "The model files are on disk, but no Python environment here can run them yet",
    },
    "modelMsg_notDownloaded": {"zh": "未下载", "en": "Not downloaded"},
    "modelMsg_checkingRuntime": {"zh": "正在检查运行环境…", "en": "Checking the runtime…"},
    "modelMsg_cloneReady": {"zh": "已安装,声音克隆可用", "en": "Installed — voice cloning is ready"},
    "modelMsg_weightsNoRuntime": {
        "zh": "权重已下好,但还没有解释器装了它 —— 再点一次「下载」会把运行环境补上",
        "en": "Weights are downloaded, but no interpreter has the engine installed — click Download again to add the runtime",
    },
    "modelMsg_runtimeNoWeights": {"zh": "运行环境已就绪,还差模型权重", "en": "The runtime is ready; the model weights are still missing"},
    # ---- 任务消息(任务中心 / 飞书 / 工作流都读它)----
    "jobMsg_asrQueued": {"zh": "转写排队中", "en": "Transcription queued"},
    "jobMsg_asrDownloading": {"zh": "首次转写:下载模型中 {percent}%", "en": "First transcription: downloading the model, {percent}%"},
    "jobMsg_asrRunning": {"zh": "{provider} 转写中(首次会自动下载模型)", "en": "Transcribing with {provider} (the model downloads automatically the first time)"},
    "jobMsg_asrDone": {"zh": "转写完成", "en": "Transcription complete"},
    "jobMsg_asrFailed": {"zh": "转写失败", "en": "Transcription failed"},
    "jobMsg_ttsRunning": {"zh": "合成《{voice}》配音中", "en": "Synthesising voiceover with “{voice}”"},
    "jobMsg_ttsDone": {"zh": "配音已生成", "en": "Voiceover generated"},
    "jobMsg_ttsFailed": {"zh": "配音生成失败", "en": "Voiceover generation failed"},
    "jobMsg_dubRunning": {"zh": "字幕配音中({done}/{total})", "en": "Dubbing subtitles ({done}/{total})"},
    "jobMsg_dubDone": {"zh": "字幕配音完成:{done} 条", "en": "Dubbed {done} subtitle(s)"},
    # 部分失败单独一句:把「10 条里成了 9 条」说成「配音完成」,用户要到时间线上一段段找才发现少了一条。
    "jobMsg_dubPartial": {"zh": "字幕配音完成:{done} 条成功,{failed} 条失败", "en": "Dubbed {done} subtitle(s), {failed} failed"},
    "jobMsg_dubFailed": {"zh": "字幕配音失败", "en": "Subtitle dubbing failed"},
    "jobMsg_urlImportRunning": {"zh": "从链接下载({done}/{total})", "en": "Downloading from links ({done}/{total})"},
    "jobMsg_urlImportItem": {
        "zh": "下载第 {n}/{total} 条:{title}",
        "en": "Downloading {n}/{total}: {title}",
    },
    "jobMsg_urlImportDone": {"zh": "已导入 {done} 条素材", "en": "Imported {done} item(s)"},
    "jobMsg_urlImportPartial": {
        "zh": "已导入 {done} 条,{failed} 条失败",
        "en": "Imported {done} item(s), {failed} failed",
    },
    "jobMsg_urlImportFailed": {"zh": "从链接下载失败", "en": "Downloading from links failed"},
    "f5Model_base": {"zh": "基础模型(中文 / 英文)", "en": "Base model (Chinese / English)"},
    "f5Model_ja": {"zh": "日语模型", "en": "Japanese model"},
    "f5ModelNote_base": {
        "zh": "F5-TTS 官方权重,中英双语。装了它就能用自己的音色念中文和英文。",
        "en": "The official F5-TTS weights, Chinese + English. Enough to read Chinese and English in your own voice.",
    },
    "f5ModelNote_community": {
        "zh": "社区微调权重(F5-TTS 官方清单收录)。装了之后,日文字幕也能用你自己的音色念。",
        "en": "A community finetune listed by F5-TTS upstream. Once installed, Japanese is read in your own cloned voice too.",
    },
    "jobMsg_podcastRunning": {"zh": "生成播客中", "en": "Generating the podcast"},
    "jobMsg_podcastDone": {"zh": "播客已生成", "en": "Podcast generated"},
    "jobMsg_renderFinishing": {"zh": "整理输出…", "en": "Finalising the output…"},
    "jobMsg_renderDone": {"zh": "导出完成", "en": "Export complete"},
    "jobMsg_renderFailed": {"zh": "导出失败", "en": "Export failed"},
    "jobMsg_genericFailed": {"zh": "{what} 失败", "en": "{what} failed"},
    "jobMsg_generationQueued": {"zh": "已提交给生成服务", "en": "Submitted to the generation provider"},
    "jobMsg_generationRunning": {"zh": "生成中", "en": "Generating"},
    "jobMsg_generationDone": {"zh": "生成完成", "en": "Generation complete"},
    "jobMsg_generationFailed": {"zh": "生成失败", "en": "Generation failed"},
    "jobMsg_waitingWorker": {"zh": "等待执行器认领", "en": "Waiting for a worker to claim it"},
    "jobMsg_interrupted": {"zh": "已中断", "en": "Interrupted"},
    "jobMsg_cancelled": {"zh": "已取消", "en": "Cancelled"},
    "jobMsg_claimed": {"zh": "执行器已认领", "en": "Claimed by a worker"},
    "jobMsg_workflowQueued": {"zh": "工作流排队中: {name}", "en": "Workflow queued: {name}"},
    "jobMsg_workflowRunning": {"zh": "工作流运行中: {name}", "en": "Workflow running: {name}"},
    "jobMsg_workflowDone": {"zh": "工作流完成: {name}", "en": "Workflow complete: {name}"},
    "jobMsg_workflowFailed": {"zh": "工作流失败", "en": "Workflow failed"},
    "jobMsg_publishWaiting": {"zh": "等待桌面发布器认领: {title}", "en": "Waiting for the desktop publisher: {title}"},
    "jobMsg_publishRunning": {"zh": "桌面发布器执行中: {title}", "en": "Desktop publisher running: {title}"},
    "jobMsg_publishDone": {"zh": "发布完成: {title}", "en": "Published: {title}"},
    "jobMsg_publishFailed": {"zh": "发布失败", "en": "Publishing failed"},
    "jobMsg_publishCancelled": {"zh": "发布已取消", "en": "Publishing cancelled"},
    "jobMsg_publishStatus": {"zh": "发布 {status}: {title}", "en": "Publish {status}: {title}"},
    "jobMsg_proxyQueued": {"zh": "生成预览代理排队中", "en": "Proxy generation queued"},
    #: 配置字段的名字(节点检查器上每一行的标题)。按**键名**给,不按节点给 ——
    #: selector 在六种浏览器节点里是同一个意思。
    "wfField_account_id": {"zh": "发布账号", "en": "Publishing account"},
    "wfField_all": {"zh": "全部", "en": "All"},
    "wfField_asset_id": {"zh": "素材", "en": "Asset"},
    "wfField_asset_ids": {"zh": "素材", "en": "Assets"},
    "wfField_attribute": {"zh": "取哪个属性", "en": "Attribute"},
    "wfField_body": {"zh": "子图", "en": "Subgraph"},
    "wfField_code": {"zh": "代码", "en": "Code"},
    "wfField_condition": {"zh": "条件", "en": "Condition"},
    "wfField_description": {"zh": "说明", "en": "Description"},
    "wfField_dy": {"zh": "纵向距离", "en": "Vertical distance"},
    "wfField_end": {"zh": "结束位置", "en": "End"},
    "wfField_engine": {"zh": "引擎", "en": "Engine"},
    "wfField_exact": {"zh": "精确匹配", "en": "Exact match"},
    "wfField_expression": {"zh": "表达式", "en": "Expression"},
    "wfField_file_path": {"zh": "文件路径", "en": "File path"},
    "wfField_find": {"zh": "查找", "en": "Find"},
    "wfField_frequency_penalty": {"zh": "重复惩罚", "en": "Frequency penalty"},
    "wfField_gone": {"zh": "等它消失", "en": "Wait until gone"},
    "wfField_headers": {"zh": "请求头", "en": "Headers"},
    "wfField_input": {"zh": "入参", "en": "Arguments"},
    "wfField_inputs": {"zh": "入参映射", "en": "Input mapping"},
    "wfField_instance_id": {"zh": "连接", "en": "Connection"},
    "wfField_items": {"zh": "要遍历的列表", "en": "List to iterate"},
    "wfField_json_schema": {"zh": "JSON Schema", "en": "JSON Schema"},
    "wfField_json_schema_name": {"zh": "Schema 名称", "en": "Schema name"},
    "wfField_json_schema_strict": {"zh": "严格模式", "en": "Strict mode"},
    "wfField_kind": {"zh": "类型", "en": "Kind"},
    "wfField_left": {"zh": "左值", "en": "Left value"},
    "wfField_limit": {"zh": "条数上限", "en": "Limit"},
    "wfField_max_iterations": {"zh": "最多循环几次", "en": "Max iterations"},
    "wfField_max_tokens": {"zh": "最长输出", "en": "Max output"},
    "wfField_method": {"zh": "请求方法", "en": "Method"},
    "wfField_mode": {"zh": "模式", "en": "Mode"},
    "wfField_model": {"zh": "模型", "en": "Model"},
    "wfField_name": {"zh": "名称", "en": "Name"},
    "wfField_name_contains": {"zh": "名称包含", "en": "Name contains"},
    "wfField_negative_prompt": {"zh": "负向提示词", "en": "Negative prompt"},
    "wfField_op": {"zh": "运算", "en": "Operator"},
    "wfField_operations": {"zh": "操作", "en": "Operations"},
    "wfField_output": {"zh": "对外输出", "en": "Output"},
    "wfField_parameters": {"zh": "生成参数", "en": "Generation parameters"},
    "wfField_params": {"zh": "启动参数", "en": "Start parameters"},
    "wfField_path": {"zh": "路径", "en": "Path"},
    "wfField_plugin_id": {"zh": "插件", "en": "Plugin"},
    "wfField_presence_penalty": {"zh": "话题惩罚", "en": "Presence penalty"},
    "wfField_preset": {"zh": "预设", "en": "Preset"},
    "wfField_profile_id": {"zh": "供应商配置", "en": "Provider connection"},
    "wfField_project_id": {"zh": "项目", "en": "Project"},
    "wfField_prompt": {"zh": "提示词", "en": "Prompt"},
    "wfField_provider": {"zh": "服务商", "en": "Provider"},
    "wfField_replace": {"zh": "替换为", "en": "Replace with"},
    "wfField_response_format": {"zh": "返回格式", "en": "Response format"},
    "wfField_right": {"zh": "右值", "en": "Right value"},
    "wfField_seconds": {"zh": "秒数", "en": "Seconds"},
    "wfField_seed": {"zh": "随机种子", "en": "Seed"},
    "wfField_selector": {"zh": "元素选择器", "en": "Selector"},
    "wfField_sequence_id": {"zh": "时间线", "en": "Timeline"},
    "wfField_session": {"zh": "浏览器会话", "en": "Browser session"},
    "wfField_session_mode": {"zh": "会话方式", "en": "Session mode"},
    "wfField_session_name": {"zh": "会话名称", "en": "Session name"},
    "wfField_source": {"zh": "来源", "en": "Source"},
    "wfField_source_assets": {"zh": "输入素材", "en": "Input assets"},
    "wfField_start": {"zh": "起始位置", "en": "Start"},
    "wfField_stop": {"zh": "停止词", "en": "Stop sequences"},
    "wfField_system": {"zh": "系统提示词", "en": "System prompt"},
    "wfField_tags": {"zh": "标签", "en": "Tags"},
    "wfField_target_lang": {"zh": "目标语言", "en": "Target language"},
    "wfField_temperature": {"zh": "发散程度", "en": "Temperature"},
    "wfField_template": {"zh": "模板", "en": "Template"},
    "wfField_text": {"zh": "文本", "en": "Text"},
    "wfField_timeout_ms": {"zh": "超时(毫秒)", "en": "Timeout (ms)"},
    "wfField_title": {"zh": "标题", "en": "Title"},
    "wfField_tool_name": {"zh": "工具", "en": "Tool"},
    "wfField_top_p": {"zh": "采样范围", "en": "Top-p"},
    "wfField_track_id": {"zh": "轨道", "en": "Track"},
    "wfField_url": {"zh": "网址", "en": "URL"},
    "wfField_url_contains": {"zh": "网址包含", "en": "URL contains"},
    "wfField_value": {"zh": "值", "en": "Value"},
    "wfField_values": {"zh": "具名输出", "en": "Named outputs"},
    "wfField_voice_id": {"zh": "音色", "en": "Voice"},
    "wfField_workflow_id": {"zh": "工作流", "en": "Workflow"},
    #: 节点面板的分组名。
    "wfCat_flow": {"zh": "流程", "en": "Flow"},
    "wfCat_ai": {"zh": "AI", "en": "AI"},
    "wfCat_asset": {"zh": "素材", "en": "Assets"},
    "wfCat_data": {"zh": "数据", "en": "Data"},
    "wfCat_publish": {"zh": "发布", "en": "Publishing"},
    "wfCat_browser": {"zh": "浏览器", "en": "Browser"},
    "wfCat_plugin": {"zh": "插件", "en": "Plugins"},
    #: 工作流节点目录 —— 名字、说明、每个配置字段的说明。目录里存 key,出口才翻
    #: (见 api/routes/workflows.node_types);两条棘轮钉着「目录里不许出现文案」
    #: 和「写的 key 必须能翻」,见 tests/test_backend_i18n。
    "wfNode_start": {"zh": "开始", "en": "Start"},
    "wfNode_start_desc": {"zh": "工作流入口,声明输入参数(运行时可覆盖默认值)。", "en": "Workflow entry point; declares input parameters (defaults can be overridden per run)."},
    "wfNode_start_params": {"zh": "输入参数名 → 默认值", "en": "Input parameter name → default value"},
    "wfNode_llm": {"zh": "LLM 生成", "en": "LLM"},
    "wfNode_llm_desc": {"zh": "调用配置的 AI 供应商生成文本。", "en": "Generate text with the configured AI provider."},
    "wfNode_llm_prompt": {"zh": "这一轮要模型做的事", "en": "What the model should do this turn"},
    "wfNode_llm_preset": {"zh": "生成风格(替代裸 temperature)", "en": "Generation style (instead of a bare temperature)"},
    "wfNode_llm_profile_id": {"zh": "留空自动选择", "en": "Leave empty to choose automatically"},
    "wfNode_llm_model": {"zh": "留空用配置默认", "en": "Leave empty to use the connection's default"},
    "wfNode_llm_temperature": {"zh": "采样温度 0-2;留空跟随生成风格", "en": "Sampling temperature 0-2; leave empty to follow the generation style"},
    "wfNode_llm_top_p": {"zh": "核采样 0-1;留空不传", "en": "Nucleus sampling 0-1; leave empty to omit"},
    "wfNode_llm_max_tokens": {"zh": "最大输出 token;留空不传", "en": "Maximum output tokens; leave empty to omit"},
    "wfNode_llm_frequency_penalty": {"zh": "频率惩罚 -2 到 2;留空不传", "en": "Frequency penalty -2 to 2; leave empty to omit"},
    "wfNode_llm_presence_penalty": {"zh": "存在惩罚 -2 到 2;留空不传", "en": "Presence penalty -2 to 2; leave empty to omit"},
    "wfNode_llm_seed": {"zh": "留空不传", "en": "Leave empty to omit"},
    "wfNode_llm_stop": {"zh": "多个用换行分隔", "en": "One per line for several"},
    "wfNode_llm_response_format": {"zh": "输出格式", "en": "Output format"},
    "wfNode_llm_json_schema_name": {"zh": "JSON Schema 名称,默认 workflow_output", "en": "JSON Schema name; defaults to workflow_output"},
    "wfNode_llm_json_schema": {"zh": "仅 response_format=json_schema 时使用", "en": "Used only when response_format=json_schema"},
    "wfNode_llm_json_schema_strict": {"zh": "JSON Schema 严格模式", "en": "JSON Schema strict mode"},
    "wfNode_plugin_tool": {"zh": "插件工具", "en": "Plugin tool"},
    "wfNode_plugin_tool_desc": {"zh": "调用已启用插件的纯函数工具。", "en": "Call a pure-function tool from an enabled plugin."},
    "wfNode_plugin_tool_instance_id": {"zh": "用哪个连接;留空自动选(仅一个时)", "en": "Which connection to use; leave empty to pick automatically (when there is only one)"},
    "wfNode_plugin_tool_input": {"zh": "工具入参", "en": "Tool arguments"},
    "wfNode_transcribe_asset": {"zh": "素材转写", "en": "Transcribe asset"},
    "wfNode_transcribe_asset_desc": {"zh": "对音视频素材跑 ASR,输出全文。", "en": "Run ASR over an audio or video asset and output the full text."},
    "wfNode_transcribe_asset_asset_id": {"zh": "要转写的素材 —— 只收视频或音频,图片会被拒", "en": "The asset to transcribe — audio or video only; images are rejected"},
    "wfNode_export_sequence": {"zh": "导出时间线", "en": "Export timeline"},
    "wfNode_export_sequence_desc": {"zh": "渲染导出一条时间线,产出新素材。", "en": "Render a timeline to a file and register it as a new asset."},
    "wfNode_asset": {"zh": "素材", "en": "Asset"},
    "wfNode_asset_desc": {"zh": "指向素材库里的一份素材,把它的 id 交给下游。拖一个文件到画布上就会得到这个节点 —— 它是「这条流程从这份素材开始」的说法。", "en": "Points at one asset in the library and hands its id downstream. Dropping a file onto the canvas produces this node — it is how you say “this flow starts from this asset”."},
    "wfNode_inspect_sequence": {"zh": "看一眼时间线", "en": "Inspect timeline"},
    "wfNode_inspect_sequence_desc": {"zh": "读出这条时间线的轨道、片段和总时长。编排之前先知道现在长什么样。", "en": "Read a timeline's tracks, clips and total duration. Look before you arrange."},
    "wfNode_timeline_append": {"zh": "把素材接到时间线", "en": "Append to timeline"},
    "wfNode_timeline_append_desc": {"zh": "把一份素材接到某条轨道的**末尾**。这是编排里占九成的动作 —— 一段段往后排。轨道留空就用第一条同类轨道(视频素材进视频轨,音频进音频轨)。", "en": "Append an asset to the **end** of a track. This is nine tenths of arranging — one clip after another. Leave the track empty and the first track of a matching kind is used (video assets go to a video track, audio to an audio track)."},
    "wfNode_timeline_append_sequence_id": {"zh": "要编排的时间线", "en": "The timeline to arrange"},
    "wfNode_timeline_append_asset_id": {"zh": "要接进去的素材", "en": "The asset to append"},
    "wfNode_timeline_append_track_id": {"zh": "接到哪条轨道。留空自动挑一条同类的", "en": "Which track to append to. Leave empty to pick a matching one automatically"},
    "wfNode_timeline_append_start": {"zh": "从第几秒开始截。留空从头", "en": "Trim in-point in seconds. Leave empty to start at the beginning"},
    "wfNode_timeline_append_end": {"zh": "截到第几秒。留空到尾", "en": "Trim out-point in seconds. Leave empty to run to the end"},
    "wfNode_timeline_add_track": {"zh": "加一条轨道", "en": "Add a track"},
    "wfNode_timeline_add_track_desc": {"zh": "给时间线加一条视频 / 音频 / 字幕轨。", "en": "Add a video / audio / subtitle track to a timeline."},
    "wfNode_timeline_add_track_kind": {"zh": "轨道类型", "en": "Track kind"},
    "wfNode_timeline_clear": {"zh": "清空时间线", "en": "Clear timeline"},
    "wfNode_timeline_clear_desc": {"zh": "删掉这条时间线上的所有片段,轨道留着。重跑一条工作流之前常常要先清一次。", "en": "Delete every clip on this timeline, keeping the tracks. Usually the first step before re-running a workflow."},
    "wfNode_edit_timeline": {"zh": "时间线高级操作", "en": "Timeline advanced operations"},
    "wfNode_edit_timeline_desc": {"zh": "一次提交一组操作,用于上面几个节点覆盖不了的情况(移动、裁剪、切一段、改效果与变换)。operations 是一个 JSON 数组,每项形如 {\"kind\": \"move_clip\", \"clip_id\": …}。常规的「接素材 / 加轨道 / 清空」用对应的专用节点,不必写这个。", "en": "Submit a batch of operations for what the nodes above cannot express (move, trim, cut a range, change effects and transforms). operations is a JSON array whose items look like {\"kind\": \"move_clip\", \"clip_id\": …}. For ordinary append / add-track / clear, use the dedicated nodes instead."},
    "wfNode_edit_timeline_operations": {"zh": "JSON 数组。可用的 kind:{kinds}", "en": "A JSON array. Available kinds: {kinds}"},
    "wfNode_ai_generate": {"zh": "AI 生成素材", "en": "AI generate"},
    "wfNode_ai_generate_desc": {"zh": "文生图/文生视频(也支持图生图、图生视频),产出素材进素材库。", "en": "Text-to-image / text-to-video (image-to-image and image-to-video too); the result is registered in the asset library."},
    "wfNode_ai_generate_kind": {"zh": "生成类型", "en": "What to generate"},
    "wfNode_ai_generate_negative_prompt": {"zh": "部分模型支持", "en": "Supported by some models"},
    "wfNode_ai_generate_parameters": {"zh": "取值随模型而定 —— 逐模型的可用清单看 /api/generation/options 里那个模型的 capabilities.parameter_keys。目录里出现过的有:{keys}", "en": "Values depend on the model — for the per-model list see that model's capabilities.parameter_keys under /api/generation/options. Ones that appear in the catalogue: {keys}"},
    "wfNode_ai_generate_source_assets": {"zh": "每行一条 `素材id` 或 `素材id:角色`。角色:{roles_zh};不写角色时图生视频按首帧、图生图按参考图。", "en": "One `asset_id` or `asset_id:role` per line. Roles: {roles}. With no role, image-to-video treats it as the first frame and image-to-image as a reference image."},
    "wfNode_publish": {"zh": "发布", "en": "Publish"},
    "wfNode_publish_desc": {"zh": "用已登录的平台账号发布到抖音 / 小红书 / 视频号 / B站(由桌面端内嵌浏览器执行)。", "en": "Publish to Douyin / Xiaohongshu / Weixin Channels / Bilibili using an already signed-in account (carried out by the desktop app's embedded browser)."},
    "wfNode_publish_account_id": {"zh": "浏览器池可查", "en": "Look it up in the browser pool"},
    "wfNode_publish_asset_id": {"zh": "要发布的素材 —— 必须已经下载到本地", "en": "The asset to publish — it must already be downloaded locally"},
    "wfNode_publish_title": {"zh": "各平台的长度上限不同,超了会被平台拒掉", "en": "Length limits differ per platform; going over gets rejected by the platform"},
    "wfNode_condition": {"zh": "条件分支", "en": "Condition"},
    "wfNode_condition_desc": {"zh": "按条件把流程导向「真」或「假」分支(连线时从对应端点拉出)。", "en": "Route the flow down the “true” or “false” branch (drag from the matching port when connecting)."},
    "wfNode_condition_left": {"zh": "如 {{llm-1.text}}", "en": "e.g. {{llm-1.text}}"},
    "wfNode_condition_op": {"zh": "比较方式", "en": "Comparison"},
    "wfNode_condition_right": {"zh": "empty/not_empty 不需要", "en": "Not needed for empty / not_empty"},
    "wfNode_http_request": {"zh": "HTTP 请求", "en": "HTTP request"},
    "wfNode_http_request_desc": {"zh": "调用外部 API,输出状态码与响应内容。", "en": "Call an external API; outputs the status code and the response body."},
    "wfNode_http_request_method": {"zh": "默认 GET", "en": "GET by default"},
    "wfNode_http_request_body": {"zh": "请求体(POST/PUT),JSON 或纯文本", "en": "Request body (POST/PUT), JSON or plain text"},
    "wfNode_code": {"zh": "代码", "en": "Code"},
    "wfNode_code_desc": {"zh": "运行一段 Python:inputs 为入参 dict,把结果赋给 output 变量。与插件同级的本地信任沙箱。", "en": "Run a piece of Python: inputs is the argument dict, and whatever you assign to output becomes the result. A locally trusted sandbox, at the same level as plugins."},
    "wfNode_code_code": {"zh": "如:output = len(inputs['text'])", "en": "e.g. output = len(inputs['text'])"},
    "wfNode_template": {"zh": "文本模板", "en": "Text template"},
    "wfNode_template_desc": {"zh": "把多个上游变量拼装成一段文本。", "en": "Assemble several upstream variables into one piece of text."},
    "wfNode_json_extract": {"zh": "JSON 提取", "en": "JSON extract"},
    "wfNode_json_extract_desc": {"zh": "从 JSON/对象里按点路径取值,常接在 HTTP 请求或插件工具后面。", "en": "Read a value out of JSON or an object by dotted path; usually placed after an HTTP request or a plugin tool."},
    "wfNode_json_extract_source": {"zh": "JSON 文本或 {{节点.json}}", "en": "JSON text or {{node.json}}"},
    "wfNode_json_extract_path": {"zh": "点路径,如 data.items.0.title;留空返回整个对象", "en": "Dotted path, e.g. data.items.0.title; leave empty to return the whole object"},
    "wfNode_text_transform": {"zh": "文本处理", "en": "Text transform"},
    "wfNode_text_transform_desc": {"zh": "对文本做去空白/大小写/替换/正则提取/取长度等处理。", "en": "Trim whitespace, change case, replace, extract by regex, take the length, and so on."},
    "wfNode_text_transform_op": {"zh": "处理方式", "en": "Operation"},
    "wfNode_text_transform_find": {"zh": "replace 的查找串 / regex_extract 的正则", "en": "The search string for replace, or the pattern for regex_extract"},
    "wfNode_text_transform_replace": {"zh": "replace 的替换串", "en": "The replacement string for replace"},
    "wfNode_delay": {"zh": "延时", "en": "Delay"},
    "wfNode_delay_desc": {"zh": "等待若干秒再继续(限流/节流用)。", "en": "Wait a number of seconds before continuing (for rate limiting / throttling)."},
    "wfNode_delay_seconds": {"zh": "等待秒数,默认 1,上限 300", "en": "Seconds to wait; defaults to 1, capped at 300"},
    "wfNode_synthesize_speech": {"zh": "语音合成", "en": "Text to speech"},
    "wfNode_synthesize_speech_desc": {"zh": "用指定音色把文本合成为配音,产出音频素材进素材库。", "en": "Speak text in a chosen voice; the result is registered in the asset library."},
    "wfNode_synthesize_speech_voice_id": {"zh": "配音库可查", "en": "Look it up in the voice library"},
    "wfNode_notify": {"zh": "发送通知", "en": "Send notification"},
    "wfNode_notify_desc": {"zh": "给工作区成员推送一条站内通知。", "en": "Push an in-app notification to the members of this workspace."},
    "wfNode_notify_body": {"zh": "通知正文", "en": "Notification body"},
    "wfNode_translate": {"zh": "翻译", "en": "Translate"},
    "wfNode_translate_desc": {"zh": "把文本翻译成目标语言:Google 免费接口(无需 key)或 AI 供应商。", "en": "Translate text into a target language: Google's free endpoint (no key needed) or an AI provider."},
    "wfNode_translate_engine": {"zh": "翻译引擎(默认 Google 免费)", "en": "Translation engine (Google's free one by default)"},
    "wfNode_translate_profile_id": {"zh": "engine=ai 时的供应商配置,留空自动", "en": "The provider connection used when engine=ai; leave empty to choose automatically"},
    "wfNode_loop_foreach": {"zh": "循环·遍历", "en": "Loop · for each"},
    "wfNode_loop_foreach_desc": {"zh": "对一个列表逐项运行内嵌子流程,汇总每次迭代的输出为列表。子流程内用 {{loop.item}} / {{loop.index}} 引用当前元素与序号。", "en": "Run an embedded sub-flow once per item of a list and collect each iteration's output into a list. Inside the sub-flow, {{loop.item}} and {{loop.index}} refer to the current element and its index."},
    "wfNode_loop_foreach_items": {"zh": "如 {{split_1.results}};也接受多行文本,按行拆分", "en": "e.g. {{split_1.results}}; multi-line text is also accepted and split by line"},
    "wfNode_loop_foreach_body": {"zh": "循环体子流程(在节点内编辑;子流程节点用 {{loop.item}}/{{loop.index}})", "en": "The loop body sub-flow (edited inside the node; its nodes use {{loop.item}} / {{loop.index}})"},
    "wfNode_loop_foreach_output": {"zh": "每次迭代的输出,引用子流程节点输出(如 {{translate_1.text}});留空则输出整份子上下文", "en": "Each iteration's output, referencing a sub-flow node's output (e.g. {{translate_1.text}}); leave empty to output the whole sub-context"},
    "wfNode_loop_while": {"zh": "循环·条件", "en": "Loop · while"},
    "wfNode_loop_while_desc": {"zh": "反复运行内嵌子流程,直到条件不再成立(带最大次数上限防死循环)。子流程内用 {{loop.index}} 拿当前轮次;子流程里放一个「条件」节点,把它的 {{节点id.result}} 填到 condition。", "en": "Run an embedded sub-flow repeatedly until the condition stops holding (with a maximum iteration count to prevent runaway loops). Inside the sub-flow, {{loop.index}} is the current round; put a Condition node in the sub-flow and feed its {{node_id.result}} into condition."},
    "wfNode_loop_while_body": {"zh": "循环体子流程(每轮跑一遍;通常含一个条件节点决定是否继续)", "en": "The loop body sub-flow (one pass per round; usually contains a Condition node that decides whether to continue)"},
    "wfNode_loop_while_condition": {"zh": "每轮跑完后判断是否继续,引用子流程里条件节点的布尔输出(如 {{check.result}});留空则只跑一轮", "en": "Checked after each round to decide whether to continue; reference the boolean output of a Condition node inside the sub-flow (e.g. {{check.result}}); leave empty to run exactly once"},
    "wfNode_loop_while_max_iterations": {"zh": "最大轮次(默认 50,硬上限 1000),防死循环", "en": "Maximum rounds (50 by default, hard cap 1000), to prevent runaway loops"},
    "wfNode_loop_while_output": {"zh": "每轮的输出(如 {{step.text}});留空则输出整份子上下文", "en": "Each round's output (e.g. {{step.text}}); leave empty to output the whole sub-context"},
    "wfNode_asset_query": {"zh": "素材筛选", "en": "Find assets"},
    "wfNode_asset_query_desc": {"zh": "按条件批量选出工作区里的素材(类型/名称/标签),输出素材列表 —— 常接「循环·遍历」的 items 逐个处理。", "en": "Select assets in this workspace in bulk (by kind / name / tags) and output the list — usually feeding the items of a “Loop · for each”."},
    "wfNode_asset_query_kind": {"zh": "素材类型", "en": "Asset kind"},
    "wfNode_asset_query_name_contains": {"zh": "留空不筛", "en": "Leave empty to not filter"},
    "wfNode_asset_query_tags": {"zh": "逗号分隔,命中任一即选;留空不筛", "en": "Comma separated; matching any one selects it. Leave empty to not filter"},
    "wfNode_asset_query_limit": {"zh": "最多返回条数(默认 50,上限 500)", "en": "Maximum number returned (50 by default, capped at 500)"},
    "wfNode_asset_tag": {"zh": "素材打标签", "en": "Tag assets"},
    "wfNode_asset_tag_desc": {"zh": "给素材增删标签 —— 常接「素材筛选」或「循环·遍历」,把整理归档做成一步。", "en": "Add or remove tags on assets — usually after “Find assets” or “Loop · for each”, turning filing into a single step."},
    "wfNode_asset_tag_asset_ids": {"zh": "逗号分隔,或直接接「素材筛选」的 ids", "en": "Comma separated, or connect the ids output of “Find assets” directly"},
    "wfNode_asset_tag_tags": {"zh": "逗号分隔", "en": "Comma separated"},
    "wfNode_asset_tag_mode": {"zh": "add=追加,remove=移除,replace=整组替换", "en": "add = append, remove = take away, replace = swap the whole set"},
    "wfNode_asset_update": {"zh": "素材整理", "en": "Organize assets"},
    "wfNode_asset_update_desc": {"zh": "重命名素材、或把素材归入某个项目。", "en": "Rename assets, or move them into a project."},
    "wfNode_asset_update_asset_ids": {"zh": "逗号分隔", "en": "Comma separated"},
    "wfNode_asset_update_name": {"zh": "新名称;多个素材时会自动加序号。留空则不改名", "en": "New name; a number is appended automatically when there are several assets. Leave empty to keep the names"},
    "wfNode_asset_update_project_id": {"zh": "归入的项目 id;留空则不改动归属", "en": "The project to move them into; leave empty to keep them where they are"},
    "wfNode_project_create": {"zh": "新建项目", "en": "Create project"},
    "wfNode_project_create_desc": {"zh": "在当前工作区建一个项目,输出它的 id —— 可接「素材整理」把素材归进去。", "en": "Create a project in this workspace and output its id — can feed “Organize assets” to file assets into it."},
    "wfNode_project_create_name": {"zh": "项目名", "en": "Project name"},
    "wfNode_call_workflow": {"zh": "调用工作流", "en": "Call workflow"},
    "wfNode_call_workflow_desc": {"zh": "把另一个已保存的工作流当子流程调用:映射入参 → 跑完取其「输出」节点声明的结果作为本节点输出(引用 {{call_1.output.xxx}})。子流程走完整引擎,自动收纳到本流程下、随本流程取消;防递归、防过深。", "en": "Call another saved workflow as a sub-flow: map the inputs, run it, and take the results declared by its Output node as this node's output (referenced as {{call_1.output.xxx}}). The sub-flow runs through the full engine, is nested under this run and cancels with it; recursion and excessive depth are refused."},
    "wfNode_call_workflow_workflow_id": {"zh": "要调用的工作流(选一个已保存的)", "en": "The workflow to call (pick a saved one)"},
    "wfNode_call_workflow_inputs": {"zh": "{参数名: 值/引用},喂给子流程开始节点的参数,如 {\"topic\": \"{{start.theme}}\"}", "en": "{name: value/reference} fed to the sub-flow's Start node, e.g. {\"topic\": \"{{start.theme}}\"}"},
    "wfNode_output": {"zh": "输出", "en": "Output"},
    "wfNode_output_desc": {"zh": "声明本工作流的输出(参考 dify End):{名: 引用}。被「调用工作流」时,调用方拿到的就是这里声明的具名输出;留空/无本节点则输出整份上下文。", "en": "Declare this workflow's outputs (compare Dify's End node): {name: reference}. When called by “Call workflow”, the caller receives exactly these named outputs; leave it empty or omit the node and the whole context is output instead."},
    "wfNode_output_values": {"zh": "{名: 引用},如 {\"result\": \"{{llm_1.text}}\", \"url\": \"{{browser_1.value}}\"}", "en": "{name: reference}, e.g. {\"result\": \"{{llm_1.text}}\", \"url\": \"{{browser_1.value}}\"}"},
    "wfNode_subgraph": {"zh": "子图", "en": "Subgraph"},
    "wfNode_subgraph_desc": {"zh": "把一组节点封装成一个可复用子图(参考 ComfyUI「折叠为子图」):内嵌、可任意嵌套,在节点内进子画布编辑。与主引擎同一套内核(并行/条件分支一致)。用 inputs 把外层值喂进去(子图内 {{input.名}} 引用),output 指定子图输出(引用内部节点,如 {{node_1.text}});留空则输出整份子上下文。", "en": "Fold a group of nodes into a reusable subgraph (compare ComfyUI's “convert to subgraph”): embedded, nestable to any depth, edited on its own canvas inside the node. It runs on the same engine core as the main flow (identical parallelism and branching). Feed outer values in with inputs (referenced inside as {{input.name}}) and pick what comes out with output (referencing an inner node, e.g. {{node_1.text}}); leave it empty to output the whole sub-context."},
    "wfNode_subgraph_inputs": {"zh": "喂进子图的输入 {名: 值/引用},子图内用 {{input.名}} 取,如 {\"topic\": \"{{start.theme}}\"}", "en": "Inputs fed into the subgraph, {name: value/reference}, read inside as {{input.name}}, e.g. {\"topic\": \"{{start.theme}}\"}"},
    "wfNode_subgraph_body": {"zh": "在节点内进子画布编辑;无入边的根即入口,可放多个", "en": "Edited on its own canvas inside the node; any root with no incoming edge is an entry point, and there may be several"},
    "wfNode_subgraph_output": {"zh": "子图输出,引用内部节点输出(如 {{node_1.text}});留空则输出整份子上下文", "en": "The subgraph's output, referencing an inner node's output (e.g. {{node_1.text}}); leave empty to output the whole sub-context"},
    "wfNode_browser_open": {"zh": "打开浏览器", "en": "Open browser"},
    "wfNode_browser_open_desc": {"zh": "新建一个浏览器会话并可选导航到网址,输出 session 供后续浏览器节点使用。ephemeral=临时(跑完即清);named=具名持久(保留登录);pool=复用「浏览器池」里某个已登录档案(受租约:一档案一时刻一会话)。", "en": "Start a browser session, optionally navigating to a URL, and output a session for the later browser nodes. ephemeral = throwaway (wiped when the run ends); named = persistent by name (keeps logins); pool = reuse a signed-in profile from the browser pool (leased: one session per profile at a time)."},
    "wfNode_browser_open_url": {"zh": "打开后导航到的网址(可留空,之后用「导航」节点)", "en": "The URL to navigate to after opening (may be left empty; use the Navigate node later)"},
    "wfNode_browser_open_session_mode": {"zh": "ephemeral=临时;named=具名持久;pool=复用浏览器池档案(已登录身份)", "en": "ephemeral = throwaway; named = persistent by name; pool = reuse a browser-pool profile (a signed-in identity)"},
    "wfNode_browser_open_session_name": {"zh": "具名会话名称(session_mode=named 时必填)", "en": "The session's name (required when session_mode=named)"},
    "wfNode_browser_open_profile_id": {"zh": "浏览器池档案(session_mode=pool 时必填),复用其登录态", "en": "The browser-pool profile (required when session_mode=pool) whose signed-in state is reused"},
    "wfNode_browser_navigate": {"zh": "浏览器·导航", "en": "Browser · navigate"},
    "wfNode_browser_navigate_desc": {"zh": "在会话里跳转到网址。", "en": "Go to a URL in this session."},
    "wfNode_browser_navigate_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_navigate_url": {"zh": "目标网址", "en": "Target URL"},
    "wfNode_browser_click": {"zh": "浏览器·点击", "en": "Browser · click"},
    "wfNode_browser_click_desc": {"zh": "按 CSS 选择器或可见文本点击元素。", "en": "Click an element by CSS selector or by its visible text."},
    "wfNode_browser_click_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_click_selector": {"zh": "CSS 选择器(与文本二选一)", "en": "CSS selector (either this or the text)"},
    "wfNode_browser_click_text": {"zh": "按可见文本点击(与选择器二选一)", "en": "Click by visible text (either this or the selector)"},
    "wfNode_browser_click_exact": {"zh": "文本是否精确匹配", "en": "Whether the text must match exactly"},
    "wfNode_browser_input": {"zh": "浏览器·输入", "en": "Browser · type"},
    "wfNode_browser_input_desc": {"zh": "往输入框/文本域填入内容(含 contenteditable)。", "en": "Fill an input or textarea (contenteditable included)."},
    "wfNode_browser_input_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_input_selector": {"zh": "目标输入框的 CSS 选择器", "en": "CSS selector of the target field"},
    "wfNode_browser_input_value": {"zh": "要填入的内容", "en": "The text to fill in"},
    "wfNode_browser_upload": {"zh": "浏览器·上传文件", "en": "Browser · upload file"},
    "wfNode_browser_upload_desc": {"zh": "往页面的文件输入框(<input type=file>)塞一个本地文件——发布上传视频的关键一步。用 asset_id 传素材(如 {{export_1.asset_id}}),或 file_path 传本地绝对路径(二选一)。走 CDP setFileInputFiles,不弹系统对话框。", "en": "Hand a local file to a page's file input (<input type=file>) — the crucial step when publishing a video. Pass an asset with asset_id (e.g. {{export_1.asset_id}}) or a local absolute path with file_path (one or the other). It goes through CDP setFileInputFiles, so no system dialog opens."},
    "wfNode_browser_upload_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_upload_selector": {"zh": "文件输入框 CSS 选择器(默认 input[type=file])", "en": "CSS selector of the file input (defaults to input[type=file])"},
    "wfNode_browser_upload_asset_id": {"zh": "要上传的素材 id(如 {{export_1.asset_id}});与 file_path 二选一", "en": "The asset to upload (e.g. {{export_1.asset_id}}); either this or file_path"},
    "wfNode_browser_upload_file_path": {"zh": "或直接给本地绝对路径;与 asset_id 二选一", "en": "Or a local absolute path directly; either this or asset_id"},
    "wfNode_browser_upload_timeout_ms": {"zh": "等文件输入框出现的超时(毫秒,默认 15000)", "en": "How long to wait for the file input to appear (milliseconds, 15000 by default)"},
    "wfNode_browser_extract": {"zh": "浏览器·提取", "en": "Browser · extract"},
    "wfNode_browser_extract_desc": {"zh": "取元素的文本或属性;可一次取全部匹配。输出 value 供下游使用。", "en": "Read an element's text or an attribute; can take every match at once. Outputs value for downstream use."},
    "wfNode_browser_extract_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_extract_selector": {"zh": "CSS 选择器", "en": "CSS selector"},
    "wfNode_browser_extract_attribute": {"zh": "取该属性值(留空=取文本)", "en": "Read this attribute (leave empty to read the text)"},
    "wfNode_browser_extract_all": {"zh": "是=取全部匹配为数组;否=第一个", "en": "Yes = every match as an array; No = the first one"},
    "wfNode_browser_wait": {"zh": "浏览器·等待", "en": "Browser · wait"},
    "wfNode_browser_wait_desc": {"zh": "等元素出现/消失、URL 变化或页面出现某文本。", "en": "Wait for an element to appear or disappear, for the URL to change, or for some text to show up on the page."},
    "wfNode_browser_wait_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_wait_selector": {"zh": "等这个元素(默认等出现)", "en": "Wait for this element (waits for it to appear by default)"},
    "wfNode_browser_wait_gone": {"zh": "是=等元素消失", "en": "Yes = wait for the element to disappear"},
    "wfNode_browser_wait_url_contains": {"zh": "等 URL 包含此片段(与选择器/文本三选一)", "en": "Wait until the URL contains this fragment (one of selector / text / this)"},
    "wfNode_browser_wait_text": {"zh": "等页面出现此文本", "en": "Wait for this text to appear on the page"},
    "wfNode_browser_wait_timeout_ms": {"zh": "默认 15000", "en": "15000 by default"},
    "wfNode_browser_scroll": {"zh": "浏览器·滚动", "en": "Browser · scroll"},
    "wfNode_browser_scroll_desc": {"zh": "滚动到某元素,或按像素滚动页面。", "en": "Scroll to an element, or scroll the page by a number of pixels."},
    "wfNode_browser_scroll_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_scroll_selector": {"zh": "滚动到该元素(留空=按 dy 滚动)", "en": "Scroll to this element (leave empty to scroll by dy)"},
    "wfNode_browser_scroll_dy": {"zh": "无选择器时向下滚动的像素,默认 600", "en": "Pixels to scroll down when there is no selector; 600 by default"},
    "wfNode_browser_evaluate": {"zh": "浏览器·执行脚本", "en": "Browser · run script"},
    "wfNode_browser_evaluate_desc": {"zh": "在页面里执行一段 JS 表达式并取返回值(高级)。", "en": "Evaluate a JavaScript expression in the page and take its return value (advanced)."},
    "wfNode_browser_evaluate_session": {"zh": "来自「打开浏览器」的 session", "en": "The session from “Open browser”"},
    "wfNode_browser_evaluate_expression": {"zh": "JS 表达式,其返回值即输出 value", "en": "A JS expression; its return value becomes the output value"},
    "wfNode_browser_close": {"zh": "关闭浏览器", "en": "Close browser"},
    "wfNode_browser_close_desc": {"zh": "关闭会话:临时会话顺带清掉 cookie/存储。用完记得关,免得视图常驻。", "en": "Close the session; a throwaway session also has its cookies and storage wiped. Close it when you are done, or the view stays around."},
    "wfNode_browser_close_session": {"zh": "要关闭的 session", "en": "The session to close"},
    "jobMsg_trimQueued": {"zh": "截取排队中", "en": "Trim queued"},
    "jobMsg_trimRunning": {"zh": "正在截取", "en": "Trimming"},
    "jobMsg_trimDone": {"zh": "截取完成", "en": "Trimmed"},
    "jobMsg_proxyRunning": {"zh": "生成预览代理中", "en": "Generating the preview proxy"},
    "jobMsg_proxyDone": {"zh": "预览代理完成", "en": "Preview proxy ready"},
    "jobMsg_proxyFailed": {"zh": "预览代理生成失败", "en": "Preview proxy generation failed"},
    # ---- 下载/安装过程中的进度句 ----
    # 带 {} 的是**模板**:参数在产生它的地方算好、跟着 key 传出来,不把值拼进句子(拼进去就没法翻了)。
    "dlMsg_preparing": {"zh": "准备下载…", "en": "Preparing the download…"},
    "dlMsg_preparingShort": {"zh": "准备中…", "en": "Preparing…"},
    "dlMsg_creatingRuntime": {"zh": "创建运行环境…", "en": "Creating the runtime…"},
    "dlMsg_installingDeps": {
        "zh": "安装 {engine} 运行依赖(数 GB,首次较慢)…",
        "en": "Installing the {engine} runtime dependencies (several GB; the first time is slow)…",
    },
    "dlMsg_fetchingFishSource": {"zh": "拉取 Fish Speech 源码…", "en": "Fetching the Fish Speech source…"},
    "dlMsg_etaMinutes": {"zh": "剩余 {m}分{s}秒", "en": "{m}m {s}s left"},
    "dlMsg_etaSeconds": {"zh": "剩余 {s}秒", "en": "{s}s left"},
    "dlMsg_elapsed": {"zh": "下载中(已用 {m}分{s}秒)", "en": "Downloading (elapsed {m}m {s}s)"},
    "dlMsg_processDied": {"zh": "下载进程异常退出", "en": "The download process exited unexpectedly"},
    # ---- 转写模型目录 ----
    "asrLabel_funasr": {"zh": "FunASR(SenseVoice)", "en": "FunASR (SenseVoice)"},
    "asrDetail_funasr": {
        "zh": "支持 50+ 种语言,自动判语种;官方称识别效果优于 Whisper。含 VAD 断句、标点与说话人分离。",
        "en": "50+ languages with automatic detection; its authors report better accuracy than Whisper. Includes VAD segmentation, punctuation and speaker diarisation.",
    },
    "asrDetail_whisperSmall": {"zh": "多语种,自动检测语言;速度与精度均衡", "en": "Multilingual with automatic language detection; balanced speed and accuracy"},
    "asrDetail_whisperMedium": {"zh": "多语种,精度更高、更慢", "en": "Multilingual; more accurate, slower"},
    "asrDetail_whisperLarge": {"zh": "多语种最高精度,占用最大", "en": "Multilingual; highest accuracy, largest footprint"},
    # ---- 声音克隆引擎目录 ----
    "ttsDetail_f5": {
        "zh": "零样本声音克隆,给一段参考音频即可合成同音色语音(推荐)",
        "en": "Zero-shot voice cloning — give it one reference clip and it speaks in that voice (recommended).",
    },
    "ttsDetail_fishSpeech": {
        "zh": "零样本克隆,支持情感标签;一键下载源码 + 权重,占用更大",
        "en": "Zero-shot cloning with emotion tags; downloads source and weights in one go, larger footprint.",
    },
    # ---- 语音引擎(供应商)----
    "ttsProvider_clone": {"zh": "本地音色克隆", "en": "Local voice clone"},
    "ttsProviderNote_cloneReady": {"zh": "用音色库里的克隆音色,完全本地。", "en": "Uses cloned voices from your library — fully local."},
    "ttsProviderNote_cloneMissing": {
        "zh": "本地引擎还没装:去设置的「声音克隆」点「下载」装一次;只想马上出声的话,下面的「Edge 免费在线合成」不用装。",
        "en": "The local engine isn't installed yet — install it once from Settings → Voice clone. If you just want sound now, Edge below needs no setup.",
    },
    "ttsProviderNote_edge": {
        "zh": "免费在线合成,无需任何配置;需联网,微软 Edge 同款音色。",
        "en": "Free online synthesis, no setup; needs internet. Same voices as Microsoft Edge.",
    },
    "ttsProviderNote_openai": {
        "zh": "预置音色,不需要参考音频。自建 /audio/speech 兼容端点填档案里的 Endpoint 即可,不必另建一项。",
        "en": "Preset voices, no reference audio needed. For a self-hosted /audio/speech endpoint just set Endpoint on the profile — no separate entry required.",
    },
    "ttsProvider_openai": {"zh": "OpenAI 语音合成(含兼容端点)", "en": "OpenAI speech (incl. compatible endpoints)"},
    "ttsProvider_edge": {"zh": "Edge 免费语音(微软)", "en": "Edge free voices (Microsoft)"},
    "ttsProvider_bailian": {"zh": "阿里云百炼(qwen-tts)", "en": "Alibaba Bailian (qwen-tts)"},
    "ttsProvider_cosyvoice": {"zh": "阿里云百炼(CosyVoice)", "en": "Alibaba Bailian (CosyVoice)"},
    "ttsProviderNote_cosyvoice": {
        "zh": "同一把百炼 DashScope Key 的另一套语音 API。支持语速,音色 id 与 qwen-tts 完全不同。",
        "en": "The other speech API behind the same Bailian (DashScope) key. Supports speed; its voice ids differ entirely from qwen-tts.",
    },
    "ttsProviderNote_bailian": {
        "zh": "用百炼的 DashScope Key,音色固定四个。它不支持语速 —— 需要把配音精确塞进原时长的,请选别的引擎。",
        "en": "Uses your Bailian (DashScope) key; four fixed voices. No speed control — pick another engine when dubbing must fit an exact window.",
    },
    "ttsProvider_volcano": {"zh": "火山方舟(豆包)", "en": "Volcano Ark (Doubao)"},
    "ttsProvider_volcanoPodcast": {"zh": "火山播客(双人对话)", "en": "Volcano Podcast (two speakers)"},
    "ttsProviderNote_volcanoPodcast": {
        "zh": "两个发音人对谈;配置是 App ID + Access Token,不是方舟 API Key。",
        "en": "A two-speaker conversation; configured with App ID + Access Token, not an Ark API key.",
    },
    "ttsProviderNote_volcano": {
        "zh": "中文音色最好。配置账号 AK/SK 后可拉取账号内全部音色。",
        "en": "Best Chinese voices. Set the account AK/SK to pull every voice on the account.",
    },
    "translateErr_noProvider": {
        "zh": "没有可用的 AI 供应商,请先在设置里添加",
        "en": "No AI provider is available — add one in Settings first",
    },
    "translateErr_noCredential": {
        "zh": "供应商「{name}」还没有配置你的密钥,请先在设置里填写",
        "en": "Provider \u300c{name}\u300d has no key of yours yet — set it in Settings first",
    },
}


#: 本次请求的语言。由中间件按 Accept-Language 设定(见 app/main.py)。
#:
#: **为什么要有它**:任务消息由 12 个接口返回,若在每个路由里各取一次请求头再翻,就是同一个问题
#: 十二个答案 —— 漏一个,那一屏的任务就还是另一种语言。序列化那一层拿不到 Request,ContextVar 是
#: 让它知道"这一次是谁在问"的唯一办法。
#: 没有请求上下文时(飞书机器人、定时任务、后台线程)取缺省 —— 那正是它该给的答案。
_current_locale: ContextVar[str] = ContextVar("openstudio_locale", default=DEFAULT_LOCALE)


def set_current_locale(locale: str) -> None:
    _current_locale.set(locale)


def get_current_locale() -> str:
    return _current_locale.get()


def normalize_locale(raw: str | None) -> str:
    """把 Accept-Language 归一成我们支持的那几种。

    只取主语言标签(`zh-CN` → `zh`),不认的一律回落到缺省 —— **不猜**:与其把 `ja` 硬映射到
    某种语言,不如给缺省,至少它是一致的。
    """
    for part in (raw or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        primary = tag.split("-")[0]
        if primary in LOCALES:
            return primary
    return DEFAULT_LOCALE


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """翻一个 key,可带参数。

    **查不到就原样返回 key**,不抛错:一条文案缺翻译不该让整个接口 500。它会以 key 的样子出现在
    界面上——难看,但看得见,而棘轮保证它进不了主干。

    带参数的句子(「安装 {engine} 运行依赖…」)是模板 —— **参数在产生它的地方就算好、跟着 key 一起
    传出来**,而不是把值直接拼进句子。拼进去就没法翻了:那句话从此只有一种语言。
    格式化失败(模板少写了一个占位符)同样不抛错,退回未格式化的原句 —— 少个词好过整页 500。
    """
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(locale) or entry.get(DEFAULT_LOCALE) or key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


#: 状态字典里放模板参数的那一栏。翻完就摘掉 —— 它是给翻译用的,不该出现在 API 响应里。
PARAMS_FIELD = "message_params"


def translate_fields(payload: dict[str, Any], keys: tuple[str, ...], locale: str) -> dict[str, Any]:
    """把一个字典里指定的几个字段就地翻掉(返回新字典,不改原数据)。

    `message` 这一栏如果带模板参数(见 PARAMS_FIELD),用它来格式化,然后把参数栏摘掉。
    """
    params = payload.get(PARAMS_FIELD) or {}
    out = {
        **payload,
        **{
            k: t(payload[k], locale, **(params if k == "message" else {}))
            for k in keys
            if isinstance(payload.get(k), str)
        },
    }
    out.pop(PARAMS_FIELD, None)
    return out

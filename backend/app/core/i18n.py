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
    # ---- i18n 分区 B1(路由、插件、供应商设置等):这一批新加的 key 放在这行下面 ----
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
    # ---- AI 对话调用的报错(target_for 在每一通后端直连 LLM 的入口拦下) ----
    "aiChat_noChatModel": {
        "zh": "连接「{name}」下没有可用的对话模型",
        "en": "Connection \"{name}\" has no usable chat model.",
    },
    "aiChat_noBaseUrl": {
        "zh": "连接「{name}」还没填服务地址,去设置里补上再用",
        "en": "Connection \"{name}\" has no service address yet — add it in Settings first.",
    },
    "aiChat_agentOnly": {
        "zh": "连接「{name}」是订阅授权(如 Kimi Code),当前操作只支持直连 API;请改用支持订阅网关的画板、工作流或智能体入口",
        "en": "Connection \"{name}\" uses a subscription sign-in (e.g. Kimi Code), while this operation only supports a direct API. Use a board, workflow or agent entry point that supports the subscription gateway.",
    },
    "aiChat_oauthRequired": {
        "zh": "连接「{name}」还没有完成订阅授权,请先到设置里登录",
        "en": "Connection \"{name}\" has not completed its subscription sign-in. Sign in from Settings first.",
    },
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
    # ---- 从链接导入:取不到的原因(见 media/ytdlp.classify) ----
    #: **「不支持」和「没有」是两回事。** 此前 Unsupported URL 和 no video 共用一句「这个链接里
    #: 没有可下载的视频」—— 站点根本不认识,却被说成里面没有视频,用户只会换着链接反复试。
    "urlImportErr_unsupported": {
        "zh": "不支持这个网站或这种链接。换成某一条视频自己的页面地址再试。",
        "en": "This site or kind of link isn't supported. Try the page address of one specific video instead.",
    },
    "urlImportErr_noMedia": {
        "zh": "这个链接里没有找到视频或音频。",
        "en": "No video or audio was found at this link.",
    },
    "urlImportErr_loginRequired": {
        "zh": "这条内容要登录才能取。在「登录身份」里选一个已登录该站点的浏览器档案再试。",
        "en": "This content requires signing in. Choose a browser profile that is signed in to this site under “Signed-in identity” and try again.",
    },
    "urlImportErr_unavailable": {
        "zh": "这条内容不可用:可能是私密的、已被删除或已下架。",
        "en": "This content isn't available: it may be private, deleted or taken down.",
    },
    "urlImportErr_geoBlocked": {
        "zh": "这条内容在当前网络所在的地区看不到,或出口 IP 被站点限制。请为浏览器档案配置可用代理后重试。",
        "en": "This content isn't available from your current network's region, or the site blocks its IP. Set a working proxy for the browser profile and try again.",
    },
    "urlImportErr_notFound": {
        "zh": "这个地址取不到内容(404)。链接可能打错了,或者这条内容已经被删除。",
        "en": "Nothing was found at this address (404). The link may be mistyped, or the content has been deleted.",
    },
    "urlImportErr_forbidden": {
        "zh": "站点拒绝了匿名取流。请在「登录身份」里选一个已登录的浏览器档案,或为档案配置可用代理后重试。",
        "en": "The site refused anonymous access. Choose a signed-in browser profile under “Signed-in identity”, or set a working proxy for it, and try again.",
    },
    "urlImportErr_formatMismatch": {
        "zh": "这个站点没有给出可下载的格式。多半是登录身份与取流方式对不上 —— 换一个登录身份,或者先不选登录身份再试一次。",
        "en": "The site offered no downloadable format. The signed-in identity likely doesn't match how the stream is fetched — try another identity, or none.",
    },
    "urlImportErr_drm": {
        "zh": "这条内容受 DRM 版权保护,无法下载。",
        "en": "This content is DRM-protected and can't be downloaded.",
    },
    "urlImportErr_mergeFailed": {
        "zh": "音视频合并失败(ffmpeg)。改成「只要音频」通常能绕开;若一直如此,可能是这条流的格式特殊。",
        "en": "Merging video and audio failed (ffmpeg). Choosing audio only usually works around it; if it keeps happening, the stream format may be unusual.",
    },
    "urlImportErr_network": {
        "zh": "网络连不上这个站点(超时或连接失败)。检查网络,或为浏览器档案配置可用代理后重试。",
        "en": "Couldn't reach this site (timed out or the connection failed). Check the network, or set a working proxy for the browser profile, and try again.",
    },
    "urlImportErr_fileMissing": {
        "zh": "下载报成功,但没找到落地的文件。",
        "en": "The download reported success, but the file wasn't found.",
    },
    "urlImportErr_other": {"zh": "取不到这条内容:{detail}", "en": "Couldn't fetch this: {detail}"},
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
    #: 重启之后接着取已经提交给供应商的那一条 —— 不再提交,不会再扣一次费。
    "jobMsg_generationResuming": {"zh": "后端重启过,正在接着取回已提交的生成结果", "en": "The backend restarted; picking up the result of the already-submitted generation"},
    "jobMsg_generationDone": {"zh": "生成完成", "en": "Generation complete"},
    "jobMsg_generationFailed": {"zh": "生成失败", "en": "Generation failed"},
    "jobMsg_waitingWorker": {"zh": "等待执行器认领", "en": "Waiting for a worker to claim it"},
    "jobMsg_interrupted": {"zh": "已中断", "en": "Interrupted"},
    "jobMsg_cancelled": {"zh": "已取消", "en": "Cancelled"},
    "jobMsg_leaseExpired": {"zh": "执行器失联", "en": "Worker lost"},
    #: 失败**原因**那一半。此前这三句是写死的中文 —— `error_key` / `error_params` 这套
    #: 东西是完整的(列、迁移、出口校验器、blame() 都在),而总线自己的三条终态一条都没用它。
    "jobErr_backendRestart": {
        "zh": "后端重启导致任务中断,请重新发起",
        "en": "The backend restarted and interrupted this task; please start it again",
    },
    "jobErr_cancelled": {"zh": "已取消", "en": "Cancelled"},
    "jobErr_noDubSucceeded": {"zh": "没有一条配音成功", "en": "No line was dubbed successfully"},

    # ---- 确认卡的措辞 ----------------------------------------------------------------
    #: **确认卡是授权界面**:用户点「批准」之前唯一会读的就是这一行。所以它和任务消息同一条
    #: 规矩 —— 落库存 key,出口按读的人的语言翻。此前 23 个摘要返回的都是写死的中文,
    #: 于是英文用户读到的授权提示永远是中文,等于没有提示。
    "confirm_editTimeline": {
        "zh": "{count} 个时间线操作: {kinds}",
        "en": "{count} timeline operations: {kinds}",
    },
    "confirm_renderSequence": {"zh": "导出时间线为 mp4", "en": "Export the timeline as mp4"},
    "confirm_dubSubtitles": {
        "zh": "给{scope}配音{fit}(配到一条单独的配音轨;{original})",
        "en": "Dub {scope}{fit} (onto its own dub track; {original})",
    },
    "confirm_dubScopeClips": {"zh": "{count} 条字幕", "en": "{count} subtitles"},
    "confirm_dubScopeTrack": {"zh": "整条字幕轨", "en": "the whole subtitle track"},
    "confirm_dubScopeTrackCounted": {
        "zh": "整条字幕轨({count} 条字幕)",
        "en": "the whole subtitle track ({count} subtitles)",
    },
    "confirm_dubFit": {"zh": ",并变速压回原段落长度", "en": ", time-stretched back to each segment's length"},
    "confirm_separateAudio": {
        "zh": "把这份素材拆成「人声」和「背景音」两份新素材(原素材不动;本机跑模型,长素材会很慢)",
        "en": "Split this asset into separate voice and background tracks (the original is untouched; runs locally, slow on long media)",
    },
    "confirm_denoiseAudio": {
        "zh": "用{engine}{strength},产出一份新素材(视频保留画面、只换声音;原素材不动){music}",
        "en": "Denoise with {engine}{strength}, producing a new asset (video keeps its picture, only the audio changes; the original is untouched){music}",
    },
    "confirm_denoiseStrength": {"zh": "做{level}降噪", "en": " at {level} strength"},
    "confirm_denoiseLight": {"zh": "轻度", "en": "light"},
    "confirm_denoiseMedium": {"zh": "中度", "en": "medium"},
    "confirm_denoiseStrong": {"zh": "强力", "en": "strong"},
    "confirm_denoiseDefaultEngine": {"zh": "内置降噪", "en": "the built-in denoiser"},
    "confirm_denoiseRemovesMusic": {
        "zh": ";**背景音乐也会被当成噪声去掉**",
        "en": "; **background music will be removed as noise too**",
    },
    "confirm_videoToGif": {
        "zh": "把视频转成新的 GIF({fps} fps,宽 {width} px{clip}),原视频不变",
        "en": "Convert the video into a new GIF ({fps} fps, {width} px wide{clip}); the video is unchanged",
    },
    "confirm_gifClip": {"zh": ",截取 {duration} 秒", "en": ", taking {duration}s"},
    "confirm_originalDuck": {"zh": "配音说话时原声压低", "en": "duck the original while the dub speaks"},
    "confirm_originalMute": {"zh": "原声静音", "en": "mute the original"},
    "confirm_originalKeep": {"zh": "原声不动", "en": "leave the original as is"},
    "confirm_generateImage": {"zh": "生成图片: {asked}", "en": "Generate an image: {asked}"},
    "confirm_generateVideo": {"zh": "生成视频: {asked}", "en": "Generate a video: {asked}"},
    "confirm_generateAudio": {"zh": "生成音频: {asked}", "en": "Generate audio: {asked}"},
    "confirm_generatePodcast": {"zh": "生成播客: {asked}", "en": "Generate a podcast: {asked}"},
    "punct_listSep": {"zh": "、", "en": ", "},
    "confirm_createWorkflow": {"zh": "创建工作流「{name}」({nodes} 个节点){warning}", "en": "Create workflow \u300c{name}\u300d ({nodes} nodes){warning}"},
    "confirm_updateWorkflow": {"zh": "修改工作流({nodes} 个节点){warning}", "en": "Update workflow ({nodes} nodes){warning}"},
    "confirm_updateWorkflowPlain": {"zh": "修改工作流{warning}", "en": "Update workflow{warning}"},
    "confirm_editWorkflow": {"zh": "{count} 个工作流编辑: {kinds}{warning}", "en": "{count} workflow edits: {kinds}{warning}"},
    "confirm_editWorkflowCode": {"zh": "  ⚠️ 含代码节点(运行时执行本地 Python)", "en": "  ⚠️ Includes a code node (runs local Python when the workflow runs)"},
    "confirm_runWorkflow": {"zh": "运行工作流{named}(可能产生 AI/渲染消耗){warning}", "en": "Run workflow{named} (may incur AI/render cost){warning}"},
    "confirm_workflowNamed": {"zh": "「{name}」", "en": " \u300c{name}\u300d"},
    "confirm_editBoard": {"zh": "{count} 个画板编辑: {kinds}", "en": "{count} board edits: {kinds}"},
    "confirm_externalNodes": {
        "zh": "  ⚠️ 含{labels}节点(后果在本应用之外,撤不回)",
        "en": "  ⚠️ Includes {labels} nodes (their effects are outside this app and cannot be undone)",
    },
    # ---- Blender 场景互通:领域报错(见 domain/blender,LocalizedError) ----
    "blenderErr_notLocalDesktop": {"zh": "场景互通需要本机桌面后端与 Blender 运行在同一台电脑。", "en": "Scene sync needs the desktop backend and Blender running on the same computer."},
    "blenderErr_connectionNotFound": {"zh": "找不到这个 Blender 连接。", "en": "This Blender connection wasn't found."},
    "blenderErr_localOnly": {"zh": "场景互通仅支持本机 Blender。", "en": "Scene sync only works with Blender on this computer."},
    "blenderErr_badPort": {"zh": "请将 Blender 连接端口设为 1–65535 的整数。", "en": "Set the Blender connection port to a whole number from 1 to 65535."},
    "blenderErr_blocked": {"zh": "{reason}", "en": "{reason}"},
    "blenderErr_noConnection": {"zh": "还没有连接 Blender：在插件页安装并启用「Blender MCP」，并在 Blender 里开启 MCP Add-on。", "en": "Blender isn't connected yet: install and enable “Blender MCP” on the Plugins page, then turn on the MCP add-on in Blender."},
    "blenderErr_busy": {"zh": "正在与 Blender 同步，请稍后再试。", "en": "A sync with Blender is already running. Try again in a moment."},
    "blenderErr_plugin": {"zh": "Blender 插件出错：{detail}", "en": "The Blender plugin failed: {detail}"},
    "blenderErr_timeout": {"zh": "这一步等了 {seconds} 秒还没回来。Blender 那边很可能还在跑 —— 先切过去看一眼，不要立刻重试：重试会排在它后面，同样等不到。", "en": "This step didn't come back after {seconds} seconds. Blender is most likely still working — switch over and check before retrying; a retry would queue behind it and time out too."},
    "blenderErr_unresponsive": {"zh": "Blender 没有响应，请检查 Add-on 连接。", "en": "Blender didn't respond. Check the add-on connection."},
    "blenderErr_addonNotRunning": {"zh": "连不上 Blender。请先打开 Blender，并在 Blender MCP 附加组件里启动连接（3D 视图侧栏的 BlenderMCP 面板）。", "en": "Can't reach Blender. Open Blender and start the connection in the Blender MCP add-on (the BlenderMCP panel in the 3D viewport sidebar)."},
    "blenderErr_syncFailed": {"zh": "Blender 未完成同步：{detail}", "en": "Blender didn't finish syncing: {detail}"},
    "blenderErr_syncFailedNoDetail": {"zh": "Blender 未完成同步，请检查 Blender Add-on 后重试。", "en": "Blender didn't finish syncing. Check the Blender add-on and try again."},
    "blenderErr_tooLarge": {"zh": "Blender 返回的数据过大。", "en": "Blender returned too much data."},
    "blenderErr_unreadable": {"zh": "Blender 同步结果无法读取，请重试。", "en": "The sync result from Blender couldn't be read. Try again."},
    "blenderErr_transferNotFound": {"zh": "找不到这次同步记录。", "en": "This sync record wasn't found."},
    "blenderErr_shotNoCamera": {"zh": "镜头「{name}」找不到对应的机位。", "en": "Shot “{name}” has no matching camera."},
    "blenderErr_sceneChanged": {"zh": "场景已变更，请等待保存完成后重新发送。", "en": "The scene has changed. Wait for it to save, then send again."},
    "blenderErr_shotNotFound": {"zh": "找不到这个镜头。", "en": "This shot wasn't found."},
    "blenderErr_sendFirst": {"zh": "请先成功发送一个场景。", "en": "Send a scene successfully first."},
    "blenderErr_noModel": {"zh": "Blender 没有生成可接收的模型，请重试。", "en": "Blender didn't produce a model that can be received. Try again."},
    "blenderErr_shotOutOfRange": {"zh": "Blender 镜头超出当前场景支持范围，未导入。", "en": "The Blender shot is outside what this scene supports and wasn't imported."},
    "blenderErr_noExport": {"zh": "Blender 没有导出可用的模型，请重试。", "en": "Blender didn't export a usable model. Try again."},
    "blenderErr_noRender": {"zh": "Blender 没有渲出画面，请检查 Add-on 连接后重试。", "en": "Blender didn't render an image. Check the add-on connection and try again."},
    "blenderErr_unknownView": {"zh": "不认识的视角 {name}；可选 {choices}，或者写「方位角/仰角」如 120/25", "en": "Unknown view {name}; use one of {choices}, or “azimuth/elevation” such as 120/25"},
    "blenderErr_elevationRange": {"zh": "仰角要在 -89 到 89 之间，给的是 {value}", "en": "Elevation must be between -89 and 89; got {value}"},
    "blenderErr_shadingChoice": {"zh": "shading 只能是 {choices}", "en": "shading must be one of {choices}"},
    "blenderErr_zoomRange": {"zh": "zoom 要在 {low} 到 {high} 之间，给的是 {value}", "en": "zoom must be between {low} and {high}; got {value}"},
    "blenderErr_noCode": {"zh": "没有要执行的代码", "en": "There's no code to run"},
    "blenderErr_cantReadScene": {"zh": "无法读取 Blender 场景，请在 Blender 中开启 MCP Add-on。", "en": "Couldn't read the Blender scene. Turn on the MCP add-on in Blender."},
    "blenderErr_interruptedByRestart": {"zh": "后端重启，这次同步没有完成。", "en": "The backend restarted, so this sync didn't finish."},
    "blenderErr_projectNotFound": {"zh": "找不到这次同步的 Blender 工程文件。", "en": "The Blender project file for this sync wasn't found."},
    # ---- Blender 场景互通:取回/接收时的提示(worker 回 key + params,bridge.render_warnings 翻) ----
    "blenderWarn_modelUnplaced": {"zh": "模型「{name}」没有找到对应的位置，已跳过。", "en": "Model “{name}” had no matching position and was skipped."},
    "blenderWarn_modelFailed": {"zh": "模型「{name}」导入失败：{detail}", "en": "Model “{name}” couldn't be imported: {detail}"},
    "blenderWarn_shotMissing": {"zh": "镜头「{name}」不存在，保留发送时的镜头。", "en": "Shot “{name}” no longer exists; the shot as sent was kept."},
    "blenderWarn_shotUnsupportedView": {"zh": "镜头「{name}」使用正交或倾斜视角，保留发送时的镜头。", "en": "Shot “{name}” uses an orthographic or tilted view; the shot as sent was kept."},
    "blenderWarn_shotSampled": {"zh": "镜头「{name}」已采样为 100 个关键帧，请检查运动。", "en": "Shot “{name}” was sampled into 100 keyframes. Check the motion."},
    "blenderWarn_shotTruncated": {"zh": "镜头「{name}」只取了 Blender 时间线的前 120 秒。", "en": "Only the first 120 seconds of the Blender timeline were taken for shot “{name}”."},
    "blenderWarn_cameraNotPerspective": {"zh": "相机「{name}」没有取回：它是正交或全景相机，Mosael 只有透视镜头。", "en": "Camera “{name}” wasn't brought back: it's orthographic or panoramic, and Mosael only has perspective shots."},
    "blenderWarn_cameraRolled": {"zh": "相机「{name}」没有取回：画面有滚转或正对上下方，Mosael 的镜头始终保持水平。", "en": "Camera “{name}” wasn't brought back: it's rolled or looking straight up or down, and Mosael shots always stay level."},
    "blenderWarn_cameraOverLimit": {"zh": "相机「{name}」没有取回：一个场景最多 {limit} 个镜头。", "en": "Camera “{name}” wasn't brought back: a scene holds at most {limit} shots."},
    "blenderWarn_cameraOutOfRange": {"zh": "相机「{name}」没有取回：位置或视角超出 Mosael 支持的范围。", "en": "Camera “{name}” wasn't brought back: its position or field of view is outside what Mosael supports."},
    "blenderWarn_noActiveCamera": {"zh": "场景里没有活动相机，跳过 camera 视角。", "en": "The scene has no active camera, so the camera view was skipped."},
    "blenderWarn_lightUnknownType": {"zh": "灯光「{name}」没有取回：Mosael 不认识 {kind} 类型的灯。", "en": "Light “{name}” wasn't brought back: Mosael doesn't know {kind} lights."},
    "blenderWarn_lightOverLimit": {"zh": "灯光「{name}」没有取回：一个场景最多 {limit} 个物体。", "en": "Light “{name}” wasn't brought back: a scene holds at most {limit} objects."},
    "blenderWarn_lightOutOfRange": {"zh": "灯光「{name}」没有取回：位置或亮度超出 Mosael 支持的范围。", "en": "Light “{name}” wasn't brought back: its position or brightness is outside what Mosael supports."},
    "blenderWarn_spotAsPoint": {"zh": "聚光灯「{name}」按点光取回：Mosael 没有聚光，{angle}° 的光锥没有带过来。", "en": "Spot light “{name}” came back as a point light: Mosael has no spot lights, so its {angle}° cone was dropped."},
    "blenderWarn_areaAsPoint": {"zh": "面光「{name}」按点光取回：Mosael 没有面光，面积和朝向没有带过来。", "en": "Area light “{name}” came back as a point light: Mosael has no area lights, so its size and direction were dropped."},
    "blenderWarn_extraSun": {"zh": "太阳「{name}」没有取回：Mosael 只有一盏主光，已用「{used}」。", "en": "Sun “{name}” wasn't brought back: Mosael has a single key light and used “{used}”."},
    "blenderWarn_sunBelowHorizon": {"zh": "太阳「{name}」的光从地平线以下射来，已按贴地（仰角 0°）处理。", "en": "Sun “{name}” shines from below the horizon; it was set at ground level (0° elevation)."},
    "blenderWarn_sunTooBright": {"zh": "太阳「{name}」的强度超出 Mosael 的上限，已按 {value} 处理。", "en": "Sun “{name}” is brighter than Mosael allows; it was set to {value}."},
    "blenderWarn_sunColor": {"zh": "太阳「{name}」的颜色不是色温能表示的，已按最接近的 {kelvin} K 处理。", "en": "Sun “{name}” has a color that a color temperature can't express; the closest, {kelvin} K, was used."},
    "blenderDefaultModelName": {"zh": "Blender 模型", "en": "Blender model"},
    "blenderDefaultSceneName": {"zh": "Blender 场景", "en": "Blender scene"},
    "blenderErr_staleRevision": {"zh": "场景已更新到修订 {revision}，请先 get_scene 再导入。", "en": "The scene is now at revision {revision}; call get_scene before importing."},
    "confirm_blenderExecute": {
        "zh": "⚠️ 在你的 Blender 里执行建模代码({lines} 行){purpose} —— Blender 的 Python 不是沙箱,可读写本机文件;执行前已压撤销点,可在 Blender 里 ⌘Z",
        "en": "⚠️ Run modelling code in your Blender ({lines} lines){purpose} — Blender's Python is not a sandbox and can read and write local files; an undo point was pushed first, so ⌘Z works in Blender",
    },
    "confirm_blenderPurpose": {"zh": ":{purpose}", "en": ": {purpose}"},
    "confirm_deleteAssets": {
        "zh": "永久删除 {count} 个素材({names}){tail} —— 文件会从磁盘上清掉,撤不回来",
        "en": "Permanently delete {count} assets ({names}){tail} — the files are removed from disk and cannot be recovered",
    },
    "confirm_deleteAssetsClips": {
        "zh": ",时间线上引用它们的 {clips} 个片段会变成「素材已删除」",
        "en": ", and {clips} clips referencing them on the timeline become \u300casset deleted\u300d",
    },
    "confirm_deleteProjects": {
        "zh": "永久删除 {count} 个项目({names}),连同它们的时间线{tail} —— 撤不回来",
        "en": "Permanently delete {count} projects ({names}) along with their timelines{tail} — this cannot be undone",
    },
    "confirm_deleteProjectsAssets": {
        "zh": ";里面的 {assets} 个素材不会被删,会回到工作区",
        "en": "; the {assets} assets inside are not deleted and return to the workspace",
    },
    "confirm_publishAsset": {"zh": "⚠️ 用你的账号**公开发布**{what}", "en": "⚠️ **Publish publicly** with your account: {what}"},
    "confirm_publishTitled": {"zh": "「{title}」", "en": "\u300c{title}\u300d"},
    "confirm_publishUntitled": {"zh": "一条内容", "en": "one item"},
    "confirm_httpRequest": {"zh": "⚠️ 向外部发起 {method} 请求: {url}", "en": "⚠️ Make an outbound {method} request to {url}"},
    "confirm_runCode": {
        "zh": "在隔离沙箱里运行一段 Python({chars} 字符,无网络、看不到你的文件){head}",
        "en": "Run Python in an isolated sandbox ({chars} chars, no network, cannot see your files){head}",
    },
    "confirm_runHostCode": {
        "zh": "⚠️ **不隔离**,直接在你的电脑上运行一段 Python({chars} 字符),可读写你的文件{head}",
        "en": "⚠️ **Not isolated** — run Python directly on your computer ({chars} chars); it can read and write your files{head}",
    },
    "confirm_codeHead": {"zh": ": {head}…", "en": ": {head}…"},
    "confirm_browserOpen": {"zh": "智能体打开{mode}浏览器{target}", "en": "The agent opens a {mode} browser{target}"},
    "confirm_browserNamed": {"zh": "具名持久", "en": "named, persistent"},
    "confirm_browserEphemeral": {"zh": "临时", "en": "temporary"},
    "confirm_browserTarget": {"zh": " → {url}", "en": " → {url}"},
    "confirm_browserPoolOpen": {
        "zh": "⚠️ 智能体请求复用你的浏览器档案 {who} 的登录身份跑任务{target}",
        "en": "⚠️ The agent asks to reuse the signed-in identity of your browser profile {who}{target}",
    },
    "confirm_profilePublish": {"zh": "「{name}」({platform} 发布账号)", "en": "\u300c{name}\u300d ({platform} publishing account)"},
    "confirm_profileGeneric": {"zh": "「{name}」(通用档案)", "en": "\u300c{name}\u300d (general profile)"},
    "confirm_originalSeparate": {
        "zh": "原声只去掉人声、留背景音(需要本机已装好分离引擎)",
        "en": "strip only the voice from the original, keeping the background (needs the separation engine installed locally)",
    },
    "jobErr_leaseExpired": {
        "zh": "执行器失联,任务已停止;请检查产出后重新发起",
        "en": "The worker went away and the task stopped; check the output and start it again",
    },
    "jobMsg_claimed": {"zh": "执行器已认领", "en": "Claimed by a worker"},
    "jobMsg_workflowQueued": {"zh": "工作流排队中: {name}", "en": "Workflow queued: {name}"},
    "jobMsg_workflowRunning": {"zh": "工作流运行中: {name}", "en": "Workflow running: {name}"},
    "jobMsg_workflowDone": {"zh": "工作流完成: {name}", "en": "Workflow complete: {name}"},
    "jobMsg_workflowFailed": {"zh": "工作流失败: {name}", "en": "Workflow failed: {name}"},
    "jobMsg_publishWaiting": {"zh": "等待桌面发布器认领: {title}", "en": "Waiting for the desktop publisher: {title}"},
    "jobMsg_publishRunning": {"zh": "桌面发布器执行中: {title}", "en": "Desktop publisher running: {title}"},
    "jobMsg_publishDone": {"zh": "发布完成: {title}", "en": "Published: {title}"},
    "jobMsg_publishFailed": {"zh": "发布失败: {title}", "en": "Publishing failed: {title}"},
    "jobMsg_publishCancelled": {"zh": "发布已取消: {title}", "en": "Publishing cancelled: {title}"},
    "jobMsg_publishStatus": {"zh": "发布 {status}: {title}", "en": "Publish {status}: {title}"},
    "jobMsg_proxyQueued": {"zh": "生成预览代理排队中", "en": "Proxy generation queued"},
    #: 配置字段的名字(节点检查器上每一行的标题)。按**键名**给,不按节点给 ——
    #: selector 在六种浏览器节点里是同一个意思。
    "wfField_account_id": {"zh": "发布账号", "en": "Publishing account"},
    "wfField_all": {"zh": "全部", "en": "All"},
    "wfField_asset_id": {"zh": "素材", "en": "Asset"},
    "wfField_asset_ids": {"zh": "素材", "en": "Assets"},
    "wfField_clip_id": {"zh": "片段", "en": "Clip"},
    "wfField_attribute": {"zh": "取哪个属性", "en": "Attribute"},
    "wfField_body": {"zh": "子图", "en": "Subgraph"},
    "wfField_code": {"zh": "代码", "en": "Code"},
    "wfField_condition": {"zh": "条件", "en": "Condition"},
    "wfField_description": {"zh": "说明", "en": "Description"},
    "wfField_duration": {"zh": "时长", "en": "Duration"},
    "wfField_at": {"zh": "落点", "en": "Position"},
    "wfField_concurrency": {"zh": "同时跑几项", "en": "Concurrency"},
    "wfField_start_field": {"zh": "起点字段", "en": "Start field"},
    "wfField_end_field": {"zh": "终点字段", "en": "End field"},
    "wfField_text_field": {"zh": "文本字段", "en": "Text field"},
    "wfField_allow_empty": {"zh": "允许为空", "en": "Allow empty"},
    "wfField_max_duration": {"zh": "最长时长", "en": "Max duration"},
    "wfField_dy": {"zh": "纵向距离", "en": "Vertical distance"},
    "wfField_end": {"zh": "结束位置", "en": "End"},
    "wfField_engine": {"zh": "引擎", "en": "Engine"},
    "wfField_strength": {"zh": "强度", "en": "Strength"},
    "wfField_exact": {"zh": "精确匹配", "en": "Exact match"},
    "wfField_expression": {"zh": "表达式", "en": "Expression"},
    "wfField_file_path": {"zh": "文件路径", "en": "File path"},
    "wfField_find": {"zh": "查找", "en": "Find"},
    "wfField_fps": {"zh": "帧率", "en": "Frame rate"},
    "wfField_frequency_penalty": {"zh": "重复惩罚", "en": "Frequency penalty"},
    "wfField_gone": {"zh": "等它消失", "en": "Wait until gone"},
    "wfField_headers": {"zh": "请求头", "en": "Headers"},
    "wfField_input": {"zh": "入参", "en": "Arguments"},
    "wfField_inputs": {"zh": "入参映射", "en": "Input mapping"},
    "wfField_height": {"zh": "高度", "en": "Height"},
    "wfField_ranges": {"zh": "时间范围", "en": "Time ranges"},
    "wfField_min_confidence": {"zh": "最低置信度", "en": "Minimum confidence"},
    "wfField_max_removal_ratio": {"zh": "最大删除比例", "en": "Maximum removal ratio"},
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
    "wfField_voice": {"zh": "音色", "en": "Voice"},
    # 它和 voice_id 从不同时出现(见 synthesize_speech 的说明),所以两格都叫「音色」——
    # 一个界面上只有一格的东西,不需要在名字里解释它是哪一种。
    "wfField_speed": {"zh": "语速", "en": "Speed"},
    "wfField_workflow_id": {"zh": "工作流", "en": "Workflow"},
    "wfField_width": {"zh": "宽度", "en": "Width"},
    # 输出接点与同名配置字段共用这组语义名。
    "wfField_applied": {"zh": "已应用数量", "en": "Applied"},
    "wfField_assets": {"zh": "素材列表", "en": "Assets"},
    "wfField_audio_track_id": {"zh": "音频轨道", "en": "Audio track"},
    "wfField_count": {"zh": "数量", "en": "Count"},
    "wfField_generation_id": {"zh": "生成任务", "en": "Generation"},
    "wfField_ids": {"zh": "ID 列表", "en": "IDs"},
    "wfField_iterations": {"zh": "迭代次数", "en": "Iterations"},
    "wfField_json": {"zh": "JSON", "en": "JSON"},
    "wfField_language": {"zh": "语言", "en": "Language"},
    "wfField_length": {"zh": "长度", "en": "Length"},
    "wfField_removed": {"zh": "移除数量", "en": "Removed"},
    "wfField_removed_seconds": {"zh": "移除时长", "en": "Removed duration"},
    "wfField_result": {"zh": "结果", "en": "Result"},
    "wfField_results": {"zh": "结果列表", "en": "Results"},
    "wfField_revision": {"zh": "版本", "en": "Revision"},
    "wfField_segments": {"zh": "分段", "en": "Segments"},
    "wfField_texts": {"zh": "逐条文本", "en": "Per-segment lines"},
    "wfField_clip_ids": {"zh": "片段", "en": "Clips"},
    "wfField_keep_original": {"zh": "保留原文", "en": "Keep the original"},
    "wfField_match_duration": {"zh": "压回原长度", "en": "Fit to original length"},
    "wfField_line": {"zh": "配音文本", "en": "Text to dub"},
    "wfField_original_audio": {"zh": "原声", "en": "Original audio"},
    "wfField_done": {"zh": "完成条数", "en": "Done"},
    "wfField_failed": {"zh": "失败条数", "en": "Failed"},
    "wfField_sent": {"zh": "已发送", "en": "Sent"},
    "wfField_source_asset_id": {"zh": "来源素材", "en": "Source asset"},
    "wfField_status": {"zh": "状态", "en": "Status"},
    "wfField_timed_text": {"zh": "带时间码文本", "en": "Timed text"},
    "wfField_timeline_end": {"zh": "时间线结束位置", "en": "Timeline end"},
    "wfField_timeline_start": {"zh": "时间线起始位置", "en": "Timeline start"},
    "wfField_tracks": {"zh": "轨道列表", "en": "Tracks"},
    "wfField_transcript_id": {"zh": "逐字稿", "en": "Transcript"},
    "wfField_updated": {"zh": "更新数量", "en": "Updated"},
    "wfField_video_track_id": {"zh": "视频轨道", "en": "Video track"},
    "wfField_waited": {"zh": "等待结果", "en": "Wait result"},
    "wfField_layout": {"zh": "布景", "en": "Layout"},
    "wfField_scene_id": {"zh": "3D 场景", "en": "3D scene"},
    "wfField_shot_id": {"zh": "镜头", "en": "Shot"},
    "wfField_shot_ids": {"zh": "镜头列表", "en": "Shots"},
    "wfField_shot_count": {"zh": "镜头数", "en": "Shot count"},
    "wfField_render": {"zh": "渲染内容", "en": "Render"},
    "wfField_source_group": {"zh": "用哪一组素材", "en": "Which sources to use"},
    #: 节点面板的分组名。
    "wfCat_flow": {"zh": "流程", "en": "Flow"},
    "wfCat_ai": {"zh": "AI", "en": "AI"},
    "wfCat_audio": {"zh": "音频", "en": "Audio"},
    "wfCat_asset": {"zh": "素材", "en": "Assets"},
    "wfCat_3d": {"zh": "3D", "en": "3D"},
    "wfCat_knowledge": {"zh": "知识库", "en": "Knowledge"},
    "wfNode_note_search": {"zh": "检索笔记", "en": "Search notes"},
    "wfNode_note_search_desc": {"zh": "按标题、正文、标签与专题检索当前工作区笔记，返回带来源的摘要；完整正文请接「读取笔记」。", "en": "Search workspace titles, content, tags and topics. Returns cited excerpts; connect Read note for full content."},
    "wfNode_note_read": {"zh": "读取笔记", "en": "Read note"},
    "wfNode_note_read_desc": {"zh": "选择笔记，输出完整 Markdown 正文及来源链接。版本留空读取最新内容，也可指定历史版本。", "en": "Select a note to read its complete Markdown and source link. Leave revision empty for the latest content or pin a version."},
    "wfNode_note_create": {"zh": "保存为笔记", "en": "Save as note"},
    "wfNode_note_create_desc": {"zh": "把文案或上游输出保存为当前工作区的新笔记，不覆盖已有文档。", "en": "Save text or upstream output as a new workspace note, keeping existing documents intact."},
    "wfField_query": {"zh": "检索词", "en": "Search query"},
    "wfField_note_id": {"zh": "笔记", "en": "Note"},
    "wfField_markdown": {"zh": "正文（Markdown）", "en": "Content (Markdown)"},
    "wfField_citation_url": {"zh": "来源链接", "en": "Source link"},
    "wfField_notes": {"zh": "笔记列表", "en": "Notes"},
    "wfField_has_more": {"zh": "还有更多结果", "en": "More results"},
    "wfField_offset": {"zh": "起始位置", "en": "Offset"},
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
    "wfNode_transcribe_asset_engine": {"zh": "「自动」跟随设置页;选定一个会固定本次工作流用的转写引擎。", "en": "Auto follows Settings; an explicit choice pins the ASR engine for this workflow run."},
    "wfNode_export_sequence": {"zh": "导出时间线", "en": "Export timeline"},
    "wfNode_export_sequence_desc": {"zh": "渲染导出一条时间线,产出新素材。", "en": "Render a timeline to a file and register it as a new asset."},
    "wfNode_video_to_gif": {"zh": "视频转 GIF", "en": "Video to GIF"},
    "wfNode_video_to_gif_desc": {"zh": "把视频转换成一份新的 GIF 素材，原视频保持不变。", "en": "Convert a video into a new GIF asset while preserving the source video."},
    "wfNode_video_to_gif_asset_id": {"zh": "源视频素材", "en": "Source video asset"},
    "wfNode_video_to_gif_fps": {"zh": "帧率，默认 12（1–30）", "en": "Frame rate; 12 by default (1–30)"},
    "wfNode_video_to_gif_width": {"zh": "最大宽度，默认 720（64–1920）", "en": "Maximum width; 720 by default (64–1920)"},
    "wfNode_video_to_gif_start": {"zh": "从第几秒开始，默认 0", "en": "Start time in seconds; 0 by default"},
    "wfNode_video_to_gif_duration": {"zh": "转换多少秒，留空到视频末尾", "en": "Seconds to convert; leave empty to use the rest of the video"},
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
    "wfNode_timeline_append_at": {"zh": "放在时间线的第几秒。留空就接在这条轨道的末尾", "en": "Where on the timeline to place it, in seconds. Leave empty to append after the last clip on the track"},
    "wfNode_timeline_append_max_duration": {
        "zh": "最长占几秒。比这长就加速塞进去(最多 1.5 倍,再快就听不清了);留空不限。适合让一段口播不压到下一镜",
        "en": "The longest it may run, in seconds. Longer clips are sped up to fit (at most 1.5×, beyond that speech becomes hard to follow); leave empty for no limit. Useful to keep narration from running into the next shot",
    },
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
    "wfNode_ai_generate_source_group": {
        "zh": "有的模型(如 Seedance)首尾帧和参考素材不能同时用。两组都接上时,在这里选这一次用哪一组,另一组会被忽略;「全部」表示原样全部交给模型",
        "en": "Some models (such as Seedance) cannot combine first/last frames with reference media. With both connected, choose which group this run uses and the other is ignored; All passes everything to the model",
    },
    # ---- i18n 分区 B2(ai/ 下的供应商与运行时):这一批新加的 key 放在这行下面 ----
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
    "wfNode_speech_engine": {"zh": "嗓子从哪来:用配音库里克隆的,还是某个引擎现成的", "en": "Where the voice comes from: one you cloned, or a stock voice from an engine"},
    "wfNode_speech_voice": {"zh": "用哪把嗓子。清单跟着引擎变:克隆时是配音库里的音色,选了引擎就是那个引擎的音色", "en": "Which voice to use. The list follows the engine: your voice library for cloning, otherwise that engine's own voices"},
    "wfSpeechEngineClone": {"zh": "克隆音色(配音库)", "en": "Cloned voice (voice library)"},
    "wfNode_synthesize_speech_speed": {"zh": "语速倍率,默认 1", "en": "Speed multiplier; 1 by default"},
    "wfNode_notify": {"zh": "发送通知", "en": "Send notification"},
    "wfNode_notify_desc": {"zh": "给工作区成员推送一条站内通知。", "en": "Push an in-app notification to the members of this workspace."},
    "wfNode_notify_body": {"zh": "通知正文", "en": "Notification body"},
    "wfNode_translate": {"zh": "翻译", "en": "Translate"},
    "wfNode_translate_desc": {"zh": "把文本翻译成目标语言:Google 免费接口(无需 key)或 AI 供应商。", "en": "Translate text into a target language: Google's free endpoint (no key needed) or an AI provider."},
    "wfNode_translate_engine": {"zh": "翻译引擎(默认 Google 免费)", "en": "Translation engine (Google's free one by default)"},
    "wfNode_translate_lines": {"zh": "批量翻译", "en": "Translate lines"},
    "wfNode_separate_audio": {"zh": "分离人声与背景音", "en": "Separate voice and background"},
    "wfField_model_ids": {"zh": "允许用的道具", "en": "Props that may be used"},
    "wfNode_scene_props": {"zh": "可用的 3D 道具", "en": "Available 3D props"},
    "wfNode_scene_props_desc": {
        "zh": "把这个工作区里的 3D 模型(通常是在 Blender 里建好再收进来的)列成一份清单交给布景师:每一份的 id、名字和实测的长宽高。接进设计布景那个节点的提示词,它就能把真实道具摆进白模,而不是只用基本体拼。留空 = 这个工作区里的全部模型。读不了的(压缩网格、面数超预算、文件不在)不进清单,并在清单里说明。",
        "en": "List this workspace's 3D models (usually modelled in Blender and brought back in) as a catalogue for the set designer: each one's id, name and measured width/height/depth. Feed it into the prompt of the node that designs the blockout and it can place real props instead of only primitives. Leave empty for every model in the workspace. Models that cannot be read (compressed mesh, over the triangle budget, missing file) are left out and noted in the catalogue.",
    },
    "wfNode_scene_props_model_ids": {
        "zh": "允许摆哪几份模型,留空表示全部",
        "en": "Which models may be placed; empty means all of them",
    },
    "wfOut_props_catalog": {"zh": "道具清单", "en": "Prop catalogue"},
    "wfOut_props_model_ids": {"zh": "可用道具 id", "en": "Usable prop ids"},
    "wfOut_props_count": {"zh": "可用道具数", "en": "Usable props"},
    "wfNode_scene_create": {"zh": "搭建 3D 白模场景", "en": "Build a 3D blockout scene"},
    "wfNode_scene_create_desc": {
        "zh": "把一份布景(物体、机位轨迹、镜头、打光)建成一个 3D 场景,出现在「3D 场景」列表里,可以打开在工作台里调整。布景通常接一个 AI 对话节点的结构化输出;坐标以米为单位,Y 朝上,地面在 y=0。",
        "en": "Turn a layout (objects, camera paths, shots, lighting) into a 3D scene. It appears in 3D Scenes and can be opened and adjusted in the workbench. The layout usually comes from a chat model's structured output; units are metres, Y is up, the floor is at y=0.",
    },
    "wfNode_scene_create_name": {"zh": "场景名,留空用工作流的名字", "en": "Scene name; leave empty to use the workflow's name"},
    "wfNode_scene_create_layout": {
        "zh": "布景 JSON:objects(物体与相机)、shots(镜头,各指向一台相机)、lighting(主光)。和 3D 场景的数据格式相同",
        "en": "Layout JSON: objects (including cameras), shots (each pointing at a camera), lighting. Same format as a 3D scene's content",
    },
    "wfNode_scene_render": {"zh": "渲染白模参考", "en": "Render blockout references"},
    "wfNode_scene_render_desc": {
        "zh": "从 3D 场景的某个镜头渲出白模首帧、尾帧和运镜视频,作为新素材交给图像/视频生成当参考;同时给出一句从机位轨迹算出来的镜头语言(焦段、机位高度、推拉摇移),可以直接拼进提示词。在本机渲染,不花钱;导入的 3D 模型也会画进去(读不了的在 skipped_models 里报数)。",
        "en": "Render the first frame, last frame and camera-move video of one shot in a 3D scene as new assets to use as references for image or video generation, plus a line of camera language computed from the camera path (lens, height, dolly/pan/orbit) that can go straight into a prompt. Rendered locally at no cost; imported 3D models are drawn too (any that could not be read are counted in skipped_models).",
    },
    "wfNode_scene_render_scene_id": {"zh": "要渲的 3D 场景,如 {{搭建白模.scene_id}}", "en": "The 3D scene to render, e.g. {{build_blockout.scene_id}}"},
    "wfNode_scene_render_shot_id": {"zh": "场景里哪个镜头(镜头 id)", "en": "Which shot in the scene (shot id)"},
    "wfNode_scene_render_render": {
        "zh": "只要静帧(首尾两张,约两秒)、只要运镜视频(逐帧渲,一个 5 秒镜头半分钟上下),或者都要",
        "en": "Stills only (first and last frame, about two seconds), the camera-move video only (rendered frame by frame, about half a minute for a 5-second shot), or both",
    },
    "wfNode_scene_render_project_id": {"zh": "渲出来的素材放进哪个项目", "en": "The project the rendered assets go into"},
    "wfNode_separate_audio_desc": {
        "zh": "把一份音频或视频拆成「人声」和「背景音」两份**新素材**,原素材一个字节不动。背景音是人声之外的全部:音乐、环境声、音效。译配时用它保住背景:人声那条丢掉、背景音留着,配音叠在上面。需要本机装好分离引擎。",
        "en": "Split an audio or video asset into a voice stem and a background stem as two **new assets**; the original is untouched. The background is everything except the voice: music, ambience, effects. Use it in dubbing to keep the background: drop the voice, keep the rest, lay the dub on top. Requires a separation engine installed on this machine.",
    },
    "wfNode_separate_audio_asset_id": {"zh": "要分离的素材(音频或视频都行)", "en": "The asset to separate (audio or video)"},
    "wfNode_separate_audio_engine": {"zh": "用哪个分离引擎。「自动」= 用本机现在装好的那个;引擎在「设置 → 本机引擎 → 人声分离」里装。", "en": "Which separation engine to use. Auto uses whichever is installed on this machine; install engines under Settings → On-device engines → Voice separation."},
    "sepEngine_demucs": {"zh": "Demucs(本机)", "en": "Demucs (local)"},
    "sepMsg_brokenRuntime": {
        # 解释器在、依赖却不全的那种(pip 装到一半断了)。不说"未安装" —— 用户明明记得装过。
        "zh": "运行环境不完整(依赖没装齐),点「安装」补上",
        "en": "The runtime is incomplete — some dependencies are missing. Click Install to repair it.",
    },
    "wfNode_denoise_audio": {"zh": "降噪", "en": "Reduce noise"},
    "wfNode_denoise_audio_desc": {
        "zh": "给一份音频或视频降噪,产出一份**新素材**(视频的画面原样保留,只换声音),原素材不动。内置引擎适合空调、风扇、电流声这类持续的底噪,音乐不受影响;以说话为主的素材选 deepfilternet 效果最好,但它会把音乐一起去掉。只想要人声、别的都不要,用「分离人声与背景音」取人声那一份。",
        "en": "Reduce noise in an audio or video asset and produce a **new asset** (a video keeps its picture; only the sound changes); the original is untouched. The built-in engine handles steady noise such as air conditioning, fans and hum, and leaves music alone; for speech-led material deepfilternet does best but removes music too. To keep only the voice and nothing else, use Separate voice and background and take the voice stem.",
    },
    "wfNode_denoise_audio_asset_id": {"zh": "要降噪的素材(音频或视频都行)", "en": "The asset to clean up (audio or video)"},
    "wfNode_denoise_audio_engine": {
        "zh": "用哪个降噪引擎。「自动」和「内置」是频谱降噪(不装任何东西,不动音乐,只去持续的底噪);DeepFilterNet 是效果最好的语音降噪(要先在设置里下载);RNNoise 是轻量语音降噪。后两种都会把音乐一起去掉。",
        "en": "Which engine to use. Auto and Built-in are the spectral denoiser (nothing to install, music untouched, steady noise only); DeepFilterNet is the best speech denoiser (download it in Settings first); RNNoise is a lightweight speech denoiser. The last two remove music as well.",
    },
    "wfNode_denoise_audio_strength": {
        "zh": "下手多重:「轻」只去最明显的底噪,「中」适合大多数录音,「重」去得最干净但可能让声音发闷。",
        "en": "How hard to go: Light removes only the obvious hiss, Medium suits most recordings, Strong is the cleanest but can dull the voice.",
    },
    "wfOut_denoised_asset_id": {"zh": "降噪后", "en": "Cleaned"},
    "wfOut_response_format_used": {"zh": "实际输出档位", "en": "Format actually used"},
    "wfOut_post_id": {"zh": "作品 ID", "en": "Post ID"},
    "wfOut_post_url": {"zh": "作品链接", "en": "Post link"},
    "wfOut_original_audio": {"zh": "原声实际处理方式", "en": "What happened to the original audio"},
    "wfOut_original_audio_note": {"zh": "原声处理说明", "en": "Original audio note"},
    "wfOut_graybox_first_frame": {"zh": "白模首帧", "en": "Blockout first frame"},
    "wfOut_graybox_last_frame": {"zh": "白模尾帧", "en": "Blockout last frame"},
    "wfOut_graybox_video": {"zh": "白模运镜视频", "en": "Blockout camera move"},
    "wfOut_camera_move": {"zh": "镜头语言", "en": "Camera language"},
    "wfOut_skipped_models": {"zh": "未渲染的导入模型", "en": "Imported models not rendered"},
    "wfOut_model_warnings": {"zh": "没渲进去的是哪几件、为什么", "en": "Which models were left out, and why"},
    "dubOriginalAudio_keep": {"zh": "原声保留原样。", "en": "The original audio was left as it was."},
    "dubOriginalAudio_duck": {"zh": "配音说话时原声被压低。", "en": "The original audio is lowered while the dub speaks."},
    "dubOriginalAudio_mute": {"zh": "原声整轨静音。", "en": "The original audio track is muted."},
    "dubOriginalAudio_separate": {"zh": "已拆出人声并去掉,背景音乐保留。", "en": "The original voice was separated out and removed; the background music is kept."},
    "dubOriginalAudio_mute_fallback": {
        "zh": "没有可用的人声分离引擎,原声整轨静音 —— 背景音乐也一起没了。在「设置 → 本机引擎 → 人声分离」装好后重跑,可以保住背景音乐。",
        "en": "No voice separation engine was available, so the whole original track was muted — the background music went with it. Install one under Settings → On-device engines → Voice separation and run again to keep the music.",
    },
    "denoiseEngine_ffmpeg": {"zh": "内置降噪", "en": "Built-in noise reduction"},
    "denoiseEngine_deepfilternet": {"zh": "DeepFilterNet 语音降噪", "en": "DeepFilterNet speech enhancement"},
    "denoiseEngine_rnnoise": {"zh": "RNNoise 语音降噪", "en": "RNNoise speech denoising"},
    "denoiseDesc_ffmpeg": {
        "zh": "去掉空调、风扇、电流声这类持续的底噪,音乐不受影响。一阵一阵的噪声(键盘、碗碟)基本去不掉。不用装任何东西。",
        "en": "Removes steady noise such as air conditioning, fans and hum, and leaves music alone. Intermittent noise (keyboards, dishes) mostly stays. Nothing to install.",
    },
    "denoiseDesc_deepfilternet": {
        "zh": "效果最好的语音降噪:持续的和一阵一阵的噪声都能去掉,说话声失真最小。音乐会被当成噪声去掉。需要先下载一次。",
        "en": "The best speech denoising here: removes both steady and intermittent noise with the least damage to the voice. Music is treated as noise. Needs a one-time download.",
    },
    "denoiseDesc_rnnoise": {
        "zh": "轻量的语音降噪模型,一阵一阵的噪声也能压下去,效果不如 DeepFilterNet。音乐会被当成噪声压低。不用装任何东西。",
        "en": "A lightweight speech model that also handles intermittent noise, though not as well as DeepFilterNet. Music is treated as noise. Nothing to install.",
    },
    "denoiseSetup_deepfilternet": {"zh": "先在「设置 → 本机引擎 → 降噪」里下载 DeepFilterNet", "en": "Download DeepFilterNet first under Settings → On-device engines → Noise reduction"},
    "denoiseSetup_rnnoise": {"zh": "这台机器上的 ffmpeg 不带 RNNoise 滤镜(arnndn)", "en": "This machine's ffmpeg was built without the RNNoise filter (arnndn)"},
    "dlMsg_downloading": {"zh": "下载中…", "en": "Downloading…"},
    "wfOut_vocals_asset_id": {"zh": "人声", "en": "Voice"},
    "wfOut_background_asset_id": {"zh": "背景音", "en": "Background"},
    "wfNode_translate_lines_desc": {
        "zh": "一次翻一整轨:并发发出、共用一条连接,顺序不变(第 i 条译文对第 i 段)。逐条循环也能做到,但那是一句一次请求,免费接口很容易因此限流。",
        "en": "Translate a whole track in one step: concurrent round-trips over one shared connection, order preserved (translation i matches segment i). A per-line loop does the same thing one request at a time, which easily trips the free endpoint's rate limit.",
    },
    "wfNode_translate_lines_texts": {
        "zh": "要翻译的一列文本。也可以直接给逐字稿的段落(每段带 text),节点会自己取出正文。",
        "en": "The list of texts to translate. A transcript's segments work too (each carrying `text`) — the node pulls the text out itself.",
    },
    "wfNode_translate_model": {
        "zh": "用这条连接上的哪个模型。留空 = 按这条连接的对话能力解析。",
        "en": "Which model on that connection to use. Empty resolves it from the connection's chat capability.",
    },
    "wfNode_translate_profile_id": {
        "zh": "引擎选 AI 时用哪条连接。留空 = 用第一条可用的 —— 你有好几条时,那多半不是你想要的那条。",
        "en": "Which connection to use when the engine is AI. Empty means the first available one \u2014 with several configured, that is rarely the one you meant.",
    },
    "wfNode_generate_subtitles": {"zh": "生成字幕", "en": "Generate subtitles"},
    "wfNode_generate_subtitles_desc": {"zh": "把逐字稿段落批量插成时间线上的字幕条;给了译文就用译文,可选同时保留原文两行。", "en": "Turn transcript segments into subtitle cues on the timeline; uses the translated lines when given, optionally keeping the original as a second line."},
    "wfNode_generate_subtitles_sequence_id": {"zh": "字幕落到哪条时间线", "en": "The timeline the subtitles go onto"},
    "wfNode_generate_subtitles_segments": {"zh": "逐字稿段落,如 {{转写.segments}} —— 时间码从这里来", "en": "Transcript segments, e.g. {{transcribe.segments}} — the timecodes come from here"},
    "wfNode_generate_subtitles_texts": {"zh": "逐条替换的文本(通常是译文),条数要和段落一致;留空就用原话", "en": "One replacement line per segment (usually the translation); the counts must match. Leave empty to keep the original wording"},
    "wfNode_generate_subtitles_keep_original": {"zh": "双语字幕:原文在上、译文在下", "en": "Bilingual cues: the original on top, the translation below"},
    "wfNode_generate_subtitles_start_field": {"zh": "每一段的起点在哪个字段,可以用点号取嵌套字段(如 append.timeline_start);默认 start", "en": "Which field holds each segment's start; dots reach nested fields (e.g. append.timeline_start). start by default"},
    "wfNode_generate_subtitles_end_field": {"zh": "每一段的终点在哪个字段;默认 end", "en": "Which field holds each segment's end. end by default"},
    "wfNode_generate_subtitles_text_field": {"zh": "每一段的文本在哪个字段;默认 text。起止或文本为空的段落会被跳过", "en": "Which field holds each segment's text. text by default. Segments with an empty start, end or text are skipped"},
    "wfNode_generate_subtitles_allow_empty": {"zh": "一条能用的段落都没有时怎么办:no = 报错(翻译配字幕时那说明上游出了问题);yes = 交出 0 条、流程继续", "en": "What to do when no segment is usable: no raises an error (when subtitling a translation that means something upstream went wrong); yes returns zero cues and the flow continues"},
    "wfNode_generate_subtitles_offset": {"zh": "素材在时间线上的起点,如 {{接入素材.timeline_start}};默认 0", "en": "Where the clip starts on the timeline, e.g. {{append.timeline_start}}; 0 by default"},
    "wfNode_generate_subtitles_track_id": {"zh": "落到哪条字幕轨,留空就用第一条(没有就新建)", "en": "Which subtitle track to use; empty means the first one, created if there is none"},
    "wfNode_dub_subtitles": {"zh": "字幕配音", "en": "Dub subtitles"},
    "wfNode_dub_subtitles_desc": {"zh": "把选中的字幕条逐条念出来,落到一条专门的配音轨 —— 原声和原素材一个字不动,不满意整条轨删掉就回到原样。", "en": "Speak the chosen subtitle cues onto a dedicated dub track — the original audio and clips are untouched, so deleting that one track undoes everything."},
    "wfNode_dub_subtitles_sequence_id": {"zh": "配音落到哪条时间线", "en": "The timeline the dub goes onto"},
    "wfNode_dub_subtitles_clip_ids": {"zh": "要配音的字幕条,如 {{生成字幕.clip_ids}}", "en": "The subtitle cues to dub, e.g. {{generate_subtitles.clip_ids}}"},
    "wfNode_dub_subtitles_match_duration": {"zh": "把配音快进/放慢到原段落的长度,好让它对得上画面", "en": "Speed each dubbed line up or down to fill the original segment, so it stays in sync with the picture"},
    "wfNode_dub_subtitles_line": {
        "zh": "双语字幕包含两行时，选择哪部分交给语音合成；单语字幕选择「完整字幕」即可。",
        "en": "Choose which part of a two-line bilingual cue is sent to speech synthesis. Use Full cue for single-line subtitles.",
    },
    "wfNode_dub_subtitles_original_audio": {
        "zh": "配音之后原声怎么办。「压低」在配音说话时把原声降到 30%,适合原声是环境音或音乐;译配时两边都是人声,压低只会变成两个人同时说话,用「静音」;「只去掉人声」要求本机已装好分离引擎,不可用时任务会明确失败而不会改成静音。都不删东西,随时能改回来。",
        "en": "What happens to the original audio once the dub lands. Lower turns it down to 30% while the dub speaks, which suits ambience or music; a translated dub replaces one voice with another, so lowering leaves two people talking at once — use Mute. Remove the voice requires a ready separation engine; the task fails explicitly instead of switching to mute when it is unavailable. Nothing is deleted, and it can be changed back at any time.",
    },
    "wfNode_loop_foreach": {"zh": "循环·遍历", "en": "Loop · for each"},
    "wfNode_loop_foreach_desc": {"zh": "对一个列表逐项运行内嵌子流程,汇总每次迭代的输出为列表。子流程内用 {{loop.item}} / {{loop.index}} 读取当前元素与序号,用 {{input.名}} 读取显式传入的外层值。", "en": "Run an embedded sub-flow once per item of a list and collect each iteration's output into a list. Inside it, {{loop.item}} / {{loop.index}} read the current item and index, while {{input.name}} reads explicitly passed outer values."},
    "wfNode_loop_foreach_items": {"zh": "如 {{split_1.results}};也接受多行文本,按行拆分", "en": "e.g. {{split_1.results}}; multi-line text is also accepted and split by line"},
    "wfNode_loop_foreach_inputs": {"zh": "传入循环体的共享值 {名: 值/引用};循环体内用 {{input.名}} 读取", "en": "Shared values passed into the loop body as {name: value/reference}; read them inside as {{input.name}}"},
    "wfNode_loop_foreach_body": {"zh": "循环体子流程(在节点内编辑;子流程节点用 {{loop.item}}/{{loop.index}})", "en": "The loop body sub-flow (edited inside the node; its nodes use {{loop.item}} / {{loop.index}})"},
    "wfNode_loop_foreach_output": {"zh": "每次迭代的输出,引用子流程节点输出(如 {{translate_1.text}});留空则输出整份子上下文", "en": "Each iteration's output, referencing a sub-flow node's output (e.g. {{translate_1.text}}); leave empty to output the whole sub-context"},
    "wfNode_loop_foreach_concurrency": {
        "zh": "同时跑几项(1–4)。1 = 一项跑完再跑下一项;各项互不依赖时(比如逐镜生成画面)调大能快不少。结果仍按原顺序排,任何一项失败都会停下。",
        "en": "How many items run at once (1–4). 1 runs them one after another; when items don't depend on each other (such as generating each shot) a higher value is much faster. Results keep their original order, and any failure stops the loop.",
    },
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
    "wfNode_asset_tag_mode": {"zh": "追加、移除,还是整组替换", "en": "Append, remove, or replace the whole set"},
    "wfNode_asset_update": {"zh": "素材整理", "en": "Organize assets"},
    "wfNode_asset_update_desc": {"zh": "重命名素材、或把素材归入某个项目。", "en": "Rename assets, or move them into a project."},
    "wfNode_asset_update_asset_ids": {"zh": "逗号分隔", "en": "Comma separated"},
    "wfNode_asset_update_name": {"zh": "新名称;多个素材时会自动加序号。留空则不改名", "en": "New name; a number is appended automatically when there are several assets. Leave empty to keep the names"},
    "wfNode_asset_update_project_id": {"zh": "归入的项目 id;留空则不改动归属", "en": "The project to move them into; leave empty to keep them where they are"},
    "wfNode_project_create": {"zh": "新建项目", "en": "Create project"},
    "wfNode_project_create_desc": {"zh": "在当前工作区建一个项目,输出它的 id —— 可接「素材整理」把素材归进去。", "en": "Create a project in this workspace and output its id — can feed “Organize assets” to file assets into it."},
    "wfNode_project_create_name": {"zh": "项目名", "en": "Project name"},
    "wfNode_project_sequence_create": {"zh": "新建成片项目", "en": "Create video project"},
    "wfNode_project_sequence_create_desc": {"zh": "一次建立项目、可编辑序列及默认音视频轨,输出序列和轨道 id,供自动编排与导出直接使用。", "en": "Create a project, editable sequence, and default video/audio tracks in one step, exposing their IDs for immediate automated assembly and export."},
    "wfNode_project_sequence_create_name": {"zh": "项目与序列名称", "en": "Project and sequence name"},
    "wfNode_project_sequence_create_width": {"zh": "画布宽度(默认 1920)", "en": "Canvas width (1920 by default)"},
    "wfNode_project_sequence_create_height": {"zh": "画布高度(默认 1080)", "en": "Canvas height (1080 by default)"},
    "wfNode_project_sequence_create_fps": {"zh": "帧率(默认 30)", "en": "Frame rate (30 by default)"},
    "wfNode_timeline_cut_ranges": {"zh": "按时间批量整理", "en": "Clean up time ranges"},
    "wfNode_timeline_cut_ranges_desc": {"zh": "一次删除同一片段的多个源时间范围,保留部分自动首尾相接。适合根据带时间码逐字稿清理停顿、口头禅、重复和错误重录。", "en": "Remove multiple source-time ranges from one clip in a single operation and ripple the kept pieces together. Designed for transcript-driven cleanup of pauses, fillers, repetition, and false starts."},
    "wfNode_timeline_cut_ranges_clip_id": {"zh": "要整理的原始片段 id", "en": "Original clip ID to clean up"},
    "wfNode_timeline_cut_ranges_ranges": {"zh": "范围数组:[{src_start,src_end,reason,...}];空数组保持原片不变", "en": "Range array: [{src_start, src_end, reason, ...}]; an empty array keeps the clip unchanged"},
    "wfNode_timeline_cut_ranges_min_confidence": {"zh": "只执行达到此置信度的范围(默认 0,取值 0–1)", "en": "Only apply ranges at or above this confidence (0 by default; 0–1)"},
    "wfNode_timeline_cut_ranges_max_removal_ratio": {"zh": "删除总时长不得超过原片比例(默认 1,取值 0–1)", "en": "Maximum share of the original clip that may be removed (1 by default; 0–1)"},
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
    "wfNode_browser_open_session_mode": {"zh": "临时(用完即清)、具名持久,还是复用浏览器池里已登录的档案", "en": "Throwaway, persistent by name, or a signed-in profile from the browser pool"},
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
    # ---- 工作流执行期的失败原因(WorkflowDomainError 的 key) ----
    "wfErr_cancelled": {"zh": "已取消", "en": "Cancelled"},
    "wfErr_assetNotInWorkspace": {"zh": "素材不在这个工作区里", "en": "That asset is not in this workspace"},
    "wfErr_sequenceNotInWorkspace": {"zh": "序列不在这个工作区里", "en": "That timeline is not in this workspace"},
    "wfErr_assetIdMissing": {"zh": "缺少 asset_id", "en": "asset_id is missing"},
    "wfErr_trackNotOnSequence": {"zh": "这条时间线上没有那条轨道", "en": "That track is not on this timeline"},
    "wfErr_revisionMissing": {"zh": "工作流执行绑定的修订快照不存在", "en": "The revision this run is bound to no longer exists"},
    "wfErr_startExists": {"zh": "已有开始节点,不能再添加 start 节点", "en": "There is already a start node"},
    "wfErr_connectDataNeedsPorts": {"zh": "connect_data 需要 source_output 和 target_input", "en": "connect_data needs source_output and target_input"},
    "wfErr_recursiveCall": {"zh": "工作流递归调用(直接或间接调用了自身),已阻止", "en": "Blocked: the workflow calls itself, directly or indirectly"},
    "wfErr_pickWorkflow": {"zh": "请选择要调用的工作流", "en": "Pick the workflow to call"},
    "wfErr_calledWorkflowMissing": {"zh": "被调用的工作流不存在", "en": "The workflow being called does not exist"},
    "wfErr_calledWorkflowHasNoOutput": {
        "zh": "被调用的工作流「{name}」没有「输出」节点 —— 加一个,并在里面声明要交给调用方的那几个值",
        "en": "The called workflow \u300c{name}\u300d has no Output node — add one and declare the values it hands back",
    },
    "wfErr_responseFormat": {"zh": "response_format 只能是 text/json_object/json_schema", "en": "response_format must be text, json_object or json_schema"},
    "wfErr_schemaEmpty": {"zh": "JSON Schema 不能为空", "en": "The JSON Schema cannot be empty"},
    "wfErr_llmPromptEmpty": {"zh": "LLM 节点的提示词为空:请填写提示词,或把「引用」的上游接好、确认其有输出。", "en": "The LLM node has no prompt: write one, or connect an upstream reference and make sure it produces output."},
    "wfErr_llmNotJson": {"zh": "LLM 未返回合法 JSON", "en": "The model did not return valid JSON"},
    "wfErr_browserSessionMissing": {"zh": "缺少浏览器会话:先用「打开浏览器」节点,并把它的 session 输出连过来", "en": "No browser session: add an Open browser node and connect its session output"},
    "wfErr_uploadNeedsSource": {"zh": "上传节点需要 asset_id 或 file_path", "en": "The upload node needs asset_id or file_path"},
    "wfErr_uploadAssetMissing": {"zh": "上传素材不存在", "en": "That asset does not exist"},
    "wfErr_uploadAssetNoFile": {"zh": "上传素材没有文件", "en": "That asset has no file"},
    "wfErr_pickPoolProfile": {"zh": "请选择浏览器池档案(session_mode=pool)", "en": "Pick a browser-pool profile (session_mode=pool)"},
    "wfErr_waitNeedsCondition": {"zh": "等待节点需要 selector / url_contains / text 之一", "en": "The wait node needs one of selector, url_contains or text"},
    "wfErr_loopItems": {"zh": "循环·遍历的 items 必须是列表(或多行文本)", "en": "For-each items must be a list (or multi-line text)"},
    "wfErr_concurrencyInteger": {"zh": "同时跑几项(concurrency)要是一个整数", "en": "Concurrency must be an integer"},
    "wfErr_notifyTitleEmpty": {"zh": "通知标题不能为空", "en": "The notification title cannot be empty"},
    "wfErr_tagNoAssets": {"zh": "素材打标签:没有可处理的素材 id", "en": "Tag assets: no asset ids to work on"},
    "wfErr_tagsEmpty": {"zh": "素材打标签:标签不能为空", "en": "Tag assets: the tags cannot be empty"},
    "wfErr_updateNoAssets": {"zh": "素材整理:没有可处理的素材 id", "en": "Update assets: no asset ids to work on"},
    "wfErr_updateNothingToDo": {"zh": "素材整理:至少要设置新名称或目标项目", "en": "Update assets: set a new name or a target project"},
    "wfErr_projectNameEmpty": {"zh": "新建项目:项目名不能为空", "en": "New project: the name cannot be empty"},
    "wfErr_sequenceProjectNameEmpty": {"zh": "新建成片项目:项目名不能为空", "en": "New video project: the name cannot be empty"},
    "wfErr_canvasSizeRange": {"zh": "新建成片项目:画布宽高必须在 16 到 16384 之间", "en": "New video project: width and height must be between 16 and 16384"},
    "wfErr_fpsRange": {"zh": "新建成片项目:帧率必须在 1 到 240 之间", "en": "New video project: the frame rate must be between 1 and 240"},
    "wfErr_targetProjectMissing": {"zh": "素材整理:目标项目不存在,或不属于当前工作区", "en": "Update assets: the target project does not exist in this workspace"},
    "wfErr_canvasNumbers": {"zh": "新建成片项目:宽、高和帧率必须是数字", "en": "New video project: width, height and frame rate must be numbers"},
    "wfErr_childMissing": {"zh": "子任务不存在", "en": "The sub-task no longer exists"},
    "wfErr_queryTooLong": {"zh": "检索词不能超过 300 字", "en": "The search text cannot exceed 300 characters"},
    "wfErr_noteBodyEmpty": {"zh": "笔记正文不能为空", "en": "The note body cannot be empty"},
    "wfErr_transcriptMissing": {"zh": "转写完成但没有找到文稿", "en": "Transcription finished but no transcript was found"},
    "wfErr_gifAssetNotInWorkspace": {"zh": "要转换的视频素材不在当前工作区", "en": "The video to convert is not in this workspace"},
    "wfErr_publishAccountMissing": {"zh": "发布账号不存在", "en": "That publishing account does not exist"},
    "wfErr_publishAssetMissing": {"zh": "发布素材不存在", "en": "The asset to publish does not exist"},
    "wfErr_operationsEmpty": {"zh": "operations 要是一个非空数组", "en": "operations must be a non-empty array"},
    "wfErr_inspectNeedsSequence": {"zh": "检视节点缺少 sequence_id", "en": "The inspect node needs a sequence_id"},
    "wfErr_sequenceIdMissing": {"zh": "缺少 sequence_id", "en": "sequence_id is missing"},
    "wfErr_trimRange": {"zh": "截取的结束时间要大于开始时间", "en": "The end time must be later than the start time"},
    "wfErr_cutNeedsClip": {"zh": "批量裁切缺少 clip_id", "en": "The batch cut is missing a clip_id"},
    "wfErr_clipNotOnSequence": {"zh": "要整理的片段不在这条时间线上", "en": "The clip to cut is not on this timeline"},
    "wfErr_ratioRange": {"zh": "最低置信度和最大删除比例必须在 0–1 之间", "en": "The confidence floor and the removal cap must be between 0 and 1"},
    "wfErr_rangesArray": {"zh": "裁切范围必须是数组", "en": "The cut ranges must be an array"},
    "wfErr_segmentsArray": {"zh": "segments 要是一个段落数组(如 {{转写.segments}})", "en": "segments must be an array of transcript segments (e.g. {{transcribe.segments}})"},
    "wfErr_textsArray": {"zh": "texts 要是一个字符串数组,或者一行一条的文本", "en": "texts must be an array of strings, or one line per entry"},
    "wfErr_subtitleTrackFailed": {"zh": "新建字幕轨失败", "en": "Could not create the subtitle track"},
    "wfErr_noSegments": {"zh": "没有可用来生成字幕的逐字稿段落", "en": "No transcript segments to build subtitles from"},
    "wfErr_noUsableSegments": {"zh": "这些段落里没有一条能生成字幕(文本为空或时长为 0)", "en": "None of these segments can become a subtitle (empty text, or zero length)"},
    "wfErr_noCuesToDub": {"zh": "没有要配音的字幕条", "en": "No subtitle cues to dub"},
    "wfErr_assetNodeEmpty": {"zh": "素材节点没有选素材", "en": "The asset node has no asset selected"},
    "wfErr_startNegative": {"zh": "落点不能是负数", "en": "The start point cannot be negative"},
    "wfErr_ratioNumbers": {"zh": "最低置信度和最大删除比例必须是 0–1 的数字", "en": "The confidence floor and the removal cap must be numbers between 0 and 1"},
    "wfErr_subtitlesOnSubtitleTrack": {"zh": "字幕只能放在字幕轨上", "en": "Subtitles can only go on a subtitle track"},
    "wfErr_offsetSeconds": {"zh": "offset 要是一个秒数", "en": "offset must be a number of seconds"},
    "wfErr_aiEditInvalidGraph": {"zh": "AI 没能产出一张合法的工作流:{reason}", "en": "The model did not produce a valid workflow: {reason}"},
    "wfErr_noExecutor": {"zh": "节点类型 {type} 没有执行器", "en": "No executor for node type {type}"},
    "wfErr_mustBeNumber": {"zh": "{field} 必须是数字", "en": "{field} must be a number"},
    "wfErr_belowMin": {"zh": "{field} 不能小于 {min}", "en": "{field} cannot be below {min}"},
    "wfErr_aboveMax": {"zh": "{field} 不能大于 {max}", "en": "{field} cannot be above {max}"},
    "wfErr_mustBeInteger": {"zh": "{field} 必须是整数", "en": "{field} must be a whole number"},
    "wfErr_schemaInvalid": {"zh": "JSON Schema 无效:{reason}", "en": "The JSON Schema is invalid: {reason}"},
    "wfErr_unknownTextOp": {"zh": "未知的文本处理方式:{op}", "en": "Unknown text operation: {op}"},
    "wfErr_unknownConditionOp": {"zh": "未知的比较方式:{op}", "en": "Unknown comparison: {op}"},
    "wfErr_conditionNeedsNumbers": {"zh": "比较方式「{op}」要的是数字,拿到的是 {left} / {right}", "en": "The “{op}” comparison needs numbers; got {left} / {right}"},
    "wfErr_childFailed": {"zh": "子任务失败:{reason}", "en": "The sub-task failed: {reason}"},
    "wfErr_pluginToolFailed": {"zh": "插件工具失败:{reason}", "en": "The plugin tool failed: {reason}"},
    "wfErr_pluginToolInternal": {
        "zh": "工具 {tool} 只供 Mosael 内部使用,不能在工作流里调用",
        "en": "The tool {tool} is reserved for Mosael itself and cannot run in a workflow",
    },
    "wfErr_pluginInstanceGone": {"zh": "节点选的连接已不可用(插件 {package});请在节点上重新选一个", "en": "The connection this node picked is gone (plugin {package}); choose another on the node"},
    "wfErr_pluginNoInstance": {"zh": "没有可用的「{package}」连接:请在插件页新建并启用一个", "en": "No usable “{package}” connection: create and enable one on the Plugins page"},
    "wfErr_pluginManyInstances": {"zh": "有多个「{package}」连接({names}),请在节点上选一个", "en": "Several “{package}” connections exist ({names}); pick one on the node"},
    "wfErr_tagUnknownMode": {"zh": "素材打标签:未知的模式 {mode}", "en": "Tag assets: unknown mode {mode}"},
    "wfErr_pluginNodeType": {"zh": "插件节点类型不合法:{type}", "en": "Invalid plugin node type: {type}"},
    "wfErr_integerRange": {"zh": "{field}必须是 {min} 到 {max} 之间的整数", "en": "{field} must be a whole number between {min} and {max}"},
    "wfErr_loopTooMany": {"zh": "循环·遍历拿到 {count} 项,超过上限 {cap};请先筛选或分批", "en": "The for-each got {count} items, over the {cap} cap; filter or split them first"},
    "wfErr_loopIterationsFailed": {
        # 几项一起失败时**全部**说出来:只报第一项,用户会以为其余的都好 —— 而每一项都可能是一笔花出去的钱。
        "zh": "{total} 次迭代里第 {which} 次失败,另有 {skipped} 次因此没有开始。第一个原因:{reason}",
        "en": "Iterations {which} of {total} failed, and {skipped} more were not started because of it. First reason: {reason}",
    },
    "wfErr_loopIterationFailed": {"zh": "{where}失败:{reason}", "en": "{where} failed: {reason}"},
    "wfErr_sceneLayoutMissing": {"zh": "没有给布景", "en": "No layout was given"},
    "wfErr_sceneLayoutInvalid": {"zh": "布景不是一个有效的 3D 场景:{reason}", "en": "The layout is not a valid 3D scene: {reason}"},
    "wfErr_sceneNotInWorkspace": {"zh": "这个 3D 场景不存在,或不属于当前工作区", "en": "This 3D scene does not exist or is not in this workspace"},
    "wfErr_sceneRenderFailed": {"zh": "白模渲染失败:{reason}", "en": "Blockout render failed: {reason}"},
    "wfErr_linesSegmentsMismatch": {"zh": "译文有 {lines} 条,逐字稿有 {segments} 段,对不上", "en": "{lines} translated lines against {segments} transcript segments — they do not line up"},
    "wfErr_speechParams": {"zh": "{what}{reason}", "en": "{what}: {reason}"},
    "wfErr_noSuchTrackKind": {"zh": "这条时间线上没有 {kind} 轨道,先加一条", "en": "This timeline has no {kind} track; add one first"},
    "wfErr_operationsNotJson": {"zh": "operations 不是合法 JSON:{reason}", "en": "operations is not valid JSON: {reason}"},
    "wfErr_rangesNotJson": {"zh": "裁切范围不是合法 JSON:{reason}", "en": "The cut ranges are not valid JSON: {reason}"},
    "wfErr_segmentsNotJson": {"zh": "segments 不是合法 JSON:{reason}", "en": "segments is not valid JSON: {reason}"},
    "wfErr_segmentTimecode": {"zh": "第 {index} 段的时间码不是数字", "en": "Segment {index} has a non-numeric timecode"},
    "wfErr_nestTooDeep": {"zh": "工作流嵌套过深(超过 {max} 层),已阻止", "en": "Blocked: workflows nested deeper than {max}"},
    "wfErr_nodeMissing": {"zh": "节点不存在:{id}", "en": "No such node: {id}"},
    "wfErr_unknownNodeType": {"zh": "未知的节点类型:{type}", "en": "Unknown node type: {type}"},
    "wfErr_nodeIdExists": {"zh": "节点 id 已存在:{id}", "en": "A node with id {id} already exists"},
    "wfErr_unknownGraphOp": {"zh": "不支持的图操作:{kind}", "en": "Unsupported graph operation: {kind}"},
    "wfErr_unknownTemplate": {"zh": "未知的内置工作流模板:{id}", "en": "Unknown built-in workflow template: {id}"},
    "wfErr_cleanupTooMuch": {"zh": "整理方案准备删除 {seconds} 秒,超过允许的 {ratio};请收紧整理尺度或检查方案", "en": "The cleanup plan would remove {seconds}s, over the {ratio} cap; tighten the thresholds or review the plan"},
    "wfErr_jsonSchemaMismatch": {"zh": "模型返回的 JSON 不符合 Schema:{reason}", "en": "The model's JSON does not match the schema: {reason}"},
    # ---- 工作流节点的下拉选项(wfOpt_<字段>_<值>;wfOpt__<值> 是各字段通用的是/否) ----
    "wfOpt__true": {"zh": "是", "en": "Yes"},
    "wfOpt__false": {"zh": "否", "en": "No"},
    "wfOpt__yes": {"zh": "是", "en": "Yes"},
    "wfOpt__no": {"zh": "否", "en": "No"},
    "wfOpt_engine_auto": {"zh": "自动", "en": "Auto"},
    "wfOpt_engine_funasr": {"zh": "FunASR", "en": "FunASR"},
    "wfOpt_engine_whisperx": {"zh": "WhisperX", "en": "WhisperX"},
    "wfOpt_engine_google": {"zh": "Google 翻译", "en": "Google Translate"},
    "wfOpt_engine_ai": {"zh": "AI 模型", "en": "AI model"},
    "wfOpt_engine_demucs": {"zh": "Demucs", "en": "Demucs"},
    "wfOpt_engine_ffmpeg": {"zh": "内置(频谱降噪)", "en": "Built-in (spectral)"},
    "wfOpt_engine_deepfilternet": {"zh": "DeepFilterNet", "en": "DeepFilterNet"},
    "wfOpt_engine_rnnoise": {"zh": "RNNoise", "en": "RNNoise"},
    "wfOpt_kind_all": {"zh": "全部", "en": "All"},
    "wfOpt_kind_video": {"zh": "视频", "en": "Video"},
    "wfOpt_kind_image": {"zh": "图片", "en": "Image"},
    "wfOpt_kind_audio": {"zh": "音频", "en": "Audio"},
    "wfOpt_kind_subtitle": {"zh": "字幕", "en": "Subtitles"},
    "wfOpt_line_all": {"zh": "完整字幕（含两行）", "en": "Full cue (both lines)"},
    "wfOpt_line_first": {"zh": "第一行", "en": "First line"},
    "wfOpt_line_last": {"zh": "第二行", "en": "Second line"},
    "wfOpt_mode_add": {"zh": "追加", "en": "Append"},
    "wfOpt_mode_remove": {"zh": "移除", "en": "Remove"},
    "wfOpt_mode_replace": {"zh": "整组替换", "en": "Replace all"},
    "wfOpt_op_equals": {"zh": "等于", "en": "Equals"},
    "wfOpt_op_not_equals": {"zh": "不等于", "en": "Does not equal"},
    "wfOpt_op_contains": {"zh": "包含", "en": "Contains"},
    "wfOpt_op_not_contains": {"zh": "不包含", "en": "Does not contain"},
    "wfOpt_op_empty": {"zh": "为空", "en": "Is empty"},
    "wfOpt_op_not_empty": {"zh": "不为空", "en": "Is not empty"},
    "wfOpt_op_gt": {"zh": "大于", "en": "Greater than"},
    "wfOpt_op_lt": {"zh": "小于", "en": "Less than"},
    "wfOpt_op_trim": {"zh": "去掉首尾空白", "en": "Trim"},
    "wfOpt_op_upper": {"zh": "转大写", "en": "Uppercase"},
    "wfOpt_op_lower": {"zh": "转小写", "en": "Lowercase"},
    "wfOpt_op_replace": {"zh": "替换", "en": "Replace"},
    "wfOpt_op_regex_extract": {"zh": "正则提取", "en": "Extract with regex"},
    "wfOpt_op_length": {"zh": "取长度", "en": "Length"},
    "wfOpt_source_group_all": {"zh": "全部", "en": "All"},
    "wfOpt_source_group_keyframes": {"zh": "首尾帧", "en": "First/last frames"},
    "wfOpt_source_group_references": {"zh": "参考素材", "en": "References"},
    "wfOpt_render_stills": {"zh": "首尾静帧", "en": "First and last frame"},
    "wfOpt_render_video": {"zh": "运镜视频", "en": "Camera-move video"},
    "wfOpt_render_both": {"zh": "静帧和运镜视频", "en": "Stills and video"},
    "wfOpt_original_audio_duck": {"zh": "配音说话时压低", "en": "Lower while the dub speaks"},
    "wfOpt_original_audio_mute": {"zh": "静音", "en": "Mute"},
    "wfOpt_original_audio_keep": {"zh": "保持原样", "en": "Leave as is"},
    "wfOpt_original_audio_separate": {"zh": "只去掉人声", "en": "Remove the voice"},
    "wfOpt_preset_precise": {"zh": "严谨", "en": "Precise"},
    "wfOpt_preset_balanced": {"zh": "平衡", "en": "Balanced"},
    "wfOpt_preset_creative": {"zh": "发散", "en": "Creative"},
    "wfOpt_response_format_text": {"zh": "纯文本", "en": "Text"},
    "wfOpt_response_format_json_object": {"zh": "JSON 对象", "en": "JSON object"},
    "wfOpt_response_format_json_schema": {"zh": "按 JSON Schema", "en": "JSON Schema"},
    "wfOpt_session_mode_ephemeral": {"zh": "临时", "en": "Throwaway"},
    "wfOpt_session_mode_named": {"zh": "具名持久", "en": "Named, persistent"},
    "wfOpt_session_mode_pool": {"zh": "浏览器池档案", "en": "Browser-pool profile"},
    "wfOpt_strength_light": {"zh": "轻", "en": "Light"},
    "wfOpt_strength_medium": {"zh": "中", "en": "Medium"},
    "wfOpt_strength_strong": {"zh": "重", "en": "Strong"},
    "wfOpt_target_lang_en": {"zh": "英语", "en": "English"},
    "wfOpt_target_lang_zh-CN": {"zh": "简体中文", "en": "Simplified Chinese"},
    "wfOpt_target_lang_zh-TW": {"zh": "繁体中文", "en": "Traditional Chinese"},
    "wfOpt_target_lang_ja": {"zh": "日语", "en": "Japanese"},
    "wfOpt_target_lang_ko": {"zh": "韩语", "en": "Korean"},
    "wfOpt_target_lang_fr": {"zh": "法语", "en": "French"},
    "wfOpt_target_lang_de": {"zh": "德语", "en": "German"},
    "wfOpt_target_lang_es": {"zh": "西班牙语", "en": "Spanish"},
    "wfOpt_target_lang_ru": {"zh": "俄语", "en": "Russian"},
    # ---- 任务种类(app/domain/job_catalog.py) ----
    "jobKind_workflow": {"zh": "工作流", "en": "Workflow"},
    "jobKind_publish": {"zh": "发布", "en": "Publish"},
    "jobKind_render": {"zh": "导出", "en": "Export"},
    "jobKind_transcribe": {"zh": "转写", "en": "Transcribe"},
    "jobKind_subtitle_dub": {"zh": "字幕配音", "en": "Subtitle dub"},
    "jobKind_ai_generation": {"zh": "AI 生成", "en": "AI generation"},
    "jobKind_tts": {"zh": "语音合成", "en": "Speech"},
    "jobKind_podcast": {"zh": "播客", "en": "Podcast"},
    "jobKind_url_import": {"zh": "链接导入", "en": "URL import"},
    "jobKind_video_to_gif": {"zh": "视频转 GIF", "en": "Video to GIF"},
    "jobKind_denoise_audio": {"zh": "降噪", "en": "Noise reduction"},
    "jobKind_separate_audio": {"zh": "人声分离", "en": "Voice separation"},
    "jobKind_trim": {"zh": "截取", "en": "Trim"},
    "jobKind_proxy": {"zh": "预览代理", "en": "Preview proxy"},
    "jobKind_other": {"zh": "任务", "en": "Task"},
    "jobMsg_trimQueued": {"zh": "截取排队中", "en": "Trim queued"},
    "jobMsg_trimRunning": {"zh": "正在截取", "en": "Trimming"},
    "jobMsg_trimDone": {"zh": "截取完成", "en": "Trimmed"},
    "jobMsg_separateQueued": {"zh": "人声与背景音分离排队中", "en": "Voice/background separation queued"},
    "jobMsg_separateRunning": {"zh": "正在分离人声与背景音(本机跑模型,长素材会很慢)", "en": "Separating voice and background (local model; long assets take a while)"},
    "jobMsg_separateDone": {"zh": "分离完成,人声与背景音已加入素材库", "en": "Separated; the voice and background stems are in the media library"},
    "jobMsg_denoiseQueued": {"zh": "降噪排队中", "en": "Noise reduction queued"},
    "jobMsg_denoiseRunning": {"zh": "正在降噪", "en": "Reducing noise"},
    "jobMsg_denoiseDone": {"zh": "降噪完成,新素材已加入素材库", "en": "Noise reduced; the cleaned asset is in the media library"},
    "jobMsg_videoGifQueued": {"zh": "视频转 GIF 排队中", "en": "Video-to-GIF queued"},
    "jobMsg_videoGifRunning": {"zh": "正在将视频转换为 GIF", "en": "Converting video to GIF"},
    "jobMsg_videoGifDone": {"zh": "GIF 已生成", "en": "GIF created"},
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
    #: 免费端点没有稳定配额承诺，可能按客户端标识、出口或突发频率拒绝。说清下一条路，不把
    #: 原因武断归到 IP —— 2026-09 的真实故障就是旧 client=gtx 被统一 429，换出口也无效。
    "translateErr_googleRateLimited": {
        "zh": "Google 免费翻译接口拒绝了请求(429)。这个非官方端点可能限制客户端标识、出口或突发频率。稍后再试，或者把翻译节点的引擎换成「AI 翻译」；AI 翻译走你自己的供应商。",
        "en": "Google's unofficial free translate endpoint refused the request (429). It may limit client identities, network exits, or request bursts. Try again later, or switch the translate node's engine to \u300cAI\u300d to use your own provider.",
    },
    "translateErr_googleHttp": {
        "zh": "Google 免费翻译接口返回 {status}。稍后再试,或者把翻译节点的引擎换成「AI 翻译」。",
        "en": "Google's free translate endpoint returned {status}. Try again later, or switch the translate node's engine to \u300cAI\u300d.",
    },
    "translateErr_googleUnreachable": {
        "zh": "连不上 Google 免费翻译接口:{reason}。它在部分网络下不可达 —— 可以配置出站代理,或者把翻译节点的引擎换成「AI 翻译」。",
        "en": "Could not reach Google's free translate endpoint: {reason}. It is unreachable on some networks \u2014 configure an outbound proxy, or switch the translate node's engine to \u300cAI\u300d.",
    },
    # ---- i18n 分区 B3(画板、智能体、生成、配音等领域):这一批新加的 key 放在这行下面 ----
}


#: 本次请求的语言。由中间件按 Accept-Language 设定(见 app/main.py)。
#:
#: **为什么要有它**:任务消息由 12 个接口返回,若在每个路由里各取一次请求头再翻,就是同一个问题
#: 十二个答案 —— 漏一个,那一屏的任务就还是另一种语言。序列化那一层拿不到 Request,ContextVar 是
#: 让它知道"这一次是谁在问"的唯一办法。
#: 没有请求上下文时(飞书机器人、定时任务、后台线程)取缺省 —— 那正是它该给的答案。
_current_locale: ContextVar[str] = ContextVar("mosael_locale", default=DEFAULT_LOCALE)


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


def _drop_placeholders(text: str) -> str:
    """把填不上的占位符连同它的标点一起抹掉,只留字面部分。

    退路不能是「原样返回模板」:那样用户脸上就糊着一个 `{name}`。而这条路真正会被走到的
    是**旧任务记录** —— message_params 这一列是后加的,它之前落库的那些行参数是空的,
    而接口按 key 重翻。给一个 key 补上占位符(「工作流失败」→「工作流失败: {name}」)时,
    历史行就都走这里:抹掉之后它们回到补占位符之前的样子,正是当初存进去的那句。
    """
    from string import Formatter

    literals = [literal for literal, field, _, _ in Formatter().parse(text) if literal]
    # 占位符没了,它前面那个引导标点也就没有要引导的东西了。
    return "".join(literals).strip().rstrip(":：,，、-—").strip()


def is_message_key(text: str) -> bool:
    """这是**我们自己的一条文案 key**,还是一句现成的话?

    任务消息(`jobs.say`)和工作流错误(`WorkflowDomainError`)都接受"key 或一句话"——两者共用
    一个参数,于是必须有**一个**地方判断到底是哪一种,而不是各处各猜。判据只有一条:在不在
    MESSAGES 里。认不出的就是字面量:原样显示,**不当模板填**,也**不当 key 落库**。

    这一条是付过账才收进来的:第三方报错原文(LLM 返回的 403 JSON)被当成 key 截成 80 字存进
    `error_key`,读的时候又拿它当模板去 format —— 花括号一炸,整个执行历史接口 500,
    而面板上什么都不说,看起来就是"一次运行都没有"。
    """
    return text in MESSAGES


def _text(key: str, locale: str) -> str:
    """这条 key 在这个语言下的原文。**查不到就原样返回 key**,不抛错:一条文案缺翻译不该让整个
    接口 500。它会以 key 的样子出现在界面上——难看,但看得见,而棘轮保证它进不了主干。"""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(locale) or entry.get(DEFAULT_LOCALE) or key


def pick_text(value: Any, locale: str | None = None, *, author_locale: str = "") -> str:
    """一段**贴着数据写的**多语言文字:`{"zh": "…", "en": "…"}`,也可以就是一个字符串。

    和 `t()` 是两件事,不该混:`t` 翻的是**我们自己**的文案(key 在 MESSAGES 里,棘轮盯着两种
    语言都得有);这里挑的是**数据自带**的文案 —— 插件清单里作者写的、内置模板里节点的名字。
    那些东西没有全局 key 可言,翻译就写在它旁边("翻译贴着它翻译的那个东西写")。

    挑哪一条:要的那种语言 → 同一主语言的任意变体(`en-US` 认 `en`)→ 作者声明的原文语言 →
    部署缺省 → 写在最前面的那一条。**退路是给原文,不是给空**。
    """
    if not isinstance(value, dict):
        return str(value or "")
    want = locale or get_current_locale()
    by_primary: dict[str, str] = {}
    for key, picked in value.items():
        if not isinstance(picked, str) or not picked.strip():
            continue
        by_primary.setdefault(_primary_tag(str(key)), picked)
        if str(key).strip().lower() == str(want).strip().lower():
            return picked
    for candidate in (want, author_locale, DEFAULT_LOCALE):
        picked = by_primary.get(_primary_tag(str(candidate))) if candidate else None
        if picked:
            return picked
    return next(iter(by_primary.values()), "")


def _primary_tag(tag: str) -> str:
    """`zh-CN` / `zh_Hans` → `zh`。整串相等的话,一份写成 `en-US` 的翻译就白写了。"""
    return tag.replace("_", "-").split("-")[0].strip().lower()


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """翻一个 key,可带参数。

    带参数的句子(「安装 {engine} 运行依赖…」)是模板 —— **参数在产生它的地方就算好、跟着 key 一起
    传出来**,而不是把值直接拼进句子。拼进去就没法翻了:那句话从此只有一种语言。

    **没传参数就原样返回,不跑 format。** 界面文案里的花括号是**给人照抄的写法**,不是待填的槽:
    节点提示里的 `{{转写.segments}}` 正是用户要往输入框里敲的那串字,而 format 会把它吃掉一层
    花括号,照抄下去不生效;`{名: 值}` 这种示例更惨——它会被当成一个填不上的槽整段抹掉
    (「{名: 引用},如 …」曾经在界面上只剩下一个",如")。
    任务消息那条路要的正相反(槽填不上就该消失),走 render_message。
    """
    text = _text(key, locale)
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def fragment(key: str, **params: Any) -> Any:
    """摘要里被拼进去的**那半句**,留成 key 而不是当场翻成字。

    确认卡的措辞是拼出来的(「给 *12 条字幕* 配音 *,并变速压回原段落长度*」),而拼进去的
    每一段自己也是文案。当场翻的话,外层就算存了 key,内层还是冻成了写它那天的语言。

    返回的是一个带 `__key` 的小字典,`render_nested` 渲染时递归展开 —— 它落进
    `summary_params`(JSON 列),所以形状必须是能 JSON 化的。
    """
    return {"__key": key, "params": params} if key else ""


def render_nested(key: str, params: Any, locale: str = DEFAULT_LOCALE) -> str:
    """渲染一条**可以嵌套**的文案:参数里带 `__key` 的那些先各自渲染,再填进外层。"""

    def resolve(value: Any) -> Any:
        if isinstance(value, dict) and "__key" in value:
            return render_nested(str(value["__key"]), value.get("params") or {}, locale)
        if isinstance(value, list):
            # **连接号也随语言变**:中文用顿号,英文用逗号加空格。先翻每一段,再按读的人的
            # 习惯连起来 —— 反过来(先连再翻)得到的是一串翻不动的拼接物。
            return _text("punct_listSep", locale).join(str(resolve(one)) for one in value)
        return value

    resolved = {name: resolve(value) for name, value in (params or {}).items()}
    return render_message(key, locale, resolved)


def render_message(key: str, locale: str = DEFAULT_LOCALE, params: dict[str, Any] | None = None) -> str:
    """渲染一条**任务消息**:占位符必须被填掉,填不上就连同标点一起抹掉(见 _drop_placeholders)。

    和 t() 分家,是因为两类文案对花括号的期待正相反:任务消息里的 `{name}` 是待填的槽,没有参数
    就该消失;而界面文案里的花括号是要给人看的写法,碰都不该碰。此前两者共用一条路,于是给任务
    消息补占位符的那次改动,顺手把三条节点提示打成了残句。
    """
    #: 认不出的 key 是一句现成的话,不是模板 —— 它里面的花括号是内容(JSON、代码),不是槽。
    #: 拿它去 format,要么抛错、要么把 `{"error": …}` 当占位符抹掉(见 is_message_key)。
    if not is_message_key(key):
        return key
    text = _text(key, locale)
    try:
        return text.format(**(params or {}))
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def tr(key: str, **params: object) -> str:
    """按**这次请求**的语言翻一个 key(语言由中间件放进 ContextVar,见 app/api/middleware)。

    路由里直接写的报错(`HTTPException(detail=…)`)用它;领域错误用 LocalizedError。
    """
    return t(key, get_current_locale(), **params)


class LocalizedError(Exception):
    """带文案 key 的错误:领域里只说「是哪一种」和参数,**不拼句子**;变成文字时按当时的语言翻。

    `str(exc)` 取的是 ContextVar 里的语言 —— 在请求里就是请求方的语言,在后台线程里是缺省语言。
    所以各领域那些「`{"detail": str(exc)}`」的出口不用改,换成它就自动跟着界面语言走。

    此前 Blender、插件等领域的报错是写死的中文句子:英文界面里弹出来的是中文,中间还夹着上游
    原样透传的英文(「Blender 未完成同步:Error executing code: Could not connect to Blender…」)。
    上游给的原文作为参数(通常叫 `detail`)放进翻好的句子里,不在领域里拼接。
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return t(self.key, get_current_locale(), **self.params)


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
            # message 是任务消息,填不上的槽要抹掉;其余字段是界面文案,原样翻。
            k: (render_message(payload[k], locale, params) if k == "message" else t(payload[k], locale))
            for k in keys
            if isinstance(payload.get(k), str)
        },
    }
    out.pop(PARAMS_FIELD, None)
    return out

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

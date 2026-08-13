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
    # ---- 转写模型目录 ----
    "asrLabel_funasrZh": {"zh": "FunASR 中文套件", "en": "FunASR Chinese bundle"},
    "asrDetail_funasrZh": {
        "zh": "Paraformer 识别 + VAD 断句 + 标点 + 说话人分离,中文转写默认引擎",
        "en": "Paraformer ASR + VAD segmentation + punctuation + speaker diarisation — the default engine for Chinese.",
    },
    "asrDetail_whisperSmall": {"zh": "多语种,速度与精度均衡(默认)", "en": "Multilingual; balanced speed and accuracy (default)"},
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
}


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


def t(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """翻一个 key。

    **查不到就原样返回 key**,不抛错:一条文案缺翻译不该让整个接口 500。它会以 key 的样子出现在
    界面上——难看,但看得见,而棘轮保证它进不了主干。
    """
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(locale) or entry.get(DEFAULT_LOCALE) or key


def translate_fields(payload: dict[str, Any], keys: tuple[str, ...], locale: str) -> dict[str, Any]:
    """把一个字典里指定的几个字段就地翻掉(返回新字典,不改原数据)。"""
    return {**payload, **{k: t(payload[k], locale) for k in keys if isinstance(payload.get(k), str)}}

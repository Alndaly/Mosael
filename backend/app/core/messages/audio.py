"""后端文案 · 配音、转写、降噪、分离、分析(分区 B3)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # -- B3·配音、转写、降噪、分离、分析 --
    # 配音 / 声音克隆(domain/voices/voices.py、engine_catalog.py、agent_voice.py)
    "voiceErr_ffmpegNoReason": {"zh": "ffmpeg 没有说明原因", "en": "ffmpeg gave no reason"},
    "voiceErr_referenceTooShort": {
        "zh": "参考音频太短(只有 {actual} 秒)。零样本克隆要听够才能学到音色,请给 {min}–{max} 秒连续清晰的人声 —— 太短的话合成出来会是一段听不懂的声音。",
        "en": "The reference audio is too short (only {actual} s). Zero-shot cloning needs enough speech to learn the voice — give it {min}–{max} seconds of continuous, clear speech, or the result will be unintelligible.",
    },
    "voiceErr_referenceTextRequired": {
        "zh": "这个音色没有填参考文本,而 {label} 不会自己识别 —— 它需要知道那段参考音频说的是什么,才能学到音色;没有的话合成出来会是一段听不懂的声音。在音色库里重建这个音色时把参考文本填上,或者改用 F5-TTS(它会自己转写参考音频)。",
        "en": "This voice has no reference text, and {label} can't work it out on its own — it needs to know what the reference audio says to learn the voice, or the result will be unintelligible. Add the reference text to this voice in the voice library, or switch to F5-TTS (it transcribes the reference audio itself).",
    },
    "voiceErr_noRuntime": {
        "zh": "{label} 还没有运行环境:没有任何 Python 解释器装了它。部署管理员在「管理 → 引擎 → 声音克隆」里点「下载」,装一次就好;想马上出声可以先在上面的引擎里选「Edge 免费在线合成」,它不需要安装。",
        "en": "{label} has no runtime yet: no Python interpreter has it installed. A deployment admin clicks Download under Admin → Engines → Voice cloning — it only needs installing once. To get audio right away, pick the free Edge online engine above; it needs no install.",
    },
    "voiceErr_noWeights": {
        "zh": "{label} 的模型权重还没下好,现在合成不出声音。部署管理员在「管理 → 引擎 → 声音克隆」里点「下载」补上 —— 这里不会自动下:那是几个 GB 的事,该由管理员决定什么时候开始。",
        "en": "{label}'s model weights aren't downloaded yet, so it can't synthesise anything. A deployment admin clicks Download under Admin → Engines → Voice cloning — it won't start on its own here, since it's several GB and the admin decides when.",
    },
    "voiceErr_unknownEngine": {"zh": "不认识的本地引擎:{engine}", "en": "Unknown local engine: {engine}"},
    "voiceErr_synthNoReason": {
        "zh": "语音合成失败,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。",
        "en": "Speech synthesis failed and the worker process left no reason. Try once more; if it keeps happening, please report it.",
    },
    "voiceErr_synthTorchcodec": {
        "zh": "语音合成失败:音频解码库(torchcodec)加载不了:它需要一份版本对得上的 FFmpeg。升级引擎依赖通常就能解决(管理 → 引擎 →「声音克隆」→ 下载,需要部署管理员);若仍然如此,装一个 Homebrew 的 ffmpeg 即可,系统那份不会被改动。",
        "en": "Speech synthesis failed: the audio decoding library (torchcodec) couldn't load — it needs a matching FFmpeg version. Upgrading the engine's dependencies usually fixes it (Admin → Engines → Voice cloning → Download, deployment admins only); if not, install ffmpeg from Homebrew — the system copy is left untouched.",
    },
    "voiceErr_synthMissingModule": {
        "zh": "语音合成失败:{detail} —— 引擎的运行环境不完整。部署管理员在「管理 → 引擎 → 声音克隆」里点「下载」,它会把缺的依赖补上。",
        "en": "Speech synthesis failed: {detail} — the engine's runtime is incomplete. A deployment admin clicks Download under Admin → Engines → Voice cloning to add the missing dependencies.",
    },
    "voiceErr_synthFailed": {"zh": "语音合成失败:{detail}", "en": "Speech synthesis failed: {detail}"},
    "voiceErr_synthNoAudio": {
        "zh": "语音合成失败:worker 报成功却没有产出音频",
        "en": "Speech synthesis failed: the worker reported success but produced no audio.",
    },
    "voiceErr_jaCloneNeedsWeights": {
        "zh": "这段文本是日文,而本地克隆现在装的权重念不了它。部署管理员在「管理 → 引擎 → 声音克隆」下载日文模型(约 {size} GB)后就能用你自己的音色念;不想等的话,改用 Edge TTS 的日文音色或 OpenAI TTS。",
        "en": "This text is Japanese, and the local cloning weights installed now can't read it. Once a deployment admin downloads the Japanese model (about {size} GB) under Admin → Engines → Voice cloning, it reads in your own voice — or, to skip the wait, use a Japanese Edge TTS voice or OpenAI TTS.",
    },
    "voiceErr_koCloneNeedsWeights": {
        "zh": "这段文本是韩文,而本地克隆现在装的权重念不了它。部署管理员在「管理 → 引擎 → 声音克隆」下载韩文模型(约 {size} GB)后就能用你自己的音色念;不想等的话,改用 Edge TTS 的韩文音色或 OpenAI TTS。",
        "en": "This text is Korean, and the local cloning weights installed now can't read it. Once a deployment admin downloads the Korean model (about {size} GB) under Admin → Engines → Voice cloning, it reads in your own voice — or, to skip the wait, use a Korean Edge TTS voice or OpenAI TTS.",
    },
    "voiceErr_jaCloneUnsupported": {
        "zh": "这段文本是日文,而本地音色克隆没有能念它的模型 —— 它不会报错,只会念出一段听不懂的声音。改用 Edge TTS 的日文音色,或 OpenAI TTS。",
        "en": "This text is Japanese, and local voice cloning has no model that can read it — it wouldn't fail, it would just produce unintelligible audio. Use a Japanese Edge TTS voice or OpenAI TTS instead.",
    },
    "voiceErr_koCloneUnsupported": {
        "zh": "这段文本是韩文,而本地音色克隆没有能念它的模型 —— 它不会报错,只会念出一段听不懂的声音。改用 Edge TTS 的韩文音色,或 OpenAI TTS。",
        "en": "This text is Korean, and local voice cloning has no model that can read it — it wouldn't fail, it would just produce unintelligible audio. Use a Korean Edge TTS voice or OpenAI TTS instead.",
    },
    "voiceErr_jaEdgeVoiceMismatch": {
        "zh": "这段文本是日文,而选中的 Edge 音色是 {voice_lang} 的 —— 请换一个 ja- 开头的音色。",
        "en": "This text is Japanese, but the selected Edge voice is {voice_lang}. Pick a voice that starts with ja-.",
    },
    "voiceErr_koEdgeVoiceMismatch": {
        "zh": "这段文本是韩文,而选中的 Edge 音色是 {voice_lang} 的 —— 请换一个 ko- 开头的音色。",
        "en": "This text is Korean, but the selected Edge voice is {voice_lang}. Pick a voice that starts with ko-.",
    },
    "voiceErr_jaVoiceMismatch": {
        "zh": "这段文本是日文,而选中的音色是 {voice_lang} 的 —— 它念出来会是一段听不懂的声音,请换一个能念日文的音色。",
        "en": "This text is Japanese, but the selected voice is {voice_lang} — it would come out unintelligible. Pick a voice that can read Japanese.",
    },
    "voiceErr_koVoiceMismatch": {
        "zh": "这段文本是韩文,而选中的音色是 {voice_lang} 的 —— 它念出来会是一段听不懂的声音,请换一个能念韩文的音色。",
        "en": "This text is Korean, but the selected voice is {voice_lang} — it would come out unintelligible. Pick a voice that can read Korean.",
    },
    "voiceErr_referenceTranscodeFailed": {"zh": "参考音频处理失败:{detail}", "en": "Couldn't process the reference audio: {detail}"},
    "voiceErr_assetNotFound": {"zh": "素材不存在", "en": "This asset doesn't exist."},
    "voiceErr_assetNoFile": {"zh": "素材没有本地文件", "en": "This asset has no local file."},
    "voiceErr_noTranscript": {"zh": "该素材还没有逐字稿,请先转写", "en": "This asset has no transcript yet — transcribe it first."},
    "voiceErr_noSpeakerSegments": {"zh": "没有找到该说话人的可用片段", "en": "No usable segments were found for this speaker."},
    "voiceErr_speakerExtractFailed": {"zh": "提取说话人音频失败:{detail}", "en": "Couldn't extract the speaker's audio: {detail}"},
    "voiceErr_referenceGoneForRecognition": {
        "zh": "这条音色的参考音频不在了,没法识别",
        "en": "This voice's reference audio is gone, so there's nothing to recognise.",
    },
    "voiceErr_nothingHeard": {
        "zh": "没听出内容 —— 参考音频可能太轻或没有人声,换一段再试",
        "en": "No speech was recognised — the reference audio may be too quiet or have no voice in it. Try a different clip.",
    },
    "voiceErr_nameEmpty": {"zh": "音色名称不能为空", "en": "Give the voice a name."},
    "voiceErr_consentKind": {
        "zh": "要选一项授权声明:这把嗓子是谁的({kinds})",
        "en": "Pick a consent declaration for whose voice this is ({kinds}).",
    },
    "exportAiLabelText": {"zh": "AI 生成", "en": "AI-generated"},
    "wfErr_voiceConsentMissing": {
        "zh": "音色「{name}」还没声明是谁的嗓子:在配音库里补上授权声明,才能用于数字人",
        "en": "The voice \"{name}\" has no declaration of whose voice it is. Add one in the voice library before using it for digital humans.",
    },
    "voiceErr_textEmpty": {"zh": "合成文本不能为空", "en": "Enter some text to synthesise."},
    "voiceErr_voiceNotFound": {"zh": "音色不存在", "en": "This voice doesn't exist."},
    "voiceErr_workspaceRequired": {"zh": "需要指定工作区", "en": "A workspace is required."},
    "voiceErr_referenceMissing": {"zh": "音色参考音频缺失", "en": "This voice's reference audio is missing."},
    "voiceErr_unknownPodcastMode": {"zh": "未知的播客模式:{mode}", "en": "Unknown podcast mode: {mode}"},
    "voiceErr_podcastWorkspaceRequired": {"zh": "播客需要指定工作区", "en": "A podcast needs a workspace."},
    "voiceErr_noVoiceSelected": {"zh": "没有选音色", "en": "No voice was selected."},
    "voiceErr_voiceNotInWorkspace": {
        "zh": "这个工作区的配音库里没有这个音色",
        "en": "This voice isn't in this workspace's voice library.",
    },
    "voiceErr_agentVoiceNotConfigured": {
        "zh": "还没有选语音对话的音色 —— 到设置的「语音对话」里选一个。它和配音的默认音色是分开的:配音要质量,对话要快。",
        "en": "No voice is chosen for voice chat yet — pick one under Settings → Voice chat. It's separate from the default voiceover voice: voiceovers want quality, chat wants speed.",
    },
    "voiceErr_agentVoiceDisabled": {
        "zh": "「让它出声」关着 —— 到设置的「语音对话」里打开,智能体才会念出来。",
        "en": "Speak replies is off — turn it on under Settings → Voice chat to hear the agent.",
    },
    # 字幕配音与原声处理(domain/voices/subtitle_dub.py、original_audio.py)
    "dubErr_originalAudioMode": {"zh": "原声处理方式只能是 {modes}", "en": "The original-audio mode must be one of {modes}."},
    "dubErr_separationUnavailableForMode": {
        "zh": "选择了「只去掉人声」，但音频分离引擎尚不可用；请部署管理员先在「管理 → 引擎」里安装，或明确改选「静音」",
        "en": "You chose \"Remove voice only\", but no audio separation engine is available yet. Have a deployment admin install one under Admin → Engines first, or choose \"Mute\" instead.",
    },
    "dubErr_separationUnavailable": {
        "zh": "音频分离引擎尚不可用；请部署管理员先在「管理 → 引擎」里安装",
        "en": "No audio separation engine is available yet — a deployment admin installs one under Admin → Engines first.",
    },
    "dubErr_sequenceNotFound": {"zh": "时间线不存在", "en": "This timeline doesn't exist."},
    "dubErr_removeVoiceFailed": {"zh": "只去掉人声失败：{detail}", "en": "Couldn't remove the voice: {detail}"},
    "dubErr_subtitleTrackNotFound": {"zh": "这条时间线上没有那条字幕轨", "en": "That subtitle track isn't on this timeline."},
    "dubErr_noSubtitleTrack": {"zh": "这条时间线上没有字幕轨", "en": "This timeline has no subtitle track."},
    "dubErr_multipleSubtitleTracks": {
        "zh": "这条时间线上有多条字幕轨,请指明配哪一条",
        "en": "This timeline has more than one subtitle track — say which one to dub.",
    },
    "dubErr_nothingToDub": {"zh": "选中的字幕里没有可配音的文本", "en": "The selected subtitles have no text to dub."},
    "dubErr_childMissing": {"zh": "合成任务不见了", "en": "The synthesis job has disappeared."},
    "dubErr_childNoAudio": {"zh": "合成任务报成功却没有产出音频", "en": "The synthesis job reported success but produced no audio."},
    "dubErr_childFailed": {"zh": "合成失败", "en": "Synthesis failed."},
    "dubErr_childTimeout": {"zh": "合成任务超时", "en": "The synthesis job timed out."},
    # 转写(domain/voices/transcription.py)
    "asrErr_unsupportedEngine": {"zh": "没有这一家转写:{name}", "en": "No such transcription provider: {name}"},
    "asrErr_providerNotReady": {"zh": "「{plugin}」还用不了:{missing}", "en": "“{plugin}” can't be used yet: {missing}"},
    "asrErr_pluginFailed": {"zh": "「{plugin}」没转成:{detail}", "en": "“{plugin}” couldn't transcribe it: {detail}"},
    "asrErr_pluginBadOutput": {
        "zh": "「{plugin}」交回的逐字稿形状不对(要有 segments,每段有 start / end / text):{detail}",
        "en": "“{plugin}” returned a transcript in the wrong shape (expected segments with start / end / text): {detail}",
    },
    "asrHint_runtimeMissing": {
        "zh": "缺的是运行环境,不是模型:模型权重已经下好的话不用再下一遍,但还没有 Python 解释器装了 {engine}。部署管理员在「管理 → 引擎 → 转写模型」里点「安装运行环境」,装一次就好。",
        "en": "What's missing is the runtime, not the model: if the weights are already downloaded there's no need to download them again, but no Python interpreter has {engine} installed yet. A deployment admin clicks Install runtime under Admin → Engines → Transcription models — it only needs doing once.",
    },
    "asrEngine_funasr": {"zh": "FunASR(本机)", "en": "FunASR (on device)"},
    "asrEngine_whisperx": {"zh": "WhisperX(本机)", "en": "WhisperX (on device)"},
    "asrErr_engineRuntimeMissing": {
        "zh": "所选 ASR 引擎 {engine} 的运行环境不可用,请部署管理员先在「管理 → 引擎 → 转写模型」里安装。",
        "en": "The runtime for the selected ASR engine {engine} isn't available. A deployment admin installs it first under Admin → Engines → Transcription models.",
    },
    "asrErr_noRuntime": {
        "zh": "缺的是运行环境,不是模型:模型权重已经下好的话不用再下一遍,但还没有任何 Python 解释器装了 funasr 或 whisperx。部署管理员在「管理 → 引擎 → 转写模型」里点「安装运行环境」,装一次就好。",
        "en": "What's missing is the runtime, not the model: if the weights are already downloaded there's no need to download them again, but no Python interpreter has funasr or whisperx installed. A deployment admin clicks Install runtime under Admin → Engines → Transcription models — it only needs doing once.",
    },
    "asrErr_audioExtractFailed": {"zh": "音频提取失败:{detail}", "en": "Couldn't extract the audio: {detail}"},
    "asrErr_dictationTooLong": {
        "zh": "这段录音 {seconds} 秒,超过了听写的 {limit} 秒上限 —— 长内容请作为素材导入再转写。",
        "en": "This recording is {seconds} s, over the {limit} s dictation limit. For longer content, import it as an asset and transcribe that.",
    },
    "asrErr_engineFailed": {"zh": "转写失败({engine}):{detail}", "en": "Transcription failed ({engine}): {detail}"},
    "asrErr_assetNotFound": {"zh": "素材不存在", "en": "This asset doesn't exist."},
    "asrErr_notMedia": {"zh": "只有视频或音频素材可以转写", "en": "Only video or audio assets can be transcribed."},
    "asrErr_assetNoFile": {"zh": "素材没有本地文件", "en": "This asset has no local file."},
    "asrErr_noAudioTrack": {
        "zh": "「{name}」没有音轨,没有可以转写的声音。",
        "en": "\"{name}\" has no audio track, so there's nothing to transcribe.",
    },
    "asrErr_emptyResult": {"zh": "转写结果为空", "en": "The transcription came back empty."},
    # 降噪(domain/assets/denoise.py)
    "denoiseErr_unknownEngine": {"zh": "没有这个降噪引擎:{name}", "en": "There's no noise-reduction engine called {name}."},
    "separationErr_unknownEngine": {"zh": "没有这个分离引擎:{name}", "en": "There's no vocal-separation engine called {name}."},
    "denoiseErr_noEngine": {"zh": "没有可用的降噪引擎", "en": "No noise-reduction engine is available."},
    "denoiseErr_engineNotReady": {"zh": "降噪引擎 {engine} 还没准备好", "en": "The noise-reduction engine {engine} isn't ready yet."},
    "denoiseErr_notMedia": {"zh": "只有音频或视频素材可以降噪", "en": "Only audio or video assets can be denoised."},
    "denoiseErr_fileMissing": {"zh": "这份素材的文件找不到了", "en": "This asset's file can't be found."},
    "denoiseErr_noLocalFile": {"zh": "这份素材没有本地文件", "en": "This asset has no local file."},
    # 人声与背景音分离(domain/assets/separation.py)
    "separationErr_noEngine": {"zh": "没有可用的音频分离引擎", "en": "No audio separation engine is available."},
    "separationErr_noEngineInstall": {
        "zh": "没有可用的音频分离引擎 —— 部署管理员先在「管理 → 引擎」里装一个",
        "en": "No audio separation engine is available — a deployment admin installs one under Admin → Engines first.",
    },
    "separationErr_fileMissing": {"zh": "这份素材的文件找不到了", "en": "This asset's file can't be found."},
    "separationErr_missingVocals": {"zh": "分离结果里缺少:人声", "en": "The separation result is missing the vocals."},
    "separationErr_missingBackground": {"zh": "分离结果里缺少:背景音", "en": "The separation result is missing the background."},
    "separationErr_notMedia": {"zh": "只有音频或视频素材可以分离", "en": "Only audio or video assets can be separated."},
    "separationErr_noLocalFile": {"zh": "这份素材没有本地文件", "en": "This asset has no local file."},
    # 素材分析(domain/analysis/service.py)
    "analysisErr_profileNotFound": {
        "zh": "指定的供应商配置不存在或已停用",
        "en": "The selected provider connection doesn't exist or is disabled.",
    },
    "analysisErr_noVisionProvider": {
        "zh": "没有可用的多模态供应商，请在设置中添加（如 Kimi 或 MiniMax）",
        "en": "No multimodal provider is available. Add one in Settings (for example Kimi or MiniMax).",
    },
    "analysisErr_noCredential": {
        "zh": "供应商「{name}」还没有配置你的密钥,请先在设置里填写",
        "en": "Provider \"{name}\" doesn't have your key yet. Add it in Settings first.",
    },
    "analysisErr_frameExtractFailed": {"zh": "视频抽帧失败", "en": "Couldn't extract frames from the video."},
    "analysisErr_noFrames": {"zh": "视频中没有可用画面", "en": "The video has no usable frames."},
    "analysisErr_videoTooLarge": {
        "zh": "视频超过 {mb}MB,原生直传过大,请改用抽帧模式",
        "en": "The video is over {mb} MB — too large to send natively. Switch to frame sampling.",
    },
    "analysisErr_noChatModel": {
        "zh": "供应商「{name}」没有可用的对话模型",
        "en": "Provider \"{name}\" has no usable chat model.",
    },
    "analysisErr_geminiFailed": {"zh": "Gemini 视频分析失败: {detail}", "en": "Gemini video analysis failed: {detail}"},
    "analysisErr_unsupportedKind": {"zh": "只支持分析图片或视频素材", "en": "Only image or video assets can be analysed."},
    "analysisErr_noLocalFile": {"zh": "素材没有本地文件", "en": "This asset has no local file."},
    "analysisErr_unknownMode": {"zh": "未知分析方式: {mode}", "en": "Unknown analysis mode: {mode}"},
    "analysisErr_fileMissing": {"zh": "素材文件缺失", "en": "This asset's file is missing."},
    "analysisErr_imageUnconvertible": {
        "zh": "图片无法转换成视觉模型支持的格式",
        "en": "The image couldn't be converted to a format the vision model supports.",
    },
    "analysisErr_oauthNoNativeVideo": {
        "zh": "当前 OAuth 模型的自动化 Gateway 不支持原生视频，请改用抽帧模式",
        "en": "This OAuth model's automation gateway doesn't support native video. Switch to frame sampling.",
    },
    "analysisErr_noNativeVideoProvider": {
        "zh": "没有支持原生视频理解的供应商(需 Gemini / 通义千问 Qwen-VL / Kimi),或改用抽帧模式",
        "en": "No provider supports native video understanding (it needs Gemini, Qwen-VL or Kimi). Add one, or switch to frame sampling.",
    },
}

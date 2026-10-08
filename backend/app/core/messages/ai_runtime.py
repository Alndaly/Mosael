"""后端文案 · ai/ 下的供应商与本机运行时:生成供应商、语音合成、降噪 / 分离、装依赖与常驻 worker(分区 B2)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- i18n 分区 B2(ai/ 下的供应商与运行时):这一批新加的 key 放在这行下面 ----
    # ---- 生成供应商(ai/providers):上游原话放在 {detail} 里,不翻 ----
    # 文案里**不写字面花括号**:任务失败原因那条路(render_message)总会 format 一遍,字面的 { } 会被吃掉;
    # 要显示花括号就走参数(见 pluginErr_streamNoResult 的 {shape})。
    "providerErr_apiKeyMissing": {
        "zh": "{vendor} 的 API Key 还没配置,请在设置 → 供应商配置里填写",
        "en": "{vendor} API key is not configured. Add it in Settings → Provider config.",
    },
    "providerErr_klingNoFace": {"zh": "可灵在这段视频里没认出人脸:换一段正脸清楚的视频", "en": "Kling found no face in this video; use one with a clear, frontal face."},
    "providerErr_klingFaceTooShort": {"zh": "这段视频里人脸出现不到 2 秒(或配音不到 2 秒),可灵对不了口型", "en": "The face is on screen for less than 2 seconds (or the audio is shorter than 2 seconds), so Kling can't lip-sync it."},
    "providerErr_klingAudioTooLarge": {"zh": "配音太长:可灵最多收 5MB 的音频,压成 mp3 还是超了,剪短一点再试", "en": "The audio is too long: Kling takes at most 5 MB, and it's still over after compressing to MP3. Shorten it and try again."},
    "providerErr_klingKeyMissing": {
        "zh": "可灵的 Access Key / API Key 还没配置,请在设置 → 供应商配置里填写",
        "en": "Kling Access Key / API key is not configured. Add it in Settings → Provider config.",
    },
    "providerErr_requestFailed": {"zh": "{vendor} 请求失败:{detail}", "en": "{vendor} request failed: {detail}"},
    "providerErr_firstFrameFetchFailed": {
        "zh": "{vendor} 取首帧图片失败:{detail}",
        "en": "{vendor} could not fetch the first-frame image: {detail}",
    },
    "providerErr_generationFailed": {"zh": "{vendor} 生成失败:{detail}", "en": "{vendor} generation failed: {detail}"},
    "providerErr_upstreamAuth": {
        "zh": "{vendor} 不认这把密钥,请到设置里检查连接的凭据:{detail}",
        "en": "{vendor} rejected the credentials; check the connection in Settings: {detail}",
    },
    "providerErr_upstreamBalance": {
        "zh": "{vendor} 账户余额或额度不足,充值后再试:{detail}",
        "en": "{vendor} account is out of balance or quota; top up and try again: {detail}",
    },
    "providerErr_upstreamRateLimited": {
        "zh": "{vendor} 限流了,等一会儿再试:{detail}",
        "en": "{vendor} is rate limiting requests; try again in a moment: {detail}",
    },
    "providerErr_upstreamContentBlocked": {
        "zh": "{vendor} 的内容审核拦下了这次请求(这是服务商的审核,不是 Mosael 拦的),换个说法再试:{detail}",
        "en": "{vendor} content moderation blocked this request (the provider's moderation, not Mosael's); rephrase and try again: {detail}",
    },
    #: 火山方舟的内容审核(见 adapters/bytedance/ark/errors)。说清是**服务商**的审核,不是 Mosael 拦的。
    "providerErr_arkPrivacyBlocked": {
        "zh": "火山方舟的内容审核认为{part}里可能有真人(隐私信息),拒绝了这次请求。这是服务商的审核,不是 Mosael 拦的:"
              "换一张不是写实真人的图,或者换一个不拦真人的模型(比如{alternative})再试。服务商原话:{detail}",
        "en": "Volcengine Ark's content moderation thinks {part} may show a real person (private information) and refused "
              "the request. This is the provider's moderation, not Mosael's: use an image that isn't a photorealistic real "
              "person, or switch to a model that doesn't block real people (such as {alternative}) and try again. "
              "Provider said: {detail}",
    },
    "providerErr_arkContentBlocked": {
        "zh": "火山方舟的内容审核认为{part}可能含敏感内容,拒绝了这次请求。这是服务商的审核,不是 Mosael 拦的:"
              "改一下{part}再试。服务商原话:{detail}",
        "en": "Volcengine Ark's content moderation thinks {part} may contain sensitive content and refused the request. "
              "This is the provider's moderation, not Mosael's: change {part} and try again. Provider said: {detail}",
    },
    "arkPart_inputText": {"zh": "提示词", "en": "the prompt"},
    "arkPart_inputImage": {"zh": "输入的图片(首帧 / 参考图)", "en": "an input image (first frame or reference)"},
    "arkPart_inputVideo": {"zh": "输入的视频", "en": "an input video"},
    "arkPart_inputAudio": {"zh": "输入的音频", "en": "an input audio clip"},
    "arkPart_outputText": {"zh": "生成的文字", "en": "the generated text"},
    "arkPart_outputImage": {"zh": "生成的图片", "en": "the generated image"},
    "arkPart_outputVideo": {"zh": "生成的视频", "en": "the generated video"},
    "arkPart_outputAudio": {"zh": "生成的音频", "en": "the generated audio"},
    "arkAlternative_video": {"zh": "Evolink 上的 Seedance", "en": "Seedance on Evolink"},
    "arkAlternative_image": {"zh": "Evolink 上的图像模型", "en": "an image model on Evolink"},
    "providerErr_upstreamInvalidParams": {
        "zh": "{vendor} 说参数不对:{detail}",
        "en": "{vendor} rejected the parameters: {detail}",
    },
    "providerErr_upstreamNotEntitled": {
        "zh": "{vendor} 账号没有开通这项服务(或这个模型):{detail}",
        "en": "{vendor} account is not entitled to this service or model: {detail}",
    },
    "providerErr_upstreamUnavailable": {
        "zh": "{vendor} 服务暂时不可用,稍后再试:{detail}",
        "en": "{vendor} is temporarily unavailable; try again later: {detail}",
    },
    "providerErr_noAudioData": {"zh": "{vendor} 没有返回音频", "en": "{vendor} returned no audio"},
    "providerErr_heygenKeyMissing": {
        "zh": "HeyGen 还没填 API Key:在设置里的「HeyGen」连接上填好",
        "en": "HeyGen has no API key yet: fill it in on the HeyGen connection in Settings",
    },
    "providerErr_heygenVideoFormat": {
        "zh": "HeyGen 的对口型只收 mp4 / webm 的原片,这段是 {format}:先在剪辑里导出成 mp4 再试",
        "en": "HeyGen lip-sync only takes mp4 / webm source videos and this one is {format}: export it as mp4 first",
    },
    "providerErr_hedraKeyMissing": {
        "zh": "Hedra 还没填 API Key:在设置里的「Hedra」连接上填好(形如 key_id:secret)",
        "en": "Hedra has no API key yet: fill it in on the Hedra connection in Settings (key_id:secret)",
    },
    "providerErr_volcanoVisualKeysMissing": {
        "zh": "即梦 AI 要账号级的 AK 和 SK:在设置里的「火山引擎 即梦 AI」连接上填好",
        "en": "Jimeng AI needs an account-level AK and SK: fill them in on the Volcengine Jimeng AI connection in Settings",
    },
    "providerErr_volcanoMusicKeysMissing": {
        "zh": "火山引擎音乐生成需要账号的 AK 和 SK,请到设置里把这条连接补全",
        "en": "Volcengine music generation needs the account's AK and SK; complete the connection in Settings",
    },
    "providerErr_noTaskId": {"zh": "{vendor} 没有返回任务 id", "en": "{vendor} did not return a task ID"},
    "providerErr_noUsableFace": {
        "zh": "{vendor}:这张图里没找到一张清晰的正脸,说不了话 —— 换一张清晰、单人、正面的人像。{detail}",
        "en": "{vendor}: no clear, frontal face was found in this image, so it can't talk — use a clear single-person front portrait. {detail}",
    },
    "providerErr_uploadPolicyMissing": {
        "zh": "{vendor} 没有给出临时存储的上传凭证,本地素材传不上去",
        "en": "{vendor} did not return an upload credential for temporary storage, so local media can't be sent",
    },
    "providerErr_sourceMissing": {"zh": "{vendor}:缺少素材({role})", "en": "{vendor}: missing source ({role})"},
    "providerErr_noTaskIdDetail": {"zh": "{vendor} 没有返回任务 id:{detail}", "en": "{vendor} did not return a task ID: {detail}"},
    "providerErr_noResultUrl": {
        "zh": "{vendor} 报告生成成功,但没有给出产物地址",
        "en": "{vendor} reported success but returned no result URL",
    },
    "providerErr_noImageData": {"zh": "{vendor} 没有返回图片数据", "en": "{vendor} returned no image data"},
    "providerErr_unexpectedUrlResult": {
        "zh": "{vendor} 返回的是图片地址,而这里要的是内联的图片数据",
        "en": "{vendor} returned an image URL where inline image data was expected",
    },
    "providerErr_cancelled": {"zh": "已取消", "en": "Cancelled"},
    "providerErr_pluginConnectionGone": {
        "zh": "这条生成连接对应的插件连接已经不在了,请重新选择模型",
        "en": "The plugin connection behind this model no longer exists. Pick a model again.",
    },
    "providerErr_pluginFailed": {"zh": "「{name}」生成失败:{detail}", "en": "“{name}” failed to generate: {detail}"},
    "providerErr_pluginSourceNotLibrary": {
        "zh": "只能把素材库里的文件交给插件,「{name}」不是",
        "en": "Only files from the asset library can be handed to a plugin, and “{name}” is not one.",
    },
    "providerErr_pollTimeout": {
        "zh": "生成超时(远端任务 {task} 在 {hours} 小时内没有结束)",
        "en": "Generation timed out (remote task {task} did not finish within {hours} h)",
    },
    "providerErr_vendorPollTimeout": {
        "zh": "{vendor} 生成超时(远端任务 {task} 在 {hours} 小时内没有结束)",
        "en": "{vendor} generation timed out (remote task {task} did not finish within {hours} h)",
    },
    "providerErr_resumeUnsupported": {
        "zh": "{vendor} 不支持取回已提交的任务",
        "en": "{vendor} cannot resume a task that was already submitted",
    },
    # 从远端拉一份媒体回来没成(见 ai/media_transfer.MediaDownloadError)。生成那边会换成一句更具体的话。
    "transferErr_downloadFailed": {"zh": "下载失败:{detail}", "en": "Download failed: {detail}"},
    "providerErr_promptEmpty": {"zh": "提示词不能为空", "en": "The prompt cannot be empty"},
    "providerErr_numImagesRange": {"zh": "图片张数要在 1 到 {max} 之间", "en": "The number of images must be between 1 and {max}"},
    "providerErr_durationInvalid": {
        "zh": "时长必须是正数,或 -1(自动)",
        "en": "Duration must be a positive number, or -1 (auto)",
    },
    "providerErr_durationRange": {
        "zh": "时长必须是 -1(自动),或在 {min} 到 {max} 秒之间",
        "en": "Duration must be -1 (auto) or between {min} and {max} seconds",
    },
    "providerErr_resolutionEmpty": {"zh": "分辨率不能为空", "en": "Resolution cannot be empty"},
    "providerErr_lyricsInvalid": {
        "zh": "歌词必须是一段不超过 {max} 字的文字",
        "en": "Lyrics must be text of at most {max} characters",
    },
    "providerErr_resolutionChoices": {"zh": "分辨率只能是 {choices} 之一", "en": "Resolution must be one of {choices}"},
    "providerErr_unreadableInputImage": {"zh": "{vendor} 无法读取输入图片:{name}", "en": "{vendor} could not read the input image: {name}"},
    "providerErr_uploadFailed": {"zh": "{vendor} 素材上传失败:{detail}", "en": "{vendor} media upload failed: {detail}"},
    "providerErr_uploadNoUrl": {
        "zh": "{vendor} 素材上传成功,但没有返回文件地址",
        "en": "{vendor} accepted the upload but returned no file URL",
    },
    "providerErr_tooManyImages": {"zh": "{vendor} 一次最多接收 {limit} 张图片", "en": "{vendor} accepts at most {limit} images per request"},
    "providerErr_tooManyVideos": {"zh": "{vendor} 一次最多接收 {limit} 段视频", "en": "{vendor} accepts at most {limit} videos per request"},
    "providerErr_tooManyAudios": {"zh": "{vendor} 一次最多接收 {limit} 段音频", "en": "{vendor} accepts at most {limit} audio clips per request"},
    "providerErr_klingElementsNeedOmni": {
        "zh": "可灵的多图参考主体只能用 Kling 3.0 Omni 模型",
        "en": "Kling reference elements require the Kling 3.0 Omni model",
    },
    "providerErr_klingElementImageCount": {
        "zh": "可灵的多图参考要 {min}～{max} 张图(第一张是正面图,其余是其他角度),这次给了 {given} 张",
        "en": "Kling multi-image reference needs {min}–{max} images (the first is the front view, the rest other angles); got {given}",
    },
    "providerErr_klingElementFailed": {"zh": "可灵建主体失败:{detail}", "en": "Kling could not create the reference element: {detail}"},
    "providerErr_klingElementNoId": {
        "zh": "可灵建主体成功却没有返回 element_id",
        "en": "Kling created the reference element but returned no element_id",
    },
    "providerErr_klingElementNoTaskId": {
        "zh": "可灵建主体没有返回任务 id",
        "en": "Kling did not return a task ID for the reference element",
    },
    "providerErr_klingElementTimeout": {"zh": "可灵建主体超时", "en": "Kling timed out creating the reference element"},
    "providerErr_klingTooManyElements": {
        "zh": "可灵一次最多引用 {max} 个主体,这次给了 {given} 个",
        "en": "Kling can reference at most {max} elements per request; got {given}",
    },
    # ---- 语音合成 / 播客 ----
    "providerErr_unknownSpeechEngine": {"zh": "未知的语音引擎:{engine}", "en": "Unknown speech engine: {engine}"},
    "providerErr_ttsKeyMissing": {
        "zh": "{engine} 语音合成需要 API Key,请在设置里配置",
        "en": "{engine} speech synthesis needs an API key. Add it in Settings.",
    },
    "providerErr_ttsFailed": {"zh": "{engine} 语音合成失败:{detail}", "en": "{engine} speech synthesis failed: {detail}"},
    "providerErr_ttsEmptyAudio": {"zh": "{engine} 语音合成返回空音频", "en": "{engine} speech synthesis returned empty audio"},
    "providerErr_edgeTtsMissing": {
        "zh": "edge-tts 依赖未安装,请更新后端环境",
        "en": "The edge-tts dependency is not installed. Update the backend environment.",
    },
    "providerErr_bailianTtsKeyMissing": {
        "zh": "百炼语音合成需要 DashScope API Key,请在设置里配置",
        "en": "Alibaba Cloud Bailian speech synthesis needs a DashScope API key. Add it in Settings.",
    },
    "providerErr_bailianTtsNoAudioUrl": {
        "zh": "百炼语音合成没有返回音频地址",
        "en": "Alibaba Cloud Bailian speech synthesis returned no audio URL",
    },
    "providerErr_bailianTtsFailed": {
        "zh": "百炼语音合成失败:{detail}",
        "en": "Alibaba Cloud Bailian speech synthesis failed: {detail}",
    },
    "providerErr_voiceEnrollFailed": {
        "zh": "百炼声音复刻失败:{detail}",
        "en": "Alibaba Cloud Bailian voice cloning failed: {detail}",
    },
    "providerErr_voiceEnrollUploadFailed": {
        "zh": "参考音频没能传到百炼的临时存储:{detail}",
        "en": "The reference audio couldn't be uploaded to Bailian's temporary storage: {detail}",
    },
    "providerErr_voiceEnrollNoVoiceId": {
        "zh": "百炼说复刻提交了,却没有给出音色 id",
        "en": "Bailian accepted the clone but returned no voice ID",
    },
    "providerErr_voiceEnrollUnsupported": {
        "zh": "{engine} 不支持声音复刻",
        "en": "{engine} doesn't support voice cloning",
    },
    "providerErr_volcanoTtsKeyMissing": {
        "zh": "火山引擎语音合成需要新版控制台的 API Key",
        "en": "Volcano Engine speech synthesis needs an API key from the new console",
    },
    "providerErr_volcanoTtsVoiceMissing": {
        "zh": "火山引擎语音合成需要音色 id(如 {example})",
        "en": "Volcano Engine speech synthesis needs a voice ID (e.g. {example})",
    },
    "providerErr_volcanoTtsFailed": {"zh": "火山 TTS 失败:{detail}", "en": "Volcano Engine TTS failed: {detail}"},
    "providerErr_volcanoTtsRequestFailed": {"zh": "火山 TTS 请求失败:{detail}", "en": "Volcano Engine TTS request failed: {detail}"},
    "providerErr_volcanoTtsEmptyAudio": {"zh": "火山 TTS 返回空音频", "en": "Volcano Engine TTS returned empty audio"},
    "providerErr_podcastConnectRejected": {"zh": "播客连接被拒绝:{detail}", "en": "The podcast connection was rejected: {detail}"},
    "providerErr_podcastSessionStartFailed": {"zh": "播客会话启动失败:{detail}", "en": "The podcast session failed to start: {detail}"},
    "providerErr_podcastFailed": {"zh": "播客生成失败(code={code}):{detail}", "en": "Podcast generation failed (code={code}): {detail}"},
    "providerErr_podcastSessionFailed": {"zh": "播客会话失败:{detail}", "en": "The podcast session failed: {detail}"},
    "providerErr_podcastEmptyAudio": {"zh": "播客返回了空音频", "en": "The podcast came back with empty audio"},
    "providerErr_podcastCredentialsMissing": {
        "zh": "火山播客需要 App ID 和 Access Token(不是语音合成的 API Key)",
        "en": "Volcano Engine podcasts need an App ID and Access Token (not the speech-synthesis API key)",
    },
    "providerErr_podcastNeedsTwoSpeakers": {
        "zh": "AI 生成对话需要正好两个发音人",
        "en": "An AI-generated dialogue needs exactly two speakers",
    },
    "providerErr_podcastNeedsInputText": {"zh": "请提供要改写成对话的文本", "en": "Provide the text to turn into a dialogue"},
    "providerErr_podcastNeedsTopic": {"zh": "请提供要检索并讨论的主题", "en": "Provide a topic to research and discuss"},
    "providerErr_podcastReadNeedsSpeaker": {"zh": "朗读模式需要至少一个发音人", "en": "Read-aloud mode needs at least one speaker"},
    "providerErr_podcastReadNeedsText": {"zh": "请提供要朗读的文本", "en": "Provide the text to read aloud"},
    # ---- 降噪 / 人声分离(本机引擎) ----
    "providerErr_denoiseUnknownStrength": {
        "zh": "不认识的降噪档位:{strength}(可选:{choices})",
        "en": "Unknown denoise strength: {strength} (choose from {choices})",
    },
    "providerErr_denoiseDeepfilterMissing": {"zh": "DeepFilterNet 还没装好", "en": "DeepFilterNet is not installed yet"},
    "providerErr_denoiseTimeout": {"zh": "降噪超时", "en": "Noise reduction timed out"},
    "providerErr_denoiseFailed": {"zh": "降噪失败:{detail}", "en": "Noise reduction failed: {detail}"},
    "providerErr_denoiseFailedSilent": {
        "zh": "降噪失败:{tool} 没有说明原因",
        "en": "Noise reduction failed: {tool} gave no reason",
    },
    "providerErr_denoiseConvertFailed": {
        "zh": "降噪前转换失败:{detail}",
        "en": "Could not convert the audio before noise reduction: {detail}",
    },
    "providerErr_denoiseConvertFailedSilent": {
        "zh": "降噪前转换失败:{tool} 没有说明原因",
        "en": "Could not convert the audio before noise reduction: {tool} gave no reason",
    },
    "providerErr_denoiseMeasureFailed": {
        "zh": "量不出这段音频的噪声:{detail}",
        "en": "Could not measure the noise in this audio: {detail}",
    },
    "providerErr_denoiseMeasureFailedSilent": {
        "zh": "量不出这段音频的噪声:{tool} 没有说明原因",
        "en": "Could not measure the noise in this audio: {tool} gave no reason",
    },
    "providerErr_separationRuntimeBroken": {
        "zh": "音频分离的运行环境还没装好(部署管理员在「管理 → 引擎」里装一次):{detail}",
        "en": "The audio separation runtime is not set up (a deployment admin installs it once under Admin → Engines): {detail}",
    },
    "providerErr_separationRuntimeMissing": {
        "zh": "音频分离的运行环境还没准备好,部署管理员在「管理 → 引擎」里装一次即可",
        "en": "The audio separation runtime is not ready. A deployment admin installs it once under Admin → Engines.",
    },
    "providerErr_separationFailed": {"zh": "分离失败:{detail}", "en": "Separation failed: {detail}"},
    "providerErr_separationExitCode": {"zh": "分离失败(退出码 {code})", "en": "Separation failed (exit code {code})"},
    "providerErr_separationUnreadable": {"zh": "分离结果读不出来:{detail}", "en": "Could not read the separation result: {detail}"},
    "providerErr_separationTimeout": {"zh": "分离超时", "en": "Separation timed out"},
    "providerErr_separationMissingStems": {"zh": "分离结果里缺少:{stems}", "en": "The separation result is missing: {stems}"},
    "providerErr_separationAudioMissing": {"zh": "找不到要分离的音频:{path}", "en": "Could not find the audio to separate: {path}"},
    "providerErr_separationNoDemucs": {
        "zh": "这个运行环境里没有 demucs:{detail}",
        "en": "demucs is not available in this runtime: {detail}",
    },
    "providerErr_separationNoVocals": {
        "zh": "{model} 没有给出人声轨,只有:{stems}",
        "en": "{model} produced no vocal track, only: {stems}",
    },
    "providerErr_separationOnlyVocals": {
        "zh": "{model} 只给了人声一条,没有可以合成背景音的部分",
        "en": "{model} produced only the vocal track, with nothing to build the background from",
    },
    "providerErr_separationWriteFailed": {"zh": "没能写出 {name}", "en": "Could not write {name}"},
    # ---- 本机运行环境(ai/runtime):装依赖、下权重、常驻 worker ----
    "runtimeErr_noBasePython": {
        "zh": "找不到可用于创建运行环境的 Python 解释器",
        "en": "No Python interpreter is available to create the runtime",
    },
    "runtimeErr_noBasePythonTts": {
        "zh": "找不到可用于创建运行环境的 Python。请重装应用,或在「管理 → 引擎 → 声音克隆」里手动指定一个 TTS 解释器(需要部署管理员)。",
        "en": "No Python is available to create the runtime. Reinstall the app, or set a TTS interpreter manually under Admin → Engines → Voice cloning (deployment admins only).",
    },
    "runtimeErr_venvFailed": {"zh": "创建运行环境失败:{detail}", "en": "Could not create the runtime: {detail}"},
    "runtimeErr_venvFailedSilent": {"zh": "创建运行环境失败:没有留下原因", "en": "Could not create the runtime, and no reason was given"},
    "runtimeErr_depsFailed": {
        "zh": "安装 {engine} 运行依赖失败:{detail}",
        "en": "Could not install the {engine} runtime dependencies: {detail}",
    },
    "runtimeErr_stillBroken": {
        "zh": "装完 {engine} 之后它仍然跑不起来:{detail}",
        "en": "{engine} still won't run after installing: {detail}",
    },
    "runtimeErr_stillBrokenSilent": {
        "zh": "装完 {engine} 之后它仍然跑不起来:没有留下原因",
        "en": "{engine} still won't run after installing, and no reason was given",
    },
    "runtimeErr_asrPythonMissing": {
        "zh": "未找到安装了 {engine} 的 Python 解释器,请设置 MOSAEL_ASR_PYTHON",
        "en": "No Python interpreter with {engine} installed was found. Set MOSAEL_ASR_PYTHON.",
    },
    "runtimeErr_unknownAsrEngine": {"zh": "不认识的转写引擎:{engine}", "en": "Unknown transcription engine: {engine}"},
    "runtimeErr_unknownSeparationEngine": {"zh": "不认识的分离引擎:{engine}", "en": "Unknown separation engine: {engine}"},
    "runtimeErr_alreadyDownloading": {"zh": "{name} 已经在下载中", "en": "{name} is already downloading"},
    "runtimeErr_alreadyInstalling": {"zh": "这个引擎已经在安装中", "en": "This engine is already being installed"},
    "runtimeErr_deepfilterUnsupportedPlatform": {
        "zh": "这个平台没有 DeepFilterNet 的发布文件",
        "en": "DeepFilterNet has no release build for this platform",
    },
    "runtimeErr_checksumMismatch": {
        "zh": "下载到的文件校验不符(SHA-256 {digest}…),已丢弃,没有安装",
        "en": "The downloaded file failed its checksum (SHA-256 {digest}…); it was discarded and nothing was installed",
    },
    "runtimeErr_f5LanguageBusy": {
        "zh": "已有语言包正在下载({busy}),请等它完成",
        "en": "A language pack is already downloading ({busy}). Wait for it to finish.",
    },
    "runtimeErr_f5RuntimeMissing": {
        "zh": "请先在「管理 → 引擎 → 声音克隆」里安装 F5-TTS 运行环境(需要部署管理员)",
        "en": "Install the F5-TTS runtime first under Admin → Engines → Voice cloning (deployment admins only)",
    },
    "runtimeErr_f5CheckpointMissing": {
        "zh": "下载报成功,但检查点不在盘上",
        "en": "The download reported success, but the checkpoint is not on disk",
    },
    "runtimeErr_f5NoTarget": {"zh": "没有指定权重目录", "en": "No weights directory was given"},
    "runtimeErr_gitMissing": {"zh": "未找到 git,无法拉取 Fish Speech 源码", "en": "git was not found, so the Fish Speech source cannot be fetched"},
    "runtimeErr_fishCloneFailed": {"zh": "拉取 Fish Speech 源码失败:{detail}", "en": "Could not fetch the Fish Speech source: {detail}"},
    "runtimeErr_fishCloneFailedSilent": {
        "zh": "拉取 Fish Speech 源码失败:git 没有说明原因",
        "en": "Could not fetch the Fish Speech source: git gave no reason",
    },
    "runtimeErr_fishRepoMissing": {
        "zh": "Fish Speech S2 不可用:需要 fishaudio/s2-pro 权重 + 官方 fish-speech 源码检出。部署管理员在「管理 → 引擎 → 声音克隆」里下载 Fish Speech(源码与权重一并装好),或设置 MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR。(源码目录未找到)",
        "en": "Fish Speech S2 is unavailable: it needs the fishaudio/s2-pro weights and an official fish-speech source checkout. A deployment admin downloads Fish Speech under Admin → Engines → Voice cloning (it fetches both), or sets MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR. (Source directory not found.)",
    },
    "runtimeErr_fishModelMissing": {
        "zh": "Fish Speech S2 不可用:需要 fishaudio/s2-pro 权重 + 官方 fish-speech 源码检出。部署管理员在「管理 → 引擎 → 声音克隆」里下载 Fish Speech(源码与权重一并装好),或设置 MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR。(模型目录缺少 codec.pth)",
        "en": "Fish Speech S2 is unavailable: it needs the fishaudio/s2-pro weights and an official fish-speech source checkout. A deployment admin downloads Fish Speech under Admin → Engines → Voice cloning (it fetches both), or sets MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR. (codec.pth is missing from the model directory.)",
    },
    "runtimeErr_fishNeedsReference": {"zh": "Fish Speech 需要参考音频", "en": "Fish Speech needs reference audio"},
    "runtimeErr_downloadNoReason": {
        "zh": "下载没有完成,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。",
        "en": "The download did not finish and the process left no reason. Try once more; if it keeps happening, please report it.",
    },
    "runtimeErr_downloadNoReasonLog": {
        "zh": "下载没有完成,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。\n完整日志:{log}",
        "en": "The download did not finish and the process left no reason. Try once more; if it keeps happening, please report it.\nFull log: {log}",
    },
    "runtimeErr_hubUnreachable": {
        "zh": "连不上模型下载源({endpoint}):{detail} —— 在上面的「模型下载源」换一个(镜像下不动时,官方直连往往反而是通的)再重试。",
        "en": "Could not reach the model download source ({endpoint}): {detail}. Switch “Model download source” above and try again (when a mirror stalls, the official source often works).",
    },
    "runtimeErr_hubUnreachableLog": {
        "zh": "连不上模型下载源({endpoint}):{detail} —— 在上面的「模型下载源」换一个(镜像下不动时,官方直连往往反而是通的)再重试。\n完整日志:{log}",
        "en": "Could not reach the model download source ({endpoint}): {detail}. Switch “Model download source” above and try again (when a mirror stalls, the official source often works).\nFull log: {log}",
    },
    "runtimeErr_failedWithLog": {"zh": "{detail}\n完整日志:{log}", "en": "{detail}\nFull log: {log}"},
    "runtimeErr_ttsWorkerBusy": {
        "zh": "{engine} 的合成正忙,等待超过 {seconds} 秒",
        "en": "{engine} is busy synthesizing; waited more than {seconds} seconds",
    },
    "runtimeErr_ttsWorkerFailed": {"zh": "合成失败", "en": "Synthesis failed"},
    "runtimeErr_ttsWorkerTimedOut": {
        "zh": "合成超时,没有回音 —— 进程已被终止",
        "en": "Synthesis timed out with no response; the process was stopped",
    },
    "runtimeErr_ttsWorkerDied": {
        "zh": "合成进程中途退出,没有给出结果",
        "en": "The synthesis process exited early without a result",
    },
    "runtimeErr_asrWorkerBusy": {
        "zh": "{engine} 的识别正忙,等待超过 {seconds} 秒",
        "en": "{engine} is busy transcribing; waited more than {seconds} seconds",
    },
    "runtimeErr_asrWorkerFailed": {"zh": "识别失败", "en": "Transcription failed"},
    "runtimeErr_asrWorkerTimedOut": {
        "zh": "识别超时,没有回音 —— 进程已被终止",
        "en": "Transcription timed out with no response; the process was stopped",
    },
    "runtimeErr_asrWorkerDied": {
        "zh": "识别进程中途退出,没有给出结果",
        "en": "The transcription process exited early without a result",
    },
}

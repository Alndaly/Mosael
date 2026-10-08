"""后端文案 · 生成、发布、浏览器、素材(分区 B3)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # -- B3·生成、发布、浏览器、素材 --
    # 生成:素材角色的名字(zh 与 domain/generation/catalog.SOURCE_ROLE_LABELS 一致,有测试钉着)
    "genRole_first_frame": {"zh": "首帧", "en": "first frame"},
    "genRole_last_frame": {"zh": "尾帧", "en": "last frame"},
    "genRole_reference_image": {"zh": "参考图", "en": "reference image"},
    "genRole_reference_video": {"zh": "参考视频", "en": "reference video"},
    "genRole_reference_audio": {"zh": "参考音频", "en": "reference audio"},
    "genRole_source_video": {"zh": "待编辑的视频", "en": "video to edit"},
    "genRole_first_clip": {"zh": "待续写的片段", "en": "clip to extend"},
    "genRole_driving_audio": {"zh": "驱动音频", "en": "driving audio"},
    "genRole_mask": {"zh": "蒙版", "en": "mask"},
    # 接在提示词后面告诉模型「谁是第几份」(见 generation.operations.source_legend)。这是说给模型听的,
    # 冒号后面不留空,和画板此前在前端拼的那一句一字不差。
    "genPromptSourceLegend": {
        "zh": "本次提供的素材:{legend}",
        "en": "Materials provided with this request:{legend}",
    },
    # 连进来的文档接在提示词后面时的抬头(见 generation.operations.documents_note),说给模型听的。
    # 英文和画板此前在前端拼的那一句一字不差。
    "genPromptReferenceDocuments": {
        "zh": "参考文档(素材):",
        "en": "Reference documents (source material):",
    },
    "genErr_orSep": {"zh": "或", "en": " or "},
    "genErr_andSep": {"zh": " 和 ", "en": " and "},
    "genErr_none": {"zh": "无", "en": "none"},
    # 生成:提交前的校验(domain/generation/operations)
    "genErr_noDefaultModel": {
        "zh": "还没有可用的生成模型,先去设置里配一个",
        "en": "No generation model is available yet. Set one up in Settings first.",
    },
    "genErr_sourceGone": {
        "zh": "{label}素材（{id}…）已删除或不在当前工作区，请重新连接或选择",
        "en": "The {label} asset ({id}…) was deleted or isn't in this workspace. Reconnect it or choose another.",
    },
    "genErr_sourceGoneNoId": {
        "zh": "{label}素材已删除或不在当前工作区，请重新连接或选择",
        "en": "The {label} asset was deleted or isn't in this workspace. Reconnect it or choose another.",
    },
    "genErr_connectionUnavailable": {
        "zh": "这条生成连接不可用",
        "en": "This generation connection isn't available.",
    },
    "genErr_adapterUnavailable": {
        "zh": "{provider}/{kind} 没有可用的生成适配器",
        "en": "No generation adapter is available for {provider}/{kind}.",
    },
    "genErr_workbenchGraphAlone": {
        "zh": "跑工作台画布上的图时,提示词、参数和素材都在图里 —— 不能再另给",
        "en": "When running the workbench canvas graph, the prompt, parameters and media are all in the graph; none can be given separately.",
    },
    "genErr_digitalHumanNeedsConsent": {
        "zh": "这是数字人生成(带驱动音频):先确认已取得画面中人物的授权 —— 本人,或已取得其单独同意",
        "en": "This is a digital-human generation (it has driving audio): confirm you have the pictured person's consent first — it's you, or they agreed separately.",
    },
    "genErr_voiceConsentMissing": {
        "zh": "驱动音频是用克隆音色「{name}」配的,而这把嗓子还没声明是谁的 —— 先到配音库里补上声明(本人、已获同意或虚构)",
        "en": "The driving audio was voiced with the cloned voice “{name}”, which has no consent declaration yet — declare whose voice it is in the voice library first (you, consented, or fictional).",
    },
    "genErr_entityConsentMissing": {
        "zh": "画面里的脸是人物「{name}」的参考图,而他是真人、还没有「本人」或「已获同意」的声明 —— 先在资产详情里补上",
        "en": "The face is a reference image of “{name}”, a real person with no “myself” or “consented” declaration yet — add it on the asset's page first.",
    },
    "genErr_sourceGroup": {"zh": "素材分组只能是 {groups}", "en": "The asset group must be one of: {groups}"},
    "genErr_unknownRole": {"zh": "未知的素材角色:{role}", "en": "Unknown asset role: {role}"},
    "genErr_notInteger": {
        "zh": "{provider}/{model} 的 {name} 必须是整数",
        "en": "{name} for {provider}/{model} must be a whole number.",
    },
    "genErr_unknownParams": {
        "zh": "{provider}/{model} 不支持这些参数:{unknown};可用的是:{allowed}",
        "en": "{provider}/{model} doesn't support these parameters: {unknown}. Supported: {allowed}",
    },
    "genErr_notBoolean": {
        "zh": "{provider}/{model} 的 {name} 必须是布尔值 true/false",
        "en": "{name} for {provider}/{model} must be true or false.",
    },
    "genErr_notNumber": {
        "zh": "{provider}/{model} 的 {name} 必须是数字",
        "en": "{name} for {provider}/{model} must be a number.",
    },
    "genErr_notText": {
        "zh": "{provider}/{model} 的 {name} 必须是文本",
        "en": "{name} for {provider}/{model} must be text.",
    },
    "genErr_paramBelow": {
        "zh": "{provider}/{model} 的 {name} 不能小于 {low}",
        "en": "{name} for {provider}/{model} can't be less than {low}.",
    },
    "genErr_paramAbove": {
        "zh": "{provider}/{model} 的 {name} 不能大于 {high}",
        "en": "{name} for {provider}/{model} can't be more than {high}.",
    },
    "genErr_sizeFormat": {
        "zh": "{provider}/{model} 的尺寸要写成「宽x高」,每边至少 {minimum}(比如 {example}),收到的是:{value}",
        "en": "The size for {provider}/{model} must be written as width x height, at least {minimum} on each side (e.g. {example}); got: {value}",
    },
    "genErr_choiceOnly": {
        "zh": "{provider}/{model} 的 {name} 只能是:{choices}",
        "en": "{name} for {provider}/{model} must be one of: {choices}",
    },
    "genErr_durationChoices": {
        "zh": "{provider}/{model} 的时长只能是:{choices} 秒",
        "en": "Duration for {provider}/{model} must be one of: {choices} seconds",
    },
    "genErr_durationRange": {
        "zh": "{provider}/{model} 的时长要在 {low}–{high} 秒之间",
        "en": "Duration for {provider}/{model} must be between {low} and {high} seconds.",
    },
    "genErr_durationRangeOrAuto": {
        "zh": "{provider}/{model} 的时长要在 {low}–{high} 秒之间，或 {special}（自动）",
        "en": "Duration for {provider}/{model} must be between {low} and {high} seconds, or {special} (auto).",
    },
    "genErr_durationForResolution": {
        "zh": "{provider}/{model} 的 {resolution} 分辨率只支持 {choices} 秒",
        "en": "At {resolution}, {provider}/{model} only supports {choices} seconds.",
    },
    "genErr_roleUnsupported": {
        "zh": "{provider}/{model} 不支持「{role}」这种素材;它支持的是:{supported}",
        "en": "{provider}/{model} doesn't accept “{role}” assets. It accepts: {supported}",
    },
    "genErr_sourceDurationRange": {
        "zh": "{label}「{name}」{seconds} 秒,这个模型只收 {min}–{max} 秒的 —— 剪一段,或换一个模型",
        "en": "The {label} “{name}” is {seconds}s; this model only takes {min}–{max}s. Trim it, or pick another model.",
    },
    "genErr_durationCapWithRole": {
        "zh": "{provider}/{model} 挂了{label}时,时长最多 {cap} 秒(不挂能到 {max} 秒)",
        "en": "With a {label} attached, {provider}/{model} allows at most {cap} seconds ({max} seconds without it).",
    },
    "genErr_tooManySources": {
        "zh": "{provider}/{model} 最多收 {cap} 份{label},这次给了 {count} 份",
        "en": "{provider}/{model} accepts at most {cap} {label} input(s); this request has {count}.",
    },
    "genErr_tooFewReferences": {
        "zh": "{provider}/{model} 的多图参考至少要 {floor} 张参考图(第一张是正面图,其余是其他角度),这次只给了 {given} 张",
        "en": "Multi-image reference for {provider}/{model} needs at least {floor} reference images (the first is the front view, the rest are other angles); only {given} given.",
    },
    "genErr_exclusiveSources": {
        "zh": "{provider}/{model} 的{names}不能一起用:它们对应不同的生成模式,一次只能选择一组。",
        "en": "For {provider}/{model}, {names} can't be used together: they belong to different generation modes, so choose one set at a time.",
    },
    "genErr_sourceRequired": {
        "zh": "{provider}/{model} 必须给一份{options}",
        "en": "{provider}/{model} needs a {options}.",
    },
    "genErr_companionRequired": {
        "zh": "{provider}/{model} 的{label}不能单独使用,要搭配{companions}一起给",
        "en": "For {provider}/{model}, the {label} can't be used alone; add a {companions} as well.",
    },
    # 生成:任务执行时(domain/generation/runner)
    "genErr_noApiKey": {
        "zh": "供应商 {provider} 还没有配置你的密钥,请先在设置里填写",
        "en": "Provider {provider} doesn't have your API key yet. Add it in Settings first.",
    },
    "genErr_sourceMissing": {
        "zh": "{label}素材不存在或不属于当前工作区",
        "en": "The {label} asset doesn't exist or isn't in this workspace.",
    },
    # 服务商做完了、成片没拉回来(见 ai/media_transfer.MediaDownloadError)。这时钱多半已经扣了 —— 不能说成「供应商
    # 请求失败」,更不能让人以为要重新生成。远端任务还能再问的,说去点「重新取回」;问不了的(同步接口),说清只能重来。
    "genErr_resultNotCollected": {
        "zh": "服务商已经生成好了(这一次多半已经计费),只是把成片下载回来时断了:{detail}。点「重新取回」再下一次就行,不用重新生成,也不会再付一次钱。",
        "en": "The provider finished this generation (it has most likely been charged), but downloading the result broke off: {detail}. Use “Retrieve again” to download it once more — no need to generate again or pay twice.",
    },
    "genErr_resultNotCollectedNoReceipt": {
        "zh": "服务商已经生成好了(这一次多半已经计费),只是把成片下载回来时断了:{detail}。这家的接口事后取不回,只能重新生成;重来之前可以先去服务商后台看看这一次有没有扣费。",
        "en": "The provider finished this generation (it has most likely been charged), but downloading the result broke off: {detail}. This provider can't hand a result over again later, so the only way is to generate again — check the provider's console for this charge first.",
    },
    # 付费请求送到了、没等到回答(读超时、网关 502 / 504 / 524,见 core/http_retry.sent_but_unanswered)。对方多半照样在做、
    # 照样扣钱,而我们手里什么都没有 —— 不能说成「请求失败」让人放心重来。
    "genErr_outcomeUnknown": {
        "zh": "请求已经送到服务商,但没等到回答:{detail}。服务商可能照样做完、照样扣了费(这一次的花费按估算记下了)。重新生成之前,先去服务商后台看看这一次有没有扣费、有没有出结果。",
        "en": "The request reached the provider, but no answer came back: {detail}. The provider may have finished it and charged for it anyway (an estimate for this attempt has been recorded). Before generating again, check the provider's console for this charge and result.",
    },
    "genErr_notRetrievable": {
        "zh": "这条生成没有能重新取回的远端结果:它没提交出去、已经取回过、被停下了,或者这家供应商不支持事后再取",
        "en": "There is no remote result to retrieve for this generation: it was never submitted, was already retrieved, was stopped, or this provider can't hand a result over again.",
    },
    "genErr_sourceMustBeVideo": {"zh": "{label}素材必须是视频", "en": "The {label} asset must be a video."},
    "genErr_sourceMustBeImage": {"zh": "{label}素材必须是图片", "en": "The {label} asset must be an image."},
    "genErr_sourceMustBeAudio": {"zh": "{label}素材必须是音频", "en": "The {label} asset must be audio."},
    "genErr_promptOrLyricsRequired": {
        "zh": "{provider} · {model}:描述和歌词至少要给一段",
        "en": "{provider} · {model}: give a description, lyrics, or both.",
    },
    "genErr_lyricsTooLong": {
        "zh": "{provider} · {model}:歌词最多 {cap} 字,现在是 {count} 字",
        "en": "{provider} · {model}: lyrics can be at most {cap} characters; these are {count}.",
    },
    "genErr_lyricsExcludesPrompt": {
        "zh": "{provider} · {model}:歌词和描述只能给一段 —— 两段都给时这个模型只用歌词,描述会被丢掉",
        "en": "{provider} · {model}: give either lyrics or a description, not both — this model would use the lyrics and drop the description.",
    },
    "genErr_instrumentalWithLyrics": {
        "zh": "{provider} · {model}:选了纯音乐就不要再给歌词 —— 两者只能二选一",
        "en": "{provider} · {model}: an instrumental track has no lyrics; clear one of the two.",
    },
    "genErr_instrumentalNeedsPrompt": {
        "zh": "{provider} · {model}:纯音乐要写一段描述(风格、情绪、乐器……)",
        "en": "{provider} · {model}: an instrumental track needs a description (style, mood, instruments…).",
    },
    "genErr_promptRequired": {
        "zh": "{provider} · {model}:这个模型要写一段描述",
        "en": "{provider} · {model}: this model needs a description.",
    },
    "genErr_promptNotAccepted": {
        "zh": "{provider} · {model}:这个模型不收提示词 —— 它只按素材和参数出结果;把提示词清空再提交",
        "en": "{provider} · {model}: this model takes no prompt — it works from the inputs and parameters alone. Clear the prompt and submit again.",
    },
    "genErr_lyricsRequired": {
        "zh": "{provider} · {model}:这个模型要给歌词",
        "en": "{provider} · {model}: this model needs lyrics.",
    },
    "genErr_sourceNoLocalFile": {"zh": "{label}素材缺少本地文件", "en": "The {label} asset has no local file."},
    "genErr_sourceFileMissing": {"zh": "{label}素材文件不存在", "en": "The {label} asset's file is missing."},
    # 生成:提示词优化
    "genErr_optimizeNotJson": {
        "zh": "提示词优化返回的不是合法 JSON",
        "en": "Prompt optimization didn't return valid JSON.",
    },
    "genErr_optimizeNotObject": {
        "zh": "提示词优化返回的 JSON 不是对象",
        "en": "Prompt optimization returned JSON that isn't an object.",
    },
    "genErr_optimizeEmptyPrompt": {"zh": "提示词为空,无法优化", "en": "The prompt is empty, so there's nothing to optimize."},
    "genErr_optimizeNoChatModel": {
        "zh": "未配置对话模型,请在设置里为「对话」选择供应商与模型",
        "en": "No chat model is set up. In Settings, choose a provider and model for Chat.",
    },
    "genErr_optimizeEmptyResult": {"zh": "优化结果为空", "en": "Optimization came back empty."},
    # 生成:本地素材换公网直链(domain/generation/public_links)
    "genErr_noUploader": {
        "zh": (
            "「{asset}」是本地素材,而这个模型的这一项只收公网链接。"
            "在「插件」页的「对象存储」里建一个连接(火山引擎 TOS / 阿里云 OSS / 腾讯云 COS / Amazon S3 / S3 兼容服务),"
            "填上桶和密钥,之后它会自动传上去;或者直接粘一条你已有的公网直链。"
        ),
        "en": (
            "“{asset}” is a local asset, but this model only accepts a public link here. "
            "Create a connection under Object Storage on the Plugins page (Volcengine TOS / Alibaba Cloud OSS / "
            "Tencent Cloud COS / Amazon S3 / any S3-compatible service) and fill in the bucket and keys — it will then "
            "be uploaded automatically. Or paste a public direct link you already have."
        ),
    },
    "genErr_uploaderIncomplete": {
        "zh": "「{plugin}」还没配好({missing}),所以「{asset}」传不上去。去插件页把它补齐,或者直接粘一条公网直链。",
        "en": "“{plugin}” isn't fully set up (missing: {missing}), so “{asset}” can't be uploaded. Complete it on the Plugins page, or paste a public direct link.",
    },
    "genErr_uploaderAmbiguous": {
        "zh": "你配好了几家对象存储({names}),「{asset}」要传去哪一家还没定。去「设置 → 能力提供方 → 素材外链」里选一家,再生成一次。",
        "en": "You've set up several object storage services ({names}) and haven't chosen where “{asset}” goes. Pick one under Settings → Capability providers → Asset links, then generate again.",
    },
    "genErr_uploaderOutdated": {
        "zh": "「{plugin}」的插件版本太旧 —— 去「插件」页的市场里把它更新到最新,再生成一次。",
        "en": "“{plugin}” is out of date — update it from the marketplace on the Plugins page, then generate again.",
    },
    "genErr_uploadFailed": {
        "zh": "用「{plugin}」上传「{asset}」失败:{detail}",
        "en": "Uploading “{asset}” with “{plugin}” failed: {detail}",
    },
    "genErr_pluginNoReason": {"zh": "插件没说原因", "en": "the plugin gave no reason"},
    "genErr_uploadNoUrl": {
        "zh": "「{plugin}」传完了却没给出地址 —— 这是插件自己的 bug",
        "en": "“{plugin}” finished uploading but returned no address — that's a bug in the plugin.",
    },
    # 生成:模型解析与参数契约(domain/generation/resolution)
    "genErr_unknownKind": {"zh": "未知的生成类型:{kind}", "en": "Unknown generation type: {kind}"},
    "genErr_templateMismatch": {
        "zh": "参数模板不属于这条连接或生成类型不匹配",
        "en": "This parameter template belongs to another connection or a different generation type.",
    },
    "genErr_contractMissing": {"zh": "参数契约不存在", "en": "This parameter contract doesn't exist."},
    "genErr_connectionMissing": {"zh": "生成连接不存在", "en": "The generation connection doesn't exist."},
    "genErr_modelUnavailable": {
        "zh": "「{model}」现在用不了:{reason}",
        "en": "“{model}” can't be used right now: {reason}",
    },
    "genMissing_someModel": {"zh": "之前选的模型", "en": "The model chosen earlier"},
    "genMissing_connectionGone": {
        "zh": "它所在的那条连接已经删掉了 —— 换一个模型",
        "en": "The connection it was on has been deleted. Choose another model.",
    },
    "genMissing_connectionOff": {
        "zh": "连接「{name}」现在用不了(停用了或还没配好)—— 到设置或插件页打开它,或者换一个模型",
        "en": "The connection “{name}” can't be used right now (it's turned off or not set up). Turn it on in Settings or "
              "on the Plugins page, or choose another model.",
    },
    "genMissing_modelOff": {
        "zh": "「{model}」在连接「{name}」上停用了 —— 到设置里打开它,或者换一个模型",
        "en": "“{model}” is turned off on the connection “{name}”. Turn it on in Settings, or choose another model.",
    },
    "genMissing_modelGone": {
        "zh": "连接「{name}」上已经没有它了(改了名、挪了位置或删掉了)—— 换一个模型",
        "en": "The connection “{name}” no longer has it (it was renamed, moved or deleted). Choose another model.",
    },
    "genErr_modelNotEnabled": {
        "zh": "生成模型未启用或不存在",
        "en": "The generation model isn't enabled or doesn't exist.",
    },
    "genErr_modelLacksKind_image": {
        "zh": "「{model}」没有标上「图像生成」能力。到设置里这个模型的「能力」标上它,或换一个模型",
        "en": "“{model}” isn't tagged for image generation. Tag it under this model's Capabilities in Settings, or pick another model.",
    },
    "genErr_modelLacksKind_video": {
        "zh": "「{model}」没有标上「视频生成」能力。到设置里这个模型的「能力」标上它,或换一个模型",
        "en": "“{model}” isn't tagged for video generation. Tag it under this model's Capabilities in Settings, or pick another model.",
    },
    "genErr_modelLacksKind_audio": {
        "zh": "「{model}」没有标上「音乐与音效生成」能力。到设置里这个模型的「能力」标上它,或换一个模型",
        "en": "“{model}” isn't tagged for music & sound generation. Tag it under this model's Capabilities in Settings, or pick another model.",
    },
    "genErr_modelAmbiguous": {
        "zh": "同一模型存在于多条连接，请明确选择连接",
        "en": "This model exists on more than one connection. Choose which connection to use.",
    },
    # 生成:自定义参数组(domain/generation/custom_profiles)
    "genErr_profileStrList": {"zh": "{field} 要是一串非空文字", "en": "{field} must be a list of non-empty strings."},
    "genErr_profilePositiveInt": {"zh": "{field} 要是一个正整数", "en": "{field} must be a positive whole number."},
    "genErr_profileIntList": {"zh": "{field} 要是一串整数", "en": "{field} must be a list of whole numbers."},
    "genErr_profileStr": {"zh": "{field} 要是一段非空文字", "en": "{field} must be non-empty text."},
    "genErr_profileInt": {"zh": "{field} 要是一个整数", "en": "{field} must be a whole number."},
    "genErr_profileBool": {"zh": "{field} 要是 true 或 false", "en": "{field} must be true or false."},
    "genErr_profileChoice": {"zh": "{field} 只能是 {choices} 之一", "en": "{field} must be one of {choices}."},
    "genErr_profileStrToInt": {"zh": "{field} 要是一组「名字 → 正整数」", "en": "{field} must map names to positive whole numbers."},
    "genErr_profileStrToStrList": {"zh": "{field} 要是一组「名字 → 可选值」", "en": "{field} must map names to lists of allowed values."},
    "genErr_profileStrToIntList": {"zh": "{field} 要是一组「名字 → 一串整数」", "en": "{field} must map names to lists of whole numbers."},
    "genErr_profileGroups": {"zh": "{field} 要是若干组名字", "en": "{field} must be a list of name groups."},
    "genErr_profileUnknownShape": {"zh": "{field} 的形状没人认得", "en": "The shape of {field} isn't recognized."},
    "genErr_profileKind": {"zh": "参数组只能是 {kinds}", "en": "A parameter set must be for {kinds}."},
    "genErr_profileNotObject": {"zh": "参数组的内容要是一组键值", "en": "A parameter set must be an object of key-value pairs."},
    "genErr_profileUnknownFields": {"zh": "这几个字段我们不认得:{fields}", "en": "These fields aren't recognized: {fields}"},
    "genErr_profileUnsentParams": {
        "zh": "这些参数当前没有生成适配器会发送，不能只在界面里声明:{params}",
        "en": "No generation adapter sends these parameters yet, so they can't just be declared here: {params}",
    },
    "genErr_profileNoParams": {
        "zh": "至少要声明一个参数(parameter_keys),否则指向它和不指是一样的",
        "en": "Declare at least one parameter (parameter_keys); otherwise pointing to this set is the same as not pointing to one.",
    },
    "genErr_profileDefaultNotListed": {
        "zh": "{default_key} 的值不在 {list_key} 里面",
        "en": "The value of {default_key} isn't in {list_key}.",
    },
    # 发布
    "publishErr_unknownOption": {
        "zh": "{platform} 不支持发布选项 {option}(支持:{supported})",
        "en": "{platform} doesn't support the publish option {option} (supported: {supported})",
    },
    "publishErr_optionNeedsBool": {
        "zh": "发布选项 {option} 需要 true/false(收到 {value})",
        "en": "Publish option {option} must be true or false (got {value})",
    },
    "publishErr_optionChoices": {
        "zh": "发布选项 {option} 只能是 {choices}(收到 {value})",
        "en": "Publish option {option} must be one of {choices} (got {value})",
    },
    "publishErr_unknownPlatform": {
        "zh": "未知平台: {platform}(支持 {supported})",
        "en": "Unknown platform: {platform} (supported: {supported})",
    },
    "publishErr_missingConfig": {
        "zh": "平台 {platform} 缺少必填配置 {key}",
        "en": "Platform {platform} is missing the required setting {key}.",
    },
    "publishErr_accountDisabled": {"zh": "发布账号已停用", "en": "This publishing account is disabled."},
    "publishErr_assetNoFile": {"zh": "素材没有本地文件,无法发布", "en": "The asset has no local file, so it can't be published."},
    "publishErr_titleTooLong": {
        "zh": "{platform} 标题最多 {max} 字(当前 {count} 字)",
        "en": "{platform} titles can be at most {max} characters (this one has {count}).",
    },
    "publishErr_assetNotFound": {"zh": "素材不存在", "en": "Asset not found."},
    "publishErr_copyNeedsInput": {"zh": "需要提供 brief 或素材", "en": "Provide a brief or an asset."},
    "publishErr_copyNoJson": {"zh": "输出中没有 JSON 对象", "en": "The output contains no JSON object."},
    "publishErr_copyInvalid": {"zh": "AI 未能产出合法文案: {detail}", "en": "The AI couldn't produce valid copy: {detail}"},
    "publishErr_unknownTaskStatus": {"zh": "未知任务状态: {status}", "en": "Unknown task status: {status}"},
    "publishErr_taskNotFound": {"zh": "任务不存在", "en": "Task not found."},
    "publishErr_accountNotFound": {"zh": "账号不存在", "en": "Account not found."},
    "publishErr_unknownBindingStatus": {"zh": "未知登录态: {status}", "en": "Unknown sign-in status: {status}"},
    # 浏览器自动化
    "browserErr_uploadNeedsHostFile": {
        "zh": "上传的文件必须来自素材库,或是你有权读的本机路径",
        "en": "The uploaded file must come from the asset library or be a path on this computer you're allowed to read.",
    },
    "browserErr_navigateScheme": {
        "zh": "浏览器只能打开 http(s) 网址",
        "en": "The browser can only open http(s) addresses.",
    },
    "browserErr_profileNotFound": {"zh": "浏览器档案不存在", "en": "Browser profile not found."},
    "browserErr_profileHasSession": {
        "zh": "该档案有正在进行的会话,先结束再删",
        "en": "This profile has an active session. End it before deleting.",
    },
    "browserErr_profileLinkedToAccount": {
        "zh": "该档案绑定了发布账号,请先在发布页解绑或删除账号",
        "en": "This profile is linked to a publishing account. Unlink or delete that account on the Publish page first.",
    },
    "browserErr_invalidSessionName": {
        "zh": "具名会话要有一个名字(不超过 {max} 个字)",
        "en": "A named session needs a name (at most {max} characters).",
    },
    "browserErr_sessionBusy": {
        "zh": "具名会话「{name}」正被另一次运行占用(同一份登录同一时刻只给一个),等它结束再试",
        "en": "The named session “{name}” is in use by another run (one sign-in serves one run at a time). Try again when it finishes.",
    },
    "browserNotice_loginNotCarriedOver": {
        "zh": "具名会话「{name}」没有沿用升级前的登录,需要重新登录一次。原因:{detail}",
        "en": "The named session “{name}” didn't keep its sign-in from before the upgrade; sign in again once. Reason: {detail}",
    },
    "browserErr_profileDisabled": {"zh": "该浏览器档案已停用", "en": "This browser profile is disabled."},
    "browserErr_profileBusy": {
        "zh": "该档案正被占用(同一时刻只允许一个会话),请稍后再试",
        "en": "This profile is in use (only one session at a time). Try again later.",
    },
    "browserErr_sessionClosed": {
        "zh": "浏览器会话不存在或已关闭",
        "en": "The browser session doesn't exist or has been closed.",
    },
    "browserErr_actionLost": {"zh": "浏览器动作丢失", "en": "The browser action was lost."},
    "browserErr_actionFailed": {"zh": "浏览器动作失败", "en": "The browser action failed."},
    "browserErr_actionFailedDetail": {"zh": "浏览器动作失败:{detail}", "en": "The browser action failed: {detail}"},
    "browserErr_actionTimeout": {
        "zh": "浏览器动作执行超时:执行器领走之后一直没做完",
        "en": "The browser action timed out: the executor took it but never finished it.",
    },
    "browserErr_actionNotClaimed": {
        "zh": "浏览器动作一直没被领走:桌面端没开,或者浏览器执行器没在运行",
        "en": "Nobody picked up the browser action: the desktop app isn't open, or its browser executor isn't running.",
    },
    "browserErr_actionQueueTimeout": {
        "zh": "浏览器动作排队超过 {seconds} 秒还没轮到:执行器在线,但前面还有 {ahead} 条动作在排或在跑",
        "en": "The browser action waited over {seconds} seconds in the queue: the executor is online, but {ahead} actions ahead of it are queued or running.",
    },
    "browserErr_actionHalted": {
        "zh": "这次运行已经停下(别的节点失败了),浏览器动作不再等",
        "en": "This run has stopped (another node failed), so the browser action is no longer awaited.",
    },
    "browserErr_invalidActionStatus": {"zh": "非法动作状态", "en": "Invalid action status."},
    "browserErr_actionNotFound": {"zh": "动作不存在", "en": "Action not found."},
    "browserErr_leaseMismatch": {
        "zh": "租约令牌不匹配:这条动作已经不归你了",
        "en": "Lease token mismatch: this action no longer belongs to you.",
    },
    "browserErr_artifactLate": {
        "zh": "这条动作已经结束了,它的下载 / 截图来晚了,没有收进素材库。",
        "en": "This action has already finished; its download or screenshot arrived too late and wasn't saved to the library.",
    },
    "browserErr_executorLost": {
        "zh": "执行器失联(租约到期)",
        "en": "Lost contact with the executor (its lease expired).",
    },
    "browserErr_backendRestarted": {
        "zh": "后端重启导致中断",
        "en": "Interrupted because the backend restarted.",
    },
    # 素材:从链接导入、插件取素材、视频转 GIF
    "urlImportErr_noneSelected": {"zh": "没有选中任何条目", "en": "No items are selected."},
    "urlImportErr_tooMany": {
        "zh": "一次最多下载 {max} 条,先分几次来",
        "en": "You can download at most {max} items at a time. Split them into several batches.",
    },
    "urlImportErr_badKind": {"zh": "只能下载视频或音频", "en": "Only video or audio can be downloaded."},
    "urlImportErr_badPageUrl": {"zh": "视频所在页面的地址必须是 http(s) 地址", "en": "The address of the page the video came from must be an http(s) address."},
    "assetErr_notFoundRef": {"zh": "素材不存在: {ref}", "en": "Asset not found: {ref}"},
    "capability_public_url": {"zh": "素材外链", "en": "Asset links"},
    "capability_public_url_desc": {"zh": "有些模型只收链接不收本地文件(方舟 Seedance 的参考视频等):本地素材先传到你的对象存储,换一条限时直链。", "en": "Some models only accept a link, not a local file (Seedance's reference video, for one): local assets are uploaded to your object storage for a time-limited link."},
    "capability_document_parse": {"zh": "文档解析", "en": "Document parsing"},
    "capability_document_parse_desc": {"zh": "把 PDF、Word、PPT、Excel 等文档转成 Markdown,给智能体读、存成笔记。本地解析不出本机;交给插件(如 MinerU 云端)时文档会上传到那一家。", "en": "Turns PDF, Word, PowerPoint, Excel and other documents into Markdown for the agent to read and to save as notes. Local parsing stays on this computer; a plugin (such as MinerU's cloud) uploads the document to that service."},
    "capErr_none": {"zh": "还没有能做这件事的连接", "en": "No connection can do this yet."},
    "capErr_notDefaultable": {
        "zh": "「{name}」没有默认这一说:每个用到它的地方都要点名用哪一家。",
        "en": "“{name}” has no default: every place that uses it names the provider itself.",
    },
    "capErr_unknown": {"zh": "没有叫「{name}」的实现,或者它不是你的连接", "en": "There's no provider “{name}”, or it isn't your connection."},
    "capErr_incomplete": {"zh": "「{plugin}」还没配好:缺 {missing}", "en": "“{plugin}” isn't set up yet: missing {missing}."},
    "capErr_ambiguous": {"zh": "配好了几家({names}),请在「设置 → 能力提供方」里定用哪一家", "en": "Several are set up ({names}); choose one under Settings → Capability providers."},
    "capErr_outdated": {"zh": "「{plugin}」版本太旧,请到插件页更新", "en": "“{plugin}” is out of date; update it on the Plugins page."},
    "capMissing_permissions": {"zh": "插件权限(到插件页授予)", "en": "plugin permissions (grant them on the Plugins page)"},
    "docParser_local": {"zh": "本地解析", "en": "Local parsing"},
    "docErr_interruptedByRestart": {"zh": "解析到一半应用重启了,点「重新解析」再来一次", "en": "The app restarted mid-parse; choose Parse again to retry."},
    "docErr_notParsedYet": {"zh": "「{name}」还没解析好,等解析完再存成笔记", "en": "“{name}” hasn't been parsed yet; save it as a note once parsing is done."},
    "docErr_assetNotFound": {"zh": "这个工作区里没有素材 {asset_id}", "en": "There's no asset {asset_id} in this workspace."},
    "docErr_parseStoppedForRead": {
        "zh": "「{name}」的解析被停下了,还没有可读的正文:在文档详情里点「重新解析」",
        "en": "Parsing “{name}” was stopped, so there's no text to read yet: choose Re-parse on the document",
    },
    "docErr_stillParsing": {"zh": "「{name}」还在解析,过一会儿再读", "en": "“{name}” is still being parsed; read it again in a moment."},
    "docErr_parseFailedForRead": {"zh": "「{name}」没解析成:{error}。在素材详情里点「重新解析」(可以换一家)", "en": "“{name}” couldn't be parsed: {error}. Use Parse again in the asset details (you can pick another parser)."},
    "docErr_noPageImagesToLook": {"zh": "「{name}」没有页面图:PDF 总有;Word / PPT 要本机装了 LibreOffice 才有。先用 read_document 读文字", "en": "“{name}” has no page images: PDFs always do; Word and PowerPoint need LibreOffice on this computer. Read its text with read_document first."},
    "docErr_pageOutOfRange": {"zh": "页码要在 1–{total} 之间", "en": "Page numbers must be between 1 and {total}."},
    "docErr_pluginFailed": {"zh": "「{plugin}」没解析成:{detail}", "en": "“{plugin}” couldn't parse it: {detail}"},
    "docErr_pluginBadOutput": {"zh": "解析插件交回的结果不对({detail}):请更新这个插件", "en": "The parser plugin returned something unexpected ({detail}); update the plugin."},
    "docErr_notDocument": {"zh": "「{name}」不是文档,不用解析", "en": "“{name}” isn't a document; there's nothing to parse."},
    "docErr_fileMissing": {"zh": "「{name}」的文件不在了,解析不了", "en": "The file of “{name}” is missing, so it can't be parsed."},
    "docErr_unreadable": {"zh": "这份文档读不了(文件坏了,或者加了密码):{detail}", "en": "This document can't be read (it's damaged or password-protected): {detail}"},
    "docErr_formatNotSupported": {"zh": "本地解析还不认 .{ext}", "en": "Local parsing doesn't handle .{ext} yet."},
    "docErr_legacyNeedsLibreOffice": {"zh": "老格式 .{ext} 要先转成新格式:装上 LibreOffice 后重新解析,或者另存为新格式再导入", "en": "The old .{ext} format needs converting first: install LibreOffice and parse again, or save it in the new format and import that."},
    "docNote_littleText": {"zh": "抽出来的字很少,可能是扫描件或图片版:可以换 MinerU 这类插件做 OCR 解析", "en": "Very little text came out — it may be scanned or image-only. A plugin such as MinerU can OCR it."},
    "docNote_pageImagesCapped": {"zh": "页数太多,只渲了前 200 页的页面图(文字全抽了)", "en": "Too many pages: page images cover the first 200 pages (all the text is extracted)."},
    "docNote_noPageImages": {"zh": "装上 LibreOffice 能看到每一页的版式(智能体也能看图);现在只有文字和插图", "en": "Install LibreOffice to see each page's layout (the agent can look at it too); for now there's text and embedded images only."},
    "docNote_tableTruncated": {"zh": "表格太大,只取了前 2000 行、40 列", "en": "The table is large; only the first 2000 rows and 40 columns are kept."},
    "docErr_noParser": {"zh": "没有可用的文档解析", "en": "No document parser is available."},
    "docErr_parserIncomplete": {"zh": "文档解析用的「{plugin}」还没配好:缺 {missing}。去插件页补上,或在「设置 → 能力提供方」里换回本地解析", "en": "“{plugin}”, set for document parsing, isn't set up yet: missing {missing}. Complete it on the Plugins page, or switch back to local parsing under Settings → Capability providers."},
    "docErr_parserAmbiguous": {"zh": "配好了几家文档解析({names}),请在「设置 → 能力提供方」里定用哪一家", "en": "Several document parsers are set up ({names}); choose one under Settings → Capability providers."},
    "docErr_parserOutdated": {"zh": "文档解析用的「{plugin}」版本太旧,请到插件页更新", "en": "“{plugin}”, set for document parsing, is out of date; update it on the Plugins page."},
    "assetErr_unsupportedFileType": {"zh": "素材库不收「{name}」这种文件:能导入的是图片、视频、音频,和 PDF、Word、PPT、Excel、CSV、Markdown、TXT、网页、EPUB 文档", "en": "The library can't take “{name}”: you can import images, video, audio, and PDF, Word, PowerPoint, Excel, CSV, Markdown, text, web page and EPUB documents."},
    "assetErr_otherWorkspace": {"zh": "这份素材不属于当前工作区", "en": "This asset doesn't belong to the current workspace."},
    "assetErr_beingPublished": {
        "zh": "「{name}」还在发布到「{account}」:等它发完,或先在发布页取消那条任务,再删",
        "en": "“{name}” is still being published to “{account}”. Wait for it to finish, or cancel that task on the Publish page, then delete it.",
    },
    "assetErr_wrongKindForPlugin": {"zh": "「{name}」不是这里要的素材:要{kinds}", "en": "“{name}” isn't the kind of asset needed here: expected {kinds}."},
    "assetErr_badCursor": {"zh": "翻页位置不对:它不是这份列表(这种排序)给的,请从第一页重新取", "en": "That page position doesn't belong to this list (or this sort order); fetch from the first page again."},
    "assetErr_unknownSort": {"zh": "不认得的排序「{sort}」:可选 created、updated、name、duration", "en": "Unknown sort “{sort}”: use created, updated, name or duration."},
    "assetErr_unknownIntermediate": {"zh": "不认得的中间产物「{kind}」:可选 dub_line(配音片段)、lipsync_chunk(对口型分块)", "en": "Unknown intermediate “{kind}”: use dub_line (dub lines) or lipsync_chunk (lip-sync chunks)."},
    "assetErr_unknownTagMatch": {"zh": "不认得的标签匹配方式「{match}」:可选 all(同时带有)、any(带有任一)", "en": "Unknown tag match “{match}”: use all or any."},
    "assetKind_image": {"zh": "图片", "en": "an image"},
    "assetKind_video": {"zh": "视频", "en": "a video"},
    "assetKind_audio": {"zh": "音频", "en": "audio"},
    "assetKind_document": {"zh": "文档", "en": "a document"},
    "assetErr_noFileYet": {
        "zh": "素材 {name} 还没有文件(可能仍在生成中)",
        "en": "Asset {name} has no file yet (it may still be generating).",
    },
    "assetErr_fileLost": {"zh": "素材 {name} 的文件已丢失", "en": "The file for asset {name} is missing."},
    "gifErr_notVideo": {"zh": "只有视频素材可以转换为 GIF", "en": "Only video assets can be converted to GIF."},
    "gifErr_noLocalFile": {"zh": "视频素材没有本地文件", "en": "The video asset has no local file."},
    "gifErr_badParams": {"zh": "GIF 参数超出允许范围", "en": "The GIF settings are out of the allowed range."},
    "gifErr_fileMissing": {"zh": "视频素材文件不存在", "en": "The video file is missing."},
}

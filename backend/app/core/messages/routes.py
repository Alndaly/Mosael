"""后端文案 · 路由层的报错(分区 B1)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- B1 · 02_routes ----
    "routeErr_internal": {
        "zh": "后端出错了,这次操作没有完成。错误已记进后端日志;重试一次,还不行就把日志发给开发者。",
        "en": "The backend hit an error and this action didn't complete. It's in the backend log — try again, and if it keeps failing, send the log to the developers.",
    },
    "routeErr_accountNotFound": {
        "zh": "账号不存在",
        "en": "Account not found.",
    },
    "routeErr_currentPasswordWrong": {
        "zh": "当前密码不对",
        "en": "The current password is incorrect.",
    },
    "routeErr_publishAccountNotInWorkspace": {
        "zh": "这个工作区里没有这个发布账号",
        "en": "This publishing account isn't in this workspace.",
    },
    "routeErr_assetNotInWorkspace": {
        "zh": "这个工作区里没有这个素材",
        "en": "This asset isn't in this workspace.",
    },
    "routeErr_extractionNotFinished": {
        "zh": "这份文档还没解析完",
        "en": "This document hasn't finished parsing yet.",
    },
    "routeErr_resetOwnPassword": {
        "zh": "改自己的密码在「设置 → 账户」里(要输入当前密码);在这里重置会把你自己踢下线",
        "en": "Change your own password in Settings → Account (it asks for the current one); resetting it here would sign you out.",
    },
    "routeErr_aiConnectionNotFound": {
        "zh": "这条 AI 供应商连接不存在",
        "en": "This AI provider connection doesn't exist.",
    },
    "routeErr_badAnalysisVideoMode": {
        "zh": "analysis_video_mode 只能是 auto/native/frames",
        "en": "analysis_video_mode must be auto, native, or frames.",
    },
    "routeErr_badThinkingLevel": {
        "zh": "thinking_level 只能是 off/low/medium/high",
        "en": "thinking_level must be off, low, medium, or high.",
    },
    "sessionGroupErr_notFound": {
        "zh": "分组不存在",
        "en": "Group not found.",
    },
    "agentErr_sessionAllowTier": {
        "zh": "「{tool}」的「{permission}」这一档不能设成本会话始终允许 —— 只有 {allowed} 这几档可以;撤不回的操作每次都要人确认",
        "en": "“{tool}” at the “{permission}” tier cannot be always-allowed for this session — only {allowed} can; irreversible actions ask every time.",
    },
    "agentErr_sessionAllowUnknownTool": {
        "zh": "没有需要确认的工具叫「{tool}」,不能加进本会话始终允许",
        "en": "There is no confirmation tool called “{tool}” to always allow.",
    },
    "agentErr_sessionAllowAlwaysAsks": {
        "zh": "「{tool}」每一次都要人确认,不能加进本会话始终允许",
        "en": "“{tool}” asks every time; it can't be always-allowed for this session.",
    },
    "agentErr_badPermissionMode": {
        "zh": "permission_mode 只能是 {modes}",
        "en": "permission_mode must be one of {modes}.",
    },
    "agentErr_sharedSessionNoBypass": {
        "zh": "共享会话(如飞书)不能开 bypass —— 它不该由一个人替一群人开",
        "en": "Shared sessions (such as Feishu) can't use bypass — one person shouldn't turn it on for a whole group.",
    },
    "routeErr_questionNotFound": {
        "zh": "问题不存在",
        "en": "Question not found.",
    },
    "routeErr_nothingToRead": {
        "zh": "没有要念的内容",
        "en": "There is nothing to read aloud.",
    },
    "routeErr_browserSessionNotFound": {
        "zh": "浏览器会话不存在",
        "en": "Browser session not found.",
    },
    "routeErr_providerNotFound": {
        "zh": "供应商不存在",
        "en": "Provider not found.",
    },
    "routeErr_leaseSuperseded": {
        "zh": "租约已被顶替,续租失败",
        "en": "The lease was taken over by someone else, so it couldn't be renewed.",
    },
    "routeErr_pluginToolUnavailable": {
        "zh": "插件工具 {name} 不可用(连接未启用、未授权、缺凭据,或该工具未开启)",
        "en": "Plugin tool {name} is unavailable (the connection is disabled, unauthorized, missing credentials, or the tool is turned off).",
    },
    "routeErr_pluginToolNeedsWorkspace": {
        "zh": "插件工具 {name} 要先经你确认,而确认卡得开在某个工作区里 —— 请带上 workspace_id",
        "en": "Plugin tool {name} needs your approval first, and the approval card has to live in a workspace — pass workspace_id.",
    },
    "routeErr_pluginCallFailed": {
        "zh": "插件调用失败",
        "en": "The plugin call failed.",
    },
    "routeErr_toolArgsNone": {
        "zh": "(无)",
        "en": "(none)",
    },
    "routeErr_toolBadArgs": {
        "zh": "{detail};该工具接受的参数:{accepted}",
        "en": "{detail}; this tool accepts: {accepted}",
    },
    "routeErr_unknownModel": {
        "zh": "未知模型",
        "en": "Unknown model.",
    },
    "routeErr_dictationTooLarge": {
        "zh": "录音太大了,听写请说短一点。",
        "en": "The recording is too large. Keep dictation shorter.",
    },
    "routeErr_noAudio": {
        "zh": "没有收到音频",
        "en": "No audio was received.",
    },
    "routeErr_pathNotFile": {
        "zh": "路径不存在或不是文件",
        "en": "The path doesn't exist or isn't a file.",
    },
    "routeErr_unsupportedFileType": {
        "zh": "不支持的文件类型:{suffix}",
        "en": "Unsupported file type: {suffix}",
    },
    "assetErr_projectNotInWorkspace": {
        "zh": "项目不存在或不属于该工作区",
        "en": "The project doesn't exist or isn't in this workspace.",
    },
    "analysisErr_assetNotInAgentWorkspace": {
        "zh": "素材不属于当前智能体会话的工作区",
        "en": "The asset isn't in this agent session's workspace.",
    },
    "assetErr_framesOnlyFromVideo": {
        "zh": "只能从视频里取帧",
        "en": "Frames can only be taken from a video.",
    },
    "routeErr_noProxyForAsset": {
        "zh": "该素材不支持生成预览代理",
        "en": "This asset doesn't support a preview proxy.",
    },
    "routeErr_inviteCodeUnusable": {
        "zh": "这个邀请码用不了:可能抄错了、已经有人用过,或者过了 7 天有效期。请向管理员要一个新的",
        "en": "This invite code can't be used: it may be mistyped, already used, or past its 7-day validity. Ask an administrator for a new one.",
    },
    "routeErr_jobRetentionChoice": {
        "zh": "任务保留只能选 90 天、180 天、365 天或永久",
        "en": "Task retention can only be 90, 180 or 365 days, or forever.",
    },
    "routeErr_webUrlScheme": {
        "zh": "网页地址要以 https:// 或 http:// 开头,例如 https://studio.example.com",
        "en": "The web address has to start with https:// or http://, e.g. https://studio.example.com.",
    },
    "routeErr_inviteLinkNeedsDeploymentAdmin": {
        "zh": "这台 Mosael 只收受邀的人:这张链接能让已有账号的人加入工作区,注册要部署管理员放行。请找发链接的人,或者部署管理员",
        "en": "This Mosael only accepts invited people: this link lets existing accounts join the workspace, but signing up needs a deployment administrator's approval. Ask whoever sent the link, or a deployment administrator.",
    },
    "routeErr_signupClosed": {
        "zh": "这个部署不开放自助注册,请向管理员要一个邀请码",
        "en": "This deployment doesn't allow self sign-up. Ask an administrator for an invite code.",
    },
    "routeErr_lastDeploymentAdmin": {
        "zh": "这是最后一个部署管理员,收回之后没人能管这个部署了",
        "en": "This is the last deployment administrator; revoking it would leave nobody able to manage this deployment.",
    },
    "routeErr_avatarType": {
        "zh": "仅支持 PNG / JPEG / WebP 图片",
        "en": "Only PNG, JPEG, or WebP images are supported.",
    },
    "routeErr_emptyFile": {
        "zh": "空文件",
        "en": "The file is empty.",
    },
    "routeErr_avatarTooLarge": {
        "zh": "头像不能超过 4MB",
        "en": "The avatar must be 4 MB or smaller.",
    },
    "routeErr_browserProfileNotFound": {
        "zh": "浏览器档案不存在",
        "en": "Browser profile not found.",
    },
    "routeErr_commentNotFound": {
        "zh": "评论不存在",
        "en": "Comment not found.",
    },
    "routeErr_denoiseEngineNotInstallable": {
        "zh": "这个降噪引擎不需要安装,或者不存在",
        "en": "This noise-reduction engine doesn't need installing, or doesn't exist.",
    },
    "routeErr_badGenerationKind": {
        "zh": "kind 只能是 image 或 video",
        "en": "kind must be image or video.",
    },
    "routeErr_jobNotFound": {
        "zh": "job 不存在",
        "en": "Job not found.",
    },
    "routeErr_noteSourceNotFound": {
        "zh": "来源不存在",
        "en": "Source not found.",
    },
    "noteErr_trashFirst": {
        "zh": "请先将笔记移入回收站",
        "en": "Move the note to the trash first.",
    },
    "noteErr_changedBeforeDelete": {
        "zh": "笔记状态已变化，请重新载入后再删除",
        "en": "The note has changed. Reload it before deleting.",
    },
    "routeErr_noteVersionNotFound": {
        "zh": "版本不存在",
        "en": "Version not found.",
    },
    "routeErr_noNotifiableMembers": {
        "zh": "该工作区没有可通知的成员",
        "en": "This workspace has no members to notify.",
    },
    "routeErr_loginMethodNotConfigured": {
        "zh": "该登录方式未配置",
        "en": "This sign-in method isn't configured.",
    },
    "oauthLogin_expired": {
        "zh": "登录请求已过期或不匹配,请回到 Mosael 重试。",
        "en": "The sign-in request expired or doesn't match. Go back to Mosael and try again.",
    },
    "oauthLogin_deniedPage": {
        "zh": "授权被拒绝,可以关闭本页。",
        "en": "Authorization was denied. You can close this page.",
    },
    "oauthLogin_denied": {
        "zh": "授权被拒绝:{detail}",
        "en": "Authorization was denied: {detail}",
    },
    "oauthLogin_noCode": {
        "zh": "提供方未返回授权码",
        "en": "The provider didn't return an authorization code.",
    },
    "oauthLogin_noCodePage": {
        "zh": "提供方未返回授权码,请回到 Mosael 重试。",
        "en": "The provider didn't return an authorization code. Go back to Mosael and try again.",
    },
    "oauthLogin_failedPage": {
        "zh": "登录失败,请回到 Mosael 查看原因。",
        "en": "Sign-in failed. Go back to Mosael to see why.",
    },
    "oauthLogin_codePageLead": {
        "zh": "快好了。回到 Mosael,把这个确认码填进去:",
        "en": "Almost done. Go back to Mosael and enter this confirmation code:",
    },
    "oauthLogin_codePageWarning": {
        "zh": "如果不是你自己刚在 Mosael 里点的「用 Google / Apple 登录」,别把这个码告诉任何人,直接关掉本页 —— 什么都不会发生。",
        "en": "If you didn't just click “Continue with Google / Apple” in Mosael yourself, don't share this code with anyone; "
              "just close this page and nothing will happen.",
    },
    "oauthLogin_tooManyWrongCodes": {
        "zh": "确认码填错太多次,这次登录已作废。重新点一次登录即可。",
        "en": "Too many wrong confirmation codes, so this sign-in was cancelled. Start the sign-in again.",
    },
    "oauthLogin_tokenExchangeFailed": {
        "zh": "换取令牌失败:{detail}",
        "en": "Could not exchange the token: {detail}",
    },
    "oauthLogin_badIdToken": {
        "zh": "id_token 无法解析",
        "en": "The id_token couldn't be parsed.",
    },
    "oauthLogin_noSubject": {
        "zh": "提供方未返回用户标识(sub)",
        "en": "The provider didn't return a user identifier (sub).",
    },
    "routeErr_pluginConnectionNotFound": {
        "zh": "插件接入不存在",
        "en": "Plugin connection not found.",
    },
    "routeErr_modelPreviewNotFound": {
        "zh": "这个模型没有预览图",
        "en": "This model has no preview image.",
    },
    "pluginErr_oauthTokenExchangeFailed": {
        "zh": "换令牌失败:{detail}",
        "en": "Could not exchange the token: {detail}",
    },
    "routeErr_modelFileGone": {
        "zh": "模型文件已不在,请重新导入。",
        "en": "The model file is gone. Import it again.",
    },
    "routeErr_unknownSeparationEngine": {
        "zh": "未知的分离引擎",
        "en": "Unknown separation engine.",
    },
    "genErr_paramGroupNotFound": {
        "zh": "这条连接下没有这个参数组",
        "en": "This connection has no such parameter group.",
    },
    "genErr_paramGroupNameRequired": {
        "zh": "给这份参数组起个名字",
        "en": "Give this parameter group a name.",
    },
    "genErr_paramGroupNameTaken": {
        "zh": "这条连接下已经有同名的参数组了",
        "en": "This connection already has a parameter group with that name.",
    },
    "genErr_paramGroupInUse": {
        "zh": "还有 {count} 个模型在使用这份参数模板，请先改回跟随目录",
        "en": "{count} model(s) still use this parameter template. Switch them back to following the catalog first.",
    },
    "routeErr_unknownCapability": {
        "zh": "未知能力",
        "en": "Unknown capability.",
    },
    "routeErr_modelLacksCapability": {
        "zh": "该模型不提供 {capability} 能力",
        "en": "This model doesn't provide the {capability} capability.",
    },
    "routeErr_modelIdRequired": {
        "zh": "模型 id 不能为空",
        "en": "Model id can't be empty.",
    },
    "routeErr_modelNotInConnection": {
        "zh": "该连接下没有这个模型",
        "en": "This connection has no such model.",
    },
    "routeErr_notSubscriptionPlan": {
        "zh": "该供应商不是订阅计划,不需要授权登录",
        "en": "This provider isn't a subscription plan, so it doesn't need a sign-in.",
    },
    "routeErr_loginSessionEnded": {
        "zh": "登录会话已结束",
        "en": "The sign-in session has ended.",
    },
    "routeErr_loginStepNotWaiting": {
        "zh": "这一步已经不在等待作答了",
        "en": "This step is no longer waiting for an answer.",
    },
    "routeErr_tokenRefreshFailed": {
        "zh": "令牌刷新失败:{detail}",
        "en": "Token refresh failed: {detail}",
    },
    "routeErr_pricingNeedsKey": {
        "zh": "这条连接还没有你的密钥,先填一把再来取目录报价",
        "en": "This connection doesn't have your key yet. Add one before fetching catalog prices.",
    },
    # 预填出来的规则备注。存进库里的是翻好的句子(备注本来就是给人看、可直接改的自由文本),
    # 按点「预填」那一刻的界面语言。
    "pricingNote_catalog": {
        "zh": "按供应商模型目录的报价预填,可直接改",
        "en": "Prefilled from the provider's model catalog. Edit freely.",
    },
    "pricingNote_reference": {
        "zh": "官方价目{region}{remark} · {source} · 查证于 {checked}",
        "en": "Official list price{region}{remark} · {source} · checked {checked}",
    },
    "pricingNote_referenceRelay": {
        "zh": "原厂({vendor})官方价目,中转站实际收费可能不同{region}{remark} · {source} · 查证于 {checked}",
        "en": "Original vendor ({vendor}) list price; the relay may charge differently{region}{remark} · {source} · checked {checked}",
    },
    "pricingRegion_cn": {
        "zh": "(中国内地)",
        "en": " (mainland China)",
    },
    "pricingRegion_intl": {
        "zh": "(国际站)",
        "en": " (international)",
    },
    # 分时段价格的校验(domain/billing/price_schedule)。时段按界面上的顺序从 1 数。
    "pricingErr_timeZoneRequired": {
        "zh": "分时段价格需要选一个时区",
        "en": "Time-of-day prices need a time zone.",
    },
    "pricingErr_timeZone": {
        "zh": "不认识的时区:{zone}",
        "en": "Unknown time zone: {zone}",
    },
    "pricingErr_windowClock": {
        "zh": "第 {index} 个时段的时间要写成「时:分」,如 09:30",
        "en": "Time slot {index} needs times written as HH:MM, e.g. 09:30.",
    },
    "pricingErr_windowEmpty": {
        "zh": "第 {index} 个时段的开始和结束是同一时刻",
        "en": "Time slot {index} starts and ends at the same time.",
    },
    "pricingErr_windowWeekdays": {
        "zh": "第 {index} 个时段的星期写得不对",
        "en": "Time slot {index} has invalid weekdays.",
    },
    "pricingErr_windowAmount": {
        "zh": "第 {index} 个时段的单价不能为负",
        "en": "Time slot {index} needs a non-negative price.",
    },
    "pricingErr_windowOverlap": {
        "zh": "第 {first} 个和第 {second} 个时段有重叠 —— 同一时刻只能有一个价",
        "en": "Time slots {first} and {second} overlap; a moment can only have one price.",
    },
    "routeErr_providerLacksCapability": {
        "zh": "该供应商不支持 {capability} 能力",
        "en": "This provider doesn't support the {capability} capability.",
    },
    "providerErr_unknownVendor": {
        "zh": "没有这家供应商:{vendor}",
        "en": "There is no provider called {vendor}.",
    },
    "providerErr_missingRequiredConfig": {
        "zh": "缺少必要配置: {fields}",
        "en": "Missing required settings: {fields}",
    },
    "routeErr_onlyOwnerCanShare": {
        "zh": "只有它的主人可以共享或收回",
        "en": "Only its owner can share it or stop sharing it.",
    },
    "routeErr_assetNotFound": {
        "zh": "素材不存在",
        "en": "Asset not found.",
    },
    "routeErr_previewCloneUsesSample": {
        "zh": "本地克隆的音色,试听它的参考录音就是它",
        "en": "For a cloned voice, its reference recording is the preview.",
    },
    "routeErr_voiceNotFound": {
        "zh": "音色不存在",
        "en": "Voice not found.",
    },
    "routeErr_referenceAudioMissing": {
        "zh": "参考音频缺失",
        "en": "The reference audio is missing.",
    },
    "routeErr_noSuchModel": {
        "zh": "没有这个模型",
        "en": "No such model.",
    },
    "routeErr_ttsSettingsNotApplied": {
        "zh": "TTS 设置没有生效({detail})。改动已写入数据库,但这个进程读到的仍是旧值 —— 请检查后端日志。",
        "en": "The TTS settings didn't take effect ({detail}). The change was saved to the database, but this process still reads the old values — check the backend logs.",
    },
    "routeErr_unknownEngine": {
        "zh": "未知引擎",
        "en": "Unknown engine.",
    },
    "routeErr_workflowTemplateAndGraph": {
        "zh": "创建工作流时不能同时提交模板和自定义图",
        "en": "When creating a workflow, send either a template or a custom graph, not both.",
    },
    "routeErr_workflowRevisionNotFound": {
        "zh": "工作流修订不存在",
        "en": "Workflow revision not found.",
    },
    "routeErr_workflowRunOutputNotFound": {
        "zh": "这次运行没有存下这个输出的全文",
        "en": "This run has no full text stored for that output.",
    },
    "routeErr_judgeHostCodeNeedsAdmin": {
        "zh": "把「本机执行代码」交给判断者需要这台机器的管理员权限 —— 代码在本机不隔离地跑,承担风险的是这台机器的主人",
        "en": "Letting the judge approve \"run code on this machine\" requires admin rights on this machine — the code runs unsandboxed here, and the risk falls on the machine's owner.",
    },
    "routeErr_poemUnreachable": {
        "zh": "今日诗词暂时不可达:{detail}",
        "en": "The daily poem service is unreachable right now: {detail}",
    },
}

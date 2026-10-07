"""后端文案 · 智能体确认卡上的可确认操作(分区 B1)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- B1 · 03_confirmable ----
    "confirmErr_noActor": {"zh": "这张卡没有能替谁做的人(账号已经不在了)", "en": "There's no one to act for on this card (the account is gone)."},
    # ---- 智能体改技能(ADR 0043) ----
    "confirm_createSkill": {"zh": "新建技能「{title}」({name}){warning}", "en": "Create the skill “{title}” ({name}){warning}"},
    "confirm_updateSkill": {
        "zh": "修改技能「{title}」:{count} 个文件有改动({paths}){warning}",
        "en": "Change the skill “{title}”: {count} file(s) change ({paths}){warning}",
    },
    "confirm_copySkill": {
        "zh": "把「{source}」复制成这个工作区的技能「{name}」{warning}",
        "en": "Copy “{source}” into this workspace's skills as “{name}”{warning}",
    },
    "confirm_enableSkill": {
        "zh": "启用技能「{title}」—— 以后这个工作区里的智能体会照它做事{warning}",
        "en": "Turn on the skill “{title}” — the agent in this workspace will follow it from now on{warning}",
    },
    "confirm_disableSkill": {"zh": "关掉技能「{title}」{warning}", "en": "Turn off the skill “{title}”{warning}"},
    "confirm_deleteSkill": {
        "zh": "永久删除技能「{title}」({files} 个文件,{size})—— 删了就没了{warning}",
        "en": "Permanently delete the skill “{title}” ({files} files, {size}) — it can't be recovered{warning}",
    },
    "confirm_importSkill": {
        "zh": "从 {source} 导入 {count} 个技能:{names}{warning}",
        "en": "Import {count} skill(s) from {source}: {names}{warning}",
    },
    #: 卡上单独成行的那句(见 confirmations.card_parts):一份技能里写着「把你自己改成……」时,人一眼看得出来。
    "confirm_skillInUse": {
        "zh": "  ⚠️ 这是在用技能{skills}时提出的",
        "en": "  ⚠️ Proposed while following the skill {skills}",
    },
    "confirmErr_unknownChoice": {
        "zh": "这张卡上没有这几个开关:{keys}",
        "en": "This card has no such switches: {keys}",
    },
    "confirmErr_timelineOpFails": {
        "zh": "第 {index} 条时间线操作({kind})照现在的时间线做不了:{reason}。没有开卡,改好这一条再提交",
        "en": "Timeline operation #{index} ({kind}) can't be done on the timeline as it is now: {reason}. No card was opened; fix it and send again.",
    },
    "confirmErr_boardNotInWorkspace": {
        "zh": "这个工作区里没有这张画板",
        "en": "This workspace has no such board.",
    },
    "confirmErr_editBoardNeedsOps": {
        "zh": "edit_board 需要一个非空的 operations 列表",
        "en": "edit_board needs a non-empty operations list.",
    },
    "confirmErr_unknownBoardOp": {
        "zh": "不支持的画板算子:{kind}",
        "en": "Unsupported board operation: {kind}",
    },
    "confirmErr_runBoardItemNotTool": {
        "zh": "「{item_id}」上没有能替人跑的这一项:智能体能跑的是一格的能力(带上 producer,见 list_board_producers 里 role 为 ability 的)、空格子上的生成器和 3D 场景格的渲白模;内置的生成、写字、配音由用户在面板上发起",
        "en": "“{item_id}” has nothing the agent can run this way. The agent can run an item's abilities (pass producer; see the role \"ability\" entries of list_board_producers), a generator set on an empty slot, and a 3D scene item's render; built-in generate, write and voice-over are started by the user from their panel.",
    },
    "confirmErr_workflowChangedSinceCard": {
        "zh": "开卡之后工作流「{name}」被改过(开卡时是第 {opened} 版,现在是第 {now} 版),这张卡批准的不是现在这张图,没有运行 —— 请重新发起",
        "en": "Workflow “{name}” was changed after this card was opened (it was revision {opened}, now {now}), so the card does not cover the current graph and nothing was run. Please ask again.",
    },
    "confirmErr_workflowGone": {
        "zh": "这张卡要运行的工作流已经被删除了",
        "en": "The workflow this card would run has been deleted.",
    },
    "confirmErr_boardItemChanged": {
        "zh": "开卡之后「{item_id}」换了产出方式,这张卡批准的不是现在这一个 —— 请重新发起",
        "en": "“{item_id}” switched to a different producer after this card was opened, so the card no longer covers it. Please ask again.",
    },
    "confirmErr_pluginToolUnavailable": {
        "zh": "插件工具 {name} 不在你的工具表里(连接是别人接的、已停用、未授权、缺凭据,或该工具未开启)",
        "en": "Plugin tool {name} is not among your tools (the connection belongs to someone else, or it is disabled, unauthorized, missing credentials, or the tool is turned off).",
    },
    "confirmErr_pluginToolBadInput": {
        "zh": "插件工具 {name} 的参数不对:{detail}",
        "en": "The arguments for plugin tool {name} are wrong: {detail}",
    },
    "confirmErr_pluginToolFailed": {
        "zh": "插件工具 {name} 没跑成:{detail}",
        "en": "Plugin tool {name} did not run: {detail}",
    },
    "confirmErr_noApprover": {
        "zh": "这张卡没有记下是谁批准的,不知道该用谁的身份运行",
        "en": "This card has no approver on record, so there is no one to run it as.",
    },
    "confirmErr_blenderLocalOnly": {
        "zh": "Blender 建模只在本机桌面版可用 —— Blender 要和 Mosael 跑在同一台电脑上。",
        "en": "Blender modeling is only available in the local desktop app — Blender must run on the same computer as Mosael.",
    },
    "confirmErr_blenderNoCode": {
        "zh": "没有要在 Blender 里执行的代码",
        "en": "There is no code to run in Blender.",
    },
    "confirmErr_approverNotFound": {
        "zh": "找不到批准这次操作的用户",
        "en": "The user who approved this action can't be found.",
    },
    "confirmErr_blenderCodeFailed": {
        "zh": "Blender 里的代码出错了:\n{detail}",
        "en": "The code failed in Blender:\n{detail}",
    },
    "confirmErr_notAList": {
        "zh": "{key} 要是一个列表",
        "en": "{key} must be a list.",
    },
    "confirmErr_nothingToDelete": {
        "zh": "{key} 是空的:没有要删的东西",
        "en": "{key} is empty: there is nothing to delete.",
    },
    "confirmErr_tooManyToDelete": {
        "zh": "一次最多删 {limit} 个,分几次来 —— 卡上列不下的话,批准的人并不知道自己批了什么",
        "en": "Delete at most {limit} at a time; split it up — if the card can't list them all, the approver doesn't know what they're approving.",
    },
    "confirmErr_missingAssets": {
        "zh": "这个工作区里找不到这些素材:{ids}",
        "en": "These assets aren't in this workspace: {ids}",
    },
    "confirmErr_missingProjects": {
        "zh": "这个工作区里找不到这些项目:{ids}",
        "en": "These projects aren't in this workspace: {ids}",
    },
    "confirmErr_publishAccountNotFound": {
        "zh": "发布账号不存在",
        "en": "Publishing account not found.",
    },
    "confirmErr_assetNotFound": {
        "zh": "素材不存在",
        "en": "Asset not found.",
    },
    "confirmErr_httpOnly": {
        "zh": "只能请求 http(s) 网址",
        "en": "Only http(s) URLs can be requested.",
    },
    "confirmErr_browserHttpOnly": {
        "zh": "浏览器只能打开 http(s) 网址",
        "en": "The browser can only open http(s) URLs.",
    },
    "confirmErr_projectIdNotSequence": {
        "zh": "「{id}」是项目「{project}」的 id,不是时间线的。它的时间线(sequence_id):{timelines}",
        "en": "“{id}” is the id of the project “{project}”, not of a timeline. Its timelines (sequence_id): {timelines}",
    },
    "confirmErr_projectHasNoTimeline": {
        "zh": "「{id}」是项目「{project}」的 id,不是时间线的;这个项目还没有时间线 —— 先用 create_project(project_id=\"{id}\", name=…) 建一条。",
        "en": "“{id}” is the id of the project “{project}”, not of a timeline, and that project has no timeline yet — create one with create_project(project_id=\"{id}\", name=…).",
    },
    "confirmErr_speechNeedsText": {
        "zh": "配音要有一段要念的文字(text)",
        "en": "Speech needs some text to read (text).",
    },
    "confirmErr_badLine": {
        "zh": "line 只能是 all / first / last",
        "en": "line must be all, first, or last.",
    },
    "confirmErr_clipIdsNotArray": {
        "zh": "clip_ids 要是一个数组(留空表示整条字幕轨)",
        "en": "clip_ids must be an array (leave it empty for the whole subtitle track).",
    },
    "confirmErr_badOriginalAudio": {
        "zh": "original_audio 只能是 {modes}",
        "en": "original_audio must be one of {modes}.",
    },
    "confirmErr_assetNotInWorkspace": {
        "zh": "这个工作区里没有这份素材",
        "en": "This workspace has no such asset.",
    },
    "confirmErr_separateNeedsAudio": {
        "zh": "只有音频或视频素材可以分离",
        "en": "Only audio or video assets can be separated.",
    },
    "confirmErr_denoiseNeedsAudio": {
        "zh": "只有音频或视频素材可以降噪",
        "en": "Only audio or video assets can have noise reduced.",
    },
    "confirmErr_videoNotInWorkspace": {
        "zh": "这个工作区里没有这份视频素材",
        "en": "This workspace has no such video asset.",
    },
    "confirmErr_parseNeedsDocument": {
        "zh": "只有文档素材(PDF、Word、PPT、Excel……)可以解析",
        "en": "Only document assets (PDF, Word, PowerPoint, Excel…) can be parsed.",
    },
    "confirmErr_unknownProvider": {
        "zh": "没有叫「{name}」的实现;配好了的有:{choices}",
        "en": "There is no provider called “{name}”; the ready ones are: {choices}",
    },
    "confirmErr_gridNeedsImage": {
        "zh": "只有图片素材可以切宫格",
        "en": "Only image assets can be split into a grid.",
    },
    "confirmErr_gifNeedsVideo": {
        "zh": "只有视频素材可以转换为 GIF",
        "en": "Only video assets can be converted to GIF.",
    },
    "confirmErr_gifBadParams": {
        "zh": "GIF 参数格式不正确",
        "en": "The GIF parameters are malformed.",
    },
    "confirmErr_gifParamsOutOfRange": {
        "zh": "GIF 参数超出允许范围",
        "en": "The GIF parameters are out of range.",
    },
    "confirm_importFromUrl": {
        "zh": "从这个链接下载{kind}进素材库{login}:{url}",
        "en": "Download {kind} from this link into the media library{login}: {url}",
    },
    "confirm_importVideo": {"zh": "视频", "en": "the video"},
    "confirm_importAudio": {"zh": "音频", "en": "the audio"},
    "confirm_importWithProfile": {
        "zh": ",借用浏览器档案「{name}」的登录态",
        "en": ", borrowing the signed-in session of browser profile \u201c{name}\u201d",
    },
}

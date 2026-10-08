"""后端文案 · 领域层的报错(分区 B1)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- B1 · 05_domain ----
    "collabErr_unknownSubjectType": {
        "zh": "不支持的协作对象类型:{kind}",
        "en": "Unsupported collaboration subject type: {kind}",
    },
    "collabErr_subjectNotFound": {
        "zh": "协作对象不存在",
        "en": "The item being discussed doesn't exist.",
    },
    "collabErr_commentEmpty": {
        "zh": "评论不能为空",
        "en": "The comment can't be empty.",
    },
    "collabErr_commentTooLong": {
        "zh": "评论最多 5000 字",
        "en": "A comment can be at most 5000 characters.",
    },
    "collabErr_moveOwnOnly": {
        "zh": "只能移动自己发布的评论",
        "en": "You can only move your own comments.",
    },
    "collabErr_moveCanvasOnly": {
        "zh": "只有画布评论支持移动",
        "en": "Only canvas comments can be moved.",
    },
    "collabErr_editOwnOnly": {
        "zh": "只能编辑自己发布的评论",
        "en": "You can only edit your own comments.",
    },
    "collabErr_commentLength": {
        "zh": "评论需要包含 1 至 5000 字",
        "en": "A comment must be 1 to 5000 characters.",
    },
    "collabErr_commentMalformed": {
        "zh": "评论格式不合法",
        "en": "The comment is malformed.",
    },
    "collabErr_deleteOwnOnly": {
        "zh": "只能删除自己发布的评论",
        "en": "You can only delete your own comments.",
    },
    "fontErr_badType": {
        "zh": "只支持 .ttf / .otf / .ttc 字体文件(woff 无法用于导出)",
        "en": "Only .ttf, .otf, or .ttc font files are supported (woff can't be used for export).",
    },
    "fontErr_tooLarge": {
        "zh": "字体文件过大(上限 32MB)",
        "en": "The font file is too large (limit 32 MB).",
    },
    "fontErr_empty": {
        "zh": "字体文件为空",
        "en": "The font file is empty.",
    },
    "fontErr_unreadable": {
        "zh": "无法解析该字体文件,请确认它没有损坏",
        "en": "The font file couldn't be read. Make sure it isn't corrupted.",
    },
    "hostCodeErr_localOnly": {
        "zh": "不隔离执行只在本机桌面版可用 —— 远程部署上「这台电脑」是服务器,不是你的电脑。",
        "en": "Running code without isolation is only available in the local desktop app — on a remote deployment, \"this computer\" is the server, not yours.",
    },
    "hostCodeErr_noPython": {
        "zh": "找不到可用的 Python 解释器。",
        "en": "No usable Python interpreter was found.",
    },
    "hostCodeErr_timeout": {
        "zh": "代码执行超时({seconds}s)",
        "en": "The code timed out after {seconds}s.",
    },
    "hostCodeErr_outputTooLarge": {
        "zh": "代码输出超过上限({limit} KiB)",
        "en": "The code output exceeds the limit ({limit} KiB).",
    },
    "hostCodeErr_failed": {
        "zh": "代码执行出错:{detail}",
        "en": "The code failed: {detail}",
    },
    "hostCodeErr_failedNoReason": {
        "zh": "代码执行出错:子进程没有留下原因",
        "en": "The code failed without giving a reason.",
    },
    "hostCodeErr_badOutput": {
        "zh": "代码输出无法解析(请把结果赋给 output 变量)",
        "en": "The code output couldn't be parsed (assign the result to the output variable).",
    },
    "jobErr_parentFinished": {
        "zh": "父任务已结束,不能再派生任务",
        "en": "The parent job has finished, so it can't start new jobs.",
    },
    "jobErr_alreadyFinished": {
        "zh": "任务已结束,无法取消",
        "en": "The job has already finished and can't be canceled.",
    },
    "jobErr_badReportStatus": {
        "zh": "未知回报状态: {status}",
        "en": "Unknown report status: {status}",
    },
    "jobErr_badLease": {
        "zh": "执行器租约无效,请使用认领返回的 lease_token",
        "en": "Invalid worker lease. Use the lease_token returned when the job was claimed.",
    },
    "lutErr_oneD": {
        "zh": "这是 1D LUT,导出仅支持 3D LUT(.cube)",
        "en": "This is a 1D LUT; export only supports 3D LUTs (.cube).",
    },
    "lutErr_badSize": {
        "zh": ".cube 的 LUT_3D_SIZE 无效",
        "en": "The .cube file has an invalid LUT_3D_SIZE.",
    },
    "lutErr_noSize": {
        "zh": "不是有效的 .cube 文件(缺少 LUT_3D_SIZE)",
        "en": "Not a valid .cube file (LUT_3D_SIZE is missing).",
    },
    "lutErr_sizeOutOfRange": {
        "zh": "LUT_3D_SIZE={size} 超出支持范围 [2, 256]",
        "en": "LUT_3D_SIZE={size} is outside the supported range [2, 256].",
    },
    "lutErr_tooFewRows": {
        "zh": "数据行不足:期望 {expected} 行,实际 {actual} 行",
        "en": "Not enough data rows: expected {expected}, found {actual}.",
    },
    "lutErr_badType": {
        "zh": "只支持 .cube 3D LUT 文件",
        "en": "Only .cube 3D LUT files are supported.",
    },
    "lutErr_tooLarge": {
        "zh": "LUT 文件过大(上限 32MB)",
        "en": "The LUT file is too large (limit 32 MB).",
    },
    "lutErr_notUtf8": {
        "zh": ".cube 必须是 UTF-8 文本",
        "en": "A .cube file must be UTF-8 text.",
    },
    "memberErr_userNotFound": {
        "zh": "没有这个用户名。对方要先有这台 Mosael 的账号:开放注册时他在登录页自己注册;仅限邀请时请部署管理员给他一个邀请码",
        "en": "No such username. They need an account on this Mosael first: with open sign-up they register on the login page; if it's invite-only, ask a deployment admin for an invite code for them.",
    },
    "memberErr_inviteSelf": {
        "zh": "不能邀请自己",
        "en": "You can't invite yourself.",
    },
    "memberErr_alreadyMember": {
        "zh": "对方已是本工作区成员",
        "en": "They're already a member of this workspace.",
    },
    "memberErr_invitePending": {
        "zh": "已经邀请过了,等对方在通知里接受;要换角色,先撤回下面那条邀请",
        "en": "Already invited — waiting for them to accept in their notifications. To change the role, revoke that invitation below first.",
    },
    "memberErr_inviteNotFound": {
        "zh": "邀请不存在",
        "en": "Invitation not found.",
    },
    "memberErr_inviteHandled": {
        "zh": "邀请已处理过",
        "en": "This invitation has already been handled.",
    },
    "memberErr_notMember": {
        "zh": "不是本工作区成员",
        "en": "Not a member.",
    },
    "memberErr_lastOwnerDemote": {
        "zh": "不能降级最后一个所有者",
        "en": "Can't demote the last owner.",
    },
    "memberErr_onlyOwnerTouchesOwner": {
        "zh": "只有所有者能授予、修改或移除所有者",
        "en": "Only an owner can grant, change or remove the owner role.",
    },
    "memberErr_lastOwnerRemove": {
        "zh": "不能移除最后一个所有者",
        "en": "Can't remove the last owner.",
    },
    "memberErr_lastDeploymentAdmin": {
        "zh": "这是最后一个部署管理员 —— 先把管理员给别人,再删这个账号。",
        "en": "This is the last deployment administrator — make someone else an administrator before deleting this account.",
    },
    "memberErr_usernameTaken": {
        "zh": "这个用户名已经有人用了。",
        "en": "That username is already taken.",
    },
    "memberErr_sharedWorkspaces": {
        "zh": "这些工作区里还有别人,不能跟着账号一起删:{names}。先转让或把他移出去。",
        "en": "Other people are still in these workspaces, so they can't be deleted with the account: {names}. Transfer them or remove those people first.",
    },
    "noteErr_notFound": {
        "zh": "笔记不存在",
        "en": "Note not found.",
    },
    "noteErr_tagTooLong": {
        "zh": "标签或专题名称不能超过 80 字",
        "en": "Tag and topic names can be at most 80 characters.",
    },
    "noteErr_projectNotFound": {
        "zh": "项目不存在",
        "en": "Project not found.",
    },
    "noteErr_sourceNotInWorkspace": {
        "zh": "引用来源不存在于当前工作区",
        "en": "The referenced source isn't in this workspace.",
    },
    "noteErr_referencedTrashed": {
        "zh": "引用的笔记已在回收站",
        "en": "The referenced note is in the trash.",
    },
    "noteErr_versionNotFound": {
        "zh": "引用版本不存在",
        "en": "The referenced version doesn't exist.",
    },
    "noteErr_changedElsewhere": {
        "zh": "笔记已被其他操作更新，请保留草稿并重新载入",
        "en": "The note was changed elsewhere. Keep your draft and reload.",
    },
    "noteErr_restoreFirst": {
        "zh": "请先从回收站恢复笔记",
        "en": "Restore the note from the trash first.",
    },
    "noteErr_referencedTrashedRestore": {
        "zh": "引用的笔记已在回收站，请先恢复笔记",
        "en": "The referenced note is in the trash. Restore it first.",
    },
    "noteErr_rangeOrder": {
        "zh": "结束时间必须晚于开始时间",
        "en": "The end time must be after the start time.",
    },
    "noteErr_badUrl": {
        "zh": "来源链接必须是有效网址",
        "en": "The source link must be a valid URL.",
    },
    "noteErr_urlScheme": {
        "zh": "来源链接必须是 http 或 https 地址",
        "en": "The source link must be an http or https URL.",
    },
    "noteErr_sourceIdEmpty": {
        "zh": "来源 ID 不能为空",
        "en": "The source ID can't be empty.",
    },
    # ---- 按段改笔记(domain/notes/passages,智能体的 edit_note):读的人多半是模型,说清怎么改对 ----
    "noteErr_passageNoOps": {
        "zh": "edit_note 需要一个非空的 operations 列表",
        "en": "edit_note needs a non-empty operations list.",
    },
    "noteErr_passageOpUnknown": {
        "zh": "第 {index} 条的 kind 只能是 replace 或 insert,收到的是 {kind}",
        "en": "Operation #{index}: kind must be replace or insert, got {kind}.",
    },
    "noteErr_passageTextMissing": {
        "zh": "第 {index} 条缺 text(新内容;要删掉一段就给空字符串)",
        "en": "Operation #{index} is missing text (the new content; use an empty string to delete a passage).",
    },
    "noteErr_passageInsertWhere": {
        "zh": "第 {index} 条 insert 要在 after(插在这段原文后面)和 before(插在前面)里恰好给一个",
        "en": "Operation #{index}: an insert needs exactly one of after (insert after this text) or before (insert before it).",
    },
    "noteErr_passageAnchorEmpty": {
        "zh": "第 {index} 条的 {field} 是空的:要给笔记里现有的一段原文",
        "en": "Operation #{index}: {field} is empty; give a passage that is in the note now.",
    },
    "noteErr_passageNotFound": {
        "zh": "第 {index} 条的 {field} 在笔记里找不到:「{excerpt}」。原文要逐字一致(含标点、空格和 Markdown 符号),先用 read_note 读出来再照抄",
        "en": "Operation #{index}: {field} is not in the note: “{excerpt}”. It must match exactly (punctuation, spaces and Markdown marks included); read_note first and copy it.",
    },
    "noteErr_passageAmbiguous": {
        "zh": "第 {index} 条的 {field} 在笔记里出现了 {count} 次,改哪一处说不清:把原文取长一点,带上前后文,让它只出现一次",
        "en": "Operation #{index}: {field} appears {count} times in the note, so which one is meant is unclear. Quote a longer passage with its surroundings so it appears only once.",
    },
    "permErr_needsEditor": {
        "zh": "你在这个工作区是「只读」,这一步要「编辑」或以上的角色。请工作区的管理员在「设置 → 团队与成员」里调整",
        "en": "You're a Viewer in this workspace; this needs Editor or above. Ask a workspace admin to change your role in Settings → Team & members.",
    },
    "permErr_needsAdmin": {
        "zh": "这一步要这个工作区的「管理员」或「所有者」来做。请找他们,或请他们在「设置 → 团队与成员」里调整你的角色",
        "en": "This needs a workspace Admin or Owner. Ask one of them, or ask them to change your role in Settings → Team & members.",
    },
    "permErr_needsOwner": {
        "zh": "这一步只有这个工作区的「所有者」能做",
        "en": "Only the workspace Owner can do this.",
    },
    "permErr_deploymentAdminOnly": {
        "zh": "这项设置属于整个部署,只有部署管理员能改",
        "en": "This setting applies to the whole deployment; only a deployment administrator can change it.",
    },
    "permErr_providerNotFound": {
        "zh": "供应商不存在",
        "en": "Provider not found.",
    },
    "permErr_providerManagedByPlugin": {
        "zh": "这条连接由插件管理,请到插件页修改",
        "en": "This connection is managed by a plugin. Change it from the Plugins page.",
    },
    "poemErr_noToken": {
        "zh": "今日诗词没有返回 token",
        "en": "The daily poem service returned no token.",
    },
    "poemErr_empty": {
        "zh": "今日诗词返回了空句子",
        "en": "The daily poem service returned an empty line.",
    },
    "poemErr_requestFailed": {
        "zh": "请求失败:{detail}",
        "en": "Request failed: {detail}",
    },
    "poemErr_unreachable": {
        "zh": "今日诗词不可达",
        "en": "The daily poem service is unreachable.",
    },
    "credLeaseErr_busy": {
        "zh": "凭据正被另一次刷新占用,请重试",
        "en": "The credential is being refreshed by another request. Try again.",
    },
    "credLeaseErr_superseded": {
        "zh": "租约已被顶替,本次刷新结果不予写入",
        "en": "The lease was taken over, so this refresh result wasn't saved.",
    },
    "credLeaseErr_expired": {
        "zh": "租约已超时,本次刷新结果不予写入",
        "en": "The lease expired, so this refresh result wasn't saved.",
    },
    "credLeaseErr_providerNotFound": {
        "zh": "供应商不存在",
        "en": "Provider not found.",
    },
    "credLeaseErr_badCredential": {
        "zh": "凭据格式无法识别(缺少 type)",
        "en": "Unrecognized credential format (missing \"type\").",
    },
    "providerHealth_credentialRejected": {
        "zh": "凭据被拒",
        "en": "Credentials rejected",
    },
    "providerErr_modelIdRequired": {
        "zh": "模型 id 不能为空",
        "en": "Model id can't be empty.",
    },
    "quotaErr_noUsageWindow": {
        "zh": "响应里没有可识别的用量窗口",
        "en": "The response has no recognizable usage window.",
    },
    "quotaErr_noQuotaWindow": {
        "zh": "响应里没有可识别的额度窗口",
        "en": "The response has no recognizable quota window.",
    },
    "quotaErr_missingField": {
        "zh": "响应缺少 {field}",
        "en": "The response is missing \"{field}\".",
    },
    "quotaErr_noQuota": {
        "zh": "响应里没有可识别的额度",
        "en": "The response has no recognizable quota.",
    },
    "quotaErr_credentialExpired": {
        "zh": "凭据已过期。在对话里发一条消息会自动刷新;仍失败请重新授权登录。",
        "en": "The credential has expired. Sending a chat message refreshes it automatically; if that still fails, sign in again.",
    },
    "quotaErr_forbidden": {
        "zh": "该账号没有访问这个额度接口的权限",
        "en": "This account isn't allowed to access this quota endpoint.",
    },
    "quotaErr_rateLimited": {
        "zh": "对方限流,稍后再试",
        "en": "Rate limited by the provider. Try again later.",
    },
    "quotaErr_notObject": {
        "zh": "响应不是对象",
        "en": "The response isn't a JSON object.",
    },
    "quotaErr_unsupported": {
        "zh": "该供应商不提供额度查询",
        "en": "This provider doesn't offer quota lookup.",
    },
    "quotaErr_notSignedIn": {
        "zh": "尚未授权登录",
        "en": "Not signed in yet.",
    },
    "quotaErr_requestFailed": {
        "zh": "查询失败:{detail}",
        "en": "Lookup failed: {detail}",
    },
    "quotaErr_unparseable": {
        "zh": "响应无法解析:{detail}",
        "en": "The response couldn't be parsed: {detail}",
    },
    "sceneErr_tooLargeGlb": {
        "zh": "模型超出上限 {limit} MB。把贴图换成 KTX2、几何用 Draco 压一下(Mosael 都能解),或者在 Blender 里隐藏用不到的物体、把贴图降到 2K。",
        "en": "The model exceeds the {limit} MB limit. Convert textures to KTX2 and compress geometry with Draco (Mosael can decode both), or hide unused objects in Blender and reduce textures to 2K.",
    },
    "sceneErr_tooLargeGlbSized": {
        "zh": "模型超出上限 {limit} MB（这份 {actual} MB）。把贴图换成 KTX2、几何用 Draco 压一下(Mosael 都能解),或者在 Blender 里隐藏用不到的物体、把贴图降到 2K。",
        "en": "The model exceeds the {limit} MB limit (this one is {actual} MB). Convert textures to KTX2 and compress geometry with Draco (Mosael can decode both), or hide unused objects in Blender and reduce textures to 2K.",
    },
    "sceneErr_tooLargeGltf": {
        "zh": "模型超出上限 {limit} MB。改导出 GLB —— 内嵌 glTF 要整份解析，所以它的上限低得多。GLB 可以到 {glbLimit} MB。也可以在 Blender 里隐藏用不到的物体、把贴图降到 2K。",
        "en": "The model exceeds the {limit} MB limit. Export GLB instead — embedded glTF has to be parsed whole, so its limit is much lower; GLB can go up to {glbLimit} MB. You can also hide unused objects in Blender and reduce textures to 2K.",
    },
    "sceneErr_tooLargeGltfSized": {
        "zh": "模型超出上限 {limit} MB（这份 {actual} MB）。改导出 GLB —— 内嵌 glTF 要整份解析，所以它的上限低得多。GLB 可以到 {glbLimit} MB。也可以在 Blender 里隐藏用不到的物体、把贴图降到 2K。",
        "en": "The model exceeds the {limit} MB limit (this one is {actual} MB). Export GLB instead — embedded glTF has to be parsed whole, so its limit is much lower; GLB can go up to {glbLimit} MB. You can also hide unused objects in Blender and reduce textures to 2K.",
    },
    "sceneErr_needsGltf2": {
        "zh": "需要 glTF 2.0 格式的模型。",
        "en": "The model must be in glTF 2.0 format.",
    },
    "sceneErr_tooDeep": {
        "zh": "模型的结构嵌套太深，无法导入。",
        "en": "The model is nested too deeply to import.",
    },
    "sceneErr_externalRefs": {
        "zh": "请导出自包含的 GLB（或把资源内嵌进 glTF）—— 模型里引用的外部文件和网址不会被读取。",
        "en": "Export a self-contained GLB (or embed resources in the glTF) — external files and URLs referenced by the model aren't read.",
    },
    "sceneErr_tooComplex": {
        "zh": "模型有 {nodes} 个节点、{meshes} 个网格，超出实时编辑的上限（5000 / 2000）。请在 Blender 里合并物体或减少细分后重试。",
        "en": "The model has {nodes} nodes and {meshes} meshes, over the real-time editing limit (5000 / 2000). Merge objects or reduce subdivision in Blender and try again.",
    },
    "sceneErr_badGlb": {
        "zh": "这不是一个有效的 GLB 文件（文件头读不通）。",
        "en": "This isn't a valid GLB file (its header can't be read).",
    },
    "sceneErr_unreadableModel": {
        "zh": "无法读取这份模型:{detail}",
        "en": "Couldn't read this model: {detail}",
    },
    "sceneErr_sceneNotFound": {
        "zh": "3D 场景不存在",
        "en": "3D scene not found.",
    },
    "sceneErr_modelNotInWorkspace": {
        "zh": "导入的模型不属于这个工作区",
        "en": "The imported model doesn't belong to this workspace.",
    },
    "sceneErr_changedKeepDraft": {
        "zh": "场景已在别处被修改。请保留草稿并重新载入后再保存。",
        "en": "Scene changed elsewhere. Keep your draft and reload before saving.",
    },
    "sceneErr_changed": {
        "zh": "场景已在别处被修改",
        "en": "Scene changed elsewhere.",
    },
    "sceneErr_usedByBoards": {
        "zh": "还有画板在用这个场景:{names}。先把它们里面的这个 3D 节点删掉。",
        "en": "Boards still use this scene: {names}. Delete the 3D node from them first.",
    },
    "sceneErr_modelNotFound": {
        "zh": "模型不存在",
        "en": "Model not found.",
    },
    "sceneErr_usedByScenes": {
        "zh": "还有场景在用这份模型:{names}。先把它们里面的这件物体删掉。",
        "en": "Scenes still use this model: {names}. Delete the object from them first.",
    },
    "sceneErr_objectOpNeedsId": {
        "zh": "每个物体操作都需要一个 id",
        "en": "Every object operation needs an id.",
    },
    "sceneErr_unknownViews": {
        "zh": "不认识的视角 {views};可选 shot、{choices}",
        "en": "Unknown view {views}; choose shot or one of {choices}",
    },
    "sceneErr_badRender": {
        "zh": "render 只能是 {choices}",
        "en": "render must be one of {choices}.",
    },
    "sceneErr_badReferenceUse": {
        "zh": "3D 参考的用法只能是 {choices}",
        "en": "A 3D reference is used as one of: {choices}.",
    },
    "sceneErr_referenceUseVideoOnly": {
        "zh": "首尾帧和运镜参考只给视频用;图片用构图参考",
        "en": "First/last frames and camera-move references are for video; images use the composition reference.",
    },
    "sceneErr_referenceRoleUnsupported": {
        "zh": "这个模型不收 {role},换一种 3D 参考的用法,或换一个收它的模型",
        "en": "This model does not accept {role}. Pick another way to use the 3D reference, or a model that accepts it.",
    },
    "sceneRef_image": {
        "zh": "参考图是 3D 场景「{name}」的白模渲染:只沿用它的构图、机位视角、人物站位和光的方向。",
        "en": "The reference image is a blockout render of the 3D scene \"{name}\": take only its composition, camera angle, where the people stand and where the light comes from.",
    },
    "sceneRef_frames": {
        "zh": "首帧和尾帧是 3D 场景「{name}」的白模渲染:只沿用构图、机位、人物站位和光的方向。",
        "en": "The first and last frames are blockout renders of the 3D scene \"{name}\": take only the composition, camera, where the people stand and where the light comes from.",
    },
    "sceneRef_video": {
        "zh": "参考视频是 3D 场景「{name}」的白模预演:只沿用它的运镜、机位节奏、构图和人物走位。",
        "en": "The reference video is a blockout previs of the 3D scene \"{name}\": take only its camera moves, pacing, composition and how the people move.",
    },
    "sceneRef_realism": {
        "zh": "白模的纯色、无材质外观只是占位 —— 成品要完整写实,每样东西都换成真实的材质、纹理与细节,不要出现灰模或未上材质的表面。",
        "en": "The flat, untextured blockout look is only a placeholder. The result must be fully realistic, with real materials, textures and detail everywhere; no grey models or untextured surfaces.",
    },
    "sceneRef_figure": {
        "zh": "白模里颜色为 {color} 的人偶是「{name}」。",
        "en": "The figure coloured {color} in the blockout is \"{name}\".",
    },
    "sceneRef_cameraMove": {"zh": "运镜:{move}。", "en": "Camera: {move}."},
    "sceneErr_pickShot": {
        "zh": "这个场景有好几个镜头({shots}),要指定渲哪一个",
        "en": "This scene has several shots ({shots}); pick the one to render.",
    },
    "sceneErr_projectNotInWorkspace": {
        "zh": "要归档到的项目不在这个 3D 场景所在的工作区里",
        "en": "The project to file the renders under isn't in this 3D scene's workspace.",
    },
    "schedErr_workflowMissing": {
        "zh": "任务绑定的工作流不存在",
        "en": "The workflow bound to this task doesn't exist.",
    },
    "schedErr_workflowNotRunnable": {
        "zh": "绑定的工作流「{name}」带着这个任务的参数跑不起来:{reason}",
        "en": "The bound workflow “{name}” can't run with this task's parameters: {reason}",
    },
    "schedNotice_runFailed": {"zh": "定时任务没跑起来:{name}", "en": "Scheduled task didn't start: {name}"},
    "schedNotice_disabled": {
        "zh": "定时任务跑不起来,已停用:{name}",
        "en": "Scheduled task can't run and was turned off: {name}",
    },
    "schedErr_workflowGone": {
        "zh": "绑定的工作流已删除,这个任务不能启用或运行。删掉它,或新建一个绑到现有工作流上的任务",
        "en": "The workflow bound to this task was deleted, so it can't be enabled or run. Delete it, or create a new task bound to an existing workflow.",
    },
    "schedErr_notWebhook": {
        "zh": "只有 Webhook 触发的任务才有触发密钥",
        "en": "Only webhook-triggered tasks have a trigger secret.",
    },
    "hookErr_taskNotFound": {
        "zh": "任务不存在",
        "en": "Task not found.",
    },
    "hookErr_badSecret": {
        "zh": "触发密钥不对(可能已经重置过)",
        "en": "Invalid trigger secret (it may have been reset).",
    },
    "hookErr_runNotFound": {
        "zh": "这个任务没有这次运行",
        "en": "This task has no such run.",
    },
    "schedErr_unsupportedKind": {
        "zh": "定时任务不支持这种任务:{kind}",
        "en": "Scheduled tasks don't support this kind of task: {kind}",
    },
    "schedErr_badKind": {
        "zh": "定时任务只能是:{kinds}",
        "en": "A scheduled task must be one of: {kinds}",
    },
    "schedErr_busy": {
        "zh": "这个任务上一次还没跑完",
        "en": "The previous run of this task hasn't finished yet.",
    },
    "schedErr_disabled": {
        "zh": "定时任务已停用",
        "en": "The scheduled task is disabled.",
    },
    "schedErr_onceNeedsRunAt": {
        "zh": "单次执行需要 run_at",
        "en": "A one-time schedule needs run_at.",
    },
    "schedErr_intervalNeedsSeconds": {
        "zh": "按间隔执行需要一个正的秒数",
        "en": "An interval schedule needs a positive number of seconds.",
    },
    "schedErr_weeklyNeedsWeekday": {
        "zh": "每周执行需要 weekday 0-6(周一为 0)",
        "en": "A weekly schedule needs weekday 0-6 (Monday = 0).",
    },
    "schedErr_unsupportedTrigger": {
        "zh": "不支持的触发方式:{trigger}",
        "en": "Unsupported trigger type: {trigger}",
    },
    "schedErr_badTime": {
        "zh": "time 必须是 HH:MM",
        "en": "time must be HH:MM.",
    },
    "schedErr_badRunAt": {
        "zh": "run_at 必须是 ISO 日期时间",
        "en": "run_at must be an ISO datetime.",
    },
    # 这台电脑上的文件是部署主人的私有资源(见 domain/host_files)。说的是怎么办。
    "hostErr_notAbsolute": {
        "zh": "本机文件路径必须是绝对路径",
        "en": "A file path on this computer must be absolute.",
    },
    "hostErr_notAFile": {
        "zh": "这个路径不是一个存在的文件",
        "en": "That path isn't an existing file.",
    },
    "hostErr_notReadable": {
        "zh": "这台电脑上的文件属于部署管理员,只有管理员能直接读。请改用素材库里的素材,或请管理员把所在文件夹加进「共享给成员的本机文件夹」",
        "en": "Files on this computer belong to the deployment admin, and only admins can read them directly. Use an asset from the library instead, or ask an admin to add the folder to “Folders shared with members”.",
    },
    # 往网页上传框塞的文件(见 host_files.upload_source):素材和本机路径只能给一个。
    "hostErr_uploadBothSources": {
        "zh": "素材和本机路径只能填一个:请清空其中一个",
        "en": "Fill in either an asset or a path on this computer, not both. Clear one of them.",
    },
    "hostErr_uploadNeedsSource": {
        "zh": "没有要上传的文件:请选一个素材,或填一个本机路径",
        "en": "There's nothing to upload. Choose an asset or enter a path on this computer.",
    },
    "hostErr_uploadAssetMissing": {
        "zh": "要上传的素材不存在,或不在这个工作区里",
        "en": "The asset to upload doesn't exist or isn't in this workspace.",
    },
    "hostErr_uploadAssetNoFile": {
        "zh": "这份素材没有文件,传不了",
        "en": "This asset has no file to upload.",
    },
    "hostErr_codeNeedsAdmin": {
        "zh": "在这台电脑上直接运行代码能读写它的任何文件,只有部署管理员能批准",
        "en": "Running code directly on this computer can read and write any of its files, so only a deployment admin can approve it.",
    },
    "hostErr_folderNotAbsolute": {
        "zh": "共享文件夹必须是绝对路径:{path}",
        "en": "A shared folder must be an absolute path: {path}",
    },
    "hostErr_folderMissing": {
        "zh": "这台电脑上没有这个文件夹:{path}",
        "en": "There's no such folder on this computer: {path}",
    },
    "hostErr_folderIsRoot": {
        "zh": "不能共享根目录 —— 那等于把整台电脑交出去。请选具体的文件夹",
        "en": "The root directory can't be shared — that would hand over the whole computer. Pick a specific folder.",
    },
    # 跑的人用得了,但被执行的那一版是别人改的(见 domain/authority)。说的是怎么办:请主人认可这一版。
    "shareErr_notVouched": {
        "zh": "工作流「{workflow}」的 v{revision} 是别人改的,它要用的这份资源不归改它的人用。请资源的主人打开这个工作流,确认改动后点「认可这一版」",
        "en": "Version v{revision} of the workflow “{workflow}” was changed by someone else, and they can't use what it needs here. Ask the owner to open the workflow, review the change and click “Approve this version”.",
    },
    "shareErr_notVouched_publishAccount": {
        "zh": "工作流「{workflow}」的 v{revision} 是别人改的,而它要用一个改它的人用不了的私有发布账号。请账号主人打开这个工作流,确认改动后点「认可这一版」",
        "en": "Version v{revision} of the workflow “{workflow}” was changed by someone else, and it publishes with a private account they can't use. Ask the account's owner to open the workflow, review the change and click “Approve this version”.",
    },
    "shareErr_notVouched_browserProfile": {
        "zh": "工作流「{workflow}」的 v{revision} 是别人改的,而它要用一个改它的人用不了的私有浏览器档案。请档案主人打开这个工作流,确认改动后点「认可这一版」",
        "en": "Version v{revision} of the workflow “{workflow}” was changed by someone else, and it uses a private browser profile they can't use. Ask the profile's owner to open the workflow, review the change and click “Approve this version”.",
    },
    "hostErr_notVouched": {
        "zh": "工作流「{workflow}」的 v{revision} 是别人改的,而它要读这台电脑上的文件。请部署管理员打开这个工作流,确认改动后点「认可这一版」",
        "en": "Version v{revision} of the workflow “{workflow}” was changed by someone else, and it reads files on this computer. Ask a deployment admin to open the workflow, review the change and click “Approve this version”.",
    },
    # 管私有身份只认主人(见 domain/sharing.ensure_manageable)。共享是借出去用,不是交出去管。
    "shareErr_notManageable": {
        "zh": "这份资源属于别人,只有主人能改、停用或删除它",
        "en": "This belongs to someone else, so only its owner can change, disable or delete it.",
    },
    "shareErr_notManageable_publishAccount": {
        "zh": "这个发布账号属于别人。共享给你只是可以用它发布 —— 改名、停用、改代理、复检、退出登录和删除只有主人能做",
        "en": "This publishing account belongs to someone else. Sharing it lets you publish with it — only its owner can rename, disable, change the proxy, recheck, sign out or delete it.",
    },
    "shareErr_notManageable_browserProfile": {
        "zh": "这个浏览器档案属于别人。共享给你只是可以用它 —— 改名、停用、改代理、清除登录数据和删除只有主人能做",
        "en": "This browser profile belongs to someone else. Sharing it lets you use it — only its owner can rename, disable, change the proxy, clear its sign-in data or delete it.",
    },
    "shareErr_notManageable_agentSession": {
        "zh": "这条对话是同事共享给你看的。在里面发消息、答选择卡、批确认卡,以及改名、删除、收进分组、改模型和权限只有主人能做",
        "en": "This conversation was shared with you to view. Only its owner can message in it, answer or approve its cards, rename, delete or group it, or change its model and permissions.",
    },
    "shareErr_notManageable_generationSession": {
        "zh": "这条生成会话是同事共享给你看的。改名、删除、收进分组、换模型和在里面继续生成只有主人能做",
        "en": "This generation session was shared with you to view. Only its owner can rename, delete, group, change its model or keep generating in it.",
    },
    "shareErr_notManageable_scheduledTask": {
        "zh": "这个定时任务属于别人:它到点替主人跑、用的是主人的钥匙和额度。改、停用、删除、重置触发密钥和立即运行只有主人能做",
        "en": "This scheduled task belongs to someone else: it runs as its owner, on the owner's keys and quota. Only its owner can change, disable, delete, reset its trigger secret or run it now.",
    },
    "shareErr_unknownKind": {
        "zh": "未知的资源类型:{kind}",
        "en": "Unknown resource type: {kind}",
    },
    # 用的那一刻被归属挡下(见 domain/sharing.ensure_usable)。说的是怎么办,不点名那一份叫什么。
    "shareErr_notUsable": {
        "zh": "这份资源属于别人且没有共享出来,只有主人和被共享到的人能用",
        "en": "This belongs to someone else and hasn't been shared, so only its owner and the people it's shared with can use it.",
    },
    "shareErr_notUsable_publishAccount": {
        "zh": "这个发布账号属于别人且没有共享出来,只有主人和被共享到的人能用它发布。请主人在发布页把它共享到这个工作区,或换一个自己的账号",
        "en": "This publishing account belongs to someone else and hasn't been shared, so only its owner and the people it's shared with can publish with it. Ask the owner to share it to this workspace on the Publish page, or pick an account of your own.",
    },
    "shareErr_notUsable_browserProfile": {
        "zh": "这个浏览器档案属于别人且没有共享出来,只有主人和被共享到的人能用它的登录态。请主人在浏览器池里把它共享到这个工作区,或换一个自己的档案",
        "en": "This browser profile belongs to someone else and hasn't been shared, so only its owner and the people it's shared with can use its sign-ins. Ask the owner to share it to this workspace in the Browser pool, or pick a profile of your own.",
    },
    "webErr_emptyQuery": {
        "zh": "query 不能为空",
        "en": "query can't be empty.",
    },
    "webErr_searchFailed": {
        "zh": "搜索请求失败: {detail}",
        "en": "Search request failed: {detail}",
    },
    "webErr_tooManyRedirects": {
        "zh": "跳转次数过多",
        "en": "Too many redirects.",
    },
    "webErr_fetchFailed": {
        "zh": "抓取失败: {detail}",
        "en": "Fetch failed: {detail}",
    },
    # ---- 内网守卫(core/outbound_guard):用户给的地址只许去公网 ----
    "outboundErr_private": {
        "zh": "不能访问 {host}:它解析到 {address},是{reason}。用户、模板或智能体给的地址默认只许去公网,"
              "免得借这台服务器摸进本机和内网的服务(包括云服务器的元数据接口)。确实需要的话,请部署管理员在"
              "「管理 → 部署设置 → 内网访问」里把「{entry}」加进允许名单(也可以写主机名、IP 或 CIDR 网段)。",
        "en": "Can't reach {host}: it resolves to {address}, which is {reason}. Addresses given by users, templates "
              "or the agent may only go to the public internet by default, so nobody can use this server to reach "
              "services on this machine or the internal network (including a cloud server's metadata endpoint). "
              "If this is intended, ask a deployment admin to add “{entry}” to the allowlist under "
              "Admin → Deployment → Internal network access (a host name, an IP or a CIDR range also works).",
    },
    "outboundErr_badUrl": {
        "zh": "不是可以访问的网址:{url}(只支持 http:// 或 https:// 开头的地址)",
        "en": "Not a reachable web address: {url} (only http:// and https:// addresses are supported).",
    },
    "outboundErr_tooLarge": {
        "zh": "{host} 回来的东西超过 {limit_mb} MB,没有收完就停了",
        "en": "What {host} sent back is over {limit_mb} MB, so it was not read to the end.",
    },
    "outboundErr_badEntry": {
        "zh": "允许名单里这一项写不对:{entry}。每一项写一个主机名、IP 或 CIDR 网段,主机名和 IP 可以带端口,"
              "例如 127.0.0.1:11434、nas.local、10.0.0.0/8",
        "en": "This allowlist entry isn't valid: {entry}. Write one host name, IP or CIDR range per entry; host "
              "names and IPs may carry a port, e.g. 127.0.0.1:11434, nas.local, 10.0.0.0/8.",
    },
    "outboundReason_loopback": {"zh": "本机回环地址", "en": "a loopback address on this machine"},
    "outboundReason_private": {"zh": "局域网地址", "en": "a private network address"},
    "outboundReason_linkLocal": {"zh": "链路本地地址", "en": "a link-local address"},
    "outboundReason_metadata": {"zh": "云服务器的元数据地址", "en": "a cloud metadata address"},
    "outboundReason_unspecified": {"zh": "未指定地址(等于本机)", "en": "the unspecified address (this machine)"},
    "outboundReason_special": {"zh": "保留或特殊用途的地址", "en": "a reserved or special-purpose address"},
}

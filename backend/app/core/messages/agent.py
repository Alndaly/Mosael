"""后端文案 · 智能体、时间线、工作流、沙箱、场景渲染(分区 B3)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # -- B3·智能体、时间线、工作流、沙箱、场景渲染 --
    # 智能体:对话回合、排队消息、放行判断者、订阅登录、记忆、计划
    "agentErr_noChatModelChosen": {
        "zh": "还没有选好对话模型:在输入框旁边选一个,或到设置里把它设成你的默认模型。",
        "en": "No chat model is selected yet. Pick one next to the message box, or set a default model in Settings.",
    },
    "agentErr_connectionNoModel": {
        "zh": "供应商「{name}」没有可用的模型:请在设置里为它填写默认模型,或在对话框的模型选择器里选一个。",
        "en": "Provider \"{name}\" has no usable model. Set a default model for it in Settings, or pick one in the chat's model picker.",
    },
    "agentErr_emptyReply": {
        "zh": (
            "模型没有返回任何内容。请检查 AI 供应商配置:base_url 是否完整"
            "(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。"
        ),
        "en": (
            "The model returned nothing. Check the AI provider settings: the base_url must be complete "
            "(including the port and /v1, e.g. http://localhost:11434/v1), the model name must exist, and the service must be reachable."
        ),
    },
    "agentErr_turnFailed": {"zh": "智能体执行失败，请稍后重试。", "en": "The agent run failed. Try again later."},
    "agentErr_turnCrashed": {"zh": "智能体执行异常。", "en": "The agent run hit an unexpected error."},
    "agentErr_messageAlreadyRunning": {
        "zh": "这条消息已经开始处理,无法撤回",
        "en": "This message is already being processed and can't be withdrawn.",
    },
    "agentErr_queuedMessageMissing": {"zh": "找不到这条排队消息", "en": "That queued message no longer exists."},
    "agentErr_judgeNoModel": {"zh": "没有可用于判断的对话模型", "en": "No chat model is available for the judge."},
    "agentErr_judgeNotJson": {"zh": "判断者的回答不是 JSON:{raw}", "en": "The judge's answer is not JSON: {raw}"},
    "agentErr_judgeNoAllow": {
        "zh": "判断者的回答里没有 allow 布尔值:{raw}",
        "en": "The judge's answer has no boolean \"allow\": {raw}",
    },
    "agentErr_loginStartFailed": {"zh": "登录进程启动失败", "en": "Could not start the sign-in process."},
    "agentErr_loginExited": {"zh": "登录进程意外结束", "en": "The sign-in process ended unexpectedly."},
    "agentErr_loginTimeout": {"zh": "授权超时,请重新发起登录", "en": "Authorization timed out. Start the sign-in again."},
    "agentErr_memoryEmpty": {"zh": "记忆内容不能为空", "en": "A memory can't be empty."},
    "agentErr_memoryTooLong": {
        "zh": "单条记忆最多 {max} 字 —— 它每一轮都要重发一遍,写不下的说明那不是一条约定",
        "en": "A memory can be at most {max} characters — it is resent on every turn, so anything that doesn't fit isn't a convention.",
    },
    "agentErr_memoryFull": {
        "zh": "记忆已达 {max} 条上限,请先删掉不再需要的",
        "en": "You've reached the limit of {max} memories. Delete the ones you no longer need first.",
    },
    "agentErr_planStepsNotArray": {"zh": "steps 必须是数组", "en": "steps must be an array."},
    "agentErr_planEmpty": {"zh": "计划至少要有一步", "en": "A plan needs at least one step."},
    # 智能体问用户的选择题(报错面向模型:要说清怎么改)
    "questionErr_listEmpty": {"zh": "questions 必须是非空数组", "en": "questions must be a non-empty array."},
    "questionErr_tooMany": {
        "zh": "一次最多问 {max} 个问题 —— 再多就该分两轮问",
        "en": "Ask at most {max} questions at a time — split anything more across two rounds.",
    },
    "questionErr_notObject": {"zh": "每个问题都得是对象", "en": "Each question must be an object."},
    "questionErr_questionEmpty": {"zh": "question 不能为空", "en": "question can't be empty."},
    "questionErr_duplicate": {
        "zh": "问题重复了:{question} —— 答案按问题正文归位,重复就对不回去",
        "en": "Duplicate question: {question} — answers are matched by question text, so duplicates can't be told apart.",
    },
    "questionErr_tooFewOptions": {
        "zh": "「{question}」至少要给 2 个选项 —— 只有一个的话不必问",
        "en": "\"{question}\" needs at least 2 options — with only one there is nothing to ask.",
    },
    "questionErr_tooManyOptions": {
        "zh": "「{question}」最多 {max} 个选项",
        "en": "\"{question}\" can have at most {max} options.",
    },
    "questionErr_optionNotObject": {"zh": "每个选项都得是对象", "en": "Each option must be an object."},
    "questionErr_optionLabelEmpty": {
        "zh": "选项的 label 不能为空 —— 空的会渲染成一个点不动的按钮",
        "en": "An option's label can't be empty — an empty one renders as a button that does nothing.",
    },
    "questionErr_optionDuplicate": {
        "zh": "「{question}」里选项重名:{label}",
        "en": "\"{question}\" has a duplicate option: {label}",
    },
    "questionErr_alreadyAnswered": {"zh": "这个问题已经回答过了", "en": "This question has already been answered."},
    "questionErr_notAsked": {"zh": "没有问过这个问题:{question}", "en": "This question was never asked: {question}"},
    "questionErr_nothingPicked": {"zh": "「{question}」没有选任何一项", "en": "Nothing was chosen for \"{question}\"."},
    "questionErr_freeTextOnlyOne": {
        "zh": "「{question}」的自由文本只能有一条",
        "en": "\"{question}\" accepts only one free-text answer.",
    },
    "questionErr_freeTextTooLong": {
        "zh": "「{question}」的自由文本太长(上限 {max} 字)",
        "en": "The free-text answer to \"{question}\" is too long (limit {max} characters).",
    },
    # 时间线(序列)
    "seqErr_nothingToUndo": {"zh": "没有可撤销的操作", "en": "Nothing to undo."},
    "seqErr_nothingToRedo": {"zh": "没有可重做的操作", "en": "Nothing to redo."},
    "seqErr_nothingOfYoursToUndo": {"zh": "没有你自己可撤销的操作", "en": "You have nothing of your own to undo."},
    # 并发:拒的时候说清是谁改的(见 domain/sequences/concurrency)。{who} 是人名的列表,或「你」「有人」。
    "seqErr_changedBy": {
        "zh": "{who}刚改过这条时间线,和这一步对不上;已换成最新的一版,请在它上面再做一次",
        "en": "{who} just changed this timeline, and this step no longer fits. It now shows the latest version — please do it again there.",
    },
    "seqErr_undoBlockedBy": {
        "zh": "{who}之后又动了这一步涉及的片段,撤销 / 重做它会打乱对方的改动,所以没有执行;已换成最新的一版",
        "en": "{who} has since changed what this step touched, so undoing or redoing it would scramble that change. Nothing was done; the timeline now shows the latest version.",
    },
    "seqWho_you": {"zh": "你", "en": "You"},
    "seqWho_someone": {"zh": "有人", "en": "Someone"},
    "seqErr_undoTrackHasClips": {
        "zh": "轨道上还有片段,撤销不了「新建轨道」",
        "en": "The track still has clips, so \"Add track\" can't be undone.",
    },
    "seqErr_notUndoable": {"zh": "「{kind}」这种操作不支持撤销", "en": "\"{kind}\" can't be undone."},
    "seqErr_undoClipGone": {
        "zh": "这一步引用的片段已经不在了,撤销不了",
        "en": "The clip this step refers to no longer exists, so it can't be undone.",
    },
    "seqErr_subtitleTrackHasNoSound": {
        "zh": "字幕轨没有声音,不能静音、独奏或闪避;不想显示字幕请用隐藏",
        "en": "A subtitle track has no sound, so it can't be muted, soloed or ducked. Hide it to stop showing the subtitles.",
    },
    "seqErr_onlySubtitleTracksHide": {
        "zh": "只有字幕轨可以隐藏",
        "en": "Only subtitle tracks can be hidden.",
    },
    "seqErr_detachAudioVideoOnly": {"zh": "只能从视频片段分离音频", "en": "Audio can only be detached from a video clip."},
    "seqErr_clipNoAudioSource": {"zh": "该片段没有音频源", "en": "This clip has no audio source."},
    "seqErr_transformNotNumber": {"zh": "transform.{key} 必须是数字", "en": "transform.{key} must be a number."},
    "seqErr_canvasSizeRange": {"zh": "画幅尺寸需在 16–8192 之间", "en": "The frame size must be between 16 and 8192."},
    "seqErr_revisionConflict": {
        "zh": "这条时间线刚被改过;已换成最新的一版,请在它上面再做一次",
        "en": "This timeline was just changed. It now shows the latest version — please do it again there.",
    },
    "seqErr_unknownOp": {"zh": "不认识的时间线操作: {kind}", "en": "Unknown timeline operation: {kind}"},
    "seqErr_trimNoRoom": {
        "zh": "这里没有地方放下这一段:修剪会让它短到没有,或者两边都贴着别的片段",
        "en": "There's no room for this clip here: the trim would leave nothing, or it is boxed in by its neighbours.",
    },
    "seqErr_speedWouldOverlap": {
        "zh": "慢放后这一段会盖住同轨的下一段。打开「推开后面的片段」,或先给它腾出地方",
        "en": "At this speed the clip would run into the next clip on its track. Let it push the following clips, or make room first.",
    },
    # 工作流:选项来源、修订、AI 编排、JSON 校验
    "wfErr_unknownOptionSource": {"zh": "未知的选项来源:{source}", "en": "Unknown option source: {source}"},
    "wfErr_graphConflict": {
        "zh": "工作流已在别处更新,请载入最新内容后再改",
        "en": "This workflow was changed somewhere else. Load the latest version and try again.",
    },
    "wfErr_graphBaseMissing": {
        "zh": "保存整张工作流图时必须带上它所基于的版本(base_graph_hash)",
        "en": "Saving a whole workflow graph requires the version it was based on (base_graph_hash).",
    },
    "wfErr_revisionConcurrent": {
        "zh": "工作流在保存期间被连续修改，请重试",
        "en": "The workflow kept changing while it was being saved. Try again.",
    },
    "wfErr_revisionSnapshotMissing": {
        "zh": "工作流 v{revision} 的修订快照不存在",
        "en": "The revision snapshot for workflow v{revision} does not exist.",
    },
    "wfErr_revisionDigestMismatch": {
        "zh": "工作流 v{revision} 的图摘要校验失败",
        "en": "The graph digest check failed for workflow v{revision}.",
    },
    "wfErr_revisionProjectionMismatch": {
        "zh": "工作流 v{revision} 的当前投影与修订快照不一致",
        "en": "Workflow v{revision}'s current graph does not match its revision snapshot.",
    },
    "wfErr_revisionNotFound": {"zh": "工作流修订 v{revision} 不存在", "en": "Workflow revision v{revision} does not exist."},
    "wfErr_aiEditBadJson": {"zh": "JSON 解析失败: {detail}", "en": "Could not parse the JSON: {detail}"},
    "wfErr_aiEditNoJsonObject": {"zh": "输出中没有 JSON 对象", "en": "The output contains no JSON object."},
    "wfErr_jsonSchemaMismatchUnenforced": {
        "zh": "模型返回的 JSON 不符合 Schema:{reason}(这一档实际跑在 {tier}:该端点无法把 Schema 当成硬约束)",
        "en": "The model's JSON does not match the schema: {reason} (this call actually ran as {tier}: the endpoint can't enforce the schema as a hard constraint)",
    },
    # 代码沙箱
    "sandboxErr_timeout": {"zh": "代码执行超时({seconds}s)", "en": "The code timed out ({seconds}s)."},
    "sandboxErr_outputTooLarge": {
        "zh": "代码输出超过上限({kib} KiB, stdout + stderr)",
        "en": "The code's output exceeded the limit ({kib} KiB, stdout + stderr).",
    },
    "sandboxErr_dockerMissing": {"zh": "需要安装并启动 Docker 才能执行代码", "en": "Install and start Docker to run code."},
    "sandboxErr_containerCreateFailed": {"zh": "创建容器失败", "en": "could not create the container"},
    "sandboxErr_notReady": {
        "zh": "代码隔离环境未就绪: {detail}。请先运行 docker pull {image}",
        "en": "The code sandbox isn't ready: {detail}. Run docker pull {image} first.",
    },
    "sandboxErr_cleanupFailed": {
        "zh": "沙箱容器清理失败,请检查 Docker 状态",
        "en": "Could not clean up the sandbox container. Check that Docker is healthy.",
    },
    "sandboxErr_cleanupFailedDetail": {
        "zh": "沙箱容器清理失败: {detail}",
        "en": "Could not clean up the sandbox container: {detail}",
    },
    "sandboxErr_unavailable": {
        "zh": (
            "这台机器上没有可用的代码隔离环境,因此不执行代码。"
            "请在部署机上安装并启动 Docker(服务端会用一个无网络、只读、非 root 的容器来跑)。"
        ),
        "en": (
            "No code sandbox is available on this machine, so the code was not run. "
            "Install and start Docker on the server (code runs in a container with no network, a read-only filesystem and a non-root user)."
        ),
    },
    "sandboxErr_noReason": {"zh": "子进程没有留下原因", "en": "the process left no reason"},
    "sandboxErr_codeFailed": {"zh": "代码执行出错:{why}", "en": "The code failed: {why}"},
    "sandboxErr_outputUnparsable": {
        "zh": "代码输出无法解析(请把结果赋给 output 变量)",
        "en": "Could not read the code's output (assign the result to the output variable).",
    },
    # 白模渲染与导入模型
    "sceneRenderErr_shotNoCamera": {"zh": "镜头「{shot}」没有可用的机位", "en": "Shot \"{shot}\" has no usable camera."},
    "sceneRenderErr_shotMissing": {"zh": "场景里没有镜头 {shot_id}", "en": "The scene has no shot {shot_id}."},
    "sceneRenderErr_unknownView": {
        "zh": "不认识的视角 {view},可选:{options}",
        "en": "Unknown view {view}. Options: {options}",
    },
    "sceneRenderErr_ffmpegNoReason": {"zh": "ffmpeg 没有说原因", "en": "ffmpeg gave no reason"},
    "sceneRenderErr_videoEncodeFailed": {
        "zh": "白模运镜视频编码失败:{detail}",
        "en": "Encoding the graybox camera-move video failed: {detail}",
    },
    "modelMeshErr_tooManyTriangles": {
        "zh": "模型超过 {limit} 个三角形,白模参考帧渲不动 —— 请先在 Blender 里用精简(Decimate)修改器减面再导入。",
        "en": "The model has more than {limit} triangles, too many for graybox reference frames. Reduce it with Blender's Decimate modifier before importing.",
    },
    "modelMeshErr_noMesh": {"zh": "模型里没有可以渲染的三角形网格。", "en": "The model has no triangle mesh to render."},
    "modelMeshErr_gltfVersion": {
        "zh": "只支持 glTF 2.0,这份是 {version}。",
        "en": "Only glTF 2.0 is supported; this file is version {version}.",
    },
    "modelMeshErr_glbNoJson": {"zh": "GLB 里没有 JSON 块。", "en": "The GLB file has no JSON chunk."},
    "modelMeshErr_badGlb": {
        "zh": "GLB 的文件结构不对(文件头声明的长度和文件对不上)—— 从 Blender 重新导出一份。",
        "en": "The GLB file is malformed (its header doesn't match the file). Export it again from Blender.",
    },
    "modelMeshErr_draco": {
        "zh": "模型用了 Draco 压缩网格,白模渲染器解不开 —— 导出 GLB 时关掉压缩即可。",
        "en": "The model uses Draco mesh compression, which the graybox renderer can't decode. Export the GLB with compression turned off.",
    },
    "modelMeshErr_meshopt": {
        "zh": "模型用了 meshopt 压缩网格,白模渲染器解不开 —— 导出 GLB 时关掉压缩即可。",
        "en": "The model uses meshopt compression, which the graybox renderer can't decode. Export the GLB with compression turned off.",
    },
    "modelMeshErr_missingBinChunk": {
        "zh": "模型声明了内置二进制块,文件里却没有。",
        "en": "The model declares an embedded binary chunk, but the file doesn't contain one.",
    },
    "modelMeshErr_externalBuffer": {
        "zh": "模型的数据在另一个文件里({uri}),导入时只收到了这一份 —— 请导出为自包含的 .glb。",
        "en": "The model's data is in a separate file ({uri}), and only this file was imported. Export a self-contained .glb.",
    },
    "modelMeshErr_sparseAccessor": {
        "zh": "模型用了稀疏访问器(sparse accessor),白模渲染器读不了。",
        "en": "The model uses a sparse accessor, which the graybox renderer can't read.",
    },
    "modelMeshErr_unreadable": {"zh": "模型文件读不了:{detail}", "en": "Couldn't read the model file: {detail}"},
}

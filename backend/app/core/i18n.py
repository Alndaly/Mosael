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
    # ---- B1 · 01_plugins ----
    "pluginErr_upstream": {
        "zh": "{detail}",
        "en": "{detail}",
    },
    "pluginErr_notFound": {
        "zh": "插件不存在",
        "en": "Plugin not found.",
    },
    "pluginErr_instanceNotFound": {
        "zh": "插件连接不存在",
        "en": "Plugin connection not found.",
    },
    "pluginErr_packageNotFound": {
        "zh": "插件包不存在",
        "en": "Plugin package not found.",
    },
    "pluginErr_connectionNotFound": {
        "zh": "没有这个连接",
        "en": "Connection not found.",
    },
    "pluginErr_capabilityNotDeclared": {
        "zh": "「{name}」没有声明「{capability}」这项能力",
        "en": "\"{name}\" does not declare the \"{capability}\" capability.",
    },
    "pluginErr_mcpNoAssetChannel": {
        "zh": "这个工具要收一份素材,但 MCP 形态没有交接文件的通道",
        "en": "This tool takes an asset, but MCP plugins have no channel for handing over files.",
    },
    "pluginErr_assetNeedsWorkspace": {
        "zh": "这个工具要收一份素材,但这次调用没有归属工作区",
        "en": "This tool takes an asset, but this call doesn't belong to a workspace.",
    },
    "pluginErr_singleConnection": {
        "zh": "「{name}」只能有一个连接",
        "en": "\"{name}\" can have only one connection.",
    },
    "pluginErr_unknownConfig": {
        "zh": "插件未声明这些配置项: {keys}",
        "en": "The plugin doesn't declare these settings: {keys}",
    },
    "pluginErr_unknownCredentials": {
        "zh": "插件未声明这些凭据项: {keys}",
        "en": "The plugin doesn't declare these credentials: {keys}",
    },
    "pluginErr_unknownPermissions": {
        "zh": "插件未声明这些权限: {keys}",
        "en": "The plugin doesn't declare these permissions: {keys}",
    },
    "pluginBlocked_disabled": {
        "zh": "未启用",
        "en": "Disabled",
    },
    "pluginBlocked_missingConfig": {
        "zh": "缺少配置: {names}",
        "en": "Missing settings: {names}",
    },
    "pluginBlocked_missingCredentials": {
        "zh": "缺少凭据: {names}",
        "en": "Missing credentials: {names}",
    },
    "pluginBlocked_permissionsPending": {
        "zh": "权限未授予",
        "en": "Permissions not granted",
    },
    "pluginErr_fillFirst": {
        "zh": "请先填写: {names}",
        "en": "Fill in first: {names}",
    },
    "pluginErr_unavailable": {
        "zh": "「{name}」不可用:{reason}",
        "en": "\"{name}\" is unavailable: {reason}",
    },
    "pluginErr_noSuchTool": {
        "zh": "「{name}」没有工具 {tool}",
        "en": "\"{name}\" has no tool named {tool}.",
    },
    "pluginErr_artifactNeedsWorkspace": {
        "zh": "这个工具产出了文件,但这次调用没有归属工作区,收不下",
        "en": "This tool produced a file, but this call doesn't belong to a workspace, so it can't be saved.",
    },
    "pluginErr_configNotJson": {
        "zh": "「{label}」不是合法的 JSON:第 {line} 行第 {column} 列,{detail}",
        "en": "“{label}” is not valid JSON: line {line}, column {column}: {detail}",
    },
    "pluginErr_artifactTooMany": {
        "zh": "插件一次交出的文件超过 {limit} 份",
        "en": "The plugin returned more than {limit} files in one call.",
    },
    "pluginErr_interruptedByRestart": {
        "zh": "后端重启,这次调用没有结果",
        "en": "The backend restarted, so this call has no result.",
    },
    "pluginErr_toolInternal": {
        "zh": "工具 {tool} 只供 Mosael 内部使用,不能直接调用",
        "en": "The tool {tool} is reserved for Mosael itself and can't be called directly.",
    },
    "pluginErr_scanSkipped": {
        "zh": "其余插件都已登记,这几个没登记上:{detail}",
        "en": "All other plugins were registered; these could not be: {detail}",
    },
    "pluginErr_runtimeCrashed": {
        "zh": "插件运行时异常: {detail}",
        "en": "Plugin runtime error: {detail}",
    },
    "pluginErr_artifactNoPath": {
        "zh": "插件产出缺少 path",
        "en": "The plugin output is missing \"path\".",
    },
    "pluginErr_artifactOutsideScratch": {
        "zh": "插件产出必须写在 {env} 指定的目录里",
        "en": "Plugin output must be written inside the directory given by {env}.",
    },
    "pluginErr_artifactMissing": {
        "zh": "插件产出文件不存在",
        "en": "The plugin's output file does not exist.",
    },
    "pluginErr_artifactTooLarge": {
        "zh": "插件产出超过大小上限",
        "en": "The plugin's output exceeds the size limit.",
    },
    "pluginErr_artifactNoUrl": {
        "zh": "插件产出缺少 url",
        "en": "The plugin output is missing \"url\".",
    },
    "pluginErr_artifactBadScheme": {
        "zh": "插件产出的 url 只能是 http/https",
        "en": "The plugin output URL must be http or https.",
    },
    "pluginErr_artifactDownloadFailed": {
        "zh": "下载插件产出失败:{detail}",
        "en": "Could not download the plugin output: {detail}",
    },
    "pluginErr_manifestMissingField": {
        "zh": "插件清单 {path} 缺少必填字段: {field}",
        "en": "Plugin manifest {path} is missing a required field: {field}",
    },
    "pluginErr_manifestBadId": {
        "zh": "插件清单 {path} 的 id「{id}」不合法:只能用字母、数字和 . _ -,并以字母或数字开头",
        "en": "Plugin manifest {path} has an invalid id “{id}”: use only letters, digits and . _ -, starting with a letter or digit.",
    },
    "pluginErr_manifestBadToolName": {
        "zh": "插件清单 {path} 的工具名「{tool}」不合法:以字母开头,只能用字母、数字、_ 和 -,最长 64 个字符",
        "en": "Plugin manifest {path} has an invalid tool name “{tool}”: start with a letter and use only letters, digits, _ and -, up to 64 characters.",
    },
    "pluginErr_manifestDuplicateTool": {
        "zh": "插件清单 {path} 里有两个工具都叫 {tool}",
        "en": "Plugin manifest {path} declares two tools named {tool}.",
    },
    "pluginErr_manifestReservedKey": {
        "zh": "插件清单 {path}:配置 / 凭据的键 {field} 会盖掉宿主给插件的环境变量(PATH、HOME、LANG、MOSAEL_* 等),请换个名字",
        "en": "In plugin manifest {path}, the config/credential key {field} would override an environment variable the host provides (PATH, HOME, LANG, MOSAEL_* and so on); please rename it.",
    },
    "pluginErr_manifestDuplicateKey": {
        "zh": "插件清单 {path}:配置 / 凭据的键 {field} 和 {other} 大写后是同一个环境变量",
        "en": "In plugin manifest {path}, the config/credential keys {field} and {other} become the same environment variable once upper-cased.",
    },
    "pluginErr_manifestToolExtraCapability": {
        "zh": "插件清单 {path} 的工具 {tool} 声明了包上没有的能力: {capabilities}",
        "en": "In plugin manifest {path}, tool {tool} declares capabilities the package doesn't: {capabilities}",
    },
    "pluginErr_manifestBadEffects": {
        "zh": "插件清单 {path}:{tool} 的 effects 只能是 {allowed} 之一,写的是「{value}」",
        "en": "In plugin manifest {path}, the effects of {tool} must be one of {allowed}, not “{value}”.",
    },
    "pluginErr_manifestReadOnlyEffects": {
        "zh": "插件清单 {path}:工具 {tool} 标了 read_only,effects 却写成「{value}」—— 只读的工具没有后果,两处说的不是一回事",
        "en": "In plugin manifest {path}, tool {tool} is marked read_only yet declares effects “{value}”; a read-only tool has no effects, so the two contradict each other.",
    },
    "pluginErr_manifestCapabilityNeedsProcess": {
        "zh": "插件清单 {path}:能力 {capability} 只能由本地脚本形态的插件提供(MCP 插件不支持)",
        "en": "In plugin manifest {path}, the {capability} capability can only be provided by a local-script plugin (not MCP).",
    },
    "pluginErr_manifestCapabilityUnclaimed": {
        "zh": "插件清单 {path} 声明了能力 {capability},但没有哪个工具认领它 —— 在负责它的那个工具上也写上 provides",
        "en": "Plugin manifest {path} declares the {capability} capability, but no tool claims it — add provides to the tool that handles it.",
    },
    "pluginErr_manifestCapabilityClaimedTwice": {
        "zh": "插件清单 {path}:能力 {capability} 被多个工具同时认领({tools}),只能有一个",
        "en": "In plugin manifest {path}, the {capability} capability is claimed by several tools ({tools}); only one may claim it.",
    },
    "pluginErr_streamNoResult": {
        "zh": "插件没有给出结果就结束了(最后一行应当是 {shape})",
        "en": "The plugin finished without a result (its last line should be {shape}).",
    },
    "pluginErr_capabilityNoTool": {
        "zh": "「{name}」没有负责 {capability} 的工具,请到插件页更新这个插件",
        "en": "“{name}” has no tool that handles {capability}. Update the plugin from the Plugins page.",
    },
    "pluginErr_generationBadModels": {
        "zh": "「{name}」交回的模型清单格式不对,应当是 {shape}",
        "en": "“{name}” returned a model list in the wrong shape; it should be {shape}.",
    },
    "pluginErr_generationNoOutput": {
        "zh": "「{name}」完成了生成,但没有交回任何文件",
        "en": "“{name}” finished generating but handed back no files.",
    },
    "pluginErr_toolsBadShape": {
        "zh": "「{name}」交回的工具清单格式不对,应当是 {shape}",
        "en": "“{name}” returned a tool list in the wrong shape; it should be {shape}.",
    },
    "pluginErr_generationNoFingerprint": {
        "zh": "「{name}」没有交回模型清单的指纹",
        "en": "“{name}” returned no fingerprint for its model list.",
    },
    "pluginErr_bundledCannotReplace": {
        "zh": "「{name}」和随 Mosael 一起提供的插件同名(同一个 id),不能用市场上的包替换它",
        "en": "“{name}” has the same id as a plugin that ships with Mosael, so a package from the market can't replace it.",
    },
    "pluginErr_bundledCannotUninstall": {
        "zh": "「{name}」随 Mosael 一起提供,不能卸载;不想用的话停用它的连接即可",
        "en": "“{name}” ships with Mosael and can't be uninstalled; disable its connection if you don't want to use it.",
    },
    "pluginErr_manifestNotJson": {
        "zh": "插件清单不是合法 JSON: {path}",
        "en": "The plugin manifest is not valid JSON: {path}",
    },
    "pluginErr_manifestNotObject": {
        "zh": "插件清单必须是一个对象: {path}",
        "en": "The plugin manifest must be a JSON object: {path}",
    },
    "pluginErr_mcpNoBlock": {
        "zh": "MCP 插件必须声明 mcp 配置块(manifest.mcp)",
        "en": "An MCP plugin must declare an \"mcp\" block (manifest.mcp).",
    },
    "pluginErr_mcpStdioNoCommand": {
        "zh": "stdio 传输必须声明 command",
        "en": "The stdio transport must declare a \"command\".",
    },
    "pluginErr_mcpHttpNoUrl": {
        "zh": "http 传输必须声明 url",
        "en": "The http transport must declare a \"url\".",
    },
    "pluginErr_mcpBadTransport": {
        "zh": "不支持的 MCP 传输方式: {transport}(支持 stdio / http)",
        "en": "Unsupported MCP transport: {transport} (use stdio or http).",
    },
    "pluginErr_mcpTimeout": {
        "zh": "MCP 插件响应超时({seconds}s)",
        "en": "The MCP plugin didn't respond within {seconds}s.",
    },
    "pluginErr_mcpConnectFailed": {
        "zh": "连接 MCP 插件失败: {detail}",
        "en": "Could not connect to the MCP plugin: {detail}",
    },
    "pluginErr_mcpToolFailed": {
        "zh": "MCP 工具 {tool} 返回错误",
        "en": "MCP tool {tool} returned an error.",
    },
    "pluginErr_oauthNotDeclared": {
        "zh": "这个插件没有声明 OAuth,凭据只能手动填。",
        "en": "This plugin doesn't declare OAuth; enter its credentials by hand.",
    },
    "pluginErr_oauthNeedsClientId": {
        "zh": "先填好「{field}」再来授权 —— 授权链接要用它。",
        "en": "Fill in \"{field}\" before authorizing — the authorization link needs it.",
    },
    "pluginErr_oauthNoCode": {
        "zh": "没有拿到授权码。",
        "en": "No authorization code was received.",
    },
    "pluginErr_oauthTokenNotObject": {
        "zh": "令牌接口回的不是一个对象。",
        "en": "The token endpoint didn't return a JSON object.",
    },
    "pluginErr_oauthFailed": {
        "zh": "授权失败:{detail}",
        "en": "Authorization failed: {detail}",
    },
    "pluginErr_oauthNoFields": {
        "zh": "令牌接口没有回任何一个声明过的字段 —— 对照插件清单的 stores 看看。",
        "en": "The token endpoint returned none of the declared fields — check \"stores\" in the plugin manifest.",
    },
    "pluginErr_marketBadScheme": {
        "zh": "插件市场地址只能是 http/https",
        "en": "The plugin marketplace URL must be http or https.",
    },
    "pluginErr_marketUnreachable": {
        "zh": "打不开插件市场:{detail}",
        "en": "Could not open the plugin marketplace: {detail}",
    },
    "pluginErr_marketNotJson": {
        "zh": "插件市场返回的不是合法 JSON",
        "en": "The plugin marketplace did not return valid JSON.",
    },
    "pluginErr_marketBadShape": {
        "zh": "插件市场格式不对:应当是 {example}",
        "en": "The plugin marketplace has the wrong format; expected {example}",
    },
    "pluginErr_downloadBadScheme": {
        "zh": "插件下载地址只能是 http/https",
        "en": "The plugin download URL must be http or https.",
    },
    "pluginErr_archiveTooLarge": {
        "zh": "插件包超过大小上限",
        "en": "The plugin package exceeds the size limit.",
    },
    "pluginErr_downloadFailed": {
        "zh": "下载插件失败:{detail}",
        "en": "Could not download the plugin: {detail}",
    },
    "pluginErr_archiveSymlink": {
        "zh": "插件包里有符号链接,拒绝安装:{name}",
        "en": "The plugin package contains a symbolic link, so it was not installed: {name}",
    },
    "pluginErr_archivePathEscape": {
        "zh": "插件包里有越界路径,拒绝安装:{name}",
        "en": "The plugin package contains a path outside its folder, so it was not installed: {name}",
    },
    "pluginErr_archiveUnpackedTooLarge": {
        "zh": "插件包解压后超过大小上限",
        "en": "The unpacked plugin package exceeds the size limit.",
    },
    "pluginErr_archiveNoManifest": {
        "zh": "这个包里没有 {manifest},不是一个插件",
        "en": "This package has no {manifest}, so it isn't a plugin.",
    },
    "pluginErr_archiveNotZip": {
        "zh": "这不是一个合法的 zip 包",
        "en": "This is not a valid zip file.",
    },
    "pluginErr_manifestInvalid": {
        "zh": "插件清单不合法:{detail}",
        "en": "Invalid plugin manifest: {detail}",
    },
    "pluginErr_alreadyInstalled": {
        "zh": "「{name}」已经装过了 —— 要装新版本请选「更新」",
        "en": "\"{name}\" is already installed — choose \"Update\" to install a new version.",
    },
    "pluginErr_noEntry": {
        "zh": "插件未声明 entry 脚本,无法执行(runtime.entry)",
        "en": "The plugin declares no entry script (runtime.entry), so it can't run.",
    },
    "pluginErr_dirMissing": {
        "zh": "插件目录不存在,请重新扫描",
        "en": "The plugin folder is missing. Rescan plugins.",
    },
    "pluginErr_entryOutside": {
        "zh": "entry 脚本必须位于插件目录内",
        "en": "The entry script must be inside the plugin folder.",
    },
    "pluginErr_entryMissing": {
        "zh": "entry 脚本不存在: {entry}",
        "en": "Entry script not found: {entry}",
    },
    "pluginErr_missingInput": {
        "zh": "缺少必填输入: {keys}",
        "en": "Missing required input: {keys}",
    },
    "pluginErr_noPython": {
        "zh": "找不到可用于运行插件的 Python 解释器",
        "en": "No Python interpreter is available to run the plugin.",
    },
    "pluginErr_timeout": {
        "zh": "插件执行超时({seconds}s)",
        "en": "The plugin timed out after {seconds}s.",
    },
    #: 选连接的三种失败(见 plugins.nodes.resolve_instance)。工作流节点和画板上的工具共用,
    #: 所以不说「在节点上」—— 选连接的那一格在哪,读的人自己眼前就是。
    "pluginErr_instanceGone": {
        "zh": "选的连接已不可用(插件 {package});请重新选一个",
        "en": "The chosen connection is gone (plugin {package}); choose another",
    },
    "pluginErr_noInstance": {
        "zh": "没有可用的「{package}」连接:请在插件页新建并启用一个",
        "en": "No usable “{package}” connection: create and enable one on the Plugins page",
    },
    "pluginErr_manyInstances": {
        "zh": "有多个「{package}」连接({names}),请选一个",
        "en": "Several “{package}” connections exist ({names}); pick one",
    },
    "pluginErr_cancelled": {
        "zh": "任务已取消,插件调用被中止",
        "en": "The task was cancelled, so the plugin call was stopped.",
    },
    "pluginErr_processExit": {
        "zh": "插件进程退出码 {code}:{detail}",
        "en": "The plugin process exited with code {code}: {detail}",
    },
    "pluginErr_processExitNoReason": {
        "zh": "插件进程退出码 {code}:插件没有留下原因",
        "en": "The plugin process exited with code {code} without giving a reason.",
    },
    "pluginErr_outputTooLarge": {
        "zh": "插件输出超过大小限制 (1MB)",
        "en": "The plugin output exceeds the size limit (1 MB).",
    },
    "pluginErr_outputNotJson": {
        "zh": "插件输出不是合法 JSON: {tail}",
        "en": "The plugin output is not valid JSON: {tail}",
    },
    "pluginErr_outputNotObject": {
        "zh": "插件输出必须是 JSON 对象",
        "en": "The plugin output must be a JSON object.",
    },
    "pluginErr_failedNoReason": {
        "zh": "插件返回失败但未说明原因",
        "en": "The plugin reported a failure without giving a reason.",
    },
    "pluginErr_outputNoOutput": {
        "zh": "插件成功响应必须包含 output 对象",
        "en": "A successful plugin response must include an \"output\" object.",
    },
    "pluginErr_stateNotObject": {
        "zh": "插件返回的 state 必须是对象",
        "en": "The \"state\" returned by the plugin must be an object.",
    },
    "pluginErr_stateUnknownKeys": {
        "zh": "插件想记住未声明的键: {keys}",
        "en": "The plugin tried to store undeclared keys: {keys}",
    },
    "pluginErr_stateTooLong": {
        "zh": "插件状态过长(上限 {limit} 字符): {keys}",
        "en": "Plugin state is too long (limit {limit} characters): {keys}",
    },
    # ---- B1 · 02_routes ----
    "routeErr_internal": {
        "zh": "后端出错了,这次操作没有完成。错误已记进后端日志;重试一次,还不行就把日志发给开发者。",
        "en": "The backend hit an error and this action didn't complete. It's in the backend log — try again, and if it keeps failing, send the log to the developers.",
    },
    "routeErr_accountNotFound": {
        "zh": "账号不存在",
        "en": "Account not found.",
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
    "routeErr_groupNotFound": {
        "zh": "分组不存在",
        "en": "Group not found.",
    },
    "routeErr_badPermissionMode": {
        "zh": "permission_mode 只能是 {modes}",
        "en": "permission_mode must be one of {modes}.",
    },
    "routeErr_sharedSessionNoBypass": {
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
    "routeErr_assetNotInAgentWorkspace": {
        "zh": "素材不属于当前智能体会话的工作区",
        "en": "The asset isn't in this agent session's workspace.",
    },
    "routeErr_framesOnlyFromVideo": {
        "zh": "只能从视频里取帧",
        "en": "Frames can only be taken from a video.",
    },
    "routeErr_noProxyForAsset": {
        "zh": "该素材不支持生成预览代理",
        "en": "This asset doesn't support a preview proxy.",
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
    "routeErr_noteTrashFirst": {
        "zh": "请先将笔记移入回收站",
        "en": "Move the note to the trash first.",
    },
    "routeErr_noteChangedBeforeDelete": {
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
    "oauthLogin_okPage": {
        "zh": "登录成功,回到 Mosael 即可,本页可以关闭。",
        "en": "Signed in. Go back to Mosael; you can close this page.",
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
    "routeErr_pluginTokenExchangeFailed": {
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
    "routeErr_paramGroupNotFound": {
        "zh": "这条连接下没有这个参数组",
        "en": "This connection has no such parameter group.",
    },
    "routeErr_paramGroupNameRequired": {
        "zh": "给这份参数组起个名字",
        "en": "Give this parameter group a name.",
    },
    "routeErr_paramGroupNameTaken": {
        "zh": "这条连接下已经有同名的参数组了",
        "en": "This connection already has a parameter group with that name.",
    },
    "routeErr_paramGroupInUse": {
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
    # 分时段价格的校验(domain/price_schedule)。时段按界面上的顺序从 1 数。
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
    "routeErr_missingRequiredConfig": {
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
    "routeErr_notWorkflowFile": {
        "zh": "不是有效的 Mosael 工作流文件",
        "en": "This isn't a valid Mosael workflow file.",
    },
    "routeErr_workflowFileTooNew": {
        "zh": "文件版本({version})比当前应用支持的更新,请升级应用后再导入",
        "en": "The file version ({version}) is newer than this app supports. Update the app, then import it.",
    },
    "routeErr_workflowRevisionNotFound": {
        "zh": "工作流修订不存在",
        "en": "Workflow revision not found.",
    },
    "routeErr_judgeHostCodeNeedsAdmin": {
        "zh": "把「本机执行代码」交给判断者需要这台机器的管理员权限 —— 它和工作流里的代码节点是同一个能力",
        "en": "Letting the judge approve \"run code on this machine\" requires admin rights on this machine — it's the same capability as the code node in workflows.",
    },
    "routeErr_poemUnreachable": {
        "zh": "今日诗词暂时不可达:{detail}",
        "en": "The daily poem service is unreachable right now: {detail}",
    },
    # ---- B1 · 03_confirmable ----
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
        "zh": "「{item_id}」不是工具格:智能体只能运行工具格;图片/视频/音频槽和便签由用户在面板上生成",
        "en": "“{item_id}” is not a tool item. The agent can only run tool items; image/video/audio slots and notes are generated by the user from their panel.",
    },
    "confirmErr_boardItemChanged": {
        "zh": "开卡之后「{item_id}」换了工具,这张卡批准的不是现在这一个 —— 请重新发起",
        "en": "“{item_id}” switched to a different tool after this card was opened, so the card no longer covers it. Please ask again.",
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
    "confirmErr_noTtsProvider": {
        "zh": "没有配置可用于语音生成的真实供应商",
        "en": "No provider is set up for speech generation.",
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
    # ---- B1 · 04_aichat ----
    "aiChat_labelDefault": {
        "zh": "AI 调用",
        "en": "AI call",
    },
    "aiChatErr_http": {
        "zh": "{label}失败:{status} {detail}（模型 {model}）",
        "en": "{label} failed: {status} {detail} (model {model})",
    },
    "aiChatErr_network": {
        "zh": "{label}失败(网络/连接):{detail}",
        "en": "{label} failed (network/connection): {detail}",
    },
    "aiChatErr_networkRetried": {
        "zh": "{label}失败(网络/连接,已重试 {tries} 次仍失败):{detail}",
        "en": "{label} failed (network/connection, still failing after {tries} retries): {detail}",
    },
    "aiChatErr_badShape": {
        "zh": "{label}失败:供应商返回的结构不认识({detail})",
        "en": "{label} failed: the provider returned a response in an unrecognized shape ({detail})",
    },
    "aiChatErr_gatewayNoClient": {
        "zh": "{label}失败:OAuth Gateway 不支持复用调用方 HTTP 连接",
        "en": "{label} failed: the OAuth gateway can't reuse the caller's HTTP connection.",
    },
    "aiChatErr_failed": {
        "zh": "{label}失败:{detail}",
        "en": "{label} failed: {detail}",
    },
    "aiChatDowngrade_rejected": {
        "zh": "供应商明确拒绝了这一档",
        "en": "The provider explicitly rejected this tier",
    },
    "aiChatDowngrade_empty": {
        "zh": "这一档下返回了空正文",
        "en": "This tier returned an empty body",
    },
    "providerErr_connectionMissing": {
        "zh": "指定的供应商配置不存在或已停用",
        "en": "The selected provider connection doesn't exist or is disabled.",
    },
    "providerErr_noConnection": {
        "zh": "没有可用的 AI 供应商连接,请先在设置里添加并配置",
        "en": "No AI provider connection is available. Add and configure one in Settings first.",
    },
    "providerErr_noKey": {
        "zh": "供应商「{name}」还没有配置你的密钥,请先在设置里填写",
        "en": "Provider \"{name}\" doesn't have your key yet. Add it in Settings first.",
    },
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
        "zh": "该用户名不存在;请对方先在登录页注册账号",
        "en": "No such username. Ask them to sign up on the login page first.",
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
        "zh": "已有待处理的邀请",
        "en": "There's already a pending invitation.",
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
    "memberErr_lastOwnerRemove": {
        "zh": "不能移除最后一个所有者",
        "en": "Can't remove the last owner.",
    },
    "memberErr_lastDeploymentAdmin": {
        "zh": "这是最后一个部署管理员 —— 先把管理员给别人,再删这个账号。",
        "en": "This is the last deployment administrator — make someone else an administrator before deleting this account.",
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
    "sceneErr_projectNotInWorkspace": {
        "zh": "要归档到的项目不在这个 3D 场景所在的工作区里",
        "en": "The project to file the renders under isn't in this 3D scene's workspace.",
    },
    "schedErr_workflowMissing": {
        "zh": "任务绑定的工作流不存在",
        "en": "The workflow bound to this task doesn't exist.",
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
    "webErr_publicOnly": {
        "zh": "只能抓取公网 http/https 页面(已拦截内网/本机地址)",
        "en": "Only public http/https pages can be fetched (private and local addresses are blocked).",
    },
    "webErr_redirectPrivate": {
        "zh": "该页面跳转到了内网/本机地址,已拦截",
        "en": "The page redirected to a private or local address, so it was blocked.",
    },
    "webErr_tooManyRedirects": {
        "zh": "跳转次数过多",
        "en": "Too many redirects.",
    },
    "webErr_fetchFailed": {
        "zh": "抓取失败: {detail}",
        "en": "Fetch failed: {detail}",
    },
    # ---- B1 · 06_integrations_media ----
    "feishuErr_token": {
        "zh": "获取 tenant_access_token 失败: {detail}",
        "en": "Couldn't get a tenant_access_token: {detail}",
    },
    "feishuErr_sendText": {
        "zh": "飞书发消息失败: {detail}",
        "en": "Couldn't send the Feishu message: {detail}",
    },
    "feishuErr_download": {
        "zh": "下载飞书资源失败({status})",
        "en": "Couldn't download the Feishu resource ({status}).",
    },
    "feishuErr_qrUnsupported": {
        "zh": "当前环境不支持扫码创建,请手动填写 App ID / App Secret。",
        "en": "Creating the app by QR code isn't supported here. Enter the App ID and App Secret by hand.",
    },
    "feishuErr_noDeviceCode": {
        "zh": "飞书未返回 device_code,扫码创建暂不可用,请手动创建应用。",
        "en": "Feishu didn't return a device_code, so QR creation is unavailable for now. Create the app by hand.",
    },
    "feishuErr_sendCard": {
        "zh": "飞书发卡片失败: {detail}",
        "en": "Couldn't send the Feishu card: {detail}",
    },
    "volcErr_needsAkSk": {
        "zh": "需要账号的 AK / SK 才能拉取音色列表",
        "en": "The account's AK / SK are needed to fetch the voice list.",
    },
    "volcErr_notJson": {
        "zh": "火山 OpenAPI 返回了非 JSON 响应({status})",
        "en": "The Volcengine OpenAPI returned a non-JSON response ({status}).",
    },
    "volcErr_upstream": {
        "zh": "{detail}",
        "en": "{detail}",
    },
    "volcErr_unknown": {
        "zh": "火山 OpenAPI 返回了未知错误",
        "en": "The Volcengine OpenAPI returned an unknown error.",
    },
    "audioErr_extract": {
        "zh": "取不出这份素材的声音:{detail}",
        "en": "Couldn't extract the audio from this asset: {detail}",
    },
    "audioErr_replace": {
        "zh": "没能把处理后的声音放回视频:{detail}",
        "en": "Couldn't put the processed audio back into the video: {detail}",
    },
    "audioErr_ffmpegNoReason": {
        "zh": "ffmpeg 没有说明原因",
        "en": "ffmpeg gave no reason",
    },
    "stillErr_negativeTime": {
        "zh": "时间不能是负数",
        "en": "The time can't be negative.",
    },
    "stillErr_failed": {
        "zh": "取帧失败",
        "en": "Couldn't grab the frame.",
    },
    "stillErr_noFrame": {
        "zh": "这个时间点上没有画面 —— 是不是超过片长了?",
        "en": "There's no picture at this time — is it past the end?",
    },
    "gifErr_fps": {
        "zh": "GIF 帧率要在 1–30 fps 之间",
        "en": "The GIF frame rate must be between 1 and 30 fps.",
    },
    "gifErr_width": {
        "zh": "GIF 宽度要在 64–1920 像素之间",
        "en": "The GIF width must be between 64 and 1920 pixels.",
    },
    "gifErr_range": {
        "zh": "GIF 起点不能为负数，时长必须大于 0",
        "en": "The GIF start can't be negative, and its duration must be greater than 0.",
    },
    "gifErr_failed": {
        "zh": "视频转 GIF 失败",
        "en": "Couldn't convert the video to GIF.",
    },
    "gifErr_noOutput": {
        "zh": "视频转 GIF 没有产生有效文件",
        "en": "Converting the video to GIF produced no usable file.",
    },
    "renderErr_frameFailed": {
        "zh": "取当前帧失败:{detail}",
        "en": "Couldn't grab the current frame: {detail}",
    },
    "renderErr_frameTimeout": {
        "zh": "取当前帧超时({seconds} 秒内没画完)",
        "en": "Grabbing the current frame timed out (not done within {seconds} s).",
    },
    "renderErr_ffmpegExit": {
        "zh": "FFmpeg 异常退出,退出码 {code}",
        "en": "FFmpeg exited with code {code}",
    },
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
    "confirm_generateSound": {"zh": "生成音乐/音效: {asked}", "en": "Generate music / sound: {asked}"},
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
    "confirm_runBoardItem": {"zh": "在画板「{board}」上运行工具「{tool}」{item}{via}{warning}", "en": "Run the tool “{tool}” on board “{board}”{item}{via}{warning}"},
    "confirm_boardItemNamed": {"zh": "(工具格「{name}」)", "en": " (tool item “{name}”)"},
    "confirm_boardRunVia": {"zh": ",用你的连接「{name}」", "en": ", using your connection “{name}”"},
    #: 卡上点明「为什么要你看一眼」的那半句,按后果分(词表见 domain/effects)。画板工具格和插件工具共用。
    "confirm_effectPaid": {"zh": "(会产生费用或占用付费算力)", "en": " (this costs money or paid compute)"},
    "confirm_effectExternal": {"zh": "  ⚠️ 后果在本应用之外(插件或外部服务),撤不回", "en": "  ⚠️ Its effects are outside this app (a plugin or an outside service) and cannot be undone"},
    "confirm_effectLocalCode": {"zh": "  ⚠️ 会在你的电脑上运行代码", "en": "  ⚠️ This runs code on your computer"},
    "confirm_runPluginTool": {
        "zh": "运行插件工具「{tool}」(连接「{connection}」){args}{warning}",
        "en": "Run the plugin tool “{tool}” (connection “{connection}”){args}{warning}",
    },
    "confirm_pluginToolArgs": {"zh": ",参数:{args}", "en": ", with {args}"},
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
    # ---- 生成供应商(ai/providers):上游原话放在 {detail} 里,不翻 ----
    # 文案里**不写字面花括号**:任务失败原因那条路(render_message)总会 format 一遍,字面的 { } 会被吃掉;
    # 要显示花括号就走参数(见 pluginErr_streamNoResult 的 {shape})。
    "providerErr_apiKeyMissing": {
        "zh": "{vendor} 的 API Key 还没配置,请在设置 → 供应商配置里填写",
        "en": "{vendor} API key is not configured. Add it in Settings → Provider config.",
    },
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
        "zh": "{vendor} 的内容审核拦下了这次请求,换个说法再试:{detail}",
        "en": "{vendor} content moderation blocked this request; rephrase and try again: {detail}",
    },
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
    "providerErr_volcanoMusicKeysMissing": {
        "zh": "火山引擎音乐生成需要账号的 AK 和 SK,请到设置里把这条连接补全",
        "en": "Volcengine music generation needs the account's AK and SK; complete the connection in Settings",
    },
    "providerErr_noTaskId": {"zh": "{vendor} 没有返回任务 id", "en": "{vendor} did not return a task ID"},
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
        "zh": "音频分离的运行环境还没装好(去设置里装一次):{detail}",
        "en": "The audio separation runtime is not set up (install it once in Settings): {detail}",
    },
    "providerErr_separationRuntimeMissing": {
        "zh": "音频分离的运行环境还没准备好,去设置里装一次",
        "en": "The audio separation runtime is not ready. Install it once in Settings.",
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
        "zh": "找不到可用于创建运行环境的 Python。请重装应用,或在设置里手动指定一个 TTS 解释器。",
        "en": "No Python is available to create the runtime. Reinstall the app, or set a TTS interpreter manually in Settings.",
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
        "zh": "请先在设置的「声音克隆」里安装 F5-TTS 运行环境",
        "en": "Install the F5-TTS runtime first under Settings → Voice cloning",
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
        "zh": "Fish Speech S2 不可用:需要 fishaudio/s2-pro 权重 + 官方 fish-speech 源码检出。在设置→声音克隆填『源码目录』『模型目录』,或设置 MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR。(源码目录未找到)",
        "en": "Fish Speech S2 is unavailable: it needs the fishaudio/s2-pro weights and an official fish-speech source checkout. Fill in “Source directory” and “Model directory” under Settings → Voice cloning, or set MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR. (Source directory not found.)",
    },
    "runtimeErr_fishModelMissing": {
        "zh": "Fish Speech S2 不可用:需要 fishaudio/s2-pro 权重 + 官方 fish-speech 源码检出。在设置→声音克隆填『源码目录』『模型目录』,或设置 MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR。(模型目录缺少 codec.pth)",
        "en": "Fish Speech S2 is unavailable: it needs the fishaudio/s2-pro weights and an official fish-speech source checkout. Fill in “Source directory” and “Model directory” under Settings → Voice cloning, or set MOSAEL_FISH_REPO_DIR / MOSAEL_FISH_MODEL_DIR. (codec.pth is missing from the model directory.)",
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
    # ---- 智能体 sidecar(ai/sidecar) ----
    "aiErr_sidecarNotBuilt": {
        "zh": "pi sidecar 未构建:{path}(在 agent-sidecar 目录执行 pnpm build)",
        "en": "The pi sidecar is not built: {path} (run pnpm build in the agent-sidecar directory)",
    },
    "aiErr_noProvider": {
        "zh": "未配置可用的 AI 供应商;请在设置里添加并启用一个供应商。",
        "en": "No AI provider is available. Add and enable one in Settings.",
    },
    "aiErr_gatewayFailed": {"zh": "Gateway 调用失败", "en": "The gateway call failed"},
    "aiErr_gatewayTimeout": {"zh": "Gateway 调用超过 {seconds} 秒未返回", "en": "The gateway call did not return within {seconds} seconds"},
    "aiErr_gatewayNoResult": {"zh": "Gateway 没有返回结果", "en": "The gateway returned no result"},
    "aiErr_turnFailedCheckProvider": {
        "zh": "{detail}\n请检查 AI 供应商配置:base_url 是否为完整的 OpenAI 兼容端点(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。",
        "en": "{detail}\nCheck the AI provider settings: the base_url must be a complete OpenAI-compatible endpoint (with port and /v1, e.g. http://localhost:11434/v1), the model name must exist, and the service must be reachable.",
    },
    "aiErr_emptyReply": {
        "zh": "模型没有返回任何内容。请检查 AI 供应商配置:base_url 是否为完整的 OpenAI 兼容端点(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。",
        "en": "The model returned nothing. Check the AI provider settings: the base_url must be a complete OpenAI-compatible endpoint (with port and /v1, e.g. http://localhost:11434/v1), the model name must exist, and the service must be reachable.",
    },
    "aiErr_turnTimeout": {
        "zh": "智能体运行超过 {seconds} 秒未返回,已终止。",
        "en": "The agent ran for more than {seconds} seconds without returning and was stopped.",
    },
    "aiErr_turnTimeoutDetail": {
        "zh": "智能体运行超过 {seconds} 秒未返回,已终止。\n{detail}",
        "en": "The agent ran for more than {seconds} seconds without returning and was stopped.\n{detail}",
    },
    "aiErr_sidecarExited": {"zh": "pi sidecar 异常退出(退出码 {exit_code})", "en": "The pi sidecar exited with code {exit_code}"},
    "aiErr_compactFailed": {"zh": "压缩失败", "en": "Compaction failed"},
    "aiErr_compactNoResult": {"zh": "压缩没有返回结果", "en": "Compaction returned no result"},
    "aiErr_refreshFailed": {"zh": "刷新凭据失败", "en": "Could not refresh the credentials"},
    "aiErr_refreshNoResult": {"zh": "刷新凭据没有返回结果", "en": "Refreshing the credentials returned no result"},
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
    "wfNode_dub_subtitles_clip_ids": {"zh": "要配音的字幕条,如 {{生成字幕.clip_ids}};一条都没有时什么都不做(配 0 条、原声不动)", "en": "The subtitle cues to dub, e.g. {{generate_subtitles.clip_ids}}; with none, nothing is dubbed and the original audio is left alone"},
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
    "wfNode_browser_upload_file_path": {"zh": "或直接给本机绝对路径;与 asset_id 二选一。本机文件只有部署管理员能读,其他成员只能用管理员共享出来的文件夹里的", "en": "Or an absolute path on this computer; either this or asset_id. Only deployment admins can read files on this computer — other members can only use files inside folders an admin has shared"},
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
    "wfNode_browser_close_desc": {"zh": "关闭会话:临时会话顺带清掉 cookie/存储。这次运行结束时(成功、失败或取消)会自动关;想在用完那一刻就释放视图和池档案的占用,接在那一步后面。", "en": "Close the session; a throwaway session also has its cookies and storage wiped. The run closes it automatically when it ends (succeeded, failed or cancelled); add this node to release the view and the pool profile as soon as you are done with them."},
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
    "wfErr_generateNodeText": {"zh": "节点「{node}」还不能跑:{reason}", "en": "Node “{node}” can't run yet: {reason}"},
    "wfErr_llmNotJson": {"zh": "LLM 未返回合法 JSON", "en": "The model did not return valid JSON"},
    "wfErr_browserSessionNotInWorkspace": {"zh": "浏览器会话不存在,或不在这个工作区里", "en": "That browser session does not exist or is not in this workspace"},
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
    "jobKind_board_write": {"zh": "画板写字", "en": "Board writing"},
    "jobKind_board_run": {"zh": "画板工具", "en": "Board tool"},
    "jobKind_proxy": {"zh": "预览代理", "en": "Preview proxy"},
    "jobKind_other": {"zh": "任务", "en": "Task"},
    "jobMsg_boardWriteQueued": {"zh": "写字排队中", "en": "Writing queued"},
    "jobMsg_boardWriteRunning": {"zh": "正在写", "en": "Writing"},
    "jobMsg_boardWriteDone": {"zh": "写好了", "en": "Written"},
    "jobMsg_boardRunQueued": {"zh": "「{name}」排队中", "en": "“{name}” queued"},
    "jobMsg_boardRunRunning": {"zh": "正在跑「{name}」", "en": "Running “{name}”"},
    "jobMsg_boardRunDone": {"zh": "「{name}」跑完了", "en": "“{name}” finished"},
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
    # -- B3·画板与标记 --
    "boardErr_revisionConflict": {"zh": "画板已被其他操作更新（本地 v{base}，当前 v{current}）", "en": "This board was changed somewhere else (yours is v{base}, the latest is v{current}). Reload it and try again."},
    "boardErr_notFound": {"zh": "画板不存在", "en": "This board doesn't exist."},
    "boardErr_nameEmpty": {"zh": "画板名不能为空", "en": "Give the board a name."},
    "boardErr_itemNotFound": {"zh": "画板项不存在:{item_id}", "en": "There's no item {item_id} on this board."},
    "boardErr_itemIdMissing": {"zh": "画板项不存在:(空)", "en": "No board item was given — pass an item id."},
    "boardErr_fieldNotNumber": {"zh": "{field} 必须是数字,收到 {value}", "en": "{field} must be a number, but got {value}."},
    "boardErr_fieldNotFinite": {"zh": "{field} 必须是有限的数字,收到 {value}", "en": "{field} must be a finite number, but got {value}."},
    "boardErr_itemFieldNotNumber": {"zh": "画板项 {item_id} 的 {field} 必须是数字,收到 {value}", "en": "Board item {item_id}: {field} must be a number, but got {value}."},
    "boardErr_itemFieldNotFinite": {"zh": "画板项 {item_id} 的 {field} 必须是有限的数字,收到 {value}", "en": "Board item {item_id}: {field} must be a finite number, but got {value}."},
    "boardErr_itemFieldNotObject": {"zh": "画板项 {item_id} 的 {field} 必须是对象", "en": "Board item {item_id}: {field} must be an object."},
    "boardErr_itemFieldNotString": {"zh": "画板项 {item_id} 的 {field} 必须是字符串", "en": "Board item {item_id}: {field} must be a string."},
    "boardErr_itemFieldNotArray": {"zh": "画板项 {item_id} 的 {field} 必须是数组", "en": "Board item {item_id}: {field} must be an array."},
    "boardErr_itemFieldNotBool": {"zh": "画板项 {item_id} 的 {field} 必须是布尔值", "en": "Board item {item_id}: {field} must be true or false."},
    "boardErr_itemFieldInvalid": {"zh": "画板项 {item_id} 的 {field} 不合法", "en": "Board item {item_id} has an invalid {field}."},
    "boardErr_itemSizeNotPositive": {"zh": "画板项 {item_id} 的 {field} 必须大于 0", "en": "Board item {item_id}: {field} must be greater than 0."},
    "boardErr_sizeNotPositive": {"zh": "{field} 必须大于 0", "en": "{field} must be greater than 0."},
    "boardErr_promptTooLong": {"zh": "画板项 {item_id} 的提示词超过 {limit} 字", "en": "The prompt on board item {item_id} is longer than {limit} characters. Shorten it."},
    "boardErr_textTooLong": {"zh": "画板项 {item_id} 的文字超过 {limit} 字", "en": "The text on board item {item_id} is longer than {limit} characters. Shorten it."},
    "boardErr_sourceAssetsNotObjects": {"zh": "画板项 {item_id} 的 form.source_assets 必须是对象数组", "en": "Board item {item_id}: form.source_assets must be an array of objects."},
    "boardErr_promptDocumentNotDoc": {"zh": "画板项 {item_id} 的 form.prompt_document 必须是 TipTap doc 对象", "en": "Board item {item_id}: form.prompt_document must be a TipTap doc object."},
    "boardErr_formConfigTooLarge": {"zh": "画板项 {item_id} 的工具配置过大", "en": "Board item {item_id}: the tool settings are too large."},
    "boardErr_bindingsNotRefs": {"zh": "画板项 {item_id} 的绑定 {field} 必须是一列 {{\"from\": 上游那一格的 id}}", "en": "Board item {item_id}: binding {field} must be a list of {{\"from\": upstream item id}}."},
    "boardErr_textFormatNoteOnly": {"zh": "只有便签有正文格式,{kind} 没有", "en": "Only notes have a text format; a {kind} item doesn't."},
    "boardErr_nodeNotOnBoard": {"zh": "「{node}」不能在画板上跑", "en": "“{node}” can't run on a board."},
    "boardErr_toolInternal": {"zh": "工具「{tool}」只给应用内部调用,不能在画板上跑", "en": "The tool “{tool}” is for the app's internal use and can't run on a board."},
    "boardErr_formNeedsTool": {"zh": "画板项 {item_id} 的表单要写明跑哪个工具(producer 写成 node:<节点类型>,见 list_board_producers),收到的是「{producer}」", "en": "Board item {item_id}: the form must name a tool to run (producer as node:<node type>, see list_board_producers); got “{producer}”."},
    "boardErr_formOnlyOnAction": {"zh": "只有工具格(action)的表单能这样写,画板项 {item_id} 是 {kind}", "en": "Only a tool item (action) takes a form this way; board item {item_id} is a {kind}."},
    "boardErr_toolConfigUnknownField": {"zh": "工具「{tool}」没有字段「{field}」(有的是:{fields})", "en": "The tool “{tool}” has no field “{field}” (it has: {fields})."},
    "boardErr_bindingUnknownField": {"zh": "工具「{tool}」没有能接上游的字段「{field}」(能接的:{fields})", "en": "The tool “{tool}” has no field “{field}” that takes an upstream item (these do: {fields})."},
    "boardErr_bindingFieldNotBindable": {"zh": "工具「{tool}」的字段「{field}」不接上游(数字、下拉和专用控件直接填在 config 里)", "en": "The tool “{tool}” field “{field}” doesn't take an upstream item (numbers, choices and special pickers go straight into config)."},
    "boardErr_bindingSourceMissing": {"zh": "字段「{field}」接的上游「{source}」不在画布上", "en": "Field “{field}” is bound to “{source}”, which isn't on the board."},
    "boardErr_bindingNotWired": {"zh": "字段「{field}」接的「{source}」没有连到「{item_id}」:先用 connect 连一根从它到工具格的线", "en": "Field “{field}” is bound to “{source}”, but there is no edge from it to “{item_id}”. Connect them first."},
    "boardErr_bindingKindMismatch": {"zh": "字段「{field}」接不了「{source}」:它是 {kind},这个字段要的是 {kinds}", "en": "Field “{field}” can't take “{source}”: that is a {kind} item, and this field takes {kinds}."},
    "boardErr_pluginNotConnected": {"zh": "你还没有能跑「{tool}」的「{plugin}」连接:到插件页新建或启用一个,再回来运行", "en": "You have no “{plugin}” connection that can run “{tool}”. Create or enable one on the Plugins page, then run it again."},
    "boardProducer_generate": {"zh": "生成", "en": "Generate"},
    "boardProducer_generate_desc": {"zh": "用生成模型出图、出片、出声音", "en": "Create images, video or sound with a generation model."},
    "boardProducer_write": {"zh": "写字", "en": "Write"},
    "boardProducer_write_desc": {"zh": "让 AI 往这张便签上写或改", "en": "Have AI write or rewrite this note."},
    "boardProducer_speak": {"zh": "配音", "en": "Voice-over"},
    "boardProducer_speak_desc": {"zh": "把一段文字念成音频", "en": "Read a piece of text aloud as audio."},
    "boardProducer_trim": {"zh": "截一段", "en": "Trim"},
    "boardProducer_trim_desc": {"zh": "从一段视频或音频里截出一段", "en": "Cut a stretch out of a video or audio clip."},
    "boardErr_promptDocumentTooLarge": {"zh": "画板项 {item_id} 的 form.prompt_document 过大", "en": "Board item {item_id}: form.prompt_document is too large. Shorten the prompt."},
    "boardErr_runStatusInvalid": {"zh": "画板项 {item_id} 的 run.status 不合法:{status}", "en": "Board item {item_id} has an invalid run.status: {status}"},
    "boardErr_finishedRunHasJob": {"zh": "画板项 {item_id} 已结束却仍带有 job_id", "en": "Board item {item_id} has finished running but still carries a job_id. Drop the job_id."},
    "boardErr_canvasNotObject": {"zh": "画布必须是一个对象", "en": "The canvas must be an object."},
    "boardErr_canvasFieldNotArray": {"zh": "画布的 {field} 必须是数组", "en": "The canvas {field} must be an array."},
    "boardErr_tooManyItems": {"zh": "一张画板最多 {limit} 项,收到 {count} 项", "en": "A board can hold at most {limit} items; this one has {count}. Remove some first."},
    "boardErr_itemNotObject": {"zh": "画板项必须是对象", "en": "Each board item must be an object."},
    "boardErr_itemMissingField": {"zh": "画板项缺少 {field}", "en": "A board item is missing {field}."},
    "boardErr_itemIdEmpty": {"zh": "画板项的 id 不能为空", "en": "A board item's id can't be empty."},
    "boardErr_duplicateItemId": {"zh": "画板项 id 重复:{item_id}", "en": "Two board items share the id {item_id}. Give each one its own id."},
    "boardErr_unknownItemKind": {"zh": "未知的画板项类型:{kind};可用的是 {kinds}", "en": "Unknown board item type: {kind}. Use one of: {kinds}."},
    "boardErr_legacyRunFields": {"zh": "画板项 {item_id} 使用了已停用的顶层运行态；请改用 run.status/run.job_id/run.error", "en": "Board item {item_id} uses the retired top-level run fields. Use run.status / run.job_id / run.error instead."},
    "boardErr_unknownColor": {"zh": "未知的颜色:{color};可用的是 {colors}", "en": "Unknown color: {color}. Use one of: {colors}."},
    "boardErr_documentNeedsNote": {"zh": "文档节点需要有效的笔记 ID", "en": "A document item needs a valid note ID."},
    "boardErr_documentNeedsRevision": {"zh": "文档节点需要有效的引用版本", "en": "A document item needs a valid note revision to reference."},
    "boardErr_sceneNeedsId": {"zh": "3D 场景节点需要 scene_id", "en": "A 3D scene item needs a scene_id."},
    "boardErr_sceneNotInWorkspace": {"zh": "3D 场景不属于当前工作区", "en": "That 3D scene isn't in this workspace."},
    "boardErr_titleTooLong": {"zh": "画板项 {item_id} 的名字超过 {limit} 字", "en": "The name of board item {item_id} is longer than {limit} characters. Shorten it."},
    "boardErr_frameHasNoText": {"zh": "分组框 {item_id} 没有正文:它的名字写在 title 里", "en": "Frame {item_id} has no text; its name goes in title."},
    "boardErr_moveChildrenFrameOnly": {"zh": "只有分组框有 move_children,{kind} 没有", "en": "Only frames have move_children; a {kind} item doesn't."},
    "boardErr_edgeNotObject": {"zh": "连线必须是对象", "en": "Each connection must be an object."},
    "boardErr_edgeDangling": {"zh": "连线两端必须都是画板上的项:{source} → {target}", "en": "Both ends of a connection must be items on the board: {source} → {target}"},
    "boardErr_edgeLabelNotString": {"zh": "连线的 label 必须是字符串", "en": "A connection's label must be a string."},
    "boardErr_edgeNotFound": {"zh": "连线不存在:{edge_id}", "en": "There's no connection {edge_id} on this board."},
    "boardErr_edgeIdMissing": {"zh": "连线不存在:(空)", "en": "No connection was given — pass an edge id."},
    "boardErr_opNotObject": {"zh": "算子必须是对象", "en": "Each board operation must be an object."},
    "boardErr_selfEdge": {"zh": "不能把一项连到它自己", "en": "An item can't be connected to itself."},
    "boardErr_unknownOp": {"zh": "不支持的画板算子:{kind}", "en": "Unsupported board operation: {kind}"},
    "boardErr_opKindMissing": {"zh": "不支持的画板算子:(空)", "en": "A board operation is missing its kind."},
    "boardErr_nothingToSpeak": {"zh": "没有可念的文字", "en": "There's no text to read aloud."},
    "boardErr_assetNotInWorkspace": {"zh": "这个工作区里没有这份素材", "en": "This asset isn't in this workspace."},
    "boardErr_noOutput": {"zh": "任务结束了,但没有交回任何产出", "en": "The task finished without producing anything."},
    "boardErr_itemBusy": {"zh": "这一格还在生成,等它结束(或在任务中心取消)再来", "en": "This item is still generating. Wait for it to finish, or cancel it in the task center, then try again."},
    "boardErr_writeNeedsPrompt": {"zh": "先写点要求,再让它写", "en": "Write what you want first, then ask it to write."},
    "boardErr_unknownProducer": {"zh": "画板上没有「{producer}」这种产出方式(可用:{producers})", "en": "Boards have no producer called \"{producer}\" (available: {producers})."},
    "boardErr_producerFormInvalid": {"zh": "「{producer}」的表单里 {field} 不合法:{detail}", "en": "The \"{producer}\" form has an invalid {field}: {detail}"},
    "boardErr_producerCannotHost": {"zh": "「{producer}」不能挂在{kind}这种格子上", "en": "The \"{producer}\" producer can't sit on a {kind} item."},
    "trimErr_unsupportedKind": {"zh": "只能截取视频或音频", "en": "Only video or audio can be trimmed."},
    "trimErr_muteNeedsVideo": {"zh": "只有视频能去掉声音 —— 音频去掉声音就什么都不剩了", "en": "Only video can drop its sound — an audio clip without its sound is empty."},
    "trimErr_noLocalFile": {"zh": "素材没有本地文件", "en": "This asset has no local file."},
    "trimErr_endBeforeStart": {"zh": "结束时间要晚于开始时间", "en": "The end time must be after the start time."},
    "trimErr_negativeStart": {"zh": "开始时间不能是负数", "en": "The start time can't be negative."},
    "trimErr_fileMissing": {"zh": "素材文件缺失", "en": "The asset's file is missing."},
    "trimErr_failed": {"zh": "截取失败", "en": "Trimming failed."},
    "trimErr_empty": {"zh": "截取出来是空的 —— 这段范围里没有内容", "en": "The trimmed clip came out empty — there's nothing in that range. Pick a different range."},
    "markerErr_keyNotAllowed": {"zh": "快捷键里不能用 {value} 这个键", "en": "The key {value} can't be used in a shortcut."},
    "markerErr_shortcutNotString": {"zh": "标记的 shortcut 必须是字符串", "en": "A marker's shortcut must be a string."},
    "markerErr_shortcutEmpty": {"zh": "标记的 shortcut 不能为空", "en": "A marker's shortcut can't be empty."},
    "markerErr_unknownModifier": {"zh": "快捷键里不认识的修饰键:{modifier}", "en": "Unknown modifier key in the shortcut: {modifier}"},
    "markerErr_duplicateModifier": {"zh": "快捷键里重复的修饰键:{modifier}", "en": "The shortcut repeats the modifier key {modifier}."},
    "markerErr_fieldNotNumber": {"zh": "标记 {marker_id} 的 {field} 必须是数字,收到 {value}", "en": "Marker {marker_id}: {field} must be a number, but got {value}."},
    "markerErr_fieldNotFinite": {"zh": "标记 {marker_id} 的 {field} 不是有限数", "en": "Marker {marker_id}: {field} isn't a finite number."},
    "markerErr_notArray": {"zh": "markers 必须是数组", "en": "markers must be an array."},
    "markerErr_tooMany": {"zh": "一份文档最多 {limit} 个标记,收到 {count} 个", "en": "A document can have at most {limit} markers; this one has {count}. Remove some first."},
    "markerErr_notObject": {"zh": "标记必须是对象", "en": "Each marker must be an object."},
    "markerErr_idEmpty": {"zh": "标记的 id 不能为空", "en": "A marker's id can't be empty."},
    "markerErr_idTooLong": {"zh": "标记的 id 过长:{id_prefix}…", "en": "A marker's id is too long: {id_prefix}…"},
    "markerErr_duplicateId": {"zh": "标记 id 重复:{marker_id}", "en": "Two markers share the id {marker_id}. Give each one its own id."},
    "markerErr_nameNotString": {"zh": "标记 {marker_id} 的 name 必须是字符串", "en": "Marker {marker_id}: name must be a string."},
    "markerErr_shortcutTaken": {"zh": "快捷键 {combo} 已经绑给了标记「{marker}」", "en": "The shortcut {combo} is already bound to the marker “{marker}”. Pick another key."},
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
        "zh": "{label} 还没有运行环境:没有任何 Python 解释器装了它。去设置的「声音克隆」那一页点「下载」,装一次就好;想马上出声可以先在上面的引擎里选「Edge 免费在线合成」,它不需要安装。",
        "en": "{label} has no runtime yet: no Python interpreter has it installed. Go to Settings → Voice cloning and click Download — it only needs installing once. To get audio right away, pick the free Edge online engine above; it needs no install.",
    },
    "voiceErr_noWeights": {
        "zh": "{label} 的模型权重还没下好,现在合成不出声音。去设置的「声音克隆」那一页点「下载」补上 —— 这里不会替你下:那是几个 GB 的事,该由你决定什么时候开始。",
        "en": "{label}'s model weights aren't downloaded yet, so it can't synthesise anything. Go to Settings → Voice cloning and click Download — it won't start on its own here, since it's several GB and you decide when.",
    },
    "voiceErr_unknownEngine": {"zh": "不认识的本地引擎:{engine}", "en": "Unknown local engine: {engine}"},
    "voiceErr_synthNoReason": {
        "zh": "语音合成失败,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。",
        "en": "Speech synthesis failed and the worker process left no reason. Try once more; if it keeps happening, please report it.",
    },
    "voiceErr_synthTorchcodec": {
        "zh": "语音合成失败:音频解码库(torchcodec)加载不了:它需要一份版本对得上的 FFmpeg。升级引擎依赖通常就能解决(设置 →「声音克隆」→ 下载);若仍然如此,装一个 Homebrew 的 ffmpeg 即可,系统那份不会被改动。",
        "en": "Speech synthesis failed: the audio decoding library (torchcodec) couldn't load — it needs a matching FFmpeg version. Upgrading the engine's dependencies usually fixes it (Settings → Voice cloning → Download); if not, install ffmpeg from Homebrew — the system copy is left untouched.",
    },
    "voiceErr_synthMissingModule": {
        "zh": "语音合成失败:{detail} —— 引擎的运行环境不完整。去设置的「声音克隆」那一页点「下载」,它会把缺的依赖补上。",
        "en": "Speech synthesis failed: {detail} — the engine's runtime is incomplete. Go to Settings → Voice cloning and click Download to add the missing dependencies.",
    },
    "voiceErr_synthFailed": {"zh": "语音合成失败:{detail}", "en": "Speech synthesis failed: {detail}"},
    "voiceErr_synthNoAudio": {
        "zh": "语音合成失败:worker 报成功却没有产出音频",
        "en": "Speech synthesis failed: the worker reported success but produced no audio.",
    },
    "voiceErr_jaCloneNeedsWeights": {
        "zh": "这段文本是日文,而本地克隆现在装的权重念不了它。去设置的「声音克隆」下载日文模型(约 {size} GB)后就能用你自己的音色念;不想等的话,改用 Edge TTS 的日文音色或 OpenAI TTS。",
        "en": "This text is Japanese, and the local cloning weights installed now can't read it. Download the Japanese model (about {size} GB) under Settings → Voice cloning to read it in your own voice — or, to skip the wait, use a Japanese Edge TTS voice or OpenAI TTS.",
    },
    "voiceErr_koCloneNeedsWeights": {
        "zh": "这段文本是韩文,而本地克隆现在装的权重念不了它。去设置的「声音克隆」下载韩文模型(约 {size} GB)后就能用你自己的音色念;不想等的话,改用 Edge TTS 的韩文音色或 OpenAI TTS。",
        "en": "This text is Korean, and the local cloning weights installed now can't read it. Download the Korean model (about {size} GB) under Settings → Voice cloning to read it in your own voice — or, to skip the wait, use a Korean Edge TTS voice or OpenAI TTS.",
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
    # 字幕配音与原声处理(domain/voices/subtitle_dub.py、original_audio.py)
    "dubErr_originalAudioMode": {"zh": "原声处理方式只能是 {modes}", "en": "The original-audio mode must be one of {modes}."},
    "dubErr_separationUnavailableForMode": {
        "zh": "选择了「只去掉人声」，但音频分离引擎尚不可用；请先到设置中安装分离引擎，或明确改选「静音」",
        "en": "You chose \"Remove voice only\", but no audio separation engine is available yet. Install one in Settings first, or choose \"Mute\" instead.",
    },
    "dubErr_separationUnavailable": {
        "zh": "音频分离引擎尚不可用；请先到设置中安装",
        "en": "No audio separation engine is available yet — install one in Settings first.",
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
    "asrErr_unsupportedEngine": {"zh": "不支持的 ASR 引擎:{engine}", "en": "Unsupported ASR engine: {engine}"},
    "asrErr_engineRuntimeMissing": {
        "zh": "所选 ASR 引擎 {engine} 的运行环境不可用,请先到设置的「转写模型」安装。",
        "en": "The runtime for the selected ASR engine {engine} isn't available. Install it under Settings → Transcription models first.",
    },
    "asrErr_noRuntime": {
        "zh": "缺的是运行环境,不是模型:模型权重已经下好的话不用再下一遍,但还没有任何 Python 解释器装了 funasr 或 whisperx。去设置的「转写模型」那一页点「安装运行环境」,装一次就好。",
        "en": "What's missing is the runtime, not the model: if the weights are already downloaded there's no need to download them again, but no Python interpreter has funasr or whisperx installed. Go to Settings → Transcription models and click Install runtime — it only needs doing once.",
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
    # 降噪(domain/denoise.py)
    "denoiseErr_unknownEngine": {"zh": "没有这个降噪引擎:{engine}", "en": "There's no noise-reduction engine called {engine}."},
    "denoiseErr_noEngine": {"zh": "没有可用的降噪引擎", "en": "No noise-reduction engine is available."},
    "denoiseErr_engineNotReady": {"zh": "降噪引擎 {engine} 还没准备好", "en": "The noise-reduction engine {engine} isn't ready yet."},
    "denoiseErr_notMedia": {"zh": "只有音频或视频素材可以降噪", "en": "Only audio or video assets can be denoised."},
    "denoiseErr_fileMissing": {"zh": "这份素材的文件找不到了", "en": "This asset's file can't be found."},
    "denoiseErr_noLocalFile": {"zh": "这份素材没有本地文件", "en": "This asset has no local file."},
    # 人声与背景音分离(domain/separation.py)
    "separationErr_noEngine": {"zh": "没有可用的音频分离引擎", "en": "No audio separation engine is available."},
    "separationErr_noEngineInstall": {
        "zh": "没有可用的音频分离引擎 —— 先在设置里装一个",
        "en": "No audio separation engine is available — install one in Settings first.",
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
            "装一个对象存储插件(火山引擎 TOS / 阿里云 OSS / 腾讯云 COS / Amazon S3)之后它会自动传上去 ——"
            "在「插件」页里装并填上桶和密钥;或者直接粘一条你已有的公网直链。"
        ),
        "en": (
            "“{asset}” is a local asset, but this model only accepts a public link here. "
            "Install an object storage plugin (Volcengine TOS / Alibaba Cloud OSS / Tencent Cloud COS / Amazon S3) "
            "and it will be uploaded automatically — install it on the Plugins page and fill in the bucket and keys. "
            "Or paste a public direct link you already have."
        ),
    },
    "genErr_uploaderIncomplete": {
        "zh": "「{plugin}」还没配好({missing}),所以「{asset}」传不上去。去插件页把它补齐,或者直接粘一条公网直链。",
        "en": "“{plugin}” isn't fully set up (missing: {missing}), so “{asset}” can't be uploaded. Complete it on the Plugins page, or paste a public direct link.",
    },
    "genErr_uploaderAmbiguous": {
        "zh": "你配好了几家对象存储({names}),「{asset}」要传去哪一家还没定。去「设置 → 素材外链」里选一家,再生成一次。",
        "en": "You've set up several object storage services ({names}) and haven't chosen where “{asset}” goes. Pick one under Settings → Asset links, then generate again.",
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
    "genErr_modelNotEnabled": {
        "zh": "生成模型未启用或不存在",
        "en": "The generation model isn't enabled or doesn't exist.",
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
        "zh": "具名会话需要合法名称(字母/数字/-/_)",
        "en": "A named session needs a valid name (letters, digits, - or _).",
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
        "zh": "浏览器动作超时(执行器未响应)",
        "en": "The browser action timed out (the executor didn't respond).",
    },
    "browserErr_invalidActionStatus": {"zh": "非法动作状态", "en": "Invalid action status."},
    "browserErr_actionNotFound": {"zh": "动作不存在", "en": "Action not found."},
    "browserErr_leaseMismatch": {
        "zh": "租约令牌不匹配:这条动作已经不归你了",
        "en": "Lease token mismatch: this action no longer belongs to you.",
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
    "assetErr_notFoundRef": {"zh": "素材不存在: {ref}", "en": "Asset not found: {ref}"},
    "assetErr_otherWorkspace": {"zh": "这份素材不属于当前工作区", "en": "This asset doesn't belong to the current workspace."},
    "assetErr_noFileYet": {
        "zh": "素材 {name} 还没有文件(可能仍在生成中)",
        "en": "Asset {name} has no file yet (it may still be generating).",
    },
    "assetErr_fileLost": {"zh": "素材 {name} 的文件已丢失", "en": "The file for asset {name} is missing."},
    "gifErr_notVideo": {"zh": "只有视频素材可以转换为 GIF", "en": "Only video assets can be converted to GIF."},
    "gifErr_noLocalFile": {"zh": "视频素材没有本地文件", "en": "The video asset has no local file."},
    "gifErr_badParams": {"zh": "GIF 参数超出允许范围", "en": "The GIF settings are out of the allowed range."},
    "gifErr_fileMissing": {"zh": "视频素材文件不存在", "en": "The video file is missing."},
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
    "agentErr_loginSidecarMissing": {
        "zh": "pi sidecar 未构建:{path}(在 agent-sidecar 目录执行 pnpm build)",
        "en": "The pi sidecar is not built: {path} (run pnpm build in the agent-sidecar directory).",
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
        "zh": "字幕轨没有声音,不能独奏或闪避",
        "en": "A subtitle track has no sound, so it can't be soloed or ducked.",
    },
    "seqErr_detachAudioVideoOnly": {"zh": "只能从视频片段分离音频", "en": "Audio can only be detached from a video clip."},
    "seqErr_clipNoAudioSource": {"zh": "该片段没有音频源", "en": "This clip has no audio source."},
    "seqErr_transformNotNumber": {"zh": "transform.{key} 必须是数字", "en": "transform.{key} must be a number."},
    "seqErr_canvasSizeRange": {"zh": "画幅尺寸需在 16–8192 之间", "en": "The frame size must be between 16 and 8192."},
    "seqErr_revisionConflict": {
        "zh": "这个序列刚被改过,请刷新后重试",
        "en": "This sequence was just changed. Refresh and try again.",
    },
    "seqErr_unknownOp": {"zh": "不认识的时间线操作: {kind}", "en": "Unknown timeline operation: {kind}"},
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
        return text.format(**_resolve_params(params, locale))
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def fragment(key: str, **params: Any) -> Any:
    """摘要里被拼进去的**那半句**,留成 key 而不是当场翻成字。

    确认卡的措辞是拼出来的(「给 *12 条字幕* 配音 *,并变速压回原段落长度*」),而拼进去的
    每一段自己也是文案。当场翻的话,外层就算存了 key,内层还是冻成了写它那天的语言。

    返回的是一个带 `__key` 的小字典,渲染(`t` / `render_message`)时递归展开 —— 它落进
    JSON 列(确认卡的 `summary_params`、任务的 `error_params`),所以形状必须是能 JSON 化的。

    报错里提到的字段名也是这种半句:「{field} 必须是整数」里的 field 在中文界面叫「条数上限」、
    英文界面叫「Limit」。当场翻成字塞进参数,外层句子按读的人的语言翻了,里面那半截还是写它
    那天的语言。
    """
    return {"__key": key, "params": params} if key else ""


def stored_param(value: Any) -> Any:
    """一个参数落库(JSON 列)前的形状:文案片段和列表原样留着,读的时候再翻、再按读的人的
    习惯连起来(见 _resolve_params);其余写成字。"""
    if isinstance(value, dict) and "__key" in value:
        return value
    if isinstance(value, (list, tuple)):
        return [stored_param(one) for one in value]
    return str(value)


def _resolve_params(params: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """参数里带 `__key` 的那些(见 fragment)先各自按这个语言渲染,再交给外层去填。"""

    def resolve(value: Any) -> Any:
        if isinstance(value, dict) and "__key" in value:
            return render_message(str(value["__key"]), locale, value.get("params") or {})
        if isinstance(value, list):
            # **连接号也随语言变**:中文用顿号,英文用逗号加空格。先翻每一段,再按读的人的
            # 习惯连起来 —— 反过来(先连再翻)得到的是一串翻不动的拼接物。
            return _text("punct_listSep", locale).join(str(resolve(one)) for one in value)
        return value

    return {name: resolve(value) for name, value in (params or {}).items()}


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
        return text.format(**_resolve_params(params, locale))
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def tr(key: str, **params: object) -> str:
    """按**这次请求**的语言翻一个 key(语言由中间件放进 ContextVar,见 app/api/middleware)。

    路由里直接写的报错(HTTPException 的 detail)用它;领域错误用 LocalizedError。
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

    @classmethod
    def relay(cls, exc: BaseException) -> "LocalizedError":
        """把别的领域的错误转述成这一类,**带着它的 key 和参数**。

        此前各处写的是 `XxxError(str(exc))`:上游那句话在抛出那一刻就翻成了字,key 丢了 ——
        落进任务失败原因、接口 detail 的只剩写下它那一刻的语言。认不出 key 的(第三方库的原话)
        照旧当字面量:`t` 查不到就原样返回那句话。
        """
        key = str(getattr(exc, "key", "") or "")
        if is_message_key(key):
            return cls(key, **dict(getattr(exc, "params", None) or {}))
        return cls(str(exc))


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

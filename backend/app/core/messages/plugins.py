"""后端文案 · 插件、插件包与插件连接(分区 B1)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- B1 · 01_plugins ----
    "pkgSource_pypiTitle": {"zh": "PyPI 镜像", "en": "PyPI mirror"},
    "pkgSource_npmTitle": {"zh": "npm 镜像", "en": "npm registry"},
    "pkgSource_pypiOfficial": {"zh": "官方 PyPI", "en": "Official PyPI"},
    "pkgSource_npmOfficial": {"zh": "官方 npm", "en": "Official npm"},
    "pkgSource_tsinghua": {"zh": "清华大学", "en": "Tsinghua University"},
    "pkgSource_aliyun": {"zh": "阿里云", "en": "Alibaba Cloud"},
    "pkgSource_tencent": {"zh": "腾讯云", "en": "Tencent Cloud"},
    "pkgSource_huawei": {"zh": "华为云", "en": "Huawei Cloud"},
    "pkgSource_npmmirror": {"zh": "npmmirror(阿里)", "en": "npmmirror (Alibaba)"},
    "pkgSource_pytorchOfficial": {"zh": "官方(download.pytorch.org)", "en": "Official (download.pytorch.org)"},
    "pkgSource_nju": {"zh": "南京大学", "en": "Nanjing University"},
    "pluginErr_packageSourceUnknown": {"zh": "认不出的包生态:{source}", "en": "Unknown package ecosystem: {source}"},
    "pluginErr_packageSourceUrl": {
        "zh": "镜像地址要以 http:// 或 https:// 开头:{url}",
        "en": "A mirror address must start with http:// or https://: {url}",
    },
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
    #: 数组入参收到「名字 → 值」的映射(见 plugins.inputs._as_list):旧版表单的写法,或上游交错了形状。
    "pluginErr_listGotMapping": {
        "zh": "「{field}」要的是一串值,收到的却是「名字 → 值」的映射(旧版表单的写法,或上游交来的形状不对):"
              "请在节点上把它重新填成一行一项",
        "en": "“{field}” takes a list of values but got a name → value mapping (the old form's format, or an upstream "
              "output of the wrong shape): refill it on the node, one item per row",
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
    "pluginBlocked_unauthorized": {
        "zh": "还没授权 —— 填好应用凭据后点「去授权」",
        "en": "Not authorized yet — fill in the app credentials, then click Authorize",
    },
    "pluginBlocked_permissionsPending": {
        "zh": "还没授予权限:{names}。到插件页这个连接的「权限」里授予后才能用",
        "en": "Permissions not granted yet: {names}. Grant them under Permissions on this connection in the Plugins page to use it",
    },
    "pluginBlocked_permissionsAdded": {
        "zh": "插件更新后多要了 {n} 项权限:{names}。这个连接先停用了,到插件页这个连接上授予后恢复(之前授予的不受影响)",
        "en": "The plugin update asks for {n} more permission(s): {names}. This connection is paused until you grant them on the Plugins page (earlier grants are kept)",
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
    "pluginErr_networkMode": {
        "zh": "不认识的网络设置「{mode}」:只能是跟随 Mosael、直连或走指定代理",
        "en": "Unknown network setting “{mode}”: it must be follow Mosael, direct, or a proxy.",
    },
    "pluginErr_proxyUrl": {
        "zh": "代理地址「{url}」不对:要写全,例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080",
        "en": "The proxy address “{url}” is incomplete: write it in full, e.g. http://127.0.0.1:7890 or socks5://127.0.0.1:1080.",
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
    "pluginErr_streamNoResult": {
        "zh": "插件没有给出结果就结束了(最后一行应当是 {shape})",
        "en": "The plugin finished without a result (its last line should be {shape}).",
    },
    "modelLibErr_notProvided": {
        "zh": "「{name}」不提供模型库:它的插件没有认领 model_library",
        "en": "“{name}” has no model library: its plugin does not provide model_library",
    },
    "modelLibErr_badUrl": {
        "zh": "这不是一个能下载的链接:要以 http:// 或 https:// 开头",
        "en": "This is not a downloadable link: it must start with http:// or https://",
    },
    "modelLibErr_badFilename": {
        "zh": "文件名「{name}」不行:只能是一个文件名,不能带斜杠、反斜杠、冒号这类路径符号,也不能是 . 或 ..",
        "en": "The file name “{name}” won't do: it must be a single name without slashes, backslashes or colons, and not . or ..",
    },
    "modelLibErr_badFolder": {
        "zh": "目录「{name}」不行:选这台服务器上的一个模型目录(如 loras)",
        "en": "The folder “{name}” won't do: pick one of the server's model folders (e.g. loras)",
    },
    "modelLibErr_tooManyNodes": {
        "zh": "一次最多查 {n} 格",
        "en": "At most {n} inputs can be looked up at once",
    },
    "modelLibErr_badAnswer": {
        "zh": "{name} 的回答形状不对",
        "en": "{name} gave a malformed answer",
    },
    "modelLibErr_cantSavePreview": {
        "zh": "这台 ComfyUI 存不了预览图:{note}",
        "en": "This ComfyUI can't save previews: {note}",
    },
    "modelLibErr_nothingToLookUp": {
        "zh": "没有要找的文件:这台服务器上的模型都有预览图了",
        "en": "Nothing to look up: every model on this server already has a preview",
    },
    "modelLibErr_noSuchLookup": {
        "zh": "没有这个找图任务(不是这个连接的,或者已经清掉了)",
        "en": "No such preview lookup (it belongs to another connection, or was cleared)",
    },
    "modelLibErr_noElsewherePreview": {
        "zh": "这个文件还没有从 Civitai 取来的预览图:先「在 Civitai 上找」",
        "en": "This file has no preview from Civitai yet: use “Find on Civitai” first",
    },
    "modelLibErr_confirmFilenameMatch": {
        "zh": "这个文件是按文件名和大小在 Civitai 上对上的,存回之前要确认是同一个文件",
        "en": "This file was matched on Civitai by name and size; confirm it's the same file before saving",
    },
    "modelLibErr_alreadyHasPreview": {
        "zh": "那台服务器上已经有这个文件的预览图了,不覆盖",
        "en": "That server already has a preview for this file; it won't be overwritten",
    },
    "modelLibErr_elsewhereUnreachable": {
        "zh": "这张示例图这会儿取不到(Civitai 没回应),过一会儿再试",
        "en": "Couldn't fetch this example image right now (Civitai didn't answer); try again in a moment",
    },
    "modelLibErr_instanceGone": {
        "zh": "这个插件连接已经删掉了,下载没开始",
        "en": "This plugin connection was deleted; the download did not start",
    },
    "workflowLibErr_notProvided": {
        "zh": "「{name}」不提供工作流库:它的插件没有认领 workflow_library",
        "en": "“{name}” has no workflow library: its plugin does not provide workflow_library",
    },
    "workflowLibErr_badPath": {
        "zh": "「{path}」不是一个能用的工作流路径:要以 .json 结尾,不能带 ..、反斜杠或 :*?\"<>| 这类字符,每一段不能以点开头",
        "en": "“{path}” is not a usable workflow path: it must end in .json, without .., backslashes or characters like :*?\"<>|, and no part may start with a dot",
    },
    "workflowLibErr_badFolder": {
        "zh": "「{path}」不是一个能用的文件夹名:不能带 ..、反斜杠或 :*?\"<>| 这类字符,每一段不能以点开头,也不能以 .json 结尾",
        "en": "“{path}” is not a usable folder name: no .., backslashes or characters like :*?\"<>|, no part may start with a dot, and it can't end in .json",
    },
    "workflowLibErr_folderNotEmpty": {
        "zh": "文件夹「{path}」里还有 {count} 个文件,没有删。先把里面的工作流挪走或删掉,再删这个文件夹",
        "en": "The folder “{path}” still holds {count} file(s), so it wasn't deleted. Move or delete the workflows in it first",
    },
    "workflowLibErr_folderIntoItself": {
        "zh": "不能把文件夹「{path}」挪进它自己里面",
        "en": "The folder “{path}” can't be moved into itself",
    },
    "workflowLibErr_exists": {
        "zh": "那台服务器上已经有「{path}」了,不会覆盖。换一个名字",
        "en": "“{path}” already exists on that server and won't be overwritten. Pick another name",
    },
    "workflowLibErr_importOne": {
        "zh": "要导入的东西只给一样:一段 JSON、一个文件或一个链接",
        "en": "Give exactly one thing to import: a piece of JSON, a file or a link",
    },
    "workflowLibErr_importTooBig": {
        "zh": "要导入的东西太大了(超过 {mb} MB),不像一张工作流",
        "en": "What you're importing is too big (over {mb} MB) to be a workflow",
    },
    "workflowLibErr_importBadUrl": {
        "zh": "链接要以 http:// 或 https:// 开头",
        "en": "The link must start with http:// or https://",
    },
    "workflowLibErr_notUiWorkflow": {
        "zh": "要存的不是一张界面格式的工作流(没有 nodes)",
        "en": "What's being saved is not a UI-format workflow (no nodes)",
    },
    "workflowLibErr_badPacks": {
        "zh": "要装的节点包不对:一次 1 到 {most} 个,每个是 Manager 里那个包的名字或仓库地址",
        "en": "The node packs to install won't do: 1 to {most} at a time, each the pack's name or repository URL in the Manager",
    },
    "workflowLibErr_badAnswer": {
        "zh": "「{name}」的插件回的东西不对,没改成",
        "en": "The plugin of “{name}” answered with something unexpected; nothing was changed",
    },
    "workflowLibErr_stale": {
        "zh": "「{path}」刚在 ComfyUI 里改过,应用表单没存。重新打开再改",
        "en": "“{path}” was just changed in ComfyUI, so the app form wasn't saved. Open it again and redo the change",
    },
    "workflowLibErr_badAppItem": {
        "zh": "应用表单里的「{item}」不对:只认根图上的节点(节点号是数字)和图级的种子 / 尺寸 / 跑几遍",
        "en": "“{item}” in the app form won't do: only nodes on the top-level graph (numeric ids) and the graph-level seed / size / runs",
    },
    "workflowLibErr_canvasNotUi": {
        "zh": "画布上的图不是界面格式的工作流",
        "en": "The canvas graph is not a UI-format workflow",
    },
    "workflowLibErr_canvasTooBig": {
        "zh": "画布上的图太大了(超过 {mb} MB)",
        "en": "The canvas graph is too big (over {mb} MB)",
    },
    "workflowLibErr_canvasBadPrompt": {
        "zh": "画布导出的 API 图形状不对,没有运行",
        "en": "The API graph exported from the canvas is malformed, so it wasn't run",
    },
    "workflowLibErr_runNotModel": {
        "zh": "「{path}」还不是这个连接下的生成模型:先在 ComfyUI 里保存这张工作流(新建的要起个名字存一次),回到工作流库刷新出来再运行",
        "en": "“{path}” isn't a generation model on this connection yet: save the workflow in ComfyUI first (a new one needs a name), refresh the workflow library, then run it",
    },
    "workflowLibErr_badMarks": {
        "zh": "{name} 交回的画布标记形状不对",
        "en": "{name} returned malformed canvas marks",
    },
    "workflowLibErr_appTooBig": {
        "zh": "应用表单太大了:最多 {items} 项、每项最多 {choices} 个可选值、最多标 {results} 个结果",
        "en": "The app form is too big: at most {items} items, {choices} choices per item and {results} result nodes",
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
        "zh": "插件市场地址只能是 https(本机调试可以用 http://127.0.0.1)",
        "en": "The plugin marketplace URL must use https (plain http only for 127.0.0.1 during development).",
    },
    "pluginErr_marketUnreachable": {
        "zh": "打不开插件市场:{detail}",
        "en": "Could not open the plugin marketplace: {detail}",
    },
    "pluginErr_marketStatus": {
        "zh": "插件市场的索引取不到:{url} 返回 HTTP {status}",
        "en": "Could not fetch the plugin marketplace index: {url} returned HTTP {status}",
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
        "zh": "插件下载地址只能是 https(本机调试可以用 http://127.0.0.1)",
        "en": "The plugin download URL must use https (plain http only for 127.0.0.1 during development).",
    },
    "pluginErr_archiveDigestMismatch": {
        "zh": "下载到的插件包和市场索引里登记的不一致(sha256 对不上),没有安装。可能是下载地址被替换或传输出错,稍后再试或联系插件作者",
        "en": "The downloaded plugin package doesn't match the one listed in the marketplace (sha256 mismatch), so it wasn't installed. The download may have been swapped or corrupted; try again later or contact the plugin author.",
    },
    "pluginErr_downloadFailed": {
        "zh": "下载插件失败:{detail}",
        "en": "Could not download the plugin: {detail}",
    },
    "pluginErr_updateNotReleased": {
        "zh": "这个插件的新版本还没发布,当前已是可下载的最新版",
        "en": "The new version of this plugin hasn't been released yet — you already have the latest downloadable version.",
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
    #: 插件节点为什么用不了(见 plugins.nodes.why_unusable)。按真实原因说,读的人才知道该去哪儿。
    "pluginErr_nodePluginMissing": {
        "zh": "这个节点来自插件「{plugin}」,这里没有装这个插件(或者已经删掉了)",
        "en": "This node comes from the plugin “{plugin}”, which isn't installed here (or has been removed)",
    },
    "pluginErr_nodeNoConnection": {
        "zh": "你还没有接「{plugin}」:在插件页新建并启用一个连接",
        "en": "You haven't connected “{plugin}” yet: create and enable a connection on the Plugins page",
    },
    "pluginErr_nodeUnusable": {
        "zh": "「{plugin}」的「{tool}」用不了:{details}",
        "en": "“{tool}” from “{plugin}” can't be used: {details}",
    },
    "pluginWhy_connection": {"zh": "连接「{name}」{reason}", "en": "connection “{name}”: {reason}"},
    "pluginWhy_toolGone": {
        "zh": "上已经没有这个工具了(插件更新后去掉了它)",
        "en": "no longer has this tool (the plugin dropped it in an update)",
    },
    "pluginWhy_toolListFailed": {
        "zh": "的工具清单没拉下来({reason}):把它连的服务开起来,再在插件页刷新一次",
        "en": "couldn't fetch its tool list ({reason}): start the service it connects to, then refresh it on the Plugins page",
    },
    "pluginWhy_toolInternal": {
        "zh": "上这个工具只给应用自己调,不能放进工作流",
        "en": "only lets the app itself call this tool; it can't go in a workflow",
    },
    "pluginWhy_toolNotExposed": {
        "zh": "没有勾选这个工具:在插件页的工具列表里勾上它",
        "en": "doesn't have this tool enabled: tick it in the tool list on the Plugins page",
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
    # ---- 本机服务(ADR 0041) ----
    "pluginErr_noSuchService": {
        "zh": "「{name}」没有声明叫 {service} 的本机服务,请到插件页更新这个插件",
        "en": "“{name}” declares no local service named {service}. Update the plugin from the Plugins page.",
    },
    "localService_starting": {
        "zh": "正在启动本机 {name}",
        "en": "Starting the local {name}",
    },
    "localServiceErr_notConfigured": {
        "zh": "这个连接没有用本机服务",
        "en": "This connection doesn't use a local service.",
    },
    "localServiceErr_noService": {
        "zh": "「{name}」不能在本机起服务:它的清单里没有声明本机服务",
        "en": "“{name}” can't run a local service: its manifest declares none.",
    },
    "localServiceErr_unknownMode": {
        "zh": "认不出的运行方式:{mode}",
        "en": "Unknown way to run it: {mode}",
    },
    "localServiceErr_noDirectory": {
        "zh": "先选一个装好的目录",
        "en": "Choose an installed folder first.",
    },
    "localServiceErr_confirmRequired": {
        "zh": "运行这个目录里的代码之前要先确认一次:它会在这台机器上运行",
        "en": "Confirm before running the code in this folder: it runs on this machine.",
    },
    "localServiceErr_directoryBusy": {
        "zh": "这个目录已经由连接「{name}」在跑:同一个目录只起一份",
        "en": "This folder is already running for the connection “{name}”: one folder runs only once.",
    },
    "localServiceErr_portBusy": {
        "zh": "端口 {port} 被别的程序占着:关掉它,或者在「高级」里换一个端口",
        "en": "Port {port} is taken by another program. Close it, or choose another port under Advanced.",
    },
    "localServiceErr_portTaken": {
        "zh": "端口 {port} 已经分给连接「{name}」了",
        "en": "Port {port} is already assigned to the connection “{name}”.",
    },
    "localServiceErr_badPort": {
        "zh": "端口要在 {low}–{high} 之间",
        "en": "The port must be between {low} and {high}.",
    },
    "localServiceErr_noFreePort": {
        "zh": "从 {start} 往上找不到空着的端口",
        "en": "No free port found from {start} upwards.",
    },
    "localServiceErr_stopFirst": {
        "zh": "先停下它,再改端口",
        "en": "Stop it before changing the port.",
    },
    "localServiceErr_badArgs": {
        "zh": "附加参数没写完:{detail}",
        "en": "The extra arguments are incomplete: {detail}",
    },
    "localServiceErr_badLaunch": {
        "zh": "「{name}」给的启动方式不对:{detail}",
        "en": "“{name}” gave an invalid way to start it: {detail}",
    },
    "localServiceErr_spawnFailed": {
        "zh": "起不来:{detail}",
        "en": "It couldn't start: {detail}",
    },
    "localServiceErr_readyTimeout": {
        "zh": "等了 {seconds} 秒还没就绪,已经停掉了。看看日志里卡在哪一步",
        "en": "It wasn't ready after {seconds} seconds, so it was stopped. Check the log to see where it got stuck.",
    },
    "localServiceErr_exitedDuringStart": {
        "zh": "还没就绪就退出了(退出码 {code}),看看日志里说了什么",
        "en": "It exited before it was ready (exit code {code}). Check the log for what it said.",
    },
    "localServiceErr_crashedTooOften": {
        "zh": "{minutes} 分钟里重启了 {count} 次还是崩,不再自动重启。看看日志里说了什么",
        "en": "It kept crashing after {count} restarts in {minutes} minutes, so it won't restart automatically. Check the log.",
    },
    "localServiceErr_badIdleMinutes": {
        "zh": "闲置多久自动停要在 {low}–{high} 分钟之间(0 = 不自动停)",
        "en": "The idle time before stopping must be between {low} and {high} minutes (0 = never).",
    },
    "localServiceErr_tooManyShared": {
        "zh": "共用的模型文件夹最多 {limit} 处",
        "en": "At most {limit} shared models folders.",
    },
    "localServiceErr_sharedNotRecognized": {
        "zh": "这一处不能当共用的模型文件夹:{detail}",
        "en": "This can't be used as a shared models folder: {detail}",
    },
    # ---- 本机服务此刻为什么用不了(插件调用失败、目录刷不出来时按它说;见 local_services.issue_of) ----
    "localServiceIssue_stopped": {
        "zh": "本机的 {name} 没在运行:用到时会自动启动,也可以现在点「启动」",
        "en": "The local {name} isn't running: it starts automatically when it's used, or choose Start now.",
    },
    "localServiceIssue_idleStopped": {
        "zh": "本机的 {name} 闲置了 {minutes} 分钟,自动停了(释放显存):用到时会自动启动,也可以现在点「启动」",
        "en": "The local {name} was idle for {minutes} min and stopped to free GPU memory: it starts automatically when "
              "it's used, or choose Start now.",
    },
    "localServiceIssue_starting": {
        "zh": "本机的 {name} 正在启动…",
        "en": "The local {name} is starting…",
    },
    "localServiceIssue_failed": {
        "zh": "本机的 {name} 起不来:{reason}",
        "en": "The local {name} couldn't start: {reason}",
    },
    "localServiceIssue_installing": {
        "zh": "本机的 {name} 正在装,装好之后就能用",
        "en": "The local {name} is being installed; it can be used once that finishes.",
    },
    "localServiceIssue_updating": {
        "zh": "本机的 {name} 正在换版本,换好之后就能用",
        "en": "The local {name} is changing versions; it can be used once that finishes.",
    },
    "localServiceIssue_notInstalled": {
        "zh": "本机的 {name} 还没装好:到连接页上「接着装」",
        "en": "The local {name} isn't installed yet. Choose Resume on the connection page.",
    },
    "localServiceIssue_rebuild": {
        "zh": "本机的 {name} 运行环境要重建(用 Python {have} 建的,Mosael 现在带的是 {want}):到连接页上点「重建运行环境」",
        "en": "The local {name} needs its environment rebuilt (built with Python {have}; Mosael now ships {want}). "
              "Choose Rebuild environment on the connection page.",
    },
    "localServiceIssue_unresponsive": {
        "zh": "本机的 {name} 进程在跑,但没有应答:看看它的日志",
        "en": "The local {name} process is running but not answering. Check its log.",
    },
    "localServiceErr_stopped": {
        "zh": "本机 {name} 在启动时被停下了",
        "en": "The local {name} was stopped while it was starting.",
    },
    # ---- 让 Mosael 装(ADR 0041 §4) ----
    "localServiceInstall_trial": {
        "zh": "试起一次,健康检查通过才算装好",
        "en": "Start it once; it counts as installed only after a healthy start",
    },
    "localServiceErr_installing": {
        "zh": "正在装或换版本:做完了(或者取消了)再来",
        "en": "It's being installed or changing versions. Wait until that finishes (or cancel it).",
    },
    # ---- 让 Mosael 装的那一份换版本(更新、回到上一版) ----
    "localServiceUpdate_trial": {
        "zh": "试起新版本一次,没通过就换回原来的",
        "en": "Start the new version once; if it isn't healthy, go back to the earlier one",
    },
    "localServiceRollback_trial": {
        "zh": "试起一次",
        "en": "Start it once",
    },
    "localServiceUpdate_goingBack": {
        "zh": "试起没通过,正在换回 {version}…",
        "en": "It didn't start healthily; going back to {version}…",
    },
    "localServiceUpdate_cancelled": {
        "zh": "取消了",
        "en": "cancelled",
    },
    "localServiceErr_updateRolledBack": {
        "zh": "新版本 {version} 试起没通过:{reason}。已经换回 {previous}(源码和依赖)",
        "en": "The new version {version} didn't start healthily: {reason}. Went back to {previous} (source and packages).",
    },
    "localServiceErr_updateRollbackFailed": {
        "zh": "新版本 {version} 试起没通过:{reason}。换回 {previous} 时也出错了:{detail}。到连接页上点「换回 {previous}」再试一次",
        "en": "The new version {version} didn't start healthily: {reason}. Going back to {previous} failed too: {detail}. "
              "Choose “Go back to {previous}” on the connection page to try again.",
    },
    "localServiceErr_changeUnfinished": {
        "zh": "上一次换版本没做完:先点「换回 {version}」把它收拾好",
        "en": "The last version change didn't finish. Choose “Go back to {version}” first to tidy it up.",
    },
    "localServiceErr_noUpdate": {
        "zh": "已经是最新的版本({version})了",
        "en": "It's already the latest version ({version}).",
    },
    "localServiceErr_noPrevious": {
        "zh": "没有可以回去的上一版(更新之后才有,回到上一版之后就没了)",
        "en": "There's no earlier version to go back to (there is one after an update, until you go back).",
    },
    "localServiceErr_notInstalled": {
        "zh": "本机 {name} 还没装好:到连接页上「接着装」",
        "en": "The local {name} isn't installed yet. Choose Resume on the connection page.",
    },
    "localServiceErr_rebuildNeeded": {
        "zh": "本机 {name} 的运行环境要重建:它是用 Python {have} 建的,Mosael 现在带的是 {want}。到连接页上点「重建运行环境」"
              "(源码和模型不动)",
        "en": "The local {name} needs its environment rebuilt: it was built with Python {have}, and Mosael now ships {want}. "
              "Choose Rebuild environment on the connection page (the source and models stay).",
    },
    "localServiceErr_notManaged": {
        "zh": "这个连接不是「让 Mosael 装」的那一种",
        "en": "This connection isn't one Mosael installs.",
    },
    "localServiceErr_noBasePython": {
        "zh": "找不到建运行环境用的 Python(随 Mosael 一起发的那一个),装不了",
        "en": "The Python Mosael uses to build environments (the one it ships with) wasn't found, so nothing can be installed.",
    },
    "localServiceErr_installCrashed": {
        "zh": "安装时出错了:{detail}",
        "en": "The install hit an error: {detail}",
    },
}

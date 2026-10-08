/**
 * 桌面壳(主进程)自己的多语言:菜单、托盘、原生对话框、系统通知,以及发布器 / 浏览器执行器
 * 回报给后端、最终出现在任务行里的失败原因。
 *
 * **为什么不直接用前端的 messages.ts**:主进程是 CommonJS,运行时 require 不到前端的 TS 表;
 * 而这里的字是主进程**自己**说的话(渲染层根本不经手),所以文案表跟着说话的人走。
 *
 * **语言从哪来**:渲染层把界面语言写在 `<html lang>` 上,preload 盯着它、变了就经
 * IPC.send.locale 报给主进程(见 preload.cjs)。报上来之前(启动那一两秒)用系统语言垫着。
 *
 * **每个 bundle 各有一份状态**:publish.bundle.cjs / system.bundle.cjs 由 esbuild 各自把本模块
 * 打进去,和 main.cjs 这份不是同一个实例 —— 所以语言变化由 main.cjs 的 applyLocale 逐个转告
 * (它们各自导出 setLocale)。
 *
 * 占位符是 `{name}`;同一个 key 的中英两份要用同样的占位符、两种语言都得有(本文件内的事,由 i18n.test.ts 查)。
 */

/** 支持的语言。第一个是缺省 —— 与后端 core/i18n 的 DEFAULT_LOCALE 一致。 */
const LOCALES = ["zh", "en"];
const DEFAULT_LOCALE = LOCALES[0];

/** key → { zh, en }。 */
const MESSAGES = {
  // ---- 应用菜单 ----
  menu_about: { zh: "关于 Mosael", en: "About Mosael" },
  menu_aboutVersion: { zh: "版本 {version}", en: "Version {version}" },
  menu_services: { zh: "服务", en: "Services" },
  menu_hide: { zh: "隐藏 Mosael", en: "Hide Mosael" },
  menu_hideOthers: { zh: "隐藏其他", en: "Hide Others" },
  menu_unhide: { zh: "全部显示", en: "Show All" },
  menu_quitApp: { zh: "退出 Mosael", en: "Quit Mosael" },
  menu_file: { zh: "文件", en: "File" },
  menu_closeWindow: { zh: "关闭窗口", en: "Close Window" },
  menu_quit: { zh: "退出", en: "Exit" },
  menu_edit: { zh: "编辑", en: "Edit" },
  menu_undo: { zh: "撤销", en: "Undo" },
  menu_redo: { zh: "重做", en: "Redo" },
  menu_cut: { zh: "剪切", en: "Cut" },
  menu_copy: { zh: "复制", en: "Copy" },
  menu_paste: { zh: "粘贴", en: "Paste" },
  menu_selectAll: { zh: "全选", en: "Select All" },
  menu_view: { zh: "视图", en: "View" },
  menu_reload: { zh: "重新加载", en: "Reload" },
  menu_forceReload: { zh: "强制重新加载", en: "Force Reload" },
  menu_devTools: { zh: "开发者工具", en: "Developer Tools" },
  menu_resetZoom: { zh: "实际大小", en: "Actual Size" },
  menu_zoomIn: { zh: "放大", en: "Zoom In" },
  menu_zoomOut: { zh: "缩小", en: "Zoom Out" },
  menu_fullscreen: { zh: "全屏", en: "Toggle Full Screen" },
  menu_window: { zh: "窗口", en: "Window" },
  menu_minimize: { zh: "最小化", en: "Minimize" },
  menu_zoom: { zh: "缩放", en: "Zoom" },
  menu_front: { zh: "前置全部窗口", en: "Bring All to Front" },
  menu_close: { zh: "关闭", en: "Close" },
  menu_help: { zh: "帮助", en: "Help" },
  common_ok: { zh: "好", en: "OK" },
  common_cancel: { zh: "取消", en: "Cancel" },
  common_untitled: { zh: "未命名", en: "Untitled" },

  // ---- 托盘 ----
  tray_running: { zh: "{count} 个任务运行中", en: "{count} running" },
  tray_idle: { zh: "空闲", en: "Idle" },
  tray_open: { zh: "打开 Mosael", en: "Open Mosael" },
  tray_openAtLogin: { zh: "开机时启动", en: "Open at Login" },

  // ---- 系统通知(发布需要人介入的那几种状态) ----
  notice_loginRequired: { zh: "账号需要登录", en: "Account needs to sign in" },
  notice_waitingManual: { zh: "发布需要人工处理", en: "Publishing needs your attention" },
  notice_permissionRequired: { zh: "账号权限不足", en: "Account lacks permission" },
  notice_blocked: { zh: "发布被拦截", en: "Publishing was blocked" },

  // ---- 对话框与主进程报错 ----
  dialog_exportDiagnostics: { zh: "导出 Mosael 诊断包", en: "Export Mosael Diagnostics" },
  dialog_zipArchive: { zh: "ZIP 压缩包", en: "ZIP archive" },
  dialog_createBackup: { zh: "创建 Mosael 数据备份", en: "Create Mosael Backup" },
  dialog_backupFile: { zh: "Mosael 备份", en: "Mosael backup" },
  backend_stoppedTitle: { zh: "Mosael 后端已停止", en: "Mosael backend stopped" },
  backend_stoppedBody: {
    zh: "本地后端反复意外退出(最后一次:{code}),自动重启没能恢复。可以再试一次;一直起不来的话,日志在 {logs} 和 {dataLogs}(设置 → 数据里能导出诊断包)。",
    en: "The local backend kept exiting unexpectedly (last: {code}) and automatic restarts did not recover it. You can try again; if it keeps failing, the logs are in {logs} and {dataLogs} (Settings → Data can export a diagnostics package).",
  },
  backend_retry: { zh: "再试一次", en: "Try Again" },
  backend_portTakenTitle: { zh: "端口被另一个后端占用", en: "Port taken by another backend" },
  backend_portTakenBody: {
    zh: "端口 {port} 上已经有一个后端在跑,但它不是这个版本、这份数据的({reason})。请先退出它(或结束残留的 mosael-backend 进程)再打开 Mosael。",
    en: "A backend is already running on port {port}, but it does not belong to this version or data folder ({reason}). Quit it (or end the leftover mosael-backend process) and open Mosael again.",
  },
  backend_startFailedTitle: { zh: "Mosael 后端启动失败", en: "Mosael backend failed to start" },
  backend_startFailedBody: {
    zh: "本地后端没能在端口 {port} 上起来(进程退出了:{code})。日志在 {logs} 和 {dataLogs}。",
    en: "The local backend could not start on port {port} (the process exited: {code}). The logs are in {logs} and {dataLogs}.",
  },
  renderer_crashedTitle: { zh: "Mosael 的界面反复崩溃", en: "The Mosael window keeps crashing" },
  renderer_crashedBody: {
    zh: "界面一分钟里崩了好几次(最后一次:{reason}),已经不再自动重新载入。可以再载入一次;一直这样的话,日志在 {logs} 和 {dataLogs}。",
    en: "The window crashed several times within a minute (last: {reason}) and is no longer reloaded automatically. You can reload it once more; if it keeps happening, the logs are in {logs} and {dataLogs}.",
  },
  renderer_reload: { zh: "重新载入", en: "Reload" },
  startup_title: { zh: "Mosael 正在启动…", en: "Starting Mosael…" },
  startup_body: {
    zh: "首次打开、或者升级之后要整理数据时,可能要几分钟。",
    en: "The first launch, or tidying up data after an update, can take a few minutes.",
  },
  startup_slowBody: {
    zh: "还没好。可以接着等;想看它在做什么,日志在 {logs}。",
    en: "Not ready yet. You can keep waiting; to see what it's doing, the logs are in {logs}.",
  },
  startup_elapsed: { zh: "已经等了 {seconds} 秒", en: "Waiting for {seconds} s" },
  masterKey_title: { zh: "Mosael 取不到加密钥匙", en: "Mosael can't unlock its encryption key" },
  masterKey_message: {
    zh: "存在系统钥匙串里的 Mosael 主密钥解不开。",
    en: "The Mosael master key kept in the system keychain could not be unlocked.",
  },
  masterKey_detailMac: {
    zh: "已保存的凭据(模型服务的密钥、插件凭据)都靠这把钥匙解密。Mosael 不会另生一把新钥匙凑合用 —— 那样旧的凭据就再也解不开了。\n\n如果刚才在钥匙串的提示里点了「拒绝」,点「重试」,再选「允许」或「始终允许」;也可以在「钥匙串访问」里找到「Mosael Safe Storage」,把 Mosael 加进它的访问控制后再重试。\n\n封存的钥匙:{path}",
    en: "Your saved credentials (provider keys, plugin credentials) are decrypted with this key. Mosael will not make a new key to get by — the old credentials could never be decrypted again.\n\nIf you just clicked \"Deny\" on the keychain prompt, click Try Again and choose \"Allow\" or \"Always Allow\". You can also find \"Mosael Safe Storage\" in Keychain Access, add Mosael to its access control, and try again.\n\nSealed key: {path}",
  },
  masterKey_detail: {
    zh: "已保存的凭据(模型服务的密钥、插件凭据)都靠这把钥匙解密。Mosael 不会另生一把新钥匙凑合用 —— 那样旧的凭据就再也解不开了。\n\n请确认系统的凭据存储(Windows 的数据保护 / 桌面的密钥环)可用,再点「重试」。\n\n封存的钥匙:{path}",
    en: "Your saved credentials (provider keys, plugin credentials) are decrypted with this key. Mosael will not make a new key to get by — the old credentials could never be decrypted again.\n\nMake sure the system credential store (Windows data protection / your desktop keyring) is available, then click Try Again.\n\nSealed key: {path}",
  },
  masterKey_retry: { zh: "重试", en: "Try Again" },
  masterKey_openKeychain: { zh: "打开钥匙串访问", en: "Open Keychain Access" },
  restore_needsManagedBackend: {
    zh: "恢复数据需要由本桌面应用启动的后端",
    en: "Restore requires the backend managed by this desktop app",
  },
  restore_backendStopTimeout: { zh: "后端没能按时停下", en: "The backend did not stop in time" },
  backup_requestFailed: { zh: "备份请求失败({status})", en: "Backup request failed ({status})" },
  update_noTag: {
    zh: "GitHub 的返回里没有版本号(tag_name)",
    en: "GitHub's response has no version (tag_name)",
  },
  publisher_loadFailed: { zh: "发布执行器加载失败:{detail}", en: "The publisher failed to load: {detail}" },
  publisher_missing: {
    zh: "发布执行器不可用:electron/publish.bundle.cjs 缺失(先跑 pnpm build:publisher)",
    en: "The publisher is unavailable: electron/publish.bundle.cjs is missing (run pnpm build:publisher first)",
  },
  webauthn_pickAccountTitle: { zh: "选择账号", en: "Choose an account" },
  webauthn_pickAccountMessage: {
    zh: "{site} 上有多个可用账号",
    en: "Several accounts are available on {site}",
  },

  // ---- 自定义 CSS 文件的初始模板(写进用户磁盘,按建文件那一刻的界面语言) ----
  customCss_template: {
    zh: `/* Mosael —— 自定义 CSS
 *
 * 这个文件里的样式**压过应用自带的所有样式**(它是无层级的,而且注入在最后),
 * 所以多数时候不需要 !important。存盘即生效,不用重启。
 *
 * 改主题色、圆角这类整体观感,最省事的是覆盖设计令牌:
 */

/*
:root {
  --primary: #7c3aed;
  --radius: 6px;
}
*/

/* 深色主题单独调: */
/*
.dark {
  --primary: #a78bfa;
}
*/

/* 也可以直接改某个元素。用开发者工具(Cmd/Ctrl+Option+I)选中它看类名。 */
`,
    en: `/* Mosael — custom CSS
 *
 * Styles in this file **override everything the app ships with** (they are unlayered
 * and injected last), so you rarely need !important. Saving applies them right away,
 * no restart needed.
 *
 * For overall look and feel (accent color, corner radius) the easiest route is to
 * override the design tokens:
 */

/*
:root {
  --primary: #7c3aed;
  --radius: 6px;
}
*/

/* Tune the dark theme separately: */
/*
.dark {
  --primary: #a78bfa;
}
*/

/* You can also restyle a single element. Pick it with Developer Tools
 * (Cmd/Ctrl+Option+I) to see its class names. */
`,
  },

  // ---- 发布平台名(实时面板上的「平台 · 步骤」,以及失败原因里的主语) ----
  platform_mock: { zh: "Mock", en: "Mock" },
  platform_douyin: { zh: "抖音", en: "Douyin" },
  platform_xiaohongshu: { zh: "小红书", en: "Xiaohongshu" },
  platform_weixinChannels: { zh: "微信视频号", en: "WeChat Channels" },
  platform_bilibili: { zh: "B 站", en: "Bilibili" },
  platform_tiktok: { zh: "TikTok", en: "TikTok" },
  platform_youtube: { zh: "YouTube", en: "YouTube" },

  // ---- 发布步骤(实时面板) ----
  publishStep_preparing: { zh: "准备中", en: "Preparing" },
  publishStep_openCreator: { zh: "打开创作页", en: "Opening the creator page" },
  publishStep_checkLogin: { zh: "检查登录态", en: "Checking sign-in" },
  publishStep_upload: { zh: "上传视频", en: "Uploading the video" },
  publishStep_fillTitle: { zh: "填写标题", en: "Filling in the title" },
  publishStep_fillTags: { zh: "填写标签与简介", en: "Filling in tags and description" },
  publishStep_submit: { zh: "提交投稿", en: "Submitting" },
  publishStep_waitConfirm: { zh: "等待平台确认", en: "Waiting for the platform to confirm" },
  publishStep_done: { zh: "发布成功", en: "Published" },
  publishStep_failed: { zh: "失败", en: "Failed" },

  // ---- 发布失败原因(回报给后端,出现在任务行 / 账号状态里) ----
  publishErr_notLoggedIn: { zh: "未登录", en: "Not signed in" },
  publishErr_notLoggedInTask: {
    zh: "账号未登录。在发布控制台点该账号「登录」完成扫码后重试。",
    en: "The account is not signed in. Click “Sign in” for this account in the publishing console, finish signing in, then retry.",
  },
  publishErr_sessionExpired: { zh: "登录已失效,请重新登录", en: "Your sign-in has expired. Please sign in again." },
  publishErr_notReady: { zh: "发布器未就绪", en: "The publisher is not ready" },
  publishErr_foregroundBusy: {
    zh: "有账号正在前台操作,请先处理完再登录",
    en: "Another account is using the foreground view. Finish there before signing in.",
  },
  publishErr_accountBusy: {
    zh: "该账号有发布任务正在进行,请等它完成后再登录",
    en: "This account has a publishing task in progress. Sign in after it finishes.",
  },
  publishErr_noUploadEntry: { zh: "{platform} 没有找到上传入口。", en: "{platform}: could not find the upload entry." },
  publishErr_editorMissing: {
    zh: "{platform} 上传后编辑器没有出现(找不到输入框)。",
    en: "{platform}: the editor never appeared after the upload (no input field found).",
  },
  publishErr_uploadTimeout: {
    zh: "{platform} 上传超时,没有在时限内完成。",
    en: "{platform}: the upload did not finish in time.",
  },
  publishErr_uploadFailed: { zh: "{platform} 报告视频上传失败。", en: "{platform} reported that the video upload failed." },
  publishErr_titleRejected: {
    zh: "{platform} 的标题输入框没有接受填入的内容。",
    en: "{platform}: the title field did not accept the text.",
  },
  publishErr_descriptionRejected: {
    zh: "{platform} 的正文编辑器没有接受填入的描述。",
    en: "{platform}: the body editor did not accept the description.",
  },
  publishErr_submitDisabled: {
    zh: "{platform} 的发布按钮一直不可点击。",
    en: "{platform}: the publish button never became clickable.",
  },
  publishErr_notConfirmed: {
    zh: "{platform} 没有确认发布:既没有出现成功提示,也没有跳转到作品管理页。",
    en: "{platform} did not confirm the post: no success message appeared and it never reached the content manager.",
  },
  publishErr_rejected: { zh: "{platform} 拒绝了这次投稿:{reason}", en: "{platform} rejected the post: {reason}" },
  publishErr_declarationNotSelected: {
    zh: "{platform} 的创作声明没能选中。",
    en: "{platform}: could not select the creation declaration.",
  },
  publishErr_coverNotSelected: {
    zh: "{platform} 的推荐封面没能选中。",
    en: "{platform}: could not select the recommended cover.",
  },
  publishErr_visibilityMissing: {
    zh: "{platform} 的可见范围控件没有找到,为避免误公开发布已中止。",
    en: "{platform}: the visibility control was not found, so publishing stopped to avoid posting publicly by mistake.",
  },
  publishErr_titleMismatch: {
    zh: "{platform} 的标题框没有接受填入的内容(应为 {expected},实际是 {actual})。",
    en: "{platform}: the title box did not accept the text (expected {expected}, got {actual}).",
  },
  publishErr_tagRejected: { zh: "{platform} 没有接受标签 #{tag}。", en: "{platform} did not accept the tag #{tag}." },
  publishErr_visibilityNotApplied: {
    zh: "{platform} 的可见范围没能设成 {visibility},为避免误发已中止。",
    en: "{platform}: could not set the visibility to {visibility}, so publishing stopped to avoid a wrong post.",
  },
  publishErr_adminVerify: {
    zh: "{platform} 需要管理员验证。在内嵌浏览器里完成扫码验证后重试。",
    en: "{platform} requires admin verification. Complete the QR verification in the embedded browser, then retry.",
  },
  publishErr_notOperator: {
    zh: "{platform} 提示这个微信号不是所选视频号的管理员或运营者。",
    en: "{platform} says this WeChat account is not an admin or operator of the selected channel.",
  },
  publishErr_originalMissing: {
    zh: "{platform} 的「原创声明」控件没有找到。",
    en: "{platform}: the “original content” control was not found.",
  },
  publishErr_originalStuck: {
    zh: "{platform} 的「原创声明」停在 {after},应为 {wanted}。",
    en: "{platform}: the “original content” switch stayed {after}, wanted {wanted}.",
  },

  // ---- 浏览器自动化动作的报错(回给后端,出现在工作流 / 智能体的执行结果里) ----
  browserErr_clickNeedsTarget: { zh: "click 需要 selector 或 text", en: "click needs a selector or text" },
  browserErr_uploadNeedsPath: { zh: "upload 需要文件路径", en: "upload needs a file path" },
  browserErr_fileInputMissing: {
    zh: "upload:文件输入框没有出现:{selector}",
    en: "upload: the file input never appeared: {selector}",
  },
  browserErr_waitNeedsTarget: {
    zh: "wait 需要 selector / url_contains / text 之一",
    en: "wait needs one of selector / url_contains / text",
  },
  browserErr_waitGone: { zh: "元素始终没有消失:{target}", en: "the element never went away: {target}" },
  browserErr_waitVisible: { zh: "元素一直没出现:{target}", en: "the element never appeared: {target}" },
  browserErr_waitUrl: { zh: "网址里一直没有出现:{target}", en: "the URL never contained: {target}" },
  browserErr_waitText: { zh: "页面上一直没有出现文字:{target}", en: "the text never appeared on the page: {target}" },
  browserErr_waitTimeout: {
    zh: "等待超时({seconds}s):{what};当前停在 {url}",
    en: "Timed out after {seconds}s: {what}; the page is at {url}",
  },
  browserErr_unknownAction: { zh: "未知浏览器动作:{action}", en: "Unknown browser action: {action}" },
  browserErr_elementMissing: {
    zh: "等了 {seconds}s 还是找不到要操作的元素:{target};当前停在 {url}",
    en: "Still couldn't find the element to act on after {seconds}s: {target}; the page is at {url}",
  },
  browserErr_partitionAwaitingMove: {
    zh: "这个具名会话的登录数据还等着搬到新位置(升级时改了存放方式),重启桌面端之后再用",
    en: "This named session's sign-in data is still waiting to move to its new location (the storage layout changed in an upgrade). Restart the desktop app before using it.",
  },
  browserErr_navigateFailed: {
    zh: "网页没有打开({code}):{url}",
    en: "The page didn't open ({code}): {url}",
  },
  browserErr_frameMissing: {
    zh: "等了 {seconds}s 还是找不到框架:{frame};当前停在 {url}",
    en: "Still couldn't find the frame after {seconds}s: {frame}; the page is at {url}",
  },
  browserErr_frameCrossOrigin: {
    zh: "框架 {frame} 里是另一个网站的页面({src}),浏览器自动化够不到跨域框架里的元素;可以用「打开网址」直接打开这个地址再操作",
    en: "The frame {frame} holds a page from another site ({src}); browser automation can't reach inside cross-origin frames. Open that address with “Open URL” and work on it directly",
  },
  browserErr_notAFrame: {
    zh: "{frame} 不是框架(iframe),是 <{tag}>;「在框架里」要填 iframe 的选择器",
    en: "{frame} isn't a frame (iframe), it's a <{tag}>; “In frame” takes the iframe's selector",
  },
  browserErr_httpError: {
    zh: "网页打开了,但服务器回的是 {status}:{url}(要照样往下走,在节点上打开「允许错误页」)",
    en: "The page opened, but the server answered {status}: {url} (to carry on anyway, turn on “Allow error pages” on the node)",
  },
  browserErr_extractMissing: {
    zh: "页面上没有匹配的元素可提取:{selector};当前停在 {url}",
    en: "No element on the page matches, so there is nothing to extract: {selector}; the page is at {url}",
  },
  browserErr_scriptSyntax: {
    zh: "脚本有语法错误:{detail}",
    en: "The script has a syntax error: {detail}",
  },
  browserErr_scriptThrew: {
    zh: "脚本运行出错:{detail}",
    en: "The script failed: {detail}",
  },
  browserErr_scriptTimeout: {
    zh: "脚本运行超过 {seconds} 秒还没结束(在节点的「超时」里可以调大)",
    en: "The script was still running after {seconds} seconds (raise the node's timeout if it needs longer)",
  },
  browserErr_scrollMissing: {
    zh: "页面上没有要滚动到的元素:{selector};当前停在 {url}",
    en: "The element to scroll to isn't on the page: {selector}; the page is at {url}",
  },
  devMain_cannotRestart: {
    zh: "这次不是经 pnpm dev 拉起的,没法替你重启,请手动重启 Mosael",
    en: "Mosael wasn't started by pnpm dev, so it can't restart itself; restart it by hand",
  },
  // 渲染层经 IPC 调主进程失败时给人看的话(见 ipc-errors.cjs)。
  ipcErr_mainOutdated: {
    zh: "这个功能要重启 Mosael 才能用(应用的一部分还是旧版本)",
    en: "Restart Mosael to use this (part of the app is still the old version)",
  },
  ipcErr_failed: {
    zh: "桌面端没有完成这一步,再试一次",
    en: "The desktop app couldn't finish this; try again",
  },
  // 「切换页面」节点(见 publish/actionPage.ts)。
  browserErr_pageNeedsTarget: {
    zh: "要切到哪一页:填第几个、标题里的字,或网址里的一段",
    en: "Which page to switch to: give its position, words from its title, or part of its URL",
  },
  browserErr_pageBadIndex: {
    zh: "第几个页面要填正整数(最上面那个是 1),现在是:{value}",
    en: "The page position must be a whole number (the top one is 1); got: {value}",
  },
  browserErr_pageWhatIndex: { zh: "第 {index} 个页面", en: "page {index}" },
  browserErr_pageWhatTitle: { zh: "标题含「{value}」的页面", en: "a page whose title contains “{value}”" },
  browserErr_pageWhatUrl: { zh: "网址含「{value}」的页面", en: "a page whose URL contains “{value}”" },
  browserErr_pageNotFound: {
    zh: "没有找到{what}:这个会话现在开着 {count} 个页面",
    en: "Couldn't find {what}: this session has {count} pages open",
  },
  browserErr_pageLastOne: {
    zh: "这是这个会话里唯一的页面,不能关;要关掉整个浏览器请用「关闭浏览器」",
    en: "This is the session's only page, so it can't be closed; use “Close browser” to close the whole browser",
  },
  // 「截图」节点(见 publish/actionCapture.ts)。
  browserErr_shotNeedsSelector: {
    zh: "截元素要填 CSS 选择器",
    en: "Capturing an element needs a CSS selector",
  },
  browserErr_shotElementEmpty: {
    zh: "要截的元素没有大小(可能被藏起来了):{target}",
    en: "The element to capture has no size (it may be hidden): {target}",
  },
  browserErr_shotFailed: {
    zh: "没截到画面:页面可能还没加载完,或这个会话的窗口已经关了",
    en: "Nothing was captured: the page may still be loading, or this session's window has closed",
  },
  browserErr_shotFullUnavailable: {
    zh: "这一页截不了整页长图(开着开发者工具时也会这样),可以先截可见区域",
    en: "This page can't be captured as a full-page image (this also happens while DevTools is open); try the visible area",
  },
  // 内嵌浏览器里的下载(不弹保存框,直接进素材库;见 publish/downloads.ts)。
  downloadErr_type: {
    zh: "素材库不收这种文件:「{name}」。能存的是视频、音频、图片和常见文档(PDF、Word、PPT、Excel、文本……)",
    en: "The library can't take “{name}”: you can save video, audio, images and common documents (PDF, Word, PowerPoint, Excel, text…)",
  },
  downloadErr_tooLarge: {
    zh: "下载的文件太大了:最多 {maxGb} GB,已经停下",
    en: "The download is too large: {maxGb} GB at most, so it was stopped",
  },
  downloadErr_interrupted: {
    zh: "「{name}」没有下载完(连接断了,或网站拒绝了这次下载)",
    en: "“{name}” didn't finish downloading (the connection dropped or the site refused the download)",
  },
  downloadErr_cancelled: {
    zh: "「{name}」的下载取消了",
    en: "The download of “{name}” was cancelled",
  },
  downloadErr_saveFailed: {
    zh: "「{name}」下载好了,但没能存进素材库:{reason}",
    en: "“{name}” downloaded but couldn't be saved to the library: {reason}",
  },
  downloadErr_gone: {
    zh: "这份下载已经不在了(存过了,或下好之后十分钟没人存)",
    en: "This download is no longer available (it was already saved, or nobody saved it within ten minutes)",
  },
};

let current = DEFAULT_LOCALE;

/**
 * 把 `zh-CN` / `en-US` / `en_GB` 归一成支持的那几种;认不出的回落到缺省。**不猜**:
 * 与后端 normalize_locale 同一条规矩。
 * @param {unknown} raw
 * @returns {"zh" | "en"}
 */
function normalizeLocale(raw) {
  const primary = String(raw ?? "").trim().toLowerCase().split(/[-_]/)[0];
  return /** @type {"zh" | "en"} */ (LOCALES.includes(primary) ? primary : DEFAULT_LOCALE);
}

/** @param {unknown} raw */
function setLocale(raw) {
  current = normalizeLocale(raw);
  return current;
}

function getLocale() {
  return current;
}

/**
 * 翻一个 key。查不到就原样返回 key —— 难看但看得见,i18n.test.ts 保证它进不了主干。
 * 填不上的占位符原样留着,不吞掉:那是写错了参数名,留着才查得出来。
 * @param {string} key
 * @param {Record<string, unknown>} [params]
 */
function t(key, params) {
  const entry = /** @type {Record<string, Record<string, string>>} */ (MESSAGES)[key];
  const text = entry ? entry[current] || entry[DEFAULT_LOCALE] : key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

module.exports = { LOCALES, DEFAULT_LOCALE, MESSAGES, normalizeLocale, setLocale, getLocale, t };

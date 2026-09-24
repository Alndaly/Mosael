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
    zh: "本地后端意外退出(退出码 {code})。请重启 Mosael。",
    en: "The local backend exited unexpectedly (code {code}). Please restart Mosael.",
  },
  backend_startFailedTitle: { zh: "Mosael 后端启动失败", en: "Mosael backend failed to start" },
  backend_startFailedBody: {
    zh: "本地后端没能在端口 {port} 上就绪。请确认端口未被占用;日志可在 ~/.mosael/logs 查看。",
    en: "The local backend did not become healthy on port {port}. Check that the port is free and see logs in ~/.mosael/logs if available.",
  },
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

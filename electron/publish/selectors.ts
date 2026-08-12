import { resolvePlatform } from "./platforms";

/**
 * Centralized platform page contracts. CSS selectors are used with the driver's css* methods
 * (valid querySelector syntax only — attribute matchers like [class^='x'] are
 * fine, but Playwright's :has-text/text= are NOT, so text matching goes through
 * PageDriver's *Text helpers). Grounded in public automation projects + a live
 * pass against each login page; post-upload form selectors still warrant a
 * confirmation pass after a real in-app login.
 */
/**
 * 「发布成功后会跳到哪里」的 URL 模式。提到模块级共用:`isManageUrl`/`isListUrl` 用它做终态判定,
 * 适配器的 commitClick 受理判定也用它——同一个语义写两遍必然会分叉。
 */
export const MANAGE_URL_PATTERNS = {
  douyin: /content\/manage/,
  xiaohongshu: /creator\.xiaohongshu\.com\/(new\/notes|publish\/success)/,
  weixinChannels: /platform\/post\/list/,
  bilibili: /upload-manager|content-manager|article/,
  tiktok: /tiktokstudio\/content|tiktokstudio\/upload\?.*posted/,
  // **不能只写 /videos/** —— 上传页本身就是 `.../videos/upload?...`,那样这条在点提交之前就已经
  // 为真,收尾判定等于没做(实测:提交后 3 毫秒就"确认成功")。排除掉 /upload 才是"回到了列表页"。
  youtube: /studio\.youtube\.com\/channel\/[^/]+\/videos(?!\/upload)/,
} as const;

export const SELECTORS = {
  douyin: {
    uploadUrl: resolvePlatform("douyin").publishUrl,
    fileInput: "div[class^='container'] input[type='file'], input[type='file']",
    titleInput: 'input[placeholder*="填写作品标题"], input[placeholder*="作品标题"]', // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
    descEditor: 'div.zone-container[contenteditable="true"], div[contenteditable="true"]',
    overlays: '.shepherd-element, .shepherd-modal-overlay-container, [class*="mention-wrapper"]',
    submitText: "发布", // i18n-ok
    uploadDoneText: "重新上传", // i18n-ok
    uploadFailedText: "上传失败", // i18n-ok
    loggedOutTexts: ["扫码登录", "手机号登录", "二维码失效"], // i18n-ok
    loggedInTexts: ["高清发布", "发布视频", "作品管理", "内容管理", "创作者中心"], // i18n-ok
    // 可见性(实测):三档各是一个 label 包着 input[type=checkbox],默认「公开」已选中。
    // **按文案找,不按类名** —— radio-d4zkru 这种是构建期哈希,下次发版就变。
    visibilityTexts: { public: ["公开"], friends: ["好友可见"], private: ["仅自己可见"] } as const, // i18n-ok
    isPublishUrl: (u: string): boolean => /content\/(publish|post\/video)/.test(u),
    isManageUrl: (u: string): boolean => MANAGE_URL_PATTERNS.douyin.test(u),
  },
  xiaohongshu: {
    publishUrl: resolvePlatform("xiaohongshu").publishUrl,
    videoTabText: "上传视频", // i18n-ok
    fileInput: 'input[type="file"]',
    titleInput:
      'input[placeholder*="填写标题"], input[placeholder*="请输入标题"], input[placeholder*="标题"], textarea[placeholder*="标题"]', // i18n-ok
    contentEditor:
      'div[contenteditable="true"], .ql-editor, [data-placeholder*="正文"], [aria-label*="正文"]', // i18n-ok
    submitButton:
      'xhs-publish-btn[is-publish="true"][submit-disabled="false"], .publish-page-publish-btn button',
    // Custom element whose host exposes enabled/loading state via attributes.
    // Recent Xiaohongshu builds do not expose an open shadow root, so submit is
    // triggered through the host node contract instead of coordinate clicks.
    submitHost: "xhs-publish-btn",
    // 「原创声明」:实测是 .original-wrapper 里的 input[type=checkbox],默认不勾。
    originalSwitch: ".original-wrapper input[type=checkbox]",
    submitText: "发布", // i18n-ok
    uploadProgressTexts: ["正在上传视频", "视频上传中", "上传中"], // i18n-ok
    publishDoneTexts: ["发布成功", "发布完成", "审核中", "笔记发布成功", "提交成功"], // i18n-ok
    loggedInTexts: ["发布笔记", "创作中心", "数据中心"], // i18n-ok
    isLoginUrl: (u: string): boolean => /\/login/.test(u),
    isPublishEditorUrl: (u: string): boolean => /\/publish\/publish|\/new\/publish/.test(u),
  },
  weixinChannels: {
    createUrl: resolvePlatform("weixin-channels").publishUrl,
    revealUploadText: "发表视频", // i18n-ok
    fileInput: 'input[type="file"]',
    descEditor: 'div.input-editor[contenteditable="true"], div.input-editor',
    shortTitleInput:
      'input[placeholder*="填写短标题"], input[placeholder*="短标题"], input.weui-desktop-form__input', // i18n-ok
    submitText: "发表", // i18n-ok
    uploadFailed: 'div.status-msg.error, .status-msg.error, [class*="error"]',
    publishDoneTexts: ["发表成功", "发布成功", "已发表", "审核中", "提交成功"], // i18n-ok
    adminVerifyText: "管理员本人验证", // i18n-ok
    noPermissionText: "你还不能发表视频", // i18n-ok
    loggedInTexts: ["通知中心", "内容管理", "数据中心"], // i18n-ok
    // QR lives in a CROSS-ORIGIN iframe, so detect the login landing container.
    loginLanding:
      '.login-view, .login-qrcode-wrap, .qrcode-wrap, iframe[src*="login-for-iframe"], iframe[src*="login"]',
    isLoginUrl: (u: string): boolean => /login/.test(u),
    isListUrl: (u: string): boolean => MANAGE_URL_PATTERNS.weixinChannels.test(u),
  },
  bilibili: {
    uploadUrl: resolvePlatform("bilibili").publishUrl,
    manageUrl: resolvePlatform("bilibili").manageUrl,
    fileInput: 'input[type="file"]',
    titleInput:
      'input[placeholder*="标题"], textarea[placeholder*="标题"], input[maxlength="80"], input[maxlength="100"]', // i18n-ok
    descEditor:
      'textarea[placeholder*="简介"], textarea[placeholder*="描述"], div[contenteditable="true"], .ql-editor, .bcc-editor, .desc-textarea textarea', // i18n-ok
    tagInput:
      'input[placeholder*="标签"], input[placeholder*="tag"], input[placeholder*="Tag"], input[placeholder*="Enter"], input[placeholder*="回车"]', // i18n-ok
    statementInput: 'input[placeholder*="创作声明"]', // i18n-ok
    statementOptionText: "内容无需标注", // i18n-ok
    recommendedTag: ".tag-wrp .hot-tag-container, .tag-list .hot-tag-container",
    coverSelected: ".cover .cover-item, .cover .img-item-cover-selected",
    coverRecommendation: ".cover .img-item-cover",
    submitButton: ".submit-add",
    submitTexts: ["立即投稿", "投稿", "发布"], // i18n-ok
    loggedOutTexts: ["登录", "扫码登录", "密码登录", "短信登录"], // i18n-ok
    loggedInTexts: ["创作首页", "稿件管理", "内容管理", "投稿", "创作中心"], // i18n-ok
    uploadDoneTexts: ["上传完成", "上传成功", "视频上传完成", "上传完毕"], // i18n-ok
    uploadFailedTexts: ["上传失败", "上传出错", "重新上传"], // i18n-ok
    publishDoneTexts: ["投稿成功", "提交成功", "发布成功", "审核中", "稿件投递成功"], // i18n-ok
    isLoginUrl: (u: string): boolean => /passport\.bilibili\.com|\/login/.test(u),
    isManageUrl: (u: string): boolean => MANAGE_URL_PATTERNS.bilibili.test(u),
  },
  /**
   * TikTok。**界面语言跟账号走**(英文 / 中文 / 其它),所以能用结构就不用文案:
   * TikTok 站内大量使用 `data-e2e` 属性,实测登录页上就有 `login-title`、`tiktok-logo` 等 —— 它们
   * 比 "Log in to TikTok" 这种句子稳得多。文案只作为兜底,且中英各列一份。
   */
  tiktok: {
    uploadUrl: resolvePlatform("tiktok").publishUrl,
    manageUrl: resolvePlatform("tiktok").manageUrl,
    fileInput: 'input[type="file"]',
    // 文案编辑器是 DraftJS,不是 <input>。
    captionEditor:
      '.public-DraftEditor-content[contenteditable="true"], div[contenteditable="true"][role="combobox"], div[contenteditable="true"]',
    postButton: '[data-e2e="post_video_button"], button[data-e2e="post_video_button"]',
    // 可见性(实测 DOM):容器带 data-e2e,里面是个 Select 的 combobox 按钮,默认值 Everyone。
    visibilityTrigger:
      '[data-e2e="video_visibility_container"] [role="combobox"], [data-e2e="video_visibility_container"] button',
    visibilityValue: '[data-e2e="video_visibility_container"]',
    // 下拉项:Select 组件的选项,中英各列一份(界面语言跟账号走)。
    visibilityOption: '[role="option"], .Select__item, li',
    // 可见性三档的选项文案(实测下拉里是 div[role=option].Select__item;界面语言跟账号走)。
    visibilityTexts: {
      private: ["Only you", "仅自己可见", "仅自己"], // i18n-ok
      friends: ["Friends", "好友"], // i18n-ok
      public: ["Everyone", "所有人"], // i18n-ok
    } as const,
    // 上传页会弹「是否开启自动内容检查」;它是个模态,挡住真实点击。**点取消**——不替用户改账号设置。
    dismissTexts: ["Cancel", "取消", "Got it", "知道了"], // i18n-ok
    postTexts: ["Post", "发布"], // i18n-ok
    loggedOutMarks: '[data-e2e="login-title"], [data-e2e="channel-item"]',
    loggedOutTexts: ["Log in to TikTok", "Use QR code", "登录 TikTok", "扫码登录"], // i18n-ok
    loggedInTexts: ["Upload video", "Select video", "上传视频", "选择视频"], // i18n-ok
    uploadingTexts: ["Uploading", "上传中", "%"], // i18n-ok
    uploadFailedTexts: ["Upload failed", "上传失败", "Failed to upload"], // i18n-ok
    // **别放宽泛词。** 原先这里有 "posted" 和 "Manage your posts" —— 前者是内容列表的列名,后者是
    // 导航项,两者在**点发布之前**就在页面上,判定因此恒真(YouTube 那边的「已上传」栽过同一个跟头,
    // 表现是提交后几毫秒即"成功",而什么都还没发生)。只留发布完成后才会出现的完整说法。
    publishDoneTexts: ["Your video is being uploaded", "视频正在上传", "发布成功", "已发布", "Video posted"], // i18n-ok
    isLoginUrl: (u: string): boolean => /\/login|accounts\.tiktok\.com/.test(u),
    isManageUrl: (u: string): boolean => MANAGE_URL_PATTERNS.tiktok.test(u),
  },
  /**
   * YouTube Studio。**未登录会跳到 accounts.google.com** —— 这是最可靠的登录判据,实测过。
   *
   * Studio 是 Polymer 应用,节点大多带稳定 id(`#title-textarea`、`#next-button`…),
   * 这些 id 在公开的自动上传项目里长期有效,比文案稳。
   *
   * **可见性默认发为 Private**:自动上传一旦误发公开是收不回的。想公开由人到 YouTube 上改一次,
   * 代价远小于反过来。这一点也写进了后端的平台说明,用户在界面上看得到。
   */
  youtube: {
    // /upload 会直接把 Studio 带进上传对话框,比先进 Studio 再点「创建」少两跳。
    uploadUrl: "https://www.youtube.com/upload",
    fileInput: 'input[type="file"]',
    titleBox: '#title-textarea #textbox, ytcp-social-suggestions-textbox[id="title-textarea"] #textbox',
    descBox: '#description-textarea #textbox, ytcp-social-suggestions-textbox[id="description-textarea"] #textbox',
    notMadeForKids: 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
    madeForKids: 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_MFK"]',
    nextButton: "#next-button",
    // 可见性三档:name 是 Studio 自己的枚举,比文案稳(界面语言跟账号走)。
    visibilityRadio: {
      private: 'tp-yt-paper-radio-button[name="PRIVATE"]',
      unlisted: 'tp-yt-paper-radio-button[name="UNLISTED"]',
      public: 'tp-yt-paper-radio-button[name="PUBLIC"]',
    } as const,
    privateRadio: 'tp-yt-paper-radio-button[name="PRIVATE"]',
    doneButton: "#done-button",
    closeDialog: "#close-button",
    // 「还在传」的痕迹。**只认上传那一段**,不含 Processing/处理中 —— 处理可以长达几十分钟,而
    // YouTube 允许在处理期间就把稿件发出去;把处理也算成"没传完"会让流程白等到超时。
    uploadProgressPattern: "Uploading|上传中|正在上传|\\d+%", // i18n-ok
    // 实测中文界面的真实文案(2026-08 抓的现场):**「检查完毕」不是「检查完成」**,而最强的一条是
    // 「已保存为私享视频」—— 草稿一落库就出现,正是"传完了"的意思。原先那份是照着英文猜的翻译,
    // 一条都没命中,于是判据只能靠超时收场。
    uploadDoneTexts: [
      "已保存为私享视频", "已保存为草稿", "上传完毕", "上传完成", "检查完毕", "检查完成", "处理完毕", "处理完成", // i18n-ok
      "Saved as private", "Saved as draft", "Upload complete", "Checks complete", "Processing complete",
    ],
    uploadFailedTexts: ["Upload failed", "上传失败", "Daily upload limit reached"], // i18n-ok
    // 「已上传」删掉:Studio 列表页上到处都是这两个字,留着等于判定恒真。只认发布完成对话框里
    // 那句完整的话。
    publishDoneTexts: ["视频已发布", "视频已上传", "Video published", "Video uploaded"], // i18n-ok
    loggedInTexts: ["YouTube Studio", "Channel dashboard", "创作者工作室", "频道数据"], // i18n-ok
    // 未登录时 Google 会把你送去登录页;这比找文案可靠得多。
    isLoginUrl: (u: string): boolean => /accounts\.google\.com|\/ServiceLogin|signin/.test(u),
    isManageUrl: (u: string): boolean => MANAGE_URL_PATTERNS.youtube.test(u),
  },
} as const;

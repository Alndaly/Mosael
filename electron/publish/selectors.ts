import { resolvePlatform } from "./platforms";

/**
 * Centralized platform page contracts. CSS selectors are used with the driver's css* methods
 * (valid querySelector syntax only — attribute matchers like [class^='x'] are
 * fine, but Playwright's :has-text/text= are NOT, so text matching goes through
 * PageDriver's *Text helpers). Grounded in public automation projects + a live
 * pass against each login page; post-upload form selectors still warrant a
 * confirmation pass after a real in-app login.
 */
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
    isPublishUrl: (u: string): boolean => /content\/(publish|post\/video)/.test(u),
    isManageUrl: (u: string): boolean => /content\/manage/.test(u),
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
    isListUrl: (u: string): boolean => /platform\/post\/list/.test(u),
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
    isManageUrl: (u: string): boolean => /upload-manager|content-manager|article/.test(u),
  },
} as const;

import type { PublishTask } from "./types";
import { resolvePlatform } from "./platforms";
import type { PageDriver } from "./pageDriver";
import { AutomationBlockedError } from "./errors";

export interface PublishAdapter {
  openCreatorPage(): Promise<void>;
  checkLogin(): Promise<boolean>;
  uploadVideo(videoPath: string): Promise<void>;
  fillTitle(title: string): Promise<void>;
  fillTags(tags: string[]): Promise<void>;
  submit(): Promise<void>;
  waitResult(): Promise<void>;
}

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

// 站内文案:拿去和真实中文站点做文本匹配的**选择器**,不是本应用的 UI 文案 —— 翻译了就点不中。
// 提成常量而不是行内字面量:行内时 `// i18n-ok` 只能挂在 `{` 后面,prettier 会把它挪进块内,
// 而 check-i18n 的豁免是逐行判的(规则 5),挪走就漏判。属性/声明后的行尾注释 prettier 不动
// (与下方各平台配置里 submitText 等的写法一致)。
const TEXT_PUBLISH_VIDEO = "发布视频"; // i18n-ok
const TEXT_NEW_TOPIC = "新建话题"; // i18n-ok

// Generous because real video uploads/transcoding can take minutes.
const UPLOAD_TIMEOUT = 10 * 60 * 1000;
const RESULT_TIMEOUT = 2 * 60 * 1000;
const ACTION_TIMEOUT = 30 * 1000;
const HUMAN_INTERVENTION_TIMEOUT = 10 * 60 * 1000;

const normalizeTag = (tag: string): string => tag.replace(/^#/, "").trim();

const escapeHtml = (value: string): string =>
  value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const stringOption = (task: PublishTask, key: string): string | null => {
  const value = task.platformOptions[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

/**
 * Centralized selectors. CSS selectors are used with the driver's css* methods
 * (valid querySelector syntax only — attribute matchers like [class^='x'] are
 * fine, but Playwright's :has-text/text= are NOT, so text matching goes through
 * the *Text helpers below). Grounded in public automation projects + a live
 * pass against each login page; the post-upload form selectors still warrant a
 * confirmation pass after a real in-app login.
 */
const SELECTORS = {
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

export class MockAdapter implements PublishAdapter {
  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.setHtml(`
      <main style="font-family: system-ui; padding: 32px;">
        <h1>Mibu Mock Publisher</h1>
        <p>Task: ${escapeHtml(this.task.title)}</p>
        <p id="status">Status: preparing</p>
      </main>
    `);
    await wait(500);
  }

  async checkLogin(): Promise<boolean> {
    await wait(300);
    return true;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    await this.status(`selected video: ${videoPath}`);
    await wait(700);
  }

  async fillTitle(title: string): Promise<void> {
    await this.status(`filled title: ${title}`);
    await wait(400);
  }

  async fillTags(tags: string[]): Promise<void> {
    await this.status(`filled tags: ${tags.join(", ") || "none"}`);
    await wait(400);
  }

  async submit(): Promise<void> {
    await this.status("submitted");
    await wait(500);
  }

  async waitResult(): Promise<void> {
    await this.status("publish success");
    await wait(500);
  }

  private async status(message: string): Promise<void> {
    await this.driver.evaluate(
      `(() => { const n = document.getElementById('status'); if (n) n.textContent = ${JSON.stringify(
        `Status: ${message}`,
      )}; })()`,
    );
  }
}

export class DouyinAdapter implements PublishAdapter {
  private readonly s = SELECTORS.douyin;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
    const uploadReady = await this.driver.fileInputAttached(this.s.fileInput, 6_000);
    if (!uploadReady && (await this.driver.hasText(TEXT_PUBLISH_VIDEO))) {
      await this.driver
        .clickByText(TEXT_PUBLISH_VIDEO, {
          exact: true,
          selector: "button, [role=button], a, div, span",
        })
        .catch(() => undefined);
    }
  }

  async checkLogin(): Promise<boolean> {
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasText(text)) {
        return false;
      }
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasText(text)) {
        return true;
      }
    }
    return this.driver.cssAttached(this.s.fileInput, 8_000);
  }

  async uploadVideo(videoPath: string): Promise<void> {
    await this.driver.cssAttached(this.s.fileInput, ACTION_TIMEOUT);
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.driver.waitForUrl(this.s.isPublishUrl, ACTION_TIMEOUT);

    const settled = await this.driver.waitForFunction(
      `/(${this.s.uploadDoneText}|${this.s.uploadFailedText})/.test(document.body.innerText)`,
      UPLOAD_TIMEOUT,
      1_500,
    );
    if (!settled) {
      throw new Error("Douyin upload did not complete in time.");
    }
    if (await this.driver.hasText(this.s.uploadFailedText)) {
      throw new Error("Douyin reported video upload failure (上传失败)."); // i18n-ok
    }
  }

  async fillTitle(title: string): Promise<void> {
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillCss(this.s.titleInput, title.slice(0, 30));
  }

  async fillTags(tags: string[]): Promise<void> {
    const description = stringOption(this.task, "description");
    if (description) {
      await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
      await this.driver.insertText(this.s.descEditor, description);
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const topicText = `#${normalizedTag}`;
      await this.driver.insertText(this.s.descEditor, ` ${topicText}`);
      await wait(800);
      const pickedTopic = await this.driver
        .clickCenterByText(topicText, {
          selector: '[class*="mention-suggest"] div, [class*="mention-suggest"] span',
        })
        .then(() => true)
        .catch(() => false);
      if (pickedTopic) {
        await this.driver.waitForFunction(
          `[...document.querySelectorAll('[data-mention="#"]')].some((el) => (el.textContent || '').includes(${JSON.stringify(
            topicText,
          )}))`,
          2_000,
          200,
        );
      } else {
        await this.driver.pressKey("Space");
      }
      await this.driver.insertText(this.s.descEditor, " ");
      await wait(300);
    }
    await this.driver.pressKey("Escape");
  }

  async submit(): Promise<void> {
    await this.driver.removeElements(this.s.overlays); // shepherd.js onboarding overlays
    // Exact match first so 发布 can't hit e.g. 定时发布/发布设置; fall back to
    // the looser match in case the button text carries extra decoration.
    await this.driver
      .clickByText(this.s.submitText, { exact: true })
      .catch(() => this.driver.clickByText(this.s.submitText));
  }

  async waitResult(): Promise<void> {
    const ok = await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT);
    if (!ok) {
      throw new Error("Douyin did not confirm publish (no redirect to content management).");
    }
  }
}

export class XiaohongshuAdapter implements PublishAdapter {
  private readonly s = SELECTORS.xiaohongshu;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.publishUrl);
    // Default tab is image-text; switch to the video uploader if present.
    await this.driver
      .clickByText(this.s.videoTabText, {
        exact: true,
        selector: "button, [role=button], a, div, span",
      })
      .catch(() => undefined);
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasText(text)) {
        return true;
      }
    }
    return this.driver.cssAttached(this.s.fileInput, 4_000);
  }

  async uploadVideo(videoPath: string): Promise<void> {
    await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    await this.driver.setFiles(this.s.fileInput, videoPath);
    // Editor fields render once the upload is accepted; wait for the title.
    const ready = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!ready) {
      throw new Error("Xiaohongshu editor did not appear after upload (title field missing).");
    }
    const publishReady =
      (await this.driver.waitCssEnabled(this.s.submitButton, UPLOAD_TIMEOUT)) ||
      (await this.driver.waitTextEnabledDeep(this.s.submitText, 1_000, {
        hostSelector: this.s.submitHost,
      }));
    if (!publishReady) {
      throw new Error(
        "Xiaohongshu upload did not finish in time (publish button stayed disabled).",
      );
    }
  }

  async fillTitle(title: string): Promise<void> {
    const value = title.slice(0, 20);
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillCss(this.s.titleInput, value);
    const accepted = await this.driver.waitForFunction(
      `(() => {
        const el = document.querySelector(${JSON.stringify(this.s.titleInput)});
        return el && el.value === ${JSON.stringify(value)};
      })()`,
      3_000,
      200,
    );
    const current = await this.driver.cssValue(this.s.titleInput);
    if (!accepted || current !== value) {
      throw new Error("Xiaohongshu title input did not accept the filled value.");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    const description = stringOption(this.task, "description");
    if (description) {
      await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
      await this.driver.insertText(this.s.contentEditor, description);
      await this.driver.insertText(this.s.contentEditor, " ");
      const accepted = await this.driver.waitForFunction(
        `(() => (document.querySelector(${JSON.stringify(
          this.s.contentEditor,
        )})?.innerText || '').includes(${JSON.stringify(description)}))()`,
        3_000,
        200,
      );
      if (!accepted) {
        throw new Error("Xiaohongshu content editor did not accept the description.");
      }
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      await this.driver.insertText(this.s.contentEditor, `#${normalizedTag}`);
      await this.driver.waitForFunction(
        `(() => {
          const target = ${JSON.stringify(`#${normalizedTag}`)};
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
          };
          return [
            ...document.querySelectorAll(
              '#creator-editor-topic-container .item, [data-tippy-root] .item, .tippy-content .item'
            )
          ].some((el) => visible(el) && (el.textContent || '').includes(target));
        })()`,
        2_500,
        200,
      );
      const picked =
        (await this.driver.clickXiaohongshuTopicCandidate(normalizedTag)) ||
        (await this.driver
          .clickByText(TEXT_NEW_TOPIC, {
            exact: true,
            selector: "#creator-editor-topic-container *, [data-tippy-root] *, .tippy-content *",
          })
          .then(() => true)
          .catch(() => false));
      if (!picked) {
        await this.driver.pressKey("Enter");
      }
      const selected = await this.driver.waitForFunction(
        `(() => [...document.querySelectorAll('a.tiptap-topic')].some((el) => { // i18n-ok
          const data = el.getAttribute('data-topic') || '';
          const text = (el.textContent || '').replace('[话题]#', '').replace(/^#/, '').trim();
          return text === ${JSON.stringify(normalizedTag)} || data.includes(${JSON.stringify(
            `"name":"${normalizedTag}"`,
          )});
        }))()`,
        5_000,
        300,
      );
      if (!selected && !(await this.driver.hasXiaohongshuTopic(normalizedTag))) {
        throw new Error(`Xiaohongshu topic was not selected: #${normalizedTag}`);
      }
      await this.driver.insertText(this.s.contentEditor, " ");
    }
  }

  async submit(): Promise<void> {
    const ready =
      (await this.driver.waitCssEnabled(this.s.submitButton, ACTION_TIMEOUT)) ||
      (await this.driver.waitTextEnabledDeep(this.s.submitText, 1_000, {
        hostSelector: this.s.submitHost,
      }));
    if (!ready) {
      throw new Error("Xiaohongshu publish button is not clickable.");
    }

    if (await this.driver.publishXiaohongshuCustomElement(this.s.submitHost)) {
      return;
    }
    if (await this.driver.clickInShadow(this.s.submitHost, this.s.submitText)) {
      return;
    }
    if (await this.driver.activateCustomElement(this.s.submitHost)) {
      return;
    }
    await this.driver.clickByText(this.s.submitText, {
      exact: true,
      selector: "button, [role=button], div, span",
    });
  }

  async waitResult(): Promise<void> {
    const donePattern = this.s.publishDoneTexts.join("|");
    await wait(1_000);
    const ok = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return true;
        const url = location.href;
        const isEditor = /\\/publish\\/publish|\\/new\\/publish/.test(url);
        const hasPublishHost = Boolean(document.querySelector(${JSON.stringify(this.s.submitHost)}));
        return !isEditor && !hasPublishHost && /creator\\.xiaohongshu\\.com/.test(url);
      })()`,
      RESULT_TIMEOUT,
      1_000,
    );
    if (!ok) {
      throw new Error(
        "Xiaohongshu did not confirm publish (no success text and still on/near the publish editor).",
      );
    }
  }
}

export class WeixinChannelsAdapter implements PublishAdapter {
  private readonly s = SELECTORS.weixinChannels;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.createUrl);
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    if (await this.driver.cssVisible(this.s.loginLanding, 2_500)) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    return this.driver.fileInputAttached(this.s.fileInput, 4_000);
  }

  async uploadVideo(videoPath: string): Promise<void> {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    let attached = await this.driver.fileInputAttached(this.s.fileInput, 8_000);
    if (!attached) {
      await this.driver.clickByText(this.s.revealUploadText).catch(() => undefined);
      attached = await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    }
    if (!attached) {
      throw new Error("WeChat Channels upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();

    // Upload done == the 发表 button leaves its disabled state.
    const ok = await this.driver.waitButtonEnabled(this.s.submitText, UPLOAD_TIMEOUT);
    if (!ok) {
      if (await this.driver.cssVisible(this.s.uploadFailed, 500)) {
        throw new Error("WeChat Channels reported an upload error (status-msg.error).");
      }
      throw new Error("WeChat Channels upload did not complete in time.");
    }
  }

  async fillTitle(title: string): Promise<void> {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const description = stringOption(this.task, "description") ?? title;
    const shortTitle = stringOption(this.task, "shortTitle") ?? title;
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    await this.driver.insertText(this.s.descEditor, description);
    // Optional short title (best effort; skipped if the field is absent).
    if (await this.driver.cssVisible(this.s.shortTitleInput, 2_000)) {
      await this.driver
        .fillCss(this.s.shortTitleInput, shortTitle.slice(0, 16))
        .catch(() => undefined);
    } else {
      await this.driver.fillInputNearText("短标题", shortTitle.slice(0, 16)).catch(() => false); // i18n-ok
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      await this.driver.insertText(this.s.descEditor, ` #${normalizedTag}`);
      await this.driver.pressKey("Space");
      await wait(300);
    }
  }

  async submit(): Promise<void> {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const ready = await this.driver.waitButtonEnabled(this.s.submitText, ACTION_TIMEOUT);
    if (!ready) {
      throw new Error("WeChat Channels publish button is not clickable.");
    }
    await this.driver
      .clickByTextDeep(this.s.submitText, { exact: true })
      .catch(() => this.driver.clickByText(this.s.submitText, { exact: true }));
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
  }

  async waitResult(): Promise<void> {
    const donePattern = this.s.publishDoneTexts.join("|");
    const ok =
      (await this.driver.waitForUrl(this.s.isListUrl, RESULT_TIMEOUT)) ||
      (await this.driver.waitForFunction(
        `(() => {
          const seen = new Set();
          const collect = (root) => {
            if (!root || seen.has(root)) return '';
            seen.add(root);
            let text = root instanceof Document ? (root.body?.innerText || '') : (root.textContent || '');
            for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
              if (el.shadowRoot) text += '\\n' + collect(el.shadowRoot);
            }
            return text;
          };
          return new RegExp(${JSON.stringify(donePattern)}).test(collect(document));
        })()`,
        10_000,
      ));
    if (!ok) {
      throw new Error("WeChat Channels did not confirm publish (no redirect to post list).");
    }
  }

  private async waitForHumanGateIfNeeded(): Promise<void> {
    if (await this.driver.hasTextDeep(this.s.adminVerifyText)) {
      const cleared = await this.driver.waitTextGoneDeep(
        this.s.adminVerifyText,
        HUMAN_INTERVENTION_TIMEOUT,
        2_000,
      );
      if (!cleared) {
        throw new AutomationBlockedError(
          "manual_required",
          "WeChat Channels requires admin verification. Complete the QR verification in the embedded view, then retry.",
        );
      }
    }
  }

  private async assertCanPublish(): Promise<void> {
    if (await this.driver.hasTextDeep(this.s.noPermissionText)) {
      throw new AutomationBlockedError(
        "permission_required",
        "WeChat Channels says this WeChat account is not an admin/operator for the selected channel.",
      );
    }
  }
}

export class BilibiliAdapter implements PublishAdapter {
  private readonly s = SELECTORS.bilibili;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    if (await this.driver.cssAttached(this.s.fileInput, 6_000)) {
      return true;
    }
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return false;
      }
    }
    return false;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    const attached = await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    if (!attached) {
      throw new Error("Bilibili upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    const editorReady = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!editorReady) {
      throw new Error("Bilibili editor did not appear after upload (title field missing).");
    }

    const donePattern = this.s.uploadDoneTexts.join("|");
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const settled = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return true;
        if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return true;
        return Boolean(document.querySelector(${JSON.stringify(this.s.titleInput)}));
      })()`,
      UPLOAD_TIMEOUT,
      1_000,
    );
    if (!settled) {
      throw new Error("Bilibili upload did not complete in time.");
    }
    if (
      await this.driver.waitForFunction(
        `new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`,
        500,
        100,
      )
    ) {
      throw new Error("Bilibili reported video upload failure.");
    }
  }

  async fillTitle(title: string): Promise<void> {
    const value = title.slice(0, 80);
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillField(this.s.titleInput, value);
    const current = await this.driver.cssValue(this.s.titleInput);
    if (!current?.includes(value)) {
      throw new Error("Bilibili title input did not accept the filled value.");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    await this.selectCreationStatement();

    const description = stringOption(this.task, "description");
    if (description) {
      if (await this.driver.cssVisible(this.s.descEditor, 5_000)) {
        await this.driver.fillField(this.s.descEditor, description);
      } else {
        await this.driver.fillInputNearText("简介", description).catch(() => false); // i18n-ok
      }
    }

    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const inserted =
        (await this.clickRecommendedTag(normalizedTag)) ||
        (await this.inputTag(normalizedTag)) ||
        (await this.driver
          .fillInputNearText("标签", normalizedTag) // i18n-ok
          .then(async (ok) => {
            if (ok) {
              await this.driver.pressKey("Enter");
              return this.waitForTagChip(normalizedTag);
            }
            return false;
          })
          .catch(() => false)) ||
        (await this.clickAnyRecommendedTag());
      if (!inserted) {
        throw new Error(`Bilibili tag was not accepted: #${normalizedTag}`);
      }
      await wait(200);
    }
    await this.selectRecommendedCover();
  }

  async submit(): Promise<void> {
    if (await this.driver.cssVisible(this.s.submitButton, 5_000)) {
      await this.driver.clickCenterCss(this.s.submitButton);
      return;
    }
    for (const text of this.s.submitTexts) {
      const clicked = await this.driver
        .clickByText(text, {
          exact: true,
          selector: "button, [role=button], a, div, span",
        })
        .then(() => true)
        .catch(() => false);
      if (clicked) {
        return;
      }
    }
    throw new Error("Bilibili publish button was not found.");
  }

  async waitResult(): Promise<void> {
    const donePattern = this.s.publishDoneTexts.join("|");
    const ok =
      (await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT)) ||
      (await this.driver.waitForFunction(
        `new RegExp(${JSON.stringify(donePattern)}).test(document.body?.innerText || '')`,
        RESULT_TIMEOUT,
        1_000,
      ));
    if (!ok) {
      throw new Error("Bilibili did not confirm publish (no success text or manager redirect).");
    }
  }

  private async inputTag(tag: string): Promise<boolean> {
    const focused = await this.driver.focusAndClearField(this.s.tagInput);
    if (!focused) {
      return false;
    }
    await this.driver.type(tag);
    await this.driver.pressKey("Enter");
    return this.waitForTagChip(tag);
  }

  private async selectCreationStatement(): Promise<void> {
    const selected = await this.driver.evaluate<boolean>(`(() => {
      const input = [...document.querySelectorAll(${JSON.stringify(this.s.statementInput)})]
        .find((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
      return Boolean(input && input.value && input.value.trim());
    })()`);
    if (selected) {
      return;
    }

    const optionText = JSON.stringify(this.s.statementOptionText);
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const clickElement = (el) => {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        const init = {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2,
          button: 0
        };
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll('.creation-statement-container .bcc-option')]
        .find((el) => (el.innerText || el.textContent || '').trim() === ${optionText});
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);

    if (!clicked) {
      return;
    }

    const accepted = await this.driver.waitForFunction(
      `(() => {
        const input = [...document.querySelectorAll(${JSON.stringify(this.s.statementInput)})]
          .find((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          });
        return Boolean(input && input.value && input.value.trim());
      })()`,
      3_000,
      250,
    );
    if (!accepted) {
      throw new Error("Bilibili creation statement did not become selected.");
    }
  }

  private async clickRecommendedTag(tag: string): Promise<boolean> {
    const expected = JSON.stringify(tag);
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        const init = {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2,
          button: 0
        };
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll(${JSON.stringify(this.s.recommendedTag)})]
        .find((el) => visible(el) && (el.innerText || el.textContent || '').trim() === ${expected});
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);
    if (!clicked) {
      return false;
    }
    return this.waitForTagChip(tag);
  }

  private async clickAnyRecommendedTag(): Promise<boolean> {
    const before = await this.driver.evaluate<number>(
      `document.querySelectorAll('#tag-container .label-item-v2-content').length`,
    );
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        const init = {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2,
          button: 0
        };
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll(${JSON.stringify(this.s.recommendedTag)})]
        .find((el) => visible(el) && !/(^|\\s)hot-tag-container-selected(\\s|$)/.test(String(el.className || '')));
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);
    if (!clicked) {
      return false;
    }
    return this.driver.waitForFunction(
      `document.querySelectorAll('#tag-container .label-item-v2-content').length > ${before}`,
      3_000,
      250,
    );
  }

  private async selectRecommendedCover(): Promise<void> {
    const alreadySelected = await this.driver.cssVisible(this.s.coverSelected, 2_000);
    if (alreadySelected) {
      return;
    }

    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        const init = {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: window,
          clientX: r.left + r.width / 2,
          clientY: r.top + r.height / 2,
          button: 0
        };
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const cover = [...document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)})]
        .find(visible);
      if (!cover) return false;
      clickElement(cover);
      return true;
    })()`);

    if (!clicked) {
      return;
    }

    const selected = await this.driver.cssVisible(this.s.coverSelected, 5_000);
    if (!selected) {
      throw new Error("Bilibili recommended cover did not become selected.");
    }
  }

  private async waitForTagChip(tag: string): Promise<boolean> {
    const expected = JSON.stringify(tag);
    return this.driver.waitForFunction(
      `(() => {
        const texts = [
          ...document.querySelectorAll('#tag-container .label-item-v2-content, #tag-container [class*="label"][class*="content"], #tag-container [class*="tag-pre"] *')
        ]
          .map((el) => (el.textContent || '').trim())
          .filter(Boolean);
        return texts.some((text) => text === ${expected});
      })()`,
      3_000,
      250,
    );
  }
}

export const createAdapter = (
  platform: string,
  driver: PageDriver,
  task: PublishTask,
): PublishAdapter => {
  const normalizedPlatform = resolvePlatform(platform).id;
  if (normalizedPlatform === "douyin") {
    return new DouyinAdapter(driver, task);
  }
  if (normalizedPlatform === "xiaohongshu") {
    return new XiaohongshuAdapter(driver, task);
  }
  if (normalizedPlatform === "weixin-channels") {
    return new WeixinChannelsAdapter(driver, task);
  }
  if (normalizedPlatform === "bilibili") {
    return new BilibiliAdapter(driver, task);
  }
  return new MockAdapter(driver, task);
};

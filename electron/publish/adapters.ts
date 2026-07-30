import type { PublishTask } from "./types";
import { resolvePlatform } from "./platforms";
import type { PageDriver } from "./pageDriver";
import { AutomationBlockedError } from "./errors";
import { MANAGE_URL_PATTERNS, SELECTORS } from "./selectors";
import {
  PROCESSING_TEXTS,
  commitClick,
  domAttempt,
  pageReacted,
  pointerAttempt,
} from "./clickChain";
import { plog } from "./log";

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

/** 收尾判定失败时,把「当时页面究竟是什么」记下来:URL + 正文开头。
 *
 * 没有这条,故障在日志里只剩一句 `did not confirm publish`,而「平台改版导致文案/选择器失配」
 * 和「按钮点了但没生效」是两种完全不同的原因,却长得一模一样——只能靠猜。 */
async function plogPageState(tag: string, driver: PageDriver): Promise<void> {
  const text = await driver
    .evaluate<string>(`(document.body?.innerText || '').slice(0, 300)`)
    .catch(() => "");
  plog(tag, { url: driver.url(), text });
}

const normalizeTag = (tag: string): string => tag.replace(/^#/, "").trim();

const escapeHtml = (value: string): string =>
  value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const stringOption = (task: PublishTask, key: string): string | null => {
  const value = task.platformOptions[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

export class MockAdapter implements PublishAdapter {
  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.setHtml(`
      <main style="font-family: system-ui; padding: 32px;">
        <h1>Open Studio Mock Publisher</h1>
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
        .pointerClickByText(topicText, {
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
    await commitClick({
      what: "douyin submit",
      attempts: [
        // 精确匹配优先,免得「发布」命中「定时发布」/「发布设置」;宽松匹配兜底(按钮文案可能带装饰)。
        domAttempt(`text ${this.s.submitText} (exact)`, () =>
          this.driver.clickByText(this.s.submitText, { exact: true }),
        ),
        domAttempt(`text ${this.s.submitText} (loose)`, () =>
          this.driver.clickByText(this.s.submitText),
        ),
      ],
      // 抖音成功后跳转内容管理页,URL 变化是最强的受理信号。
      accepted: pageReacted(this.driver, {
        texts: [...PROCESSING_TEXTS, this.s.uploadFailedText],
        urlPattern: MANAGE_URL_PATTERNS.douyin,
      }),
    });
  }

  async waitResult(): Promise<void> {
    const ok = await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT);
    if (!ok) {
      await plogPageState("waitResult failed (douyin):", this.driver);
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
        (await this.clickTopicCandidate(normalizedTag)) ||
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
      if (!selected && !(await this.hasTopicChip(normalizedTag))) {
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

    // 四条降级路径互为兜底:发布按钮是 shadow DOM 里的自定义元素,外面 querySelector 不到,
    // 改版时往往是前几条陆续失效、最后落到最脆的按文案点击,而表现只是「偶尔发不出去」——
    // 所以走通的是哪一条必须记下来。这些路径全是派发事件,不依赖坐标,故都算 dom 类。
    await commitClick({
      what: "xiaohongshu submit",
      attempts: [
        domAttempt("dispatchPublishEvent", () =>
          this.expectTrue(this.dispatchPublishEvent(this.s.submitHost)),
        ),
        domAttempt("clickInShadow", () =>
          this.expectTrue(this.driver.clickInShadow(this.s.submitHost, this.s.submitText)),
        ),
        domAttempt("activateCustomElement", () =>
          this.expectTrue(this.driver.activateCustomElement(this.s.submitHost)),
        ),
        domAttempt(`text ${this.s.submitText}`, () =>
          this.driver.clickByText(this.s.submitText, {
            exact: true,
            selector: "button, [role=button], div, span",
          }),
        ),
      ],
      accepted: pageReacted(this.driver, {
        gone: this.s.submitHost,
        texts: [...PROCESSING_TEXTS, ...this.s.publishDoneTexts],
      }),
    });
  }


  // ---- 小红书专有的页面细节 ------------------------------------------------
  //
  // 这三段原先住在 PageDriver 上,方法名里带着 Xiaohongshu —— 通用页面驱动却写死一个平台的
  // 选择器(a.tiptap-topic / #creator-editor-topic-container / .tippy-box / <xhs-publish-btn>)。
  // 名字只是症状,病根是位置不对;改成通用名会更误导,所以搬到这里,顺带去掉冗余的平台前缀。

  private async hasTopicChip(tag: string): Promise<boolean> {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    return this.driver.evaluate<boolean>(`(() => { // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
      const target = ${normalized};
      return [...document.querySelectorAll('a.tiptap-topic')].some((el) => {
        const data = el.getAttribute('data-topic') || '';
        const text = (el.textContent || '').replace('[话题]#', '').replace(/^#/, '').trim();
        return text === target || data.includes('"name":"' + target + '"');
      });
    })()`);
  }

  private async clickTopicCandidate(tag: string): Promise<boolean> {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    const ok = await this.driver.evaluate<boolean>(`(() => { // i18n-ok
      const target = ${normalized};
      const topicText = '#' + target;
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const containers = [
        ...document.querySelectorAll(
          '#creator-editor-topic-container, [data-tippy-root], .tippy-box, .tippy-content'
        )
      ].filter(visible);
      const pool = containers.flatMap((container) => [
        ...container.querySelectorAll('.item, [role=option], button, [role=button], div, span')
      ]);
      const matches = pool.filter((el) => {
        if (!visible(el)) return false;
        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        return text === topicText ||
          text.startsWith(topicText + ' ') ||
          text.includes(topicText + '新建话题') ||
          text.includes('新建话题');
      });
      if (!matches.length) return false;
      const score = (el) => {
        const cls = (el.className || '').toString();
        const tagName = el.tagName.toLowerCase();
        let value = 0;
        if (/\\bitem\\b/.test(cls)) value -= 40;
        if (/is-selected/.test(cls)) value -= 30;
        if (tagName === 'button' || el.getAttribute('role') === 'button') value -= 10;
        if ((el.textContent || '').trim().startsWith(topicText)) value -= 5;
        const r = el.getBoundingClientRect();
        value += Math.max(0, r.width * r.height) / 10000;
        return value;
      };
      matches.sort((a, b) => score(a) - score(b));
      const el = matches[0];
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
      const fire = (type) => {
        const EventCtor = type.startsWith('pointer') && window.PointerEvent
          ? window.PointerEvent
          : window.MouseEvent;
        el.dispatchEvent(new EventCtor(type, init));
      };
      fire('pointerdown');
      fire('mousedown');
      if (typeof el.click === 'function') {
        el.click();
      } else {
        fire('click');
      }
      fire('mouseup');
      fire('pointerup');
      fire('click');
      return true;
    })()`);
    if (ok) {
      await wait(120);
    }
    return ok;
  }

  private async dispatchPublishEvent(selector: string): Promise<boolean> {
    const ok = await this.driver.evaluate<boolean>(`(() => {
      ${this.driver.deepQueryPrelude(selector)}
      const host = find(document);
      if (!host) return false;
      const rect = host.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      if (
        host.getAttribute('submit-disabled') === 'true' ||
        host.getAttribute('disabled') === 'true' ||
        host.getAttribute('aria-disabled') === 'true'
      ) {
        return false;
      }
      host.scrollIntoView({ block: 'center', inline: 'nearest' });
      if (typeof host._onPublish === 'function') {
        host._onPublish();
      } else {
        host.dispatchEvent(new CustomEvent('publish', { bubbles: true, composed: true }));
      }
      return true;
    })()`);
    if (ok) {
      await wait(120);
    }
    return ok;
  }

  /** 把「返回 false 表示没点到」的原语转成抛错,以便统一进 commitClick 的降级链。 */
  private async expectTrue(result: Promise<boolean>): Promise<void> {
    if (!(await result)) {
      throw new Error("target not present");
    }
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
      await plogPageState("waitResult failed (xiaohongshu):", this.driver);
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
    await commitClick({
      what: "weixin-channels submit",
      attempts: [
        // 可信优先:pointerClickByTextDeep 走真实鼠标事件,能穿 shadow root 找到目标。
        pointerAttempt(`deep text ${this.s.submitText}`, () =>
          this.driver.pointerClickByTextDeep(this.s.submitText, { exact: true }),
        ),
        // 降级:el.click(),不受视口与遮挡影响。
        domAttempt(`text ${this.s.submitText}`, () =>
          this.driver.clickByText(this.s.submitText, { exact: true }),
        ),
      ],
      accepted: pageReacted(this.driver, {
        texts: [...PROCESSING_TEXTS, ...this.s.publishDoneTexts],
        urlPattern: MANAGE_URL_PATTERNS.weixinChannels,
      }),
    });
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
      await plogPageState("waitResult failed (weixin-channels):", this.driver);
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
    // 上一次投稿成功后,B 站**原地**把编辑页替换成成功页(URL 不变,见 waitResult 注释)。而持久
    // 视图复用同一 WebContents,下一次 goto 到「同一个 URL」常被 SPA abort、不刷新,于是残留成功页
    // ——找不到上传入口,这一次发布就失败。没探到文件输入(成功页/异常态)就先去 about:blank 断开
    // SPA,再回到上传页,强制拿一张干净页面。
    if (!(await this.driver.fileInputAttached(this.s.fileInput, 6_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.s.uploadUrl);
    }
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

    // 编辑表单在**选完文件的瞬间**就渲染出来,视频还在后台传——所以「标题框出现」不是上传完成。
    // 旧实现把 `querySelector(titleInput)` 写进 settle 条件,而上面刚等过它可见,于是第一次轮询
    // (0ms)就返回 true:填完表直接点「立即投稿」时视频往往才传了几秒,B 站不受理,表单原地不动,
    // 再白等 waitResult 五分钟报「未确认发布」。大文件必挂、小文件碰巧传完就成功,表现为随机失败。
    //
    // 真信号有两个,任一即可(不互为前提):完成/失败文案,或「进度标记出现过又消失」。只认文案会
    // 在 B 站改文案时全线挂死;只认进度标记会在它压根不渲染百分比时退化回旧 bug。
    const progressExpr = `/上传中|正在上传|\\d+%/.test(document.body?.innerText || '')`; // i18n-ok
    const started = await this.driver.waitForFunction(progressExpr, 15_000, 500);

    // 「进度标记消失」这一条必须**连续数拍都成立**才算数。B 站的进度区文案是跳变的
    // (百分比、速度、剩余时间轮换),单拍不匹配太常见——按单拍判定会在上传刚开始几秒就误判完成,
    // 然后带着没传完的视频去点投稿,而 B 站此时点投稿是**静默无反应**的,查起来极难。
    const STABLE_POLLS = 3;
    const stateExpr = `(() => {
      const text = document.body?.innerText || '';
      if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return 'failed';
      if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return 'done-text';
      return ${started ? `(${progressExpr}) ? 'in-progress' : 'quiet'` : "'no-signal'"};
    })()`;
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    let quietPolls = 0;
    let settleReason = "";
    let settled = false;
    while (Date.now() < deadline) {
      const state = await this.driver.evaluate<string>(stateExpr).catch(() => "unknown");
      if (state === "failed" || state === "done-text") {
        settleReason = state;
        settled = true;
        break;
      }
      quietPolls = state === "quiet" ? quietPolls + 1 : 0;
      if (quietPolls >= STABLE_POLLS) {
        settleReason = `quiet x${quietPolls}`;
        settled = true;
        break;
      }
      await wait(1_000);
    }
    if (!settled) {
      // 带上进度区文案:B 站改版导致信号失配时,一眼能看出该改哪个 pattern。
      const seen = await this.driver
        .evaluate<string>(`(document.body?.innerText || '').slice(0, 400)`)
        .catch(() => "");
      plog("uploadVideo not settled, page text:", JSON.stringify(seen));
      throw new Error("Bilibili upload did not complete in time.");
    }
    plog("uploadVideo settled:", { started, reason: settleReason });
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
    // 点之前先体检一遍必填项。B 站在必填项没齐时点「立即投稿」是**静默无反应**的——没有 toast、
    // 没有报错、表单原地不动,和「按钮点不动」长得一模一样。此前的快照只取到表单下半部分,
    // 恰好漏掉了标题/创作声明/分区/封面这些必填项所在的上半部分。
    plog("bilibili submit: readiness", JSON.stringify(await this.submitReadiness()));
    await commitClick({
      what: "bilibili submit",
      attempts: [
        // 可信优先:真实鼠标事件(isTrusted),B 站风控最紧。
        pointerAttempt(`css ${this.s.submitButton}`, () =>
          this.driver.pointerClickCss(this.s.submitButton),
        ),
        // 降级一:完整指针事件序列。「立即投稿」是个 span,处理器很可能挂在 pointerdown/mousedown
        // 上,只发 click 不动 —— 这一条事件齐全又不依赖命中测试,是目前最可能真正生效的一条。
        domAttempt(`full-click ${this.s.submitButton}`, () =>
          this.driver.dispatchFullClickCss(this.s.submitButton),
        ),
        // 降级二:纯 el.click()。按文案找,兼容 B 站换掉 .submit-add 这个类名的情况。
        ...this.s.submitTexts.map((text) =>
          domAttempt(`text ${text}`, () =>
            this.driver.clickByText(text, {
              exact: true,
              selector: "button, [role=button], a, div, span",
            }),
          ),
        ),
      ],
      accepted: pageReacted(this.driver, {
        gone: this.s.submitButton,
        texts: [...PROCESSING_TEXTS, ...this.s.publishDoneTexts, ...this.s.uploadFailedTexts],
        urlPattern: MANAGE_URL_PATTERNS.bilibili,
      }),
      snapshot: () => this.submitSnapshot(),
    });
  }

  /**
   * 「点到了却没反应」时的页面现场。
   *
   * 已知不是点击侧的问题:落点自检显示元素可见、未禁用、elementFromPoint 命中的正是它自己,
   * 可信指针点击与 el.click() 都送达过。那答案只可能在页面上,而后台视图截不到图,只能取文本:
   *  - 上传是否真的完成(B 站在上传未完成时点投稿是**静默无反应**的,这是首要怀疑);
   *  - 是否有校验提示/错误浮层(我们的受理判定认不出的那种);
   *  - 提交元素自身的状态(它是个 span,禁用态可能只体现在 class/cursor 上)。
   */
  /**
   * 提交前的必填项体检。
   *
   * B 站的必填项在页面上用红色 `*` 标记(标题 / 创作声明 / 分区),封面另算。任何一项没齐,点
   * 「立即投稿」都是静默无反应 —— 所以这里逐项报出**实际值**,而不是再去猜。
   * `starred` 直接从 DOM 里找带 `*` 的标签、连带取它旁边控件的当前值,这样即使 B 站加了新的必填项
   * 也能一起报出来,不必等我们更新选择器。
   */
  private async submitReadiness(): Promise<unknown> {
    return this.driver
      .evaluate(
        `(() => {
          const val = (el) => !el ? null
            : (el.value ?? el.getAttribute('value') ?? (el.innerText || '').trim()).slice(0, 60);
          // 带 * 的必填标签 → 取同一行/父块里第一个 input 或下拉的当前值
          const starred = [...document.querySelectorAll('span,label,div')]
            .filter((el) => el.children.length === 0 && (el.textContent || '').trim() === '*')
            .map((star) => {
              const row = star.closest('div');
              const label = ((row && row.innerText) || '').replace(/\\s+/g, ' ').trim().slice(0, 40);
              const field = row ? row.querySelector('input, textarea, [class*="select"], [class*="dropdown"]') : null;
              return { label: label, value: val(field) };
            })
            .slice(0, 8);
          const cover = document.querySelector('.cover');
          return {
            starred: starred,
            title: val(document.querySelector('input[maxlength="80"], input[maxlength="100"]')),
            statement: val(document.querySelector(${JSON.stringify(this.s.statementInput)})),
            coverSelectedCount: document.querySelectorAll(${JSON.stringify(this.s.coverSelected)}).length,
            coverCandidates: document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)}).length,
            coverText: cover ? (cover.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120) : null,
            // 表单上半部分:此前的 textTail 只取尾部,漏掉了必填项区域
            textHead: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 420),
          };
        })()`,
      )
      .catch((error: unknown) => ({ evaluateFailed: String(error).slice(0, 120) }));
  }

  private async submitSnapshot(): Promise<unknown> {
    return this.driver
      .evaluate(
        `(() => {
          const text = (document.body && document.body.innerText) || '';
          const el = document.querySelector(${JSON.stringify(this.s.submitButton)});
          const cs = el ? getComputedStyle(el) : null;
          const pick = (re) => { const m = text.match(re); return m ? m[0] : null; };
          return {
            uploadDone: /上传完成|上传成功/.test(text),
            uploadProgress: pick(/(上传中|正在上传)[^\\n]{0,24}|\\d+%/),
            hint: pick(/[^\\n]{0,40}(请|不能|不可|失败|错误|未|需要|超过|重复)[^\\n]{0,40}/),
            submitOuter: el ? el.outerHTML.slice(0, 160) : null,
            submitCursor: cs ? cs.cursor : null,
            submitPointerEvents: cs ? cs.pointerEvents : null,
            parentClass: el && el.parentElement ? String(el.parentElement.className).slice(0, 80) : null,
            textTail: text.slice(-260),
          };
        })()`,
      )
      .catch((error: unknown) => ({ evaluateFailed: String(error).slice(0, 120) }));
  }

  async waitResult(): Promise<void> {
    // B 站投稿成功**不跳转 URL**:原地把编辑页替换成成功页(「稿件投递成功 / 查看进度 / 再投一个」)。
    // 旧实现先 waitForUrl(稿件管理页) 干等满 RESULT_TIMEOUT 再看文本——URL 永远不变,于是每次成功都要
    // 白卡约 2 分钟,慢一点还会误报「未确认发布」。改为单循环并发判断:成功页文案(强信号)/ 老流程
    // 跳转(兜底)/ 明确失败提示 任一出现即结束。提交处理可达 ~2 分钟,给足 5 分钟余量。
    //
    // 成功判定必须**同时**满足「出现成功文案」和「编辑表单已消失」。只认文案会误报:实测有一次
    // 自动化的点击根本没落到按钮上(后台视图视口 0×0,见 PageDriver.setMetricsOverride),用户
    // 自己手动点了投稿,页面弹出「投稿成功」——于是这里把**别人完成的发布**记成了自己的成果,
    // 上报 success、发通知、工作流收工。「什么都没发却报成功」是最坏的失败模式,宁可多等到超时。
    // 编辑表单还在就说明没投出去:B 站成功后是原地把编辑页换成成功页,提交按钮不会留着。
    const RESULT_WAIT = 5 * 60 * 1000;
    const probe = `(() => {
      const t = (document.body && document.body.innerText) || '';
      const formGone = !document.querySelector(${JSON.stringify(this.s.submitButton)});
      const success = /稿件投递成功|投稿成功|稿件投稿成功|投稿完成/.test(t) && formGone;
      const redirected = /upload-manager|content-manager|article/.test(location.href);
      const m = t.match(/投稿失败|提交失败|发布失败|标题重复/);
      return { ok: success || redirected, fail: m ? m[0] : null, formGone: formGone, url: location.href };
    })()`;
    const settled = await this.driver.waitForFunction(
      `(() => { const s = ${probe}; return s.ok || s.fail; })()`,
      RESULT_WAIT,
      1_000,
    );
    const state = await this.driver.evaluate<{
      ok: boolean;
      fail: string | null;
      formGone: boolean;
      url: string;
    }>(probe);
    plog("waitResult:", { settled, ...state });
    if (state.ok) return;
    if (state.fail) throw new Error(`B 站投稿被拒:${state.fail}`);
    throw new Error("Bilibili did not confirm publish (no success page or manager redirect).");
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
    // 每条分支都要留痕。此前两处静默 return 没有任何日志,于是「封面到底选上了没」在事后完全不可知
    // ——而封面是 B 站的必填项,没选就点「立即投稿」是**静默无反应**的。
    // 另外 coverSelected 的第一个候选 `.cover .cover-item` 很泛:它若只是容器而非「已选中」标记,
    // alreadySelected 就恒为真、这个方法直接返回,封面永远不会被选(与 uploadDoneTexts 那处短路同类)。
    // 所以这里把两个选择器各自的命中数都记下来,一眼能看出是不是这个情况。
    const counts = await this.driver
      .evaluate<{ selected: number; candidates: number }>(
        `({
          selected: document.querySelectorAll(${JSON.stringify(this.s.coverSelected)}).length,
          candidates: document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)}).length,
        })`,
      )
      .catch(() => ({ selected: -1, candidates: -1 }));
    const alreadySelected = await this.driver.cssVisible(this.s.coverSelected, 2_000);
    plog("selectRecommendedCover:", { ...counts, alreadySelected });
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
      plog("selectRecommendedCover: 没有可点的候选封面,跳过");
      return;
    }

    const selected = await this.driver.cssVisible(this.s.coverSelected, 5_000);
    if (!selected) {
      throw new Error("Bilibili recommended cover did not become selected.");
    }
    // 选中 ≠ 处理完:B 站选完封面还要上传/裁切一下,期间点投稿同样静默无反应。等它安静下来。
    const quiet = await this.driver.waitForFunction(
      `!/上传中|处理中|裁剪中|\\d+%/.test(document.querySelector('.cover')?.innerText || '')`, // i18n-ok
      15_000,
      500,
    );
    plog("selectRecommendedCover: 已选中", { coverQuiet: quiet });
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

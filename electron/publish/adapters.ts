import type { PublishTask } from "./types";
import { resolvePlatform } from "./platforms";
import type { PageDriver } from "./pageDriver";
import { AutomationBlockedError } from "./errors";
import { SELECTORS } from "./selectors";
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
      .then(() => plog("submit: clicked by text (exact)", this.s.submitText))
      .catch(async () => {
        await this.driver.clickByText(this.s.submitText);
        plog("submit: clicked by text (loose)", this.s.submitText);
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

    // 四条降级路径互为兜底。必须记下**走通的是哪一条**:小红书的发布按钮在自定义元素 + shadow DOM
    // 里,改版时往往是前几条陆续失效、最后落到最脆的按文案点击,而表现只是「偶尔发不出去」。
    if (await this.driver.publishXiaohongshuCustomElement(this.s.submitHost)) {
      plog("submit: via publishXiaohongshuCustomElement");
      return;
    }
    if (await this.driver.clickInShadow(this.s.submitHost, this.s.submitText)) {
      plog("submit: via clickInShadow");
      return;
    }
    if (await this.driver.activateCustomElement(this.s.submitHost)) {
      plog("submit: via activateCustomElement");
      return;
    }
    await this.driver.clickByText(this.s.submitText, {
      exact: true,
      selector: "button, [role=button], div, span",
    });
    plog("submit: via clickByText (last resort)");
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
    await this.driver
      .clickByTextDeep(this.s.submitText, { exact: true })
      .then(() => plog("submit: clicked deep", this.s.submitText))
      .catch(async () => {
        await this.driver.clickByText(this.s.submitText, { exact: true });
        plog("submit: clicked flat", this.s.submitText);
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
    const settled = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return true;
        if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return true;
        return ${started ? `!(${progressExpr})` : "false"};
      })()`,
      UPLOAD_TIMEOUT,
      1_000,
    );
    if (!settled) {
      // 带上进度区文案:B 站改版导致信号失配时,一眼能看出该改哪个 pattern。
      const seen = await this.driver
        .evaluate<string>(`(document.body?.innerText || '').slice(0, 400)`)
        .catch(() => "");
      plog("uploadVideo not settled, page text:", JSON.stringify(seen));
      throw new Error("Bilibili upload did not complete in time.");
    }
    plog("uploadVideo settled:", { started });
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
      plog("submit: clicked", this.s.submitButton);
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
        plog("submit: clicked by text", text);
        return;
      }
    }
    throw new Error("Bilibili publish button was not found.");
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

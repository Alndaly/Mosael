import type { PublishTask } from "./types";
import type { SupportedPlatform } from "./platforms";
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

/**
 * 填字段:**优先真实按键**(isTrusted=true),落不稳再退回 DOM 事件那条。
 *
 * 为什么值得:`fillCss` / `fillField` / `insertText` 都是「native value setter + 派发 input/change」
 * 或 `dispatchEvent`,事件 isTrusted=false —— 而标题、简介恰恰是平台最会审查的字段。真实按键走的是
 * 和人手打字同一条输入管线。
 *
 * 为什么必须能降级:真实输入会触发平台自己的输入处理 —— @提及 / #话题 的自动补全弹层、长度截断、
 * 富文本编辑器改写,都可能让最终文本和期望不一致。typeInto 因此自带校验,校验不过就抛;这里接住并
 * 降级。**宁可 isTrusted=false,也不能把文案写坏。**
 */
async function typeOrFill(
  driver: PageDriver,
  what: string,
  selector: string,
  text: string,
  fallback: () => Promise<unknown>,
): Promise<void> {
  try {
    await driver.typeInto(selector, text);
    plog(`${what}: typed (trusted)`);
  } catch (error) {
    plog(`${what}: 真实按键未落稳,降级到 DOM 事件 —`, String(error).replace(/^Error: /, "").slice(0, 130));
    await fallback();
  }
}

/**
 * 按文案点击:**先可信、后降级**。
 *
 * pointerClickByText 发真实鼠标事件(isTrusted=true),但依赖真实布局与命中测试 —— 视图挂成悬浮面板
 * 之后才具备(见 publishWorker 里 panelAttach 早于 openCreatorPage)。挂不上或被遮挡时它会**显式抛错**,
 * 这里接住并退回 el.click():isTrusted 为 false,但点得到。
 */
async function clickTextPreferTrusted(
  driver: PageDriver,
  text: string,
  options?: { exact?: boolean; selector?: string },
): Promise<void> {
  try {
    await driver.pointerClickByText(text, options);
  } catch {
    await driver.clickByText(text, options);
  }
}

/**
 * 「这个账号分区里存着登录态吗」——**页面无关**的那一条判据。
 *
 * 登录轮询在用户此刻停留的页面上反复问 `checkLogin()`,而各平台登录完落在哪一页由它们自己决定:
 * YouTube 走完 Google 登录会把人送到 `www.youtube.com`(看视频那个站),那里既没有文件输入、
 * 也没有任何 Studio 字样 —— 只认创作页长相的判据在这里必然答错,于是**登上了却一直显示未登录**。
 *
 * 只用作正向补充,且必须排在「当前在登录页」之后:会话过期时平台会把人重定向回登录页,那一条
 * 先命中,残留 cookie 不会把已失效的会话说成有效。没配 `session` 的平台原样返回 false。
 */
async function hasStoredSession(driver: PageDriver, platform: SupportedPlatform): Promise<boolean> {
  const { session } = resolvePlatform(platform);
  if (!session) return false;
  // **只在平台自己的站上算数。** cookie 说的是「分区里存着一个会话」,它不解释当前这一页是什么:
  // 用户点「用 Google 继续」时人在 accounts.google.com,而分区里可能还躺着一枚过期的旧 cookie。
  // 那一刻判成已登录不只是显示错 —— 登录成功会自动收起内嵌浏览器,人还在登录,窗口就没了。
  if (!onPlatformSite(driver.url(), session.hosts)) return false;
  const ok = await driver.hasCookie(session.url, session.cookies);
  if (ok) plog(`${platform} checkLogin: 会话 cookie 命中(与当前页面无关)`);
  return ok;
}

/** 当前页面是不是这个平台自己的站(按域名后缀,子域算)。 */
function onPlatformSite(url: string, hosts: readonly string[]): boolean {
  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return false; // about:blank / 空串 —— 谈不上"在平台站上"
  }
  return hosts.some((host) => hostname === host || hostname.endsWith(`.${host}`));
}

const normalizeTag = (tag: string): string => tag.replace(/^#/, "").trim();

const escapeHtml = (value: string): string =>
  value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const stringOption = (task: PublishTask, key: string): string | null => {
  const value = task.platformOptions[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

/**
 * 平台自己的发布选项(可见性、允许评论…),取值范围由后端 PLATFORM_OPTIONS 定义并在建任务时校验,
 * 所以这里拿到的一定是合法值。**兜底值必须取最保守的那档** —— 万一真拿不到(老任务、字段缺失),
 * 宁可发成私享让用户去改,也不能默认公开:误发公开是收不回的。
 */
const enumOption = <T extends string>(task: PublishTask, key: string, fallback: T, allowed: readonly T[]): T => {
  const value = task.platformOptions[key];
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
};

const boolOption = (task: PublishTask, key: string, fallback: boolean): boolean => {
  const value = task.platformOptions[key];
  return typeof value === "boolean" ? value : fallback;
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
      await clickTextPreferTrusted(this.driver, TEXT_PUBLISH_VIDEO, {
        exact: true,
        selector: "button, [role=button], a, div, span",
      }).catch(() => undefined);
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
    const value = title.slice(0, 30);
    await typeOrFill(this.driver, "douyin title", this.s.titleInput, value, () =>
      this.driver.fillCss(this.s.titleInput, value),
    );
  }

  async fillTags(tags: string[]): Promise<void> {
    const description = stringOption(this.task, "description");
    if (description) {
      await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
      await typeOrFill(this.driver, "douyin desc", this.s.descEditor, description, async () => {
        // 降级前必须先清空:typeInto 可能已敲进去一部分,而 insertText 是在光标处插入,
        // 不清就会把残留和完整文案叠在一起。
        await this.driver.focusAndClearField(this.s.descEditor);
        await this.driver.insertText(this.s.descEditor, description);
      });
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

  /**
   * 按发布选项设「谁可以看」,**设不上就不许发**。
   *
   * 抖音默认公开,而我们的兜底是仅自己可见 —— 误发公开收不回。三档各是一个 label 包着
   * input[type=checkbox](不是 radio),所以点完必须回读那个 input 的 checked:点没点到和选没选中
   * 是两件事,而它们的区别就是"本该只给自己看的片子公开了"。
   */
  private async selectVisibility(): Promise<void> {
    const visibility = enumOption(this.task, "visibility", "private", ["private", "friends", "public"] as const);
    const wanted = JSON.stringify(this.s.visibilityTexts[visibility]);
    const find = `[...document.querySelectorAll('label')].find((el) => ${wanted}.includes((el.textContent || '').trim()))`;
    await this.driver
      .evaluate(`(() => {
        const label = ${find};
        if (!label) return false;
        label.scrollIntoView({ block: 'center', inline: 'nearest' });
        const input = label.querySelector('input');
        if (input && !input.checked) input.click();
        else label.click();
        return true;
      })()`)
      .catch(() => false);
    await wait(400);
    const ok = await this.driver
      .evaluate<boolean>(`(() => {
        const label = ${find};
        const input = label && label.querySelector('input');
        return Boolean(input && input.checked);
      })()`)
      .catch(() => false);
    if (!ok) {
      await plogPageState("Douyin visibility not applied:", this.driver);
      throw new Error(`Douyin visibility ${visibility} was not applied; refusing to post.`);
    }
    plog("douyin 可见性:", visibility);
  }

  async submit(): Promise<void> {
    await this.selectVisibility();
    await this.dismissOnboarding();
    await commitClick({
      what: "douyin submit",
      attempts: [
        // 可信优先:真实鼠标事件(isTrusted=true)。视图已挂成悬浮面板,有真实布局与命中测试。
        pointerAttempt(`pointer text ${this.s.submitText}`, () =>
          this.driver.pointerClickByText(this.s.submitText, { exact: true }),
        ),
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

  /**
   * 关掉 shepherd.js 的新手引导浮层 —— **优先可信手段**。
   *
   * 原先直接 removeElements 删节点:那不是"交互",而且比"关掉"更可疑(MutationObserver 看得见,
   * 还会让 shepherd 内部状态以为引导仍在进行)。人会按 Esc 或点关闭按钮,两者都是真实输入。
   * 都不成才退回删节点。
   */
  private async dismissOnboarding(): Promise<void> {
    const gone = async (): Promise<boolean> => !(await this.driver.cssVisible(this.s.overlays, 300));
    if (await gone()) return;

    await this.driver.pressKey("Escape"); // shepherd 默认 exitOnEsc
    if (await gone()) {
      plog("douyin onboarding: dismissed by Escape (trusted)");
      return;
    }
    const clicked = await this.driver
      .pointerClickCss(".shepherd-cancel-icon, .shepherd-element button[aria-label], .shepherd-button")
      .then(() => true)
      .catch(() => false);
    if (clicked && (await gone())) {
      plog("douyin onboarding: dismissed by trusted click");
      return;
    }
    plog("douyin onboarding: 可信手段关不掉,退回删除节点");
    await this.driver.removeElements(this.s.overlays);
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
    await clickTextPreferTrusted(this.driver, this.s.videoTabText, {
      exact: true,
      selector: "button, [role=button], a, div, span",
    }).catch(() => undefined);
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
    await typeOrFill(this.driver, "xiaohongshu title", this.s.titleInput, value, () =>
      this.driver.fillCss(this.s.titleInput, value),
    );
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
      await typeOrFill(this.driver, "xiaohongshu desc", this.s.contentEditor, description, async () => {
        await this.driver.focusAndClearField(this.s.contentEditor);
        await this.driver.insertText(this.s.contentEditor, description);
      });
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
        (await clickTextPreferTrusted(this.driver, TEXT_NEW_TOPIC, {
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

  /**
   * 「原创声明」按发布选项勾/不勾,并**回读校验**。
   *
   * 它是内容属性(这条笔记是不是原创),该由用户定,不是我们替他定 —— 而且勾错了是要担责任的,
   * 所以设不上就抛错,不做"设不上就照发"。
   */
  private async applyOriginal(): Promise<void> {
    const wanted = boolOption(this.task, "original", false);
    const sel = JSON.stringify(this.s.originalSwitch);
    const current = await this.driver
      .evaluate<boolean | null>(`(() => { const i = document.querySelector(${sel}); return i ? i.checked : null; })()`)
      .catch(() => null);
    if (current === null) {
      if (!wanted) return; // 页面上没有这一项,而用户也没要求勾 —— 不必大惊小怪
      await plogPageState("Xiaohongshu original switch missing:", this.driver);
      throw new Error("Xiaohongshu 原创声明 control not found.");
    }
    if (current !== wanted) {
      await this.driver.clickCss(this.s.originalSwitch).catch(() => undefined);
      await wait(400);
    }
    const after = await this.driver
      .evaluate<boolean | null>(`(() => { const i = document.querySelector(${sel}); return i ? i.checked : null; })()`)
      .catch(() => null);
    if (after !== wanted) {
      await plogPageState("Xiaohongshu original not applied:", this.driver);
      throw new Error(`Xiaohongshu 原创声明 stayed ${after}, wanted ${wanted}.`);
    }
    plog("xiaohongshu 原创声明:", wanted);
  }

  /**
   * 按发布选项设可见性,**设不上就不许发**。
   *
   * 这个下拉是小红书自己的 d-select,打开它花了五轮探查才找对路子:合成事件(哪怕完整指针序列
   * 打到 .d-select-main 上)不行,**可信鼠标点击也不行**(点确实落到了,浮层就是不出现),
   * 只有「聚焦 + 回车」能展开 —— 那个 wrapper 带 tabindex="1",它认的是键盘。
   * 展开后三档渲染成 `.group-info .name`:公开可见 / 仅互关好友可见 / 仅自己可见。
   */
  private async applyVisibility(): Promise<void> {
    const visibility = enumOption(this.task, "visibility", "private", ["private", "friends", "public"] as const);
    const wanted = this.s.visibilityTexts[visibility];
    await this.driver
      .evaluate(`(() => {
        const w = document.querySelector(${JSON.stringify(this.s.visibilityTrigger)});
        if (w && typeof w.focus === 'function') w.focus();
        return Boolean(w);
      })()`)
      .catch(() => false);
    await this.driver.pressKey("Enter").catch(() => undefined);
    await wait(700);
    for (const text of wanted) {
      const picked = await clickTextPreferTrusted(this.driver, text, {
        exact: true,
        selector: this.s.visibilityOption,
      })
        .then(() => true)
        .catch(() => false);
      if (picked) break;
    }
    await wait(500);
    const shown = ((await this.driver.cssValue(this.s.visibilityValue)) ?? "").replace(/\s+/g, " ");
    if (!wanted.some((text) => shown.includes(text))) {
      await plogPageState("Xiaohongshu visibility not applied:", this.driver);
      throw new Error(
        `Xiaohongshu visibility is still ${JSON.stringify(shown.slice(0, 40))}, wanted ${visibility}; refusing to post.`,
      );
    }
    plog("xiaohongshu 可见性:", visibility);
  }

  async submit(): Promise<void> {
    await this.applyOriginal();
    await this.applyVisibility();
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
        // 可信优先:pointerClickByTextDeep 发真实鼠标事件,且能穿 open shadow root 找到目标 ——
        // 小红书的发布按钮正是 shadow DOM 里的自定义元素。下面三条派发 DOM 事件(isTrusted=false),
        // 只当兜底。
        pointerAttempt(`deep text ${this.s.submitText}`, () =>
          this.driver.pointerClickByTextDeep(this.s.submitText, { exact: true }),
        ),
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
    await typeOrFill(this.driver, "weixin-channels desc", this.s.descEditor, description, async () => {
      await this.driver.focusAndClearField(this.s.descEditor);
      await this.driver.insertText(this.s.descEditor, description);
    });
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
    await typeOrFill(this.driver, "bilibili title", this.s.titleInput, value, () =>
      this.driver.fillField(this.s.titleInput, value),
    );
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
        await typeOrFill(this.driver, "bilibili desc", this.s.descEditor, description, () =>
          this.driver.fillField(this.s.descEditor, description),
        );
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
      // 受理判定里不放上传失败文案(uploadFailedTexts):那是 uploadVideo 的职责,而其中的「重新上传」
      // 一旦在某个版本变成常驻按钮,这里就会恒为真、验证等于没做 —— 这类「判定恒为真」的短路在本项目
      // 已经出现过两次(uploadDoneTexts 的 querySelector 兜底、coverSelected 的泛选择器),提前拆掉。
      // (注:曾据此推断线上那次「点击后 1ms 就受理」是它造成的,但实测快照显示 B 站页面上并没有
      //  「重新上传」字样,那次 1ms 受理更可能是点击生效后提交按钮短暂消失所致。见下面 RESULT_WAIT。)
      accepted: pageReacted(this.driver, {
        gone: this.s.submitButton,
        texts: [...PROCESSING_TEXTS, ...this.s.publishDoneTexts],
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
    // 15 分钟,不是 5 分钟。B 站确认投稿的延迟**方差极大**,实测同一个视频两次:
    //   ・一次点击后 11 秒就出现成功页(formGone + 成功文案);
    //   ・另一次点击已被受理(提交按钮随即消失),却过了 5 分钟还没翻成功页 —— 旧窗口到点就报
    //     「未确认发布」,而稿件其实**已经投成了**;用户于是重试,重试又再投一稿。
    // 差别应该来自后台的上传→转码(360P/480P/720P/1080P 逐档)→审核要走多久。宁可多等,
    // 也不能把成功报成失败:误报失败的代价是重复投稿,而多等只是多占一会儿账号槽。
    const RESULT_WAIT = 15 * 60 * 1000;
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


/**
 * TikTok。**和抖音是两个平台、两套账号** —— 后端的别名表里曾经把 "tiktok" 指向 douyin,
 * 说"发到 tiktok"会静默发进抖音;接进来时那条已经拆掉。
 *
 * 界面语言跟账号走,所以判定尽量走结构(`data-e2e`)而不是文案;文案作为兜底且中英各一份。
 *
 * **境内需要可用的出站代理** —— 连不上时表现为登录页打不开,而不是"登录失败";这一点写进了
 * 平台说明,免得用户在"为什么一直要我登录"上耗时间。
 */
export class TiktokAdapter implements PublishAdapter {
  private readonly s = SELECTORS.tiktok;

  // 文案走 fillTitle/fillTags 的入参,但**发布选项要从 task 上取**(可见性),所以两个都留。
  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
    // 同 B 站:持久视图复用同一个 WebContents,上一次发完可能停在结果态,goto 同一 URL 常被
    // SPA abort。没探到文件输入就先断开再回来。
    if (!(await this.driver.fileInputAttached(this.s.fileInput, 6_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.s.uploadUrl);
    }
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    // 结构优先:登录页的 data-e2e 标记比句子稳。
    if (await this.driver.cssAttached(this.s.loggedOutMarks, 2_000)) {
      return false;
    }
    // 页面无关的一条:登录成功后 TikTok 常把人留在 www.tiktok.com 的信息流,不是 Studio。
    if (await hasStoredSession(this.driver, "tiktok")) {
      return true;
    }
    if (await this.driver.fileInputAttached(this.s.fileInput, 8_000)) {
      return true;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return false;
      }
    }
    return false;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    if (!(await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT))) {
      throw new Error("TikTok upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    // 文案编辑器出现 = 表单渲染了,**不等于视频传完**(同 B 站那一课)。真正的完成信号是
    // 「发布按钮可用」:TikTok 在转码完成前一直禁用它。
    if (!(await this.driver.cssVisible(this.s.captionEditor, UPLOAD_TIMEOUT))) {
      throw new Error("TikTok editor did not appear after upload (caption box missing).");
    }
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    while (Date.now() < deadline) {
      const failed = await this.driver
        .evaluate<boolean>(`new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`)
        .catch(() => false);
      if (failed) {
        await plogPageState("TikTok upload failed:", this.driver);
        throw new Error("TikTok reported an upload failure.");
      }
      if (await this.driver.waitCssEnabled(this.s.postButton, 2_000).catch(() => false)) {
        return;
      }
      await wait(1_000);
    }
    await plogPageState("TikTok upload did not settle:", this.driver);
    throw new Error("TikTok upload did not finish in time (post button stayed disabled).");
  }

  async fillTitle(title: string): Promise<void> {
    // TikTok 没有独立标题栏,这一栏是**文案**;标签在 fillTags 里接到同一段文字后面。
    // 和 YouTube 一样:TikTok 用**文件名**预填文案,清不干净就会发出一条叫 3cce8622… 的片子,
    // 而且是静默的。填完回读校验一次。
    await this.driver.focusAndClearField(this.s.captionEditor);
    await this.driver.insertText(this.s.captionEditor, title);
    await wait(500);
    const actual = ((await this.driver.cssValue(this.s.captionEditor)) ?? "").trim();
    if (!actual.includes(title.trim())) {
      await plogPageState("TikTok caption mismatch:", this.driver);
      throw new Error(
        `TikTok caption did not accept the text (expected ${JSON.stringify(title.slice(0, 40))}, got ${JSON.stringify(actual.slice(0, 80))}).`,
      );
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    if (tags.length === 0) {
      return;
    }
    // 话题写进文案末尾:TikTok 的标签本来就是文案里的 #hashtag,没有独立标签框。
    // 逐个敲进去而不是一次性插入 —— 站内的话题联想面板会在输入时弹出,一次性插入常常
    // 让最后一个话题停在"未确认"状态。
    await this.driver.focusEnd(this.s.captionEditor);
    for (const tag of tags) {
      const clean = tag.replace(/^#/, "").trim();
      if (!clean) continue;
      await this.driver.insertText(this.s.captionEditor, ` #${clean}`);
      await wait(600);
      // 关掉联想面板,免得它把下一次输入吃掉。
      await this.driver.pressKey("Escape").catch(() => undefined);
      await wait(200);
    }
  }

  /**
   * 按发布选项设可见性,**设不上就不许发**。
   *
   * TikTok 默认 Everyone,而我们的兜底是「仅自己可见」—— 自动发布一旦误发公开是收不回的(别人
   * 已经看到、可以转存)。所以这里的失败必须是硬失败,绝不能"设不上就照发":用户要的是私享而
   * 页面还停在 Everyone,照发就等于把它公开了。
   */
  private async selectVisibility(): Promise<void> {
    // 上传页会弹「是否开启自动内容检查」之类的模态,挡住真实点击。先关掉(点取消,不替用户改设置)。
    for (const text of this.s.dismissTexts) {
      await clickTextPreferTrusted(this.driver, text, { exact: true }).catch(() => undefined);
    }
    if (!(await this.driver.cssVisible(this.s.visibilityTrigger, ACTION_TIMEOUT))) {
      await plogPageState("TikTok visibility control missing:", this.driver);
      throw new Error("TikTok visibility control not found; refusing to post publicly.");
    }
    // 打开下拉:先真实鼠标事件,再完整指针序列,最后 el.click()。
    //
    // 三条都要:这个 Select 的触发器只认 pointerdown/mousedown 一类事件,单发 el.click() 打不开
    // (实测第一次跑就是这样:下拉根本没开,于是可见性停在 Everyone,被回读校验挡下)。而可信
    // 指针点击又会被**话题联想面板**遮住(实测 hit:false,命中的是那个浮层里的 #OpenStudio),
    // 所以它也不能是唯一手段。
    await this.driver.pointerClickCss(this.s.visibilityTrigger).catch(async () => {
      await this.driver.dispatchFullClickCss(this.s.visibilityTrigger).catch(async () => {
        await this.driver.clickCss(this.s.visibilityTrigger).catch(() => undefined);
      });
    });
    await wait(900);
    const visibility = enumOption(this.task, "visibility", "private", ["private", "friends", "public"] as const);
    const wanted = this.s.visibilityTexts[visibility];
    for (const text of wanted) {
      const picked = await clickTextPreferTrusted(this.driver, text, {
        exact: true,
        selector: this.s.visibilityOption,
      })
        .then(() => true)
        .catch(() => false);
      if (picked) break;
    }
    await wait(600);
    // 回读校验:控件上显示的必须已经是「仅自己可见」。这一步不能省 —— 点没点中和设没设上是两件事,
    // 而它们的区别就是"公开发了一条"。
    const shown = ((await this.driver.cssValue(this.s.visibilityValue)) ?? "").replace(/\s+/g, " ");
    if (!wanted.some((text) => shown.includes(text))) {
      await plogPageState("TikTok visibility not applied:", this.driver);
      throw new Error(
        `TikTok visibility is still ${JSON.stringify(shown.slice(0, 60))}, wanted ${visibility}; refusing to post.`,
      );
    }
    plog("tiktok 可见性:", visibility);
  }

  async submit(): Promise<void> {
    await this.selectVisibility();
    if (!(await this.driver.waitCssEnabled(this.s.postButton, ACTION_TIMEOUT).catch(() => false))) {
      // 结构选择器失配时退回文案(界面语言跟账号走,中英各试一遍)。
      for (const text of this.s.postTexts) {
        try {
          await clickTextPreferTrusted(this.driver, text);
          return;
        } catch {
          // 换下一种说法
        }
      }
      await plogPageState("TikTok submit button unavailable:", this.driver);
      throw new Error("TikTok post button never became clickable.");
    }
    await this.driver.clickCss(this.s.postButton);
  }

  async waitResult(): Promise<void> {
    // 判据:完成文案,或跳到了内容管理页。**外加「发布按钮已经不在了」** —— 光看文案会被页面上
    // 早就存在的词命中(原先的 "posted" 是列表列名、"Manage your posts" 是导航项,两者在点发布
    // 之前就在,判定恒真)。另外原来还挂着一段 `(函数源码 && false) ||` 的死表达式,一并删掉。
    const donePattern = this.s.publishDoneTexts.join("|");
    const probe = `(() => {
      const text = document.body?.innerText || '';
      const formGone = !document.querySelector(${JSON.stringify(this.s.postButton)});
      const hasDoneText = new RegExp(${JSON.stringify(donePattern)}).test(text);
      const listed = /tiktokstudio\\/content/.test(location.href);
      return { ok: listed || (hasDoneText && formGone), hasDoneText: hasDoneText, formGone: formGone, listed: listed, url: location.href };
    })()`;
    const settled = await this.driver.waitForFunction(`(${probe}).ok`, RESULT_TIMEOUT, 1_000);
    const state = await this.driver.evaluate<Record<string, unknown>>(probe).catch(() => null);
    plog("tiktok waitResult:", { settled, ...(state ?? {}) });
    if (!settled) {
      await plogPageState("waitResult failed (tiktok):", this.driver);
      throw new Error("TikTok did not confirm the post (no success text or redirect to content list).");
    }
  }
}

/**
 * YouTube Studio。
 *
 * **可见性一律先发 Private**:自动上传误发公开是收不回来的,而"发完自己去改公开"代价小得多。
 * 这条也写进了后端的平台说明,用户在新建发布时看得到。
 *
 * 标签走**描述里的 #hashtag** 而不是「更多选项」里的关键词框:后者要多展开一层折叠面板,
 * 是这条链路上最容易因改版而断的一环;而 hashtag 在 YouTube 上本来就是创作者实际在用的形式。
 *
 * **境内需要可用的出站代理**;另外 Google 会拒绝在部分内嵌浏览器里登录 —— 应用已经把 UA 里的
 * `Electron/x.y.z` 抹掉(见 accountViews.platformUserAgent),但这一关只有真登录一次才知道。
 */
export class YoutubeAdapter implements PublishAdapter {
  private readonly s = SELECTORS.youtube;
  /** 本次上传拿到的视频 ID(详情页会显示 youtu.be 链接)。收尾判定靠它认「**这一支**发出去了」。 */
  private uploadedId: string | null = null;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
    if (!(await this.driver.fileInputAttached(this.s.fileInput, 8_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.s.uploadUrl);
    }
  }

  async checkLogin(): Promise<boolean> {
    // 未登录时 Google 直接把你送去登录页 —— 比找文案可靠。会话过期同样走这条,所以它必须排在
    // cookie 判据前面:否则残留 cookie 会把已失效的会话说成有效。
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    // 页面无关的一条,必须排在页面判据之前:登录流程结束后人停在 www.youtube.com,那里没有任何
    // Studio 标志,下面两条一个也命中不了,而 8 秒的文件输入等待还会让每轮轮询白等 8 秒。
    if (await hasStoredSession(this.driver, "youtube")) {
      return true;
    }
    if (await this.driver.fileInputAttached(this.s.fileInput, 8_000)) {
      return true;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    return false;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    if (!(await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT))) {
      throw new Error("YouTube upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    // 标题框出现 = 详情表单渲染了,视频仍在后台上传/处理。YouTube 会一直在页面上写
    // 「Uploading x%」/「Processing」,完成后变成「Upload complete」「Checks complete」之类。
    if (!(await this.driver.cssVisible(this.s.titleBox, UPLOAD_TIMEOUT))) {
      throw new Error("YouTube details form did not appear after upload (title box missing).");
    }
    // **不能拿「下一步可点」当上传完成。** YouTube 用文件名预填标题,详情页一开始就是合法的,
    // 于是「下一步」几乎立刻可点,而视频还在传。那样走完流程去点「完成」,YouTube 给的是
    // "传完后自动发布"的提示,而不是发布成功的文案 —— waitResult 认不出来,一次成功的发布被
    // 报成失败,用户重发就成了重复投稿。B 站那边踩过同一个坑(见 BilibiliAdapter.uploadVideo)。
    //
    // 真信号两个,任一即可:完成文案,或「进度痕迹出现过又连续几拍消失」。只认文案会在 YouTube
    // 改文案时全线挂死;只认进度会在它不渲染百分比时退化回旧行为。
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const donePattern = this.s.uploadDoneTexts.join("|");
    const progressExpr = `new RegExp(${JSON.stringify(this.s.uploadProgressPattern)}).test(document.body?.innerText || '')`;

    // 判据只有两条:完成文案,或**进度痕迹连续数拍都不在**。
    //
    // 这里曾经还有第三个状态:先花 20 秒等进度痕迹出现,没等到就把状态记成 no-signal。那是从
    // B 站那段照搬来的,而它在这里是个**死状态** —— 8MB 的片子两秒就传完,等我们去看时进度文字
    // 早没了,于是 no-signal 恒成立、quietPolls 永远不累加,循环唯一的出口只剩超时:实测就是
    // 卡满 10 分钟然后报「上传超时」,而视频其实早已传好并存成了私享草稿。
    //
    // 「见过进度」本来就不该是前提:没见过恰恰说明它在我们看之前就传完了。连续数拍安静已经足够,
    // 而"连续"这一条不能省 —— 进度区文案是跳变的(百分比、剩余时间轮换),按单拍判会在刚开始
    // 几秒就误判完成。
    const STABLE_POLLS = 4;
    const stateExpr = `(() => {
      const text = document.body?.innerText || '';
      if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return 'failed';
      if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return 'done-text';
      return (${progressExpr}) ? 'in-progress' : 'quiet';
    })()`;
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    let quietPolls = 0;
    let settleReason = "";
    while (Date.now() < deadline) {
      const state = await this.driver.evaluate<string>(stateExpr).catch(() => "unknown");
      if (state === "failed") {
        await plogPageState("YouTube upload failed:", this.driver);
        throw new Error("YouTube reported an upload failure.");
      }
      if (state === "done-text") {
        settleReason = state;
        break;
      }
      quietPolls = state === "quiet" ? quietPolls + 1 : 0;
      if (quietPolls >= STABLE_POLLS) {
        settleReason = `quiet x${quietPolls}`;
        break;
      }
      await wait(1_000);
    }
    if (!settleReason) {
      await plogPageState("YouTube upload did not settle:", this.driver);
      throw new Error("YouTube upload did not finish in time.");
    }
    plog("youtube uploadVideo settled:", { reason: settleReason });
    // 详情页会给出这条稿件的 youtu.be 链接 —— 抓下来,收尾判定要靠它区分「我这支发出去了」和
    // 「列表里本来就有一支同名的」。抓不到不算错,收尾会退回文案判据。
    this.uploadedId = await this.driver
      .evaluate<string | null>(`(() => {
        const a = document.querySelector('a[href*="youtu.be/"]');
        const m = a && a.getAttribute('href') ? a.getAttribute('href').match(/youtu\\.be\\/([\\w-]{6,})/) : null;
        return m ? m[1] : null;
      })()`)
      .catch(() => null);
    plog("youtube uploadVideo id:", this.uploadedId);
  }

  async fillTitle(title: string): Promise<void> {
    // YouTube **用文件名预填标题**。清不干净的后果是发出一个叫 `3cce86226e01…` 的视频,而且是
    // 静默的:表单合法、流程照走完。所以填完必须回读校验,宁可当场失败(草稿是私享的,重来即可)。
    const value = title.slice(0, resolvePlatform("youtube").titleMaxLength ?? 100);
    await this.driver.focusAndClearField(this.s.titleBox);
    await this.driver.insertText(this.s.titleBox, value);
    await wait(400);
    const actual = ((await this.driver.cssValue(this.s.titleBox)) ?? "").trim();
    if (actual !== value) {
      await plogPageState("YouTube title mismatch:", this.driver);
      throw new Error(
        `YouTube title box did not accept the title (expected ${JSON.stringify(value)}, got ${JSON.stringify(actual.slice(0, 80))}).`,
      );
    }
    const description = stringOption(this.task, "description");
    if (description && (await this.driver.cssVisible(this.s.descBox, 5_000))) {
      await this.driver.focusAndClearField(this.s.descBox);
      await this.driver.insertText(this.s.descBox, description);
      await wait(300);
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    if (tags.length === 0) {
      return;
    }
    if (!(await this.driver.cssVisible(this.s.descBox, 5_000))) {
      return;
    }
    const hashtags = tags
      .map((tag) => `#${tag.replace(/^#/, "").replace(/\s+/g, "")}`)
      .filter((tag) => tag.length > 1)
      .join(" ");
    await this.driver.focusEnd(this.s.descBox);
    await this.driver.insertText(this.s.descBox, `\n\n${hashtags}`);
    await wait(300);
  }

  async submit(): Promise<void> {
    // 「面向儿童」是必答项,不选就走不到下一步。默认「否」,但由发布选项决定 —— 选「是」会关掉
    // 评论等一批功能,那是内容属性,该由用户按素材实际情况定,不是我们替他定。
    const forKids = boolOption(this.task, "made_for_kids", false);
    const kidsRadio = forKids ? this.s.madeForKids : this.s.notMadeForKids;
    if (await this.driver.cssVisible(kidsRadio, 5_000)) {
      await this.driver.clickCss(kidsRadio).catch(() => undefined);
      await wait(300);
    }
    // 详情 → 视频元素 → 检查 → 可见性,共三次「下一步」。
    for (let step = 0; step < 3; step += 1) {
      if (!(await this.driver.waitCssEnabled(this.s.nextButton, ACTION_TIMEOUT).catch(() => false))) {
        break;
      }
      await this.driver.clickCss(this.s.nextButton);
      await wait(800);
    }
    // 可见性按发布选项来;**兜底是私享**(见 enumOption 的说明:拿不到就选最保守的那档)。
    const visibility = enumOption(this.task, "visibility", "private", ["private", "unlisted", "public"] as const);
    const radio = this.s.visibilityRadio[visibility];
    if (!(await this.driver.cssVisible(radio, ACTION_TIMEOUT))) {
      await plogPageState("YouTube visibility step not reached:", this.driver);
      throw new Error(`YouTube visibility step was not reached (${visibility} option missing).`);
    }
    await this.driver.clickCss(radio);
    await wait(400);
    // 回读校验:选中的必须就是要的那一档。**选没选中和点没点到是两件事**,而它们的区别可能是
    // "本该私享的片子公开了"。
    const chosen = await this.driver
      .evaluate<boolean>(`Boolean(document.querySelector(${JSON.stringify(radio)})?.getAttribute('aria-checked') === 'true')`)
      .catch(() => false);
    if (!chosen) {
      await plogPageState("YouTube visibility not applied:", this.driver);
      throw new Error(`YouTube visibility ${visibility} was not applied.`);
    }
    plog("youtube 可见性:", visibility, "面向儿童:", forKids);
    if (!(await this.driver.waitCssEnabled(this.s.doneButton, ACTION_TIMEOUT).catch(() => false))) {
      await plogPageState("YouTube done button unavailable:", this.driver);
      throw new Error("YouTube done button never became clickable.");
    }
    await this.driver.clickCss(this.s.doneButton);
  }

  async waitResult(): Promise<void> {
    // 「发出去了」= 上传对话框已关闭 **且** 这一支稿件出现在频道内容里。
    //
    // 这一条判据换过三次,前两次都是「恒真」:
    //  ・URL 判据原先写成 `/videos/`,而上传页本身就是 `.../videos/upload` —— 点提交之前就为真,
    //    实测提交后 3 毫秒即"确认成功",而那时什么都还没发生;
    //  ・改成 `(?!\/upload)` 之后又永远不成立:YouTube 关掉对话框**并不换路由**,还留在 /upload;
    //  ・文案判据里曾有「已上传」,那两个字在列表页上到处都是。
    //
    // 所以认**视频 ID**:它来自本次上传的详情页,列表里那一行的链接带着它。同名的旧稿件不会
    // 让它误判 —— 而"什么都没发却报成功"是这里最坏的失败模式,值得多这一道。
    const donePattern = this.s.publishDoneTexts.join("|");
    const idSelector = this.uploadedId ? `a[href*="${this.uploadedId}"]` : null;
    const probe = `(() => {
      const text = document.body?.innerText || '';
      const dialogGone = !document.querySelector(${JSON.stringify(this.s.doneButton)});
      const hasDoneText = new RegExp(${JSON.stringify(donePattern)}).test(text);
      const listed = ${idSelector ? `Boolean(document.querySelector(${JSON.stringify(idSelector)}))` : "false"};
      return { ok: dialogGone && (listed || hasDoneText), listed: listed, hasDoneText: hasDoneText, dialogGone: dialogGone };
    })()`;
    const settled = await this.driver.waitForFunction(`(${probe}).ok`, RESULT_TIMEOUT, 1_000);
    const state = await this.driver
      .evaluate<Record<string, unknown>>(probe)
      .catch(() => null);
    plog("youtube waitResult:", { settled, id: this.uploadedId, ...(state ?? {}) });
    if (!settled) {
      await plogPageState("waitResult failed (youtube):", this.driver);
      throw new Error("YouTube did not confirm the upload (video not listed and no success text).");
    }
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
  if (normalizedPlatform === "tiktok") {
    return new TiktokAdapter(driver, task);
  }
  if (normalizedPlatform === "youtube") {
    return new YoutubeAdapter(driver, task);
  }
  return new MockAdapter(driver, task);
};

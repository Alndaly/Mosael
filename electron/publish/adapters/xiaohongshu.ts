import type { ContentKind, PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, TEXT_NEW_TOPIC, UPLOAD_TIMEOUT, boolOption, clickTextPreferTrusted, enumOption, normalizeTag, plogPageState, publishError, stringOption, typeOrFill, wait } from "./shared";
import { t } from "../../i18n.cjs";
import { platformName } from "../platforms";
import { SELECTORS } from "../selectors";
import { AutomationBlockedError } from "../errors";
import { CommitClickError, PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";

/**
 * **每种内容形状怎么进到它的创作页** —— 一张「步骤计划」表,不写条件分支。
 *
 * 小红书的几种发布方式**不是同一个页面**:视频 / 图文是「发布笔记」页上的两个 tab,而
 * 「写长文」是另一套(先切 tab,再点「新的创作」,进到标题 + 正文 + 一键排版的编辑器,没有文件上传)。
 * 所以表里存的不是「一个 tab 文案」,而是**依次要点的那几步**,以及进到之后怎么确认。
 *
 * 加一种形状时只在这里加一行:步骤多一步就多写一个文案,别的代码不动。表里没有的形状就是还没接,
 * 与 `supports` 一致地报出来。
 */
interface EntryPlan {
  /** 依次要点的入口文案:第一步是顶部 tab,后面是这一档页面上的按钮。 */
  steps: readonly string[];
  /** 进到之后应该**被选中**的那个 tab 文案(多步的形状取最后进到的那一页的代表文案;空串 = 不看)。 */
  activeTab: string;
  /**
   * 进到之后文件 input 的 `accept` 里该出现的**扩展名**(真机读到的是一串扩展名,不是 `image/*`)。
   * 空数组 = 这一档没有文件上传(长文是写字)。
   */
  acceptExtensions: readonly string[];
  /**
   * 进到之后地址栏里该出现的片段。切 tab 时这一页会**换路由**(真机:`?from=tab_switch&target=image`),
   * 所以地址是最直接的证据;空串 = 这一档不改地址(长文是同一路由下换内容)。
   */
  urlContains: string;
  /** 进到之后这一页该出现的文案(改版会换,只当兜底)。 */
  hint: string;
}

const XIAOHONGSHU_ENTRY: Partial<Record<ContentKind, EntryPlan>> = {
  //: 页面上的中文只说一遍:全部取自 `selectors`(它是**匹配平台真实页面**的词表,专门豁免翻译)。
  //: 适配器里再写一遍,就会多出一份「界面文字」——`uiTextIsTranslated` 那道棘轮正是这么红的。
  video: {
    steps: [SELECTORS.xiaohongshu.videoTabText],
    activeTab: SELECTORS.xiaohongshu.videoTabText,
    acceptExtensions: [".mp4", ".mov"],
    urlContains: "",
    hint: SELECTORS.xiaohongshu.dropHintByKind.video,
  },
  "image-text": {
    steps: [SELECTORS.xiaohongshu.imageTextTabText],
    activeTab: SELECTORS.xiaohongshu.imageTextTabText,
    acceptExtensions: [".jpg", ".jpeg", ".png", ".webp"],
    urlContains: "target=image",
    hint: SELECTORS.xiaohongshu.dropHintByKind["image-text"],
  },
  //: 「写长文」还没接(要再点一次「新的创作」,而且编辑器没有文件上传)。接的时候照这个写:
  //: article: { steps: [写长文 tab, 新的创作], activeTab: 写长文 tab, acceptExtensions: [], urlContains: "target=article", hint: ... },
};

export class XiaohongshuAdapter implements PublishAdapter {
  //: 已经接的两档:视频、图文。**「写长文」是另一套页面**(见 `XIAOHONGSHU_ENTRY`),还没接。
  readonly supports = ["video", "image-text"] as const;
  private readonly s = SELECTORS.xiaohongshu;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    const plan = XIAOHONGSHU_ENTRY[this.task.contentKind];
    if (!plan) {
      //: 表里没有 = 这一种形状我们还没接(`supports` 也已经声明过,走到这里是代码不一致)。
      throw publishError("xiaohongshu", "publishErr_kindNotImplemented", { kind: this.task.contentKind });
    }
    //: **先走这一档的直连地址**(借鉴 social-auto-upload):`?target=image` / `?target=video` 是这一页
    //: 自己的参数,比「进去再点 tab」确定得多 —— 点不中、点到离屏克隆、SPA 还没渲染都能躲开。
    const entryUrl = this.s.entryUrlByKind[this.task.contentKind];
    if (entryUrl) {
      await this.driver.goto(entryUrl);
      await this.driver.cssAttached(this.s.fileInput, UPLOAD_TIMEOUT).catch(() => undefined);
      if (await this.onPlannedPage(plan)) return;
    }
    //: 地址这条路没成(平台改了参数),退回「点 tab」:逐步点,每步最多两次(精确 / 包含)。
    if (!entryUrl) await this.driver.goto(this.s.publishUrl);
    await this.driver.cssAttached(this.s.fileInput, UPLOAD_TIMEOUT).catch(() => undefined);
    for (const stepText of plan.steps) {
      for (const exact of [true, false]) {
        await clickTextPreferTrusted(this.driver, stepText, {
          exact,
          selector: "button, [role=button], a, div, span, li",
        }).catch(() => undefined);
        if (await this.waitForPlannedPage(plan)) return;
      }
    }
    throw publishError("xiaohongshu", "publishErr_tabMissing", { tab: plan.steps[0] });
  }

  /**
   * 现在这一页是不是**这一种形状的目标页**?两条判据任一成立即可:
   *
   * - **当前选中的 tab** 是这一档(`.creator-tab.active` 的文字)—— 最可靠;
   * - 或者这一档页面上该出现的文案出现了(改版会换文案,所以只当兜底)。
   *
   * **不能用「文件 input 在不在」**:视频页也有 input,那会让图文任务停在视频页上交图片。
   */
  private plannedPageExpression(plan: EntryPlan): string {
    const activeTab = JSON.stringify(plan.activeTab);
    const hint = JSON.stringify(plan.hint);
    const extensions = JSON.stringify(plan.acceptExtensions);
    const urlContains = JSON.stringify(plan.urlContains);
    const activeSelector = JSON.stringify(this.s.activeTab);
    return `(() => {
      //: 1) 选中的 tab 是这一档 —— 最直接。
      const wanted = ${activeTab};
      const active = document.querySelector(${activeSelector});
      if (wanted && (active?.textContent || '').trim() === wanted) return true;
      //: 2) 地址换成这一档的路由(切 tab 是换路由,真机是 ?from=tab_switch&target=image)。
      const wantedUrl = ${urlContains};
      if (wantedUrl && location.href.includes(wantedUrl)) return true;
      //: 3) 文件 input 的 accept 里有这一档的扩展名(真机读到的是一串扩展名,不是 MIME)。
      const wantedExtensions = ${extensions};
      const accepts = [...document.querySelectorAll('input[type="file"]')]
        .map((one) => (one.getAttribute('accept') || '').toLowerCase())
        .join(',');
      if (wantedExtensions.some((one) => accepts.includes(one))) return true;
      //: 4) 这一页该出现的文案(改版会换,只当兜底)。
      const text = document.body?.innerText || '';
      return Boolean(${hint}) && text.includes(${hint});
    })()`;
  }

  private async onPlannedPage(plan: EntryPlan): Promise<boolean> {
    try {
      return Boolean(await this.driver.evaluate<boolean>(this.plannedPageExpression(plan)));
    } catch {
      return false;
    }
  }

  private async waitForPlannedPage(plan: EntryPlan): Promise<boolean> {
    return this.driver.waitForFunction(this.plannedPageExpression(plan), 5_000, 300);
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
      throw publishError("xiaohongshu", "publishErr_editorMissing");
    }
    const publishReady =
      (await this.driver.waitCssEnabled(this.s.submitButton, UPLOAD_TIMEOUT)) ||
      (await this.driver.waitTextEnabledDeep(this.s.submitText, 1_000, {
        hostSelector: this.s.submitHost,
      }));
    if (!publishReady) {
      throw publishError("xiaohongshu", "publishErr_uploadTimeout");
    }
  }

  /** 图文:一次交多份图片(**顺序就是数组顺序**),等编辑器与「发布」都就绪。 */
  async uploadImages(paths: string[]): Promise<void> {
    if (paths.length === 0) throw publishError("xiaohongshu", "publishErr_noAssets");
    //: 用 accept 定位**图文档**那个 input:视频档的框只收视频扩展名,把图片塞进去会被页面拒
    //: (真机那句「请先切换到图片tab」就是这么来的)。找不到再退回泛匹配。
    const input =
      (await this.driver.cssAttached(this.s.imageFileInput, ACTION_TIMEOUT)) ? this.s.imageFileInput : this.s.fileInput;
    await this.driver.fileInputAttached(input, ACTION_TIMEOUT);
    await this.driver.setFiles(input, paths);
    const ready = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!ready) {
      throw publishError("xiaohongshu", "publishErr_editorMissing");
    }
    const publishReady =
      (await this.driver.waitCssEnabled(this.s.submitButton, UPLOAD_TIMEOUT)) ||
      (await this.driver.waitTextEnabledDeep(this.s.submitText, 1_000, {
        hostSelector: this.s.submitHost,
      }));
    if (!publishReady) {
      throw publishError("xiaohongshu", "publishErr_uploadTimeout");
    }
    //: **核对张数**。平台对不合规的图会弹一句「部分文件处理失败,未上传」然后照样进编辑器 ——
    //: 不核对就会以为传完了,发出去的笔记少一张(真机 2026-10-23)。
    const shown = await this.driver
      .evaluate<number | null>(`(() => {
        const match = (document.body?.innerText || '').match(/\b(\d+)\s*\/\s*18\b/);
        return match ? Number(match[1]) : null;
      })()`)
      .catch(() => null);
    if (typeof shown === "number" && shown < paths.length) {
      throw publishError("xiaohongshu", "publishErr_imagesRejected", { expected: paths.length, shown });
    }
    //: 上传成功会弹「图片可以编辑啦」——它盖在中间,后面填字/点发布都会被它挡一下。
    await this.dismissHints();
  }

  /** 正文:图文用编辑器,和话题填的是同一个 contenteditable。 */
  async fillBody(body: string): Promise<void> {
    const value = body.trim();
    if (!value) return;
    await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
    //: 只在**编辑器还是空的**时候补打一遍(第一遍的点击可能被「图片可以编辑啦」那类浮层吃掉)。
    //: 已经打进去过就不重打 —— 再打一遍就是同一段文字出现两次(真机 2026-10-23)。
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      if (attempt > 1) {
        const typed = await this.editorText();
        if (typed) break;
        await this.dismissHints();
      }
      await typeOrFill(
        this.driver,
        "xiaohongshu body",
        this.s.contentEditor,
        value,
        async () => {
          await this.driver.focusAndClearField(this.s.contentEditor);
          await this.driver.insertText(this.s.contentEditor, value);
        },
        //: **逐行打**(每行一个真实回车)。整段塞含 `\n` 的字符串时,换行会先当普通文字、
        //: 事后才一次性成段 —— 人看到的就是「先出现一整段、然后一瞬间全部换行」(维护者 2026-10-23)。
        //: 先聚焦并清空,再逐行打;清空走真实按键(见 clearFocusedField 的说明)。
        async () => {
          //: 点一下编辑器拿到焦点(可信点击优先),清空,再逐行打。
          await this.driver.pointerClickCss(this.s.contentEditor).catch(() => undefined);
          await this.driver.focusAndClearField(this.s.contentEditor);
          await this.driver.typeLines(value);
        },
      );
      if ((await this.bodyMatch(value)).ok) return;
    }
    //: 还是没对上:**按行**报出到底进去了几行。整段一致才算填好 —— 只进了一部分就发出去,
    //: 用户看到的正文和他在表单里写的不一样,那比失败更糟(所以这里不"有字就放过")。
    const { matched, total } = await this.bodyMatch(value);
    if (matched === 0) throw publishError("xiaohongshu", "publishErr_descriptionRejected");
    throw publishError("xiaohongshu", "publishErr_bodyPartial", { matched, total });
  }

  /** 编辑器里眼下有什么字(取候选里最长的那一个;空占位 `<p>` 会先被 querySelector 命中)。 */
  private async editorText(): Promise<string> {
    return this.driver
      .evaluate<string>(`(() => {
        const editors = [...document.querySelectorAll(${JSON.stringify(this.s.contentEditor)})];
        return (editors
          .map((one) => (one.innerText || one.textContent || ''))
          .sort((a, b) => b.length - a.length)[0] || '').trim();
      })()`)
      .catch(() => "");
  }

  /**
   * 正文**按行**核对:每一行(非空、去空白后)都要在编辑器里出现。
   *
   * 为什么不整段比:小红书的正文是富文本,`1. …` 会被它变成有序列表、换行位置也会变 —— 整段
   * `includes` 会误判(真机 2026-10-23 连误三次,把本来能发的笔记全拦了)。
   * 为什么也不"有字就算":只进去一半同样要拦 —— 发出去的正文和用户写的不一样,比失败更糟。
   *
   * 取**文字最多的那个候选元素**来比:真机上 `querySelector` 先命中的可能是空的占位 `<p>`。
   */
  private async bodyMatch(value: string): Promise<{ ok: boolean; matched: number; total: number }> {
    const lines = value
      .split(/\r?\n/)
      .map((one) => one.trim())
      .filter(Boolean);
    return this.driver
      .evaluate<{ ok: boolean; matched: number; total: number }>(`(() => {
        const squash = (text) => String(text || '').replace(/\s+/g, '');
        const editors = [...document.querySelectorAll(${JSON.stringify(this.s.contentEditor)})];
        const longest = editors
          .map((one) => (one.innerText || one.textContent || ''))
          .sort((a, b) => b.length - a.length)[0] || '';
        const shown = squash(longest);
        const lines = ${JSON.stringify(lines)}.map(squash).filter(Boolean);
        const matched = lines.filter((one) => shown.includes(one)).length;
        return { ok: lines.length > 0 && matched === lines.length, matched, total: lines.length };
      })()`)
      .catch(() => ({ ok: false, matched: 0, total: lines.length }));
  }

  private acceptsTextExpression(selector: string, value: string): string {
    return `(() => {
      const squash = (text) => String(text || '').replace(/\s+/g, '');
      const shown = squash(document.querySelector(${JSON.stringify(selector)})?.innerText);
      return shown.includes(squash(${JSON.stringify(value)}));
    })()`;
  }

  /** 上传后那种「图片可以编辑啦」的提示框会挡住「发布」:能点掉就点掉,点不到也不算错。 */
  private async dismissHints(): Promise<void> {
    for (const text of this.s.dismissibleHints) {
      await clickTextPreferTrusted(this.driver, text, {
        exact: true,
        selector: "button, [role=button], a, div, span",
      }).catch(() => undefined);
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
      throw publishError("xiaohongshu", "publishErr_titleRejected");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    //: **简介只有视频那一档有**。图文 / 文章的正文已经由 `fillBody` 填过,这里再来一遍就会把同一段
    //: 文字打两次(维护者 2026-10-23:「会打两遍输入框文案」),而且第二遍的校验还可能不过。
    const description = this.task.contentKind === "video" ? stringOption(this.task, "description") : "";
    if (description) {
      await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
      await typeOrFill(this.driver, "xiaohongshu desc", this.s.contentEditor, description, async () => {
        await this.driver.focusAndClearField(this.s.contentEditor);
        await this.driver.insertText(this.s.contentEditor, description);
      });
      await this.driver.insertText(this.s.contentEditor, " ");
      const accepted = await this.driver.waitForFunction(
        this.acceptsTextExpression(this.s.contentEditor, description),
        3_000,
        200,
      );
      if (!accepted) {
        throw publishError("xiaohongshu", "publishErr_descriptionRejected");
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
      //: **每个标签单独一行**再逐字打(维护者:「标签最好应该换行输入」)。挤在同一行里,
      //: 话题候选与后续文本会互相干扰,发出来也是一长串;换行之后每条话题各占一行,和人在编辑器里
      //: 一个一个加话题的样子一致。
      await this.driver.pressKey("Enter");
      await wait(120 + Math.round(Math.random() * 160));
      await this.driver.type(`#${normalizedTag}`);
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
        //: 话题候选依赖平台的联想接口:等不到候选就**跳过这个标签**并收起下拉,继续下一个 ——
        //: 别让「增强项」把整条发布拖垮(借鉴 social-auto-upload)。已经打进去的 `#tag` 会作为普通文字
        //: 留在正文里(平台不认它,但也不影响发布);**不去全选删除** —— 那样会把正文一起清掉。
        await this.driver.pressKey("Escape").catch(() => undefined);
        continue;
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
        throw publishError("xiaohongshu", "publishErr_tagRejected", { tag: normalizedTag });
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
      throw publishError("xiaohongshu", "publishErr_originalMissing");
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
      throw publishError("xiaohongshu", "publishErr_originalStuck", { after, wanted });
    }
    plog("xiaohongshu original-content declaration:", wanted);
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
      plog("xiaohongshu visibility still shows:", shown.slice(0, 40));
      throw publishError("xiaohongshu", "publishErr_visibilityNotApplied", { visibility });
    }
    plog("xiaohongshu visibility:", visibility);
  }

  async submit(): Promise<void> {
    await this.dismissHints();
    await this.applyOriginal();
    await this.applyVisibility();
    const ready =
      (await this.driver.waitCssEnabled(this.s.submitButton, ACTION_TIMEOUT)) ||
      (await this.driver.waitTextEnabledDeep(this.s.submitText, 1_000, {
        hostSelector: this.s.submitHost,
      }));
    if (!ready) {
      throw publishError("xiaohongshu", "publishErr_submitDisabled");
    }

    // 四条降级路径互为兜底:发布按钮是 shadow DOM 里的自定义元素,外面 querySelector 不到,
    // 改版时往往是前几条陆续失效、最后落到最脆的按文案点击,而表现只是「偶尔发不出去」——
    // 所以走通的是哪一条必须记下来。这些路径全是派发事件,不依赖坐标,故都算 dom 类。
    try {
      await this.commitPublishClick();
    } catch (error) {
      //: 「点了但页面毫无反应」是**常见**结果(风控拦下、校验未过、网络卡住)—— 但链上传出来的原话是
      //: 「xiaohongshu submit: clicked but the page never reacted (tried: deep text 发布, …)」,
      //: 给用户看就是把内部诊断倒出来(维护者截图指出)。翻成一句人话,细节留在 trace 里。
      if (error instanceof CommitClickError) {
        throw publishError("xiaohongshu", "publishErr_submitNoReaction");
      }
      throw error;
    }
  }

  /** 点「发布」的降级链本身(拆出来只是为了给它包一层人话错误)。 */
  private async commitPublishClick(): Promise<void> {
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
    //: 点完「发布」之后,小红书的风控有时会弹扫码 / 身份验证。**我们不绕** —— 那是平台的安全机制;
    //: 但要把它说清楚并把人请过来(执行器会把窗口亮出来、任务标成「需要处理」),
    //: 而不是让它在 10 分钟里一遍遍等到超时、报一句「没有确认发布」。
    const blocked = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        return ${JSON.stringify(SELECTORS.xiaohongshu.verificationTexts)}.some((one) => text.includes(one));
      })()`,
      4_000,
      400,
    );
    if (blocked) {
      //: 文案走 i18n(桌面壳的 publishErr_*):界面上的字不写在适配器里。
      throw new AutomationBlockedError(
        "manual_required",
        t("publishErr_verifyRequired", { platform: platformName("xiaohongshu") }),
      );
    }

    //: 判「发完了吗」看三样:**成功文案**、**落在哪个页**(笔记详情 / 笔记管理 / 列表)、
    //: 以及——**回到创作页且草稿空了**就是没发出去。最后这条此前没有,于是页面被平台弹回创作页时,
    //: 任务在本该失败的这一刻继续等了十分钟(维护者 2026-10-23 的截图:面板停在「等待平台确认」,
    //: 里面却是「上传视频」那个创作页)。
    const donePattern = this.s.publishDoneTexts.join("|");
    const doneUrls = this.s.publishDoneUrls.map((one) => one.source);
    const deadline = Date.now() + RESULT_TIMEOUT;
    await wait(1_000);
    while (Date.now() < deadline) {
      const state = await this.driver
        .evaluate<{ done: boolean; backToEditor: boolean; url: string }>(`(() => {
          const text = document.body?.innerText || '';
          if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return { done: true, backToEditor: false, url: location.href };
          const url = location.href;
          if (${JSON.stringify(doneUrls)}.some((one) => new RegExp(one).test(url))) {
            return { done: true, backToEditor: false, url };
          }
          const isEditor = /\\/publish\\/publish|\\/new\\/publish/.test(url);
          const title = document.querySelector(${JSON.stringify(this.s.titleInput)});
          const titleEmpty = !title || !(title.value || '').trim();
          return { done: false, backToEditor: Boolean(isEditor && titleEmpty), url };
        })()`)
        .catch(() => null);
      if (state?.done) return;
      if (state?.backToEditor) {
        //: 再等一拍:平台可能正在这一次跳转里渲染成功页。
        await wait(1_500);
        const stillBack = await this.driver
          .evaluate<boolean>(`(() => {
            const text = document.body?.innerText || '';
            if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return false;
            const title = document.querySelector(${JSON.stringify(this.s.titleInput)});
            return !title || !(title.value || '').trim();
          })()`)
          .catch(() => false);
        if (stillBack) {
          await plogPageState("waitResult bounced back to the editor (xiaohongshu):", this.driver);
          throw publishError("xiaohongshu", "publishErr_backToEditor");
        }
      }
      await wait(800);
    }
    await plogPageState("waitResult timed out (xiaohongshu):", this.driver);
    throw publishError("xiaohongshu", "publishErr_notConfirmed");
  }
}

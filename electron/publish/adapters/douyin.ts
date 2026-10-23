import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, TEXT_PUBLISH_VIDEO, UPLOAD_TIMEOUT, clickTextPreferTrusted, enumOption, normalizeTag, plogPageState, publishError, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";

export class DouyinAdapter implements PublishAdapter {
  /**
   * 已接的形状(ADR 0076 第 2 步):视频与**图文**。
   * 图文 2026-10-23 真机核对:投稿页「发布图文」tab → 交图 → 跳到 `/content/post/image`,
   * 标题 0/20、描述 0/1000、最多 35 张图,可见性三档与视频同一套 label。
   */
  readonly supports = ["video", "image-text"] as const;
  private readonly s = SELECTORS.douyin;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
    if (this.task.contentKind === "image-text") {
      //: 投稿页**默认是视频**那一档(真机),图文的文件框在点了「发布图文」之后才可用:
      //: 视频那个框只收 `video/*`,把图片交给它,页面只会回一句「请先切换到图文」。
      //:
      //: **先等那一排 tab 画出来再点**:SPA 落地时它们晚一拍才出现,直接点会"点了个空气",
      //: 然后以「找不到入口」失败(2026-10-23 真机就是这么红的一条)。判据用页面自己的文案。
      const tabsReady = await this.driver.waitForFunction(
        `(() => (document.body?.innerText || '').includes(${JSON.stringify(this.s.imageTextTabText)}))()`,
        ACTION_TIMEOUT,
        300,
      );
      if (!tabsReady) {
        throw publishError("douyin", "publishErr_tabMissing", { tab: this.s.imageTextTabText });
      }
      //: 点两次(精确 / 包含):tab 上可能带角标之类附加字。
      for (const exact of [true, false]) {
        await clickTextPreferTrusted(this.driver, this.s.imageTextTabText, {
          exact,
          selector: "div, button, [role=button], a, span, li",
        }).catch(() => undefined);
        if (await this.driver.cssAttached(this.s.imageFileInput, 5_000)) return;
      }
      throw publishError("douyin", "publishErr_tabMissing", { tab: this.s.imageTextTabText });
    }
    const uploadReady = await this.driver.fileInputAttached(this.s.fileInput, 6_000);
    if (!uploadReady && (await this.driver.hasText(TEXT_PUBLISH_VIDEO))) {
      await clickTextPreferTrusted(this.driver, TEXT_PUBLISH_VIDEO, {
        exact: true,
        selector: "button, [role=button], a, div, span",
      }).catch(() => undefined);
    }
  }

  /** 图文:一次交多张图片(**顺序就是数组顺序**),等它跳到图文编辑器。 */
  async uploadImages(paths: string[]): Promise<void> {
    if (!paths.length) throw publishError("douyin", "publishErr_noAssets");
    await this.driver.fileInputAttached(this.s.imageFileInput, ACTION_TIMEOUT);
    await this.driver.setFiles(this.s.imageFileInput, paths);
    //: 交完图上会跳到 `/content/post/image`;那一页**没有文件框**,只有标题与描述。
    const landed = await this.driver.waitForFunction(
      `(() => location.href.includes('/content/post/image'))()`,
      UPLOAD_TIMEOUT,
      500,
    );
    if (!landed) throw publishError("douyin", "publishErr_editorMissing");
    await this.driver.cssVisible(this.s.imageTitleInput, UPLOAD_TIMEOUT);
    await this.dismissOnboarding();
  }

  /** 图文的正文:抖音的 zone 编辑器(和视频那一档的「作品描述」是同一个控件家族)。 */
  async fillBody(body: string): Promise<void> {
    const value = body.trim();
    if (!value) return;
    const selector = this.s.imageDescEditor;
    await this.driver.cssVisible(selector, ACTION_TIMEOUT);
    //: **先点一下拿到焦点**,再逐行打。此前走 `focusEnd` + 一次性 insertText:传完图之后 DOM
    //: 会重建,`focusEnd` 找的是那一刻的节点,报「element not found」把整条任务拦下(真机 2026-10-23)。
    //: 点一下 + 真实按键不依赖节点身份,编辑器换了实例也照样能打进去。
    await this.driver.pointerClickCss(selector).catch(() => undefined);
    await this.driver.focusAndClearField(selector).catch(() => undefined);
    await this.driver.typeLines(value);
    //: 富文本会把 `1. …` 变成有序列表、换行位置也会变,所以**空白不敏感**地比对(同小红的教训)。
    const accepted = await this.driver.waitForFunction(
      `(() => {
        const squash = (text) => String(text || '').replace(/\s+/g, '');
        const want = squash(${JSON.stringify(value)});
        const editors = [...document.querySelectorAll(${JSON.stringify(selector)})];
        const longest = editors.map((one) => one.innerText || one.textContent || '').sort((a, b) => b.length - a.length)[0] || '';
        if (squash(longest).includes(want)) return true;
        //: 兜底:这个平台自己也有字数计数(0 / 1000)。富文本改写标点/列表时,长度对得上就够了。
        const counted = (document.body?.innerText || '').match(/(\d+)\s*\/\s*1000/);
        return counted ? Number(counted[1]) >= Math.floor(want.length * 0.6) : false;
      })()`,
      4_000,
      200,
    );
    if (!accepted) throw publishError("douyin", "publishErr_descriptionRejected");
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
      throw publishError("douyin", "publishErr_uploadTimeout");
    }
    if (await this.driver.hasText(this.s.uploadFailedText)) {
      throw publishError("douyin", "publishErr_uploadFailed");
    }
  }

  async fillTitle(title: string): Promise<void> {
    const selector = this.task.contentKind === "image-text" ? this.s.imageTitleInput : this.s.titleInput;
    await this.driver.cssVisible(selector, ACTION_TIMEOUT);
    //: 图文标题上限 20(真机 0/20),视频那一档是 30。
    const value = title.slice(0, this.task.contentKind === "image-text" ? 20 : 30);
    await typeOrFill(this.driver, "douyin title", selector, value, () => this.driver.fillCss(selector, value));
  }

  /** 描述/正文那一格:视频是 `作品描述`,图文是 `添加作品描述...` —— 同一个编辑器家族的两种壳。 */
  private get descField(): string {
    return this.task.contentKind === "image-text" ? this.s.imageDescEditor : this.s.descEditor;
  }

  async fillTags(tags: string[]): Promise<void> {
    //: 说明只在**视频**那一档由这里填;图文的正文已经由 `fillBody` 填过(再填一遍就是两段重复文字)。
    const description = this.task.contentKind === "video" ? stringOption(this.task, "description") : "";
    if (description) {
      await this.driver.cssVisible(this.descField, ACTION_TIMEOUT);
      await typeOrFill(this.driver, "douyin desc", this.descField, description, async () => {
        // 降级前必须先清空:typeInto 可能已敲进去一部分,而 insertText 是在光标处插入,
        // 不清就会把残留和完整文案叠在一起。
        await this.driver.focusAndClearField(this.descField);
        await this.driver.insertText(this.descField, description);
      });
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.descField, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const topicText = `#${normalizedTag}`;
      await this.driver.insertText(this.descField, ` ${topicText}`);
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
      await this.driver.insertText(this.descField, " ");
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
      throw publishError("douyin", "publishErr_visibilityNotApplied", { visibility });
    }
    plog("douyin visibility:", visibility);
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
    plog("douyin onboarding: trusted dismissal failed, removing the node instead");
    await this.driver.removeElements(this.s.overlays);
  }

  async waitResult(): Promise<void> {
    const ok = await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT);
    if (!ok) {
      await plogPageState("waitResult failed (douyin):", this.driver);
      throw publishError("douyin", "publishErr_notConfirmed");
    }
  }
}

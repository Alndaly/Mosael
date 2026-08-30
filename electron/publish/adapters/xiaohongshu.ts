import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, TEXT_NEW_TOPIC, UPLOAD_TIMEOUT, boolOption, clickTextPreferTrusted, enumOption, normalizeTag, plogPageState, stringOption, typeOrFill, wait } from "./shared";
import { SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";

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
      throw new Error("小红书上传后编辑器未出现(找不到标题输入框)。");
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
      throw new Error("小红书标题输入框没有接受填入的内容。");
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
        throw new Error("小红书正文编辑器没有接受填入的描述。");
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
      throw new Error("小红书「原创声明」控件未找到。");
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
      throw new Error("小红书发布按钮不可点击。");
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

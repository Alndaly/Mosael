import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, TEXT_PUBLISH_VIDEO, UPLOAD_TIMEOUT, clickTextPreferTrusted, enumOption, normalizeTag, plogPageState, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";

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
      throw new Error("抖音上传超时,未在时限内完成。");
    }
    if (await this.driver.hasText(this.s.uploadFailedText)) {
      throw new Error("抖音报告视频上传失败(页面出现「上传失败」)。");
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
      throw new Error("抖音未确认发布(没有跳转到内容管理页)。");
    }
  }
}

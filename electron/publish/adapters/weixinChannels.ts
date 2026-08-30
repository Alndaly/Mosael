import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, HUMAN_INTERVENTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, normalizeTag, plogPageState, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { AutomationBlockedError } from "../errors";

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
      throw new Error("微信视频号未找到上传入口。");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();

    // Upload done == the 发表 button leaves its disabled state.
    const ok = await this.driver.waitButtonEnabled(this.s.submitText, UPLOAD_TIMEOUT);
    if (!ok) {
      if (await this.driver.cssVisible(this.s.uploadFailed, 500)) {
        throw new Error("微信视频号报告上传出错(status-msg.error)。");
      }
      throw new Error("微信视频号上传超时,未在时限内完成。");
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
      throw new Error("微信视频号发表按钮不可点击。");
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
      throw new Error("微信视频号未确认发布(没有跳转到动态列表)。");
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

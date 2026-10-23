import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, HUMAN_INTERVENTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, normalizeTag, plogPageState, publishError, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { AutomationBlockedError } from "../errors";
import { contractFor } from "../contracts";
import { awaitResult } from "../verify";
import { plog } from "../log";

export class WeixinChannelsAdapter implements PublishAdapter {

  /** 这一档的入口地址:契约里写的那一条(平台改了投稿地址只需要改契约)。 */
  private entryUrl(): string {
    const url = this.c.entry.video?.url;
    if (!url) throw publishError("weixin-channels", "publishErr_kindNotImplemented", { kind: "video" });
    return url;
  }
  /** 已接的形状(ADR 0076)。 */
  /** 已接的形状:声明在**类**上 —— 契约测试与执行器要按平台读它(实例字段读不到)。 */
  static readonly KINDS = ["video"] as const;
  readonly supports = WeixinChannelsAdapter.KINDS;
  private readonly s = SELECTORS.weixinChannels;
  /** 页面契约:入口 / 提交 / 成功信号都从这儿来。 */
  private readonly c = contractFor("weixin-channels");

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.entryUrl());
  }

  /**
   * 登上了吗。**线上误判过一次**:登录页只弹出「微信快捷登录」卡片、人还没点确认,账号就被写成了
   * 已登录。当时两件事叠在一起 —— 进 /platform/post/create 被服务端踢回 login.html 的那一瞬,
   * `url()` 已经是 post/create 而页面还是登录页;而登录页底部的介绍卡片恰好叫「内容管理」,
   * 于是「URL 不是登录页 + 找到了创作页文案」两条都成立。
   *
   * 所以:登录页自己的文案先判未登录;创作页标志只在 /platform/ 下算数;判成已登录之前再看一眼
   * URL —— 这期间被踢回登录页的话,刚才看到的就不是创作页。
   */
  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    if (await this.driver.cssVisible(this.s.loginLanding, 2_500)) {
      return false;
    }
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return false;
      }
    }
    if (!this.s.isPlatformUrl(this.driver.url())) {
      return false;
    }
    let found = false;
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        found = true;
        break;
      }
    }
    if (!found) found = await this.driver.fileInputAttached(this.s.fileInput, 4_000);
    return found && this.s.isPlatformUrl(this.driver.url());
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
      throw publishError("weixin-channels", "publishErr_noUploadEntry");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();

    // Upload done == the 发表 button leaves its disabled state.
    const ok = await this.driver.waitButtonEnabled(this.s.submitText, UPLOAD_TIMEOUT);
    if (!ok) {
      if (await this.driver.cssVisible(this.s.uploadFailed, 500)) {
        throw publishError("weixin-channels", "publishErr_uploadFailed");
      }
      throw publishError("weixin-channels", "publishErr_uploadTimeout");
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
      throw publishError("weixin-channels", "publishErr_submitDisabled");
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
    //: 判据在契约里:跳到作品列表 **或** 页面上出现成功文案(含 shadow root,原语负责)。
    const outcome = await awaitResult(this.driver, this.c.done, { timeout: RESULT_TIMEOUT });
    plog("weixin-channels waitResult:", outcome);
    if (outcome.status === "success") return;
    await plogPageState("waitResult failed (weixin-channels):", this.driver);
    throw publishError("weixin-channels", "publishErr_notConfirmed");
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
          publishError("weixin-channels", "publishErr_adminVerify").message,
        );
      }
    }
  }

  private async assertCanPublish(): Promise<void> {
    if (await this.driver.hasTextDeep(this.s.noPermissionText)) {
      throw new AutomationBlockedError(
        "permission_required",
        publishError("weixin-channels", "publishErr_notOperator").message,
      );
    }
  }
}

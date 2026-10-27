import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, HUMAN_INTERVENTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, normalizeTag, plogPageState, publishError, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { AutomationBlockedError } from "../errors";
import { contractFor, fieldsFor } from "../contracts";
import { awaitResult } from "../verify";
import { plog } from "../log";

export class WeixinChannelsAdapter implements PublishAdapter {

  /** 这一档的入口地址:契约里写的那一条(平台改了投稿地址只需要改契约)。 */
  private entryUrl(): string {
    const url = this.c.entry[this.task.contentKind]?.url ?? this.c.entry.video?.url;
    if (!url) throw publishError("weixin-channels", "publishErr_kindNotImplemented", { kind: this.task.contentKind });
    return url;
  }

  /** 图文那一档的驱动:「发表动态」的表单整个在同源 iframe 里(外层只有导航)。 */
  private imageDriver(): PageDriver {
    return this.driver.inFrame(this.s.imageTextFrame);
  }

  private get isImageText(): boolean {
    return this.task.contentKind === "image-text";
  }
  /** 已接的形状(ADR 0076)。 */
  /** 已接的形状:声明在**类**上 —— 契约测试与执行器要按平台读它(实例字段读不到)。 */
  static readonly KINDS = ["video", "image-text"] as const;
  readonly supports = WeixinChannelsAdapter.KINDS;
  private readonly s = SELECTORS.weixinChannels;
  /** 页面契约:入口 / 提交 / 成功信号都从这儿来。 */
  private readonly c = contractFor("weixin-channels");
  private get f() {
    return fieldsFor(this.c, this.task.contentKind);
  }

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    if (this.isImageText) {
      await this.driver.goto(this.entryUrl());
      const inner = this.imageDriver();
      const ready = await inner.cssVisible(this.s.imageTitleInput, 20_000).catch(() => false);
      if (!ready) {
        await plogPageState("WeChat channels image composer missing:", this.driver);
        throw publishError("weixin-channels", "publishErr_editorMissing");
      }
      return;
    }
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

  async uploadImages(paths: string[]): Promise<void> {
    //: 「发表动态」页:一次交多张(平台上限 18 张、单张 ≤20MB),文件框在 iframe 里。
    if (!paths.length) throw publishError("weixin-channels", "publishErr_noAssets");
    const inner = this.imageDriver();
    if (!(await inner.fileInputAttached(this.s.imageFileInput, ACTION_TIMEOUT))) {
      await plogPageState("WeChat channels image upload entry missing:", this.driver);
      throw publishError("weixin-channels", "publishErr_noUploadEntry");
    }
    await inner.setFiles(this.s.imageFileInput, paths);
    //: 缩略图出现 = 前端接住了文件。没有别的完成信号(平台不显示进度/百分比)。
    if (!(await inner.cssVisible(this.s.imageUploaded, UPLOAD_TIMEOUT).catch(() => false))) {
      await plogPageState("WeChat channels images not accepted:", this.driver);
      throw publishError("weixin-channels", "publishErr_uploadTimeout");
    }
    await wait(600);
  }

  async fillTitle(title: string): Promise<void> {
    if (this.isImageText) {
      const value = title.slice(0, 22);
      const inner = this.imageDriver();
      await inner.cssVisible(this.f.title, ACTION_TIMEOUT);
      await inner.fillField(this.f.title, value);
      const current = await inner.cssValue(this.f.title);
      if (!current?.includes(value)) throw publishError("weixin-channels", "publishErr_titleRejected");
      return;
    }
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const description = stringOption(this.task, "description") ?? title;
    const shortTitle = stringOption(this.task, "shortTitle") ?? title;
    await this.driver.cssVisible(this.f.title, ACTION_TIMEOUT);
    await typeOrFill(this.driver, "weixin-channels desc", this.f.title, description, async () => {
      await this.driver.focusAndClearField(this.f.title);
      await this.driver.insertText(this.f.title, description);
    });
    // Optional short title (best effort; skipped if the field is absent).
    const shortTitleField = this.f.shortTitle;
    if (shortTitleField && (await this.driver.cssVisible(shortTitleField, 2_000))) {
      await this.driver.fillCss(shortTitleField, shortTitle.slice(0, 16)).catch(() => undefined);
    } else {
      await this.driver.fillInputNearText("短标题", shortTitle.slice(0, 16)).catch(() => false); // i18n-ok
    }
  }

  async fillBody(body: string): Promise<void> {
    const value = body.trim();
    if (!value) return;
    const inner = this.imageDriver();
    if (!(await inner.cssVisible(this.f.body, ACTION_TIMEOUT))) {
      await plogPageState("WeChat channels image description missing:", this.driver);
      throw publishError("weixin-channels", "publishErr_editorMissing");
    }
    await inner.focusAndClearField(this.f.body);
    await inner.insertTextLines(this.f.body, value);
    const shown = await inner.cssValue(this.f.body);
    const squash = (text: string) => text.replace(/\s+/g, "");
    if (!squash(shown ?? "").includes(squash(value).slice(0, 40))) {
      await plogPageState("WeChat channels image description mismatch:", this.driver);
      throw publishError("weixin-channels", "publishErr_descriptionRejected");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    //: 图文的标签是**描述里的 #话题**,接在正文后面(视频那一档才有独立的标签框)。
    if (this.isImageText) {
      const inner = this.imageDriver();
      for (const tag of tags) {
        const normalized = normalizeTag(tag);
        if (!normalized) continue;
        await inner.focusEnd(this.f.tags);
        await inner.insertText(this.f.tags, ` #${normalized}`);
        await wait(300);
      }
      return;
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.f.tags, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      await this.driver.insertText(this.f.tags, ` #${normalizedTag}`);
      await this.driver.pressKey("Space");
      await wait(300);
    }
  }

  async submit(): Promise<void> {
    if (this.isImageText) {
      const inner = this.imageDriver();
      const clicked = await inner
        .clickByText(this.s.submitText, { exact: true })
        .then(() => true)
        .catch(() => false);
      if (!clicked) {
        await plogPageState("WeChat channels image publish button missing:", this.driver);
        throw publishError("weixin-channels", "publishErr_submitDisabled");
      }
      return;
    }
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

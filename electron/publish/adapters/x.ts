import { statSync } from "node:fs";

import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, clickTextPreferTrusted, hasStoredSession, plogPageState, publishError, stringOption, wait } from "./shared";
import { SELECTORS } from "../selectors";
import { plog } from "../log";
import { contractFor } from "../contracts";
import { awaitResult } from "../verify";

/**
 * X(Twitter)。发帖走 x.com 全站共用的撰写组件(`/compose/post` 一页只有它)。
 *
 * X 没有「标题/描述/标签」的分栏 —— 帖子正文就是文案,`#hashtag` 写进正文里(和 TikTok 的
 * caption 同一角色,见 fillTitle/fillTags)。
 *
 * 视频限制 ≤2:20 / ≤512MB:超长的片子页面会在上传后自己拒掉,waitResult 等不到完成文案,
 * 按超时失败回报 —— 不是静默成功,也不是误报成功。
 *
 * 境内需要可用的出站代理(和 TikTok/YouTube 同一类);登录态靠 auth_token cookie 与
 * 页面结构双重判据(platforms.ts 的 session 配置)。
 */
//: X 的上传上限(2026-10 的公开限制):≤512MB、≤2 分 20 秒、MP4(H.264 + AAC)。
//: 超限时页面会先接住文件、随后报「could not be processed / Incompatible video codecs」——
//: 不提前挡一下,用户只能对着那句英文猜。
const X_MAX_BYTES = 512 * 1024 * 1024;

export class XAdapter implements PublishAdapter {

  /** 这一档的入口地址:契约里写的那一条(平台改了投稿地址只需要改契约)。 */
  private entryUrl(): string {
    const url = this.c.entry.video?.url;
    if (!url) throw publishError("x", "publishErr_kindNotImplemented", { kind: "video" });
    return url;
  }
  /** 已接的形状(ADR 0076)。 */
  /** 已接的形状:声明在**类**上 —— 契约测试与执行器要按平台读它(实例字段读不到)。 */
  static readonly KINDS = ["video", "image-text", "article"] as const;
  readonly supports = XAdapter.KINDS;
  private readonly s = SELECTORS.x;
  /** 页面契约:入口 / 提交 / 成功信号都从这儿来。 */
  private readonly c = contractFor("x");

  // 帖子文本要把「简介」一起写进去(见 fillTitle),所以任务要留着。
  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  private get isArticle(): boolean {
    return this.task.contentKind === "article";
  }

  async openCreatorPage(): Promise<void> {
    if (this.isArticle) {
      //: 长文没有"直连新文章"的地址:先进文章列表页,点「Write」由平台**新建一篇草稿**
      //: (地址随后变成 `/compose/articles/edit/<id>`)。
      await this.driver.goto(this.entryUrl());
      await clickTextPreferTrusted(this.driver, this.s.articleWriteText, { exact: true });
      const ready = await this.driver
        .waitForFunction(
          `(() => Boolean(document.querySelector(${JSON.stringify(this.s.articleTitle)})))()`,
          20_000,
          250,
        )
        .catch(() => false);
      if (!ready) {
        await plogPageState("X article editor missing:", this.driver);
        throw publishError("x", "publishErr_editorMissing");
      }
      return;
    }
    await this.driver.goto(this.entryUrl());
    // 撰写组件是 SPA 路由;持久视图复用同一个 WebContents,上一次发完停在首页,直接 goto
    // 同站另一路由未必重挂组件。没探到正文框就断开再回来(同 B 站/TikTok 那一课)。
    if (!(await this.driver.cssVisible(this.s.textEditor, 6_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.entryUrl());
    }
    // 首访的 onboarding / 提示模态挡真实点击:逐条试着关(点「暂不/关闭」,不替用户改设置)。
    for (const text of this.s.dismissTexts) {
      await clickTextPreferTrusted(this.driver, text, { exact: true }).catch(() => undefined);
    }
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    // 结构优先:未登录首页左边栏是「登录」入口而不是账号切换钮。
    if (await this.driver.cssVisible(this.s.loggedOutMarks, 2_000)) {
      return false;
    }
    // 页面无关的一条:auth_token 是 HttpOnly 会话 cookie,登录即写;x.com 登完常把人留在
    // 首页/信息流,不在撰写页(同 YouTube/TikTok 的教训)。
    if (await hasStoredSession(this.driver, "x")) {
      return true;
    }
    // 撰写页本身能渲染 = 登录态有效(X 未登录访问 /compose/post 会被送去登录)。
    if (await this.driver.cssVisible(this.s.textEditor, 4_000)) {
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
    //: 体积先挡:超限时 X 只会回一句笼统的「could not be processed」,提前说是哪个限制。
    try {
      const bytes = statSync(videoPath).size;
      if (bytes > X_MAX_BYTES) {
        throw publishError("x", "publishErr_videoTooLarge", {
          limit: 512,
          actual: Math.round(bytes / (1024 * 1024)),
        });
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes("publishErr_videoTooLarge")) throw error;
      // 读不到文件大小(路径不存在等)交给后面的上传步骤报,别在这里吞掉。
    }
    if (!(await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT))) {
      await plogPageState("X upload entry missing:", this.driver);
      throw publishError("x", "publishErr_noUploadEntry");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    // 缩略图容器出现 = 前端接住了文件;**里面的进度条消失** 才是处理完(转码/校验期间发帖钮
    // 一直禁用,和 TikTok 的「按钮可用」同一性质,这里是进度条这个更直接的结构信号)。
    if (!(await this.driver.cssVisible(this.s.attachments, UPLOAD_TIMEOUT))) {
      throw publishError("x", "publishErr_editorMissing");
    }
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    while (Date.now() < deadline) {
      //: 页面报错时把那句话本身带出来 —— X 会说「Incompatible video codecs」这类具体原因,
      //: 笼统的「上传失败」会让用户拿着一个 2:20 都不到的片子反复重试。
      const failedLine = await this.driver
        .evaluate<string>(
          `(() => {
            const re = new RegExp(${JSON.stringify(failedPattern)});
            const lines = (document.body?.innerText || "").split("\\n").map((one) => one.trim());
            return lines.find((one) => re.test(one)) || "";
          })()`,
        )
        .catch(() => "");
      if (failedLine) {
        await plogPageState("X upload failed:", this.driver);
        throw publishError("x", "publishErr_videoRejected", { reason: JSON.stringify(failedLine.slice(0, 160)) });
      }
      const processing = await this.driver.cssVisible(this.s.uploadProgress, 1_000).catch(() => false);
      if (!processing) {
        return;
      }
      await wait(1_000);
    }
    await plogPageState("X upload did not settle:", this.driver);
    throw publishError("x", "publishErr_uploadTimeout");
  }

  async uploadImages(paths: string[]): Promise<void> {
    //: X 的图片和视频走**同一个**文件框(它接受图片与视频),一次交多张。
    if (!paths.length) throw publishError("x", "publishErr_noAssets");
    if (!(await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT))) {
      await plogPageState("X image upload entry missing:", this.driver);
      throw publishError("x", "publishErr_noUploadEntry");
    }
    await this.driver.setFiles(this.s.fileInput, paths);
    //: 等每一张都挂上(缩略图容器出现)并处理完(进度条消失)—— 和视频那条同一道判据。
    if (!(await this.driver.cssVisible(this.s.attachments, UPLOAD_TIMEOUT))) {
      throw publishError("x", "publishErr_editorMissing");
    }
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    while (Date.now() < deadline) {
      const processing = await this.driver.cssVisible(this.s.uploadProgress, 1_000).catch(() => false);
      if (!processing) return;
      await wait(1_000);
    }
    await plogPageState("X images did not settle:", this.driver);
    throw publishError("x", "publishErr_uploadTimeout");
  }

  async fillTitle(title: string): Promise<void> {
    if (this.isArticle) {
      const value = title.slice(0, 100);
      await this.driver.cssVisible(this.s.articleTitle, ACTION_TIMEOUT);
      await this.driver.fillField(this.s.articleTitle, value);
      const current = await this.driver.cssValue(this.s.articleTitle);
      if (!current?.includes(value)) throw publishError("x", "publishErr_titleRejected");
      return;
    }
    //: **图文**:标题和正文要写成同一条帖子,由 `fillBody` 一次写入;这里什么都不做
    //: (X 只有一个文本框,分两次写就是后一次覆盖前一次)。
    if (this.task.contentKind === "image-text") return;
    // X 没有标题栏:这一栏就是**帖子正文**。标题是它的第一行,简介(平台的「简介」字段,
    // 见 platformOptions.description)接在下面 —— 只写标题的话简介就整个丢了(维护者实测:
    // 发出去的帖子只有「标题 #标签」)。标签由 fillTags 接在末尾。
    const description = stringOption(this.task, "description");
    const text = description ? `${title}\n${description}` : title;
    await this.driver.focusAndClearField(this.s.textEditor);
    await this.driver.insertText(this.s.textEditor, text);
    await wait(400);
    const actual = ((await this.driver.cssValue(this.s.textEditor)) ?? "").trim();
    if (!actual.includes(title.trim()) || (description && !actual.includes(description.trim()))) {
      await plogPageState("X text mismatch:", this.driver);
      throw publishError("x", "publishErr_titleMismatch", {
        expected: JSON.stringify(title.slice(0, 40)),
        actual: JSON.stringify(actual.slice(0, 80)),
      });
    }
  }

  /** 图文的正文:标题 + 正文,一次写进那条帖子。 */
  async fillBody(body: string): Promise<void> {
    const value = body.trim();
    if (!value) return;
    if (this.isArticle) {
      await this.driver.cssVisible(this.s.articleEditor, ACTION_TIMEOUT);
      await this.driver.focusAndClearField(this.s.articleEditor);
      await this.driver.insertTextLines(this.s.articleEditor, value);
      await wait(500);
      const actual = ((await this.driver.cssValue(this.s.articleEditor)) ?? "").trim();
      //: 判定按"开头那段字在不在"(DraftJS 按段落重排,行内空白不是问题;整段缺失才是)。
      if (!actual.replace(/\s+/g, "").includes(value.replace(/\s+/g, "").slice(0, 40))) {
        await plogPageState("X article body mismatch:", this.driver);
        throw publishError("x", "publishErr_descriptionRejected");
      }
      return;
    }
    const title = this.task.title.trim();
    const text = title ? `${title}\n\n${value}` : value;
    await this.driver.cssVisible(this.s.textEditor, ACTION_TIMEOUT);
    await this.driver.focusAndClearField(this.s.textEditor);
    await this.driver.insertTextLines(this.s.textEditor, text);
    await wait(400);
    const actual = ((await this.driver.cssValue(this.s.textEditor)) ?? "").trim();
    if (!actual.includes(title || value.split("\n")[0])) {
      await plogPageState("X body mismatch:", this.driver);
      throw publishError("x", "publishErr_descriptionRejected");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    if (tags.length === 0) {
      return;
    }
    if (this.isArticle) {
      //: 长文的标签同样是正文里的 #hashtag(没有独立标签栏)。
      for (const tag of tags) {
        const clean = tag.replace(/^#/, "").trim();
        if (!clean) continue;
        await this.driver.focusEnd(this.s.articleEditor);
        await this.driver.insertText(this.s.articleEditor, ` ${clean}`);
        await wait(300);
      }
      return;
    }
    // 话题写进正文末尾:X 的 #hashtag 本来就是正文的一部分,没有独立标签框。
    await this.driver.focusEnd(this.s.textEditor);
    for (const tag of tags) {
      const clean = tag.replace(/^#/, "").trim();
      if (!clean) continue;
      await this.driver.insertText(this.s.textEditor, ` #${clean}`);
      await wait(400);
    }
  }

  async submit(): Promise<void> {
    if (this.isArticle) {
      //: 长文的「Publish」在编辑器右上。**发布后不可逆**,所以只点一次;若平台弹出一层
      //: 确认(内容摘要 + 再点一次 Publish),那也算同一次提交的一部分。
      const clicked = await clickTextPreferTrusted(this.driver, this.s.articlePublishText, { exact: true })
        .then(() => true)
        .catch(() => false);
      if (!clicked) {
        await plogPageState("X article publish button missing:", this.driver);
        throw publishError("x", "publishErr_submitDisabled");
      }
      //: 有的版本发完会再弹一层确认(`role=dialog` 里的第二颗 Publish)。**只在弹层里找**:
      //: 在整页里找会有两个问题 —— 一是可能又点到右上那颗(重复提交),二是有些版本把按钮
      //: 留在 DOM 里但已禁用,点了也没反应却记成"点过"。
      await wait(1_200);
      const confirmed = await this.driver
        .evaluate<boolean>(`(() => {
          const dialogs = [...document.querySelectorAll('[role="dialog"], [data-testid="sheetDialog"]')];
          for (const dialog of dialogs) {
            const again = [...dialog.querySelectorAll('button, [role=button]')]
              .find((one) => (one.textContent || '').trim() === ${JSON.stringify(this.s.articlePublishText)});
            if (again) {
              again.click();
              return true;
            }
          }
          return false;
        })()`)
        .catch(() => false);
      plog("x article submit: confirm dialog", confirmed);
      return;
    }
    // X 的发帖钮在媒体处理完、正文非空时才可用;不可用就等它可用,而不是绕过去硬点
    // (设不上就不许发 —— 自动发布误发公开是收不回的,和别家同一规矩)。
    if (!(await this.driver.waitCssEnabled(this.s.postButton, ACTION_TIMEOUT).catch(() => false))) {
      for (const text of this.s.postTexts) {
        try {
          await clickTextPreferTrusted(this.driver, text, { exact: true });
          return;
        } catch {
          // 换下一种说法
        }
      }
      await plogPageState("X submit button unavailable:", this.driver);
      throw publishError("x", "publishErr_submitDisabled");
    }
    await this.driver.clickCss(this.s.postButton);
  }

  async waitResult(): Promise<void> {
    if (this.isArticle) {
      //: 长文发完:编辑页(`…/articles/edit/<id>`)消失 —— 地址变了,或标题框没了。
      //: 只看地址不够(列表页与编辑页只差一段路径),所以再等真正的成功文案/落地页。
      const deadline = Date.now() + RESULT_TIMEOUT;
      while (Date.now() < deadline) {
        const state = await this.driver
          .evaluate<{ url: string; editor: boolean }>(`(() => ({
            url: location.href,
            editor: Boolean(document.querySelector(${JSON.stringify(this.s.articleTitle)})),
          }))()`)
          .catch(() => null);
        if (state && !state.editor) {
          plog("x article waitResult:", { url: state.url });
          return;
        }
        await wait(1_000);
      }
      await plogPageState("X article waitResult failed:", this.driver);
      throw publishError("x", "publishErr_notConfirmed");
    }
    //: 判据在契约里:地址回到首页 **或**「已发送」toast;两者都要过"撰写组件已经消失"这道闸
    //: (X 发完把人送回首页,而 "Post" 这类词在按钮上本来就写着)。
    const outcome = await awaitResult(this.driver, this.c.done, { timeout: RESULT_TIMEOUT });
    plog("x waitResult:", outcome);
    if (outcome.status === "success") return;
    await plogPageState("waitResult failed (x):", this.driver);
    throw publishError("x", "publishErr_notConfirmed");
  }
}

import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, clickTextPreferTrusted, enumOption, hasStoredSession, plogPageState, wait } from "./shared";
import { SELECTORS } from "../selectors";
import { plog } from "../log";

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
      throw new Error("TikTok 未找到上传入口。");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    // 文案编辑器出现 = 表单渲染了,**不等于视频传完**(同 B 站那一课)。真正的完成信号是
    // 「发布按钮可用」:TikTok 在转码完成前一直禁用它。
    if (!(await this.driver.cssVisible(this.s.captionEditor, UPLOAD_TIMEOUT))) {
      throw new Error("TikTok 上传后编辑器未出现(找不到描述输入框)。");
    }
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    while (Date.now() < deadline) {
      const failed = await this.driver
        .evaluate<boolean>(`new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`)
        .catch(() => false);
      if (failed) {
        await plogPageState("TikTok upload failed:", this.driver);
        throw new Error("TikTok 报告上传失败。");
      }
      if (await this.driver.waitCssEnabled(this.s.postButton, 2_000).catch(() => false)) {
        return;
      }
      await wait(1_000);
    }
    await plogPageState("TikTok upload did not settle:", this.driver);
    throw new Error("TikTok 上传超时(发布按钮一直不可用)。");
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
      throw new Error("TikTok 可见范围控件未找到,为避免误公开发布已中止。");
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
      throw new Error("TikTok 发布按钮始终不可点击。");
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
      throw new Error("TikTok 未确认发布(没有成功提示,也没有跳转到内容列表)。");
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

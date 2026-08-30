import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, boolOption, enumOption, hasStoredSession, plogPageState, stringOption, wait } from "./shared";
import { SELECTORS } from "../selectors";
import { plog } from "../log";
import { resolvePlatform } from "../platforms";

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
      throw new Error("YouTube 未找到上传入口。");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    // 标题框出现 = 详情表单渲染了,视频仍在后台上传/处理。YouTube 会一直在页面上写
    // 「Uploading x%」/「Processing」,完成后变成「Upload complete」「Checks complete」之类。
    if (!(await this.driver.cssVisible(this.s.titleBox, UPLOAD_TIMEOUT))) {
      throw new Error("YouTube 上传后详情表单未出现(找不到标题输入框)。");
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
        throw new Error("YouTube 报告上传失败。");
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
      throw new Error("YouTube 上传超时,未在时限内完成。");
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
      throw new Error("YouTube 完成按钮始终不可点击。");
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
      throw new Error("YouTube 未确认上传(列表里没有该视频,也没有成功提示)。");
    }
  }
}

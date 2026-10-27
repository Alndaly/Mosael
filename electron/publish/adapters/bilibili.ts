import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, RESULT_TIMEOUT, UPLOAD_TIMEOUT, normalizeTag, plogPageState, publishError, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";
import { awaitResult } from "../verify";
import { contractFor, fieldsFor } from "../contracts";

export class BilibiliAdapter implements PublishAdapter {

  /** 这一档的入口地址:契约里写的那一条(平台改了投稿地址只需要改契约)。 */
  private entryUrl(): string {
    const url = this.c.entry[this.task.contentKind]?.url ?? this.c.entry.video?.url;
    if (!url) throw publishError("bilibili", "publishErr_kindNotImplemented", { kind: this.task.contentKind });
    return url;
  }

  /** 文章这一档的驱动:**编辑器整个在 `read-editor` 那个同源 iframe 里**。 */
  private articleDriver(): PageDriver {
    return this.driver.inFrame(this.s.articleFrame);
  }

  /** 这一次发的是文章吗(专栏)。 */
  private get isArticle(): boolean {
    return this.task.contentKind === "article";
  }
  /** 已接的形状(ADR 0076)。 */
  /** 已接的形状:声明在**类**上 —— 契约测试与执行器要按平台读它(实例字段读不到)。 */
  static readonly KINDS = ["video", "article"] as const;
  readonly supports = BilibiliAdapter.KINDS;
  private readonly s = SELECTORS.bilibili;
  /** 页面契约:入口 / 提交 / 成功信号都从这儿来。 */
  private readonly c = contractFor("bilibili");
  private get f() {
    return fieldsFor(this.c, this.task.contentKind);
  }

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    if (this.isArticle) {
      //: 专栏编辑器在 iframe 里,**等里面那格标题出现**才算这一页就绪(外层的导航早就有了)。
      await this.driver.goto(this.entryUrl());
      const inner = this.articleDriver();
      if (!(await inner.cssVisible(this.f.title, 20_000).catch(() => false))) {
        await plogPageState("Bilibili article editor missing:", this.driver);
        throw publishError("bilibili", "publishErr_editorMissing");
      }
      return;
    }
    await this.driver.goto(this.entryUrl());
    // 上一次投稿成功后,B 站**原地**把编辑页替换成成功页(URL 不变,见 waitResult 注释)。而持久
    // 视图复用同一 WebContents,下一次 goto 到「同一个 URL」常被 SPA abort、不刷新,于是残留成功页
    // ——找不到上传入口,这一次发布就失败。没探到文件输入(成功页/异常态)就先去 about:blank 断开
    // SPA,再回到上传页,强制拿一张干净页面。
    if (!(await this.driver.fileInputAttached(this.s.fileInput, 6_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.entryUrl());
    }
  }

  async checkLogin(): Promise<boolean> {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    if (await this.driver.cssAttached(this.s.fileInput, 6_000)) {
      return true;
    }
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return false;
      }
    }
    return false;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    const attached = await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    if (!attached) {
      throw publishError("bilibili", "publishErr_noUploadEntry");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    const editorReady = await this.driver.cssVisible(this.f.title, UPLOAD_TIMEOUT);
    if (!editorReady) {
      throw publishError("bilibili", "publishErr_editorMissing");
    }

    const donePattern = this.s.uploadDoneTexts.join("|");
    const failedPattern = this.s.uploadFailedTexts.join("|");

    // 编辑表单在**选完文件的瞬间**就渲染出来,视频还在后台传——所以「标题框出现」不是上传完成。
    // 旧实现把 `querySelector(titleInput)` 写进 settle 条件,而上面刚等过它可见,于是第一次轮询
    // (0ms)就返回 true:填完表直接点「立即投稿」时视频往往才传了几秒,B 站不受理,表单原地不动,
    // 再白等 waitResult 五分钟报「未确认发布」。大文件必挂、小文件碰巧传完就成功,表现为随机失败。
    //
    // 真信号有两个,任一即可(不互为前提):完成/失败文案,或「进度标记出现过又消失」。只认文案会
    // 在 B 站改文案时全线挂死;只认进度标记会在它压根不渲染百分比时退化回旧 bug。
    const progressExpr = `/上传中|正在上传|\\d+%/.test(document.body?.innerText || '')`; // i18n-ok
    const started = await this.driver.waitForFunction(progressExpr, 15_000, 500);

    // 「进度标记消失」这一条必须**连续数拍都成立**才算数。B 站的进度区文案是跳变的
    // (百分比、速度、剩余时间轮换),单拍不匹配太常见——按单拍判定会在上传刚开始几秒就误判完成,
    // 然后带着没传完的视频去点投稿,而 B 站此时点投稿是**静默无反应**的,查起来极难。
    const STABLE_POLLS = 3;
    const stateExpr = `(() => {
      const text = document.body?.innerText || '';
      if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return 'failed';
      if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return 'done-text';
      return ${started ? `(${progressExpr}) ? 'in-progress' : 'quiet'` : "'no-signal'"};
    })()`;
    const deadline = Date.now() + UPLOAD_TIMEOUT;
    let quietPolls = 0;
    let settleReason = "";
    let settled = false;
    while (Date.now() < deadline) {
      const state = await this.driver.evaluate<string>(stateExpr).catch(() => "unknown");
      if (state === "failed" || state === "done-text") {
        settleReason = state;
        settled = true;
        break;
      }
      quietPolls = state === "quiet" ? quietPolls + 1 : 0;
      if (quietPolls >= STABLE_POLLS) {
        settleReason = `quiet x${quietPolls}`;
        settled = true;
        break;
      }
      await wait(1_000);
    }
    if (!settled) {
      // 带上进度区文案:B 站改版导致信号失配时,一眼能看出该改哪个 pattern。
      const seen = await this.driver
        .evaluate<string>(`(document.body?.innerText || '').slice(0, 400)`)
        .catch(() => "");
      plog("uploadVideo not settled, page text:", JSON.stringify(seen));
      throw publishError("bilibili", "publishErr_uploadTimeout");
    }
    plog("uploadVideo settled:", { started, reason: settleReason });
    if (
      await this.driver.waitForFunction(
        `new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`,
        500,
        100,
      )
    ) {
      throw publishError("bilibili", "publishErr_uploadFailed");
    }
  }

  async fillTitle(title: string): Promise<void> {
    if (this.isArticle) {
      const value = title.slice(0, 50);
      const inner = this.articleDriver();
      if (!(await inner.cssVisible(this.f.title, ACTION_TIMEOUT))) {
        throw publishError("bilibili", "publishErr_editorMissing");
      }
      await inner.fillField(this.f.title, value);
      const current = await inner.cssValue(this.f.title);
      if (!current?.includes(value)) throw publishError("bilibili", "publishErr_titleRejected");
      return;
    }
    const value = title.slice(0, 80);
    await this.driver.cssVisible(this.f.title, ACTION_TIMEOUT);
    await typeOrFill(this.driver, "bilibili title", this.f.title, value, () =>
      this.driver.fillField(this.f.title, value),
    );
    const current = await this.driver.cssValue(this.f.title);
    if (!current?.includes(value)) {
      throw publishError("bilibili", "publishErr_titleRejected");
    }
  }

  async fillBody(body: string): Promise<void> {
    const value = body.trim();
    if (!value) return;
    const inner = this.articleDriver();
    if (!(await inner.cssVisible(this.f.body, ACTION_TIMEOUT))) {
      await plogPageState("Bilibili article editor missing:", this.driver);
      throw publishError("bilibili", "publishErr_editorMissing");
    }
    await inner.focusAndClearField(this.f.body);
    await inner.insertTextLines(this.f.body, value);
    const shown = await inner.cssValue(this.f.body);
    //: 判定按"字都在"(空白不敏感):tiptap 会按段落重排,行内空白/顺序在它那儿不是问题,
    //: 但**大段缺失**是问题(发布后不能改,少一段就是少一段)。
    const squash = (text: string) => text.replace(/\s+/g, "");
    const want = squash(value).slice(0, 60);
    if (!squash(shown ?? "").includes(want)) {
      await plogPageState("Bilibili article body mismatch:", this.driver);
      throw publishError("bilibili", "publishErr_descriptionRejected");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    //: 文章没有标签那一栏(专栏的话题在编辑器工具栏里,是正文的一部分);标签留给视频那一档。
    if (this.isArticle) return;
    await this.selectCreationStatement();

    const description = stringOption(this.task, "description");
    if (description) {
      if (await this.driver.cssVisible(this.f.body, 5_000)) {
        await typeOrFill(this.driver, "bilibili desc", this.f.body, description, () =>
          this.driver.fillField(this.f.body, description),
        );
      } else {
        await this.driver.fillInputNearText("简介", description).catch(() => false); // i18n-ok
      }
    }

    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const inserted =
        (await this.clickRecommendedTag(normalizedTag)) ||
        (await this.inputTag(normalizedTag)) ||
        (await this.driver
          .fillInputNearText("标签", normalizedTag) // i18n-ok
          .then(async (ok) => {
            if (ok) {
              await this.driver.pressKey("Enter");
              return this.waitForTagChip(normalizedTag);
            }
            return false;
          })
          .catch(() => false)) ||
        (await this.clickAnyRecommendedTag());
      if (!inserted) {
        throw publishError("bilibili", "publishErr_tagRejected", { tag: normalizedTag });
      }
      await wait(200);
    }
    await this.selectRecommendedCover();
  }

  async submit(): Promise<void> {
    if (this.isArticle) {
      await this.submitArticle();
      return;
    }
    // 点之前先体检一遍必填项。B 站在必填项没齐时点「立即投稿」是**静默无反应**的——没有 toast、
    // 没有报错、表单原地不动,和「按钮点不动」长得一模一样。此前的快照只取到表单下半部分,
    // 恰好漏掉了标题/创作声明/分区/封面这些必填项所在的上半部分。
    plog("bilibili submit: readiness", JSON.stringify(await this.submitReadiness()));
    await commitClick({
      what: "bilibili submit",
      attempts: [
        // 可信优先:真实鼠标事件(isTrusted),B 站风控最紧。
        pointerAttempt(`css ${this.s.submitButton}`, () =>
          this.driver.pointerClickCss(this.s.submitButton),
        ),
        // 降级一:完整指针事件序列。「立即投稿」是个 span,处理器很可能挂在 pointerdown/mousedown
        // 上,只发 click 不动 —— 这一条事件齐全又不依赖命中测试,是目前最可能真正生效的一条。
        domAttempt(`full-click ${this.s.submitButton}`, () =>
          this.driver.dispatchFullClickCss(this.s.submitButton),
        ),
        // 降级二:纯 el.click()。按文案找,兼容 B 站换掉 .submit-add 这个类名的情况。
        ...this.s.submitTexts.map((text) =>
          domAttempt(`text ${text}`, () =>
            this.driver.clickByText(text, {
              exact: true,
              selector: "button, [role=button], a, div, span",
            }),
          ),
        ),
      ],
      // 受理判定里不放上传失败文案(uploadFailedTexts):那是 uploadVideo 的职责,而其中的「重新上传」
      // 一旦在某个版本变成常驻按钮,这里就会恒为真、验证等于没做 —— 这类「判定恒为真」的短路在本项目
      // 已经出现过两次(uploadDoneTexts 的 querySelector 兜底、coverSelected 的泛选择器),提前拆掉。
      // (注:曾据此推断线上那次「点击后 1ms 就受理」是它造成的,但实测快照显示 B 站页面上并没有
      //  「重新上传」字样,那次 1ms 受理更可能是点击生效后提交按钮短暂消失所致。见下面 RESULT_WAIT。)
      accepted: pageReacted(this.driver, {
        gone: this.s.submitButton,
        texts: [...PROCESSING_TEXTS, ...this.s.publishDoneTexts],
        urlPattern: MANAGE_URL_PATTERNS.bilibili,
      }),
      snapshot: () => this.submitSnapshot(),
    });
  }

  /**
   * 「点到了却没反应」时的页面现场。
   *
   * 已知不是点击侧的问题:落点自检显示元素可见、未禁用、elementFromPoint 命中的正是它自己,
   * 可信指针点击与 el.click() 都送达过。那答案只可能在页面上,而后台视图截不到图,只能取文本:
   *  - 上传是否真的完成(B 站在上传未完成时点投稿是**静默无反应**的,这是首要怀疑);
   *  - 是否有校验提示/错误浮层(我们的受理判定认不出的那种);
   *  - 提交元素自身的状态(它是个 span,禁用态可能只体现在 class/cursor 上)。
   */
  /**
   * 提交前的必填项体检。
   *
   * B 站的必填项在页面上用红色 `*` 标记(标题 / 创作声明 / 分区),封面另算。任何一项没齐,点
   * 「立即投稿」都是静默无反应 —— 所以这里逐项报出**实际值**,而不是再去猜。
   * `starred` 直接从 DOM 里找带 `*` 的标签、连带取它旁边控件的当前值,这样即使 B 站加了新的必填项
   * 也能一起报出来,不必等我们更新选择器。
   */
  /**
   * 发一篇专栏。
   *
   * **先设「仅自己可见」再发**:B 站专栏**发布后不能编辑**,而自动发布误发公开是收不回来的 ——
   * 先私密、人看过确认没缺段再改公开,代价小得多(和 YouTube 强制先 Private 同一条规矩)。
   */
  /**
   * 专栏发完的收尾。
   *
   * 没有"稿件管理页"那种确定跳转:发布后要么留在原页换成成功提示,要么跳到文章页。判据两条:
   * **地址不再停在编辑页**(`upload/text`)或**出现成功 / 审核中的文案**;失败原文一并认。
   */
  private async waitArticleResult(): Promise<void> {
    const deadline = Date.now() + RESULT_TIMEOUT;
    const failTexts = this.s.publishFailTexts;
    while (Date.now() < deadline) {
      const state = await this.driver
        .evaluate<{ url: string; text: string }>(`(() => ({
          url: location.href,
          text: (document.body?.innerText || '').slice(0, 4000),
        }))()`)
        .catch(() => null);
      if (state) {
        const failed = failTexts.find((one) => state.text.includes(one));
        if (failed) throw publishError("bilibili", "publishErr_rejected", { reason: failed });
        const stillEditing = /upload\/text/.test(state.url);
        const done = this.s.articleDoneTexts.find((one) => state.text.includes(one));
        if (!stillEditing || done) {
          plog("bilibili article waitResult:", { url: state.url, done: done ?? null });
          return;
        }
      }
      await wait(1_000);
    }
    await plogPageState("Bilibili article waitResult failed:", this.driver);
    throw publishError("bilibili", "publishErr_notConfirmed");
  }

  private async submitArticle(): Promise<void> {
    const inner = this.articleDriver();
    //: **先设「仅自己可见」**,再点「发布」。B 站专栏**发布后不能编辑**,自动发布误发公开收不回来 ——
    //: 先私密、人看过确认没缺段再改公开(和 YouTube 强制 Private 同一条规矩)。
    //: 可见范围是两个 `input[type=radio]`,标签文字是「仅自己可见 (将不支持分享、商业推广)」——
    //: 按**前缀**认,再点它自己的 input(点外层 label 有时只改了样式、没改状态)。
    let chosen = false;
    for (let attempt = 0; attempt < 20 && !chosen; attempt += 1) {
      chosen = await inner
        .evaluate<boolean>(`(() => {
          const radios = [...document.querySelectorAll('input[type=radio]')];
          const target = radios.find((input) => {
            const holder = input.closest('label') || input.parentElement;
            return Boolean(holder && (holder.textContent || '').trim().startsWith(${JSON.stringify(this.s.articlePrivateText)}));
          });
          if (!target) return false;
          if (!target.checked) target.click();
          return target.checked;
        })()`)
        .catch(() => false);
      if (!chosen) await wait(200);
    }
    plog("bilibili article visibility (private):", chosen);
    if (!chosen) {
      await plogPageState("Bilibili article visibility not applied:", this.driver);
      throw publishError("bilibili", "publishErr_visibilityNotApplied");
    }
    const clicked = await inner
      .clickByText(this.s.articlePublishText, { exact: true })
      .then(() => true)
      .catch(() => false);
    if (!clicked) {
      await plogPageState("Bilibili article publish button missing:", this.driver);
      throw publishError("bilibili", "publishErr_submitDisabled");
    }
  }

  private async submitReadiness(): Promise<unknown> {
    return this.driver
      .evaluate(
        `(() => {
          const val = (el) => !el ? null
            : (el.value ?? el.getAttribute('value') ?? (el.innerText || '').trim()).slice(0, 60);
          // 带 * 的必填标签 → 取同一行/父块里第一个 input 或下拉的当前值
          const starred = [...document.querySelectorAll('span,label,div')]
            .filter((el) => el.children.length === 0 && (el.textContent || '').trim() === '*')
            .map((star) => {
              const row = star.closest('div');
              const label = ((row && row.innerText) || '').replace(/\\s+/g, ' ').trim().slice(0, 40);
              const field = row ? row.querySelector('input, textarea, [class*="select"], [class*="dropdown"]') : null;
              return { label: label, value: val(field) };
            })
            .slice(0, 8);
          const cover = document.querySelector('.cover');
          return {
            starred: starred,
            title: val(document.querySelector('input[maxlength="80"], input[maxlength="100"]')),
            statement: val(document.querySelector(${JSON.stringify(this.s.statementInput)})),
            coverSelectedCount: document.querySelectorAll(${JSON.stringify(this.s.coverSelected)}).length,
            coverCandidates: document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)}).length,
            coverText: cover ? (cover.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120) : null,
            // 表单上半部分:此前的 textTail 只取尾部,漏掉了必填项区域
            textHead: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 420),
          };
        })()`,
      )
      .catch((error: unknown) => ({ evaluateFailed: String(error).slice(0, 120) }));
  }

  private async submitSnapshot(): Promise<unknown> {
    return this.driver
      .evaluate(
        `(() => {
          const text = (document.body && document.body.innerText) || '';
          const el = document.querySelector(${JSON.stringify(this.s.submitButton)});
          const cs = el ? getComputedStyle(el) : null;
          const pick = (re) => { const m = text.match(re); return m ? m[0] : null; };
          return {
            uploadDone: /上传完成|上传成功/.test(text),
            uploadProgress: pick(/(上传中|正在上传)[^\\n]{0,24}|\\d+%/),
            hint: pick(/[^\\n]{0,40}(请|不能|不可|失败|错误|未|需要|超过|重复)[^\\n]{0,40}/),
            submitOuter: el ? el.outerHTML.slice(0, 160) : null,
            submitCursor: cs ? cs.cursor : null,
            submitPointerEvents: cs ? cs.pointerEvents : null,
            parentClass: el && el.parentElement ? String(el.parentElement.className).slice(0, 80) : null,
            textTail: text.slice(-260),
          };
        })()`,
      )
      .catch((error: unknown) => ({ evaluateFailed: String(error).slice(0, 120) }));
  }

  async waitResult(): Promise<void> {
    if (this.isArticle) {
      await this.waitArticleResult();
      return;
    }
    //: 15 分钟:B 站确认投稿的延迟**方差极大**(实测同一视频 11 秒 / 5 分钟以上都有),
    //: 宁可多等 —— 误报失败的代价是用户重试、重复投稿。
    const outcome = await awaitResult(this.driver, this.c.done, { timeout: 15 * 60 * 1000 });
    plog("waitResult:", outcome);
    if (outcome.status === "success") return;
    if (outcome.status === "failed") {
      throw publishError("bilibili", "publishErr_rejected", { reason: outcome.reason ?? "" });
    }
    await plogPageState("waitResult failed (bilibili):", this.driver);
    throw publishError("bilibili", "publishErr_notConfirmed");
  }

  private async inputTag(tag: string): Promise<boolean> {
    const focused = await this.driver.focusAndClearField(this.f.tags);
    if (!focused) {
      return false;
    }
    await this.driver.type(tag);
    await this.driver.pressKey("Enter");
    return this.waitForTagChip(tag);
  }

  private async selectCreationStatement(): Promise<void> {
    const selected = await this.driver.evaluate<boolean>(`(() => {
      const input = [...document.querySelectorAll(${JSON.stringify(this.s.statementInput)})]
        .find((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
      return Boolean(input && input.value && input.value.trim());
    })()`);
    if (selected) {
      return;
    }

    const optionText = JSON.stringify(this.s.statementOptionText);
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const clickElement = (el) => {
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
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll('.creation-statement-container .bcc-option')]
        .find((el) => (el.innerText || el.textContent || '').trim() === ${optionText});
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);

    if (!clicked) {
      return;
    }

    const accepted = await this.driver.waitForFunction(
      `(() => {
        const input = [...document.querySelectorAll(${JSON.stringify(this.s.statementInput)})]
          .find((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          });
        return Boolean(input && input.value && input.value.trim());
      })()`,
      3_000,
      250,
    );
    if (!accepted) {
      throw publishError("bilibili", "publishErr_declarationNotSelected");
    }
  }

  private async clickRecommendedTag(tag: string): Promise<boolean> {
    const expected = JSON.stringify(tag);
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
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
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll(${JSON.stringify(this.s.recommendedTag)})]
        .find((el) => visible(el) && (el.innerText || el.textContent || '').trim() === ${expected});
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);
    if (!clicked) {
      return false;
    }
    return this.waitForTagChip(tag);
  }

  private async clickAnyRecommendedTag(): Promise<boolean> {
    const before = await this.driver.evaluate<number>(
      `document.querySelectorAll('#tag-container .label-item-v2-content').length`,
    );
    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
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
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const option = [...document.querySelectorAll(${JSON.stringify(this.s.recommendedTag)})]
        .find((el) => visible(el) && !/(^|\\s)hot-tag-container-selected(\\s|$)/.test(String(el.className || '')));
      if (!option) return false;
      clickElement(option);
      return true;
    })()`);
    if (!clicked) {
      return false;
    }
    return this.driver.waitForFunction(
      `document.querySelectorAll('#tag-container .label-item-v2-content').length > ${before}`,
      3_000,
      250,
    );
  }

  private async selectRecommendedCover(): Promise<void> {
    // 每条分支都要留痕。此前两处静默 return 没有任何日志,于是「封面到底选上了没」在事后完全不可知
    // ——而封面是 B 站的必填项,没选就点「立即投稿」是**静默无反应**的。
    // 另外 coverSelected 的第一个候选 `.cover .cover-item` 很泛:它若只是容器而非「已选中」标记,
    // alreadySelected 就恒为真、这个方法直接返回,封面永远不会被选(与 uploadDoneTexts 那处短路同类)。
    // 所以这里把两个选择器各自的命中数都记下来,一眼能看出是不是这个情况。
    const counts = await this.driver
      .evaluate<{ selected: number; candidates: number }>(
        `({
          selected: document.querySelectorAll(${JSON.stringify(this.s.coverSelected)}).length,
          candidates: document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)}).length,
        })`,
      )
      .catch(() => ({ selected: -1, candidates: -1 }));
    const alreadySelected = await this.driver.cssVisible(this.s.coverSelected, 2_000);
    plog("selectRecommendedCover:", { ...counts, alreadySelected });
    if (alreadySelected) {
      return;
    }

    const clicked = await this.driver.evaluate<boolean>(`(() => {
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const clickElement = (el) => {
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
        for (const type of ['pointerdown', 'mousedown', 'mouseup', 'pointerup', 'click']) {
          const EventCtor = type.startsWith('pointer') && window.PointerEvent
            ? window.PointerEvent
            : window.MouseEvent;
          el.dispatchEvent(new EventCtor(type, init));
        }
        if (typeof el.click === 'function') el.click();
      };
      const cover = [...document.querySelectorAll(${JSON.stringify(this.s.coverRecommendation)})]
        .find(visible);
      if (!cover) return false;
      clickElement(cover);
      return true;
    })()`);

    if (!clicked) {
      plog("selectRecommendedCover: no clickable candidate cover, skipping");
      return;
    }

    const selected = await this.driver.cssVisible(this.s.coverSelected, 5_000);
    if (!selected) {
      throw publishError("bilibili", "publishErr_coverNotSelected");
    }
    // 选中 ≠ 处理完:B 站选完封面还要上传/裁切一下,期间点投稿同样静默无反应。等它安静下来。
    const quiet = await this.driver.waitForFunction(
      `!/上传中|处理中|裁剪中|\\d+%/.test(document.querySelector('.cover')?.innerText || '')`, // i18n-ok
      15_000,
      500,
    );
    plog("selectRecommendedCover: selected", { coverQuiet: quiet });
  }

  private async waitForTagChip(tag: string): Promise<boolean> {
    const expected = JSON.stringify(tag);
    return this.driver.waitForFunction(
      `(() => {
        const texts = [
          ...document.querySelectorAll('#tag-container .label-item-v2-content, #tag-container [class*="label"][class*="content"], #tag-container [class*="tag-pre"] *')
        ]
          .map((el) => (el.textContent || '').trim())
          .filter(Boolean);
        return texts.some((text) => text === ${expected});
      })()`,
      3_000,
      250,
    );
  }
}


/**
 * TikTok。**和抖音是两个平台、两套账号** —— 后端的别名表里曾经把 "tiktok" 指向 douyin,
 * 说"发到 tiktok"会静默发进抖音;接进来时那条已经拆掉。
 *
 * 界面语言跟账号走,所以判定尽量走结构(`data-e2e`)而不是文案;文案作为兜底且中英各一份。
 *
 * **境内需要可用的出站代理** —— 连不上时表现为登录页打不开,而不是"登录失败";这一点写进了
 * 平台说明,免得用户在"为什么一直要我登录"上耗时间。
 */

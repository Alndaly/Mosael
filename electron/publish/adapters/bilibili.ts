import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { ACTION_TIMEOUT, UPLOAD_TIMEOUT, normalizeTag, stringOption, typeOrFill, wait } from "./shared";
import { MANAGE_URL_PATTERNS, SELECTORS } from "../selectors";
import { PROCESSING_TEXTS, commitClick, domAttempt, pageReacted, pointerAttempt } from "../clickChain";
import { plog } from "../log";

export class BilibiliAdapter implements PublishAdapter {
  private readonly s = SELECTORS.bilibili;

  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.goto(this.s.uploadUrl);
    // 上一次投稿成功后,B 站**原地**把编辑页替换成成功页(URL 不变,见 waitResult 注释)。而持久
    // 视图复用同一 WebContents,下一次 goto 到「同一个 URL」常被 SPA abort、不刷新,于是残留成功页
    // ——找不到上传入口,这一次发布就失败。没探到文件输入(成功页/异常态)就先去 about:blank 断开
    // SPA,再回到上传页,强制拿一张干净页面。
    if (!(await this.driver.fileInputAttached(this.s.fileInput, 6_000))) {
      await this.driver.goto("about:blank");
      await this.driver.goto(this.s.uploadUrl);
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
      throw new Error("B站未找到上传入口。");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);

    const editorReady = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!editorReady) {
      throw new Error("B站上传后编辑器未出现(找不到标题输入框)。");
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
      throw new Error("B站上传超时,未在时限内完成。");
    }
    plog("uploadVideo settled:", { started, reason: settleReason });
    if (
      await this.driver.waitForFunction(
        `new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`,
        500,
        100,
      )
    ) {
      throw new Error("B站报告视频上传失败。");
    }
  }

  async fillTitle(title: string): Promise<void> {
    const value = title.slice(0, 80);
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await typeOrFill(this.driver, "bilibili title", this.s.titleInput, value, () =>
      this.driver.fillField(this.s.titleInput, value),
    );
    const current = await this.driver.cssValue(this.s.titleInput);
    if (!current?.includes(value)) {
      throw new Error("B站标题输入框没有接受填入的内容。");
    }
  }

  async fillTags(tags: string[]): Promise<void> {
    await this.selectCreationStatement();

    const description = stringOption(this.task, "description");
    if (description) {
      if (await this.driver.cssVisible(this.s.descEditor, 5_000)) {
        await typeOrFill(this.driver, "bilibili desc", this.s.descEditor, description, () =>
          this.driver.fillField(this.s.descEditor, description),
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
        throw new Error(`Bilibili tag was not accepted: #${normalizedTag}`);
      }
      await wait(200);
    }
    await this.selectRecommendedCover();
  }

  async submit(): Promise<void> {
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
    // B 站投稿成功**不跳转 URL**:原地把编辑页替换成成功页(「稿件投递成功 / 查看进度 / 再投一个」)。
    // 旧实现先 waitForUrl(稿件管理页) 干等满 RESULT_TIMEOUT 再看文本——URL 永远不变,于是每次成功都要
    // 白卡约 2 分钟,慢一点还会误报「未确认发布」。改为单循环并发判断:成功页文案(强信号)/ 老流程
    // 跳转(兜底)/ 明确失败提示 任一出现即结束。提交处理可达 ~2 分钟,给足 5 分钟余量。
    //
    // 成功判定必须**同时**满足「出现成功文案」和「编辑表单已消失」。只认文案会误报:实测有一次
    // 自动化的点击根本没落到按钮上(后台视图视口 0×0,见 PageDriver.setMetricsOverride),用户
    // 自己手动点了投稿,页面弹出「投稿成功」——于是这里把**别人完成的发布**记成了自己的成果,
    // 上报 success、发通知、工作流收工。「什么都没发却报成功」是最坏的失败模式,宁可多等到超时。
    // 编辑表单还在就说明没投出去:B 站成功后是原地把编辑页换成成功页,提交按钮不会留着。
    // 15 分钟,不是 5 分钟。B 站确认投稿的延迟**方差极大**,实测同一个视频两次:
    //   ・一次点击后 11 秒就出现成功页(formGone + 成功文案);
    //   ・另一次点击已被受理(提交按钮随即消失),却过了 5 分钟还没翻成功页 —— 旧窗口到点就报
    //     「未确认发布」,而稿件其实**已经投成了**;用户于是重试,重试又再投一稿。
    // 差别应该来自后台的上传→转码(360P/480P/720P/1080P 逐档)→审核要走多久。宁可多等,
    // 也不能把成功报成失败:误报失败的代价是重复投稿,而多等只是多占一会儿账号槽。
    const RESULT_WAIT = 15 * 60 * 1000;
    const probe = `(() => {
      const t = (document.body && document.body.innerText) || '';
      const formGone = !document.querySelector(${JSON.stringify(this.s.submitButton)});
      const success = /稿件投递成功|投稿成功|稿件投稿成功|投稿完成/.test(t) && formGone;
      const redirected = /upload-manager|content-manager|article/.test(location.href);
      const m = t.match(/投稿失败|提交失败|发布失败|标题重复/);
      return { ok: success || redirected, fail: m ? m[0] : null, formGone: formGone, url: location.href };
    })()`;
    const settled = await this.driver.waitForFunction(
      `(() => { const s = ${probe}; return s.ok || s.fail; })()`,
      RESULT_WAIT,
      1_000,
    );
    const state = await this.driver.evaluate<{
      ok: boolean;
      fail: string | null;
      formGone: boolean;
      url: string;
    }>(probe);
    plog("waitResult:", { settled, ...state });
    if (state.ok) return;
    if (state.fail) throw new Error(`B 站投稿被拒:${state.fail}`);
    throw new Error("B站未确认投稿(没有出现成功页,也没有跳转到稿件管理)。");
  }

  private async inputTag(tag: string): Promise<boolean> {
    const focused = await this.driver.focusAndClearField(this.s.tagInput);
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
      throw new Error("B站创作声明未能选中。");
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
      plog("selectRecommendedCover: 没有可点的候选封面,跳过");
      return;
    }

    const selected = await this.driver.cssVisible(this.s.coverSelected, 5_000);
    if (!selected) {
      throw new Error("B站推荐封面未能选中。");
    }
    // 选中 ≠ 处理完:B 站选完封面还要上传/裁切一下,期间点投稿同样静默无反应。等它安静下来。
    const quiet = await this.driver.waitForFunction(
      `!/上传中|处理中|裁剪中|\\d+%/.test(document.querySelector('.cover')?.innerText || '')`, // i18n-ok
      15_000,
      500,
    );
    plog("selectRecommendedCover: 已选中", { coverQuiet: quiet });
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

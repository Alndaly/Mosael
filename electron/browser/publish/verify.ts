/**
 * **判定原语**:这一步做成了没有。
 *
 * 发布自动化里最难查的不是"点不中",而是"点中了、也填了,却判成没成功"。2026-10-23 一天里
 * 这类误判出现了四次,而每次各适配器都自己写一遍 `waitForFunction`(小红书 8 处、B站 7 处、
 * 抖音 5 处),于是同一件事有 N 种口径:
 *
 * - 富文本把 `1. …` 变成有序列表、换行位置变了 → 整段 `includes` 永远不成立;
 * - 编辑器里混着上一轮的草稿 → 只判"包含"就放过了错内容;
 * - 成功提示挂在 shadow DOM 里 → `document.body.innerText` 一个字都读不到;
 * - 平台地址里其实写着 `published=true` → 没人看地址。
 *
 * 这里把它们收成三条原语。口径**按可靠性排**:能看平台自己给的信号(地址 / 字数计数)就不猜文案。
 */
import type { PageDriver } from "../page/pageDriver";

/** 去掉所有空白与零宽字符:富文本改写的只是排版,不是内容。 */
export function squash(text: string | null | undefined): string {
  return String(text ?? "")
    .replace(/\u200b/g, "")
    .replace(/\s+/g, "");
}

/** 读一个编辑器里眼下有什么字(取选择器命中的**最长**那个:先命中的常是空占位节点)。 */
export async function editorText(driver: PageDriver, selector: string): Promise<string> {
  return driver
    .evaluate<string>(`(() => {
      const editors = [...document.querySelectorAll(${JSON.stringify(selector)})];
      const longest = editors
        .map((one) => one.innerText || one.textContent || "")
        .sort((a, b) => b.length - a.length)[0] || "";
      return longest;
    })()`)
    .catch(() => "");
}

/** 整页可见文字(**含 shadow root**:平台的提示与自定义元素常常在那儿)。 */
export const DEEP_TEXT_EXPR = `(() => {
  const seen = new Set();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  const walk = (root) => {
    if (!root || seen.has(root)) return '';
    seen.add(root);
    let text = root instanceof Document ? (root.body?.innerText || '') : '';
    for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
      if (el.shadowRoot) text += '\\n' + walk(el.shadowRoot);
      else if (!(root instanceof Document) && visible(el)) text += '\\n' + (el.innerText || el.textContent || '');
    }
    return text;
  };
  return walk(document);
})()`;

/**
 * 这段字进编辑器了吗。
 *
 * `allowExtra`:允许多出来的字(默认 15%)。默认**不允许太多** —— 编辑器里混着上一轮草稿时,
 * 只判"包含"会放过一条内容不对的发布。要允许旧内容(比如标签追加),调用方自己给大一点。
 */
export async function textEntered(
  driver: PageDriver,
  selector: string,
  value: string,
  options: { allowExtra?: number; counter?: RegExp } = {},
): Promise<boolean> {
  const want = squash(value);
  if (!want) return true;
  const longest = squash(await editorText(driver, selector));
  if (longest.includes(want)) {
    const allowance = options.allowExtra ?? 0.15;
    return longest.length <= Math.ceil(want.length * (1 + allowance));
  }
  //: 平台自己也有字数计数(0 / 1000):富文本改写标点/列表时,长度对得上就够了。
  if (!options.counter) return false;
  const counted = await driver
    .evaluate<string>(`(() => {
      const match = (document.body?.innerText || '').match(${JSON.stringify(options.counter.source)});
      return match ? match[1] : '';
    })()`)
    .catch(() => "");
  const shown = Number(counted);
  return Number.isFinite(shown) && shown > 0 && shown >= Math.floor(want.length * 0.6);
}

/** 页面就绪:某个选择器可见(默认再给它一点时间)。 */
export async function pageReady(
  driver: PageDriver,
  selector: string,
  timeout = 30_000,
): Promise<boolean> {
  return driver.cssVisible(selector, timeout).catch(() => false);
}

/** 发布成功的信号。**按可靠性排**:地址 > 平台接口 > 文案。 */
export interface SuccessSignals {
  /** 地址命中其中一个就算成功(平台自己写的"已发布",比任何文案都硬)。 */
  urls?: readonly (RegExp | ((url: string) => boolean))[];
  /** 页面文案(**含 shadow root**)。 */
  texts?: readonly string[];
  /**
   * **成功的前提**:这个选择器必须已经不在页面上。
   *
   * B 站 / TikTok / X 发完之后都是**原地**把编辑页换成结果页(地址不变或换到列表),
   * 于是"成功文案"很容易被页面上早就存在的词命中(列表列名、导航项)。判据里加一道
   * "编辑表单没了" —— 否则会把**别人完成的发布**、或者一次根本没点中按钮的操作记成成功。
   */
  formGone?: string;
  /** 明确的失败提示:出现即失败(平台的"投稿失败 / 标题重复"这类原文)。 */
  failTexts?: readonly string[];
}

/** 判断这段地址算不算成功 —— 正则与函数两种判据在这里统一。**在 Node 里做**,不塞进页面脚本。 */
export function urlMatches(url: string, urls: SuccessSignals["urls"] = []): boolean {
  return urls.some((one) => (one instanceof RegExp ? one.test(url) : one(url)));
}

/** 整页可见文字(**含 shadow root**)。 */
export async function deepText(driver: PageDriver): Promise<string> {
  return driver.evaluate<string>(DEEP_TEXT_EXPR).catch(() => "");
}

/** 成功了吗(看一次,不等) —— 由调用方控制轮询节奏。**地址在 Node 里比,文案在页面里读**。 */
export async function successVisible(driver: PageDriver, signals: SuccessSignals): Promise<boolean> {
  //: ① **闸门先过**:编辑表单还在 = 还什么都没发出去,文案再像也不能算成功(B站 / TikTok / X 的教训)。
  if (signals.formGone) {
    const stillThere = await driver.cssVisible(signals.formGone, 300).catch(() => false);
    if (stillThere) return false;
  }
  //: ② 地址(平台自己写的落地页 / 已发布参数)—— 最硬。
  const url = driver.url();
  if (url && urlMatches(url, signals.urls)) return true;
  //: ③ 文案(含 shadow root)。没有文案信号的平台到这里就是 false。
  const texts = signals.texts ?? [];
  if (!texts.length) return false;
  const body = await deepText(driver);
  return texts.some((one) => body.includes(one));
}

/** 等成功信号出现。 */
export async function waitForSuccess(
  driver: PageDriver,
  signals: SuccessSignals,
  options: { timeout?: number; poll?: number } = {},
): Promise<boolean> {
  const deadline = Date.now() + (options.timeout ?? 120_000);
  const poll = options.poll ?? 600;
  while (Date.now() < deadline) {
    if (await successVisible(driver, signals)) return true;
    await new Promise((resolve) => setTimeout(resolve, poll));
  }
  return false;
}

/**
 * 多行正文进去了吗 —— **按行、按顺序**。
 *
 * 为什么要按行:富文本会把 `1. …` 变成有序列表、换行位置也会变,整段比会误判;而只判"包含"
 * 又会放过被拆散重排的正文(2026-10-23 真机:抖音把几行重排了,`got` 里字都在,顺序不对)。
 * 逐行在"最长的那份编辑器文字"里**从左到右**找,顺序错就是没进去。
 */
export async function linesEntered(
  driver: PageDriver,
  selector: string,
  value: string,
  options: { allowExtra?: number; counter?: RegExp } = {},
): Promise<{ ok: boolean; matched: number; total: number }> {
  const lines = value
    .split(/\r?\n/)
    .map((one) => squash(one))
    .filter(Boolean);
  const shown = squash(await editorText(driver, selector));
  if (lines.length === 0) return { ok: true, matched: 0, total: 0 };
  let cursor = -1;
  let matched = 0;
  for (const line of lines) {
    const at = shown.indexOf(line, cursor + 1);
    if (at > cursor) {
      matched += 1;
      cursor = at;
    }
  }
  const allowExtra = options.allowExtra ?? 0.15;
  const allIn = matched === lines.length;
  const notTooLong = shown.length <= Math.ceil(squash(value).length * (1 + allowExtra));
  if (allIn && notTooLong) return { ok: true, matched, total: lines.length };
  if (options.counter) {
    //: 平台自己的字数计数兜一层:富文本改标点 / 列表时长度对得上就够了。
    const counted = await driver
      .evaluate<string>(`(() => {
        const match = (document.body?.innerText || '').match(${JSON.stringify(options.counter.source)});
        return match ? match[1] : '';
      })()`)
      .catch(() => "");
    const shownCount = Number(counted);
    if (Number.isFinite(shownCount) && shownCount >= Math.floor(squash(value).length * 0.6)) {
      return { ok: true, matched, total: lines.length };
    }
  }
  return { ok: false, matched, total: lines.length };
}

/**
 * 等结果:**成功、失败、超时**三种,一次说清。
 *
 * 各平台此前各写一套"循环 + 失败文案 + 跳转兜底",于是同一件事有五种口径(而且 B 站那种
 * 延迟方差极大的平台还得单独调超时)。这里统一:先看失败提示,再过 `formGone` 闸,再看成功信号。
 */
export async function awaitResult(
  driver: PageDriver,
  signals: SuccessSignals,
  options: { timeout?: number; poll?: number } = {},
): Promise<{ status: "success" | "failed" | "timeout"; reason?: string }> {
  const deadline = Date.now() + (options.timeout ?? 120_000);
  const poll = options.poll ?? 1_000;
  while (Date.now() < deadline) {
    const failTexts = signals.failTexts ?? [];
    if (failTexts.length) {
      const body = await deepText(driver);
      const hit = failTexts.find((one) => body.includes(one));
      if (hit) return { status: "failed", reason: hit };
    }
    if (await successVisible(driver, signals)) return { status: "success" };
    await new Promise((resolve) => setTimeout(resolve, poll));
  }
  return { status: "timeout" };
}

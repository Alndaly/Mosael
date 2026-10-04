import { Script } from "node:vm";

import type { PageDriver } from "./pageDriver";
import { ActionAbortedError, ElementMissingError, EvaluateTimeoutError } from "./errors";
import { t } from "../i18n.cjs";

export interface ActionOutcome {
  value?: unknown; // extract/evaluate 的返回值;回给后端时包成 { value }
  lastUrl?: string;
}

const s = (v: unknown): string => (v == null ? "" : String(v));

/** 放进错误里的短版本。选择器和网址都可能很长,糊满一屏之后反而看不清关键那几个字。 */
const brief = (v: string, max = 80): string => (v.length <= max ? v : `${v.slice(0, max - 1)}…`);

/**
 * 点击 / 输入之前等元素出现多久(毫秒),调用方没说就用它。页面刚导航完、或者点了一下之后才挂出来的
 * 按钮,很少在第一拍就在 —— 此前找不到就立刻报错,工作流里得在每个点击前面垫一个「等待」节点。
 */
export const ELEMENT_WAIT_MS = 5_000;
const ELEMENT_POLL_MS = 250;

/**
 * 导航被放行的那一种失败:ERR_ABORTED(-3)。单页应用在加载途中自己改地址、重定向到登录页时,
 * 最初那次加载就是这样收场的 —— 页面其实到了。别的失败(域名解析不了、连不上、证书错)都是没打开。
 */
const ERR_ABORTED = -3;

/**
 * 在短等待里反复试一个「找不到元素就抛 ElementMissingError」的动作。等到了就照常返回;
 * 等满还找不到,报一句按界面语言翻好的话(此前是 `clickCss: element not found: …` 这句英文)。
 */
async function untilFound(
  driver: PageDriver,
  waitMs: number,
  what: string,
  attempt: () => Promise<void>,
): Promise<void> {
  const deadline = Date.now() + Math.max(0, waitMs);
  for (;;) {
    try {
      await attempt();
      return;
    } catch (error) {
      if (!(error instanceof ElementMissingError)) throw error;
      if (Date.now() >= deadline) {
        throw new Error(
          t("browserErr_elementMissing", {
            target: brief(what),
            seconds: (Math.max(0, waitMs) / 1000).toFixed(1),
            url: brief(driver.url(), 120),
          }),
        );
      }
    }
    await new Promise((resolve) => setTimeout(resolve, Math.min(ELEMENT_POLL_MS, Math.max(0, deadline - Date.now()))));
  }
}

const waitMsOf = (args: Record<string, unknown>): number => {
  const raw = Number(args.wait_ms);
  return Number.isFinite(raw) && raw >= 0 ? raw : ELEMENT_WAIT_MS;
};

/**
 * 「执行脚本」的脚本外面包一层,把 `input` 交进去。值只作为 **JSON 数据**进脚本,从不拼进代码 ——
 * 此前工作流把 `{{上游.输出}}` 直接插进表达式,上游交来一段带引号的文字就能改写整段脚本。
 *
 * 包成块语句而不是箭头函数:块的完成值就是最后一条语句的值,和不包时一样 —— 写了好几句、最后一句
 * 是结果的脚本照样能用;`const` 也只活在这一块里,同一页上(循环里)跑第二次不会撞「已声明」。
 *
 * `input` 由 `with` 一个**无原型**的对象交进去,而不是在外层 `const input`:`input` 是网页脚本里最常见的
 * 变量名之一(`const input = document.querySelector("input")`),此前包成 `const` 之后,自己声明了 `input`
 * 的老脚本(const / let / var / function 哪种都算)整段 SyntaxError。`with` 的作用域在脚本自己的声明**外面**:
 * 脚本自己声明了就用它自己的(块里的 const / let / class / function 遮住它,`var input = …` 的赋值也
 * 落到这一格上,读回来就是它刚写的),没声明才读到交进来的数据。只有一处看得出差别:只写 `var input;`
 * 不赋值,读到的是交进来的数据而不是 undefined。无原型是为了只拦 `input` 这一个名字 ——
 * 普通对象会把 `toString`、`constructor` 这些全局名字也拦成 Object.prototype 上的那几个。
 *
 * 没给入参(空对象)就不引入 `input` 这个名字,只包块;`undefined`(智能体直接跑的脚本)原样执行。
 */
export function scriptWithInput(expression: string, input: unknown): string {
  if (input === undefined) return expression;
  const given = input !== null && typeof input === "object" && Object.keys(input).length > 0;
  if (!given) return `{\n${expression}\n}`;
  return `with (Object.assign(Object.create(null), { input: ${JSON.stringify(input)} })) {\n${expression}\n}`;
}

/**
 * 「执行脚本」出错时说出**脚本自己的那句话**。
 *
 * Electron 的 executeJavaScript 对同步抛错、语法错只回一句「Script failed to execute…去看渲染进程的控制台」
 * (实测,electron 44)—— 用户看不到那个控制台,节点上也就只剩一句英文。脚本交回的 promise 被拒时它倒是把
 * 原话带回来。所以:同步抛的错包一层 try,改成带原话的被拒 promise;语法错在交给页面之前先在主进程编译一遍
 * (同一个 V8,语法判据一样),见 `checkScriptSyntax`。
 *
 * try 块的完成值就是块里最后一条语句的值,包了之后「最后一句是结果」照旧成立。
 */
export function scriptReportingErrors(script: string): string {
  return `try {\n${script}\n} catch (__mosaelScriptError) {\n  Promise.reject(new Error(String(__mosaelScriptError)));\n}`;
}

/** 语法不通:按界面语言说清是语法错误、错在哪(V8 的原话)。不碰页面。 */
function checkScriptSyntax(script: string): void {
  try {
    new Script(script, { filename: "script.js" });
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error(t("browserErr_scriptSyntax", { detail: error.message }));
    throw error;
  }
}

async function runScript(driver: PageDriver, args: Record<string, unknown>): Promise<unknown> {
  //: 调用方(工作流节点)可以为自己的长脚本声明预算;不带就按缺省 20s。
  const budget = Number(args.timeout_ms) || undefined;
  const script = scriptWithInput(s(args.expression), args.input);
  checkScriptSyntax(script);
  try {
    return await driver.evaluate(scriptReportingErrors(script), budget);
  } catch (error) {
    if (error instanceof ActionAbortedError) throw error;
    if (error instanceof EvaluateTimeoutError) {
      throw new Error(t("browserErr_scriptTimeout", { seconds: (error.budgetMs / 1000).toFixed(1) }));
    }
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(t("browserErr_scriptThrew", { detail: brief(detail, 300) }));
  }
}

/**
 * 把一个后端动作分派到 PageDriver:navigate/click/input/upload/press_key/extract/evaluate/wait/
 * scroll/screenshot。upload 经 CDP setFileInputFiles 塞文件(与发布上传同一套 driver.setFiles)。
 */
export async function executeBrowserAction(
  driver: PageDriver,
  action: string,
  args: Record<string, unknown>,
): Promise<ActionOutcome> {
  switch (action) {
    case "navigate": {
      const url = s(args.url);
      const result = await driver.goto(url);
      // 没打开就说没打开:此前 loadURL 失败只记一行日志,节点照样「成功」,下一步在一张错误页上找元素。
      if (result.outcome === "rejected" && result.errno !== ERR_ABORTED) {
        throw new Error(t("browserErr_navigateFailed", { code: result.code, url: brief(url, 120) }));
      }
      const landed = driver.url();
      if (landed.startsWith("chrome-error://")) {
        throw new Error(t("browserErr_navigateFailed", { code: "chrome-error", url: brief(url, 120) }));
      }
      return { lastUrl: landed };
    }
    case "click": {
      const waitMs = waitMsOf(args);
      if (args.selector) {
        const selector = s(args.selector);
        await untilFound(driver, waitMs, selector, () => driver.clickCss(selector));
      } else if (args.text) {
        const text = s(args.text);
        await untilFound(driver, waitMs, text, () => driver.clickByText(text, { exact: Boolean(args.exact) }));
      } else throw new Error(t("browserErr_clickNeedsTarget"));
      return { lastUrl: driver.url() };
    }
    case "input": {
      const selector = s(args.selector);
      await untilFound(driver, waitMsOf(args), selector, () => driver.fillField(selector, s(args.value)));
      return { lastUrl: driver.url() };
    }
    case "upload": {
      const path = s(args.path);
      if (!path) throw new Error(t("browserErr_uploadNeedsPath"));
      //: 节点上写了选择器就**只认它**:页面上有视频框和封面框时,退回「随便哪个文件框」会把文件塞错地方而节点照报成功。
      //: 没写才是「页面上的文件框」(含 shadow DOM 里的)。
      const lookup = { exact: Boolean(s(args.selector)) };
      const selector = s(args.selector) || 'input[type="file"]';
      const timeout = Number(args.timeout_ms) || 15_000;
      // 文件输入框常在点了「上传」后才挂载:先等它出现,再经 CDP setFileInputFiles 塞文件(不弹系统框)。
      const ok = await driver.fileInputAttached(selector, timeout, lookup);
      if (!ok) throw new Error(t("browserErr_fileInputMissing", { selector }));
      await driver.setFiles(selector, path, lookup);
      return { lastUrl: driver.url() };
    }
    case "press_key": {
      await driver.pressKey(s(args.key) as "Enter" | "Escape" | "Space" | "Tab");
      return { lastUrl: driver.url() };
    }
    case "extract": {
      const selector = s(args.selector);
      const attribute = args.attribute ? s(args.attribute) : null;
      const all = Boolean(args.all);
      // 找不到时回 undefined(和「找到了、值是 null」分开):选择器写错 / 页面改版时说出来,
      // 而不是交出一个空值让下游安静地拿着它往下跑。确实可能没有的,由调用方打开 allow_missing。
      const expr = `(() => {
        const els = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
        if (!els.length) return { missing: true };
        const get = (el) => ${attribute ? `el.getAttribute(${JSON.stringify(attribute)})` : "((el.innerText || el.textContent || '').trim())"};
        return { value: ${all ? "els.map(get)" : "get(els[0])"} };
      })()`;
      const found = await driver.evaluate<{ missing?: boolean; value?: unknown }>(expr);
      if (found?.missing) {
        if (!args.allow_missing) {
          throw new Error(t("browserErr_extractMissing", { selector: brief(selector), url: brief(driver.url(), 120) }));
        }
        return { value: all ? [] : null, lastUrl: driver.url() };
      }
      return { value: found?.value ?? null, lastUrl: driver.url() };
    }
    case "evaluate": {
      return { value: await runScript(driver, args), lastUrl: driver.url() };
    }
    case "wait": {
      const timeout = Number(args.timeout_ms) || 15_000;
      let ok = false;
      if (args.selector) {
        ok = Boolean(args.gone)
          ? await driver.waitForFunction(`!document.querySelector(${JSON.stringify(s(args.selector))})`, timeout, 300)
          : await driver.cssVisible(s(args.selector), timeout);
      } else if (args.url_contains) {
        const needle = s(args.url_contains);
        ok = await driver.waitForUrl((u) => u.includes(needle), timeout);
      } else if (args.text) {
        ok = await driver.waitForFunction(`(document.body?.innerText||'').includes(${JSON.stringify(s(args.text))})`, timeout, 300);
      } else {
        throw new Error(t("browserErr_waitNeedsTarget"));
      }
      if (!ok) {
        // 「等待超时」四个字是**站点改版之后最常撞见的那条错误**,而它当时什么都不说:等的哪个
        // 选择器、等了多久、页面那会儿停在哪一页。这三样就在手边,不带上就得让人回去翻节点配置
        // 再猜一遍。带上之后一眼能分出「选择器写错了」和「页面根本没跳过去」。
        const waited = (timeout / 1000).toFixed(1);
        const what = args.selector
          ? t(args.gone ? "browserErr_waitGone" : "browserErr_waitVisible", { target: brief(s(args.selector)) })
          : args.url_contains
            ? t("browserErr_waitUrl", { target: brief(s(args.url_contains)) })
            : t("browserErr_waitText", { target: brief(s(args.text)) });
        throw new Error(t("browserErr_waitTimeout", { seconds: waited, what, url: brief(driver.url(), 120) }));
      }
      return { lastUrl: driver.url() };
    }
    case "scroll": {
      if (args.selector) {
        const selector = s(args.selector);
        const found = await driver.evaluate<boolean>(`(() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return false;
          el.scrollIntoView({ block: 'center' });
          return true;
        })()`);
        if (!found && !args.allow_missing) {
          throw new Error(t("browserErr_scrollMissing", { selector: brief(selector), url: brief(driver.url(), 120) }));
        }
      } else {
        await driver.evaluate(`window.scrollBy(0, ${Number(args.dy) || 600})`);
      }
      return { lastUrl: driver.url() };
    }
    case "cookies": {
      // 把这个分区的登录态借给外部工具(yt-dlp 下载需要登录的视频)。返回 Netscape 行,
      // 后端只负责写文件 —— 格式转换在看得见 Chromium cookie 对象的这一侧做。
      return { value: await driver.cookieLines() };
    }
    case "screenshot": {
      const dataUrl = await driver.captureBase64();
      return { value: dataUrl, lastUrl: driver.url() };
    }
    default:
      throw new Error(t("browserErr_unknownAction", { action }));
  }
}

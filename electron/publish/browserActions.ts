import type { PageDriver } from "./pageDriver";
import { ElementMissingError } from "./errors";
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
      const selector = s(args.selector) || 'input[type="file"]';
      const timeout = Number(args.timeout_ms) || 15_000;
      // 文件输入框常在点了「上传」后才挂载:先等它出现,再经 CDP setFileInputFiles 塞文件(不弹系统框)。
      const ok = await driver.fileInputAttached(selector, timeout);
      if (!ok) throw new Error(t("browserErr_fileInputMissing", { selector }));
      await driver.setFiles(selector, path);
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
      return { value: await driver.evaluate(s(args.expression)), lastUrl: driver.url() };
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

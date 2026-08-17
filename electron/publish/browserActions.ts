import type { PageDriver } from "./pageDriver";

export interface ActionOutcome {
  value?: unknown; // extract/evaluate 的返回值;回给后端时包成 { value }
  lastUrl?: string;
}

const s = (v: unknown): string => (v == null ? "" : String(v));

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
      await driver.goto(s(args.url));
      return { lastUrl: driver.url() };
    }
    case "click": {
      if (args.selector) await driver.clickCss(s(args.selector));
      else if (args.text) await driver.clickByText(s(args.text), { exact: Boolean(args.exact) });
      else throw new Error("click 需要 selector 或 text");
      return { lastUrl: driver.url() };
    }
    case "input": {
      await driver.fillField(s(args.selector), s(args.value));
      return { lastUrl: driver.url() };
    }
    case "upload": {
      const path = s(args.path);
      if (!path) throw new Error("upload 需要文件路径");
      const selector = s(args.selector) || 'input[type="file"]';
      const timeout = Number(args.timeout_ms) || 15_000;
      // 文件输入框常在点了「上传」后才挂载:先等它出现,再经 CDP setFileInputFiles 塞文件(不弹系统框)。
      const ok = await driver.fileInputAttached(selector, timeout);
      if (!ok) throw new Error(`upload: 文件输入框未出现: ${selector}`);
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
      const expr = `(() => {
        const els = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
        const get = (el) => ${attribute ? `el.getAttribute(${JSON.stringify(attribute)})` : "((el.innerText || el.textContent || '').trim())"};
        return ${all ? "els.map(get)" : "(els[0] ? get(els[0]) : null)"};
      })()`;
      return { value: await driver.evaluate(expr), lastUrl: driver.url() };
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
        throw new Error("wait 需要 selector / url_contains / text 之一");
      }
      if (!ok) throw new Error("等待超时");
      return { lastUrl: driver.url() };
    }
    case "scroll": {
      const expr = args.selector
        ? `(document.querySelector(${JSON.stringify(s(args.selector))}) || {}).scrollIntoView?.({ block: 'center' })`
        : `window.scrollBy(0, ${Number(args.dy) || 600})`;
      await driver.evaluate(expr);
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
      throw new Error(`未知浏览器动作: ${action}`);
  }
}

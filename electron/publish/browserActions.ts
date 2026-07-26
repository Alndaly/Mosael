import type { PageDriver } from "./pageDriver";

export interface ActionOutcome {
  value?: unknown; // extract/evaluate 的返回值;回给后端时包成 { value }
  lastUrl?: string;
}

const s = (v: unknown): string => (v == null ? "" : String(v));

/**
 * 把一个后端动作分派到 PageDriver。Phase 0 只用 DOM 级动作(离屏 headless 视图上即可跑,与发布
 * 后台流一致):navigate/click/input/press_key/extract/evaluate/wait/scroll。坐标点击、截图、
 * 上传、循环遍历等留到后续阶段(截图需要离屏渲染,见 browserSessions 注释)。
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
    case "screenshot": {
      const dataUrl = await driver.captureBase64();
      return { value: dataUrl, lastUrl: driver.url() };
    }
    default:
      throw new Error(`未知浏览器动作: ${action}`);
  }
}

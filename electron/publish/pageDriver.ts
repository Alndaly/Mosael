import type { WebContents } from "electron";
import { writeFile } from "node:fs/promises";

import { plog } from "./log";

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const KEY_MAP: Record<string, string> = {
  Enter: "Return",
  Escape: "Escape",
  Space: "Space",
  Tab: "Tab",
};

/**
 * Drives an embedded Electron <WebContents> the way Playwright drives a Page,
 * but using only in-process primitives:
 *  - DOM reads/writes via executeJavaScript (CSS selectors only — no Playwright
 *    engine syntax like :has-text/text=; text matching is done in JS helpers)
 *  - real keystrokes via sendInputEvent (for topic dropdowns / confirm keys)
 *  - file inputs via the CDP debugger (DOM.setFileInputFiles), since JS cannot
 *    populate <input type=file> for security reasons
 */
export class PageDriver {
  private debuggerAttached = false;
  private abortSignal: AbortSignal | null = null;

  constructor(private readonly wc: WebContents) {}

  setAbortSignal(signal: AbortSignal | null): void {
    this.abortSignal = signal;
  }

  private throwIfAborted(): void {
    if (this.abortSignal?.aborted) {
      throw new Error("Task was cancelled by user.");
    }
  }

  private async wait(ms: number): Promise<void> {
    this.throwIfAborted();
    await wait(ms);
    this.throwIfAborted();
  }

  /** 均匀随机整数 [min,max],用于拟人化的抖动与停顿。 */
  private rand(min: number, max: number): number {
    return min + Math.floor(Math.random() * (max - min + 1));
  }

  /** 拟人化点击:落点在元素中心附近随机偏移(仍落在元素内),鼠标分几步移过去而非瞬移,按下到抬起
   *  之间有微停顿。替代「每次精确命中像素中心 + 零位移瞬时点击」这一强自动化特征。 */
  private async humanClickAt(rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  }): Promise<void> {
    const jitterX = Math.min(rect.width / 4, 6);
    const jitterY = Math.min(rect.height / 4, 6);
    const tx = Math.round(rect.x + rect.width / 2 + (Math.random() * 2 - 1) * jitterX);
    const ty = Math.round(rect.y + rect.height / 2 + (Math.random() * 2 - 1) * jitterY);
    const steps = this.rand(3, 6);
    const sx = tx - this.rand(20, 60);
    const sy = ty - this.rand(20, 60);
    for (let i = 1; i <= steps; i++) {
      this.wc.sendInputEvent({
        type: "mouseMove",
        x: Math.round(sx + ((tx - sx) * i) / steps),
        y: Math.round(sy + ((ty - sy) * i) / steps),
      });
      await this.wait(this.rand(8, 25));
    }
    this.wc.sendInputEvent({ type: "mouseDown", x: tx, y: ty, button: "left", clickCount: 1 });
    await this.wait(this.rand(40, 110));
    this.wc.sendInputEvent({ type: "mouseUp", x: tx, y: ty, button: "left", clickCount: 1 });
    await this.wait(120);
  }

  url(): string {
    return this.wc.getURL();
  }

  async goto(url: string): Promise<void> {
    plog("goto:", url);
    // loadURL 的 promise 等 did-finish-load;B 站等重前端页面可能长期不触发(未登录重定向 +
    // 持续加载),没有超时就会把整条认领链吊死。超时后放行:页面通常已可交互,交给 checkLogin 判断。
    const timeout = new Promise<"timeout">((resolve) => setTimeout(() => resolve("timeout"), 45_000));
    const outcome = await Promise.race([
      this.wc.loadURL(url).then(
        () => "loaded" as const,
        (error) => (plog("goto rejected:", url, String(error).slice(0, 160)), "rejected" as const),
      ),
      timeout,
    ]);
    plog(`goto ${outcome}:`, this.wc.getURL());
  }

  async setHtml(html: string): Promise<void> {
    await this.wc
      .loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html))
      .catch(() => undefined);
  }

  async evaluate<T = unknown>(expression: string): Promise<T> {
    this.throwIfAborted();
    // executeJavaScript 在页面未 finish load 时会排队不返回(B 站重前端页常见),
    // 必须有兜底超时,否则 checkLogin 等一次性探测会把认领链吊死。
    return await Promise.race([
      this.wc.executeJavaScript(expression, true) as Promise<T>,
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("evaluate timeout (page not settled)")), 20_000),
      ),
    ]);
  }

  async waitForFunction(expression: string, timeout = 30_000, poll = 300): Promise<boolean> {
    const deadline = Date.now() + timeout;
    do {
      this.throwIfAborted();
      try {
        if (await this.evaluate<boolean>(`!!(${expression})`)) {
          return true;
        }
      } catch {
        // Page may be mid-navigation; retry until the deadline.
      }
      await this.wait(poll);
    } while (Date.now() < deadline);
    return false;
  }

  async waitForUrl(
    predicate: (url: string) => boolean,
    timeout = 30_000,
    poll = 300,
  ): Promise<boolean> {
    const deadline = Date.now() + timeout;
    do {
      this.throwIfAborted();
      if (predicate(this.wc.getURL())) {
        return true;
      }
      await this.wait(poll);
    } while (Date.now() < deadline);
    return false;
  }

  // ---- CSS-based queries -------------------------------------------------

  private deepQueryPrelude(selector: string): string {
    const s = JSON.stringify(selector);
    return `const isVisible = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    };
    const collectMatches = (root, out = []) => {
      out.push(...root.querySelectorAll(${s}));
      for (const child of root.querySelectorAll('*')) {
        if (child.shadowRoot) collectMatches(child.shadowRoot, out);
      }
      return out;
    };
    const find = (root) => {
      const matches = collectMatches(root);
      return matches.find(isVisible) || matches[0] || null;
    };`;
  }

  private visibleExpr(selector: string): string {
    return `(() => { ${this.deepQueryPrelude(selector)} const el = find(document); if (!el) return false;
      const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; })()`;
  }

  async cssVisible(selector: string, timeout = 8_000): Promise<boolean> {
    return this.waitForFunction(this.visibleExpr(selector), timeout);
  }

  async cssAttached(selector: string, timeout = 8_000): Promise<boolean> {
    return this.waitForFunction(
      `(() => { ${this.deepQueryPrelude(selector)} return find(document); })()`,
      timeout,
    );
  }

  async fillCss(selector: string, value: string): Promise<void> {
    const v = JSON.stringify(value);
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      el.focus();
      setter.call(el, ${v});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    if (!ok) {
      throw new Error(`fillCss: element not found: ${selector}`);
    }
  }

  async cssValue(selector: string): Promise<string | null> {
    return this.evaluate<string | null>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return null;
      return typeof el.value === 'string' ? el.value : (el.textContent || '');
    })()`);
  }

  async fillField(selector: string, value: string): Promise<void> {
    const v = JSON.stringify(value);
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      el.focus();
      if (el.isContentEditable) {
        try {
          document.execCommand('selectAll', false, null);
          document.execCommand('insertText', false, ${v});
        } catch (e) {
          el.textContent = ${v};
        }
        el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: ${v} }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) {
        setter.call(el, ${v});
      } else {
        el.value = ${v};
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    if (!ok) {
      throw new Error(`fillField: element not found: ${selector}`);
    }
  }

  async focusAndClearField(selector: string): Promise<boolean> {
    return this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      el.focus();
      if (el.isContentEditable) {
        try {
          document.execCommand('selectAll', false, null);
          document.execCommand('delete', false, null);
        } catch (e) {
          el.textContent = '';
        }
        el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) {
        setter.call(el, '');
      } else {
        el.value = '';
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
  }

  async clickCss(selector: string): Promise<void> {
    const ok = await this.evaluate<boolean>(
      `(() => { ${this.deepQueryPrelude(selector)} const el = find(document); if (!el) return false; el.click(); return true; })()`,
    );
    if (!ok) {
      throw new Error(`clickCss: element not found: ${selector}`);
    }
  }

  async clickCenterCss(selector: string): Promise<void> {
    const rect = await this.evaluate<{
      x: number;
      y: number;
      width: number;
      height: number;
    } | null>(
      `(() => {
        ${this.deepQueryPrelude(selector)}
        const el = find(document);
        if (!el) return null;
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return null;
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      })()`,
    );
    if (!rect) {
      throw new Error(`clickCenterCss: element not found: ${selector}`);
    }
    await this.humanClickAt(rect);
  }

  /** Focus a (CSS) element and place the caret at the end — for contenteditable editors. */
  async focusEnd(selector: string): Promise<void> {
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      el.focus();
      try {
        const range = document.createRange();
        range.selectNodeContents(el);
        range.collapse(false);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (e) {}
      return true;
    })()`);
    if (!ok) {
      throw new Error(`focusEnd: element not found: ${selector}`);
    }
  }

  /** Insert text at the caret of a focused editable element (CJK-safe via execCommand). */
  async insertText(selector: string, text: string): Promise<void> {
    await this.focusEnd(selector);
    const t = JSON.stringify(text);
    await this.evaluate(`(() => {
      const ok = document.execCommand('insertText', false, ${t});
      if (!ok) {
        const el = document.activeElement;
        if (el) { el.textContent += ${t}; el.dispatchEvent(new InputEvent('input', { bubbles: true })); }
      }
    })()`);
  }

  // ---- text-based queries (Playwright :has-text / text= replacement) ------

  async hasText(text: string): Promise<boolean> {
    // 探测类查询:页面没就绪(evaluate 超时/导航中)按「没找到」处理,别让 checkLogin 直接炸。
    return this.evaluate<boolean>(
      `!!(document.body && document.body.innerText.includes(${JSON.stringify(text)}))`,
    ).catch(() => false);
  }

  async hasTextDeep(text: string): Promise<boolean> {
    const t = JSON.stringify(text);
    return this.evaluate<boolean>(`(() => {
      const seen = new Set();
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const collect = (root) => {
        if (!root || seen.has(root)) return '';
        seen.add(root);
        let text = root instanceof Document ? (root.body?.innerText || '') : '';
        if (!(root instanceof Document)) {
          for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
            if (visible(el)) text += '\\n' + (el.innerText || el.textContent || '');
          }
        }
        for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
          if (el.shadowRoot) text += '\\n' + collect(el.shadowRoot);
        }
        return text;
      };
      return collect(document).includes(${t});
    })()`).catch(() => false);
  }

  async waitTextGoneDeep(text: string, timeout = 30_000, poll = 1_000): Promise<boolean> {
    const t = JSON.stringify(text);
    return this.waitForFunction(
      `(() => {
        const seen = new Set();
        const visible = (el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
        };
        const collect = (root) => {
          if (!root || seen.has(root)) return '';
          seen.add(root);
          let text = root instanceof Document ? (root.body?.innerText || '') : '';
          if (!(root instanceof Document)) {
            for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
              if (visible(el)) text += '\\n' + (el.innerText || el.textContent || '');
            }
          }
          for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
            if (el.shadowRoot) text += '\\n' + collect(el.shadowRoot);
          }
          return text;
        };
        return !collect(document).includes(${t});
      })()`,
      timeout,
      poll,
    );
  }

  async clickByText(
    text: string,
    options: { exact?: boolean; selector?: string } = {},
  ): Promise<void> {
    const t = JSON.stringify(text);
    const selector = JSON.stringify(options.selector ?? "button, [role=button], a");
    const matcher = options.exact
      ? `e.textContent && e.textContent.trim() === ${t}`
      : `e.textContent && e.textContent.trim().includes(${t})`;
    const ok = await this.evaluate<boolean>(`(() => {
      const els = [...document.querySelectorAll(${selector})];
      const visible = (e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
      };
      const el = els.find((e) => ${matcher} && visible(e));
      if (!el) return false;
      el.click();
      return true;
    })()`);
    if (!ok) {
      throw new Error(`clickByText: no clickable element with text: ${text}`);
    }
  }

  async clickCenterByText(
    text: string,
    options: { exact?: boolean; selector?: string } = {},
  ): Promise<void> {
    const t = JSON.stringify(text);
    const selector = JSON.stringify(options.selector ?? "button, [role=button], a");
    const matcher = options.exact
      ? `e.textContent && e.textContent.trim() === ${t}`
      : `e.textContent && e.textContent.trim().includes(${t})`;
    const rect = await this.evaluate<{
      x: number;
      y: number;
      width: number;
      height: number;
    } | null>(`(() => {
      const els = [...document.querySelectorAll(${selector})];
      const visible = (e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
      };
      const matches = els.filter((e) => visible(e) && ${matcher});
      if (!matches.length) return null;
      const area = (e) => {
        const r = e.getBoundingClientRect();
        return r.width * r.height;
      };
      matches.sort((a, b) => area(a) - area(b));
      const el = matches[0];
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    })()`);
    if (!rect) {
      throw new Error(`clickCenterByText: no visible element with text: ${text}`);
    }
    await this.humanClickAt(rect);
  }

  /**
   * Click an element by its text, piercing open shadow roots (for custom
   * elements like xiaohongshu's <xhs-publish-btn>, whose label lives inside a
   * shadow tree where querySelector/textContent lookups can't see it). The
   * match is scrolled into view and clicked with a real mouse event at its
   * center, so it works regardless of how the component wires its handlers.
   */
  async clickByTextDeep(text: string, options: { exact?: boolean } = {}): Promise<void> {
    const t = JSON.stringify(text);
    const exact = options.exact !== false;
    const rect = await this.evaluate<{
      x: number;
      y: number;
      w: number;
      h: number;
    } | null>(`(() => {
      const target = ${t};
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const collect = (root, out) => {
        for (const el of root.querySelectorAll('*')) {
          out.push(el);
          if (el.shadowRoot) collect(el.shadowRoot, out);
        }
        return out;
      };
      const matchText = (el) => {
        const text = (el.textContent || '').trim();
        return ${exact} ? text === target : text.includes(target);
      };
      const matches = collect(document, []).filter((el) => visible(el) && matchText(el));
      if (!matches.length) return null;
      const clickable = (el) =>
        el.tagName === 'BUTTON' ||
        el.getAttribute('role') === 'button' ||
        /btn|button/i.test((el.className || '').toString());
      const area = (el) => {
        const r = el.getBoundingClientRect();
        return r.width * r.height;
      };
      matches.sort((a, b) => (clickable(b) - clickable(a)) || (area(a) - area(b)));
      const el = matches[0];
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    })()`);
    if (!rect) {
      throw new Error(`clickByTextDeep: no visible element with text: ${text}`);
    }
    await this.humanClickAt({ x: rect.x, y: rect.y, width: rect.w, height: rect.h });
  }

  /** Activate an element with matching text inside a host's open shadow root. */
  async clickInShadow(hostSelector: string, text: string): Promise<boolean> {
    const s = JSON.stringify(hostSelector);
    const t = JSON.stringify(text);
    const ok = await this.evaluate<boolean>(`(() => {
      const host = document.querySelector(${s});
      const root = host && host.shadowRoot;
      if (!root) return false;
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const disabled = (el) => {
        const cls = (el.className || '').toString();
        return Boolean(el.disabled) ||
          /disabled/i.test(cls) ||
          el.getAttribute('aria-disabled') === 'true' ||
          el.getAttribute('disabled') === 'true';
      };
      const clickable = (el) =>
        el.tagName === 'BUTTON' ||
        el.getAttribute('role') === 'button' ||
        /btn|button|publish/i.test((el.className || '').toString());
      const area = (el) => {
        const r = el.getBoundingClientRect();
        return r.width * r.height;
      };
      const matches = [...root.querySelectorAll('button, [role=button], div, span')]
        .filter((el) => visible(el) && !disabled(el) && (el.textContent || '').trim() === ${t});
      if (!matches.length) return false;
      matches.sort((a, b) => (clickable(b) - clickable(a)) || (area(a) - area(b)));
      const el = matches[0];
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
      const fire = (type) => {
        const EventCtor = type.startsWith('pointer') && window.PointerEvent
          ? window.PointerEvent
          : window.MouseEvent;
        el.dispatchEvent(new EventCtor(type, init));
      };
      fire('pointerdown');
      fire('mousedown');
      if (typeof el.click === 'function') {
        el.click();
      } else {
        fire('click');
      }
      fire('mouseup');
      fire('pointerup');
      fire('click');
      return true;
    })()`);
    if (ok) {
      await this.wait(120);
    }
    return ok;
  }

  /**
   * Activate a custom element node without relying on viewport coordinates.
   * Some platform widgets (notably Xiaohongshu's <xhs-publish-btn>) render their
   * internal buttons outside of accessible light/shadow DOM, but expose enabled
   * state on the host element. In that case the stable contract is the host
   * node itself, so trigger the same click/pointer event sequence on that node.
   */
  async activateCustomElement(selector: string): Promise<boolean> {
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const host = find(document);
      if (!host) return false;
      const rect = host.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const disabled =
        host.getAttribute('submit-disabled') === 'true' ||
        host.getAttribute('disabled') === 'true' ||
        host.getAttribute('aria-disabled') === 'true' ||
        /disabled/i.test((host.className || '').toString());
      if (disabled) return false;
      host.scrollIntoView({ block: 'center', inline: 'nearest' });
      const nextRect = host.getBoundingClientRect();
      const init = {
        bubbles: true,
        cancelable: true,
        composed: true,
        view: window,
        clientX: nextRect.left + nextRect.width / 2,
        clientY: nextRect.top + nextRect.height / 2,
        button: 0
      };
      const fire = (type) => {
        const EventCtor = type.startsWith('pointer') && window.PointerEvent
          ? window.PointerEvent
          : window.MouseEvent;
        host.dispatchEvent(new EventCtor(type, init));
      };
      fire('pointerdown');
      fire('mousedown');
      if (typeof host.click === 'function') {
        host.click();
      } else {
        fire('click');
      }
      fire('mouseup');
      fire('pointerup');
      fire('click');
      return true;
    })()`);
    if (ok) {
      await this.wait(120);
    }
    return ok;
  }

  async hasXiaohongshuTopic(tag: string): Promise<boolean> {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    return this.evaluate<boolean>(`(() => { // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
      const target = ${normalized};
      return [...document.querySelectorAll('a.tiptap-topic')].some((el) => {
        const data = el.getAttribute('data-topic') || '';
        const text = (el.textContent || '').replace('[话题]#', '').replace(/^#/, '').trim();
        return text === target || data.includes('"name":"' + target + '"');
      });
    })()`);
  }

  async clickXiaohongshuTopicCandidate(tag: string): Promise<boolean> {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    const ok = await this.evaluate<boolean>(`(() => { // i18n-ok
      const target = ${normalized};
      const topicText = '#' + target;
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const containers = [
        ...document.querySelectorAll(
          '#creator-editor-topic-container, [data-tippy-root], .tippy-box, .tippy-content'
        )
      ].filter(visible);
      const pool = containers.flatMap((container) => [
        ...container.querySelectorAll('.item, [role=option], button, [role=button], div, span')
      ]);
      const matches = pool.filter((el) => {
        if (!visible(el)) return false;
        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        return text === topicText ||
          text.startsWith(topicText + ' ') ||
          text.includes(topicText + '新建话题') ||
          text.includes('新建话题');
      });
      if (!matches.length) return false;
      const score = (el) => {
        const cls = (el.className || '').toString();
        const tagName = el.tagName.toLowerCase();
        let value = 0;
        if (/\\bitem\\b/.test(cls)) value -= 40;
        if (/is-selected/.test(cls)) value -= 30;
        if (tagName === 'button' || el.getAttribute('role') === 'button') value -= 10;
        if ((el.textContent || '').trim().startsWith(topicText)) value -= 5;
        const r = el.getBoundingClientRect();
        value += Math.max(0, r.width * r.height) / 10000;
        return value;
      };
      matches.sort((a, b) => score(a) - score(b));
      const el = matches[0];
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
      const fire = (type) => {
        const EventCtor = type.startsWith('pointer') && window.PointerEvent
          ? window.PointerEvent
          : window.MouseEvent;
        el.dispatchEvent(new EventCtor(type, init));
      };
      fire('pointerdown');
      fire('mousedown');
      if (typeof el.click === 'function') {
        el.click();
      } else {
        fire('click');
      }
      fire('mouseup');
      fire('pointerup');
      fire('click');
      return true;
    })()`);
    if (ok) {
      await this.wait(120);
    }
    return ok;
  }

  async publishXiaohongshuCustomElement(selector: string): Promise<boolean> {
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const host = find(document);
      if (!host) return false;
      const rect = host.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      if (
        host.getAttribute('submit-disabled') === 'true' ||
        host.getAttribute('disabled') === 'true' ||
        host.getAttribute('aria-disabled') === 'true'
      ) {
        return false;
      }
      host.scrollIntoView({ block: 'center', inline: 'nearest' });
      if (typeof host._onPublish === 'function') {
        host._onPublish();
      } else {
        host.dispatchEvent(new CustomEvent('publish', { bubbles: true, composed: true }));
      }
      return true;
    })()`);
    if (ok) {
      await this.wait(120);
    }
    return ok;
  }

  async waitTextEnabledDeep(
    text: string,
    timeout = 30_000,
    options: { exact?: boolean; hostSelector?: string } = {},
  ): Promise<boolean> {
    const t = JSON.stringify(text);
    const exact = options.exact !== false;
    const hostSelector = options.hostSelector ? JSON.stringify(options.hostSelector) : "null";
    const expr = `(() => {
      const target = ${t};
      const hostSelector = ${hostSelector};
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
      };
      const disabled = (el) => {
        let current = el;
        while (current && current.nodeType === Node.ELEMENT_NODE) {
          const cls = (current.className || '').toString();
          if (Boolean(current.disabled) ||
            /disabled/i.test(cls) ||
            current.getAttribute('aria-disabled') === 'true' ||
            current.getAttribute('disabled') === 'true' ||
            current.getAttribute('submit-disabled') === 'true' ||
            current.getAttribute('save-disabled') === 'true') {
            return true;
          }
          const root = current.getRootNode && current.getRootNode();
          current = current.parentElement || (root && root.host) || null;
        }
        return false;
      };
      const collect = (root, out) => {
        for (const el of root.querySelectorAll('*')) {
          out.push(el);
          if (el.shadowRoot) collect(el.shadowRoot, out);
        }
        return out;
      };
      const roots = [];
      if (hostSelector) {
        const host = document.querySelector(hostSelector);
        if (host?.shadowRoot) roots.push(host.shadowRoot);
        if (host) roots.push(host);
      } else {
        roots.push(document);
      }
      return roots.some((root) =>
        collect(root, []).some((el) => {
          const value = (el.textContent || '').trim();
          const textMatches = ${exact} ? value === target : value.includes(target);
          return textMatches && visible(el) && !disabled(el);
        })
      );
    })()`;
    return this.waitForFunction(expr, timeout, 1_000);
  }

  async waitCssEnabled(selector: string, timeout = 30_000): Promise<boolean> {
    const expr = `(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const cls = (el.className || '').toString();
      return !el.disabled &&
        !/disabled/i.test(cls) &&
        el.getAttribute('aria-disabled') !== 'true' &&
        el.getAttribute('submit-disabled') !== 'true' &&
        el.getAttribute('save-disabled') !== 'true';
    })()`;
    return this.waitForFunction(expr, timeout, 1_000);
  }

  /** Wait until a button whose exact text === `text` exists and is not disabled. */
  async waitButtonEnabled(text: string, timeout = 30_000): Promise<boolean> {
    const t = JSON.stringify(text);
    const expr = `(() => {
      const collect = (root, out = []) => {
        for (const el of root.querySelectorAll('button, [role=button]')) out.push(el);
        for (const el of root.querySelectorAll('*')) {
          if (el.shadowRoot) collect(el.shadowRoot, out);
        }
        return out;
      };
      const els = collect(document);
      const el = els.find((e) => e.textContent && e.textContent.trim() === ${t});
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const cls = (el.className || '').toString();
      return !el.disabled && !/disabled/i.test(cls) && el.getAttribute('aria-disabled') !== 'true';
    })()`;
    return this.waitForFunction(expr, timeout, 1_000);
  }

  // ---- real input events --------------------------------------------------

  async type(text: string): Promise<void> {
    for (const ch of text) {
      this.throwIfAborted();
      this.wc.sendInputEvent({ type: "char", keyCode: ch });
      await this.wait(20);
    }
  }

  async pressKey(key: "Enter" | "Escape" | "Space" | "Tab"): Promise<void> {
    const code = KEY_MAP[key] ?? key;
    this.wc.sendInputEvent({ type: "keyDown", keyCode: code });
    this.wc.sendInputEvent({ type: "char", keyCode: key === "Space" ? " " : code });
    this.wc.sendInputEvent({ type: "keyUp", keyCode: code });
    await this.wait(60);
  }

  // ---- file upload via CDP ------------------------------------------------

  async setFiles(selector: string, filePath: string): Promise<void> {
    this.throwIfAborted();
    const nodeId = await this.findFileInputNode(selector);
    this.throwIfAborted();
    await this.wc.debugger.sendCommand("DOM.setFileInputFiles", {
      files: [filePath],
      nodeId,
    });
  }

  async fileInputAttached(selector = 'input[type="file"]', timeout = 8_000): Promise<boolean> {
    const deadline = Date.now() + timeout;
    do {
      this.throwIfAborted();
      try {
        await this.findFileInputNode(selector);
        return true;
      } catch {
        await this.wait(300);
      }
    } while (Date.now() < deadline);
    return false;
  }

  async fillInputNearText(text: string, value: string): Promise<boolean> {
    const t = JSON.stringify(text);
    const v = JSON.stringify(value);
    return this.evaluate<boolean>(`(() => {
      const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const candidates = [...document.querySelectorAll('label, div, span')]
        .filter((el) => visible(el) && (el.textContent || '').trim() === ${t});
      for (const label of candidates) {
        const scopes = [
          label,
          label.parentElement,
          label.parentElement?.parentElement,
          label.parentElement?.nextElementSibling,
          label.parentElement?.parentElement?.querySelector(':scope > div:last-child')
        ].filter(Boolean);
        for (const scope of scopes) {
          const input = scope.querySelector('input[type="text"], input:not([type]), textarea');
          if (!input || !visible(input)) continue;
          const proto = input.tagName === 'TEXTAREA'
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          input.focus();
          setter.call(input, ${v});
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
      }
      return false;
    })()`);
  }

  async diagnostics(): Promise<Record<string, unknown>> {
    return this.evaluate<Record<string, unknown>>(`(() => {
      const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const pick = (el) => ({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type'),
        role: el.getAttribute('role'),
        text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 100),
        placeholder: el.getAttribute('placeholder'),
        className: (el.getAttribute('class') || '').slice(0, 140),
        id: el.id || null,
        src: el.getAttribute('src'),
        accept: el.getAttribute('accept')
      });
      return {
        url: location.href,
        title: document.title,
        text: (document.body?.innerText || '').replace(/\\s+/g, ' ').slice(0, 1000),
        inputs: [...document.querySelectorAll('input, textarea')].slice(0, 80).map(pick),
        visibleInputs: [...document.querySelectorAll('input, textarea')].filter(visible).slice(0, 60).map(pick),
        fileInputs: [...document.querySelectorAll('input[type="file"]')].map(pick),
        editables: [...document.querySelectorAll('[contenteditable]')].slice(0, 40).map(pick),
        buttons: [...document.querySelectorAll('button, [role="button"], a')].filter(visible).slice(0, 100).map(pick),
        iframes: [...document.querySelectorAll('iframe')].slice(0, 20).map(pick)
      };
    })()`);
  }

  private async findFileInputNode(selector: string): Promise<number> {
    this.throwIfAborted();
    if (!this.debuggerAttached) {
      this.wc.debugger.attach("1.3");
      this.debuggerAttached = true;
    }
    await this.wc.debugger.sendCommand("DOM.enable");
    const doc = (await this.wc.debugger.sendCommand("DOM.getDocument", { depth: -1 })) as {
      root: { nodeId: number };
    };
    const found = (await this.wc.debugger.sendCommand("DOM.querySelector", {
      nodeId: doc.root.nodeId,
      selector,
    })) as { nodeId: number };
    if (!found.nodeId) {
      const flattened = (await this.wc.debugger.sendCommand("DOM.getFlattenedDocument", {
        depth: -1,
        pierce: true,
      })) as {
        nodes: Array<{ nodeId: number; nodeName: string; attributes?: string[] }>;
      };
      const fallback = flattened.nodes.find((node) => {
        if (node.nodeName !== "INPUT") {
          return false;
        }
        const attributes = node.attributes ?? [];
        for (let i = 0; i < attributes.length; i += 2) {
          if (attributes[i] === "type" && attributes[i + 1] === "file") {
            return true;
          }
        }
        return false;
      });
      if (fallback?.nodeId) {
        return fallback.nodeId;
      }
      throw new Error(`setFiles: file input not found: ${selector}`);
    }
    return found.nodeId;
  }

  // ---- misc ---------------------------------------------------------------

  async removeElements(selector: string): Promise<void> {
    await this.evaluate(
      `document.querySelectorAll(${JSON.stringify(selector)}).forEach((e) => e.remove())`,
    );
  }

  async screenshot(path: string): Promise<void> {
    const image = await this.wc.capturePage();
    await writeFile(path, image.toPNG());
  }

  detach(): void {
    if (this.debuggerAttached) {
      try {
        this.wc.debugger.detach();
      } catch {
        // already detached
      }
      this.debuggerAttached = false;
    }
  }
}

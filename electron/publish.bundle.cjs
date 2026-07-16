var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// electron/publish/index.ts
var index_exports = {};
__export(index_exports, {
  hidePublishView: () => hidePublishView,
  openLogin: () => openLogin,
  openPage: () => openPage,
  setLocale: () => setLocale,
  startPublishWorker: () => startPublishWorker,
  stopPublishWorker: () => stopPublishWorker
});
module.exports = __toCommonJS(index_exports);

// electron/publish/worker.ts
var import_electron3 = require("electron");
var import_promises2 = require("node:fs/promises");
var import_node_path3 = __toESM(require("node:path"));

// electron/publish/i18n.ts
function tr(text, params) {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (_match, key) => String(params[key] ?? `{${key}}`));
}
function setLocale(_locale) {
}

// electron/publish/accountViews.ts
var import_electron2 = require("electron");
var import_node_path2 = __toESM(require("node:path"));

// electron/publish/types.ts
var EMBED_HEADER_HEIGHT = 48;

// electron/publish/pageDriver.ts
var import_promises = require("node:fs/promises");

// electron/publish/log.ts
var import_electron = require("electron");
var import_node_fs = require("node:fs");
var import_node_path = __toESM(require("node:path"));
var logFile = null;
function ensureFile() {
  if (logFile) return logFile;
  try {
    const dir = import_node_path.default.join(import_electron.app.getPath("userData"), "logs");
    (0, import_node_fs.mkdirSync)(dir, { recursive: true });
    logFile = import_node_path.default.join(dir, "publisher.log");
    return logFile;
  } catch {
    return null;
  }
}
function plog(...parts) {
  const line = `[${(/* @__PURE__ */ new Date()).toISOString()}] ${parts.map((p) => p instanceof Error ? p.stack || p.message : typeof p === "string" ? p : JSON.stringify(p)).join(" ")}`;
  console.log("[publisher]", line);
  const file = ensureFile();
  if (file) {
    try {
      (0, import_node_fs.appendFileSync)(file, line + "\n");
    } catch {
    }
  }
}

// electron/publish/pageDriver.ts
var wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
var KEY_MAP = {
  Enter: "Return",
  Escape: "Escape",
  Space: "Space",
  Tab: "Tab"
};
var PageDriver = class {
  constructor(wc) {
    this.wc = wc;
  }
  wc;
  debuggerAttached = false;
  abortSignal = null;
  setAbortSignal(signal) {
    this.abortSignal = signal;
  }
  throwIfAborted() {
    if (this.abortSignal?.aborted) {
      throw new Error("Task was cancelled by user.");
    }
  }
  async wait(ms) {
    this.throwIfAborted();
    await wait(ms);
    this.throwIfAborted();
  }
  /** 均匀随机整数 [min,max],用于拟人化的抖动与停顿。 */
  rand(min, max) {
    return min + Math.floor(Math.random() * (max - min + 1));
  }
  /** 拟人化点击:落点在元素中心附近随机偏移(仍落在元素内),鼠标分几步移过去而非瞬移,按下到抬起
   *  之间有微停顿。替代「每次精确命中像素中心 + 零位移瞬时点击」这一强自动化特征。 */
  async humanClickAt(rect) {
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
        x: Math.round(sx + (tx - sx) * i / steps),
        y: Math.round(sy + (ty - sy) * i / steps)
      });
      await this.wait(this.rand(8, 25));
    }
    this.wc.sendInputEvent({ type: "mouseDown", x: tx, y: ty, button: "left", clickCount: 1 });
    await this.wait(this.rand(40, 110));
    this.wc.sendInputEvent({ type: "mouseUp", x: tx, y: ty, button: "left", clickCount: 1 });
    await this.wait(120);
  }
  url() {
    return this.wc.getURL();
  }
  async goto(url) {
    plog("goto:", url);
    const timeout = new Promise((resolve) => setTimeout(() => resolve("timeout"), 45e3));
    const outcome = await Promise.race([
      this.wc.loadURL(url).then(
        () => "loaded",
        (error) => (plog("goto rejected:", url, String(error).slice(0, 160)), "rejected")
      ),
      timeout
    ]);
    plog(`goto ${outcome}:`, this.wc.getURL());
  }
  async setHtml(html) {
    await this.wc.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html)).catch(() => void 0);
  }
  async evaluate(expression) {
    this.throwIfAborted();
    return await Promise.race([
      this.wc.executeJavaScript(expression, true),
      new Promise(
        (_, reject) => setTimeout(() => reject(new Error("evaluate timeout (page not settled)")), 2e4)
      )
    ]);
  }
  async waitForFunction(expression, timeout = 3e4, poll = 300) {
    const deadline = Date.now() + timeout;
    do {
      this.throwIfAborted();
      try {
        if (await this.evaluate(`!!(${expression})`)) {
          return true;
        }
      } catch {
      }
      await this.wait(poll);
    } while (Date.now() < deadline);
    return false;
  }
  async waitForUrl(predicate, timeout = 3e4, poll = 300) {
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
  deepQueryPrelude(selector) {
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
  visibleExpr(selector) {
    return `(() => { ${this.deepQueryPrelude(selector)} const el = find(document); if (!el) return false;
      const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; })()`;
  }
  async cssVisible(selector, timeout = 8e3) {
    return this.waitForFunction(this.visibleExpr(selector), timeout);
  }
  async cssAttached(selector, timeout = 8e3) {
    return this.waitForFunction(
      `(() => { ${this.deepQueryPrelude(selector)} return find(document); })()`,
      timeout
    );
  }
  async fillCss(selector, value) {
    const v = JSON.stringify(value);
    const ok = await this.evaluate(`(() => {
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
  async cssValue(selector) {
    return this.evaluate(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return null;
      return typeof el.value === 'string' ? el.value : (el.textContent || '');
    })()`);
  }
  async fillField(selector, value) {
    const v = JSON.stringify(value);
    const ok = await this.evaluate(`(() => {
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
  async focusAndClearField(selector) {
    return this.evaluate(`(() => {
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
  async clickCss(selector) {
    const ok = await this.evaluate(
      `(() => { ${this.deepQueryPrelude(selector)} const el = find(document); if (!el) return false; el.click(); return true; })()`
    );
    if (!ok) {
      throw new Error(`clickCss: element not found: ${selector}`);
    }
  }
  async clickCenterCss(selector) {
    const rect = await this.evaluate(
      `(() => {
        ${this.deepQueryPrelude(selector)}
        const el = find(document);
        if (!el) return null;
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return null;
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      })()`
    );
    if (!rect) {
      throw new Error(`clickCenterCss: element not found: ${selector}`);
    }
    await this.humanClickAt(rect);
  }
  /** Focus a (CSS) element and place the caret at the end — for contenteditable editors. */
  async focusEnd(selector) {
    const ok = await this.evaluate(`(() => {
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
  async insertText(selector, text) {
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
  async hasText(text) {
    return this.evaluate(
      `!!(document.body && document.body.innerText.includes(${JSON.stringify(text)}))`
    ).catch(() => false);
  }
  async hasTextDeep(text) {
    const t = JSON.stringify(text);
    return this.evaluate(`(() => {
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
  async waitTextGoneDeep(text, timeout = 3e4, poll = 1e3) {
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
      poll
    );
  }
  async clickByText(text, options = {}) {
    const t = JSON.stringify(text);
    const selector = JSON.stringify(options.selector ?? "button, [role=button], a");
    const matcher = options.exact ? `e.textContent && e.textContent.trim() === ${t}` : `e.textContent && e.textContent.trim().includes(${t})`;
    const ok = await this.evaluate(`(() => {
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
  async clickCenterByText(text, options = {}) {
    const t = JSON.stringify(text);
    const selector = JSON.stringify(options.selector ?? "button, [role=button], a");
    const matcher = options.exact ? `e.textContent && e.textContent.trim() === ${t}` : `e.textContent && e.textContent.trim().includes(${t})`;
    const rect = await this.evaluate(`(() => {
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
  async clickByTextDeep(text, options = {}) {
    const t = JSON.stringify(text);
    const exact = options.exact !== false;
    const rect = await this.evaluate(`(() => {
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
  async clickInShadow(hostSelector, text) {
    const s = JSON.stringify(hostSelector);
    const t = JSON.stringify(text);
    const ok = await this.evaluate(`(() => {
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
  async activateCustomElement(selector) {
    const ok = await this.evaluate(`(() => {
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
  async hasXiaohongshuTopic(tag) {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    return this.evaluate(`(() => { // i18n-ok \u5E73\u53F0\u9875\u9762\u7684\u5339\u914D\u6587\u6848/\u9009\u62E9\u5668/\u6CE8\u5165\u811A\u672C,\u975E\u4EA7\u54C1\u6587\u6848
      const target = ${normalized};
      return [...document.querySelectorAll('a.tiptap-topic')].some((el) => {
        const data = el.getAttribute('data-topic') || '';
        const text = (el.textContent || '').replace('[\u8BDD\u9898]#', '').replace(/^#/, '').trim();
        return text === target || data.includes('"name":"' + target + '"');
      });
    })()`);
  }
  async clickXiaohongshuTopicCandidate(tag) {
    const normalized = JSON.stringify(tag.replace(/^#/, "").trim());
    const ok = await this.evaluate(`(() => { // i18n-ok
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
          text.includes(topicText + '\u65B0\u5EFA\u8BDD\u9898') ||
          text.includes('\u65B0\u5EFA\u8BDD\u9898');
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
  async publishXiaohongshuCustomElement(selector) {
    const ok = await this.evaluate(`(() => {
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
  async waitTextEnabledDeep(text, timeout = 3e4, options = {}) {
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
    return this.waitForFunction(expr, timeout, 1e3);
  }
  async waitCssEnabled(selector, timeout = 3e4) {
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
    return this.waitForFunction(expr, timeout, 1e3);
  }
  /** Wait until a button whose exact text === `text` exists and is not disabled. */
  async waitButtonEnabled(text, timeout = 3e4) {
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
    return this.waitForFunction(expr, timeout, 1e3);
  }
  // ---- real input events --------------------------------------------------
  async type(text) {
    for (const ch of text) {
      this.throwIfAborted();
      this.wc.sendInputEvent({ type: "char", keyCode: ch });
      await this.wait(20);
    }
  }
  async pressKey(key) {
    const code = KEY_MAP[key] ?? key;
    this.wc.sendInputEvent({ type: "keyDown", keyCode: code });
    this.wc.sendInputEvent({ type: "char", keyCode: key === "Space" ? " " : code });
    this.wc.sendInputEvent({ type: "keyUp", keyCode: code });
    await this.wait(60);
  }
  // ---- file upload via CDP ------------------------------------------------
  async setFiles(selector, filePath) {
    this.throwIfAborted();
    const nodeId = await this.findFileInputNode(selector);
    this.throwIfAborted();
    await this.wc.debugger.sendCommand("DOM.setFileInputFiles", {
      files: [filePath],
      nodeId
    });
  }
  async fileInputAttached(selector = 'input[type="file"]', timeout = 8e3) {
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
  async fillInputNearText(text, value) {
    const t = JSON.stringify(text);
    const v = JSON.stringify(value);
    return this.evaluate(`(() => {
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
  async diagnostics() {
    return this.evaluate(`(() => {
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
  async findFileInputNode(selector) {
    this.throwIfAborted();
    if (!this.debuggerAttached) {
      this.wc.debugger.attach("1.3");
      this.debuggerAttached = true;
    }
    await this.wc.debugger.sendCommand("DOM.enable");
    const doc = await this.wc.debugger.sendCommand("DOM.getDocument", { depth: -1 });
    const found = await this.wc.debugger.sendCommand("DOM.querySelector", {
      nodeId: doc.root.nodeId,
      selector
    });
    if (!found.nodeId) {
      const flattened = await this.wc.debugger.sendCommand("DOM.getFlattenedDocument", {
        depth: -1,
        pierce: true
      });
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
  async removeElements(selector) {
    await this.evaluate(
      `document.querySelectorAll(${JSON.stringify(selector)}).forEach((e) => e.remove())`
    );
  }
  async screenshot(path4) {
    const image = await this.wc.capturePage();
    await (0, import_promises.writeFile)(path4, image.toPNG());
  }
  detach() {
    if (this.debuggerAttached) {
      try {
        this.wc.debugger.detach();
      } catch {
      }
      this.debuggerAttached = false;
    }
  }
};

// electron/publish/accountViews.ts
var noop = () => void 0;
var ACCOUNT_VIEW_PRELOAD = import_node_path2.default.join(__dirname, "accountview-preload.cjs");
var platformUserAgent = (userAgent) => {
  return userAgent.replace(/\sElectron\/[\d.]+/i, "");
};
var AccountViewManager = class {
  constructor(onViewChanged = noop) {
    this.onViewChanged = onViewChanged;
  }
  onViewChanged;
  views = /* @__PURE__ */ new Map();
  drivers = /* @__PURE__ */ new Map();
  appliedProxy = /* @__PURE__ */ new Map();
  window = null;
  visibleId = null;
  nameOf = () => null;
  attachWindow(window, nameResolver) {
    this.window = window;
    this.nameOf = nameResolver;
    window.on("resize", () => this.layout());
  }
  getDriver(accountId) {
    return this.ensure(accountId).driver;
  }
  async configureAccount(accountId, proxy) {
    const partition = this.partitionFor(accountId);
    const normalizedProxy = proxy?.trim() || null;
    if (this.appliedProxy.get(partition) === normalizedProxy) {
      return;
    }
    const accountSession = import_electron2.session.fromPartition(partition);
    await accountSession.setProxy({
      mode: normalizedProxy ? "fixed_servers" : "direct",
      proxyRules: normalizedProxy ?? void 0
    });
    this.appliedProxy.set(partition, normalizedProxy);
  }
  /** Bring an account's view to the front of the window and size it. */
  show(accountId) {
    const { view } = this.ensure(accountId);
    if (!this.window || this.window.isDestroyed()) {
      return;
    }
    if (this.visibleId && this.visibleId !== accountId) {
      this.detachView(this.visibleId);
    }
    this.visibleId = accountId;
    this.layout();
    this.window.contentView.addChildView(view);
    console.info("[mibu:view] shown", {
      accountId,
      bounds: view.getBounds(),
      childCount: this.window.contentView.children.length,
      url: view.webContents.getURL()
    });
    this.emit();
  }
  /** Hide whatever view is currently shown (returns the window to the React UI). */
  hide() {
    if (this.visibleId) {
      this.detachView(this.visibleId);
      this.visibleId = null;
      this.emit();
    }
  }
  get visibleAccountId() {
    return this.visibleId;
  }
  /**
   * Open detached DevTools on the currently visible embedded view (menu-driven;
   * used to probe/calibrate selectors against the live platform DOM).
   */
  openDevTools() {
    const view = this.visibleId ? this.views.get(this.visibleId) : null;
    if (!view || view.webContents.isDestroyed()) {
      return false;
    }
    view.webContents.openDevTools({ mode: "detach" });
    return true;
  }
  destroy(accountId) {
    this.detachView(accountId);
    this.drivers.get(accountId)?.detach();
    const view = this.views.get(accountId);
    if (view) {
      try {
        view.webContents.close();
      } catch {
      }
    }
    this.views.delete(accountId);
    this.drivers.delete(accountId);
    if (this.visibleId === accountId) {
      this.visibleId = null;
      this.emit();
    }
  }
  /** Wipe the account's persisted login state (cookies, localStorage, caches). */
  async clearAccountData(accountId) {
    this.destroy(accountId);
    const partition = this.partitionFor(accountId);
    this.appliedProxy.delete(partition);
    const accountSession = import_electron2.session.fromPartition(partition);
    await accountSession.clearStorageData();
    await accountSession.clearCache().catch(noop);
  }
  destroyAll() {
    for (const accountId of [...this.views.keys()]) {
      this.destroy(accountId);
    }
  }
  ensure(accountId) {
    let view = this.views.get(accountId);
    if (!view) {
      view = new import_electron2.WebContentsView({
        webPreferences: {
          partition: this.partitionFor(accountId),
          backgroundThrottling: false,
          // 注入「返回」悬浮按钮(点击永远发生在聚焦的账号视图内,不会被 macOS 焦点切换吞掉)。
          preload: ACCOUNT_VIEW_PRELOAD,
          contextIsolation: true
        }
      });
      view.webContents.setUserAgent(platformUserAgent(view.webContents.getUserAgent()));
      view.webContents.setWindowOpenHandler(({ url }) => {
        try {
          const proto = new URL(url).protocol;
          if (proto === "http:" || proto === "https:") void view?.webContents.loadURL(url);
        } catch {
        }
        return { action: "deny" };
      });
      view.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
        console.warn("[mibu:view] load failed", {
          accountId,
          errorCode,
          errorDescription,
          url: validatedURL
        });
      });
      view.webContents.on("before-input-event", (_event, input) => {
        if (input.type === "keyDown" && input.key === "Escape") this.hide();
      });
      view.setBackgroundColor("#ffffff");
      this.views.set(accountId, view);
      this.drivers.set(accountId, new PageDriver(view.webContents));
    }
    return { view, driver: this.drivers.get(accountId) };
  }
  partitionFor(accountId) {
    return `persist:mibu-${accountId}`;
  }
  detachView(accountId) {
    const view = this.views.get(accountId);
    if (view && this.window && !this.window.isDestroyed()) {
      this.window.contentView.removeChildView(view);
    }
  }
  layout() {
    if (!this.window || this.window.isDestroyed() || !this.visibleId) {
      return;
    }
    const view = this.views.get(this.visibleId);
    if (!view) {
      return;
    }
    const [width, height] = this.window.getContentSize();
    view.setBounds({
      x: 0,
      y: EMBED_HEADER_HEIGHT,
      width,
      height: Math.max(0, height - EMBED_HEADER_HEIGHT)
    });
  }
  emit() {
    this.onViewChanged({
      visible: this.visibleId !== null,
      accountId: this.visibleId,
      accountName: this.visibleId ? this.nameOf(this.visibleId) : null
    });
  }
};

// electron/publish/platforms.ts
var PLATFORM_DEFINITIONS = [
  {
    id: "mock",
    label: "Mock",
    aliases: ["mock"],
    loginUrl: "about:blank",
    dashboardUrl: "about:blank",
    publishUrl: "about:blank",
    manageUrl: "about:blank",
    supportsShortTitle: false,
    supportsDescription: false,
    supportsTags: true
  },
  {
    id: "douyin",
    label: "\u6296\u97F3",
    // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
    aliases: ["douyin", "\u6296\u97F3"],
    // i18n-ok
    loginUrl: "https://creator.douyin.com/",
    dashboardUrl: "https://creator.douyin.com/creator-micro/home",
    publishUrl: "https://creator.douyin.com/creator-micro/content/upload",
    manageUrl: "https://creator.douyin.com/creator-micro/content/manage",
    titleMaxLength: 30,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true
  },
  {
    id: "xiaohongshu",
    label: "\u5C0F\u7EA2\u4E66",
    // i18n-ok
    aliases: ["xiaohongshu", "xhs", "rednote", "\u5C0F\u7EA2\u4E66"],
    // i18n-ok
    loginUrl: "https://creator.xiaohongshu.com/",
    dashboardUrl: "https://creator.xiaohongshu.com/new/home",
    publishUrl: "https://creator.xiaohongshu.com/publish/publish",
    manageUrl: "https://creator.xiaohongshu.com/new/notes",
    titleMaxLength: 20,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true
  },
  {
    id: "weixin-channels",
    label: "\u5FAE\u4FE1\u89C6\u9891\u53F7",
    // i18n-ok
    aliases: [
      "weixin-channels",
      "weixin",
      "wechat",
      "channels",
      "shipinhao",
      "\u89C6\u9891\u53F7",
      // i18n-ok
      "\u5FAE\u4FE1\u89C6\u9891\u53F7"
      // i18n-ok
    ],
    loginUrl: "https://channels.weixin.qq.com/login.html?from=assistant",
    dashboardUrl: "https://channels.weixin.qq.com/platform/post/list",
    publishUrl: "https://channels.weixin.qq.com/platform/post/create",
    manageUrl: "https://channels.weixin.qq.com/platform/post/list",
    titleMaxLength: 16,
    supportsShortTitle: true,
    supportsDescription: true,
    supportsTags: true
  },
  {
    id: "bilibili",
    label: "Bilibili",
    aliases: ["bilibili", "bili", "b\u7AD9", "\u54D4\u54E9\u54D4\u54E9"],
    // i18n-ok
    loginUrl: "https://passport.bilibili.com/login",
    dashboardUrl: "https://member.bilibili.com/platform/home",
    publishUrl: "https://member.bilibili.com/platform/upload/video/frame",
    manageUrl: "https://member.bilibili.com/platform/upload-manager/article",
    titleMaxLength: 80,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true
  }
];
var PLATFORM_BY_ALIAS = new Map(
  PLATFORM_DEFINITIONS.flatMap(
    (definition) => definition.aliases.map((alias) => [alias.toLowerCase(), definition])
  )
);
var resolvePlatform = (platform) => {
  return PLATFORM_BY_ALIAS.get(platform.trim().toLowerCase()) ?? PLATFORM_DEFINITIONS[0];
};

// electron/publish/errors.ts
var AutomationBlockedError = class extends Error {
  constructor(reason, message) {
    super(message);
    this.reason = reason;
    this.name = "AutomationBlockedError";
  }
  reason;
};
var isAutomationBlockedError = (error) => {
  return error instanceof AutomationBlockedError;
};

// electron/publish/adapters.ts
var wait2 = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
var TEXT_PUBLISH_VIDEO = "\u53D1\u5E03\u89C6\u9891";
var TEXT_NEW_TOPIC = "\u65B0\u5EFA\u8BDD\u9898";
var UPLOAD_TIMEOUT = 10 * 60 * 1e3;
var RESULT_TIMEOUT = 2 * 60 * 1e3;
var ACTION_TIMEOUT = 30 * 1e3;
var HUMAN_INTERVENTION_TIMEOUT = 10 * 60 * 1e3;
var normalizeTag = (tag) => tag.replace(/^#/, "").trim();
var escapeHtml = (value) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
var stringOption = (task, key) => {
  const value = task.platformOptions[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};
var SELECTORS = {
  douyin: {
    uploadUrl: resolvePlatform("douyin").publishUrl,
    fileInput: "div[class^='container'] input[type='file'], input[type='file']",
    titleInput: 'input[placeholder*="\u586B\u5199\u4F5C\u54C1\u6807\u9898"], input[placeholder*="\u4F5C\u54C1\u6807\u9898"]',
    // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
    descEditor: 'div.zone-container[contenteditable="true"], div[contenteditable="true"]',
    overlays: '.shepherd-element, .shepherd-modal-overlay-container, [class*="mention-wrapper"]',
    submitText: "\u53D1\u5E03",
    // i18n-ok
    uploadDoneText: "\u91CD\u65B0\u4E0A\u4F20",
    // i18n-ok
    uploadFailedText: "\u4E0A\u4F20\u5931\u8D25",
    // i18n-ok
    loggedOutTexts: ["\u626B\u7801\u767B\u5F55", "\u624B\u673A\u53F7\u767B\u5F55", "\u4E8C\u7EF4\u7801\u5931\u6548"],
    // i18n-ok
    loggedInTexts: ["\u9AD8\u6E05\u53D1\u5E03", "\u53D1\u5E03\u89C6\u9891", "\u4F5C\u54C1\u7BA1\u7406", "\u5185\u5BB9\u7BA1\u7406", "\u521B\u4F5C\u8005\u4E2D\u5FC3"],
    // i18n-ok
    isPublishUrl: (u) => /content\/(publish|post\/video)/.test(u),
    isManageUrl: (u) => /content\/manage/.test(u)
  },
  xiaohongshu: {
    publishUrl: resolvePlatform("xiaohongshu").publishUrl,
    videoTabText: "\u4E0A\u4F20\u89C6\u9891",
    // i18n-ok
    fileInput: 'input[type="file"]',
    titleInput: 'input[placeholder*="\u586B\u5199\u6807\u9898"], input[placeholder*="\u8BF7\u8F93\u5165\u6807\u9898"], input[placeholder*="\u6807\u9898"], textarea[placeholder*="\u6807\u9898"]',
    // i18n-ok
    contentEditor: 'div[contenteditable="true"], .ql-editor, [data-placeholder*="\u6B63\u6587"], [aria-label*="\u6B63\u6587"]',
    // i18n-ok
    submitButton: 'xhs-publish-btn[is-publish="true"][submit-disabled="false"], .publish-page-publish-btn button',
    // Custom element whose host exposes enabled/loading state via attributes.
    // Recent Xiaohongshu builds do not expose an open shadow root, so submit is
    // triggered through the host node contract instead of coordinate clicks.
    submitHost: "xhs-publish-btn",
    submitText: "\u53D1\u5E03",
    // i18n-ok
    uploadProgressTexts: ["\u6B63\u5728\u4E0A\u4F20\u89C6\u9891", "\u89C6\u9891\u4E0A\u4F20\u4E2D", "\u4E0A\u4F20\u4E2D"],
    // i18n-ok
    publishDoneTexts: ["\u53D1\u5E03\u6210\u529F", "\u53D1\u5E03\u5B8C\u6210", "\u5BA1\u6838\u4E2D", "\u7B14\u8BB0\u53D1\u5E03\u6210\u529F", "\u63D0\u4EA4\u6210\u529F"],
    // i18n-ok
    loggedInTexts: ["\u53D1\u5E03\u7B14\u8BB0", "\u521B\u4F5C\u4E2D\u5FC3", "\u6570\u636E\u4E2D\u5FC3"],
    // i18n-ok
    isLoginUrl: (u) => /\/login/.test(u),
    isPublishEditorUrl: (u) => /\/publish\/publish|\/new\/publish/.test(u)
  },
  weixinChannels: {
    createUrl: resolvePlatform("weixin-channels").publishUrl,
    revealUploadText: "\u53D1\u8868\u89C6\u9891",
    // i18n-ok
    fileInput: 'input[type="file"]',
    descEditor: 'div.input-editor[contenteditable="true"], div.input-editor',
    shortTitleInput: 'input[placeholder*="\u586B\u5199\u77ED\u6807\u9898"], input[placeholder*="\u77ED\u6807\u9898"], input.weui-desktop-form__input',
    // i18n-ok
    submitText: "\u53D1\u8868",
    // i18n-ok
    uploadFailed: 'div.status-msg.error, .status-msg.error, [class*="error"]',
    publishDoneTexts: ["\u53D1\u8868\u6210\u529F", "\u53D1\u5E03\u6210\u529F", "\u5DF2\u53D1\u8868", "\u5BA1\u6838\u4E2D", "\u63D0\u4EA4\u6210\u529F"],
    // i18n-ok
    adminVerifyText: "\u7BA1\u7406\u5458\u672C\u4EBA\u9A8C\u8BC1",
    // i18n-ok
    noPermissionText: "\u4F60\u8FD8\u4E0D\u80FD\u53D1\u8868\u89C6\u9891",
    // i18n-ok
    loggedInTexts: ["\u901A\u77E5\u4E2D\u5FC3", "\u5185\u5BB9\u7BA1\u7406", "\u6570\u636E\u4E2D\u5FC3"],
    // i18n-ok
    // QR lives in a CROSS-ORIGIN iframe, so detect the login landing container.
    loginLanding: '.login-view, .login-qrcode-wrap, .qrcode-wrap, iframe[src*="login-for-iframe"], iframe[src*="login"]',
    isLoginUrl: (u) => /login/.test(u),
    isListUrl: (u) => /platform\/post\/list/.test(u)
  },
  bilibili: {
    uploadUrl: resolvePlatform("bilibili").publishUrl,
    manageUrl: resolvePlatform("bilibili").manageUrl,
    fileInput: 'input[type="file"]',
    titleInput: 'input[placeholder*="\u6807\u9898"], textarea[placeholder*="\u6807\u9898"], input[maxlength="80"], input[maxlength="100"]',
    // i18n-ok
    descEditor: 'textarea[placeholder*="\u7B80\u4ECB"], textarea[placeholder*="\u63CF\u8FF0"], div[contenteditable="true"], .ql-editor, .bcc-editor, .desc-textarea textarea',
    // i18n-ok
    tagInput: 'input[placeholder*="\u6807\u7B7E"], input[placeholder*="tag"], input[placeholder*="Tag"], input[placeholder*="Enter"], input[placeholder*="\u56DE\u8F66"]',
    // i18n-ok
    statementInput: 'input[placeholder*="\u521B\u4F5C\u58F0\u660E"]',
    // i18n-ok
    statementOptionText: "\u5185\u5BB9\u65E0\u9700\u6807\u6CE8",
    // i18n-ok
    recommendedTag: ".tag-wrp .hot-tag-container, .tag-list .hot-tag-container",
    coverSelected: ".cover .cover-item, .cover .img-item-cover-selected",
    coverRecommendation: ".cover .img-item-cover",
    submitButton: ".submit-add",
    submitTexts: ["\u7ACB\u5373\u6295\u7A3F", "\u6295\u7A3F", "\u53D1\u5E03"],
    // i18n-ok
    loggedOutTexts: ["\u767B\u5F55", "\u626B\u7801\u767B\u5F55", "\u5BC6\u7801\u767B\u5F55", "\u77ED\u4FE1\u767B\u5F55"],
    // i18n-ok
    loggedInTexts: ["\u521B\u4F5C\u9996\u9875", "\u7A3F\u4EF6\u7BA1\u7406", "\u5185\u5BB9\u7BA1\u7406", "\u6295\u7A3F", "\u521B\u4F5C\u4E2D\u5FC3"],
    // i18n-ok
    uploadDoneTexts: ["\u4E0A\u4F20\u5B8C\u6210", "\u4E0A\u4F20\u6210\u529F", "\u89C6\u9891\u4E0A\u4F20\u5B8C\u6210", "\u4E0A\u4F20\u5B8C\u6BD5"],
    // i18n-ok
    uploadFailedTexts: ["\u4E0A\u4F20\u5931\u8D25", "\u4E0A\u4F20\u51FA\u9519", "\u91CD\u65B0\u4E0A\u4F20"],
    // i18n-ok
    publishDoneTexts: ["\u6295\u7A3F\u6210\u529F", "\u63D0\u4EA4\u6210\u529F", "\u53D1\u5E03\u6210\u529F", "\u5BA1\u6838\u4E2D", "\u7A3F\u4EF6\u6295\u9012\u6210\u529F"],
    // i18n-ok
    isLoginUrl: (u) => /passport\.bilibili\.com|\/login/.test(u),
    isManageUrl: (u) => /upload-manager|content-manager|article/.test(u)
  }
};
var MockAdapter = class {
  constructor(driver, task) {
    this.driver = driver;
    this.task = task;
  }
  driver;
  task;
  async openCreatorPage() {
    await this.driver.setHtml(`
      <main style="font-family: system-ui; padding: 32px;">
        <h1>Mibu Mock Publisher</h1>
        <p>Task: ${escapeHtml(this.task.title)}</p>
        <p id="status">Status: preparing</p>
      </main>
    `);
    await wait2(500);
  }
  async checkLogin() {
    await wait2(300);
    return true;
  }
  async uploadVideo(videoPath) {
    await this.status(`selected video: ${videoPath}`);
    await wait2(700);
  }
  async fillTitle(title) {
    await this.status(`filled title: ${title}`);
    await wait2(400);
  }
  async fillTags(tags) {
    await this.status(`filled tags: ${tags.join(", ") || "none"}`);
    await wait2(400);
  }
  async submit() {
    await this.status("submitted");
    await wait2(500);
  }
  async waitResult() {
    await this.status("publish success");
    await wait2(500);
  }
  async status(message) {
    await this.driver.evaluate(
      `(() => { const n = document.getElementById('status'); if (n) n.textContent = ${JSON.stringify(
        `Status: ${message}`
      )}; })()`
    );
  }
};
var DouyinAdapter = class {
  constructor(driver, task) {
    this.driver = driver;
    this.task = task;
  }
  driver;
  task;
  s = SELECTORS.douyin;
  async openCreatorPage() {
    await this.driver.goto(this.s.uploadUrl);
    const uploadReady = await this.driver.fileInputAttached(this.s.fileInput, 6e3);
    if (!uploadReady && await this.driver.hasText(TEXT_PUBLISH_VIDEO)) {
      await this.driver.clickByText(TEXT_PUBLISH_VIDEO, {
        exact: true,
        selector: "button, [role=button], a, div, span"
      }).catch(() => void 0);
    }
  }
  async checkLogin() {
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasText(text)) {
        return false;
      }
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasText(text)) {
        return true;
      }
    }
    return this.driver.cssAttached(this.s.fileInput, 8e3);
  }
  async uploadVideo(videoPath) {
    await this.driver.cssAttached(this.s.fileInput, ACTION_TIMEOUT);
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.driver.waitForUrl(this.s.isPublishUrl, ACTION_TIMEOUT);
    const settled = await this.driver.waitForFunction(
      `/(${this.s.uploadDoneText}|${this.s.uploadFailedText})/.test(document.body.innerText)`,
      UPLOAD_TIMEOUT,
      1500
    );
    if (!settled) {
      throw new Error("Douyin upload did not complete in time.");
    }
    if (await this.driver.hasText(this.s.uploadFailedText)) {
      throw new Error("Douyin reported video upload failure (\u4E0A\u4F20\u5931\u8D25).");
    }
  }
  async fillTitle(title) {
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillCss(this.s.titleInput, title.slice(0, 30));
  }
  async fillTags(tags) {
    const description = stringOption(this.task, "description");
    if (description) {
      await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
      await this.driver.insertText(this.s.descEditor, description);
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const topicText = `#${normalizedTag}`;
      await this.driver.insertText(this.s.descEditor, ` ${topicText}`);
      await wait2(800);
      const pickedTopic = await this.driver.clickCenterByText(topicText, {
        selector: '[class*="mention-suggest"] div, [class*="mention-suggest"] span'
      }).then(() => true).catch(() => false);
      if (pickedTopic) {
        await this.driver.waitForFunction(
          `[...document.querySelectorAll('[data-mention="#"]')].some((el) => (el.textContent || '').includes(${JSON.stringify(
            topicText
          )}))`,
          2e3,
          200
        );
      } else {
        await this.driver.pressKey("Space");
      }
      await this.driver.insertText(this.s.descEditor, " ");
      await wait2(300);
    }
    await this.driver.pressKey("Escape");
  }
  async submit() {
    await this.driver.removeElements(this.s.overlays);
    await this.driver.clickByText(this.s.submitText, { exact: true }).catch(() => this.driver.clickByText(this.s.submitText));
  }
  async waitResult() {
    const ok = await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT);
    if (!ok) {
      throw new Error("Douyin did not confirm publish (no redirect to content management).");
    }
  }
};
var XiaohongshuAdapter = class {
  constructor(driver, task) {
    this.driver = driver;
    this.task = task;
  }
  driver;
  task;
  s = SELECTORS.xiaohongshu;
  async openCreatorPage() {
    await this.driver.goto(this.s.publishUrl);
    await this.driver.clickByText(this.s.videoTabText, {
      exact: true,
      selector: "button, [role=button], a, div, span"
    }).catch(() => void 0);
  }
  async checkLogin() {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasText(text)) {
        return true;
      }
    }
    return this.driver.cssAttached(this.s.fileInput, 4e3);
  }
  async uploadVideo(videoPath) {
    await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    await this.driver.setFiles(this.s.fileInput, videoPath);
    const ready = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!ready) {
      throw new Error("Xiaohongshu editor did not appear after upload (title field missing).");
    }
    const publishReady = await this.driver.waitCssEnabled(this.s.submitButton, UPLOAD_TIMEOUT) || await this.driver.waitTextEnabledDeep(this.s.submitText, 1e3, {
      hostSelector: this.s.submitHost
    });
    if (!publishReady) {
      throw new Error(
        "Xiaohongshu upload did not finish in time (publish button stayed disabled)."
      );
    }
  }
  async fillTitle(title) {
    const value = title.slice(0, 20);
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillCss(this.s.titleInput, value);
    const accepted = await this.driver.waitForFunction(
      `(() => {
        const el = document.querySelector(${JSON.stringify(this.s.titleInput)});
        return el && el.value === ${JSON.stringify(value)};
      })()`,
      3e3,
      200
    );
    const current = await this.driver.cssValue(this.s.titleInput);
    if (!accepted || current !== value) {
      throw new Error("Xiaohongshu title input did not accept the filled value.");
    }
  }
  async fillTags(tags) {
    const description = stringOption(this.task, "description");
    if (description) {
      await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
      await this.driver.insertText(this.s.contentEditor, description);
      await this.driver.insertText(this.s.contentEditor, " ");
      const accepted = await this.driver.waitForFunction(
        `(() => (document.querySelector(${JSON.stringify(
          this.s.contentEditor
        )})?.innerText || '').includes(${JSON.stringify(description)}))()`,
        3e3,
        200
      );
      if (!accepted) {
        throw new Error("Xiaohongshu content editor did not accept the description.");
      }
    }
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.contentEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      await this.driver.insertText(this.s.contentEditor, `#${normalizedTag}`);
      await this.driver.waitForFunction(
        `(() => {
          const target = ${JSON.stringify(`#${normalizedTag}`)};
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
          };
          return [
            ...document.querySelectorAll(
              '#creator-editor-topic-container .item, [data-tippy-root] .item, .tippy-content .item'
            )
          ].some((el) => visible(el) && (el.textContent || '').includes(target));
        })()`,
        2500,
        200
      );
      const picked = await this.driver.clickXiaohongshuTopicCandidate(normalizedTag) || await this.driver.clickByText(TEXT_NEW_TOPIC, {
        exact: true,
        selector: "#creator-editor-topic-container *, [data-tippy-root] *, .tippy-content *"
      }).then(() => true).catch(() => false);
      if (!picked) {
        await this.driver.pressKey("Enter");
      }
      const selected = await this.driver.waitForFunction(
        `(() => [...document.querySelectorAll('a.tiptap-topic')].some((el) => { // i18n-ok
          const data = el.getAttribute('data-topic') || '';
          const text = (el.textContent || '').replace('[\u8BDD\u9898]#', '').replace(/^#/, '').trim();
          return text === ${JSON.stringify(normalizedTag)} || data.includes(${JSON.stringify(
          `"name":"${normalizedTag}"`
        )});
        }))()`,
        5e3,
        300
      );
      if (!selected && !await this.driver.hasXiaohongshuTopic(normalizedTag)) {
        throw new Error(`Xiaohongshu topic was not selected: #${normalizedTag}`);
      }
      await this.driver.insertText(this.s.contentEditor, " ");
    }
  }
  async submit() {
    const ready = await this.driver.waitCssEnabled(this.s.submitButton, ACTION_TIMEOUT) || await this.driver.waitTextEnabledDeep(this.s.submitText, 1e3, {
      hostSelector: this.s.submitHost
    });
    if (!ready) {
      throw new Error("Xiaohongshu publish button is not clickable.");
    }
    if (await this.driver.publishXiaohongshuCustomElement(this.s.submitHost)) {
      return;
    }
    if (await this.driver.clickInShadow(this.s.submitHost, this.s.submitText)) {
      return;
    }
    if (await this.driver.activateCustomElement(this.s.submitHost)) {
      return;
    }
    await this.driver.clickByText(this.s.submitText, {
      exact: true,
      selector: "button, [role=button], div, span"
    });
  }
  async waitResult() {
    const donePattern = this.s.publishDoneTexts.join("|");
    await wait2(1e3);
    const ok = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return true;
        const url = location.href;
        const isEditor = /\\/publish\\/publish|\\/new\\/publish/.test(url);
        const hasPublishHost = Boolean(document.querySelector(${JSON.stringify(this.s.submitHost)}));
        return !isEditor && !hasPublishHost && /creator\\.xiaohongshu\\.com/.test(url);
      })()`,
      RESULT_TIMEOUT,
      1e3
    );
    if (!ok) {
      throw new Error(
        "Xiaohongshu did not confirm publish (no success text and still on/near the publish editor)."
      );
    }
  }
};
var WeixinChannelsAdapter = class {
  constructor(driver, task) {
    this.driver = driver;
    this.task = task;
  }
  driver;
  task;
  s = SELECTORS.weixinChannels;
  async openCreatorPage() {
    await this.driver.goto(this.s.createUrl);
  }
  async checkLogin() {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    if (await this.driver.cssVisible(this.s.loginLanding, 2500)) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    return this.driver.fileInputAttached(this.s.fileInput, 4e3);
  }
  async uploadVideo(videoPath) {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    let attached = await this.driver.fileInputAttached(this.s.fileInput, 8e3);
    if (!attached) {
      await this.driver.clickByText(this.s.revealUploadText).catch(() => void 0);
      attached = await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    }
    if (!attached) {
      throw new Error("WeChat Channels upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const ok = await this.driver.waitButtonEnabled(this.s.submitText, UPLOAD_TIMEOUT);
    if (!ok) {
      if (await this.driver.cssVisible(this.s.uploadFailed, 500)) {
        throw new Error("WeChat Channels reported an upload error (status-msg.error).");
      }
      throw new Error("WeChat Channels upload did not complete in time.");
    }
  }
  async fillTitle(title) {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const description = stringOption(this.task, "description") ?? title;
    const shortTitle = stringOption(this.task, "shortTitle") ?? title;
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    await this.driver.insertText(this.s.descEditor, description);
    if (await this.driver.cssVisible(this.s.shortTitleInput, 2e3)) {
      await this.driver.fillCss(this.s.shortTitleInput, shortTitle.slice(0, 16)).catch(() => void 0);
    } else {
      await this.driver.fillInputNearText("\u77ED\u6807\u9898", shortTitle.slice(0, 16)).catch(() => false);
    }
  }
  async fillTags(tags) {
    if (!tags.length) {
      return;
    }
    await this.driver.cssVisible(this.s.descEditor, ACTION_TIMEOUT);
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      await this.driver.insertText(this.s.descEditor, ` #${normalizedTag}`);
      await this.driver.pressKey("Space");
      await wait2(300);
    }
  }
  async submit() {
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
    const ready = await this.driver.waitButtonEnabled(this.s.submitText, ACTION_TIMEOUT);
    if (!ready) {
      throw new Error("WeChat Channels publish button is not clickable.");
    }
    await this.driver.clickByTextDeep(this.s.submitText, { exact: true }).catch(() => this.driver.clickByText(this.s.submitText, { exact: true }));
    await this.waitForHumanGateIfNeeded();
    await this.assertCanPublish();
  }
  async waitResult() {
    const donePattern = this.s.publishDoneTexts.join("|");
    const ok = await this.driver.waitForUrl(this.s.isListUrl, RESULT_TIMEOUT) || await this.driver.waitForFunction(
      `(() => {
          const seen = new Set();
          const collect = (root) => {
            if (!root || seen.has(root)) return '';
            seen.add(root);
            let text = root instanceof Document ? (root.body?.innerText || '') : (root.textContent || '');
            for (const el of root.querySelectorAll ? root.querySelectorAll('*') : []) {
              if (el.shadowRoot) text += '\\n' + collect(el.shadowRoot);
            }
            return text;
          };
          return new RegExp(${JSON.stringify(donePattern)}).test(collect(document));
        })()`,
      1e4
    );
    if (!ok) {
      throw new Error("WeChat Channels did not confirm publish (no redirect to post list).");
    }
  }
  async waitForHumanGateIfNeeded() {
    if (await this.driver.hasTextDeep(this.s.adminVerifyText)) {
      const cleared = await this.driver.waitTextGoneDeep(
        this.s.adminVerifyText,
        HUMAN_INTERVENTION_TIMEOUT,
        2e3
      );
      if (!cleared) {
        throw new AutomationBlockedError(
          "manual_required",
          "WeChat Channels requires admin verification. Complete the QR verification in the embedded view, then retry."
        );
      }
    }
  }
  async assertCanPublish() {
    if (await this.driver.hasTextDeep(this.s.noPermissionText)) {
      throw new AutomationBlockedError(
        "permission_required",
        "WeChat Channels says this WeChat account is not an admin/operator for the selected channel."
      );
    }
  }
};
var BilibiliAdapter = class {
  constructor(driver, task) {
    this.driver = driver;
    this.task = task;
  }
  driver;
  task;
  s = SELECTORS.bilibili;
  async openCreatorPage() {
    await this.driver.goto(this.s.uploadUrl);
  }
  async checkLogin() {
    if (this.s.isLoginUrl(this.driver.url())) {
      return false;
    }
    for (const text of this.s.loggedInTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return true;
      }
    }
    if (await this.driver.cssAttached(this.s.fileInput, 6e3)) {
      return true;
    }
    for (const text of this.s.loggedOutTexts) {
      if (await this.driver.hasTextDeep(text)) {
        return false;
      }
    }
    return false;
  }
  async uploadVideo(videoPath) {
    const attached = await this.driver.fileInputAttached(this.s.fileInput, ACTION_TIMEOUT);
    if (!attached) {
      throw new Error("Bilibili upload input not found.");
    }
    await this.driver.setFiles(this.s.fileInput, videoPath);
    const editorReady = await this.driver.cssVisible(this.s.titleInput, UPLOAD_TIMEOUT);
    if (!editorReady) {
      throw new Error("Bilibili editor did not appear after upload (title field missing).");
    }
    const donePattern = this.s.uploadDoneTexts.join("|");
    const failedPattern = this.s.uploadFailedTexts.join("|");
    const settled = await this.driver.waitForFunction(
      `(() => {
        const text = document.body?.innerText || '';
        if (new RegExp(${JSON.stringify(failedPattern)}).test(text)) return true;
        if (new RegExp(${JSON.stringify(donePattern)}).test(text)) return true;
        return Boolean(document.querySelector(${JSON.stringify(this.s.titleInput)}));
      })()`,
      UPLOAD_TIMEOUT,
      1e3
    );
    if (!settled) {
      throw new Error("Bilibili upload did not complete in time.");
    }
    if (await this.driver.waitForFunction(
      `new RegExp(${JSON.stringify(failedPattern)}).test(document.body?.innerText || '')`,
      500,
      100
    )) {
      throw new Error("Bilibili reported video upload failure.");
    }
  }
  async fillTitle(title) {
    const value = title.slice(0, 80);
    await this.driver.cssVisible(this.s.titleInput, ACTION_TIMEOUT);
    await this.driver.fillField(this.s.titleInput, value);
    const current = await this.driver.cssValue(this.s.titleInput);
    if (!current?.includes(value)) {
      throw new Error("Bilibili title input did not accept the filled value.");
    }
  }
  async fillTags(tags) {
    await this.selectCreationStatement();
    const description = stringOption(this.task, "description");
    if (description) {
      if (await this.driver.cssVisible(this.s.descEditor, 5e3)) {
        await this.driver.fillField(this.s.descEditor, description);
      } else {
        await this.driver.fillInputNearText("\u7B80\u4ECB", description).catch(() => false);
      }
    }
    for (const tag of tags) {
      const normalizedTag = normalizeTag(tag);
      if (!normalizedTag) {
        continue;
      }
      const inserted = await this.clickRecommendedTag(normalizedTag) || await this.inputTag(normalizedTag) || await this.driver.fillInputNearText("\u6807\u7B7E", normalizedTag).then(async (ok) => {
        if (ok) {
          await this.driver.pressKey("Enter");
          return this.waitForTagChip(normalizedTag);
        }
        return false;
      }).catch(() => false) || await this.clickAnyRecommendedTag();
      if (!inserted) {
        throw new Error(`Bilibili tag was not accepted: #${normalizedTag}`);
      }
      await wait2(200);
    }
    await this.selectRecommendedCover();
  }
  async submit() {
    if (await this.driver.cssVisible(this.s.submitButton, 5e3)) {
      await this.driver.clickCenterCss(this.s.submitButton);
      return;
    }
    for (const text of this.s.submitTexts) {
      const clicked = await this.driver.clickByText(text, {
        exact: true,
        selector: "button, [role=button], a, div, span"
      }).then(() => true).catch(() => false);
      if (clicked) {
        return;
      }
    }
    throw new Error("Bilibili publish button was not found.");
  }
  async waitResult() {
    const donePattern = this.s.publishDoneTexts.join("|");
    const ok = await this.driver.waitForUrl(this.s.isManageUrl, RESULT_TIMEOUT) || await this.driver.waitForFunction(
      `new RegExp(${JSON.stringify(donePattern)}).test(document.body?.innerText || '')`,
      RESULT_TIMEOUT,
      1e3
    );
    if (!ok) {
      throw new Error("Bilibili did not confirm publish (no success text or manager redirect).");
    }
  }
  async inputTag(tag) {
    const focused = await this.driver.focusAndClearField(this.s.tagInput);
    if (!focused) {
      return false;
    }
    await this.driver.type(tag);
    await this.driver.pressKey("Enter");
    return this.waitForTagChip(tag);
  }
  async selectCreationStatement() {
    const selected = await this.driver.evaluate(`(() => {
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
    const clicked = await this.driver.evaluate(`(() => {
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
      3e3,
      250
    );
    if (!accepted) {
      throw new Error("Bilibili creation statement did not become selected.");
    }
  }
  async clickRecommendedTag(tag) {
    const expected = JSON.stringify(tag);
    const clicked = await this.driver.evaluate(`(() => {
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
  async clickAnyRecommendedTag() {
    const before = await this.driver.evaluate(
      `document.querySelectorAll('#tag-container .label-item-v2-content').length`
    );
    const clicked = await this.driver.evaluate(`(() => {
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
      3e3,
      250
    );
  }
  async selectRecommendedCover() {
    const alreadySelected = await this.driver.cssVisible(this.s.coverSelected, 2e3);
    if (alreadySelected) {
      return;
    }
    const clicked = await this.driver.evaluate(`(() => {
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
      return;
    }
    const selected = await this.driver.cssVisible(this.s.coverSelected, 5e3);
    if (!selected) {
      throw new Error("Bilibili recommended cover did not become selected.");
    }
  }
  async waitForTagChip(tag) {
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
      3e3,
      250
    );
  }
};
var createAdapter = (platform, driver, task) => {
  const normalizedPlatform = resolvePlatform(platform).id;
  if (normalizedPlatform === "douyin") {
    return new DouyinAdapter(driver, task);
  }
  if (normalizedPlatform === "xiaohongshu") {
    return new XiaohongshuAdapter(driver, task);
  }
  if (normalizedPlatform === "weixin-channels") {
    return new WeixinChannelsAdapter(driver, task);
  }
  if (normalizedPlatform === "bilibili") {
    return new BilibiliAdapter(driver, task);
  }
  return new MockAdapter(driver, task);
};

// electron/publish/backend.ts
var BASE = process.env.MIBU_BACKEND_URL || `http://127.0.0.1:${process.env.MIBU_BACKEND_PORT || 8800}`;
async function req(path4, method = "GET", body) {
  const res = await fetch(`${BASE}/api/publish${path4}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : void 0,
    body: body ? JSON.stringify(body) : void 0
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    plog("req failed:", method, path4, res.status, detail.slice(0, 300));
    throw new Error(`${method} ${path4} \u2192 ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : {};
}
function claimTask(excludeAccounts = []) {
  return req("/worker/claim", "POST", { exclude_accounts: excludeAccounts });
}
function claimCheck() {
  return req("/worker/claim-check", "POST");
}
function markDue() {
  return req("/worker/mark-due", "POST");
}
function reportTask(taskId, patch) {
  return req("/worker/report", "PATCH", { task_id: taskId, ...patch });
}
function patchAccount(accountId, patch) {
  return req("/worker/account", "PATCH", { account_id: accountId, ...patch });
}
function heartbeat() {
  return req("/worker/heartbeat", "POST");
}

// electron/publish/worker.ts
var views = null;
var running = /* @__PURE__ */ new Set();
var MAX_CONCURRENT = (() => {
  const n = Number.parseInt(process.env.MIBU_PUBLISH_CONCURRENCY || "", 10);
  return Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 3;
})();
var stopped = false;
var generation = 0;
var loginPollTimer = null;
var onSettled = null;
function settle(t, status, dryRun) {
  try {
    onSettled?.({ status, title: t.title, accountName: t.accountName, dryRun });
  } catch {
  }
}
var POLL_IDLE_MS = 4e3;
var POLL_BUSY_MS = 500;
var stepDelay = () => 700 + Math.floor(Math.random() * 1100);
var delay = (ms) => new Promise((r) => setTimeout(r, ms));
function requestFront(accountId) {
  if (!views || views.visibleAccountId) return false;
  views.show(accountId);
  return true;
}
function resolveBlockedStatus(error) {
  if (!isAutomationBlockedError(error)) return null;
  if (error.reason === "manual_required") return "waiting_manual";
  if (error.reason === "login_required") return "login_required";
  if (error.reason === "permission_required") return "permission_required";
  return "blocked";
}
function toAdapterTask(t) {
  return {
    id: t.id,
    accountId: t.account_id,
    accountName: t.account_name,
    platform: resolvePlatform(t.platform).id,
    videoPath: t.video_path,
    title: t.title,
    tags: t.tags || [],
    platformOptions: {
      dryRun: t.dry_run,
      description: t.description || "",
      shortTitle: t.short_title || ""
    },
    scheduledAt: null,
    status: "running",
    errorMessage: null,
    screenshotPath: null,
    createdAt: "",
    updatedAt: ""
  };
}
async function captureFailure(taskId, driver) {
  try {
    const dir = import_node_path3.default.join(import_electron3.app.getPath("userData"), "publish-screenshots");
    await (0, import_promises2.mkdir)(dir, { recursive: true });
    const file = import_node_path3.default.join(dir, `${taskId}-${Date.now()}.png`);
    await driver.screenshot(file);
    return file;
  } catch {
    return null;
  }
}
async function runTask(bt) {
  if (!views) {
    plog("runTask aborted (views=null):", bt.id);
    running.delete(bt.account_id);
    return;
  }
  plog("runTask start:", bt.id, bt.platform, bt.video_path);
  const t = toAdapterTask(bt);
  const driver = views.getDriver(t.accountId);
  try {
    await views.configureAccount(t.accountId, null);
    const adapter = createAdapter(t.platform, driver, t);
    await adapter.openCreatorPage();
    plog("runTask creator page opened:", bt.id, driver.url());
    await delay(stepDelay());
    const loggedIn = await adapter.checkLogin();
    plog("runTask checkLogin:", bt.id, loggedIn);
    if (!loggedIn) {
      await patchAccount(t.accountId, {
        binding_status: "login_required",
        last_error: tr("\u672A\u767B\u5F55")
      });
      await reportTask(t.id, {
        status: "login_required",
        error_message: tr("\u8D26\u53F7\u672A\u767B\u5F55\u3002\u5728\u53D1\u5E03\u63A7\u5236\u53F0\u70B9\u8BE5\u8D26\u53F7\u300C\u767B\u5F55\u300D\u5B8C\u6210\u626B\u7801\u540E\u91CD\u8BD5\u3002")
      });
      settle(t, "login_required", t.platformOptions.dryRun === true);
      return;
    }
    await patchAccount(t.accountId, { binding_status: "bound", last_error: null });
    await adapter.uploadVideo(t.videoPath);
    await delay(stepDelay());
    await adapter.fillTitle(t.title);
    await delay(stepDelay());
    await adapter.fillTags(t.tags);
    await delay(stepDelay());
    if (t.platformOptions.dryRun === true) {
      await reportTask(t.id, { status: "prepared" });
      settle(t, "prepared", true);
      requestFront(t.accountId);
      return;
    }
    await adapter.submit();
    await delay(stepDelay());
    await adapter.waitResult();
    await reportTask(t.id, { status: "success" });
    plog("runTask success:", t.id);
    settle(t, "success", false);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    plog("runTask error:", t.id, error instanceof Error ? error : message);
    const screenshot = await captureFailure(t.id, driver);
    const blocked = resolveBlockedStatus(error);
    if (blocked === "login_required")
      await patchAccount(t.accountId, {
        binding_status: "login_required",
        last_error: message
      });
    else if (blocked === "waiting_manual")
      await patchAccount(t.accountId, {
        binding_status: "manual_required",
        last_error: message
      });
    else if (blocked === "permission_required")
      await patchAccount(t.accountId, {
        binding_status: "permission_required",
        last_error: message
      });
    await reportTask(t.id, {
      status: blocked ?? "failed",
      error_message: message,
      screenshot_path: screenshot
    });
    settle(t, blocked ?? "failed", t.platformOptions.dryRun === true);
    const hasLive = (() => {
      try {
        const url = driver.url();
        return Boolean(url) && url !== "about:blank";
      } catch {
        return false;
      }
    })();
    if (hasLive) requestFront(t.accountId);
  } finally {
    running.delete(t.accountId);
    driver.setAbortSignal(null);
  }
}
async function checkAccountStatus(acc) {
  if (!views) return;
  const platform = resolvePlatform(acc.platform).id;
  const stub = {
    id: `check-${acc.account_id}`,
    accountId: acc.account_id,
    accountName: acc.name ?? "",
    platform,
    videoPath: "",
    title: "",
    tags: [],
    platformOptions: { dryRun: true, description: "", shortTitle: "" },
    scheduledAt: null,
    status: "running",
    errorMessage: null,
    screenshotPath: null,
    createdAt: "",
    updatedAt: ""
  };
  try {
    plog("recheck start:", acc.account_id, platform);
    await views.configureAccount(acc.account_id, null);
    const driver = views.getDriver(acc.account_id);
    const adapter = createAdapter(platform, driver, stub);
    await adapter.openCreatorPage();
    const loggedIn = await adapter.checkLogin();
    plog("recheck result:", acc.account_id, loggedIn ? "bound" : "login_required");
    await patchAccount(acc.account_id, {
      binding_status: loggedIn ? "bound" : "login_required",
      last_error: loggedIn ? null : tr("\u767B\u5F55\u5DF2\u5931\u6548,\u8BF7\u91CD\u65B0\u767B\u5F55")
    });
    if (acc.binding_status === "bound" && !loggedIn) {
      settle(stub, "login_required", false);
    }
  } catch (error) {
    plog("recheck error:", acc.account_id, error instanceof Error ? error : String(error));
    await patchAccount(acc.account_id, {
      binding_status: acc.binding_status && acc.binding_status !== "checking" ? acc.binding_status : "unknown",
      last_error: null
    }).catch(() => void 0);
  }
}
async function loop(gen) {
  if (stopped || gen !== generation) return;
  let didWork = false;
  try {
    await heartbeat();
    while (running.size < MAX_CONCURRENT) {
      const { task } = await claimTask([...running]);
      if (!task) break;
      plog("claimed:", task.id, task.platform, "account:", task.account_id);
      didWork = true;
      running.add(task.account_id);
      void runTask(task).catch((error) => {
        plog("runTask crashed before report:", task.id, error instanceof Error ? error : String(error));
        running.delete(task.account_id);
      });
    }
    if (running.size === 0 && !views?.visibleAccountId) {
      const { account } = await claimCheck();
      if (account) {
        didWork = true;
        running.add(account.account_id);
        try {
          await checkAccountStatus(account);
        } finally {
          running.delete(account.account_id);
        }
      }
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (!/fetch failed|ECONNREFUSED|aborted/i.test(msg)) plog("loop error:", msg);
  }
  if (!stopped && gen === generation)
    setTimeout(() => loop(gen), didWork ? POLL_BUSY_MS : POLL_IDLE_MS);
}
function startPublishWorker(opts) {
  if (views) return;
  stopped = false;
  generation += 1;
  running.clear();
  onSettled = opts.onTaskSettled ?? null;
  views = new AccountViewManager(opts.onViewChanged);
  views.attachWindow(opts.window, opts.getAccountName ?? (() => null));
  plog("worker started, generation", generation);
  void markDue().catch(() => void 0);
  loop(generation);
}
function stopPublishWorker() {
  stopped = true;
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
  views?.destroyAll();
  views = null;
  running.clear();
  onSettled = null;
}
function endLogin(gen) {
  if (gen !== generation) return;
  if (loginPollTimer) {
    clearTimeout(loginPollTimer);
    loginPollTimer = null;
  }
}
async function openLogin(accountId, platform) {
  if (!views) return;
  if (running.has(accountId)) throw new Error(tr("\u8BE5\u8D26\u53F7\u6709\u53D1\u5E03\u4EFB\u52A1\u6B63\u5728\u8FDB\u884C\uFF0C\u8BF7\u7B49\u5B83\u5B8C\u6210\u540E\u518D\u767B\u5F55"));
  if (views.visibleAccountId && views.visibleAccountId !== accountId)
    throw new Error(tr("\u6709\u8D26\u53F7\u6B63\u5728\u524D\u53F0\u64CD\u4F5C\uFF0C\u8BF7\u5148\u5904\u7406\u5B8C\u518D\u767B\u5F55"));
  const gen = generation;
  try {
    await views.configureAccount(accountId, null);
    const driver = views.getDriver(accountId);
    views.show(accountId);
    const def = resolvePlatform(platform);
    await patchAccount(accountId, { binding_status: "checking" });
    await driver.goto(def.loginUrl);
    const adapter = createAdapter(platform, driver, {
      id: `login-${accountId}`,
      accountId,
      accountName: "",
      platform: def.id,
      videoPath: "",
      title: "",
      tags: [],
      platformOptions: {},
      scheduledAt: null,
      status: "running",
      errorMessage: null,
      screenshotPath: null,
      createdAt: "",
      updatedAt: ""
    });
    const deadline = Date.now() + 10 * 60 * 1e3;
    const poll = async () => {
      loginPollTimer = null;
      if (stopped || gen !== generation || !views || Date.now() > deadline) {
        endLogin(gen);
        return;
      }
      let ok = false;
      try {
        ok = await adapter.checkLogin();
      } catch {
      }
      if (stopped || gen !== generation || !views) {
        endLogin(gen);
        return;
      }
      if (ok) {
        try {
          await patchAccount(accountId, { binding_status: "bound", last_error: null });
        } catch {
        }
        endLogin(gen);
        return;
      }
      loginPollTimer = setTimeout(poll, 5e3);
    };
    void poll();
  } catch (error) {
    endLogin(gen);
    throw error;
  }
}
async function openPage(accountId, platform) {
  if (!views) return;
  if (views.visibleAccountId && views.visibleAccountId !== accountId) {
    views.show(views.visibleAccountId);
    return;
  }
  await views.configureAccount(accountId, null);
  const driver = views.getDriver(accountId);
  const current = driver.url();
  views.show(accountId);
  if (!current || current === "about:blank") {
    const def = resolvePlatform(platform);
    await driver.goto(def.dashboardUrl || def.loginUrl);
  }
}
function hidePublishView() {
  views?.hide();
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  hidePublishView,
  openLogin,
  openPage,
  setLocale,
  startPublishWorker,
  stopPublishWorker
});

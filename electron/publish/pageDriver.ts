import type { NativeImage, WebContents } from "electron";
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
 *
 * ## 点击方法的命名约定:`pointerClick*` 前缀
 *
 * 两类点击的能力和风险**完全不同**,所以特例必须在名字上看得见:
 *
 *  - `pointerClick*`(pointerClickCss / pointerClickByText / pointerClickByTextDeep)
 *    发**真实鼠标事件**(sendInputEvent → humanClickAt)。事件 `isTrusted === true`,风控友好,
 *    是关键动作(提交/投稿)的首选。代价:需要视图有真实布局(后台视图视口 0×0 时坐标无意义),
 *    而且要做命中测试——被浮层遮挡就点不到。这两种情况都会**显式抛错**,让调用方降级。
 *  - 其余 click*(clickCss / clickByText / clickInShadow / activateCustomElement)派发 **DOM 事件**
 *    (`el.click()` / `dispatchEvent`)。不受视口与遮挡影响,点得到,但 `isTrusted === false`。
 *
 * 前缀只加在 pointer 一族:它是受约束的特例,DOM 事件是默认。
 *
 * 这个约定是有代价换来的:`clickByTextDeep` 曾经只比 `clickByText` 多一个 `Deep`,读起来像
 * 「穿透 shadow 的同款」,实际上机制换了。微信视频号的提交用的正是它,于是和 B 站一样受视口
 * 影响——而这个潜伏 bug 之所以长期没被发现,很大程度就是名字掩盖了差异。
 */
export class PageDriver {
  private debuggerAttached = false;
  private abortSignal: AbortSignal | null = null;
  private latestFrame: NativeImage | null = null; // 离屏渲染的最近一帧(paint 事件),供预览/截图

  constructor(private readonly wc: WebContents) {
    // 离屏渲染(offscreen)的视图靠 paint 事件出帧;非离屏视图不触发,无害。
    try {
      this.wc.on("paint", (_event, _dirty, image) => {
        this.latestFrame = image;
      });
    } catch {
      /* 某些环境无 paint 事件,忽略 */
    }
  }

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

  /**
   * 坐标点击的前提:视图**有真实布局**。
   *
   * 后台跑任务的发布账号视图没有挂进窗口,视口就是 0×0——此时 `scrollIntoView` 会把元素"居中"
   * 到负坐标,`sendInputEvent` 打过去落在空处,**点了等于没点,而且不报错**。上传(CDP)、填表
   * (JS)都不用坐标所以照常成功,于是表现成「表单填得好好的,就是发不出去」。
   *
   * electron 实测:未挂载 / 挂载但 bounds 移出屏幕 / 挂在窗口可视区下方,视口一律 0×0;只有真正
   * 在可视区内的挂载视图才有布局。所以这里必须**显式失败**,让调用方走 `el.click()` 那条不依赖
   * 坐标的兜底——而不是静默地什么都没做。
   */
  /** 等元素位置连续两拍不变(平滑滚动停下来了)。最多等 1.2s,等不稳也照常继续。 */
  private async waitForRectStable(selector: string): Promise<void> {
    const readTop = `(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      return el ? Math.round(el.getBoundingClientRect().top) : null;
    })()`;
    let previous: number | null = null;
    for (let i = 0; i < 8; i++) {
      const top = await this.evaluate<number | null>(readTop).catch(() => null);
      if (top !== null && top === previous) return;
      previous = top;
      await this.wait(150);
    }
  }

  private ensurePointerUsable(viewport: { vw: number; vh: number }, what: string): void {
    if (viewport.vw > 0 && viewport.vh > 0) return;
    throw new Error(
      `${what}: view has no layout (viewport ${viewport.vw}x${viewport.vh}); pointer coordinates are meaningless`,
    );
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

  /**
   * 生成一段 JS 前缀,注入后可用 `find(root)` 取到匹配 `selector` 的元素——会**穿透 open shadow
   * root** 递归查找,并优先返回可见的那个。平台无关,适配器写平台专有脚本时也要用,故公开。
   */
  deepQueryPrelude(selector: string): string {
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

  /**
   * 在元素上派发**完整的指针事件序列**(pointerover → pointerdown → mousedown → pointerup →
   * mouseup → click),全程不依赖坐标命中测试。
   *
   * 为什么需要它:`el.click()` 只发一个 `click` 事件。B 站的「立即投稿」是个
   * `<span class="submit-add">`,处理器挂在 pointerdown / mousedown 上时,只发 click 就**毫无反应**
   * ——线上实测:上传已完成、按钮可见未禁用、可信指针点击与 el.click() 都送达过,页面依然不动。
   * 而真实指针点击又依赖视口与命中测试,后台视图里容易落空。这一条把两边的短板都避开:事件齐全,
   * 且不需要"点得中"。代价是 isTrusted 为 false,所以它排在可信点击之后当降级。
   */
  async dispatchFullClickCss(selector: string): Promise<void> {
    const ok = await this.evaluate<boolean>(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (!el) return false;
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      const r = el.getBoundingClientRect();
      const base = {
        bubbles: true, cancelable: true, composed: true, view: window,
        clientX: r.x + r.width / 2, clientY: r.y + r.height / 2,
        button: 0, detail: 1,
      };
      const pointer = { ...base, pointerId: 1, pointerType: 'mouse', isPrimary: true };
      const fire = (Ctor, type, extra) => el.dispatchEvent(new Ctor(type, { ...extra }));
      fire(PointerEvent, 'pointerover', { ...pointer, buttons: 0 });
      fire(MouseEvent, 'mouseover', { ...base, buttons: 0 });
      fire(PointerEvent, 'pointerdown', { ...pointer, buttons: 1 });
      fire(MouseEvent, 'mousedown', { ...base, buttons: 1 });
      if (typeof el.focus === 'function') el.focus();
      fire(PointerEvent, 'pointerup', { ...pointer, buttons: 0 });
      fire(MouseEvent, 'mouseup', { ...base, buttons: 0 });
      fire(MouseEvent, 'click', { ...base, buttons: 0 });
      return true;
    })()`);
    if (!ok) {
      throw new Error(`dispatchFullClickCss: element not found: ${selector}`);
    }
  }

  async pointerClickCss(selector: string): Promise<void> {
    // scrollIntoView 之后必须**等滚动停下来**再读 rect:页面若是平滑滚动,同步读到的是滚动前的
    // 位置,而 humanClickAt 还要花 100–200ms 移动鼠标,真正点下去时按钮早已不在那儿 —— 命中测试
    // 在 t0 通过、在点击时刻却落空,且不报错。先滚,再等位置稳定,最后才取 rect 与命中测试。
    await this.evaluate(`(() => {
      ${this.deepQueryPrelude(selector)}
      const el = find(document);
      if (el) el.scrollIntoView({ block: 'center', inline: 'nearest' });
    })()`);
    await this.waitForRectStable(selector);

    // 视口尺寸和 rect 一起取回:同一次 evaluate,不多花一个来回。
    const found = await this.evaluate<{
      x: number;
      y: number;
      width: number;
      height: number;
      vw: number;
      vh: number;
      hit: boolean;
      at: string;
      target: string;
      disabled: boolean;
    } | null>(
      `(() => {
        ${this.deepQueryPrelude(selector)}
        const el = find(document);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return null;
        const cx = Math.round(r.x + r.width / 2), cy = Math.round(r.y + r.height / 2);
        // 落点上**实际**是谁。选择器命中不等于点得到:浮层/遮罩/粘性页脚都会把点击截走,
        // 而 sendInputEvent 打的是坐标,截走了也没人报错。
        const at = document.elementFromPoint(cx, cy);
        const describe = (n) => n
          ? n.tagName + '.' + String(n.className || '').slice(0, 40) + '|' + (n.textContent || '').trim().slice(0, 24)
          : 'null';
        return {
          x: r.x, y: r.y, width: r.width, height: r.height, vw: innerWidth, vh: innerHeight,
          hit: Boolean(at && (at === el || el.contains(at) || at.contains(el))),
          at: describe(at), target: describe(el),
          disabled: Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true'
            || /disabled/.test(String(el.className || '')),
        };
      })()`,
    );
    if (!found) {
      throw new Error(`pointerClickCss: element not found: ${selector}`);
    }
    this.ensurePointerUsable(found, "pointerClickCss");
    plog("pointerClickCss:", selector, {
      target: found.target,
      at: found.at,
      hit: found.hit,
      disabled: found.disabled,
      rect: [Math.round(found.x), Math.round(found.y), Math.round(found.width), Math.round(found.height)],
      viewport: [found.vw, found.vh],
    });
    // 点不到就别假装点了:抛出去让调用方走 el.click() 一类不受遮挡影响的兜底,
    // 而不是打一发空枪再等五分钟超时。
    if (!found.hit) {
      throw new Error(`pointerClickCss: point is covered by ${found.at} (target ${found.target})`);
    }
    if (found.disabled) {
      throw new Error(`pointerClickCss: target is disabled: ${found.target}`);
    }
    await this.humanClickAt(found);
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

  async pointerClickByText(
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
      vw: number;
      vh: number;
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
      return { x: r.x, y: r.y, width: r.width, height: r.height, vw: innerWidth, vh: innerHeight };
    })()`);
    if (!rect) {
      throw new Error(`pointerClickByText: no visible element with text: ${text}`);
    }
    this.ensurePointerUsable(rect, "pointerClickByText");
    await this.humanClickAt(rect);
  }

  /**
   * Click an element by its text, piercing open shadow roots (for custom
   * elements like xiaohongshu's <xhs-publish-btn>, whose label lives inside a
   * shadow tree where querySelector/textContent lookups can't see it). The
   * match is scrolled into view and clicked with a real mouse event at its
   * center, so it works regardless of how the component wires its handlers.
   */
  async pointerClickByTextDeep(text: string, options: { exact?: boolean } = {}): Promise<void> {
    const t = JSON.stringify(text);
    const exact = options.exact !== false;
    const rect = await this.evaluate<{
      x: number;
      y: number;
      w: number;
      h: number;
      vw: number;
      vh: number;
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
      return { x: r.x, y: r.y, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight };
    })()`);
    if (!rect) {
      throw new Error(`pointerClickByTextDeep: no visible element with text: ${text}`);
    }
    this.ensurePointerUsable(rect, "pointerClickByTextDeep");
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

  /** debugger 可能已被 accountViews 为注入 stealth 提前 attach:复用即可,别二次 attach(会抛)。 */
  private ensureDebugger(): void {
    if (!this.debuggerAttached && !this.wc.debugger.isAttached()) {
      this.wc.debugger.attach("1.3");
      this.debuggerAttached = true;
    }
  }

  /**
   * 给「没有布局」的后台视图造一个真实视口。
   *
   * 未挂进窗口的 WebContentsView 视口是 0×0(实测:挂进窗口但 bounds 移出屏幕、或摆到可视区
   * 下方,同样是 0×0——只有真正在可视区内才有布局)。视口为 0 时所有基于坐标的输入都落空:
   * `scrollIntoView` 把元素"居中"到负坐标,`sendInputEvent` 打过去点不到任何东西,**而且不报错**
   * ——表现成「表单填得好好的,就是发不出去」。
   *
   * 为什么不干脆改用 `el.click()`:那样事件 `isTrusted === false`,风控一眼能认出来。B 站和
   * 微信视频号的提交按钮特意走真实输入(见 humanClickAt 的拟人化点击)正是为了这个。
   * `Emulation.setDeviceMetricsOverride` 与控件实际大小无关,能让页面按给定尺寸真正布局——
   * 实测后台视图加了它之后 sendInputEvent 能命中,且事件仍然 isTrusted。两头都保住。
   */
  async setMetricsOverride(width: number, height: number): Promise<void> {
    this.ensureDebugger();
    await this.wc.debugger.sendCommand("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
  }

  /** 撤销视口覆盖。视图被亮到前台前必须撤,否则页面会被锁在覆盖尺寸上、和窗口对不上。 */
  async clearMetricsOverride(): Promise<void> {
    if (!this.debuggerAttached && !this.wc.debugger.isAttached()) return;
    await this.wc.debugger
      .sendCommand("Emulation.clearDeviceMetricsOverride")
      .catch(() => undefined);
  }

  private async findFileInputNode(selector: string): Promise<number> {
    this.throwIfAborted();
    this.ensureDebugger();
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

  /**
   * 存一张 PNG。**必须带超时**:后台账号视图不参与合成,`capturePage()` 在这种视图上可能永不
   * resolve(不是返回空图 —— 是挂住)。而这个方法的唯一调用点 captureFailure 位于失败分支里、
   * 在 reportTask **之前**:一挂就连锁成「日志已记 runTask error,但后端永远收不到回报」——
   * 任务永久停在 running、finally 不执行、镜像不停推帧、账号从 running 集合里再也放不出来。
   * 线上确实这么挂过,所以这里与 captureBase64 用同一套竞速。
   */
  async screenshot(path: string): Promise<void> {
    const image = await Promise.race([
      this.wc.capturePage(),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 5_000)),
    ]);
    if (!image || image.isEmpty()) {
      throw new Error("capturePage produced no image (view is not composited?)");
    }
    await writeFile(path, image.toPNG());
  }

  /** 截当前画面为 data URL(缩小到 480 宽省流)。优先用离屏渲染 paint 事件缓存的最近一帧(离屏
   *  视图 capturePage 空白,帧只从 paint 来);没有再退回 capturePage(竞速超时,绝不挂起)。 */
  async captureBase64(): Promise<string | null> {
    try {
      if (this.latestFrame && !this.latestFrame.isEmpty()) {
        return this.latestFrame.resize({ width: 480 }).toDataURL();
      }
      const image = await Promise.race([
        this.wc.capturePage(),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 3_000)),
      ]);
      if (!image || image.isEmpty()) return null;
      return image.resize({ width: 480 }).toDataURL();
    } catch {
      return null;
    }
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

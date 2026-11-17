/**
 * ADR 0081 P0:L1 的实现包成 `OwnWindowDriver`。
 *
 * `DesktopDriver` 的形状(observe / act / verify / capabilities)是给 L2 / L3 的同一层接口,
 * 这一份只认 Mosael 主窗口:`capturePage` + `sendInputEvent`。
 * 从 `main.cjs` 搬出时逐字未改,行为零变化;守卫 / overlay / cursor 仍由 main.cjs 持有。
 */
const crypto = require("node:crypto");

const { captureToCss } = require("../browser/driver/coords.cjs");

/**
 * 按名字挑一个窗口。**只挑 Mosael 自己的** —— 桌面、别的 App 在这里根本没有对应项。
 * 不退回「随便哪个窗口」:截错一个窗口比截不到更糟(它会把用户别处的画面交给模型)。
 */
/** 电脑使用只认主窗口:引用没建 / 已销毁就是「没有窗口」,不回退到窗口列表里随便找一个。 */
function computerUseWindow(mainWindow) {
  return mainWindow && typeof mainWindow.isDestroyed === "function" && !mainWindow.isDestroyed() ? mainWindow : null;
}

/**
 * 点一下 Mosael 主窗口。坐标是**页面 CSS 像素**(和 capturePage 出来的图
 * 同一套坐标,缩放在后端做);越界就回一句带窗口尺寸的人话 —— 让模型知道该往哪边改,而不是点了个空。
 *
 * 走的是 `webContents.sendInputEvent`(可信输入),不是系统级鼠标注入:只在这个窗口里生效,窗口
 * 不在前台也点得中,同时**碰不到桌面和别的 App**(L1,ADR 0075)。
 */
/** 把窗口里的 CSS 坐标换成屏幕坐标,交给指针提示亮一下(提示窗口的尖端落在那个点)。 */
let lastComputerUsePoint = null;

function showComputerUseCursor(win, x, y, kind, cursor) {
  if (!cursor || typeof win.getContentBounds !== "function") return;
  try {
    const bounds = win.getContentBounds();
    if (!bounds) return;
    lastComputerUsePoint = { x: bounds.x + x, y: bounds.y + y };
    cursor.showAt(lastComputerUsePoint.x, lastComputerUsePoint.y, kind);
  } catch {
    /* 窗口没了:提示是锦上添花,别因为它影响动作本身 */
  }
}

function dragMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) {
    throw new Error("There is no Mosael window open to drag in. Nothing was dragged.");
  }
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was dragged.");
  }
  const contents = win.webContents;
  const size = typeof contents.getSize === "function" ? contents.getSize() : null;
  for (const [x, y] of [[request.fromX, request.fromY], [request.toX, request.toY]]) {
    if (size && (x >= size[0] || y >= size[1])) {
      throw new Error(
        `That point is outside the Mosael window: it reports ${size[0]}×${size[1]} CSS pixels, and (${x}, ${y}) is not inside it. Nothing was dragged.`,
      );
    }
  }
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  const fromX = Math.round(request.fromX);
  const fromY = Math.round(request.fromY);
  const toX = Math.round(request.toX);
  const toY = Math.round(request.toY);
  const button = request.button || "left";
  const durationMs = request.durationMs || 300;
  const steps = Math.max(8, Math.min(30, Math.round(durationMs / 20)));
  const waitMs = Math.max(1, Math.round(durationMs / (steps + 1)));
  contents.sendInputEvent({ type: "mouseMove", x: fromX, y: fromY });
  contents.sendInputEvent({ type: "mouseDown", x: fromX, y: fromY, button, clickCount: 1 });
  for (let index = 1; index <= steps; index += 1) {
    const progress = index / (steps + 1);
    contents.sendInputEvent({
      type: "mouseMove",
      x: Math.round(fromX + (toX - fromX) * progress),
      y: Math.round(fromY + (toY - fromY) * progress),
    });
    spinWait(waitMs);
  }
  contents.sendInputEvent({ type: "mouseUp", x: toX, y: toY, button, clickCount: 1 });
  showComputerUseCursor(win, toX, toY, "drag", cursor);
  return { fromX, fromY, toX, toY, button, durationMs };
}

function pointerMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) throw new Error("There is no Mosael window open for the pointer. Nothing was sent.");
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was sent.");
  }
  const contents = win.webContents;
  const size = typeof contents.getSize === "function" ? contents.getSize() : null;
  if (size && (request.x >= size[0] || request.y >= size[1])) {
    throw new Error(
      `That point is outside the Mosael window: it reports ${size[0]}×${size[1]} CSS pixels, and (${request.x}, ${request.y}) is not inside it. Nothing was sent.`,
    );
  }
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  const x = Math.round(request.x);
  const y = Math.round(request.y);
  const button = request.button || "left";
  const modifiers = electronModifiers(request.modifiers);
  contents.sendInputEvent({ type: "mouseMove", x, y, modifiers });
  if (request.action === "down") contents.sendInputEvent({ type: "mouseDown", x, y, button, clickCount: 1, modifiers });
  if (request.action === "up") contents.sendInputEvent({ type: "mouseUp", x, y, button, clickCount: 1, modifiers });
  showComputerUseCursor(win, x, y, request.action === "hover" ? "hover" : request.action, cursor);
  return { action: request.action, x, y, button, modifiers };
}

function clickMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) {
    throw new Error("There is no Mosael window open to click. Nothing was clicked.");
  }
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was clicked.");
  }
  const contents = win.webContents;
  const size = typeof contents.getSize === "function" ? contents.getSize() : null;
  if (size && (request.x >= size[0] || request.y >= size[1])) {
    throw new Error(
      `That point is outside the Mosael window: it reports ${size[0]}×${size[1]} CSS pixels, and (${request.x}, ${request.y}) is not inside it. Nothing was clicked.`,
    );
  }
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  const x = Math.round(request.x);
  const y = Math.round(request.y);
  const button = request.button || "left";
  const clickCount = request.clickCount || 1;
  const modifiers = electronModifiers(request.modifiers);
  contents.sendInputEvent({ type: "mouseMove", x, y, modifiers });
  contents.sendInputEvent({ type: "mouseDown", x, y, button, clickCount, modifiers });
  contents.sendInputEvent({ type: "mouseUp", x, y, button, clickCount, modifiers });
  //: 在窗口里那个点上亮一枚指针(区别于真光标:它只亮一下,拍图也拍不到)——
  //: 连续自动放行时,人至少看得见「它刚才点了哪儿」。
  showComputerUseCursor(win, x, y, "click", cursor);
  return { x, y, button, clickCount, modifiers };
}

/**
 * 在 Mosael 主窗口里滚动:Chromium 的滚轮事件需要一个位置,不给就用窗口正中。
 * 只在这个窗口里生效(L1,ADR 0075),不碰桌面和别的 App。
 */
/**
 * 同步小睡(毫秒)。滚轮事件之间要隔二十来毫秒,而这些事件是**同步**发的(`sendInputEvent` 不是
 * Promise),这段代码跑在主进程里,用不了 `await` —— 又不能让主进程真的忙等把 UI 卡住,所以用
 * `Atomics.wait` 让这一个线程睡过去(事件循环之外,不占 CPU)。
 */
function spinWait(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {
    /* 环境不支持就干脆不等 —— 少一次抖动,比卡住强 */
  }
}

function scrollMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) {
    throw new Error("There is no Mosael window open to scroll. Nothing was scrolled.");
  }
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was scrolled.");
  }
  const contents = win.webContents;
  const size = typeof contents.getSize === "function" ? contents.getSize() : [0, 0];
  if (request.x !== null && size[0] && request.x >= size[0]) {
    throw new Error(`That x is outside the Mosael window (it is ${size[0]} CSS pixels wide). Nothing was scrolled.`);
  }
  if (request.y !== null && size[1] && request.y >= size[1]) {
    throw new Error(`That y is outside the Mosael window (it is ${size[1]} CSS pixels tall). Nothing was scrolled.`);
  }
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  const x = request.x === null ? Math.round(size[0] / 2) : Math.round(request.x);
  const y = request.y === null ? Math.round(size[1] / 2) : Math.round(request.y);
  //: 一格滚轮 ≈ 100 像素(约 3 行)。直接发 deltaY = -dy 的话「滚 3 格」只走 3 像素,人看着就是没动。
  //:
  //: **分成若干格来滚,不再一次到底**(维护者 2026-10-23:「滚动似乎是一瞬间到底的,应该有个实际
  //: 的滚动过程」)。人滚滚轮是一格一格来的:这里按 100 像素一格切成 4–8 格,格间 16–40ms 抖动,
  //: 总时长跟着距离走(最多约 400ms)。页面自己也靠这一串事件做惯性滚动与懒加载 —— 一次到底时
  //: 那些都来不及发生,看起来就是"跳"过去的。
  const dy = request.dy || 0;
  const dx = request.dx || 0;
  const steps = Math.min(8, Math.max(4, Math.max(Math.abs(dy), Math.abs(dx))));
  const perStepY = (-dy * 100) / steps;
  const perStepX = (dx * 100) / steps;
  for (let index = 0; index < steps; index += 1) {
    contents.sendInputEvent({ type: "mouseWheel", x, y, deltaX: perStepX, deltaY: perStepY, canScroll: true });
    //: 最后一格之后不等:调用方马上要读页面,多等这一下只是白慢。
    if (index < steps - 1) spinWait(16 + Math.round(Math.random() * 24));
  }
  const kind = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "scroll-right" : "scroll-left") : (dy > 0 ? "scroll-down" : "scroll-up");
  showComputerUseCursor(win, x, y, kind, cursor);
  return { dy, dx, x, y };
}

/**
 * 往 Mosael 主窗口里输入一段文字:先聚焦窗口与网页,再把文字插到焦点处。
 * `insertText` 是 Chromium 自己的「插入文本」,和用户打字走同一条路(受控输入框的 onInput 会触发),
 * 比逐字符发 keyDown/char 稳,也不会被输入法状态影响。
 */
/** 键名归一化到 Electron `sendInputEvent` 的 keyCode;只接受单字符或明确的命名键。 */
function electronKeyCode(key) {
  const lower = String(key || "").toLowerCase();
  const named = {
    enter: "Enter", tab: "Tab", escape: "Escape", backspace: "Backspace", delete: "Delete", space: "Space",
    home: "Home", end: "End", pageup: "PageUp", pagedown: "PageDown", left: "Left", right: "Right", up: "Up", down: "Down",
    ...Object.fromEntries(Array.from({ length: 12 }, (_, index) => [`f${index + 1}`, `F${index + 1}`])),
  };
  if (named[lower]) return named[lower];
  if (lower.length === 1) return lower.toUpperCase();
  throw new Error(`Unsupported key: ${key}`);
}

function electronModifiers(modifiers) {
  const map = { cmd: "command", ctrl: "control", alt: "alt", shift: "shift", meta: "command" };
  return [...new Set((Array.isArray(modifiers) ? modifiers : []).map((one) => map[String(one).toLowerCase()]).filter(Boolean))];
}

/** 在 Mosael 主窗口里按一个键或组合键;焦点在窗口自己的 DOM 里(输入框 / 画布)。 */
async function pressMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) throw new Error("There is no Mosael window open to press a key in. Nothing was pressed.");
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was pressed.");
  }
  const contents = win.webContents;
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  const keyCode = electronKeyCode(request.key);
  const modifiers = electronModifiers(request.modifiers);
  contents.sendInputEvent({ type: "keyDown", keyCode, modifiers });
  if (request.holdMs > 0) {
    //: 不要用 spinWait:按住键可以长达几分钟,阻塞主进程会让整个应用卡死。
    await new Promise((resolve) => setTimeout(resolve, request.holdMs));
  }
  contents.sendInputEvent({ type: "keyUp", keyCode, modifiers });
  if (cursor && lastComputerUsePoint) cursor.showAt(lastComputerUsePoint.x, lastComputerUsePoint.y, "type");
  return { key: request.key, modifiers: request.modifiers || [], keyCode, holdMs: request.holdMs || 0 };
}

function typeIntoMosaelWindow(request, mainWindow, cursor = null) {
  const win = computerUseWindow(mainWindow);
  if (!win) {
    throw new Error("There is no Mosael window open to type into. Nothing was typed.");
  }
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was typed.");
  }
  const contents = win.webContents;
  if (typeof win.focus === "function") win.focus();
  if (typeof contents.focus === "function") contents.focus();
  contents.insertText(String(request.text));
  //: 输入没有坐标 —— 接着在上一次点/滚的位置亮一下,让人看得出「刚才那一下是在这儿打的字」。
  if (cursor && lastComputerUsePoint) {
    cursor.showAt(lastComputerUsePoint.x, lastComputerUsePoint.y, "type");
  }
  return { typed: String(request.text).length };
}

const DOM_TOKEN_TTL_MS = 60_000;
const MAX_DOM_SNAPSHOTS = 8;

function domFingerprint(row) {
  return JSON.stringify([
    row.role || "", row.name || "", row.x, row.y, row.width, row.height, Boolean(row.disabled),
  ]);
}

/**
 * 把窗口里可操作的元素读成一张轻量清单。坐标是**窗口 CSS 像素**,和后端拿到截图后再按 scale
 * 缩放后的图片坐标同一套;输入框的当前值**不读**(可能是密码 / 私密内容)。
 */
async function domElements(win) {
  const contents = win && win.webContents;
  if (!contents || typeof contents.executeJavaScript !== "function") return [];
  try {
    const rows = await contents.executeJavaScript(`(() => {
      const nodes = Array.from(document.querySelectorAll(
        'button, a[href], input, textarea, select, [role="button"], [contenteditable="true"]'
      ));
      const text = (el) => {
        const raw = el.getAttribute('aria-label') || el.getAttribute('placeholder')
          || el.getAttribute('title') || el.innerText || el.textContent || '';
        return String(raw).replace(/\\s+/g, ' ').trim().slice(0, 120);
      };
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
          && style.visibility !== 'hidden' && style.display !== 'none';
      };
      return nodes.filter(visible).slice(0, 200).map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          role: el.getAttribute('role') || el.tagName.toLowerCase(),
          name: text(el),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
        };
      });
    })()`);
    return Array.isArray(rows) ? rows.filter((one) => one && typeof one === "object") : [];
  } catch {
    //: 元素清单是截图的补充,不是截图本身;读不到就只交图片,不让一次观察整个失败。
    return [];
  }
}

/** 等窗口里出现一段可见文字。只读;每次重读 DOM,不依赖上一次的截图。 */
async function waitForMosaelText(text, timeoutMs, mainWindow) {
  const win = computerUseWindow(mainWindow);
  if (!win || !win.webContents || typeof win.webContents.executeJavaScript !== "function") {
    throw new Error("There is no Mosael window open to wait in. Nothing was waited for.");
  }
  const started = Date.now();
  const expression = `(() => Boolean(document.body && document.body.innerText.includes(${JSON.stringify(String(text))})))()`;
  for (;;) {
    const found = await win.webContents.executeJavaScript(expression);
    const waitedMs = Date.now() - started;
    if (found) return { found: true, waitedMs };
    if (waitedMs >= timeoutMs) return { found: false, waitedMs };
    await new Promise((resolve) => setTimeout(resolve, Math.min(150, Math.max(1, timeoutMs - waitedMs))));
  }
}

/** 立即检查窗口里有没有一段可见文字;不等待。 */
async function verifyMosaelText(text, absent, mainWindow) {
  const win = computerUseWindow(mainWindow);
  if (!win || !win.webContents || typeof win.webContents.executeJavaScript !== "function") {
    throw new Error("There is no Mosael window open to verify. Nothing was checked.");
  }
  const expression = `(() => Boolean(document.body && document.body.innerText.includes(${JSON.stringify(String(text))})))()`;
  const found = Boolean(await win.webContents.executeJavaScript(expression));
  return {
    ok: absent ? !found : found,
    reason: found ? "found" : (absent ? "absent" : "not_found"),
    evidence: { text: String(text), found },
  };
}

/**
 * 拍下 Mosael 主窗口,回 `{width, height, image, elements}`(图片是原图,缩放由后端做;
 * elements 坐标随后端 scale 一起缩)。参数不对 / 没窗口 / 最小化 / 空图,都抛一句人话。
 */
async function captureMosaelWindow(mainWindow) {
  const win = computerUseWindow(mainWindow);
  if (!win) {
    throw new Error("There is no Mosael window open to screenshot. Nothing was captured.");
  }
  if (typeof win.isMinimized === "function" && win.isMinimized()) {
    throw new Error("The Mosael window is minimized; restore it and try again. Nothing was captured.");
  }
  const image = await win.webContents.capturePage();
  if (!image || image.isEmpty()) {
    throw new Error(
      "The Mosael window produced an empty picture (it may be hidden or not composited). Nothing was captured.",
    );
  }
  //: **按窗口的 CSS 尺寸归一化**。Retina 上 capturePage 给的是物理像素(2x):一张 1600×1136 的图背后
  //: 是 800×568 的页面,而 `sendInputEvent` 认的是 CSS 像素 —— 不缩放的话模型按图给的坐标点下去会差一倍
  //: (点到的位置全偏到左上角,看起来就是「点了没反应」)。缩到 CSS 尺寸之后,「图上的像素」和「点击坐标」
  //: 就是同一套数,后端那个 scale 也就还是唯一的一次缩放。
  const content = typeof win.getContentSize === "function" ? win.getContentSize() : null;
  let shot = image;
  //: 归一化判断也住在 browser/driver/coords(Retina 上 capturePage 给物理像素,而 sendInputEvent 认 CSS)。
  const target = captureToCss(image.getSize(), content || null);
  if (target) shot = image.resize({ width: target.width, height: target.height, quality: "best" });
  const { width, height } = shot.getSize();
  const elements = await domElements(win);
  return {
    width,
    height,
    image: shot.toPNG().toString("base64"),
    ...(elements.length ? { elements } : {}),
  };
}




/**
 * 合成输入不能落在确认卡 / 急停条上。模型读网页后按坐标点“批准”，等于让它自己把另一张
 * 确认卡的闸门按掉；这里按 DOM 命中结果拒绝，坐标校验留在后端卡上。
 */
async function assertComputerTargetAllowed(contents, action) {
  if (!contents || typeof contents.executeJavaScript !== "function") return;
  const points = action.kind === "drag"
    ? `[[${Number(action.fromX || 0)}, ${Number(action.fromY || 0)}], [${Number(action.toX || 0)}, ${Number(action.toY || 0)}]]`
    : `[[${Number(action.x || 0)}, ${Number(action.y || 0)}]]`;
  const blocked = await contents.executeJavaScript(`(() => {
    const points = ${points};
    const blocked = points.some(([x, y]) => {
      const hit = ${(action.kind === "type" || action.kind === "key")
        ? 'document.activeElement'
        : 'document.elementFromPoint(x, y)'};
      return Boolean(hit && hit.closest && hit.closest("[data-confirmation-card],[data-computer-use-banner]"));
    });
    return blocked;
  })()`);
  if (blocked) {
    throw new Error("That target is the Mosael confirmation or emergency-stop surface. Nothing was sent.");
  }
}

/** ADR 0081 的 DesktopDriver 端口:L1 的实现。 */
class OwnWindowDriver {
  /** `getWindow` 每次调用时取主窗口 —— mac 关窗再激活会重建它,所以不缓存引用。 */
  constructor(getWindow) {
    this.getWindow = getWindow;
    this.domSnapshots = new Map();
  }

  capabilities() {
    return { tree: false, screenshots: true, input: true, platforms: ["mosael-window"] };
  }

  /** 观察:主窗口的一张图 + 可见元素清单;元素带一次性 token。 */
  async observe() {
    const captured = await captureMosaelWindow(this.getWindow());
    const snapshotId = crypto.randomUUID();
    const elements = (captured.elements ?? []).map((row, index) => ({
      ...row,
      token: `${snapshotId}:${index}`,
    }));
    if (elements.length) {
      this.domSnapshots.set(snapshotId, { elements, at: Date.now() });
      while (this.domSnapshots.size > MAX_DOM_SNAPSHOTS) {
        this.domSnapshots.delete(this.domSnapshots.keys().next().value);
      }
    }
    return {
      ...captured,
      elements,
      meta: { window: "main", ...(elements.length ? { snapshot_id: snapshotId } : {}) },
    };
  }

  /** 令牌 → 当前 DOM 里的同一个元素;重读并比对指纹,过期 / 变了就拒绝。 */
  async resolveElement(token, consume = true) {
    const match = /^([A-Za-z0-9-]{1,64}):(\d{1,8})$/.exec(String(token || ""));
    if (!match) throw new Error("The element token is invalid; take a new screenshot.");
    const snapshot = this.domSnapshots.get(match[1]);
    const index = Number(match[2]);
    if (!snapshot || Date.now() - snapshot.at > DOM_TOKEN_TTL_MS) {
      this.domSnapshots.delete(match[1]);
      throw new Error("The element snapshot expired; take a new screenshot.");
    }
    const before = snapshot.elements[index];
    if (!before) throw new Error("The element token is not in that snapshot; take a new screenshot.");
    const window = computerUseWindow(this.getWindow());
    if (!window) throw new Error("There is no Mosael window open to resolve that element.");
    const current = await domElements(window);
    const after = current.find((row) => domFingerprint(row) === domFingerprint(before));
    if (!after) {
      this.domSnapshots.delete(match[1]);
      throw new Error("That element changed or disappeared; take a new screenshot before acting.");
    }
    if (consume) this.domSnapshots.delete(match[1]);
    return {
      x: Math.round(after.x + after.width / 2),
      y: Math.round(after.y + after.height / 2),
      role: after.role,
      name: after.name,
      snapshotId: match[1],
    };
  }

  async waitForText(text, timeoutMs) {
    return waitForMosaelText(text, timeoutMs, this.getWindow());
  }

  async verifyText(text, absent = false) {
    return verifyMosaelText(text, absent, this.getWindow());
  }

  /** 动作:点 / 输入 / 按键 / 滚动。`action.kind` 只认这四种;别的直接拒。 */
  async act(action) {
    const window = this.getWindow();
    let run = action;
    let tokenType = false;
    if (run.fromToken || run.toToken) {
      if (!run.fromToken || !run.toToken) {
        throw new Error("fromToken and toToken must be provided together.");
      }
      const from = await this.resolveElement(run.fromToken, false);
      const to = await this.resolveElement(run.toToken, false);
      this.domSnapshots.delete(from.snapshotId);
      this.domSnapshots.delete(to.snapshotId);
      run = { ...run, fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, fromToken: undefined, toToken: undefined };
    }
    if (run.token) {
      if (run.kind !== "click" && run.kind !== "type") {
        throw new Error("Element tokens currently target clicks and text input; use coordinates for this action.");
      }
      const target = await this.resolveElement(run.token);
      tokenType = run.kind === "type";
      run = { ...run, x: target.x, y: target.y, token: undefined };
    }
    if (window && (run.kind === "click" || run.kind === "type" || run.kind === "key" || run.kind === "drag" || run.kind === "hover")) {
      await assertComputerTargetAllowed(window.webContents, tokenType ? { ...run, kind: "click" } : run);
    }
    switch (run.kind) {
      case "hover":
      case "down":
      case "up":
        return pointerMosaelWindow({ ...run, action: run.kind }, window, run.cursor ?? null);
      case "click":
        return clickMosaelWindow(run, window, run.cursor ?? null);
      case "drag":
        return dragMosaelWindow(run, window, run.cursor ?? null);
      case "type":
        if (tokenType) clickMosaelWindow(run, window, run.cursor ?? null);
        return typeIntoMosaelWindow(run, window, run.cursor ?? null);
      case "key":
        return pressMosaelWindow(run, window, run.cursor ?? null);
      case "scroll":
        return scrollMosaelWindow(run, window, run.cursor ?? null);
      default:
        throw new Error(`Unknown computer-use action: ${run.kind}`);
    }
  }

  /** L1 目前没有「按用户后置条件校验」的实现,明确不支持,不冒充已验证。 */
  verify() {
    return { ok: false, reason: "verify_not_supported", evidence: null };
  }
}

module.exports = { OwnWindowDriver };

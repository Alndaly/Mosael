/**
 * ADR 0081 P0:L1 的实现包成 `OwnWindowDriver`。
 *
 * `DesktopDriver` 的形状(observe / act / verify / capabilities)是给 L2 / L3 的同一层接口,
 * 这一份只认 Mosael 主窗口:`capturePage` + `sendInputEvent`。
 * 从 `main.cjs` 搬出时逐字未改,行为零变化;守卫 / overlay / cursor 仍由 main.cjs 持有。
 */
const { captureToCss } = require("../browser/pool/coords.cjs");

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
  contents.sendInputEvent({ type: "mouseMove", x, y });
  contents.sendInputEvent({ type: "mouseDown", x, y, button, clickCount });
  contents.sendInputEvent({ type: "mouseUp", x, y, button, clickCount });
  //: 在窗口里那个点上亮一枚指针(区别于真光标:它只亮一下,拍图也拍不到)——
  //: 连续自动放行时,人至少看得见「它刚才点了哪儿」。
  showComputerUseCursor(win, x, y, "click", cursor);
  return { x, y, button, clickCount };
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
  const steps = Math.min(8, Math.max(4, Math.abs(request.dy)));
  const perStep = (-request.dy * 100) / steps;
  for (let index = 0; index < steps; index += 1) {
    contents.sendInputEvent({ type: "mouseWheel", x, y, deltaY: perStep, canScroll: true });
    //: 最后一格之后不等:调用方马上要读页面,多等这一下只是白慢。
    if (index < steps - 1) spinWait(16 + Math.round(Math.random() * 24));
  }
  showComputerUseCursor(win, x, y, request.dy > 0 ? "scroll-down" : "scroll-up", cursor);
  return { dy: request.dy, x, y };
}

/**
 * 往 Mosael 主窗口里输入一段文字:先聚焦窗口与网页,再把文字插到焦点处。
 * `insertText` 是 Chromium 自己的「插入文本」,和用户打字走同一条路(受控输入框的 onInput 会触发),
 * 比逐字符发 keyDown/char 稳,也不会被输入法状态影响。
 */
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

/**
 * 拍下 Mosael 主窗口,回 `{width, height, image}`(`image` 是 PNG 的
 * base64;缩放由后端做,主进程只给原图)。参数不对 / 没窗口 / 最小化 / 空图,都抛一句人话。
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
  //: 归一化判断也住在 browser/pool/coords(Retina 上 capturePage 给物理像素,而 sendInputEvent 认 CSS)。
  const target = captureToCss(image.getSize(), content || null);
  if (target) shot = image.resize({ width: target.width, height: target.height, quality: "best" });
  const { width, height } = shot.getSize();
  return { width, height, image: shot.toPNG().toString("base64") };
}



/** ADR 0081 的 DesktopDriver 端口:L1 的实现。 */
class OwnWindowDriver {
  /** `getWindow` 每次调用时取主窗口 —— mac 关窗再激活会重建它,所以不缓存引用。 */
  constructor(getWindow) {
    this.getWindow = getWindow;
  }

  capabilities() {
    return { tree: false, screenshots: true, input: true, platforms: ["mosael-window"] };
  }

  /** 观察:主窗口的一张图。L1 没有可访问性树,elements 明确为空,不假装有。 */
  async observe() {
    const captured = await captureMosaelWindow(this.getWindow());
    return { ...captured, elements: [], meta: { window: "main" } };
  }

  /** 动作:点 / 输入 / 滚动。`action.kind` 只认这三种;别的直接拒。 */
  async act(action) {
    const window = this.getWindow();
    switch (action.kind) {
      case "click":
        return clickMosaelWindow(action, window, action.cursor ?? null);
      case "type":
        return typeIntoMosaelWindow(action, window, action.cursor ?? null);
      case "scroll":
        return scrollMosaelWindow(action, window, action.cursor ?? null);
      default:
        throw new Error(`Unknown computer-use action: ${action.kind}`);
    }
  }

  /** L1 目前没有「按用户后置条件校验」的实现,明确不支持,不冒充已验证。 */
  verify() {
    return { ok: false, reason: "verify_not_supported", evidence: null };
  }
}

module.exports = { OwnWindowDriver };

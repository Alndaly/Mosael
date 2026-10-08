import * as React from "react";

/**
 * Mosael 自己的**整窗浮层**(看大图、工作台里模型的详情)亮着时,请主进程把前台的原生网页视图挪到窗口外,收起时放回
 * (electron 的 accountViews:ForegroundHideReason 的 `overlay`)。
 *
 * 原生视图盖在一切 DOM 上:内嵌浏览器、ComfyUI 工作台亮着时打开大图,整窗的浮层只露得出顶栏和侧栏那几条,图被画布
 * 盖住。挪开(不是藏起来)的视图照常出帧,放回时就是它此刻的样子;顶栏、侧栏里的悬停说明走的是另一层(浮层视图),
 * 不受影响。
 *
 * **挪开之前先铺一张冻结的画面**(`NativeViewStandIn`):视图一挪走,它原来那块露出来的是底下的 DOM —— 浮层刚开始
 * 淡入、还是透明的,那一下看到的是空着的应用背景,画布像被抹掉了一样闪一下(维护者在工作台里点模型缩略图时看到的)。
 * 所以和页面列表变形同一个做法(见 browser-pool/usePageListMotion):先请主进程拍下网页此刻的画面(`snapshotPage`,
 * `webContents.capturePage`)和它在窗口里的位置,铺在原处、**真画上屏了**再挪开视图 —— 浮层在那张画面上面淡入。
 * 收起时反过来:**先放回视图**(它盖住那张画面),过两帧再拿掉画面;反过来会闪一下底色。
 *
 * 「画上屏了」按 Element Timing 报的那一刻(图上挂 `elementtiming`,`PerformanceObserver` 收 `element` 条目)。真机实测
 * (工作台里点模型的详情,逐帧录渲染层):只等 `load` 再等一帧,视图第 92 毫秒挪走、画面第 274 毫秒才上屏 —— 整窗那么大的
 * 一张 PNG,`load` 之后还要异步解码、上传;等到 `decode()` 再等一帧,仍差一两帧(第 101 毫秒挪走、第 122 毫秒上屏)。
 * 没有 Element Timing 的环境(测试)退回「加载、解码好,再等一帧」。
 *
 * 引用计数:几处浮层同时亮着,最后一处收起才放回。没有前台网页时拍不到画面,只请主进程记一笔(它那边什么都不挪);
 * 网页版没有这座桥,什么都不做。
 */
type Bridge = Pick<NonNullable<Window["mosaelPublish"]>, "setOverlay"> &
  Partial<Pick<NonNullable<Window["mosaelPublish"]>, "snapshotPage">>;

/** 铺在原生视图原处的那张画面;`take` 是第几次拍的 —— 每次都是一张新图(重新挂、重新等加载)。 */
export interface StandInFrame {
  frame: string;
  bounds: { x: number; y: number; width: number; height: number };
  take: number;
}

/** 等那张画面画上屏最多等多久:拍得到就几十毫秒;卡住了也不能让浮层一直被视图盖着。 */
const FRAME_LOAD_WAIT_MS = 1_000;

let holders = 0;
/** 主进程那边已经把视图挪开了(或者至少记了一笔)。 */
let aside = false;
let running = false;
let again = false;
let standIn: StandInFrame | null = null;
let takes = 0;
/** 挂着几个 `NativeViewStandIn`(App 里一个)。一个都没有(测试里单独挂一块浮层)就不等画面加载。 */
let painters = 0;
let frameLoaded: (() => void) | null = null;
const listeners = new Set<() => void>();
/** 等「这一串走完」的人(只有测试等,见 settleNativeViewAside)。 */
const settledWaiters: Array<() => void> = [];

/** 第几张画面在 Element Timing 里叫什么。 */
const paintId = (take: number) => `native-view-stand-in-${take}`;

/**
 * 第 `take` 张画面真画上屏了:Element Timing 报到它就算(Chromium);没有这个 API 时等 `load`(NativeViewStandIn 解码好才报)
 * 再等一帧。`stop` 收掉监听(等够了没等到也要收)。
 */
function framePainted(take: number): { done: Promise<void>; stop: () => void } {
  const timing = typeof PerformanceObserver === "function" && PerformanceObserver.supportedEntryTypes?.includes("element");
  if (!timing) {
    const loaded = new Promise<void>((resolve) => {
      frameLoaded = resolve;
    });
    return { done: loaded.then(nextFrame), stop: () => (frameLoaded = null) };
  }
  let observer: PerformanceObserver | null = null;
  const done = new Promise<void>((resolve) => {
    observer = new PerformanceObserver((list) => {
      if (list.getEntries().some((entry) => (entry as PerformanceEntry & { identifier?: string }).identifier === paintId(take))) resolve();
    });
    observer.observe({ type: "element", buffered: true });
  });
  return { done, stop: () => observer?.disconnect() };
}

function setStandIn(next: StandInFrame | null): void {
  standIn = next;
  for (const listener of listeners) listener();
}

function bridgeOf(): Bridge | null {
  const bridge = typeof window === "undefined" ? undefined : window.mosaelPublish;
  return typeof bridge?.setOverlay === "function" ? bridge : null;
}

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
const nextFrame = () =>
  new Promise<void>((resolve) => {
    if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(() => resolve());
    else window.setTimeout(resolve, 16);
  });

/**
 * 让开:先在原处铺好网页此刻的画面,画上去了再请主进程挪开视图。拍的这一会儿浮层已经收起了(点开马上又关)就不挪了,
 * 回 false。
 */
async function stepAside(bridge: Bridge): Promise<boolean> {
  const shot = typeof bridge.snapshotPage === "function" ? await bridge.snapshotPage().catch(() => null) : null;
  if (holders === 0) return false;
  if (shot) {
    const take = ++takes;
    const painted = painters > 0 ? framePainted(take) : null;
    setStandIn({ ...shot, take });
    if (painted) {
      await Promise.race([painted.done, wait(FRAME_LOAD_WAIT_MS)]);
      painted.stop();
    }
  }
  await bridge.setOverlay(true).catch(() => undefined);
  return true;
}

/** 回到原处:先放回视图(它盖住那张画面),过两帧再拿掉画面。 */
async function stepBack(bridge: Bridge): Promise<void> {
  await bridge.setOverlay(false).catch(() => undefined);
  if (!standIn) return;
  await nextFrame();
  await nextFrame();
  if (holders === 0) setStandIn(null);
}

/** 把「主进程那边」摆成此刻要的样子:一次只走一步,走完再看要的变没变(让开的路上又收起了,就接着放回)。 */
async function reconcile(): Promise<void> {
  if (running) {
    again = true;
    return;
  }
  const bridge = bridgeOf();
  if (!bridge) return;
  running = true;
  try {
    do {
      again = false;
      const want = holders > 0;
      if (want && !aside) {
        aside = await stepAside(bridge);
        if (!aside && standIn) setStandIn(null);
      } else if (!want && aside) {
        aside = false;
        await stepBack(bridge);
      }
    } while (again || holders > 0 !== aside);
  } finally {
    running = false;
    for (const done of settledWaiters.splice(0)) done();
  }
}

/** 「有没有浮层要它让开」变了(0 ↔ 非 0)时通知的人(useNativeViewSteppedAside)。 */
const asideListeners = new Set<() => void>();

/**
 * 占住一次「让开」;返回放开它的函数(放多次只算一次)。
 *
 * 最后一处放开时,放回视图那一步等到这一拍的同步代码走完再开始:一处浮层收起、同一次提交里另一处接着要它让开
 * (任务中心里点一条任务:弹出层收起、详情框打开),React 先跑完卸载再跑挂载 —— 当场就放回的话,视图回来一下又挪走,
 * 画面闪一次。等一个微任务,那时已经又有人要它让开,就什么都不做。
 */
export function stepNativeViewAside(): () => void {
  holders += 1;
  if (holders === 1) {
    void reconcile();
    for (const listener of asideListeners) listener();
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders -= 1;
    if (holders > 0) return;
    queueMicrotask(() => {
      if (holders > 0) return;
      void reconcile();
      for (const listener of asideListeners) listener();
    });
  };
}

/**
 * 这会儿有整窗的浮层把原生视图挪开了没有。挪开时窗口里看得见的全是 Mosael 的 DOM:按键该交给浮层(大图的 Esc、左右翻页),
 * 不该再当成「落在看不见的地方」吞掉、交给网页(见 browser-pool/embeddedFocus)。
 */
export const nativeViewAside = () => holders > 0;

/**
 * 同上,跟着变。提示条用它:原生视图让开着的时候窗口里看得见的全是 Mosael 的 DOM,提示条照常画在 DOM 里,不必再交给浮层视图
 * (ADR 0051)。
 */
export function useNativeViewSteppedAside(): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      asideListeners.add(listener);
      return () => {
        asideListeners.delete(listener);
      };
    },
    nativeViewAside,
    () => false,
  );
}

/** `active` 为真的这段时间里让原生视图让开(卸载时也放开)。 */
export function useNativeViewAside(active: boolean): void {
  React.useEffect(() => (active ? stepNativeViewAside() : undefined), [active]);
}

/**
 * 放进弹窗内容里:内容挂着(开着,连同收起的动画)的这段时间请原生视图让开。弹窗组件本身关着时也在渲染(只是不出 portal),
 * 所以这一步要放在只有开着才挂上的内容里面。
 */
export function StepNativeViewAside() {
  useNativeViewAside(true);
  return null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * 原生视图让开的这段时间里,铺在它原处的那张冻结的画面(见上)。App 里挂一个。层级在应用的页面之上、窗口外壳之下
 * (页面列表 z-190、顶栏和工作台那一列 z-200):它铺的就是外壳围着的那一块。要原生视图让开的浮层本来就得压过外壳
 * (大图 z-220、工作台里模型的详情 z-205),自然也盖在它上面。不接指针:它只是一张画。
 */
export function NativeViewStandIn() {
  const shown = React.useSyncExternalStore(subscribe, () => standIn, () => null);
  React.useEffect(() => {
    painters += 1;
    return () => {
      painters -= 1;
    };
  }, []);
  if (!shown) return null;
  return (
    <img
      key={shown.take}
      alt=""
      aria-hidden
      data-native-view-stand-in=""
      {...{ elementtiming: paintId(shown.take) } /* React 的类型里还没有这个属性,原样落到 DOM 上 */}
      src={shown.frame}
      draggable={false}
      onLoad={(event) => void decoded(event.currentTarget).then(() => frameLoaded?.())}
      onError={() => frameLoaded?.()}
      className="pointer-events-none fixed z-[188] block max-w-none select-none"
      style={{ left: shown.bounds.x, top: shown.bounds.y, width: shown.bounds.width, height: shown.bounds.height }}
    />
  );
}

/** 这张图解码好、下一帧画得出来了(没有 `decode` 的环境:加载好就算)。解不了也不拦着。 */
function decoded(image: HTMLImageElement): Promise<void> {
  return typeof image.decode === "function" ? image.decode().catch(() => undefined) : Promise.resolve();
}

/**
 * 测试用:等正在走的那一串「让开 / 放回」走完(没在走就当场返回)。`resetNativeViewAside` 之前先等它 —— 那一串跨着好几个
 * await,上一条测试关了浮层、它还在路上;不等就重置,它走完时把 `aside` 和主进程那边的记录写进下一条测试(打乱顺序或机器忙时,
 * 下一条就多出两笔「拍画面 / 挪开」)。
 */
export function settleNativeViewAside(): Promise<void> {
  return running ? new Promise((resolve) => settledWaiters.push(resolve)) : Promise.resolve();
}

/** 测试用:回到什么都没让开的样子。 */
export function resetNativeViewAside(): void {
  holders = 0;
  for (const listener of asideListeners) listener();
  aside = false;
  running = false;
  again = false;
  frameLoaded = null;
  setStandIn(null);
}

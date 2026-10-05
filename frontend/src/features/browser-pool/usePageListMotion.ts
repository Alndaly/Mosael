import React from "react";

import { useMediaMatch } from "@/lib/useMediaMatch";

import { readCollapsed, writeCollapsed } from "./pageListState";

/** 列表展开 / 收起、画面跟着滑的过渡多长(毫秒)。列表宽度和画面的 CSS transition 用的是同一个数。 */
export const PAGE_LIST_MOTION_MS = 180;
/** 过渡的缓动:先快后慢,收尾不拖。 */
export const PAGE_LIST_EASING = "cubic-bezier(0.2, 0, 0, 1)";
/** 鼠标停多久才临时展开:从网页移到窗口边上一掠而过,不该弹出来。 */
const HOVER_MS = 150;
/** 移开多久才收回:指针在列表边上抖一下不算离开。 */
const LEAVE_MS = 150;
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

type MotionBridge = Pick<NonNullable<Window["mosaelPublish"]>, "snapshotPage" | "coverPage">;
/** 拍下的画面;`take` 是第几次拍的 —— 每次盖都是一张新图(重新挂上、重新等它加载),哪怕和上一张一模一样。 */
export type PageSnapshot = NonNullable<Awaited<ReturnType<MotionBridge["snapshotPage"]>>> & { take: number };

/** 列表此刻摆成什么样:收起没有(网页左侧让出多宽跟着它)、临时展开没有。 */
type Shape = { collapsed: boolean; peek: boolean };

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
const nextFrame = () =>
  new Promise<void>((resolve) => {
    if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(() => resolve());
    else window.setTimeout(resolve, 16);
  });

/**
 * 页面列表的展开、收起、临时展开,以及它们之间的过渡。
 *
 * **难处在原生网页视图盖在一切 DOM 上**:列表宽度一变,网页视图得跟着挪 —— 两边各走各的(渲染层画列表、主进程
 * 挪视图),中间总有那么几帧对不上:要么露出底下的应用,要么网页盖住列表的一截。再要过渡就更没法同步了。
 *
 * 所以变形之前先拍下网页此刻的画面铺在原处(`snapshot`),画面铺好了再请主进程把原生视图挪开(`coverPage`)。
 * 之后看到的全是 DOM:列表的宽度和那张画面的左沿用同一条过渡一起动,网页视图在看不见的地方换成新的宽度。
 * 过渡走完,先让原生视图回到原处,再拿掉那张画面 —— 中间不闪,也不露底。临时展开就是「盖着不揭」:鼠标移开、
 * 列表缩回去之后才揭。要求减少动态时照样先盖后揭,只是不过渡。
 *
 * `keepPeekOpen`:别的理由让临时展开开着(列表里的地址框开着)。在展开的列表里选了一页、开了新页面之后调
 * `dismiss({ instant: true })`:马上揭开让人看到那一页;鼠标移开再回来(或键盘重新切进来)才再展开。
 */
export function usePageListMotion(bridge: MotionBridge, keepPeekOpen: boolean) {
  const reduced = useMediaMatch(REDUCED_MOTION);
  //: 「收起」这个设置(记在本机)和列表此刻摆成的样子分开:改设置是一瞬间的事,摆过去要等画面盖好、过渡走完。
  const [collapsed, setCollapsed] = React.useState(readCollapsed);
  const [shape, setShape] = React.useState<Shape>(() => ({ collapsed, peek: false }));
  //: 列表里的内容按图标条排还是按整列排。缩的时候缩完才换,展开的时候先换再展开 —— 不然图标在宽列表里挤在正中。
  const [compact, setCompact] = React.useState(collapsed);
  const [snapshot, setSnapshot] = React.useState<PageSnapshot | null>(null);
  const [hovering, setHovering] = React.useState(false);
  const [lingering, setLingering] = React.useState(false);
  const [focused, setFocused] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(false);
  const ref = React.useRef<HTMLElement | null>(null);

  const wantPeek = collapsed && !dismissed && (lingering || focused || keepPeekOpen);
  const target = React.useRef<Shape>({ collapsed, peek: wantPeek });
  target.current = { collapsed, peek: wantPeek };
  const shown = React.useRef(shape);
  const reducedRef = React.useRef(reduced);
  reducedRef.current = reduced;
  const covered = React.useRef(false);
  const alive = React.useRef(true);
  const running = React.useRef(false);
  const again = React.useRef(false);
  const instantClose = React.useRef(false);
  const backdropLoaded = React.useRef<(() => void) | null>(null);
  const takes = React.useRef(0);
  const hoverTimer = React.useRef<number | undefined>(undefined);
  const leaveTimer = React.useRef<number | undefined>(undefined);

  const apply = (next: Shape) => {
    shown.current = next;
    setShape(next);
  };
  const settle = async (animated: boolean) => {
    if (animated && !reducedRef.current) await wait(PAGE_LIST_MOTION_MS);
    await nextFrame();
  };

  /** 盖上:拍下网页此刻的画面铺在原处,铺好了再把原生视图挪开。拍不到(没有前台网页)就是 false。 */
  const cover = async (): Promise<boolean> => {
    if (covered.current) return true;
    const shot = await bridge.snapshotPage().catch(() => null);
    if (!shot || !alive.current) return false;
    const loaded = new Promise<void>((resolve) => {
      backdropLoaded.current = resolve;
    });
    setSnapshot({ ...shot, take: ++takes.current });
    await Promise.race([loaded, wait(1_000)]);
    await nextFrame();
    if (!alive.current) return false;
    try {
      await bridge.coverPage(true);
    } catch {
      setSnapshot(null);
      return false;
    }
    covered.current = true;
    return true;
  };

  /** 揭开:先让原生视图回到原处(它盖住那张画面),再拿掉画面 —— 反过来会闪一下。 */
  const uncover = async () => {
    if (!covered.current) {
      setSnapshot(null);
      return;
    }
    covered.current = false;
    await bridge.coverPage(false).catch(() => undefined);
    await nextFrame();
    await nextFrame();
    if (!covered.current && alive.current) setSnapshot(null);
  };

  /** 把列表从此刻的样子一步步摆到想要的样子(一次只走一步,每一步走完再看想要的变没变)。 */
  const reconcile = React.useRef<() => Promise<void>>(async () => undefined);
  reconcile.current = async () => {
    if (running.current) {
      again.current = true;
      return;
    }
    running.current = true;
    try {
      for (;;) {
        again.current = false;
        const want = target.current;
        const now = shown.current;
        if (want.collapsed !== now.collapsed) {
          const smooth = await cover();
          if (!alive.current) return;
          if (want.collapsed) {
            apply({ collapsed: true, peek: false });
            await settle(smooth);
            setCompact(true);
          } else {
            setCompact(false);
            apply({ collapsed: false, peek: false });
            await settle(smooth);
          }
          continue;
        }
        if (want.peek !== now.peek) {
          if (want.peek) {
            if (!(await cover()) || !alive.current) break;
            setCompact(false);
            apply({ collapsed: true, peek: true });
            await settle(true);
          } else {
            apply({ collapsed: true, peek: false });
            // 选了一页、开了新页面:马上揭开让人看到它,列表在网页底下缩回去。
            if (instantClose.current) await uncover();
            else await settle(true);
            instantClose.current = false;
            setCompact(true);
          }
          continue;
        }
        break;
      }
      if (!shown.current.peek && alive.current) await uncover();
    } finally {
      running.current = false;
    }
    if (again.current && alive.current) void reconcile.current();
  };

  React.useEffect(() => {
    void reconcile.current();
  }, [collapsed, wantPeek]);

  // 展开着、过渡到一半被卸掉(回到 Mosael、换了会话):网页得回到原处。
  React.useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      window.clearTimeout(hoverTimer.current);
      window.clearTimeout(leaveTimer.current);
      if (covered.current) {
        covered.current = false;
        void bridge.coverPage(false).catch(() => undefined);
      }
    };
  }, [bridge]);

  const dismiss = React.useCallback((options: { instant?: boolean } = {}) => {
    instantClose.current = Boolean(options.instant);
    setDismissed(true);
    setFocused(false);
    const active = document.activeElement;
    if (active instanceof HTMLElement && ref.current?.contains(active)) active.blur();
  }, []);

  const toggle = () => {
    // 刚点了收起,鼠标还停在列表上:不该马上又临时展开,等移开再回来。
    if (!collapsed) dismiss();
    writeCollapsed(!collapsed);
    setCollapsed(!collapsed);
  };

  const handlers = {
    onMouseEnter: () => {
      window.clearTimeout(leaveTimer.current);
      setHovering(true);
      // 又移进来了:不管上回是怎么收回的(鼠标点的、键盘选的),这都是新的一次停留。
      setDismissed(false);
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = window.setTimeout(() => setLingering(true), HOVER_MS);
    },
    onMouseLeave: () => {
      window.clearTimeout(hoverTimer.current);
      window.clearTimeout(leaveTimer.current);
      const left = () => {
        setHovering(false);
        setLingering(false);
        setDismissed(false);
      };
      // 还没展开就移开(一掠而过):立刻算离开。
      if (shape.peek) leaveTimer.current = window.setTimeout(left, LEAVE_MS);
      else left();
    },
    onFocus: () => {
      setFocused(true);
      setDismissed(false);
    },
    onBlur: (event: React.FocusEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false);
    },
  };

  return {
    ref,
    /** 「收起」这个设置。 */
    collapsed,
    /** 列表此刻摆成的样子(网页左侧让出多宽跟着 `shape.collapsed`)。 */
    shape,
    compact,
    hovering,
    snapshot,
    /** 铺在原处的那张画面加载好了。 */
    backdropReady: () => backdropLoaded.current?.(),
    /** 过渡怎么走(要求减少动态时不走)。 */
    transition: (property: string) =>
      reduced ? "none" : `${property} ${PAGE_LIST_MOTION_MS}ms ${PAGE_LIST_EASING}`,
    toggle,
    dismiss,
    handlers,
  };
}

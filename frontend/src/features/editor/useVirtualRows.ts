import React from "react";

/**
 * 可变行高的窗口化列表:只渲染滚动视口里(含上下缓冲)的那几行,其余行用上下留白占位。
 *
 * 字幕面板每条一个 textarea、逐字稿上万个词按钮 —— 一小时的素材全部挂在 DOM 上,任何一次重渲
 * (选中、改一条、播放头换句)都要协调整张列表。行高不固定(正文会折行),所以:没量过的行按估计值
 * 占位,渲染出来后用 ResizeObserver 量真实高度回填,偏移量随之修正。
 *
 * 滚动不直接触发重渲:只有当应当渲染的 [start, end) 区间真的变了才写 state。
 */
export interface VirtualRows {
  /** 渲染区间 [start, end)。 */
  start: number;
  end: number;
  /** 区间之前 / 之后那些行的总高度,用作占位留白。 */
  padTop: number;
  padBottom: number;
  /** 行元素的 ref:量真实高度。按 key 缓存,同一行每次拿到的是同一个函数。 */
  measure: (key: string) => (element: HTMLElement | null) => void;
  /** 把第 index 行滚进视口(已在视口里就不动)—— 没渲染的行没有 DOM,不能指望 scrollIntoView。 */
  reveal: (index: number) => void;
}

/** 视口还没量到(首帧、测试环境)时按这个高度开窗,而不是退回全量渲染。 */
const FALLBACK_VIEWPORT_PX = 1200;

export function useVirtualRows({
  keys,
  scrollRef,
  listRef,
  estimate,
  overscanPx = 800,
}: {
  keys: readonly string[];
  /** 真正滚动的那个元素。 */
  scrollRef: React.RefObject<HTMLElement | null>;
  /** 行的直接父元素(滚动容器里它上面可能还有别的东西,偏移量要扣掉)。 */
  listRef: React.RefObject<HTMLElement | null>;
  estimate: number;
  overscanPx?: number;
}): VirtualRows {
  const heights = React.useRef(new Map<string, number>());
  const [measured, bumpMeasured] = React.useReducer((n: number) => n + 1, 0);

  // offsets[i] = 第 i 行的顶边(相对列表),offsets[n] = 总高。每次渲染重算:一万行也只是一遍加法。
  const offsets = React.useMemo(() => {
    const out = new Array<number>(keys.length + 1);
    out[0] = 0;
    for (let i = 0; i < keys.length; i++) out[i + 1] = out[i] + (heights.current.get(keys[i]) ?? estimate);
    return out;
    // measured:量到新高度时要重算。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, estimate, measured]);
  const offsetsRef = React.useRef(offsets);
  offsetsRef.current = offsets;

  const rangeFor = React.useCallback(
    (top: number, height: number): { start: number; end: number } => {
      const table = offsetsRef.current;
      const count = table.length - 1;
      const from = top - overscanPx;
      const to = top + (height || FALLBACK_VIEWPORT_PX) + overscanPx;
      // 第一行底边 > from 的行;二分。
      let lo = 0;
      let hi = count;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (table[mid + 1] > from) hi = mid;
        else lo = mid + 1;
      }
      let end = lo;
      while (end < count && table[end] < to) end++;
      return { start: lo, end };
    },
    [overscanPx],
  );

  const viewOf = React.useCallback((): { top: number; height: number } => {
    const scroller = scrollRef.current;
    if (!scroller) return { top: 0, height: 0 };
    const list = listRef.current;
    // 列表在滚动容器里的偏移(上面的说明、内边距)。
    const listTop = list ? list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop : 0;
    return { top: scroller.scrollTop - listTop, height: scroller.clientHeight };
  }, [scrollRef, listRef]);

  const [range, setRange] = React.useState<{ start: number; end: number }>(() => rangeFor(0, 0));
  const sync = React.useCallback(() => {
    const view = viewOf();
    const next = rangeFor(view.top, view.height);
    setRange((prev) => (prev.start === next.start && prev.end === next.end ? prev : next));
  }, [rangeFor, viewOf]);

  // 行数或量到的高度变了:区间要跟着重算(否则删掉几行后 end 越界、或新加的行不出现)。
  React.useLayoutEffect(() => {
    sync();
  }, [sync, offsets]);

  React.useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    let raf = 0;
    const schedule = () => {
      if (!raf)
        raf = requestAnimationFrame(() => {
          raf = 0;
          sync();
        });
    };
    scroller.addEventListener("scroll", schedule, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", schedule);
      observer?.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [scrollRef, sync]);

  // 行高测量:一个 observer 盯所有已渲染的行,高度变了才记一笔,并在下一帧合并成一次重算。
  const keyOf = React.useRef(new WeakMap<Element, string>());
  const rowObserver = React.useRef<ResizeObserver | null>(null);
  const pendingBump = React.useRef(0);
  const record = React.useCallback((element: Element) => {
    const key = keyOf.current.get(element);
    if (key === undefined) return;
    const height = (element as HTMLElement).offsetHeight;
    if (!height || heights.current.get(key) === height) return;
    heights.current.set(key, height);
    if (!pendingBump.current)
      pendingBump.current = requestAnimationFrame(() => {
        pendingBump.current = 0;
        bumpMeasured();
      });
  }, []);
  React.useEffect(
    () => () => {
      rowObserver.current?.disconnect();
      if (pendingBump.current) cancelAnimationFrame(pendingBump.current);
    },
    [],
  );
  const refs = React.useRef(new Map<string, (element: HTMLElement | null) => void>());
  const measure = React.useCallback(
    (key: string) => {
      let ref = refs.current.get(key);
      if (!ref) {
        let current: HTMLElement | null = null;
        ref = (element: HTMLElement | null) => {
          if (current && rowObserver.current) rowObserver.current.unobserve(current);
          current = element;
          if (!element) return;
          keyOf.current.set(element, key);
          if (!rowObserver.current && typeof ResizeObserver !== "undefined") {
            rowObserver.current = new ResizeObserver((entries) => entries.forEach((entry) => record(entry.target)));
          }
          rowObserver.current?.observe(element);
          record(element);
        };
        refs.current.set(key, ref);
      }
      return ref;
    },
    [record],
  );

  const reveal = React.useCallback(
    (index: number) => {
      const scroller = scrollRef.current;
      const table = offsetsRef.current;
      if (!scroller || index < 0 || index >= table.length - 1) return;
      const view = viewOf();
      const listTop = scroller.scrollTop - view.top;
      const top = table[index];
      const bottom = table[index + 1];
      if (top < view.top) scroller.scrollTop = listTop + top;
      else if (bottom > view.top + view.height) scroller.scrollTop = listTop + bottom - view.height;
    },
    [scrollRef, viewOf],
  );

  const start = Math.min(range.start, keys.length);
  const end = Math.min(Math.max(range.end, start), keys.length);
  return {
    start,
    end,
    padTop: offsets[start],
    padBottom: offsets[keys.length] - offsets[end],
    measure,
    reveal,
  };
}

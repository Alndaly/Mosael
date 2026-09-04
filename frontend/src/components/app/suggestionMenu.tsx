import React from "react";
import { createPortal } from "react-dom";
import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";

import { cn } from "@/lib/utils";

/**
 * 跟着光标走的候选菜单 —— TipTap suggestion 插件的**那一半界面**。
 *
 * 插件负责「什么时候出现、匹配到哪个字符、按键怎么走」;这里只负责「长什么样、摆在哪」。
 * 两个用它的地方(工作流的 `{{上游引用}}`、画板的 `@ 引用素材`)候选完全不同,而这一半
 * 一模一样 —— 抄两份的话,菜单的翻面、贴边、跟随都要各修一遍。
 *
 * 两条不显然的规矩,都是踩出来的:
 *
 *  · **位置交给 floating-ui,不自己算。** 要处理画布平移缩放(光标在动而菜单不知道)、
 *    贴到窗口边缘要翻面、容器滚动、祖先 transform 换掉 fixed 的基准。autoUpdate 用
 *    animationFrame:React Flow 的平移是改 CSS transform,既不是滚动也不是 resize。
 *  · **菜单要 portal 到 body。** 插件给的 clientRect 是屏幕坐标,而编辑器住在 React Flow
 *    的 viewport 里 —— 那个容器带着 transform,而祖先一旦有 transform 就成了后代
 *    `position: fixed` 的包含块。把屏幕坐标喂进去,菜单会跑到画布另一头还跟着缩放变形。
 */
export interface SuggestionMenuState<T> {
  items: T[];
  active: number;
  /** 没有候选时改为只说一句话。什么都不弹的话,这个键就是**静默无效**。 */
  hint?: string;
}

export interface SuggestionMenu<T> {
  menu: SuggestionMenuState<T> | null;
  /** 插件这一轮给出的**全部**候选(没过 view)。渲染表头(比如"共 N 个"、有哪些类型)用它。 */
  all: T[];
  /** 交给 `RefSuggestion.configure({ suggestion: { render } })`。 */
  render: () => {
    onStart: (props: { command: (item: T) => void; clientRect?: (() => DOMRect | null) | null; items: T[] }) => void;
    onUpdate: (props: { command: (item: T) => void; clientRect?: (() => DOMRect | null) | null; items: T[] }) => void;
    onKeyDown: (props: { event: KeyboardEvent }) => boolean;
    onExit: () => void;
  };
  /** 确认某一条(点击走这里;回车由 onKeyDown 处理)。 */
  choose: (item: T) => void;
  /** 把菜单画出来 —— 每一条长什么样由调用方给。 */
  Portal: (props: {
    children: (item: T, index: number) => React.ReactNode;
    className?: string;
    /** 钉在列表上方、**不跟着滚**的一条:筛选按钮这类"作用于下面整份列表"的东西。 */
    header?: React.ReactNode;
    /** 列表下方的一行,比如「还有 N 个」。 */
    footer?: React.ReactNode;
  }) => React.ReactNode;
}

export function useSuggestionMenu<T>({
  /** 没有任何候选时说的那句话。返回空串 = 什么都不弹。 */
  emptyHint,
  /** 两条候选算不算「同一批」—— 同一批时保留用户按下去的高亮位置,不弹回第一条。 */
  sameItems = (a: T[], b: T[]) => a.length === b.length && a.every((one, at) => one === b[at]),
  /**
   * 把插件给的候选**再过一道**:筛选、排序、截断。
   *
   * **筛选必须发生在这里,不能放进 `items()`。** 插件只在 query / 光标位置变了才重新调
   * `items()`(见 @tiptap/suggestion 的 update:`queryChanged || textChanged || rangeChanged`)——
   * 而按一下筛选钮这三样一个都没变。放进 items() 的筛选按下去列表纹丝不动,而且不报错。
   *
   * 过完之后 `menu.items` 就是**看得见的那一份**,键盘高亮和回车选中都对着它 —— 不然
   * 上下键走的是原始列表,选中的和高亮的不是同一条。
   */
  view,
}: {
  emptyHint?: () => string;
  sameItems?: (a: T[], b: T[]) => boolean;
  view?: (items: T[]) => T[];
} = {}): SuggestionMenu<T> {
  //: 插件这一轮给出的原始候选。**和可见列表分开存** —— 筛选一变,要能就着原始的重新过一遍,
  //: 而插件那时候不会再调 items()。
  const [raw, setRaw] = React.useState<T[]>([]);
  const [menu, setMenu] = React.useState<SuggestionMenuState<T> | null>(null);
  //: 插件给的**是个函数**,每次调用返回当前的光标矩形。存函数而不是存算好的坐标 ——
  //: 存坐标就成了一张快照:画布一平移,光标动了而菜单不知道,于是它钉在原地。
  const clientRectRef = React.useRef<(() => DOMRect | null) | null>(null);
  const menuEl = React.useRef<HTMLDivElement | null>(null);
  //: 插件的 onKeyDown 闭包住了创建时的 state,用 ref 读当前高亮项。
  const menuRef = React.useRef(menu);
  menuRef.current = menu;
  const commandRef = React.useRef<((item: T) => void) | null>(null);
  const emptyRef = React.useRef(emptyHint);
  emptyRef.current = emptyHint;
  const sameRef = React.useRef(sameItems);
  sameRef.current = sameItems;

  const viewRef = React.useRef(view);
  viewRef.current = view;

  const next = React.useCallback((prev: SuggestionMenuState<T> | null, source: T[]): SuggestionMenuState<T> | null => {
    const items = viewRef.current ? viewRef.current(source) : source;
    if (items.length) {
      const active = prev && !prev.hint && sameRef.current(prev.items, items) ? prev.active : 0;
      return { items, active };
    }
    const hint = emptyRef.current?.() ?? "";
    //: 有候选源、只是这次输入没匹配上 → 不打扰,继续敲两下自己就出来了。
    return hint ? { items: [], active: 0, hint } : null;
  }, []);

  const render = React.useCallback(
    () => ({
      // **onStart 和 onUpdate 用同一条规则。** tiptap 在同一次输入里 onStart 之后紧接着就调
      // onUpdate —— 两边写两份的话,onStart 刚摆上的东西会被 onUpdate 立刻清掉,表现是
      // 「提示闪一下就没了」(实测:根本看不见,像完全没实现)。
      onStart: (props: { command: (item: T) => void; clientRect?: (() => DOMRect | null) | null; items: T[] }) => {
        commandRef.current = props.command;
        clientRectRef.current = props.clientRect ?? null;
        setRaw(props.items);
        setMenu((prev) => next(prev, props.items));
      },
      onUpdate: (props: { command: (item: T) => void; clientRect?: (() => DOMRect | null) | null; items: T[] }) => {
        commandRef.current = props.command;
        clientRectRef.current = props.clientRect ?? null;
        setRaw(props.items);
        setMenu((prev) => next(prev, props.items));
      },
      // **按键交给插件**:它知道 composition,中文选词时的回车不会被当成「选中候选」。
      onKeyDown: (props: { event: KeyboardEvent }) => {
        const key = props.event.key;
        if (key === "Escape") {
          setMenu(null);
          return true;
        }
        if (key === "ArrowDown" || key === "ArrowUp") {
          setMenu((prev) =>
            prev && prev.items.length
              ? {
                  ...prev,
                  active: (prev.active + (key === "ArrowDown" ? 1 : -1) + prev.items.length) % prev.items.length,
                }
              : prev,
          );
          return true;
        }
        if (key === "Enter" || key === "Tab") {
          const current = menuRef.current;
          if (!current || current.items.length === 0) return false;
          commandRef.current?.(current.items[current.active]);
          return true;
        }
        return false;
      },
      onExit: () => {
        setRaw([]);
        setMenu(null);
      },
    }),
    [next],
  );

  //: 筛选变了(view 换了身份)就着**原始候选**重新过一遍。插件这时候不会再调 items(),
  //: 不自己重算的话,按下去的筛选钮什么都不会发生。
  const firstView = React.useRef(true);
  React.useEffect(() => {
    if (firstView.current) {
      firstView.current = false;
      return;
    }
    setMenu((prev) => (prev ? next(prev, raw) : prev));
  }, [view, raw, next]);

  React.useEffect(() => {
    const floating = menuEl.current;
    const getRect = clientRectRef.current;
    if (!menu || !floating || !getRect) return;
    const reference = { getBoundingClientRect: () => getRect() ?? new DOMRect() };
    return autoUpdate(
      reference,
      floating,
      () => {
        void computePosition(reference, floating, {
          placement: "bottom-start",
          // 贴着光标下方 6px;放不下就翻到上方;左右不够就往里挪,别被窗口切掉。
          middleware: [offset(6), flip(), shift({ padding: 8 })],
        }).then(({ x, y }) => {
          floating.style.left = `${x}px`;
          floating.style.top = `${y}px`;
        });
      },
      { animationFrame: true },
    );
  }, [menu]);

  const choose = React.useCallback((item: T) => commandRef.current?.(item), []);

  const Portal = React.useCallback(
    ({
      children,
      className,
      header,
      footer,
    }: {
      children: (item: T, index: number) => React.ReactNode;
      className?: string;
      header?: React.ReactNode;
      footer?: React.ReactNode;
    }) => {
      if (!menu) return null;
      //: 有表头/表尾时,滚动只发生在**中间那一段** —— 整块一起滚的话,筛选钮会跟着列表滚走,
      //: 而它作用于整份列表。没有表头时保持原样(一整块可滚),不给已有的调用方添麻烦。
      const banded = Boolean(header || footer);
      return createPortal(
        <div
          ref={menuEl}
          data-suggestion-menu=""
          className={cn(
            className ??
              "fixed left-0 top-0 z-50 max-h-48 min-w-[180px] rounded-md border border-border bg-panel p-1 shadow-[var(--shadow-panel)]",
            banded ? "flex flex-col overflow-hidden" : "overflow-auto",
          )}
        >
          {header}
          <div className={banded ? "min-h-0 flex-1 overflow-auto" : undefined}>
            {menu.hint ? (
              <div className="px-2 py-1 text-ui-2xs leading-relaxed text-muted-foreground">{menu.hint}</div>
            ) : null}
            {menu.items.map((item, index) => children(item, index))}
          </div>
          {footer}
        </div>,
        document.body,
      );
    },
    [menu],
  );

  return { menu, all: raw, render, choose, Portal };
}

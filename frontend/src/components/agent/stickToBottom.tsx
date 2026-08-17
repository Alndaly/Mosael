import React from "react";
import { ArrowDown } from "lucide-react";

/**
 * 对话正文的「贴底跟随」。
 *
 * 三处各抄了一遍(AI 工作台的两个面板 + 工作流助手),而其中两份逐字符相同、第三份是无条件
 * `scrollTop = scrollHeight`(用户往上翻历史会被硬拽回底部)。抄一遍就多一处会独立坏掉的地方。
 *
 * **跟随只由「往上看」解除,不由「离底部多远」解除。** 上一版的判据是距底距离:
 *
 *     onScroll = () => { stick = el.scrollHeight - el.scrollTop - el.clientHeight < 140 }
 *
 * 它有一个必然的竞态。内容长高之后我们把 `scrollTop` 顶到底,而浏览器要到**下一帧**才派发
 * scroll 事件;若这中间内容又长了一截,处理器读到的距底距离就超了阈值,跟随被关掉 —— 而它
 * 只在用户手动滚回底部时才会重开,所以之后整段流式输出都不再跟随。渲染越慢、每帧长得越多,
 * 越容易撞上,这正是「Windows 上不会自动滚动」的由来。
 *
 * 换成看 `scrollTop` 的**方向**,这个竞态就不存在了:内容在下方增长时 `scrollTop` 不变,
 * 只有用户往上滚 / 往上拖滚动条才会让它变小。判据于是和「内容长多快」彻底无关。
 *
 * 交互按 Claude / ChatGPT 那套:跟随时钉在底部;用户往上翻就停下,并给一个「回到最新」的出口;
 * 滚回底部附近自动恢复跟随;自己发消息一定回到底部。
 */

/** 距底多少像素以内算「在底部」。手指和滚轮很难精确停在 0。 */
const BOTTOM_SLACK = 48;

/** 小于这个位移不算「往上看」—— 触控板的惯性回弹、亚像素抖动都在这个量级。 */
const UP_NOISE = 2;

export type StickToBottom<T extends HTMLElement> = {
  /** 挂到滚动容器上。 */
  ref: React.RefObject<T | null>;
  /** 当前是否跟着最新内容走。为 false 时该露出「回到最新」。 */
  pinned: boolean;
  /** 不跟随期间底下又长出了新内容 —— 用来把按钮从"回到底部"强调成"有新消息"。 */
  unseen: boolean;
  /** 回到底部并恢复跟随。用户点按钮、或自己发出一条消息时调。 */
  scrollToBottom: () => void;
};

export function useStickToBottom<T extends HTMLElement>(resetKey?: unknown): StickToBottom<T> {
  const ref = React.useRef<T | null>(null);
  //: 跟随状态存两份:ref 给事件处理器读(它们不该因为 state 变化而重新绑),state 给界面渲染。
  const pinnedRef = React.useRef(true);
  const lastTopRef = React.useRef(0);
  const [pinned, setPinned] = React.useState(true);
  const [unseen, setUnseen] = React.useState(false);

  const setPinnedBoth = React.useCallback((next: boolean) => {
    pinnedRef.current = next;
    setPinned(next);
    if (next) setUnseen(false);
  }, []);

  const scrollToBottom = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // **不走 `scrollTo({ behavior: "smooth" })`**:实测在 Electron 这类环境里它会被整个忽略 ——
    // scrollTop 一动不动,而我们已经把状态翻成"在跟随了",于是按钮消失、画面却还停在原处。
    // 直接赋值是各处都真的会动的写法(`follow()` 用的也是它),浏览器自己夹到可达范围内。
    el.scrollTop = el.scrollHeight;
    lastTopRef.current = el.scrollTop; // 读回夹取后的真值,别记一个到不了的数
    setPinnedBoth(true);
  }, [setPinnedBoth]);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const atBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK;

    const onScroll = () => {
      const top = el.scrollTop;
      const wentUp = top < lastTopRef.current - UP_NOISE;
      lastTopRef.current = top;
      // 往上看 = 停下来读;滚回底部附近 = 接着跟。中间地带保持现状,不来回抖。
      if (wentUp && !atBottom()) setPinnedBoth(false);
      else if (atBottom()) setPinnedBoth(true);
    };

    const follow = () => {
      if (!pinnedRef.current) {
        // 不跟随时也要知道"底下有新东西了",否则按钮无从区分「回到底部」和「有新消息」。
        setUnseen(true);
        return;
      }
      el.scrollTop = el.scrollHeight;
      lastTopRef.current = el.scrollTop;
    };

    // 图片、字体、代码高亮加载完只改高度,**不产生 mutation** —— 那一类由它接住。
    // 观察每个直接子项而不是容器自己:容器的高度是布局定的,内容长高时它并不变。
    const resize = new ResizeObserver(follow);
    const watched = new Set<Element>();
    const syncResizeTargets = () => {
      for (const child of Array.from(el.children)) {
        if (watched.has(child)) continue;
        watched.add(child);
        resize.observe(child);
      }
    };
    syncResizeTargets();

    // markdown 是**异步长高**的:发一条消息后一次性 scrollTo 会落在半截,所以盯着内容变化跟。
    // 我们自己改 scrollTop 不产生 mutation,所以这里不必防自激。
    const mutation = new MutationObserver(() => {
      syncResizeTargets();
      follow();
    });
    mutation.observe(el, { childList: true, subtree: true, characterData: true });

    el.addEventListener("scroll", onScroll, { passive: true });
    el.scrollTop = el.scrollHeight;
    lastTopRef.current = el.scrollTop;
    return () => {
      el.removeEventListener("scroll", onScroll);
      mutation.disconnect();
      resize.disconnect();
    };
    // resetKey 换了(切会话)就整套重来:新会话该从底部开始,而不是继承上一个的滚动位置。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, setPinnedBoth]);

  // 切会话时把跟随打开 —— 上一个会话里用户翻到了半截,不该带进新会话。
  React.useEffect(() => {
    setPinnedBoth(true);
  }, [resetKey, setPinnedBoth]);

  return { ref, pinned, unseen, scrollToBottom };
}

/**
 * 「回到最新」。不跟随时才出现 —— 跟随中它没有用处,常驻只会挡住正文。
 *
 * 放在滚动容器**外面**用绝对定位:放进容器里的话它会跟着内容一起滚走,
 * 而这个按钮的意义正是"你已经不在底部了"。
 */
export function JumpToLatest({
  stick,
  label,
  newLabel,
}: {
  stick: Pick<StickToBottom<HTMLElement>, "pinned" | "unseen" | "scrollToBottom">;
  label: string;
  newLabel: string;
}) {
  if (stick.pinned) return null;
  return (
    <button
      type="button"
      onClick={() => stick.scrollToBottom()}
      className="absolute bottom-2.5 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-panel px-2.5 py-1 text-ui-2xs text-muted-foreground shadow-[var(--shadow-panel)] hover:bg-muted hover:text-foreground"
    >
      <ArrowDown size={11} />
      {stick.unseen ? newLabel : label}
    </button>
  );
}

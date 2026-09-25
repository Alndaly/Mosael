import React from "react";
import { Search } from "lucide-react";

import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { isTypingTarget, listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/**
 * 画布上的「查找节点」。**工作流和创意画板共用这一份。**
 *
 * 此前它只长在工作流的工具条里,是一段就地写的弹层:列出匹配的节点、点一下跳过去。画板要同样的
 * 东西时,照抄一份的话两边的匹配规则、键位、高亮迟早各走各的 —— 用户在一块画布上学会的 ⌘F,
 * 到另一块上就不灵了。
 *
 * 行为照「在页面里查找」的习惯:⌘F 打开,边打字边把命中的节点在画布上圈出来,Enter 跳到下一个、
 * ⇧Enter 上一个(到头绕回),Esc 关掉并清掉高亮。点列表里的某一行是"就要这个":跳过去并收起。
 *
 * **画布只需要给两样东西**:一份可搜的条目(每块画布自己知道节点上哪些字该被搜到),和一个
 * "跳到这个 id"的动作。高亮经 `onHighlight` 交回去,由画布自己决定怎么画 —— 用
 * `searchHighlightClass` 那一套,两块画布的圈长得一样。
 */

export interface CanvasSearchEntry {
  id: string;
  /** 列表里那一行的名字。 */
  title: string;
  /** 名字右边的小字(一般是类型)。和 title 一样时不显示 —— 未改名的节点名字就是类型。 */
  subtitle?: string;
  /** 另外参与匹配、但不显示的字:正文、提示词、类型的原始值。 */
  text?: readonly string[];
}

export interface CanvasSearchHighlight {
  /** 所有命中的节点。 */
  ids: ReadonlySet<string>;
  /** 当前跳到的那一个。还没按过 Enter 时是 null。 */
  activeId: string | null;
}

/** 按字面包含匹配,不分大小写。空查询返回全部 —— 打开时先把节点都列出来,和此前一致。 */
export function matchCanvasEntries<E extends CanvasSearchEntry>(entries: readonly E[], query: string): E[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...entries];
  return entries.filter((entry) =>
    [entry.title, entry.subtitle ?? "", ...(entry.text ?? [])].some((one) => one.toLowerCase().includes(needle)),
  );
}

/**
 * 下一个 / 上一个。**到头绕回**,和编辑器里的查找一样。还没跳过(null)时,往后从第一个开始、
 * 往前从最后一个开始。
 */
export function stepCanvasMatch(active: number | null, count: number, direction: 1 | -1): number | null {
  if (count <= 0) return null;
  if (active === null || active >= count) return direction === 1 ? 0 : count - 1;
  return (active + direction + count) % count;
}

/**
 * 命中的节点在画布上的样子:外面一圈主色描边。当前那个实线、其余半透明。
 *
 * 画在 React Flow 的节点外壳上(`node.className`),用 outline 而不是 border/ring —— 不占布局,
 * 不会把节点撑大一圈,也不和节点自己的选中框抢同一个属性。
 */
const MATCH_CLASS = "rounded-[10px] outline outline-2 outline-offset-4 outline-primary/45";
const ACTIVE_CLASS = "rounded-[10px] outline outline-[3px] outline-offset-4 outline-primary";

export function searchHighlightClass(highlight: CanvasSearchHighlight | null | undefined, id: string): string | undefined {
  if (!highlight?.ids.has(id)) return undefined;
  return highlight.activeId === id ? ACTIVE_CLASS : MATCH_CLASS;
}

export function CanvasNodeSearch({
  entries,
  onFocus,
  onHighlight,
  selectedId,
  placeholder = "wfNodeSearchPlaceholder",
}: {
  entries: readonly CanvasSearchEntry[];
  /** 跳到这个节点。怎么跳(居中、缩放、要不要选中)由画布决定。 */
  onFocus: (id: string) => void;
  /** 命中集变了。null = 没在查(关着,或者查询是空的)—— 画布把圈全摘掉。 */
  onHighlight?: (highlight: CanvasSearchHighlight | null) => void;
  /** 画布上当前选中的那个,在列表里标出来。 */
  selectedId?: string | null;
  placeholder?: MessageKey;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState<number | null>(null);
  const input = React.useRef<HTMLInputElement | null>(null);
  const list = React.useRef<HTMLDivElement | null>(null);

  const matches = React.useMemo(() => matchCanvasEntries(entries, query), [entries, query]);
  // 结果集变短时游标可能越界 —— 越界就当作"还没跳"。
  const current = active !== null && active < matches.length ? active : null;
  const activeId = current === null ? null : matches[current]!.id;
  const searching = open && query.trim() !== "";

  // 换了查询词,游标回到"还没跳":上一轮的第 3 个和这一轮的第 3 个不是同一个东西。
  React.useEffect(() => setActive(null), [query]);

  // 高亮交回画布。按 id 串比较而不是按数组引用:entries 每次画布变动都是新数组,
  // 不这样的话拖一下节点就要让整块画布重画一遍高亮。
  const onHighlightRef = React.useRef(onHighlight);
  onHighlightRef.current = onHighlight;
  const idsKey = searching ? matches.map((entry) => entry.id).join("\u0000") : "";
  React.useEffect(() => {
    if (!searching) {
      onHighlightRef.current?.(null);
      return;
    }
    onHighlightRef.current?.({ ids: new Set(idsKey ? idsKey.split("\u0000") : []), activeId });
  }, [searching, idsKey, activeId]);
  // 卸载时(离开这块画布)把圈摘掉,不留在下一次进来的画布上。
  React.useEffect(() => () => onHighlightRef.current?.(null), []);

  // 列表里当前那一行跟着滚进视野 —— 按了十几次 Enter 之后,当前项早就在列表底下看不见了。
  React.useEffect(() => {
    if (activeId === null) return;
    list.current
      ?.querySelector<HTMLElement>(`[data-search-entry="${CSS.escape(activeId)}"]`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);

  /**
   * ⌘/Ctrl+F 打开。**焦点在能打字的地方时不劫持** —— 在便签、提示词、检查器里按 ⌘F,
   * 那一刻的"查找"说的是那段文字,不是画布上的节点(和 ⌘N 同一个判据)。
   * 已经开着、焦点就在搜索框里时再按一次:全选查询词,方便直接换一个词。
   */
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.key.toLowerCase() !== "f") return;
      if (event.target !== input.current && isTypingTarget(event.target)) return;
      event.preventDefault();
      setOpen(true);
      requestAnimationFrame(() => input.current?.select());
    };
    return listenKeys(window, onKey);
  }, []);

  const close = () => {
    setOpen(false);
    setQuery("");
  };

  const step = (direction: 1 | -1) => {
    const next = stepCanvasMatch(current, matches.length, direction);
    if (next === null) return;
    setActive(next);
    onFocus(matches[next]!.id);
  };

  return (
    <Popover open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          className={cn("text-muted-foreground hover:text-foreground", open && "bg-secondary text-foreground")}
          aria-label={t("wfNodeSearch")}
          title={`${t("wfNodeSearch")}  ⌘F`}
          aria-pressed={open}
        >
          <Search size={14} />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[280px] p-1.5"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          input.current?.focus();
        }}
      >
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={input}
            className="h-8 pl-[30px] pr-12 text-ui-sm focus-visible:border-primary focus-visible:ring-0"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t(placeholder)}
            aria-label={t("wfNodeSearch")}
            onKeyDown={(event) => {
              // 输入法还在组词时的 Enter 是"上屏",不是"下一个" —— 中文用户每打一个词都会误跳一次。
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter") {
                event.preventDefault();
                step(event.shiftKey ? -1 : 1);
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                step(1);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                step(-1);
              }
            }}
          />
          {query.trim() && (
            <span
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ui-xs tabular-nums text-muted-foreground"
              data-search-count=""
            >
              {`${current === null ? 0 : current + 1}/${matches.length}`}
            </span>
          )}
        </div>
        <div ref={list} className="mt-1.5 flex max-h-80 flex-col gap-0.5 overflow-auto">
          {matches.length === 0 ? (
            <div className="px-2 py-2.5 text-center text-xs text-muted-foreground">{t("wfNodeSearchEmpty")}</div>
          ) : (
            matches.map((entry, index) => {
              const sub = entry.subtitle && entry.subtitle !== entry.title ? entry.subtitle : null;
              return (
                <button
                  key={entry.id}
                  type="button"
                  data-search-entry={entry.id}
                  aria-current={index === current ? "true" : undefined}
                  className={cn(
                    "flex cursor-pointer items-baseline justify-between gap-2.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted",
                    (index === current || (current === null && entry.id === selectedId)) && "bg-accent hover:bg-accent",
                  )}
                  onClick={() => {
                    onFocus(entry.id);
                    close();
                  }}
                >
                  <span className="truncate text-ui-sm font-semibold text-foreground">{entry.title}</span>
                  {sub && <span className="shrink-0 text-ui-xs text-muted-foreground">{sub}</span>}
                </button>
              );
            })
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-3 border-t border-divider px-2 pt-1.5 text-ui-2xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Kbd>↵</Kbd> {t("canvasSearchNext")}
          </span>
          <span className="inline-flex items-center gap-1">
            <Kbd>⇧↵</Kbd> {t("canvasSearchPrev")}
          </span>
          <span className="inline-flex items-center gap-1">
            <Kbd>Esc</Kbd> {t("close")}
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}

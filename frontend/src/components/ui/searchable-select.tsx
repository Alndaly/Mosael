import * as React from "react";
import { defaultFilter } from "cmdk";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { FieldSize } from "@/components/ui/control-size";
import { fieldTriggerClass, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger";
import { insideDialog } from "@/components/ui/insideDialog";
import { SEARCHABLE_CONTENT_WIDTH, SEARCHABLE_CONTENT_WIDTH_WITH_DESCRIPTIONS } from "@/components/ui/floating";
import { Hint, type HintShortcut } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

type Option = {
  value: string;
  label: string;
  /** 副标题,灰色小字排在标签下面。用来解释"这一项是干什么的"。 */
  description?: string;
  /** 分组标题。相邻的同名项归一组;顺序即传入顺序,这里不排序 —— 谁提供选项,谁决定顺序。 */
  group?: string;
  /** 行首图标。当动作菜单用时(画板的「添加」)每一行都给一个 —— 同一个菜单里有的行有图标、有的没有,
   *  文字就对不齐(和 ActionMenu 的 MenuAction.icon 同一条规矩)。 */
  icon?: React.ReactNode;
  /** 不展示但参与搜索的稳定名/别名。展示名变成人话后，仍可按内部标识精确查找。 */
  keywords?: string[];
  /** 只作用在这一项的行内样式。用于**用样式本身当信息**的清单:字体选择器按各自的字体渲染。 */
  style?: React.CSSProperties;
  /** 行首的一张小图(模型文件的缩略图),比 `icon` 大一号。 */
  media?: React.ReactNode;
  /** 挂在上一项下面、缩进一格(同一张工作流的表单入口挂在它的完整工作流下面,ADR 0045)。顺序仍由提供选项的一方定。 */
  indent?: boolean;
  /**
   * 这一项属于组里的哪一小组(有表单的工作流:组标题是工作流名 + 连接名,下面「完整工作流」和每张表单各一行,ADR 0045 §7)。
   * 相邻的同一个 `key` 归一小组,上面一行不能选的小标题,组里的行缩进一格。**搜索命中小组里任何一行,整个小组留着**
   * (按原来的顺序),命中的那几行加粗 —— 搜「精调」还看得见它是哪张工作流的、旁边还有哪几个入口。
   */
  section?: OptionSection;
  /** 选中之后触发器上写什么(小组里的行名字常是「完整工作流」,单独写在触发器上说不清是哪张);不给就是 `label`。 */
  selectedLabel?: string;
};

export type OptionSection = { key: string; label: string; subtitle?: string };

/**
 * 可搜索、限高的下拉——用于选项多到普通 Select 会溢出屏幕的场景(如 ComfyUI 的 checkpoint/采样器
 * 可能上百项)。Popover + cmdk:输入即过滤,列表封顶高度内滚动,宽度对齐触发器。
 *
 * Popover 必须带 `modal`:Dialog 用 react-remove-scroll 锁背景滚动,只放行自己 shard
 * (DialogContent)内的滚轮,而 PopoverContent 走 Portal 渲染到 body、落在 shard 之外——不加 modal
 * 时列表明明可滚、滚动条也在,滚轮却完全无效(拖滚动条/方向键仍可用,是这个故障的特征组合)。
 * 加了之后 Popover 自建滚动锁并把自己的内容作为放行区;对话框外的行为也一致(与原生 select 相同)。
 */
/**
 * 列表一次先画这么多行,滚到离底部不到 `MORE_WITHIN_PX` 时再接一批。
 *
 * ComfyUI 的 checkpoint / LoRA 清单动辄几百项,每行一张缩略图、一个会量自己截没截断的名字(Truncate)。此前一打开
 * 就全挂上,而 cmdk 自己过滤时每敲一个字要给全部项打分、再把每一行的 DOM 挨个挪一遍来排序 —— 300 项实测一个字
 * 1–1.6 秒。现在过滤和排序在这里做(同一个打分函数 `defaultFilter`,顺序和以前一样),cmdk 只管键盘和选中,
 * 列表只画前一段:看得见的那几十行之外的不挂。方向键走到最后一行时 cmdk 把它滚进视口,滚动接着画下一批。
 */
export const RENDER_BATCH = 60;
const MORE_WITHIN_PX = 240;

type Row = Option & { hit?: boolean };
type Group = [string, Row[]];

/** 相邻的同名 group 归一组,不重排(顺序由提供选项的一方定,见下面 groups 那段说明)。 */
function groupAdjacent(items: Option[]): Group[] {
  const out: Group[] = [];
  for (const item of items) {
    const heading = item.group ?? "";
    const last = out[out.length - 1];
    if (last && last[0] === heading) last[1].push(item);
    else out.push([heading, [item]]);
  }
  return out;
}

/**
 * 按搜索词过滤、排序:和 cmdk 自己过滤时同一个打分(`defaultFilter`,按 value 和 keywords 打),同一种排法 ——
 * 组内按分数高低,组按组里最高的那一项;分数一样的保持原来的先后。一个小组(`section`)当一项排:分数是组里最高的
 * 那一行,命中一行整个小组留着、按原来的顺序,命中的行标 `hit`。
 */
function filterGroups(items: Option[], query: string): Group[] {
  if (!query) return groupAdjacent(items);
  type Unit = { score: number; index: number; rows: Row[] };
  const byHeading = new Map<string, { best: number; order: number; units: Map<string, Unit> }>();
  items.forEach((item, index) => {
    const score = defaultFilter(item.value, query, keywordsOf(item));
    const heading = item.group ?? "";
    const group = byHeading.get(heading) ?? { best: 0, order: byHeading.size, units: new Map<string, Unit>() };
    const unitKey = item.section ? `section:${item.section.key}` : `item:${item.value}`;
    const unit = group.units.get(unitKey) ?? { score: 0, index, rows: [] };
    unit.rows.push({ ...item, hit: score > 0 });
    unit.score = Math.max(unit.score, score);
    group.units.set(unitKey, unit);
    group.best = Math.max(group.best, score);
    byHeading.set(heading, group);
  });
  return [...byHeading.entries()]
    .filter(([, group]) => group.best > 0)
    .sort(([, a], [, b]) => b.best - a.best || a.order - b.order)
    .map(([heading, group]) => [
      heading,
      [...group.units.values()].filter((unit) => unit.score > 0)
        .sort((a, b) => b.score - a.score || a.index - b.index).flatMap((unit) => unit.rows),
    ]);
}

/** 能搜到这一项的字:标签、描述(用户记得住「发抖音」却未必记得节点叫「发布」)和调用方给的关键词。 */
function keywordsOf(item: Option): string[] {
  return [item.label, item.description ?? "", ...(item.keywords ?? [])].filter(Boolean);
}

/** 只留前 `limit` 行(跨组计数),组标题跟着它的第一行走。 */
function firstRows(groups: Group[], limit: number): Group[] {
  const out: Group[] = [];
  let left = limit;
  for (const [heading, rows] of groups) {
    if (left <= 0) break;
    out.push([heading, rows.slice(0, left)]);
    left -= rows.length;
  }
  return out;
}

function useInsideDialog(ref: React.RefObject<HTMLElement | null>): boolean {
  const [inside, setInside] = React.useState(false);
  React.useEffect(() => {
    setInside(insideDialog(ref.current));
  });
  return inside;
}

export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder,
  emptyText,
  className,
  size,
  contentClassName,
  disabled,
  trigger,
  hint,
  shortcut,
  missingLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: Array<Option | string>;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  /** 默认触发器的档位,和 `<Input size>`、`<Button size>` 同一把尺。自定义 `trigger` 时不起作用。 */
  size?: FieldSize;
  /** 浮层自己的类名(不写宽度:宽度规则在 floating.ts 的 SEARCHABLE_CONTENT_WIDTH,棘轮 design/menuWidths.test.ts)。 */
  contentClassName?: string;
  disabled?: boolean;
  /** 自定义触发器(替换默认按钮),用于像「添加节点」这类带图标/胶囊样式的触发器。 */
  trigger?: React.ReactNode;
  /** 触发器的悬停说明(为什么点不了、这一格选的是什么)。套在触发器外面 —— 套在自定义 trigger 里会被 PopoverTrigger 吞掉属性。 */
  hint?: string | null;
  /** 打开它的快捷键(画板「添加」的 ⌘N),画在悬停说明的名字那一行。 */
  shortcut?: HintShortcut | null;
  /**
   * 记着的那一项现在不在清单里(用不了,见 lib/generationCapabilities 的 chooseGenerationOption):触发器上写它(人话的名字 +
   * 「需要升级」/「用不了」,警示色),不写占位的「选择模型」—— 显示的就是记着的那个,不是空着、也不是别的。
   */
  missingLabel?: string | null;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  /* ref 挂在 PopoverTrigger 上:asChild 的 Slot 把它合进触发器(自定义的 trigger 也一样 —— 浮层
     本来就要靠这个 ref 定位,接不住 ref 的触发器早就弹不出来)。**不在旁边另插一个探针元素**:
     下拉常是表单网格里的一格,多出来的兄弟会占掉一格 —— `[&>span]:flex` 这类行样式还会把
     `hidden` 顶掉,空 span 占住右格,下拉被挤到下一行的 112px 标签列里。 */
  const triggerRef = React.useRef<HTMLElement>(null);
  const modal = useInsideDialog(triggerRef);
  const items: Option[] = React.useMemo(
    () => options.map((option) => (typeof option === "string" ? { value: option, label: option } : option)),
    [options],
  );
  const selected = items.find((item) => item.value === value);
  const selectedText = selected?.selectedLabel ?? selected?.label;
  const missing = !selected && Boolean(missingLabel);
  const hasDescriptions = items.some((item) => item.description);
  // 按**相邻**的同名 group 归组,不重排 —— 提供选项的一方已经排好了顺序(节点面板的
  // 分组顺序来自后端的 NODE_CATEGORIES),这里再排一次就成了第二份要维护的顺序。
  //
  // 代价是**调用方得把同一组的选项挨着写**:隔开写的话,同一个组名会渲染出两个小标题,
  // 而且不会报任何错。画板的「添加」菜单栽过这一下 —— 「选一张图片」排在最末,菜单里
  // 就出现了两个「素材库」。
  const [search, setSearch] = React.useState("");
  const query = search.trim();
  const groups = React.useMemo(() => filterGroups(items, query), [items, query]);
  const total = React.useMemo(() => groups.reduce((sum, [, rows]) => sum + rows.length, 0), [groups]);
  // 打开时选中的那一项排在第一批之后:画到它为止,勾才看得见(只在没搜索时;一搜就从头画)。
  const selectedIndex = query ? -1 : items.findIndex((item) => item.value === value);
  const [limit, setLimit] = React.useState(RENDER_BATCH);
  React.useEffect(() => setLimit(Math.max(RENDER_BATCH, selectedIndex + 1)), [query, open, selectedIndex]);
  const shown = React.useMemo(() => firstRows(groups, limit), [groups, limit]);
  const more = (event: React.UIEvent<HTMLDivElement>) => {
    const list = event.currentTarget;
    if (limit < total && list.scrollHeight - list.scrollTop - list.clientHeight < MORE_WITHIN_PX) {
      setLimit((current) => Math.min(total, current + RENDER_BATCH));
    }
  };
  const openChange = (next: boolean) => {
    setOpen(next);
    if (!next) setSearch("");
  };
  return (
    <Popover modal={modal} open={open} onOpenChange={openChange}>
      <Hint label={hint} shortcut={shortcut}>
        <PopoverTrigger asChild ref={triggerRef as React.Ref<HTMLButtonElement>}>
          {trigger ?? (
            <button
              type="button"
              disabled={disabled}
              /* **共用 fieldTriggerClass**,不再手抄一份。抄出来的那份是 h-8 / gap-1 /
                 px-2.5,而 Select 和 Combobox 是 h-10 / gap-1.5 / px-3 —— 三种控件并排在同一行
                 表单里时(插件的「新建连接」就是下拉+输入框+按钮),下拉比旁边矮 8px、左右
                 留白也窄一截。那正是这个 token 的注释点名要消灭的情况。 */
              className={cn(fieldTriggerClass(size), "text-foreground", className)}
              data-missing={missing ? "" : undefined}
            >
              {/* min-w-0:flex 子项默认不肯收缩,truncate 会失效(见 field-trigger.ts)。
                  未选中时走 placeholder 色:和输入框的 placeholder 同一个视觉约定 —— 用正文色
                  写「平台」,读起来像是**已经选了**一个叫「平台」的东西。 */}
              <Truncate className={cn(!selected && (missing ? "text-warning" : "text-muted-foreground"))}>
                {selectedText ?? (missing ? missingLabel : null) ?? placeholder ?? ""}
              </Truncate>
              <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
            </button>
          )}
        </PopoverTrigger>
      </Hint>
      <PopoverContent
        className={cn(
          // 浮层自己不滚(overflow-hidden 盖掉 PopoverContent 默认的 overflow-y-auto),滚的是下面
          // 那份列表 —— 否则搜索框会跟着内容一起滚走。
          "p-0 overflow-hidden",
          hasDescriptions ? SEARCHABLE_CONTENT_WIDTH_WITH_DESCRIPTIONS : SEARCHABLE_CONTENT_WIDTH,
          contentClassName,
        )}
        align="start"
      >
        {/* shouldFilter={false}:过滤和排序在上面 filterGroups 里做,cmdk 不再给每一项打分、挪 DOM(见 RENDER_BATCH)。 */}
        <Command shouldFilter={false}>
          <CommandInput
            value={search}
            onValueChange={setSearch}
            placeholder={searchPlaceholder ?? t("searchableSelectPlaceholder")}
            className="h-9"
          />
          {/* 列表限高 = min(300px, 可用高度 − 搜索框)。只写 300px 的话,矮窗口里浮层整块比可用
              空间高,被推出窗口外、连搜索框一起看不见(真机:节点的素材下拉)。 */}
          <CommandList
            onScroll={more}
            className="max-h-[min(300px,calc(var(--radix-popover-content-available-height,100vh)-2.75rem))]"
          >
            <CommandEmpty>{emptyText ?? t("searchableSelectNoMatch")}</CommandEmpty>
            {shown.map(([heading, groupItems]) => {
              const rows = groupItems.map((item, index) => (
                <React.Fragment key={item.value}>
                {item.section && item.section.key !== groupItems[index - 1]?.section?.key && (
                  // 小组的标题(工作流名 + 连接名):不能选,只说下面这几行是哪张工作流的
                  <div role="presentation" data-section-head={item.section.key}
                       className="grid gap-px px-2 pb-0.5 pt-1.5 text-ui-xs leading-[1.35] text-muted-foreground">
                    <Truncate className="font-medium text-foreground">{item.section.label}</Truncate>
                    {item.section.subtitle && <Truncate>{item.section.subtitle}</Truncate>}
                  </div>
                )}
                <CommandItem
                  key={item.value}
                  // **cmdk 拿 value 认「哪一行」**(高亮、键盘上下、选中都按它),所以它必须是这一项唯一的
                  // 值 —— 此前拿显示的文字当 value,几个都叫「未命名场景」的场景就被当成同一行:一起高亮,
                  // 点哪个都可能选到另一个。能搜到的文字见 keywordsOf(过滤在 filterGroups 里做)。
                  value={item.value}
                  onSelect={() => {
                    onValueChange(item.value);
                    setOpen(false);
                  }}
                  className={cn((item.indent || item.section) && "pl-6", query && item.section && item.hit && "font-semibold")}
                  data-indent={item.indent || item.section ? "" : undefined}
                  data-section={item.section?.key}
                  data-hit={query && item.section && item.hit ? "" : undefined}
                >
                  {/* 勾在右端、只在选中时渲染:左侧占位勾会让**每一行**都白缩进一个图标宽,
                      而「添加节点」这类当动作菜单用的场景根本没有选中项,那块缩进纯属浪费。 */}
                  {item.icon && (
                    <span aria-hidden className="grid size-4 shrink-0 place-items-center self-start pt-px text-muted-foreground [&_svg]:size-3.5">
                      {item.icon}
                    </span>
                  )}
                  {item.media && (
                    <span aria-hidden className="grid size-9 shrink-0 overflow-hidden rounded-md [&>*]:size-full">
                      {item.media}
                    </span>
                  )}
                  {/* 名字是动态的长值(模型名、文件名):单行截断、悬停看全文。说明是静态的一句话:折行。 */}
                  <span className="grid min-w-0 flex-1 gap-px leading-[1.35]" style={item.style}>
                    <Truncate>{item.label}</Truncate>
                    {item.description && (
                      <span className="break-words text-ui-xs text-muted-foreground">{item.description}</span>
                    )}
                  </span>
                  {item.value === value && <Check size={14} className="shrink-0 text-primary" />}
                </CommandItem>
                </React.Fragment>
              ));
              return heading ? (
                <CommandGroup key={heading} heading={heading}>
                  {rows}
                </CommandGroup>
              ) : (
                <React.Fragment key="__ungrouped">{rows}</React.Fragment>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

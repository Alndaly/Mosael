import React from "react";
import { Grid2x2, Grid3x3, List, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { DETAIL_HEAD, DETAIL_SCROLL, DetailBackButton } from "@/components/app/DetailHead";
import { ModalShell } from "@/components/app/modals";
import { IconButton } from "@/components/ui/icon-button";
import { OptionPicker } from "@/components/ui/option-picker";
import { Truncate } from "@/components/ui/truncate";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { cn } from "@/lib/utils";

/**
 * 「逛一台机器上的一大堆文件」的弹窗骨架 —— 模型库在用,工作流库照它排。
 *
 * 和插件市场那种目录弹窗(CatalogDialog)不是一回事:那边几十条、每条要读一段说明;这边几百个文件,按目录分,
 * 要的是**快速缩小范围、一屏多看几张**。所以版式是文件浏览器的样子:
 *
 * 1. **左边一列目录**:名字 + 数量,按数量排,空的不列,自己滚。最上面是「全部」;不属于哪个目录的「要处理的事」
 *    (工作流缺的模型、下载记录)是钉在这一列底部的特殊项,也带数量 —— 不再叠在网格上面把第一屏挤掉。
 *    这一列是一组竖排页签:上下方向键切换,Tab 进右边的工具条和网格。窄窗口放不下两栏时收成工具条最前面的一个下拉。
 * 2. **右边上面一条工具条**(调用方给:搜索、筛选、排序、显示方式、主操作),下面一行是生效的筛选(一个个能去掉),
 *    再下面是自己滚的内容区。加载中、读不出来、空着这几种状态由调用方放进内容区,内容区是纵向的弹性盒,
 *    状态用 `m-auto` 就在剩下的整块里上下左右居中,弹窗多高都一样。
 * 3. **点开一条是一页详情**({@link LibraryDetail}):顶上一条固定头(返回、名字、常用操作),下面左右两栏各自滚。
 *    返回键和 Esc 都退回列表,并且回到刚才那一条:滚动位置和键盘焦点都还原。
 */

/** 弹窗尺寸:宽到右边排得下五六列小卡,高度固定 —— 列表和详情来回切时弹窗不跳。 */
const LIBRARY_DIALOG =
  "w-[min(1180px,calc(100vw-32px))] max-w-none h-[min(860px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)]";

/** 放不下「左边目录 + 右边网格」两栏的窗口宽度:目录收成工具条里的下拉。 */
export const LIBRARY_NARROW_QUERY = "(max-width: 760px)";
/** 详情页放不下左右两栏的宽度:改成上下排、整页一起滚。 */
export const LIBRARY_DETAIL_STACK_QUERY = "(max-width: 860px)";

export type LibraryNavItem = {
  value: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
  /** 要处理的事(缺的模型):数量标成提醒色。 */
  tone?: "warning";
};

export type LibraryNav = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** 「全部」和各个目录(调用方已经排好、去掉了空的)。 */
  items: LibraryNavItem[];
  /** 钉在这一列底部的特殊项(工作流缺的模型、下载记录)。 */
  pinned?: LibraryNavItem[];
};

const navName = (item: LibraryNavItem) => `${item.label}${item.count !== undefined ? ` ${item.count}` : ""}`;

/**
 * 工具条按钮上的字在多窄时收起(见 LibraryToolbarLabel)。看的是**工具条自己**有多宽(容器查询),不是窗口:左边那一列
 * 目录占掉的宽度窗口看不出来,窄窗口下它还会收成工具条里的一个下拉。
 *
 * 两道线按英文界面(字最长)量:弹窗开到最宽(1180)时工具条 914,中英文、什么都不收都放得下;窄一些先收 `first`,
 * 再窄收 `last`,到应用的最小窗口(980)还是一行。再窄就换行 —— 工具条本来就会折行,不会叠在一起。
 */
const TOOLBAR_COLLAPSE = {
  first: { label: "@max-[890px]/library-toolbar:hidden", icon: "hidden @max-[890px]/library-toolbar:inline-flex" },
  last: { label: "@max-[800px]/library-toolbar:hidden", icon: "hidden @max-[800px]/library-toolbar:inline-flex" },
} as const;

/**
 * 工具条按钮上的那几个字:工具条一行放不下时**按优先级收起**,按钮只剩图标。名字不丢 —— 按钮是 IconButton,
 * 读屏念 aria-label、悬停说明第一行也是它。`first` 先收(次要的:筛选),`last` 最后收(主操作:下载、导入)。
 *
 * 按钮本来就带图标的(「⬇ 下载模型」),图标写在外面,这里只收字;本来只有字的(「底模 ▾」),`icon` 是收起后
 * 顶上的那个 —— 字在的时候它是多余的。
 */
export function LibraryToolbarLabel({ collapse, icon, children }: { collapse: keyof typeof TOOLBAR_COLLAPSE; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <>
      {icon && <span data-toolbar-icon={collapse} className={TOOLBAR_COLLAPSE[collapse].icon}>{icon}</span>}
      <span data-toolbar-label={collapse} className={cn("min-w-0", TOOLBAR_COLLAPSE[collapse].label)}>
        {children}
      </span>
    </>
  );
}

export function LibraryDialog({
  open,
  onOpenChange,
  title,
  nav,
  toolbar,
  chips,
  detailKey,
  detail,
  onOpenItem,
  onBack,
  children,
  dialogs,
  dropzone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 左边那一列。读不出来、还在读的时候不给:那时没有目录可列,状态占满工具条下面的整块。 */
  nav?: LibraryNav;
  /** 右边顶上那一条。窄窗口下目录的下拉排在它最前面。 */
  toolbar: React.ReactNode;
  /** 工具条下面那一行(生效的筛选)。没有就不占地方。 */
  chips?: React.ReactNode;
  /** 正在看的那一条;null = 在列表上。 */
  detailKey: string | null;
  /** 详情页(一个 {@link LibraryDetail})。 */
  detail: React.ReactNode;
  onOpenItem: (key: string) => void;
  onBack: () => void;
  /** 内容区。`openItem(key)` 打开那一条的详情 —— 卡片的打开按钮带 `data-library-open`,外层带 `data-library-item={key}`。 */
  children: (openItem: (key: string) => void) => React.ReactNode;
  /** 挂在弹窗里的二级弹窗(下载框)。 */
  dialogs?: React.ReactNode;
  /** 往整个库上拖文件(工作流库:拖进来就导入)。见 ModalShell 的同名参数。 */
  dropzone?: React.ComponentProps<typeof ModalShell>["dropzone"];
}) {
  const narrow = useMediaMatch(LIBRARY_NARROW_QUERY);
  const scrollerRef = React.useRef<HTMLDivElement>(null);
  //: 离开列表时它滚到哪儿、从哪一条点进去的 —— 回来时原样还原。
  const listScroll = React.useRef(0);
  const cameFrom = React.useRef<string | null>(null);
  const panelId = React.useId();
  const tabPrefix = React.useId();

  const openItem = (key: string) => {
    listScroll.current = scrollerRef.current?.scrollTop ?? 0;
    cameFrom.current = key;
    onOpenItem(key);
  };

  //: 回到列表:还原滚动,焦点回到刚才那一条。**用 layout effect**:换页和还原滚动要在同一帧,不然先闪一下顶部。
  React.useLayoutEffect(() => {
    if (detailKey) return;
    const scroller = scrollerRef.current;
    const key = cameFrom.current;
    cameFrom.current = null;
    if (!key) return;
    if (scroller) scroller.scrollTop = listScroll.current;
    const item = Array.from(scroller?.querySelectorAll<HTMLElement>("[data-library-item]") ?? []).find(
      (one) => one.dataset.libraryItem === key,
    );
    item?.querySelector<HTMLElement>("[data-library-open]")?.focus({ preventScroll: true });
  }, [detailKey]);

  const allItems = nav ? [...nav.items, ...(nav.pinned ?? [])] : [];
  const tabId = (value: string) => `${tabPrefix}-${allItems.findIndex((one) => one.value === value)}`;
  const showColumn = Boolean(nav) && !narrow;
  const navPicker =
    nav && narrow ? (
      <OptionPicker
        className="w-[180px] max-w-full"
        ariaLabel={nav.label}
        value={nav.value}
        onChange={nav.onChange}
        options={allItems.map((item) => ({ value: item.value, label: navName(item) }))}
      />
    ) : null;

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className={LIBRARY_DIALOG}
      bodyClassName="flex flex-col overflow-hidden p-0 [scrollbar-gutter:auto]"
      dropzone={dropzone}
      onEscapeKeyDown={(event) => {
        if (!detailKey) return;
        event.preventDefault();
        onBack();
      }}
    >
      {detailKey ? (
        detail
      ) : (
        <div className={cn("grid min-h-0 flex-1", showColumn ? "grid-cols-[216px_minmax(0,1fr)]" : "grid-cols-[minmax(0,1fr)]")}>
          {showColumn && nav && <NavColumn nav={nav} tabId={tabId} panelId={panelId} />}
          <div
            id={panelId}
            role={showColumn ? "tabpanel" : undefined}
            aria-labelledby={showColumn && nav ? tabId(nav.value) : undefined}
            className="flex min-h-0 min-w-0 flex-col"
          >
            {/* 工具条是一个容器:按钮上的字收不收看它自己有多宽(见 LibraryToolbarLabel)。 */}
            <div data-library-toolbar="" className="@container/library-toolbar flex shrink-0 flex-wrap items-center gap-2 px-6 pb-3 pt-1">
              {navPicker}
              {toolbar}
            </div>
            {chips && <div className="shrink-0 px-6 pb-3">{chips}</div>}
            <div
              ref={scrollerRef}
              data-library-content=""
              className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-6 pb-6 pt-1"
            >
              {children(openItem)}
            </div>
          </div>
        </div>
      )}
      {dialogs}
    </ModalShell>
  );
}

function NavColumn({ nav, tabId, panelId }: { nav: LibraryNav; tabId: (value: string) => string; panelId: string }) {
  const listRef = React.useRef<HTMLDivElement>(null);
  const all = [...nav.items, ...(nav.pinned ?? [])];
  const move = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const at = all.findIndex((one) => one.value === nav.value);
    const next =
      event.key === "ArrowDown" ? Math.min(all.length - 1, at + 1)
      : event.key === "ArrowUp" ? Math.max(0, at - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? all.length - 1
      : null;
    if (next === null || next === at) return;
    event.preventDefault();
    nav.onChange(all[next].value);
    window.requestAnimationFrame(() => {
      listRef.current?.querySelector<HTMLElement>(`#${CSS.escape(tabId(all[next].value))}`)?.focus();
    });
  };
  const tab = (item: LibraryNavItem) => {
    const selected = item.value === nav.value;
    return (
      <button
        key={item.value}
        id={tabId(item.value)}
        type="button"
        role="tab"
        aria-selected={selected}
        aria-controls={panelId}
        aria-label={navName(item)}
        tabIndex={selected ? 0 : -1}
        onClick={() => nav.onChange(item.value)}
        className={cn(
          "flex h-8 min-w-0 shrink-0 cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-ui-sm text-muted-foreground transition-colors",
          "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "[&_svg]:size-3.5 [&_svg]:shrink-0",
          selected && "bg-accent font-medium text-primary hover:bg-accent hover:text-primary",
        )}
      >
        {item.icon}
        <Truncate className="flex-1">{item.label}</Truncate>
        {item.count !== undefined && (
          <span className={cn("shrink-0 text-ui-xs tabular-nums", item.tone === "warning" ? "font-semibold text-warning" : "text-muted-foreground")}>
            {item.count}
          </span>
        )}
      </button>
    );
  };
  return (
    <div
      ref={listRef}
      role="tablist"
      aria-orientation="vertical"
      aria-label={nav.label}
      onKeyDown={move}
      className="flex min-h-0 flex-col border-r border-divider"
    >
      <div role="none" className="grid min-h-0 flex-1 content-start gap-0.5 overflow-y-auto overscroll-contain px-3 pb-3 pt-1">
        {nav.items.map(tab)}
      </div>
      {(nav.pinned ?? []).length > 0 && (
        <div role="none" className="grid shrink-0 gap-0.5 border-t border-divider px-3 py-3">
          {(nav.pinned ?? []).map(tab)}
        </div>
      )}
    </div>
  );
}

export type LibraryChip = { key: string; label: string; removeLabel: string; onRemove: () => void };

/**
 * 生效的筛选:一条一个,点一下去掉;末尾「清除全部」。前面一句说现在剩几个 —— 筛完还剩多少,不用往下数。
 */
export function LibraryFilterChips({
  label,
  summary,
  chips,
  onClearAll,
}: {
  label: string;
  summary: string;
  chips: LibraryChip[];
  onClearAll: () => void;
}) {
  const t = useI18n();
  if (chips.length === 0) return null;
  return (
    <div role="group" aria-label={label} className="flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="mr-1 text-ui-xs tabular-nums text-muted-foreground">{summary}</span>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          aria-label={chip.removeLabel}
          onClick={chip.onRemove}
          className="inline-flex h-6 min-w-0 max-w-[240px] cursor-pointer items-center gap-1 rounded-sm bg-accent pl-2 pr-1 text-ui-xs text-primary hover:bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Truncate>{chip.label}</Truncate>
          <X size={12} className="shrink-0" />
        </button>
      ))}
      <button
        type="button"
        onClick={onClearAll}
        className="inline-flex h-6 cursor-pointer items-center rounded-sm px-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("libraryClearAll")}
      </button>
    </div>
  );
}

/**
 * 一条的详情页。**顶上一条固定头**:返回、名字(一行截断)、一行事实(目录 · 大小 · 标签)、右边常用操作 —— 往下滚多长,
 * 名字和操作都在。下面**左右两栏各自滚**:左边是看的(预览),右边是读的(概要、谁在用、元数据);元数据可能很长
 * (合并模型带的大段 JSON),整页一起滚的话一滚到那儿,右边的信息和左边的预览就都滚走了。窄窗口放不下两栏时上下排、
 * 整体一起滚。进来时焦点给返回键(读屏从这一页的开头读起)。
 */
export function LibraryDetail({
  backLabel,
  onBack,
  title,
  meta,
  actions,
  media,
  children,
}: {
  backLabel: string;
  onBack: () => void;
  title: string;
  /** 名字下面那一行事实(目录 · 大小 · 底模标签)。 */
  meta?: React.ReactNode;
  /** 右边的常用操作。 */
  actions?: React.ReactNode;
  /** 左栏:预览。 */
  media: React.ReactNode;
  /** 右栏:一节一节的 {@link LibrarySection}。 */
  children: React.ReactNode;
}) {
  const stacked = useMediaMatch(LIBRARY_DETAIL_STACK_QUERY);
  const backRef = React.useRef<HTMLButtonElement>(null);
  React.useLayoutEffect(() => {
    backRef.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header data-library-detail-head="" className={cn(DETAIL_HEAD, "flex flex-wrap items-center gap-x-3 gap-y-2")}>
        <DetailBackButton ref={backRef} label={backLabel} onClick={onBack} />
        <div className="grid min-w-0 flex-1 basis-[240px] gap-1">
          <h3 className="m-0 min-w-0 text-ui-lg font-semibold leading-snug tracking-tight text-foreground">
            <Truncate>{title}</Truncate>
          </h3>
          {meta && <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {stacked ? (
        <div data-library-detail-scroll="both" className={DETAIL_SCROLL}>
          <div className="grid min-w-0 gap-7">
            {media}
            {children}
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <section
            data-library-detail-pane="media"
            className="min-h-0 min-w-0 overflow-y-auto overscroll-contain border-r border-divider p-6"
          >
            {media}
          </section>
          <div data-library-detail-pane="info" className="grid min-h-0 min-w-0 content-start gap-7 overflow-y-auto overscroll-contain p-6">
            {children}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 详情右栏里的一节:小标题(带数量)+ 内容。标题能拿焦点(`tabIndex=-1`):头上的「在哪些工作流里用到」跳过来时,
 * 读屏从这一节的标题读起。
 */
export const LibrarySection = React.forwardRef<
  HTMLElement,
  { title: string; count?: number; action?: React.ReactNode; children: React.ReactNode }
>(({ title, count, action, children }, ref) => {
  return (
    // 读屏念这一节叫什么:只念标题,不连着后面的数量
    <section ref={ref} aria-label={title} className="grid min-w-0 content-start gap-3">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <h4 tabIndex={-1} className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground outline-none">
          {title}
          {count !== undefined && <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{count}</span>}
        </h4>
        {action}
      </div>
      {children}
    </section>
  );
});
LibrarySection.displayName = "LibrarySection";

/** 显示方式:大卡片(看预览)、小卡片(一屏多看几张)、列表(扫名字、大小、时间)。 */
export const LIBRARY_DENSITIES = ["large", "small", "list"] as const;
export type LibraryDensity = (typeof LIBRARY_DENSITIES)[number];

/** 三档显示方式:一组单选的图标按钮。选了哪一档由调用方记(各个库各记各的,见 usePersistentTab)。 */
export function LibraryDensitySwitch({ value, onChange }: { value: LibraryDensity; onChange: (value: LibraryDensity) => void }) {
  const t = useI18n();
  const options: { value: LibraryDensity; label: string; icon: React.ReactNode }[] = [
    { value: "large", label: t("libraryDensityLarge"), icon: <Grid2x2 /> },
    { value: "small", label: t("libraryDensitySmall"), icon: <Grid3x3 /> },
    { value: "list", label: t("libraryDensityList"), icon: <List /> },
  ];
  return (
    <div role="radiogroup" aria-label={t("libraryDensity")} className="flex h-10 shrink-0 items-center gap-0.5 rounded-md border border-border p-1">
      {options.map((one) => (
        <IconButton
          key={one.value}
          role="radio"
          aria-checked={value === one.value}
          label={one.label}
          className={cn("text-muted-foreground", value === one.value && "bg-accent text-primary hover:bg-accent hover:text-primary")}
          onClick={() => onChange(one.value)}
        >
          {one.icon}
        </IconButton>
      ))}
    </div>
  );
}

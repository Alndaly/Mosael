import React from "react";

import { CatalogBack, useCatalogBack } from "@/components/app/catalogBack";
import { DETAIL_HEAD, DETAIL_SCROLL, DetailBackButton } from "@/components/app/DetailHead";
import { ModalShell } from "@/components/app/modals";
import { CollectionTabs } from "@/components/layout/StudioPage";
import { SearchInput } from "@/components/ui/search-input";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 「逛一份目录、点开一条看清楚、再决定要不要」的弹窗 —— 插件市场和工作流社区共用这一个。
 *
 * 两边此前各长各的:市场是一列挤着的长条(说明整段铺开、权限码一排排),社区是左边一条窄列表
 * + 右边一块详情(详情大半空着,主操作在底栏,和选中的那一条隔着整个弹窗)。它们做的是同一件事,
 * 所以版式只有一份:
 *
 * 1. **卡片网格**。一张卡只回答「这是什么、我有没有、要不要」:图标、名字、一行来历、三行摘要、
 *    状态、主操作。列数跟着弹窗宽度走(auto-fill),不写断点。
 * 2. **点开是一页详情**,不是侧栏。侧栏要和网格分宽度,两边都窄;详情页拿到整个弹窗宽,
 *    宽时自己分成「正文 + 侧栏信息」两栏(容器查询,不看视口)。和模型库的详情(LibraryDetail)同一个骨架:
 *    **顶上一条固定头** —— 返回键在最前面、和名字、操作同一行(见 DetailHead),下面正文自己滚。
 *    返回键和 Esc 都退回网格,并且**回到刚才那张卡**:滚动位置和键盘焦点都还原,不从头翻。
 *
 * 状态(加载 / 出错 / 空)由调用方给 —— 两份目录各有各的说法。
 */

/** 弹窗的尺寸:宽到能排三四列卡,高度固定 —— 网格和详情来回切时弹窗不跳。 */
const CATALOG_DIALOG =
  "w-[min(1120px,calc(100vw-32px))] max-w-none h-[min(820px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)]";

export type CatalogFilter<F extends string> = { value: F; label: string; count?: number };

export function CatalogDialog<T, F extends string = string>({
  open,
  onOpenChange,
  title,
  description,
  searchLabel,
  query,
  onQueryChange,
  headerActions,
  filters,
  refine,
  notice,
  items,
  itemKey,
  renderCard,
  placeholder,
  detail,
  onDetailChange,
  renderDetail,
  backLabel,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 标题下面一句说明:这份目录是什么、从这里拿走的是什么。 */
  description?: string;
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  /** 搜索框右边的按钮(插件市场的「从链接安装」)。 */
  headerActions?: React.ReactNode;
  filters?: { label: string; value: F; onChange: (value: F) => void; items: CatalogFilter<F>[] };
  /** 筛选行右端的第二个维度(插件市场:按「它能替 Mosael 做什么」筛)。一组页签装不下两个维度。 */
  refine?: React.ReactNode;
  /** 网格上方的一条提示(插件市场:远端索引拉不到,下面只列出内置的)。详情页上不显示。 */
  notice?: React.ReactNode;
  /** 已经按搜索和筛选过滤好的条目。 */
  items: T[];
  itemKey: (item: T) => string;
  /** 一张卡。`open` 打开它的详情 —— 交给 CatalogCard 的 onOpen。 */
  renderCard: (item: T, open: () => void) => React.ReactNode;
  /** 没有卡可排时占住正文的那一块(加载、出错、空、搜不到)。有卡时不显示。 */
  placeholder?: React.ReactNode;
  /** 正在看的那一条;null = 在网格上。 */
  detail: T | null;
  onDetailChange: (id: string | null) => void;
  renderDetail: (item: T) => React.ReactNode;
  backLabel: string;
  /** 挂在弹窗里的二级弹窗(安装确认、卸载确认)。 */
  children?: React.ReactNode;
}) {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);
  //: 离开网格时它滚到哪儿、从哪张卡点进去的 —— 回来时原样还原。
  const gridScroll = React.useRef(0);
  const cameFrom = React.useRef<string | null>(null);
  const detailId = detail ? itemKey(detail) : null;

  const scroller = () => rootRef.current?.closest<HTMLElement>("[data-slot='modal-body']") ?? null;

  const openDetail = (id: string) => {
    gridScroll.current = scroller()?.scrollTop ?? 0;
    cameFrom.current = id;
    onDetailChange(id);
  };
  const back = () => onDetailChange(null);

  //: 切页之后:进详情 → 焦点给返回键(读屏从这一页的开头读起;详情自己的正文从顶上开始滚);回网格 → 还原滚动,
  //: 焦点回到刚才那张卡。**用 layout effect**:换页和还原滚动要在同一帧,不然先闪一下顶部。
  React.useLayoutEffect(() => {
    const body = scroller();
    if (detailId) {
      backRef.current?.focus({ preventScroll: true });
      return;
    }
    if (body) body.scrollTop = gridScroll.current;
    const id = cameFrom.current;
    if (!id) return;
    const card = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-catalog-card]") ?? []).find(
      (one) => one.dataset.catalogCard === id,
    );
    card?.querySelector<HTMLElement>("[data-catalog-open]")?.focus({ preventScroll: true });
    // 只在换页时跑:详情里的内容变了(装好了、状态刷新了)不该把焦点拽回返回键。
  }, [detailId]);

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className={CATALOG_DIALOG}
      //: 详情页:正文不在弹窗这一层滚 —— 固定头不动,只有头下面那一块滚(见 CatalogDetail)。
      bodyClassName={detail ? "flex flex-col overflow-hidden p-0 [scrollbar-gutter:auto]" : undefined}
      onEscapeKeyDown={(event) => {
        if (!detailId) return;
        event.preventDefault();
        back();
      }}
      header={
        // 详情页上没有这一条:搜索和筛选作用于网格,在那一页上它们什么都不做;返回键在详情自己的固定头里。
        detail ? undefined : (
          <div className="grid min-w-0 gap-3">
            {description && <p className="m-0 text-ui-sm font-normal leading-relaxed text-muted-foreground">{description}</p>}
            <div className="flex min-w-0 items-center gap-2">
              <SearchInput className="min-w-0 flex-1"
                  placeholder={searchLabel}
                  aria-label={searchLabel}
                  value={query}
                  onChange={(event) => onQueryChange(event.target.value)} />
              {headerActions}
            </div>
            {(filters || refine) && (
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                {filters && (
                  <CollectionTabs label={filters.label} value={filters.value} onChange={filters.onChange} items={filters.items} />
                )}
                {refine}
              </div>
            )}
          </div>
        )
      }
    >
      <div ref={rootRef} className={detail ? "flex min-h-0 min-w-0 flex-1 flex-col" : "min-h-full min-w-0"}>
        {!detail && notice && <div className="mb-3">{notice}</div>}
        {detail ? (
          <CatalogBack.Provider value={<DetailBackButton ref={backRef} label={backLabel} onClick={back} />}>
            {renderDetail(detail)}
          </CatalogBack.Provider>
        ) : items.length > 0 ? (
          <ul
            role="list"
            aria-label={title}
            className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,264px),1fr))] gap-3 p-0 pb-1"
          >
            {items.map((item) => (
              <li key={itemKey(item)} className="grid min-w-0">
                {renderCard(item, () => openDetail(itemKey(item)))}
              </li>
            ))}
          </ul>
        ) : (
          <div className="grid min-h-[320px] place-items-center">{placeholder}</div>
        )}
      </div>
      {children}
    </ModalShell>
  );
}

/** 状态标记的几种语气。颜色只是第二信号 —— 每一种都带字。 */
export type CatalogTone = "success" | "warning" | "primary" | "muted";

const TONE: Record<CatalogTone, string> = {
  success: "bg-[color-mix(in_srgb,var(--success)_14%,transparent)] text-success",
  warning: "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-warning",
  primary: "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
  muted: "bg-secondary text-muted-foreground",
};

export function CatalogBadge({
  tone,
  icon,
  children,
}: {
  tone: CatalogTone;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-ui-2xs font-semibold [&_svg]:size-3 [&_svg]:shrink-0",
        TONE[tone],
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** 卡片和详情页左上角那块图标底。 */
export function CatalogIcon({ children, size = "md" }: { children: React.ReactNode; size?: "md" | "lg" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] font-semibold text-primary",
        size === "lg" ? "size-14 rounded-xl text-ui-lg [&_svg]:size-6" : "size-10 rounded-lg text-ui-md [&_svg]:size-[18px]",
      )}
    >
      {children}
    </span>
  );
}

/**
 * 一张卡。**整张可点**(打开详情),而主操作是卡上另一颗独立的按钮。
 *
 * 按钮里不能再套按钮,所以「整张可点」是名字那颗按钮用一层 `after:` 盖满整张卡;主操作按钮
 * 抬到这层之上(`relative z-10`)。键盘上是两站:先到名字(回车看详情),再到主操作。
 */
export function CatalogCard({
  id,
  icon,
  title,
  meta,
  badge,
  summary,
  facts,
  action,
  onOpen,
}: {
  id: string;
  icon: React.ReactNode;
  title: string;
  /** 名字下面那一行小字:版本、作者、来源。 */
  meta?: React.ReactNode;
  /** 右上角的状态(已安装 / 有新版 / 已添加)。 */
  badge?: React.ReactNode;
  /** 纯文本摘要,截成三行 —— markdown 由调用方先摊平(`toPlainText`,见 components/markdown/inlineSyntax)。 */
  summary: string;
  /** 左下角一两条事实(几项权限、几个步骤、缺几样)。 */
  facts?: React.ReactNode;
  /** 右下角的主操作。 */
  action?: React.ReactNode;
  onOpen: () => void;
}) {
  return (
    <article
      data-catalog-card={id}
      className={cn(
        "relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr_auto] gap-3 rounded-xl border border-border bg-panel p-4 transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-catalog-open]:focus-visible]:border-primary has-[[data-catalog-open]:focus-visible]:ring-2 has-[[data-catalog-open]:focus-visible]:ring-ring",
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <CatalogIcon>{icon}</CatalogIcon>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <h3 className="m-0 min-w-0 text-ui-sm font-semibold leading-snug text-foreground">
            <button
              type="button"
              data-catalog-open
              className="block max-w-full cursor-pointer text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
              onClick={onOpen}
            >
              <Truncate>{title}</Truncate>
            </button>
          </h3>
          {meta && <Truncate as="p" className="m-0 text-ui-xs text-muted-foreground">{meta}</Truncate>}
        </div>
        {badge}
      </div>
      <Truncate as="p" lines={3} className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{summary}</Truncate>
      <div className="flex min-h-8 min-w-0 items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-3 text-ui-xs text-muted-foreground [&_svg]:size-3.5 [&_svg]:shrink-0">
          {facts}
        </span>
        {action && <span className="relative z-10 flex shrink-0 items-center gap-2">{action}</span>}
      </div>
    </article>
  );
}

/** 卡片左下角的一条事实:图标 + 一句短话。 */
export function CatalogFact({ icon, children, tone }: { icon: React.ReactNode; children: React.ReactNode; tone?: "warning" | "success" }) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1", tone === "warning" && "text-warning", tone === "success" && "text-success")}>
      {icon}
      <Truncate>{children}</Truncate>
    </span>
  );
}

/**
 * 详情页。**顶上一条固定头**:返回键、这一条的身份、**它的主操作**(操作贴着它作用的那个东西,不放到底栏),
 * 往下翻多长都在;下面是正文,自己滚。宽的时候正文右边另起一栏放「信息」类的东西(版本、作者、权限、前置条件)。
 */
export function CatalogDetail({
  icon,
  title,
  badges,
  meta,
  actions,
  aside,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  badges?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <CatalogDetailFrame
      head={
        <header data-catalog-detail-head="" className={cn(DETAIL_HEAD, "flex min-w-0 flex-wrap items-start gap-x-3 gap-y-3")}>
          <CatalogBackSlot />
          <CatalogIcon size="lg">{icon}</CatalogIcon>
          <div className="grid min-w-0 flex-1 basis-[240px] gap-1">
            {badges && <div className="flex min-w-0 flex-wrap items-center gap-1.5">{badges}</div>}
            <h3 className="m-0 min-w-0 break-words text-ui-lg font-semibold leading-snug tracking-tight text-foreground">{title}</h3>
            {meta && <p className="m-0 min-w-0 text-ui-xs text-muted-foreground">{meta}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      }
    >
      <div className="@container/catalog-detail min-w-0">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 @3xl/catalog-detail:grid-cols-[minmax(0,1fr)_280px]">
          <div className="grid min-w-0 content-start gap-7">{children}</div>
          {aside && (
            <aside className="grid min-w-0 content-start gap-6 border-t border-divider pt-6 @3xl/catalog-detail:border-l @3xl/catalog-detail:border-t-0 @3xl/catalog-detail:pl-6 @3xl/catalog-detail:pt-0">
              {aside}
            </aside>
          )}
        </div>
      </div>
    </CatalogDetailFrame>
  );
}

/**
 * 详情页的骨架:固定头 + 下面自己滚的正文。头由调用方画(CatalogDetail 的,或插件市场的 PluginHero),
 * 返回键用 {@link CatalogBackSlot} 摆在头的最前面。
 */
export function CatalogDetailFrame({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <article className="flex min-h-0 min-w-0 flex-1 flex-col">
      {head}
      <div data-catalog-detail-scroll="" className={DETAIL_SCROLL}>
        {children}
      </div>
    </article>
  );
}

/**
 * 返回键在固定头里的那一格:和图标块的中线对齐(大图标 56px、按钮 40px,往下 8px)。不在目录弹窗里渲染时什么都不画。
 */
export function CatalogBackSlot() {
  const back = useCatalogBack();
  return back ? <span className="mt-2 flex shrink-0">{back}</span> : null;
}

/** 详情页里的一节:小标题 + 内容。`action` 摆在标题行右端(「展开」「全部 8 个」这类只作用于这一节的开关)。 */
export function CatalogSection({
  title,
  count,
  action,
  children,
}: {
  title: string;
  count?: number;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    // 读屏念这一节叫什么:只念标题,不连着后面的数量
    <section aria-label={title} className="grid min-w-0 gap-3">
      <div className="flex min-h-6 min-w-0 items-center justify-between gap-2">
        <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          {title}
          {count !== undefined && <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{count}</span>}
        </h4>
        {action}
      </div>
      {children}
    </section>
  );
}

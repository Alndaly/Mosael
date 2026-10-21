"use client";

/**
 * 社区列表:搜索 + 筛选 + 卡片网格。
 *
 * 数据在构建期读好、整份交进来(几十条的量级),筛选全在浏览器里做 —— 打字即出结果,
 * 不用为了一次过滤跑一趟服务器。卡片整张可点,进详情页。
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, LayoutGrid, Package, Plug, Search, Shield, SquareTerminal, Workflow, Wrench, X, ArrowUpRight } from "lucide-react";
import * as React from "react";

import {
  fetchListedShares,
  listedShares,
  mergeListing,
  type ListedShareListKind,
} from "@/components/community/listed-shares";
import { ShareCard } from "@/components/community/shares";
import { PluginTile, WorkflowTile } from "@/components/community/tile";
import { Input } from "@/components/ui/input";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cloudShares, type CloudShare } from "@/lib/cloud";
import { toPlainText } from "@/lib/inline-markdown";
import { queryKeys } from "@/lib/queryKeys";
import type { PluginEntry, WorkflowEntry } from "@/lib/registry";
import { cn } from "@/lib/utils";

/** 搜的是看得见的字:简介里的 `**` 和反引号不该让「公网直链」搜不到、也不该让「**」搜得到。 */
function matches(query: string, fields: readonly string[]): boolean {
  const q = query.trim().toLowerCase();
  return !q || fields.some((field) => toPlainText(field).toLowerCase().includes(q));
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (next: string) => void; placeholder: string }) {
  return (
    // 窄屏独占一行:和筛选按钮挤在一行时会被压成一个图标宽。
    <div className="relative block min-w-0 basis-full sm:max-w-md sm:flex-1 sm:basis-0">
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <Input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="pl-10"
      />
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "border-foreground bg-foreground text-background"
          : "border-border bg-card text-muted-foreground hover:border-foreground/30 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Empty({ locale, onClear }: { locale: Locale; onClear: () => void }) {
  const t = getMessages(locale).community;
  return (
    <div className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-20 text-center">
      <Search className="size-6 text-muted-foreground" aria-hidden />
      <p className="m-0 font-semibold">{t.empty}</p>
      <p className="m-0 text-sm text-muted-foreground">{t.emptyHint}</p>
      <button type="button" onClick={onClear} className="mt-1 text-sm font-semibold text-primary hover:underline">
        {t.clear}
      </button>
    </div>
  );
}

/**
 * 署名那一行:作者 + 官方标记 + 版本。卡片和详情页头用同一个。
 *
 * `builtIn`:随应用内置的插件(ComfyUI)另标一句 —— 它不用装,访客该一眼看出来,而不是照着
 * 安装步骤去市场里找一颗不存在的「安装」按钮。
 */
export function Byline({
  locale,
  author,
  version,
  official,
  builtIn = false,
}: {
  locale: Locale;
  author: string;
  version: string;
  official: boolean;
  builtIn?: boolean;
}) {
  const t = getMessages(locale).community;
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      <span className="truncate">{author}</span>
      {official && (
        <span className="inline-flex items-center gap-0.5 font-medium text-primary">
          <BadgeCheck className="size-3.5" aria-hidden />
          {t.official}
        </span>
      )}
      {builtIn && (
        <span className="inline-flex items-center gap-0.5 font-medium text-primary">
          <Package className="size-3.5" aria-hidden />
          {getMessages(locale).plugins.builtIn}
        </span>
      )}
      <span aria-hidden>·</span>
      <span className="font-mono tabular-nums">{version}</span>
    </span>
  );
}

function Meta({ icon: Icon, children }: { icon: typeof Shield; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {children}
    </span>
  );
}

const CARD =
  "group flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-18px_color-mix(in_oklab,var(--primary)_60%,transparent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0";

export function PluginCard({ locale, plugin }: { locale: Locale; plugin: PluginEntry }) {
  const t = getMessages(locale).plugins;
  return (
    <Link href={localePath(locale, `/plugins/${plugin.slug}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <PluginTile seed={plugin.id} name={plugin.name} />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 truncate text-base font-semibold tracking-tight group-hover:text-primary">{plugin.name}</h3>
          <Byline
            locale={locale}
            author={plugin.author.name || "—"}
            version={`v${plugin.version}`}
            official={plugin.official}
            builtIn={plugin.bundled}
          />
        </div>
      </div>
      {/* 卡片整张是链接、简介只截三行:这里用纯文本,格式留给详情页。 */}
      <p className="mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6 text-muted-foreground">{toPlainText(plugin.summary)}</p>
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Meta icon={plugin.kind === "mcp" ? Plug : SquareTerminal}>{plugin.kind === "mcp" ? t.kindMcp : t.kindScript}</Meta>
        <Meta icon={Wrench}>{plugin.tools.length > 0 ? `${plugin.tools.length} ${t.tools}` : t.toolsFromServer}</Meta>
        <Meta icon={Shield}>{plugin.permissions.length > 0 ? `${plugin.permissions.length} ${t.permissions}` : t.noPermissions}</Meta>
      </div>
    </Link>
  );
}

export function WorkflowCard({ locale, workflow }: { locale: Locale; workflow: WorkflowEntry }) {
  const t = getMessages(locale).workflows;
  const shown = workflow.stages.slice(0, 3);
  return (
    <Link href={localePath(locale, `/workflows/${workflow.slug}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <WorkflowTile id={workflow.id} />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 truncate text-base font-semibold tracking-tight group-hover:text-primary">{workflow.name}</h3>
          <Byline locale={locale} author={workflow.author} version={`${t.templateVersion} ${workflow.version}`} official={workflow.author === "Mosael"} />
        </div>
      </div>
      <p className="mt-4 mb-0 line-clamp-3 text-sm leading-6 text-muted-foreground">{toPlainText(workflow.summary)}</p>
      {/* 流程的前几步:工作流是「一串事」,光看简介分不清两条相近的流程。 */}
      <ol className="mt-4 mb-0 grid flex-1 content-start list-none gap-1.5 p-0 text-xs" aria-label={t.stagesTitle}>
        {shown.map((stage, index) => (
          <li key={stage} className="flex min-w-0 items-center gap-2">
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-secondary font-mono text-[0.625rem] tabular-nums text-muted-foreground">
              {index + 1}
            </span>
            <span className="truncate">{toPlainText(stage)}</span>
          </li>
        ))}
        {workflow.stages.length > shown.length && (
          <li className="pl-7 text-muted-foreground">+{workflow.stages.length - shown.length}</li>
        )}
      </ol>
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Meta icon={Workflow}>{`${workflow.stages.length} ${t.steps}`}</Meta>
        <Meta icon={Wrench}>{`${workflow.nodes} ${t.nodes}`}</Meta>
      </div>
    </Link>
  );
}

/**
 * 列表缓存的键。
 *
 * 插件 / 工作流各按 kind + 语言分开(`lib/queryKeys.ts` 只登记了这两种会被混进官方列表的
 * ShareListKind)。`board` 没有官方条目,键挂在 `shareList()` 的分组前缀下:上传 / 删除
 * 画布时按整组失效,语言仍分得开 —— `/boards` 和首页第三组共用这一份缓存。
 */
function listKey(kind: ListedShareListKind, locale: Locale) {
  return kind === "board"
    ? ([...queryKeys.shareList(), "board", locale] as const)
    : queryKeys.shareList(kind, locale);
}

/**
 * 当前语言的用户分享。**在浏览器里取**,不在构建期取:官网的 `/plugins`、`/workflows`、
 * `/boards` 仍然是静态页(构建页数不变),云端挂了也只影响这一小段追加内容。
 *
 * 导出给社区首页(`landing.tsx`)复用 —— 三组的取数必须和这里逐字一致,否则
 * 落地页和各自的市场页会在语言 / 排序上漂开。
 *
 * 取数规则没变(仍是 `fetchListedShares`,失败退化成空数组),只是换成 `useQuery`:
 * - `retry: false` —— 云端挂了时,列表不是关键路径,不要每 3 秒重试到天荒地老;
 * - `staleTime: 5 分钟` —— 在 `/plugins` `/workflows` `/boards` `/community` 之间切页不重拉;
 * - 键按 kind + locale 分开(见 `lib/queryKeys.ts`),删 / 传分享后能按 kind 点名失效。
 */
export function useListedShares(kind: ListedShareListKind, locale: Locale): CloudShare[] {
  const query = useQuery({
    queryKey: listKey(kind, locale),
    // 失败已经被 fetchListedShares 吞成空数组:内容优先,页面上不出现错误块。
    queryFn: () => fetchListedShares((request) => cloudShares.list(request), kind, locale),
    retry: false,
    staleTime: 5 * 60_000,
  });
  return query.data ?? [];
}

/** 分享卡片上能搜到的字:标题 / 摘要 / 作者。 */
function shareFields(share: CloudShare): string[] {
  return [share.title, share.summary ?? "", share.author.display_name ?? "", share.author.handle ?? ""];
}

const GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

export function PluginBrowser({ locale, plugins }: { locale: Locale; plugins: PluginEntry[] }) {
  const t = getMessages(locale);
  const [query, setQuery] = React.useState("");
  const [kind, setKind] = React.useState<"all" | "script" | "mcp">("all");
  const shares = useListedShares("plugin", locale);
  // 先按**全部**官方 slug 去重,再做 kind / 搜索过滤 —— 否则筛到「本地脚本」时,
  // 一条命中了被隐藏的官方条目的官方分享会以分享卡片的样子重新冒出来。
  const officialSlugs = plugins.map((plugin) => plugin.slug);
  const extra = listedShares(shares, officialSlugs);
  const officialShown = plugins.filter(
    (plugin) =>
      (kind === "all" || plugin.kind === kind) &&
      matches(query, [plugin.name, plugin.id, plugin.summary, ...plugin.permissions, ...plugin.tools.map((tool) => tool.name)]),
  );
  // 分享是用户传来的工程文件,没有「本地脚本 / MCP」这层信息;只在「全部」里展示。
  const shareShown = kind === "all" ? extra.filter((share) => matches(query, shareFields(share))) : [];
  const shown = mergeListing(officialShown, shareShown);
  const kinds = [
    { id: "all" as const, label: t.community.all, count: plugins.length + extra.length },
    { id: "script" as const, label: t.plugins.kindScript, count: plugins.filter((p) => p.kind === "script").length },
    { id: "mcp" as const, label: t.plugins.kindMcp, count: plugins.filter((p) => p.kind === "mcp").length },
  ];
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox value={query} onChange={setQuery} placeholder={t.plugins.search} />
        <fieldset className="flex min-w-0 flex-wrap gap-2" aria-label={t.community.type}>
          {kinds.map((option) => (
            <Chip key={option.id} active={kind === option.id} onClick={() => setKind(option.id)}>
              {option.label}
              <span className="font-mono text-[0.6875rem] tabular-nums opacity-70">{option.count}</span>
            </Chip>
          ))}
        </fieldset>
      </div>
      {shown.length > 0 ? (
        <ul className={GRID}>
          {shown.map((entry) => (
            <li
              key={entry.kind === "official" ? `plugin-${entry.official.slug}` : `share-${entry.share.id}`}
              className="grid"
            >
              {entry.kind === "official" ? (
                <PluginCard locale={locale} plugin={entry.official} />
              ) : (
                <ShareCard locale={locale} share={entry.share} />
              )}
            </li>
          ))}
        </ul>
      ) : (
        <Empty locale={locale} onClear={() => { setQuery(""); setKind("all"); }} />
      )}
    </div>
  );
}

export function WorkflowBrowser({ locale, workflows }: { locale: Locale; workflows: WorkflowEntry[] }) {
  const t = getMessages(locale);
  const [query, setQuery] = React.useState("");
  const shares = useListedShares("workflow", locale);
  // 和插件列表同一条规则:先按全部官方 slug 去重,再过滤搜索词。
  const extra = listedShares(shares, workflows.map((workflow) => workflow.slug));
  const officialShown = workflows.filter((workflow) =>
    matches(query, [workflow.name, workflow.summary, ...workflow.stages, ...workflow.requires]),
  );
  const shareShown = extra.filter((share) => matches(query, shareFields(share)));
  const shown = mergeListing(officialShown, shareShown);
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox value={query} onChange={setQuery} placeholder={t.workflows.search} />
        {query && (
          <button type="button" onClick={() => setQuery("")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <X className="size-4" aria-hidden />
            {t.community.clear}
          </button>
        )}
      </div>
      {shown.length > 0 ? (
        <ul className={GRID}>
          {shown.map((entry) => (
            <li
              key={entry.kind === "official" ? `workflow-${entry.official.slug}` : `share-${entry.share.id}`}
              className="grid"
            >
              {entry.kind === "official" ? (
                <WorkflowCard locale={locale} workflow={entry.official} />
              ) : (
                <ShareCard locale={locale} share={entry.share} />
              )}
            </li>
          ))}
        </ul>
      ) : (
        <Empty locale={locale} onClear={() => setQuery("")} />
      )}
    </div>
  );
}

/**
 * 画板列表:只列当前语言的用户画布分享(`kind=board`)。
 *
 * 画布**没有官方静态内容**(`lib/registry` 里只有插件 / 工作流),所以这里没有「官方在前」
 * 的合并,也没有 slug 去重;取数、语言兜底、新→旧排序仍走 `useListedShares` /
 * `listedShares` 那一份,和 `/plugins`、`/workflows` 相同,只是没有官方条目可并。
 * 搜索只在这个已经取回来的列表里过滤,不为一次输入再跑一趟云端。
 */
export function BoardBrowser({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const [query, setQuery] = React.useState("");
  const shares = listedShares(useListedShares("board", locale), []);
  const shown = shares.filter((share) => matches(query, shareFields(share)));
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox value={query} onChange={setQuery} placeholder={t.boards.search} />
        {query && (
          <button type="button" onClick={() => setQuery("")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <X className="size-4" aria-hidden />
            {t.community.clear}
          </button>
        )}
      </div>
      {shown.length > 0 ? (
        <ul className={GRID}>
          {shown.map((share) => (
            <li key={`share-${share.id}`} className="grid">
              <ShareCard locale={locale} share={share} />
            </li>
          ))}
        </ul>
      ) : shares.length === 0 ? (
        <BoardsEmpty locale={locale} />
      ) : (
        <Empty locale={locale} onClear={() => setQuery("")} />
      )}
    </div>
  );
}

/**
 * 一整页一条画布都没有时的空态:一句人话 + 唯一的下一步(去上传)。
 *
 * 和「搜索筛空」不是一回事:那种该给的是「清除筛选」,这里给的是上传入口。样式沿用
 * `Empty` 的虚线框,不另起一套。
 */
function BoardsEmpty({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  return (
    <div className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-20 text-center">
      <LayoutGrid className="size-6 text-muted-foreground" aria-hidden />
      <p className="m-0 font-semibold">{t.boards.empty}</p>
      {/* 入口在页头右上(和 /workflows 同一个位置)——这里不再给第二颗按钮。 */}
      <p className="m-0 text-sm text-muted-foreground">{t.boards.emptyHint}</p>
    </div>
  );
}

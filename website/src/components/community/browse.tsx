"use client";

/**
 * 社区列表:搜索 + 筛选 + 卡片网格。
 *
 * 数据在构建期读好、整份交进来(几十条的量级),筛选全在浏览器里做 —— 打字即出结果,
 * 不用为了一次过滤跑一趟服务器。卡片整张可点,进详情页。
 */
import Link from "next/link";
import { BadgeCheck, Plug, Search, Shield, SquareTerminal, Workflow, Wrench, X } from "lucide-react";
import * as React from "react";

import { PluginTile, WorkflowTile } from "@/components/community/tile";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import type { PluginEntry, WorkflowEntry } from "@/lib/registry";
import { cn } from "@/lib/utils";

function matches(query: string, fields: readonly string[]): boolean {
  const q = query.trim().toLowerCase();
  return !q || fields.some((field) => field.toLowerCase().includes(q));
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (next: string) => void; placeholder: string }) {
  return (
    // 窄屏独占一行:和筛选按钮挤在一行时会被压成一个图标宽。
    <label className="relative block min-w-0 basis-full sm:max-w-md sm:flex-1 sm:basis-0">
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="h-11 w-full rounded-xl border border-input bg-card pr-4 pl-10 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20"
      />
    </label>
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

/** 署名那一行:作者 + 官方标记 + 版本。卡片和详情页头用同一个。 */
export function Byline({ locale, author, version, official }: { locale: Locale; author: string; version: string; official: boolean }) {
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
          <Byline locale={locale} author={plugin.author.name || "—"} version={`v${plugin.version}`} official={plugin.official} />
        </div>
      </div>
      <p className="mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6 text-muted-foreground">{plugin.summary}</p>
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
      <p className="mt-4 mb-0 line-clamp-3 text-sm leading-6 text-muted-foreground">{workflow.summary}</p>
      {/* 流程的前几步:工作流是「一串事」,光看简介分不清两条相近的流程。 */}
      <ol className="mt-4 mb-0 grid flex-1 content-start list-none gap-1.5 p-0 text-xs" aria-label={t.stagesTitle}>
        {shown.map((stage, index) => (
          <li key={stage} className="flex min-w-0 items-center gap-2">
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-secondary font-mono text-[0.625rem] tabular-nums text-muted-foreground">
              {index + 1}
            </span>
            <span className="truncate">{stage}</span>
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

const GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

export function PluginBrowser({ locale, plugins }: { locale: Locale; plugins: PluginEntry[] }) {
  const t = getMessages(locale);
  const [query, setQuery] = React.useState("");
  const [kind, setKind] = React.useState<"all" | "script" | "mcp">("all");
  const shown = plugins.filter(
    (plugin) =>
      (kind === "all" || plugin.kind === kind) &&
      matches(query, [plugin.name, plugin.id, plugin.summary, ...plugin.permissions, ...plugin.tools.map((tool) => tool.name)]),
  );
  const kinds = [
    { id: "all" as const, label: t.community.all, count: plugins.length },
    { id: "script" as const, label: t.plugins.kindScript, count: plugins.filter((p) => p.kind === "script").length },
    { id: "mcp" as const, label: t.plugins.kindMcp, count: plugins.filter((p) => p.kind === "mcp").length },
  ];
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox value={query} onChange={setQuery} placeholder={t.plugins.search} />
        <div className="flex flex-wrap gap-2" role="group" aria-label={t.community.type}>
          {kinds.map((option) => (
            <Chip key={option.id} active={kind === option.id} onClick={() => setKind(option.id)}>
              {option.label}
              <span className="font-mono text-[0.6875rem] tabular-nums opacity-70">{option.count}</span>
            </Chip>
          ))}
        </div>
      </div>
      {shown.length > 0 ? (
        <ul className={GRID}>
          {shown.map((plugin) => (
            <li key={plugin.id} className="grid">
              <PluginCard locale={locale} plugin={plugin} />
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
  const shown = workflows.filter((workflow) =>
    matches(query, [workflow.name, workflow.summary, ...workflow.stages, ...workflow.requires]),
  );
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
          {shown.map((workflow) => (
            <li key={workflow.id} className="grid">
              <WorkflowCard locale={locale} workflow={workflow} />
            </li>
          ))}
        </ul>
      ) : (
        <Empty locale={locale} onClear={() => setQuery("")} />
      )}
    </div>
  );
}

import React from "react";
import { AlertTriangle, BookOpen, Check, CircleArrowUp, ExternalLink, FolderOpen, Globe, MoreHorizontal, Package, ShieldCheck, ShieldQuestion, SquareTerminal } from "lucide-react";

import type { PluginInstallPreview, PluginMarketEntry, PluginPackage } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ActionMenu, type MenuAction } from "@/components/app/ActionMenu";
import { CatalogBadge, CatalogIcon, CatalogSection } from "@/components/app/CatalogDialog";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { capabilityUseIcon } from "@/components/settings/CapabilityUseList";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { capabilityIcon } from "@/features/plugins/capabilityIcons";
import { useCapabilityTerms } from "@/features/plugins/capabilityTerms";
import { ToolEffectBadge } from "@/features/plugins/ToolEffectBadge";
import { cn } from "@/lib/utils";

/**
 * 一个插件**自己是什么** —— 插件市场的详情、插件页上装好的那一个、安装确认,三处讲的是同一件事,所以只有这一份:
 *
 * - **页头**(PluginHero):图标、名字、一枚状态(内置 / 已安装 / 可更新 / 未安装)、一句话简介、版本和作者,
 *   右边是这一处能做的事(安装、更新、管理、新建连接、文档、更多)。此前名字、版本、作者、文档挤在一行小字里,
 *   读不出哪个能点;内置插件的说明是一整块提示框,现在是状态旁边的一条事实,悬停看全句。
 * - **概览**(PluginOverview):先是「能做什么」—— 每项能力一个图标、一个名字、装上之后出现在哪;再是折起来的介绍
 *   (长,点「展开」才看全);再是工具(一行一个,说明截两行)。右栏是权限(按联网、文件、程序分组说人话,权限码悬停看)
 *   和几条信息(运行方式、插件 ID、主页)。版本和作者已经在页头,不再说第二遍。
 *
 * 数据有三个来源(市场条目、装着的包、安装预览),形状各不相同 —— 先收成一个 {@link PluginProfile},下面只认它。
 */

export type PluginTool = { name: string; label?: string | null; description?: string | null; effects?: string | null };

export type PluginProfile = {
  id: string;
  name: string;
  version: string;
  /** 一句话简介(清单的 `summary`)。老索引、第三方插件可能没有。 */
  summary: string;
  /** 完整介绍(第一条技能的说明,行内 markdown)。 */
  description: string;
  author: string;
  authorUrl: string;
  docs: string;
  homepage: string;
  /** `process`(本机脚本)或 `mcp`(工具由服务报,装上才知道)。 */
  runtime: string;
  permissions: string[];
  provides: string[];
  tools: PluginTool[];
};

export function profileOfMarket(entry: PluginMarketEntry): PluginProfile {
  return {
    id: entry.id,
    name: entry.name || entry.id,
    version: entry.version,
    summary: entry.summary ?? "",
    description: entry.description ?? "",
    author: entry.author ?? "",
    authorUrl: entry.author_url ?? "",
    docs: entry.docs ?? "",
    homepage: entry.homepage ?? "",
    runtime: entry.runtime ?? "process",
    permissions: entry.permissions ?? [],
    provides: entry.provides ?? [],
    tools: entry.tools ?? [],
  };
}

/** 装着的包。`docs` 由调用方给:装着的那一版清单里没写(写 docs 之前发的)时,用市场索引里同一个插件的那一页。 */
export function profileOfPackage(pkg: PluginPackage, docs: string): PluginProfile {
  return {
    id: pkg.id,
    name: pkg.name || pkg.id,
    version: pkg.version,
    summary: pkg.summary ?? "",
    description: pkg.description ?? "",
    author: pkg.author_name ?? "",
    authorUrl: pkg.author_url ?? "",
    docs,
    homepage: pkg.homepage ?? "",
    runtime: pkg.kind ?? "process",
    permissions: pkg.permissions ?? [],
    provides: pkg.provides ?? [],
    tools: pkg.tools ?? [],
  };
}

/** 安装预览:包里那份清单。工具只有名字(装之前只看「它会带来什么」)。 */
export function profileOfPreview(preview: PluginInstallPreview): PluginProfile {
  return {
    id: preview.id,
    name: preview.name || preview.id,
    version: preview.version,
    summary: preview.summary ?? "",
    description: preview.description ?? "",
    author: preview.author_name ?? "",
    authorUrl: preview.author_url ?? "",
    docs: preview.docs ?? "",
    homepage: preview.homepage ?? "",
    runtime: "process",
    permissions: preview.permissions ?? [],
    provides: [],
    tools: (preview.tools ?? []).map((name) => ({ name })),
  };
}

/** 「文档」指向哪儿:插件在 Mosael 里怎么用的那一页;没写才退到它的主页。 */
export function docsOf(profile: PluginProfile): string {
  return profile.docs || profile.homepage;
}

/**
 * 这个插件此刻**对这台机器是什么**。装过 ≠ 有新版;内置的另算一态 —— 它跟着应用装、跟着应用更新,
 * 卸不掉。有没有新版由后端说(`update_available`),这里不拿两个版本字符串比。
 */
export type PluginStatus = "bundled" | "installed" | "update" | "available";

export function statusOfMarket(entry: PluginMarketEntry): PluginStatus {
  if (entry.bundled) return "bundled";
  if (!entry.installed) return "available";
  return entry.update_available ? "update" : "installed";
}

const STATUS_LABEL: Record<PluginStatus, MessageKey> = {
  bundled: "pluginMarketBundledBadge",
  installed: "pluginMarketInstalledBadge",
  update: "pluginMarketHasUpdate",
  available: "pluginStatusAvailable",
};

/** 状态用**标记**说,不藏在版本号那行小字里。颜色只是第二信号,每一种都带字。 */
export function PluginStatusBadge({ status }: { status: PluginStatus }) {
  const t = useI18n();
  const label = t(STATUS_LABEL[status]);
  if (status === "bundled") return <CatalogBadge tone="primary" icon={<Package />}>{label}</CatalogBadge>;
  if (status === "update") return <CatalogBadge tone="warning" icon={<CircleArrowUp />}>{label}</CatalogBadge>;
  if (status === "installed") return <CatalogBadge tone="success" icon={<Check />}>{label}</CatalogBadge>;
  return <CatalogBadge tone="muted">{label}</CatalogBadge>;
}

/** 图标:插件的清单里没有图标,用名字的第一个字 —— 编一个图形不如不编。 */
export function PluginMark({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  return <CatalogIcon size={size}>{(Array.from(name.trim())[0] ?? "?").toUpperCase()}</CatalogIcon>;
}

/** 外链:主色 + 一枚小箭头,一眼看得出能点、点了去别处。 */
export function ExternalAnchor({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className={cn("inline-flex min-w-0 items-center gap-1 text-primary underline-offset-2 hover:underline", className)}
    >
      {children}
      <ExternalLink size={11} aria-hidden className="shrink-0" />
    </a>
  );
}

/** 页头那一行事实:版本 · 作者(能点就是链接)· 调用方补的几条。点不了的就是普通字,能点的才是主色。 */
function FactLine({ facts }: { facts: React.ReactNode[] }) {
  const shown = facts.filter(Boolean);
  return (
    <p data-plugin-facts="" className="m-0 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground">
      {shown.map((fact, index) => (
        <React.Fragment key={index}>
          {index > 0 && <span aria-hidden>·</span>}
          {fact}
        </React.Fragment>
      ))}
    </p>
  );
}

/**
 * 页头。宽的时候三块并排:图标、身份(名字 + 状态、一句话、事实)、操作;窄了操作折到身份下面,左对齐。
 * `compact` 给安装确认用:图标小一号、名字不是标题(弹窗自己有标题)、没有操作。
 */
export function PluginHero({
  profile,
  status,
  facts = [],
  note,
  actions,
  headingLevel = 3,
  compact = false,
  className,
}: {
  profile: PluginProfile;
  status?: PluginStatus;
  /** 版本和作者之后再补的几条(「已装 v0.5.0」「随 Mosael 更新」)。 */
  facts?: React.ReactNode[];
  /** 事实下面一行要人留意的话(「新版本还没发布」)。 */
  note?: React.ReactNode;
  actions?: React.ReactNode;
  headingLevel?: 2 | 3;
  compact?: boolean;
  className?: string;
}) {
  const t = useI18n();
  const Heading = compact ? "p" : headingLevel === 2 ? "h2" : "h3";
  const author = profile.author ? (
    <span key="author" className="inline-flex min-w-0 items-center gap-1">
      {t("pluginAuthor")}
      {profile.authorUrl ? (
        <ExternalAnchor href={profile.authorUrl}>{profile.author}</ExternalAnchor>
      ) : (
        <span className="text-foreground">{profile.author}</span>
      )}
    </span>
  ) : null;
  // 简介:有一句话的摆一句话;没有(老索引、第三方插件)的,安装确认里拿介绍顶上、截三行 —— 那张卡上没有别处摆介绍。
  const summary = profile.summary || (compact ? toPlainText(profile.description) : "");
  return (
    <header data-plugin-hero="" className={cn("flex min-w-0 flex-wrap items-start gap-x-4 gap-y-4", className)}>
      <PluginMark name={profile.name} size={compact ? "md" : "lg"} />
      <div className="grid min-w-0 flex-1 basis-[240px] content-start gap-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
          <Heading
            className={cn(
              "m-0 min-w-0 break-words font-semibold leading-snug tracking-tight text-foreground",
              compact ? "text-ui-md" : "text-ui-lg",
            )}
          >
            {profile.name}
          </Heading>
          {status && <PluginStatusBadge status={status} />}
        </div>
        {summary && (
          <Truncate as="p" lines={3} className="m-0 max-w-[72ch] text-ui-sm leading-relaxed text-muted-foreground">
            {summary}
          </Truncate>
        )}
        <FactLine facts={[<span key="version" className="tabular-nums">v{profile.version}</span>, author, ...facts]} />
        {note}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** 页头里一条带悬停说明的事实(「随 Mosael 更新」—— 全句悬停看)。 */
export function HintedFact({ children, hint }: { children: React.ReactNode; hint: string }) {
  return (
    <Truncate className="inline-block max-w-full cursor-default underline decoration-dotted underline-offset-2" hint={hint}>
      {children}
    </Truncate>
  );
}

/** 页头事实下面那一行要人留意的话。 */
export function HeroNote({ children }: { children: React.ReactNode }) {
  return (
    <p role="note" className="m-0 flex min-w-0 items-start gap-1.5 text-ui-xs leading-relaxed text-warning">
      <AlertTriangle size={13} aria-hidden className="mt-0.5 shrink-0" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** 「文档」:装之前就该能读 —— 「它怎么用、凭据去哪儿申请」只有作者说得清,那正是决定装不装的最后一问。 */
export function DocsButton({ href, variant = "outline", className }: { href: string; variant?: "outline" | "ghost"; className?: string }) {
  const t = useI18n();
  return (
    <Button variant={variant} className={className} asChild>
      <a href={href} target="_blank" rel="noreferrer noopener">
        <BookOpen />
        {t("pluginDocs")}
      </a>
    </Button>
  );
}

/** 页头最右那颗 ⋯:不常用的、破坏性的(卸载)收在这里 —— 不和常用动作贴在一起,手滑的代价不对等。 */
export function MoreActions({ actions }: { actions: MenuAction[] }) {
  const t = useI18n();
  if (actions.length === 0) return null;
  return (
    <ActionMenu
      label={t("pluginMore")}
      actions={actions}
      trigger={
        <IconButton variant="outline" size="icon" label={t("pluginMore")} aria-haspopup="menu">
          <MoreHorizontal />
        </IconButton>
      }
    />
  );
}

/**
 * 概览:左栏能做什么、介绍、工具;右栏权限和信息。宽度看的是**容器**(弹窗、插件页右栏)不是视口 ——
 * 同一份内容在插件页的右栏里和在市场弹窗里各自决定排一栏还是两栏。
 */
export function PluginOverview({ profile }: { profile: PluginProfile }) {
  const t = useI18n();
  const docs = docsOf(profile);
  return (
    <div className="@container/plugin-overview min-w-0">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 @3xl/plugin-overview:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid min-w-0 content-start gap-7">
          {profile.provides.length > 0 && (
            <CatalogSection title={t("pluginSectionCapabilities")}>
              <CapabilityList provides={profile.provides} />
            </CatalogSection>
          )}
          {profile.description && <AboutSection text={profile.description} />}
          <ToolSection tools={profile.tools} runtime={profile.runtime} />
        </div>
        <aside className="grid min-w-0 content-start gap-7 border-t border-divider pt-6 @3xl/plugin-overview:border-l @3xl/plugin-overview:border-t-0 @3xl/plugin-overview:pl-6 @3xl/plugin-overview:pt-0">
          <CatalogSection title={t("pluginMarketPermissions")} count={profile.permissions.length || undefined}>
            <PermissionGroups permissions={profile.permissions} />
          </CatalogSection>
          <CatalogSection title={t("pluginMarketInfo")}>
            <dl className="m-0 grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-4 gap-y-2 text-ui-xs">
              <InfoRow label={t("pluginMarketRuntime")}>
                {profile.runtime === "mcp" ? t("pluginMarketRuntimeMcp") : t("pluginMarketRuntimeProcess")}
              </InfoRow>
              <InfoRow label={t("pluginMarketId")}>
                <span className="timecode break-all">{profile.id}</span>
              </InfoRow>
              {profile.homepage && profile.homepage !== docs && (
                <InfoRow label={t("pluginMarketHomepage")}>
                  <ExternalAnchor href={profile.homepage}>{hostOf(profile.homepage)}</ExternalAnchor>
                </InfoRow>
              )}
            </dl>
          </CatalogSection>
        </aside>
      </div>
    </div>
  );
}

/** 「键:值」的一行,放在两列的 `<dl>` 里:键那一列按最长的键定宽,值不被挤成两行。 */
function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 break-words text-foreground">{children}</dd>
    </>
  );
}

/** 链接只显示域名:整条 URL 在一栏 280px 的侧栏里只会折成三行。解析不了就原样给。 */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * 能做什么:每项一块 —— 图标、名字、装上之后出现在哪(后端从能力表算,ADR 0032 §4)。
 * 「用在哪」是一列安静的小字,不是一排长标签:它是这一项的附注,不是要点的东西。
 */
function CapabilityList({ provides }: { provides: string[] }) {
  const { termOf } = useCapabilityTerms();
  return (
    <ul data-plugin-capabilities="" className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))] gap-2 p-0">
      {provides.map((name) => {
        const term = termOf(name);
        const Icon = capabilityIcon(name);
        const uses = term?.used_by ?? [];
        return (
          <li key={name} data-provides={name} className="flex min-w-0 items-start gap-3 rounded-lg border border-border bg-panel-subtle p-3">
            <span
              aria-hidden
              className="grid size-8 shrink-0 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary"
            >
              <Icon size={16} />
            </span>
            <span className="grid min-w-0 gap-1">
              <strong className="text-ui-sm font-semibold leading-snug text-foreground">{term?.label ?? name}</strong>
              {uses.length > 0 && (
                <ul data-capability-uses="" className="m-0 grid list-none gap-0.5 p-0">
                  {uses.map((use) => {
                    const UseIcon = capabilityUseIcon(use.kind);
                    return (
                      <li
                        key={`${use.kind}:${use.label}`}
                        data-capability-use={use.kind}
                        className="flex min-w-0 items-start gap-1.5 text-ui-xs leading-snug text-muted-foreground"
                      >
                        <UseIcon size={12} aria-hidden className="mt-0.5 shrink-0" />
                        <span className="min-w-0">{use.label}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * 介绍折起来时摆多少:按「宽度」数 —— 中日韩一个字算 2,别的算 1。260 大约是主栏里三行中文、两三行英文。
 * 截在 JS 里而不是用 line-clamp:那样悬停会弹出一整段几百字的说明(Truncate 的规矩),而全文本来就在「展开」后面。
 * 按字数判(不量像素):折不折是确定的,测试和截图看到的是同一个样子。
 */
const ABOUT_FOLD_WIDTH = 260;

function widthOf(char: string): number {
  return /[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]/.test(char) ? 2 : 1;
}

/** 折起来时摆的那一截(纯文字,末尾省略号);放得下就是 null,不折。 */
export function foldedText(plain: string, budget = ABOUT_FOLD_WIDTH): string | null {
  const chars = Array.from(plain.trim());
  let used = 0;
  for (let index = 0; index < chars.length; index += 1) {
    used += widthOf(chars[index]);
    if (used > budget) return `${chars.slice(0, index).join("").trimEnd()}…`;
  }
  return null;
}

/** 介绍:一整段,往往很长 —— 先摆开头一截,「展开」看全文(带格式)。只带行内记号,走行内渲染器。 */
function AboutSection({ text }: { text: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const id = React.useId();
  const folded = foldedText(toPlainText(text));
  return (
    <CatalogSection
      title={t("pluginSectionAbout")}
      action={
        folded ? (
          <Button variant="ghost" size="xs" className="text-muted-foreground" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
            {open ? t("pluginShowLess") : t("pluginShowMore")}
          </Button>
        ) : undefined
      }
    >
      <p id={id} data-plugin-about={folded && !open ? "folded" : "full"} className="m-0 text-ui-sm leading-relaxed text-foreground">
        {folded && !open ? folded : <InlineMarkdown text={text} />}
      </p>
    </CatalogSection>
  );
}

/** 工具多于这么多个时先摆这些,其余「全部 N 个」—— 一屏看得完,不把权限和信息挤到很下面。 */
const TOOLS_SHOWN = 6;

/**
 * 工具:一行一个,名字 + 「需确认」+ 两行说明。工具的机器名(`pan_list`)悬停名字看 —— 那是给智能体和工作流的,
 * 读的人认的是显示名。MCP 插件的工具由服务报,装之前列不出来,说清楚,不留一块空白。
 */
function ToolSection({ tools, runtime }: { tools: PluginTool[]; runtime: string }) {
  const t = useI18n();
  const [all, setAll] = React.useState(false);
  const shown = all ? tools : tools.slice(0, TOOLS_SHOWN);
  return (
    <CatalogSection
      title={t("pluginSectionTools")}
      count={tools.length || undefined}
      action={
        tools.length > TOOLS_SHOWN ? (
          <Button variant="ghost" size="xs" className="text-muted-foreground" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? t("pluginShowLess") : t("pluginToolsAll").replace("{n}", String(tools.length))}
          </Button>
        ) : undefined
      }
    >
      {tools.length > 0 ? (
        <ul data-plugin-tools="" className="m-0 grid list-none overflow-hidden rounded-lg border border-border p-0 [&>*+*]:border-t [&>*+*]:border-divider">
          {shown.map((tool) => (
            <li key={tool.name} data-tool={tool.name} className="grid min-w-0 gap-0.5 px-3 py-2.5">
              <span className="flex min-w-0 items-center gap-2">
                <Truncate className="text-ui-sm font-medium text-foreground" hint={tool.label ? tool.name : undefined}>
                  {tool.label || tool.name}
                </Truncate>
                <ToolEffectBadge effects={tool.effects} />
              </span>
              {tool.description && (
                <Truncate as="p" lines={2} className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
                  <InlineMarkdown text={tool.description} />
                </Truncate>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
          {runtime === "mcp" ? t("pluginMarketMcpToolsBody") : t("pluginMarketNoTools")}
        </p>
      )}
    </CatalogSection>
  );
}

type PermissionKind = "network" | "filesystem" | "process" | "other";
type PermissionGroup = { kind: PermissionKind; items: { code: string; label: string }[] };

const GROUP_ORDER: PermissionKind[] = ["network", "filesystem", "process", "other"];
const GROUP_LABEL: Record<PermissionKind, MessageKey> = {
  network: "pluginPermGroupNetwork",
  filesystem: "pluginPermGroupFiles",
  process: "pluginPermGroupProcess",
  other: "pluginPermGroupOther",
};
const GROUP_ICON = { network: Globe, filesystem: FolderOpen, process: SquareTerminal, other: ShieldQuestion } as const;

/**
 * 权限按**种类**分组,每一条说人话:联网的列出连哪几家(`comfyui`、`huggingface`),文件的说读还是写。
 * 权限码(`network:comfyui`)是和插件作者、和连接上的授权开关对得上的唯一凭据,悬停看 —— 不和人话抢一行。
 * 认不出的(作者自己发明的类别)归「其他」,照原样显示码:**不猜**它是什么意思。
 */
export function groupPermissions(t: (key: MessageKey) => string, permissions: string[]): PermissionGroup[] {
  const groups = new Map<PermissionKind, PermissionGroup>();
  for (const code of permissions) {
    const [prefix, ...rest] = code.split(":");
    const scope = rest.join(":");
    const kind: PermissionKind = prefix === "network" || prefix === "filesystem" || prefix === "process" ? prefix : "other";
    const label =
      kind === "network"
        ? scope === "localhost"
          ? t("pluginPermLocalServices")
          : scope || code
        : kind === "filesystem"
          ? scope === "read"
            ? t("pluginPermReadFiles")
            : scope === "write"
              ? t("pluginPermWriteFiles")
              : code
          : kind === "process"
            ? t("pluginPermStartPrograms")
            : code;
    const group = groups.get(kind) ?? { kind, items: [] };
    group.items.push({ code, label });
    groups.set(kind, group);
  }
  return GROUP_ORDER.flatMap((kind) => (groups.has(kind) ? [groups.get(kind)!] : []));
}

export function PermissionGroups({ permissions }: { permissions: string[] }) {
  const t = useI18n();
  if (permissions.length === 0) {
    return (
      <p className="m-0 flex items-center gap-1.5 text-ui-xs text-muted-foreground">
        <ShieldCheck size={14} className="shrink-0 text-success" aria-hidden />
        {t("pluginInstallNoPerms")}
      </p>
    );
  }
  return (
    <ul data-plugin-permissions="" className="m-0 grid list-none gap-3 p-0">
      {groupPermissions(t, permissions).map((group) => {
        const Icon = GROUP_ICON[group.kind];
        return (
          <li key={group.kind} data-permission-group={group.kind} className="grid min-w-0 grid-cols-[16px_minmax(0,1fr)] items-start gap-x-2 gap-y-1.5">
            <Icon size={14} aria-hidden className="mt-0.5 text-muted-foreground" />
            <span className="text-ui-xs font-medium leading-5 text-foreground">{t(GROUP_LABEL[group.kind])}</span>
            <ul className="col-start-2 m-0 flex min-w-0 list-none flex-wrap gap-1.5 p-0">
              {group.items.map((item) => (
                <li key={item.code} data-permission={item.code} className="min-w-0 max-w-full">
                  <Truncate
                    className="rounded-md bg-secondary px-2 py-0.5 text-ui-xs leading-5 text-foreground"
                    hint={item.label === item.code ? undefined : item.code}
                  >
                    {item.label}
                  </Truncate>
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}

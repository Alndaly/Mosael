import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, Check, Download, ExternalLink, Link2, Package, Search, ShieldAlert, ShieldCheck, Store, Trash2, Wrench } from "lucide-react";
import { toast } from "sonner";

import { installPlugin, listPluginMarket, previewPluginInstall, removePluginPackage } from "@/api/client";
import { useI18n } from "@/app/preferences";
import {
  CatalogBadge,
  CatalogCard,
  CatalogDetail,
  CatalogDialog,
  CatalogFact,
  CatalogSection,
} from "@/components/app/CatalogDialog";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { EmptyState } from "@/components/layout/EmptyState";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { describePermission, describeProvides } from "@/features/plugins/pluginPermissions";
import { isImeKeystroke } from "@/lib/shortcuts";

type MarketEntry = Awaited<ReturnType<typeof listPluginMarket>>["plugins"][number];
type InstallPreview = Awaited<ReturnType<typeof previewPluginInstall>>;
type Filter = "all" | "installed" | "updates";

/**
 * 装的就是市场里这一版。
 *
 * 版本号是字符串,比不出大小 —— 但这里不需要:**不相等就是有新版**。真去解析语义化版本的话,
 * 得处理 `1.0` / `v1.0.0` / `1.0.0-beta` 这些写法,而插件作者写什么全凭自觉;判错一次的
 * 后果是把新版说成旧版,比"多提示一次更新"糟得多。
 */
function upToDate(entry: { installed?: boolean; installed_version?: string; version?: string }): boolean {
  return Boolean(entry.installed && entry.installed_version && entry.installed_version === entry.version);
}

/**
 * 一条市场条目此刻**要人做什么**。装过 ≠ 有新版;内置的另算一态 —— 它跟着应用装、跟着应用
 * 更新,这里什么都不用做(也做不了:没有下载地址,卸了下次启动又会装回来)。
 */
type Stance = "install" | "update" | "current" | "bundled";

function stanceOf(entry: MarketEntry): Stance {
  if (entry.bundled) return "bundled";
  if (upToDate(entry)) return "current";
  return entry.installed ? "update" : "install";
}

/**
 * 搜的是**这个插件是干嘛的**,不只是它叫什么。
 *
 * 只搜名字的话,「网盘」搜不到 TikHub,而「找一个能搬文件的插件」正是打开市场的理由 ——
 * 用户不知道它叫什么,他知道自己要做什么。所以说明、id 和它带来的工具也进搜索范围。
 */
function matches(entry: MarketEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  //: 说明按**字面**搜:`**公网直链**` 里的星号不该挡住「公网直链」这四个字。
  const tools = (entry.tools ?? []).flatMap((tool) => [tool.name, tool.label, toPlainText(tool.description ?? "")]);
  return [entry.name, toPlainText(entry.description ?? ""), entry.id, entry.author, ...tools].some((field) =>
    String(field ?? "").toLowerCase().includes(q),
  );
}

function passes(entry: MarketEntry, filter: Filter): boolean {
  if (filter === "installed") return Boolean(entry.installed);
  if (filter === "updates") return stanceOf(entry) === "update";
  return true;
}

/** 卡片和详情左上角的字标:名字的第一个字。插件没有自己的图标,编一个不如不编。 */
function monogram(entry: MarketEntry): string {
  return (Array.from((entry.name || entry.id).trim())[0] ?? "?").toUpperCase();
}

/**
 * 插件市场。
 *
 * 装插件 = 在这台机器上放一份**会被执行**的代码。所以这里没有一键安装 —— 点「安装」先
 * 把包下下来读一遍清单,把它声明的权限和会带来的工具摊开给人看,确认了才真的落地。
 * 那份清单在包里面,不下下来看不到,所以这一步省不掉。
 *
 * 版式归共用的目录弹窗(components/app/CatalogDialog):卡片网格 → 点开一页详情。这里只管
 * 市场自己的事:三态(装 / 更新 / 已是最新)、权限的说法、装与卸。
 *
 * **「从链接安装」收进一个按钮。** 它是逃生口:装一个来路不明的 zip,是这里风险最高的一件事,
 * 不该和搜索抢那一行的主位。
 */
export function PluginMarketDialog({
  open,
  onOpenChange,
  onChanged,
  focusId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 装上、更新或卸掉了一个包 —— 插件页的列表要跟着刷新。 */
  onChanged: () => void;
  /** 打开时直接看这个插件(官网「在 Mosael 中打开」):翻到它的详情页。 */
  focusId?: string | null;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const [url, setUrl] = React.useState("");
  const [urlOpen, setUrlOpen] = React.useState(false);
  const [pending, setPending] = React.useState<{ url: string; preview: InstallPreview } | null>(null);
  const [removing, setRemoving] = React.useState<MarketEntry | null>(null);

  //: 关掉再打开是一次新的浏览:不停在上次那页详情、也不留着上次的搜索词。
  React.useEffect(() => {
    if (open) return;
    setDetailId(null);
    setQuery("");
    setFilter("all");
  }, [open]);

  const market = useQuery({
    queryKey: ["plugin-market"],
    queryFn: () => listPluginMarket(),
    retry: false,
  });

  const preview = useMutation({
    mutationFn: (target: string) => previewPluginInstall(target),
    onSuccess: (data, target) => {
      setUrlOpen(false);
      setPending({ url: target, preview: data });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const changed = () => {
    void qc.invalidateQueries({ queryKey: ["plugin-market"] });
    onChanged();
  };

  const install = useMutation({
    mutationFn: ({ url: target, overwrite }: { url: string; overwrite: boolean }) => installPlugin(target, overwrite),
    onSuccess: () => {
      setPending(null);
      setUrl("");
      changed();
      toast.success(t("pluginInstallDone"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const uninstall = useMutation({
    mutationFn: (entry: MarketEntry) => removePluginPackage(entry.id),
    onSuccess: () => {
      setRemoving(null);
      changed();
      toast.success(t("pluginMarketUninstalled"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const entries = market.data?.plugins ?? [];
  //: 远端索引拉不到时,接口照样列出随应用内置的插件,并把原因放在 index_error 里。
  const indexError = market.data?.index_error ?? "";
  const searched = entries.filter((entry) => matches(entry, query));
  const shown = searched.filter((entry) => passes(entry, filter));
  const detail = entries.find((entry) => entry.id === detailId) ?? null;

  //: 官网「在 Mosael 中打开」:市场一到货就翻到它的详情;还没装的,再直接弹出**安装确认**
  //: (列出它要的权限),不让人再点一次。装不装仍由那张确认卡上的按钮决定。每个 focusId 只自动
  //: 弹一次 —— 关掉确认卡之后,详情还在,想装再点。
  const autoFocused = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!open || !focusId || autoFocused.current === focusId || pending || preview.isPending) return;
    const target = entries.find((entry) => entry.id === focusId);
    if (!target) return;
    autoFocused.current = focusId;
    setDetailId(target.id);
    if (!target.installed && target.download) preview.mutate(target.download);
  }, [open, focusId, entries, pending, preview]);
  React.useEffect(() => {
    if (!open) autoFocused.current = null;
  }, [open]);

  const busyWith = (entry: MarketEntry) => preview.isPending && preview.variables === entry.download;

  const count = (which: Filter) => searched.filter((entry) => passes(entry, which)).length;
  const placeholder = market.isLoading ? (
    <div className="grid w-full grid-cols-[repeat(auto-fill,minmax(min(100%,264px),1fr))] content-start gap-3 self-start" aria-hidden>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-[184px] rounded-xl" />
      ))}
    </div>
  ) : market.isError || (indexError && entries.length === 0) ? (
    <EmptyState
      size="compact"
      icon={<Store size={15} />}
      title={t("pluginMarketFailed")}
      body={indexError || String((market.error as Error).message)}
    />
  ) : entries.length === 0 ? (
    <EmptyState size="compact" icon={<Store size={15} />} title={t("pluginMarketEmpty")} />
  ) : (
    // 搜不到和市场是空的**是两件事**:一个是"换个词",一个是"这儿本来就没东西"。
    <EmptyState size="compact" icon={<Search size={15} />} title={t("pluginMarketNoMatch")} body={t("pluginMarketNoMatchBody")} />
  );

  return (
    <CatalogDialog<MarketEntry, Filter>
      open={open}
      onOpenChange={onOpenChange}
      title={t("pluginMarket")}
      description={t("pluginMarketSubtitle")}
      searchLabel={t("pluginMarketSearch")}
      query={query}
      onQueryChange={setQuery}
      headerActions={
        <InstallFromUrl
          open={urlOpen}
          onOpenChange={setUrlOpen}
          url={url}
          onUrlChange={setUrl}
          //: **只认自己那一条 URL。** 光看 isPending 的话,市场里任何一张卡片在预览,这个按钮都会跟着转。
          busy={preview.isPending && preview.variables === url.trim()}
          onSubmit={() => url.trim() && preview.mutate(url.trim())}
        />
      }
      filters={
        entries.length > 0
          ? {
              label: t("pluginMarketFilterLabel"),
              value: filter,
              onChange: setFilter,
              items: [
                { value: "all", label: t("catalogFilterAll"), count: searched.length },
                { value: "installed", label: t("pluginMarketFilterInstalled"), count: count("installed") },
                { value: "updates", label: t("pluginMarketFilterUpdates"), count: count("updates") },
              ],
            }
          : undefined
      }
      //: 拉不到索引、但还有内置的可列:说清楚下面为什么只有这几个,别让人以为市场里就这些。
      notice={
        indexError && entries.length > 0 ? (
          <Alert role="status">
            <AlertTriangle size={14} aria-hidden />
            <span className="grid min-w-0">
              <AlertTitle>{t("pluginMarketIndexPartial")}</AlertTitle>
              <AlertDescription className="text-muted-foreground">{indexError}</AlertDescription>
            </span>
          </Alert>
        ) : undefined
      }
      items={market.isSuccess ? shown : []}
      itemKey={(entry) => entry.id}
      placeholder={placeholder}
      renderCard={(entry, openDetail) => (
        <MarketCard entry={entry} busy={busyWith(entry)} onPick={() => preview.mutate(entry.download)} onOpen={openDetail} />
      )}
      detail={detail}
      onDetailChange={setDetailId}
      backLabel={t("pluginMarketBack")}
      renderDetail={(entry) => (
        <MarketDetail
          entry={entry}
          busy={busyWith(entry)}
          onPick={() => preview.mutate(entry.download)}
          onUninstall={() => setRemoving(entry)}
        />
      )}
    >
      {pending && (
        <InstallConfirm
          preview={pending.preview}
          installing={install.isPending}
          onCancel={() => setPending(null)}
          onConfirm={() => install.mutate({ url: pending.url, overwrite: !!pending.preview.installed })}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        title={t("pluginUninstallTitle").replace("{name}", removing?.name || removing?.id || "")}
        body={t("pluginUninstallBody")}
        confirmLabel={t("pluginUninstall")}
        pending={uninstall.isPending}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && uninstall.mutate(removing)}
      />
    </CatalogDialog>
  );
}

/** 逃生口:点开才给输入框。一个是"看看有什么",一个是"我已经知道要装哪个 zip",后者一年用一次。 */
function InstallFromUrl({
  open,
  onOpenChange,
  url,
  onUrlChange,
  busy,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  url: string;
  onUrlChange: (url: string) => void;
  busy: boolean;
  onSubmit: () => void;
}) {
  const t = useI18n();
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="shrink-0" aria-expanded={open}>
          <Link2 size={13} />
          {t("pluginInstallFromUrl")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[320px]">
        <div className="grid gap-1.5">
          <span className="text-ui-xs font-semibold text-foreground">{t("pluginInstallFromUrl")}</span>
          <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("pluginInstallFromUrlHint")}</p>
          <span className="flex min-w-0 items-center gap-1.5">
            <Input
              autoFocus
              className="min-w-0 flex-1"
              placeholder={t("pluginInstallUrlPlaceholder")}
              value={url}
              onChange={(event) => onUrlChange(event.target.value)}
              onKeyDown={(event) => {
                if (isImeKeystroke(event)) return;
                if (event.key === "Enter") onSubmit();
              }}
            />
            <Button className="shrink-0" disabled={!url.trim()} loading={busy} onClick={onSubmit}>
              {t("pluginInstall")}
            </Button>
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** 装 / 更新那颗按钮。已是最新、或是内置的时候**不画**:一个永远按不下去的按钮占着最显眼的位置,什么都不做。 */
function PickButton({ entry, busy, onPick, size }: { entry: MarketEntry; busy: boolean; onPick: () => void; size?: "sm" }) {
  const t = useI18n();
  const stance = stanceOf(entry);
  if (stance === "current" || stance === "bundled") return null;
  return (
    <Button size={size} disabled={!entry.download} loading={busy} onClick={onPick}>
      <Download />
      {stance === "update" ? t("pluginUpdate") : t("pluginInstall")}
    </Button>
  );
}

/** 状态用**标记**说,不藏在版本号那行小字里 ——「已装 v0.3.0」混在里面读不出来"这条我已经有了"。 */
function StanceBadge({ entry }: { entry: MarketEntry }) {
  const t = useI18n();
  const stance = stanceOf(entry);
  if (stance === "bundled") return <CatalogBadge tone="primary" icon={<Package />}>{t("pluginMarketBundledBadge")}</CatalogBadge>;
  if (stance === "update") return <CatalogBadge tone="warning">{t("pluginMarketHasUpdate")}</CatalogBadge>;
  if (stance === "current") return <CatalogBadge tone="success" icon={<Check />}>{t("pluginMarketInstalledBadge")}</CatalogBadge>;
  return null;
}

function MarketCard({
  entry,
  busy,
  onPick,
  onOpen,
}: {
  entry: MarketEntry;
  busy: boolean;
  onPick: () => void;
  onOpen: () => void;
}) {
  const t = useI18n();
  const perms = entry.permissions ?? [];
  const tools = entry.tools ?? [];
  return (
    <CatalogCard
      id={entry.id}
      icon={monogram(entry)}
      title={entry.name || entry.id}
      meta={[`v${entry.version}`, entry.author].filter(Boolean).join(" · ")}
      badge={<StanceBadge entry={entry} />}
      //: 说明是 markdown(`**公网直链**`)—— 卡片只放得下三行,摊平成纯文本,不起渲染器。
      summary={toPlainText(entry.description ?? "")}
      facts={
        <>
          {/* 权限是决定装不装的那条信息,所以卡片上就给个数;「无权限」也要说出来 ——
              空着的话,它和"作者忘了写"长得一模一样。 */}
          <CatalogFact icon={perms.length > 0 ? <ShieldAlert /> : <ShieldCheck />}>
            {perms.length === 0
              ? t("pluginMarketNoPerms")
              : perms.length === 1
                ? t("pluginMarketPermOne")
                : t("pluginMarketPermCount").replace("{n}", String(perms.length))}
          </CatalogFact>
          {tools.length > 0 ? (
            <CatalogFact icon={<Wrench />}>
              {tools.length === 1 ? t("pluginMarketToolOne") : t("pluginMarketToolCount").replace("{n}", String(tools.length))}
            </CatalogFact>
          ) : entry.runtime === "mcp" ? (
            <CatalogFact icon={<Wrench />}>{t("pluginMarketMcpTools")}</CatalogFact>
          ) : null}
        </>
      }
      action={<PickButton entry={entry} busy={busy} onPick={onPick} size="sm" />}
      onOpen={onOpen}
    />
  );
}

/** 详情里「键:值」的一行。放在一个两列的 `<dl>` 里:键那一列按最长的键定宽,值不被挤成两行。 */
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

function ExternalAnchor({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-primary hover:underline">
      {children}
      <ExternalLink size={11} aria-hidden />
    </a>
  );
}

function MarketDetail({
  entry,
  busy,
  onPick,
  onUninstall,
}: {
  entry: MarketEntry;
  busy: boolean;
  onPick: () => void;
  onUninstall: () => void;
}) {
  const t = useI18n();
  const stance = stanceOf(entry);
  const perms = entry.permissions ?? [];
  const tools = entry.tools ?? [];
  const provides = entry.provides ?? [];
  const docs = entry.docs || entry.homepage;

  return (
    <CatalogDetail
      icon={monogram(entry)}
      title={entry.name || entry.id}
      badges={stance === "install" ? undefined : <StanceBadge entry={entry} />}
      meta={
        <>
          v{entry.version}
          {entry.author && ` · ${entry.author}`}
          {stance === "update" && ` · ${t("pluginInstalled").replace("{v}", entry.installed_version)}`}
          {stance === "current" && ` · ${t("pluginUpToDate")}`}
        </>
      }
      actions={
        <>
          {/* **装之前就该能读文档。** "它到底怎么用、凭据去哪儿申请"只有作者说得清 —— 而那正是
              决定装不装的最后一问。优先插件自己的使用文档(docs),没写才退到主页。 */}
          {docs && (
            <Button variant="outline" asChild>
              <a href={docs} target="_blank" rel="noreferrer noopener">
                <BookOpen />
                {t("pluginDocs")}
              </a>
            </Button>
          )}
          {/* 内置的卸不掉(后端也拒):卸了下次启动又会装回来。 */}
          {entry.installed && stance !== "bundled" && (
            <Button variant="outline" onClick={onUninstall}>
              <Trash2 />
              {t("pluginUninstall")}
            </Button>
          )}
          <PickButton entry={entry} busy={busy} onPick={onPick} />
        </>
      }
      aside={
        <>
          <CatalogSection title={t("pluginMarketPermissions")} count={perms.length || undefined}>
            {perms.length === 0 ? (
              <p className="m-0 inline-flex items-center gap-1.5 text-ui-xs text-muted-foreground">
                <ShieldCheck size={13} className="shrink-0 text-success" aria-hidden />
                {t("pluginInstallNoPerms")}
              </p>
            ) : (
              <PermissionList permissions={perms} />
            )}
          </CatalogSection>
          <CatalogSection title={t("pluginMarketInfo")}>
            <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-4 gap-y-2 text-ui-xs">
              <InfoRow label={t("pluginMarketVersion")}>v{entry.version}</InfoRow>
              {entry.installed && entry.installed_version && stance !== "bundled" && (
                <InfoRow label={t("pluginMarketInstalledVersion")}>v{entry.installed_version}</InfoRow>
              )}
              {entry.author && (
                <InfoRow label={t("pluginMarketAuthor")}>
                  {entry.author_url ? <ExternalAnchor href={entry.author_url}>{entry.author}</ExternalAnchor> : entry.author}
                </InfoRow>
              )}
              <InfoRow label={t("pluginMarketRuntime")}>
                {entry.runtime === "mcp" ? t("pluginMarketRuntimeMcp") : t("pluginMarketRuntimeProcess")}
              </InfoRow>
              <InfoRow label={t("pluginMarketId")}>
                <span className="timecode break-all">{entry.id}</span>
              </InfoRow>
              {entry.homepage && entry.homepage !== docs && (
                <InfoRow label={t("pluginMarketHomepage")}>
                  <ExternalAnchor href={entry.homepage}>{hostOf(entry.homepage)}</ExternalAnchor>
                </InfoRow>
              )}
            </dl>
          </CatalogSection>
        </>
      }
    >
      {stance === "bundled" && (
        <Alert role="note">
          <Package size={14} aria-hidden />
          <AlertDescription>{t("pluginMarketBundledNote")}</AlertDescription>
        </Alert>
      )}
      {entry.description && (
        <CatalogSection title={t("pluginMarketAbout")}>
          {/* 说明是一段话,只带行内记号 —— 走行内渲染器,不起块级的 Streamdown。 */}
          <p className="m-0 text-ui-sm leading-relaxed text-foreground">
            <InlineMarkdown text={entry.description} />
          </p>
        </CatalogSection>
      )}
      {provides.length > 0 && (
        <CatalogSection title={t("pluginMarketProvides")}>
          <ul className="m-0 grid list-none gap-1.5 p-0 text-ui-sm text-foreground">
            {provides.map((one) => (
              <li key={one} className="flex items-start gap-2">
                <Check size={14} className="mt-0.5 shrink-0 text-success" aria-hidden />
                <span>{describeProvides(t, one) ?? one}</span>
              </li>
            ))}
          </ul>
        </CatalogSection>
      )}
      <CatalogSection title={t("pluginMarketTools")} count={tools.length || undefined}>
        {tools.length > 0 ? (
          <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))] gap-2 p-0">
            {tools.map((tool) => (
              <li key={tool.name} className="grid min-w-0 content-start gap-1 rounded-lg border border-border bg-panel-subtle px-3 py-2.5">
                <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                  <strong className="text-ui-sm font-semibold text-foreground">{tool.label || tool.name}</strong>
                  {tool.label && <code className="timecode text-ui-2xs text-muted-foreground">{tool.name}</code>}
                </span>
                {tool.description && (
                  <span className="line-clamp-3 text-ui-xs leading-relaxed text-muted-foreground">
                    <InlineMarkdown text={tool.description} />
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
            {entry.runtime === "mcp" ? t("pluginMarketMcpToolsBody") : t("pluginMarketNoTools")}
          </p>
        )}
      </CatalogSection>
    </CatalogDetail>
  );
}

/** 权限:先说人话,码在旁边小字留着 —— 那是和插件作者、和权限设置页对得上的唯一凭据。 */
function PermissionList({ permissions }: { permissions: string[] }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {permissions.map((one) => {
        const said = describePermission(t, one);
        return (
          <li key={one} className="grid grid-cols-[14px_minmax(0,1fr)] gap-2 text-ui-xs">
            <ShieldAlert size={13} className="mt-0.5 text-warning" aria-hidden />
            <span className="grid min-w-0 gap-0.5">
              {said && <span className="text-foreground">{said}</span>}
              <code className={said ? "timecode text-ui-2xs text-muted-foreground" : "timecode text-foreground"}>{one}</code>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** 装之前的最后一眼:它是谁、要什么权限、带来哪些工具。权限先说,而且用醒目的形状说 —— 这是这张卡存在的理由。 */
function InstallConfirm({
  preview,
  installing,
  onCancel,
  onConfirm,
}: {
  preview: InstallPreview;
  installing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  const perms = preview.permissions ?? [];
  const toolNames = preview.tools ?? [];
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onCancel()}
      title={t("pluginInstallConfirmTitle")}
      className="w-[min(480px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>{t("cancel")}</Button>
          <Button loading={installing} onClick={onConfirm}>
            {preview.installed ? t("pluginUpdate") : t("pluginInstall")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 text-ui-sm">
        <div className="flex flex-wrap items-baseline gap-x-1.5">
          <strong className="text-ui-md font-semibold">{preview.name || preview.id}</strong>
          <small className="text-ui-xs text-muted-foreground">v{preview.version}</small>
          {preview.author_name && (
            <small className="text-ui-xs text-muted-foreground">
              · {t("pluginAuthor")}{" "}
              {preview.author_url ? (
                <a href={preview.author_url} target="_blank" rel="noreferrer noopener" className="hover:underline">
                  {preview.author_name}
                </a>
              ) : (
                preview.author_name
              )}
            </small>
          )}
          {(preview.docs || preview.homepage) && (
            <a
              href={preview.docs || preview.homepage}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-ui-xs text-primary hover:underline"
            >
              <BookOpen size={11} />
              {t("pluginDocs")}
            </a>
          )}
        </div>
        {preview.description && (
          <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground"><InlineMarkdown text={preview.description} /></p>
        )}
        <div className="grid gap-2 rounded-lg border border-border bg-panel-subtle p-3">
          <span className="flex items-center gap-1.5 text-ui-xs font-semibold text-foreground">
            <ShieldAlert size={13} />
            {perms.length > 0 ? t("pluginInstallDeclaredPerms") : t("pluginInstallNoPerms")}
          </span>
          {perms.length > 0 && <PermissionList permissions={perms} />}
        </div>
        {toolNames.length > 0 && (
          <div className="grid gap-0.5 text-ui-xs text-muted-foreground">
            <span className="font-semibold text-foreground">{t("pluginInstallTools")}</span>
            <span className="timecode">{toolNames.join(" · ")}</span>
          </div>
        )}
        {preview.installed && (
          <p className="m-0 text-ui-xs leading-[1.55] text-warning">
            {t("pluginInstallOverwrite").replace("{v}", preview.installed_version)}
          </p>
        )}
        <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{t("pluginInstallWarning")}</p>
      </div>
    </ModalShell>
  );
}

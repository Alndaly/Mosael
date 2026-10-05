import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Link2, Settings2, ShieldAlert, ShieldCheck, Search, Store, Trash2, Wrench } from "lucide-react";
import { toast } from "sonner";

import { installPlugin, listPluginMarket, previewPluginInstall, removePluginPackage } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CatalogCard, CatalogDetailFrame, CatalogDialog, CatalogFact } from "@/components/app/CatalogDialog";
import { DETAIL_HEAD } from "@/components/app/DetailHead";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { EmptyState } from "@/components/layout/EmptyState";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { useCapabilityTerms } from "@/features/plugins/capabilityTerms";
import { OptionPicker } from "@/components/ui/option-picker";
import {
  DocsButton,
  HeroNote,
  HintedFact,
  MoreActions,
  PermissionGroups,
  PluginHero,
  PluginOverview,
  PluginStatusBadge,
  docsOf,
  profileOfMarket,
  profileOfPreview,
  statusOfMarket,
  type PluginStatus,
} from "@/features/plugins/PluginProfile";
import { isImeKeystroke } from "@/lib/shortcuts";

type MarketEntry = Awaited<ReturnType<typeof listPluginMarket>>["plugins"][number];
type InstallPreview = Awaited<ReturnType<typeof previewPluginInstall>>;
type Filter = "all" | "installed" | "updates";
/** 从哪个地址装,以及市场给这一条写的版本(从链接装时为空)。后者让后端认得出「许的新版还没发布」。 */
/** `sha256`:索引给这个包写的摘要(发版索引里有),后端下载后照它核对;从链接装时为空。 */
type PickTarget = { url: string; advertised: string; sha256?: string };

/** 从市场里的这一条装:带上它许的版本。 */
function pickOf(entry: MarketEntry): PickTarget {
  return { url: entry.download, advertised: entry.version, sha256: entry.sha256 ?? "" };
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

//: 按能力筛的下拉里「不限」那一项的值(OptionPicker 不收空串当值)。
const ANY_CAPABILITY = "__any__";

function passes(entry: MarketEntry, filter: Filter): boolean {
  if (filter === "installed") return Boolean(entry.installed);
  if (filter === "updates") return statusOfMarket(entry) === "update";
  return true;
}

/**
 * 插件市场。
 *
 * 装插件 = 在这台机器上放一份**会被执行**的代码。所以这里没有一键安装 —— 点「安装」先
 * 把包下下来读一遍清单,把它声明的权限和会带来的工具摊开给人看,确认了才真的落地。
 * 那份清单在包里面,不下下来看不到,所以这一步省不掉。
 *
 * 版式归共用的目录弹窗(components/app/CatalogDialog):卡片网格 → 点开一页详情。详情和安装确认的页头、概览
 * 和插件页上装好的那一个是同一套(PluginProfile)。这里只管市场自己的事:装 / 更新 / 管理、装与卸。
 *
 * **「从链接安装」收进一个按钮。** 它是逃生口:装一个来路不明的 zip,是这里风险最高的一件事,
 * 不该和搜索抢那一行的主位。
 */
export function PluginMarketDialog({
  open,
  onOpenChange,
  onChanged,
  focusId,
  capability: wantedCapability,
  onManage,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 装上、更新或卸掉了一个包 —— 插件页的列表要跟着刷新。 */
  onChanged: () => void;
  /** 打开时直接看这个插件(官网「在 Mosael 中打开」):翻到它的详情页。 */
  focusId?: string | null;
  /** 打开时只看能做这件事的插件(设置「能力提供方」里的「去插件市场找」)。 */
  capability?: string | null;
  /** 装着的插件详情里的「管理」:关掉市场,在插件页打开它(新建连接在那儿)。不给就不画这颗按钮。 */
  onManage?: (pluginId: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  //: 按「它能替 Mosael 做什么」筛(ADR 0032 §5:「谁能做降噪」)。空 = 不限。和上面那组页签是两个维度。
  const [capability, setCapability] = React.useState("");
  const { terms } = useCapabilityTerms();
  React.useEffect(() => {
    if (open) setCapability(wantedCapability ?? "");
  }, [open, wantedCapability]);
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const [url, setUrl] = React.useState("");
  const [urlOpen, setUrlOpen] = React.useState(false);
  const [pending, setPending] = React.useState<(PickTarget & { preview: InstallPreview }) | null>(null);
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

  const refreshMarket = () => void qc.invalidateQueries({ queryKey: ["plugin-market"] });
  const changed = () => {
    refreshMarket();
    onChanged();
  };

  const preview = useMutation({
    mutationFn: (target: PickTarget) => previewPluginInstall(target.url, target.advertised, target.sha256),
    onSuccess: (data, target) => {
      setUrlOpen(false);
      //: 市场许了新版,包里却不比装着的新:不弹那张写着「更新」的确认卡 —— 装下去什么都不会变。
      //: 说清楚为什么,再刷一遍市场:后端已经记下,这一条不再说「有新版」。
      if (data.update_unreleased) {
        toast.info(t("pluginUpdateNotReleased"));
        refreshMarket();
        return;
      }
      setPending({ ...target, preview: data });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const install = useMutation({
    mutationFn: ({ target, overwrite }: { target: PickTarget; overwrite: boolean }) =>
      installPlugin(target.url, overwrite, target.advertised, target.sha256),
    onSuccess: () => {
      setPending(null);
      setUrl("");
      changed();
      toast.success(t("pluginInstallDone"));
    },
    onError: (error: Error) => {
      toast.error(error.message);
      //: 装的那一刻才发现「新版本还没发布」(预览之后索引变了)时,后端也记下了 —— 市场跟着刷新。
      refreshMarket();
    },
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
  const capable = searched.filter((entry) => !capability || (entry.provides ?? []).includes(capability));
  const shown = capable.filter((entry) => passes(entry, filter));
  //: 只列市场里真有插件能做的那几项,各带条数 —— 选一个没有插件的能力只会得到一片空白。
  const offered = terms
    .map((term) => ({ term, count: searched.filter((entry) => (entry.provides ?? []).includes(term.name)).length }))
    .filter(({ term, count }) => count > 0 || term.name === capability);
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
    if (!target.installed && target.download) preview.mutate(pickOf(target));
  }, [open, focusId, entries, pending, preview]);
  React.useEffect(() => {
    if (!open) autoFocused.current = null;
  }, [open]);

  const busyWith = (entry: MarketEntry) => preview.isPending && preview.variables?.url === entry.download;

  const count = (which: Filter) => capable.filter((entry) => passes(entry, which)).length;
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
          busy={preview.isPending && preview.variables?.url === url.trim()}
          onSubmit={() => url.trim() && preview.mutate({ url: url.trim(), advertised: "" })}
        />
      }
      filters={
        entries.length > 0
          ? {
              label: t("pluginMarketFilterLabel"),
              value: filter,
              onChange: setFilter,
              items: [
                { value: "all", label: t("catalogFilterAll"), count: capable.length },
                { value: "installed", label: t("pluginMarketFilterInstalled"), count: count("installed") },
                { value: "updates", label: t("pluginMarketFilterUpdates"), count: count("updates") },
              ],
            }
          : undefined
      }
      refine={
        offered.length > 0 ? (
          <OptionPicker
            size="sm"
            ariaLabel={t("pluginMarketCapability")}
            value={capability || ANY_CAPABILITY}
            onChange={(next) => setCapability(next === ANY_CAPABILITY ? "" : next)}
            options={[
              { value: ANY_CAPABILITY, label: t("pluginMarketCapabilityAny") },
              ...offered.map(({ term, count }) => ({ value: term.name, label: `${term.label} · ${count}` })),
            ]}
            className="w-[240px] max-w-full"
          />
        ) : undefined
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
        <MarketCard entry={entry} busy={busyWith(entry)} onPick={() => preview.mutate(pickOf(entry))} onOpen={openDetail} />
      )}
      detail={detail}
      onDetailChange={setDetailId}
      backLabel={t("pluginMarketBack")}
      renderDetail={(entry) => (
        <MarketDetail
          entry={entry}
          busy={busyWith(entry)}
          onPick={() => preview.mutate(pickOf(entry))}
          onUninstall={() => setRemoving(entry)}
          onManage={onManage ? () => onManage(entry.id) : undefined}
        />
      )}
    >
      {pending && (
        <InstallConfirm
          preview={pending.preview}
          advertised={pending.advertised}
          installing={install.isPending}
          onCancel={() => setPending(null)}
          onConfirm={() => install.mutate({ target: pending, overwrite: !!pending.preview.installed })}
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
  const status = statusOfMarket(entry);
  if (status !== "available" && status !== "update") return null;
  return (
    <Button size={size} disabled={!entry.download} loading={busy} onClick={onPick}>
      <Download />
      {status === "update" ? t("pluginUpdate") : t("pluginInstall")}
    </Button>
  );
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
  const status = statusOfMarket(entry);
  return (
    <CatalogCard
      id={entry.id}
      icon={(Array.from((entry.name || entry.id).trim())[0] ?? "?").toUpperCase()}
      title={entry.name || entry.id}
      meta={[`v${entry.version}`, entry.author].filter(Boolean).join(" · ")}
      //: 卡片上「未安装」不标:那一张卡的「安装」按钮已经在说这件事,每张都挂一枚灰标记只是噪音。
      badge={status === "available" ? undefined : <PluginStatusBadge status={status} />}
      //: 先摆一句话简介;老索引没有就摆介绍 —— 介绍是 markdown(`**公网直链**`),卡片只放得下三行,摊平成纯文本。
      summary={entry.summary || toPlainText(entry.description ?? "")}
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

/**
 * 市场里一个插件的详情(版式见 PluginProfile):页头是它是谁、此刻对这台机器是什么、能做的事 —— 也是这一页的固定头,
 * 返回键在它最前面(和模型库的详情同一个骨架,见 DetailHead);下面是概览,自己滚。
 *
 * 操作按状态给:没装的「安装」,有新版的「更新」;装着的(含内置)「管理」—— 关掉市场、在插件页打开它,
 * 新建连接就在那儿。卸载收进 ⋯。内置插件不给装 / 更新 / 卸载:它跟着应用走(后端也拒),
 * 这件事是页头状态旁边的一条事实「随 Mosael 更新」,全句悬停看。
 */
function MarketDetail({
  entry,
  busy,
  onPick,
  onUninstall,
  onManage,
}: {
  entry: MarketEntry;
  busy: boolean;
  onPick: () => void;
  onUninstall: () => void;
  onManage?: () => void;
}) {
  const t = useI18n();
  const status: PluginStatus = statusOfMarket(entry);
  const profile = profileOfMarket(entry);
  const docs = docsOf(profile);
  const installed = status === "installed" || status === "bundled";
  return (
    <CatalogDetailFrame
      head={
        <PluginHero
          profile={profile}
          status={status}
          className={DETAIL_HEAD}
          facts={[
            status === "update" && entry.installed_version ? (
              <span key="installed" className="tabular-nums">{t("pluginInstalled").replace("{v}", entry.installed_version)}</span>
            ) : null,
            status === "bundled" ? (
              <HintedFact key="bundled" hint={t("pluginBundledHint")}>{t("pluginBundledFact")}</HintedFact>
            ) : null,
          ]}
          //: 市场许了更新的版本,但点过「更新」、下下来的包并不更新:说清楚为什么这里没有「更新」。
          note={entry.update_unreleased && status === "installed" ? <HeroNote>{t("pluginUpdateNotReleased")}</HeroNote> : undefined}
          actions={
            <>
              <PickButton entry={entry} busy={busy} onPick={onPick} />
              {installed && onManage && (
                <Button onClick={onManage}>
                  <Settings2 />
                  {t("pluginManage")}
                </Button>
              )}
              {docs && <DocsButton href={docs} />}
              {/* 内置的卸不掉(后端也拒):卸了下次启动又会装回来。 */}
              {entry.installed && status !== "bundled" && (
                <MoreActions actions={[{ label: t("pluginUninstall"), icon: <Trash2 />, destructive: true, onSelect: onUninstall }]} />
              )}
            </>
          }
        />
      }
    >
      <PluginOverview profile={profile} />
    </CatalogDetailFrame>
  );
}

/**
 * 装之前的最后一眼:它是谁(和详情页同一个页头,小一号)、要什么权限(按种类分组说人话)、会带来哪些工具。
 * 权限用醒目的形状说 —— 这是这张卡存在的理由。「文档」在左下角:决定装不装的最后一问往往是「它怎么用」。
 */
function InstallConfirm({
  preview,
  advertised,
  installing,
  onCancel,
  onConfirm,
}: {
  preview: InstallPreview;
  /** 市场给这一条写的版本(从链接装时为空)。卡上的版本号是**包里实际那一版**,两者不同时点明。 */
  advertised: string;
  installing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  const profile = profileOfPreview(preview);
  const perms = profile.permissions;
  const docs = docsOf(profile);
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onCancel()}
      title={preview.installed ? t("pluginUpdateConfirmTitle") : t("pluginInstallConfirmTitle")}
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <>
          {docs && <DocsButton href={docs} variant="ghost" className="sm:mr-auto" />}
          <Button variant="outline" onClick={onCancel}>{t("cancel")}</Button>
          <Button loading={installing} onClick={onConfirm}>
            {preview.installed ? t("pluginUpdate") : t("pluginInstall")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 text-ui-sm">
        <PluginHero profile={profile} compact />
        {/* 标题和列表之间比条目之间宽一档 —— 否则标题像是列表的第一条。 */}
        <section aria-label={t("pluginMarketPermissions")} className="grid gap-3 rounded-lg border border-border bg-panel-subtle p-3.5">
          {perms.length > 0 ? (
            <>
              <h4 className="m-0 flex items-center gap-1.5 text-ui-xs font-semibold text-foreground">
                <ShieldAlert size={14} className="text-warning" aria-hidden />
                {t("pluginInstallDeclaredPerms")}
              </h4>
              <PermissionGroups permissions={perms} />
            </>
          ) : (
            <PermissionGroups permissions={perms} />
          )}
        </section>
        {profile.tools.length > 0 && (
          <section aria-label={t("pluginInstallTools")} className="grid gap-2 text-ui-xs">
            <h4 className="m-0 flex items-center gap-1.5 font-semibold text-foreground">
              {t("pluginInstallTools")}
              <span className="font-normal tabular-nums text-muted-foreground">{profile.tools.length}</span>
            </h4>
            {/* 一个工具一枚:此前是一串用 · 连起来的等宽字,长了只能硬折行,分不清哪到哪是一个。 */}
            <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
              {profile.tools.map((tool) => (
                <li key={tool.name} className="timecode rounded-md bg-secondary px-2 py-0.5 text-ui-2xs text-muted-foreground">
                  {tool.name}
                </li>
              ))}
            </ul>
          </section>
        )}
        <div className="grid gap-1.5">
          {advertised && preview.version && advertised !== preview.version && (
            <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">
              {t("pluginInstallVersionDiffers").replace("{listed}", advertised).replace("{actual}", preview.version)}
            </p>
          )}
          {preview.installed && (
            <p className="m-0 flex items-start gap-1.5 text-ui-xs leading-[1.55] text-warning">
              <AlertTriangle size={13} aria-hidden className="mt-0.5 shrink-0" />
              {t("pluginInstallOverwrite").replace("{v}", preview.installed_version)}
            </p>
          )}
          <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{t("pluginInstallWarning")}</p>
        </div>
      </div>
    </ModalShell>
  );
}

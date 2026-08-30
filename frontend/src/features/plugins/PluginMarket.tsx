import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, Download, Link2, Search, ShieldAlert, Store } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type MarketEntry = components["schemas"]["PluginMarketEntry"];
type InstallPreview = components["schemas"]["PluginInstallPreview"];

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

/** 一条市场条目此刻**要人做什么**。三态,不是两态:装过 ≠ 有新版。 */
type Stance = "install" | "update" | "current";

function stanceOf(entry: MarketEntry): Stance {
  if (upToDate(entry)) return "current";
  return entry.installed ? "update" : "install";
}

/**
 * 搜的是**这个插件是干嘛的**,不只是它叫什么。
 *
 * 只搜名字的话,「网盘」搜不到 TikHub,而「找一个能搬文件的插件」正是打开市场的理由 ——
 * 用户不知道它叫什么,他知道自己要做什么。所以说明和 id 也进搜索范围。
 */
function matches(entry: MarketEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [entry.name, entry.description, entry.id, entry.author].some((field) =>
    String(field ?? "").toLowerCase().includes(q),
  );
}

/**
 * 插件市场。
 *
 * 装插件 = 在这台机器上放一份**会被执行**的代码。所以这里没有一键安装 —— 点「安装」先
 * 把包下下来读一遍清单,把它声明的权限和会带来的工具摊开给人看,确认了才真的落地。
 * 那份清单在包里面,不下下来看不到,所以这一步省不掉。
 *
 * 版式的两个判断:
 *
 * 1. **搜索占主位。** 市场只有四个条目时随便怎么排都行,而它是要长起来的;等长起来再补搜索,
 *    中间那段时间用户只能一行行翻。
 * 2. **「从链接安装」收进一个按钮。** 它是逃生口:装一个来路不明的 zip,是这里风险最高的
 *    一件事,却曾经占着弹窗最顶上一整行 —— 位置在说"这是主路",而主路是下面那份清单。
 */
export function PluginMarketDialog({
  open,
  onOpenChange,
  onInstalled,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInstalled: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [query, setQuery] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [urlOpen, setUrlOpen] = React.useState(false);
  const [pending, setPending] = React.useState<{ url: string; preview: InstallPreview } | null>(null);

  const market = useQuery({
    queryKey: ["plugin-market"],
    queryFn: () => api<MarketEntry[]>("/api/plugins/market"),
    retry: false,
  });

  const preview = useMutation({
    mutationFn: (target: string) =>
      api<InstallPreview>("/api/plugins/install/preview", { method: "POST", body: JSON.stringify({ url: target }) }),
    onSuccess: (data, target) => {
      setUrlOpen(false);
      setPending({ url: target, preview: data });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const install = useMutation({
    mutationFn: ({ url: target, overwrite }: { url: string; overwrite: boolean }) =>
      api("/api/plugins/install", { method: "POST", body: JSON.stringify({ url: target, overwrite }) }),
    onSuccess: () => {
      setPending(null);
      setUrl("");
      void qc.invalidateQueries({ queryKey: ["plugin-market"] });
      onInstalled();
      toast.success(t("pluginInstallDone"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const entries = market.data ?? [];
  const shown = entries.filter((entry) => matches(entry, query));
  const perms = pending?.preview.permissions ?? [];
  const toolNames = pending?.preview.tools ?? [];

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("pluginMarket")}
      className="w-[680px] max-w-[92vw]"
      // 找东西的那一条**钉在头里**:滚到第十个插件时,搜索框还在原地。
      header={
        <div className="flex min-w-0 items-center gap-1.5">
        <span className="relative min-w-0 flex-1">
          <Search
            size={13}
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            className="h-8 w-full min-w-0 rounded-lg border-border bg-field pl-[30px] pr-2.5 text-foreground [&]:text-ui-sm"
            placeholder={t("pluginMarketSearch")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("pluginMarketSearch")}
          />
        </span>
        {/* 逃生口收进一颗按钮:点开才给输入框。**它不该和搜索抢那一行** —— 一个是"看看有什么",
            一个是"我已经知道要装哪个 zip",后者一年用一次。 */}
        <Popover open={urlOpen} onOpenChange={setUrlOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="shrink-0" aria-expanded={urlOpen}>
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
                  className="h-8 min-w-0 flex-1 rounded-lg border-border bg-field px-2.5 text-foreground [&]:text-ui-sm"
                  placeholder={t("pluginInstallUrlPlaceholder")}
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && url.trim()) preview.mutate(url.trim());
                  }}
                />
                <Button
                  className="shrink-0"
                  size="sm"
                  disabled={!url.trim()}
                  //: **只认自己那一条 URL。** 光看 isPending 的话,市场里任何一张卡片在预览,
                  //: 这个按钮都会跟着转 —— 用户按的是那边,转的是这边。
                  loading={preview.isPending && preview.variables === url.trim()}
                  onClick={() => preview.mutate(url.trim())}
                >
                  {t("pluginInstall")}
                </Button>
              </span>
            </div>
          </PopoverContent>
          </Popover>
        </div>
      }
    >
      {/* 有东西就从顶部排,没东西就把空态放正中 —— content-start 一直挂着的话,
          「没有匹配的插件」会紧贴在搜索框下面,看着像是搜索框的一部分。 */}
      <div
        className={cn(
          "grid min-h-full gap-2",
          shown.length > 0 || market.isLoading ? "content-start" : "content-center justify-items-center",
        )}
      >
        {market.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-[72px] rounded-lg" />)}
        {market.isError && (
          <EmptyState
            size="compact"
            icon={<Store size={15} />}
            title={t("pluginMarketFailed")}
            body={String((market.error as Error).message)}
          />
        )}
        {market.isSuccess && entries.length === 0 && (
          <EmptyState size="compact" icon={<Store size={15} />} title={t("pluginMarketEmpty")} />
        )}
        {/* 搜不到和市场是空的**是两件事**:一个是"换个词",一个是"这儿本来就没东西"。
            合成一句的话,搜错字的人会以为市场坏了。 */}
        {market.isSuccess && entries.length > 0 && shown.length === 0 && (
          <EmptyState
            size="compact"
            icon={<Search size={15} />}
            title={t("pluginMarketNoMatch")}
            body={t("pluginMarketNoMatchBody")}
          />
        )}
        {shown.map((entry) => (
          <MarketRow
            key={entry.id}
            entry={entry}
            busy={preview.isPending && preview.variables === entry.download}
            onPick={() => preview.mutate(entry.download)}
          />
        ))}
      </div>

      {pending && (
        <ModalShell
          open
          onOpenChange={(next) => !next && setPending(null)}
          title={t("pluginInstallConfirmTitle")}
        >
          <div className="grid gap-2 text-ui-sm">
            <div className="flex flex-wrap items-baseline gap-x-1.5">
              <strong className="text-ui-md font-semibold">{pending.preview.name || pending.preview.id}</strong>
              <small className="text-ui-xs text-muted-foreground">v{pending.preview.version}</small>
              {pending.preview.homepage && (
                <a
                  href={pending.preview.homepage}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-0.5 text-ui-xs text-primary hover:underline"
                >
                  <BookOpen size={11} />
                  {t("pluginDocs")}
                </a>
              )}
            </div>
            {pending.preview.description && (
              <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{pending.preview.description}</p>
            )}
            {/* 权限先说,而且用醒目的形状说 —— 它是这个弹窗存在的唯一理由。 */}
            <div className="grid gap-1 rounded-lg border border-border bg-panel-subtle p-2">
              <span className="flex items-center gap-1.5 text-ui-xs font-semibold text-foreground">
                <ShieldAlert size={13} />
                {perms.length > 0 ? t("pluginInstallDeclaredPerms") : t("pluginInstallNoPerms")}
              </span>
              {perms.length > 0 && (
                <ul className="m-0 grid list-none gap-0.5 p-0 text-ui-xs text-muted-foreground">
                  {perms.map((one) => (
                    <li key={one} className="timecode">
                      {one}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {toolNames.length > 0 && (
              <div className="grid gap-0.5 text-ui-xs text-muted-foreground">
                <span className="font-semibold text-foreground">{t("pluginInstallTools")}</span>
                <span className="timecode">{toolNames.join(" · ")}</span>
              </div>
            )}
            {pending.preview.installed && (
              <p className="m-0 text-ui-xs leading-[1.55] text-warning">
                {t("pluginInstallOverwrite").replace("{v}", pending.preview.installed_version)}
              </p>
            )}
            <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{t("pluginInstallWarning")}</p>
            <div className="mt-1 flex items-center justify-end gap-1.5">
              <Button variant="ghost" size="sm" onClick={() => setPending(null)}>
                {t("cancel")}
              </Button>
              <Button
                size="sm"
                loading={install.isPending}
                onClick={() => install.mutate({ url: pending.url, overwrite: !!pending.preview.installed })}
              >
                {pending.preview.installed ? t("pluginUpdate") : t("pluginInstall")}
              </Button>
            </div>
          </div>
        </ModalShell>
      )}
    </ModalShell>
  );
}

/**
 * 市场里的一条。
 *
 * **权限摆在条目上,而不是只在确认弹窗里。** 权限是决定装不装的那条信息,而确认弹窗是
 * 点了「安装」之后才出现的 —— 也就是说,人得先做决定,才能看到做决定要用的东西。
 * 摆在这里,四个条目可以横着比。
 */
function MarketRow({ entry, busy, onPick }: { entry: MarketEntry; busy: boolean; onPick: () => void }) {
  const t = useI18n();
  const stance = stanceOf(entry);
  const perms = entry.permissions ?? [];

  return (
    <article className="grid gap-1.5 rounded-lg border border-border bg-panel-subtle p-2.5">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="flex min-w-0 items-center gap-1.5">
            <strong className="min-w-0 truncate text-ui-sm font-semibold text-foreground">{entry.name || entry.id}</strong>
            {/* 状态用**标记**说,不藏在副标题那行小字里 —— 那一行还挂着版本号和作者,
                「已装 v0.3.0」混在里面读不出来"这条我已经有了"。 */}
            {stance === "update" && (
              <span className="shrink-0 rounded-full bg-[color-mix(in_srgb,#d97706_16%,transparent)] px-1.5 py-px text-ui-2xs font-semibold text-[#b45309]">
                {t("pluginMarketHasUpdate")}
              </span>
            )}
            {stance === "current" && (
              <span className="inline-flex shrink-0 items-center gap-0.5 text-ui-2xs font-semibold text-muted-foreground">
                <Check size={11} />
                {t("pluginUpToDate")}
              </span>
            )}
          </span>
          <small className="flex flex-wrap items-center gap-x-1.5 text-ui-xs text-muted-foreground">
            <span>
              v{entry.version}
              {entry.author && ` · ${entry.author}`}
              {stance === "update" && ` · ${t("pluginInstalled").replace("{v}", entry.installed_version)}`}
            </span>
            {/* **装之前就该能读文档。** 权限和工具这里已经摊开了,但"它到底怎么用、凭据去哪儿
                申请"只有作者说得清 —— 而那正是决定装不装的最后一问。 */}
            {entry.homepage && (
              <a
                href={entry.homepage}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-0.5 text-primary hover:underline"
              >
                <BookOpen size={11} />
                {t("pluginDocs")}
              </a>
            )}
          </small>
        </span>
        {/* 已是最新时**不画按钮**:一个永远按不下去的按钮还占着最显眼的位置,而它什么都不做。
            状态由左边那个标记说,这里留空。 */}
        {stance !== "current" && (
          <Button className="shrink-0" size="sm" disabled={!entry.download} loading={busy} onClick={onPick}>
            <Download size={13} />
            {stance === "update" ? t("pluginUpdate") : t("pluginInstall")}
          </Button>
        )}
      </div>
      {entry.description && <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{entry.description}</p>}
      {/* 无权限也要说出来 —— 「没有声明任何权限」是这四个字里最有说服力的一条,空着的话
          它和"我忘了写"长得一模一样。 */}
      <span className="flex min-w-0 flex-wrap items-center gap-1 text-ui-2xs text-muted-foreground">
        <ShieldAlert size={11} className="shrink-0" aria-hidden />
        {perms.length === 0 ? (
          <span>{t("pluginMarketNoPerms")}</span>
        ) : (
          perms.map((one) => (
            <span key={one} className="timecode rounded bg-muted px-1 py-px text-foreground">
              {one}
            </span>
          ))
        )}
      </span>
    </article>
  );
}

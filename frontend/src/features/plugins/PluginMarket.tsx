import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ShieldAlert, Store } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type MarketEntry = components["schemas"]["PluginMarketEntry"];
type InstallPreview = components["schemas"]["PluginInstallPreview"];

/**
 * 插件市场。
 *
 * 装插件 = 在这台机器上放一份**会被执行**的代码。所以这里没有一键安装 —— 点「安装」先
 * 把包下下来读一遍清单,把它声明的权限和会带来的工具摊开给人看,确认了才真的落地。
 * 那份清单在包里面,不下下来看不到,所以这一步省不掉。
 */
export function PluginMarket({ onInstalled }: { onInstalled: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [url, setUrl] = React.useState("");
  const [pending, setPending] = React.useState<{ url: string; preview: InstallPreview } | null>(null);

  const market = useQuery({
    queryKey: ["plugin-market"],
    queryFn: () => api<MarketEntry[]>("/api/plugins/market"),
    retry: false,
  });

  const preview = useMutation({
    mutationFn: (target: string) =>
      api<InstallPreview>("/api/plugins/install/preview", { method: "POST", body: JSON.stringify({ url: target }) }),
    onSuccess: (data, target) => setPending({ url: target, preview: data }),
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
  const perms = pending?.preview.permissions ?? [];
  const toolNames = pending?.preview.tools ?? [];
  return (
    // 两行:上面是「从链接安装」(高度固定),下面吃掉剩下的空间 —— 空态要在**那块空间**的
    // 正中,而不是紧贴着输入框。此前整块是 content-start,空态被钉在顶部。
    <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2 p-2">
      <label className="grid gap-1.5 text-ui-xs font-semibold text-muted-foreground">
        <span>{t("pluginInstallFromUrl")}</span>
        <span className="flex min-w-0 items-center gap-1.5">
          <Input
            className="h-8 min-w-0 flex-1 rounded-lg border-border bg-field px-2.5 text-ui-sm font-medium text-foreground"
            placeholder={t("pluginInstallUrlPlaceholder")}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && url.trim()) preview.mutate(url.trim());
            }}
          />
          <Button
            className="shrink-0"
            variant="outline"
            size="sm"
            disabled={!url.trim()}
            loading={preview.isPending}
            onClick={() => preview.mutate(url.trim())}
          >
            <Download size={13} />
            {t("pluginInstall")}
          </Button>
        </span>
      </label>

      {/* 有东西就从顶部排,没东西就把空态放正中 —— content-start 一直挂着的话,
          「打不开市场」会紧贴在输入框下面,看着像是输入框的一部分。 */}
      <div
        className={cn(
          "grid min-h-0 gap-2 overflow-y-auto",
          entries.length > 0 || market.isLoading ? "content-start" : "content-center justify-items-center",
        )}
      >
      {market.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
      {market.isError && (
        <EmptyState size="compact" icon={<Store size={15} />} title={t("pluginMarketFailed")} body={String((market.error as Error).message)} />
      )}
      {market.isSuccess && entries.length === 0 && (
        <EmptyState size="compact" icon={<Store size={15} />} title={t("pluginMarketEmpty")} />
      )}
      {entries.map((entry) => (
        <article key={entry.id} className="grid gap-1.5 rounded-lg border border-border bg-panel-subtle p-2.5">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <span className="min-w-0">
              <strong className="block truncate text-ui-sm font-semibold text-foreground">{entry.name || entry.id}</strong>
              <small className="text-ui-xs text-muted-foreground">
                v{entry.version}
                {entry.author && ` · ${entry.author}`}
                {entry.installed && ` · ${t("pluginInstalled").replace("{v}", entry.installed_version)}`}
              </small>
            </span>
            <Button
              className="shrink-0"
              variant="outline"
              size="sm"
              disabled={!entry.download}
              loading={preview.isPending && preview.variables === entry.download}
              onClick={() => preview.mutate(entry.download)}
            >
              <Download size={13} />
              {entry.installed ? t("pluginUpdate") : t("pluginInstall")}
            </Button>
          </div>
          {entry.description && (
            <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">{entry.description}</p>
          )}
        </article>
      ))}
      </div>

      {pending && (
        <ModalShell
          open
          onOpenChange={(next) => !next && setPending(null)}
          title={t("pluginInstallConfirmTitle")}
        >
          <div className="grid gap-2 text-ui-sm">
            <div>
              <strong className="text-ui-md font-semibold">{pending.preview.name || pending.preview.id}</strong>
              <small className="ml-1.5 text-ui-xs text-muted-foreground">v{pending.preview.version}</small>
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
    </div>
  );
}

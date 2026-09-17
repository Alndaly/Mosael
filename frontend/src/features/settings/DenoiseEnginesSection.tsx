import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { type DenoiseEngine, installDenoiseEngine, listDenoiseEngines } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { pollWhileUnsettled } from "@/features/settings/pollWhileUnsettled";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

/**
 * Settings → 降噪引擎(ADR-0017)。
 *
 * 一页看全**所有**降噪方式:哪些随应用带着、哪个要下载、哪个借用别的引擎、哪些会去掉音乐。
 * 只有要下载的那种有按钮 —— 往这台机器上放一个可执行文件是显式的一步,不藏在"点一下降噪"后面。
 *
 * 这一页不认识任何引擎:名字、说明、没准备好时的提示都由后端给。
 */
export function DenoiseEnginesSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const engines = useQuery({
    queryKey: ["denoise-engines"],
    queryFn: listDenoiseEngines,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const install = useMutation({
    mutationFn: (engine: string) => installDenoiseEngine(engine),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["denoise-engines"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <SettingsGroup title={t("denoiseEnginesTitle")} description={t("denoiseEnginesDesc")}>
      <SettingsBlock>
        <div className="grid gap-2">
          {engines.data?.map((engine) => (
            <EngineRow
              key={engine.engine}
              engine={engine}
              busy={(install.isPending && install.variables === engine.engine) || engine.status === "installing"}
              onInstall={() => install.mutate(engine.engine)}
            />
          ))}
          {engines.isLoading && <p className="text-ui-sm text-muted-foreground">{t("connecting")}</p>}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function EngineRow({ engine, busy, onInstall }: { engine: DenoiseEngine; busy: boolean; onInstall: () => void }) {
  const t = useI18n();
  const installed = engine.installable ? engine.status === "installed" : engine.ready;
  return (
    <div
      className={cn(
        "grid gap-2 rounded-lg border border-border bg-background px-3 py-2.5",
        installed && "border-[color-mix(in_oklab,var(--primary)_30%,var(--border))]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid min-w-0 gap-[3px]">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-ui-md">{engine.label}</strong>
            {engine.removes_music && (
              <span className="rounded-sm bg-[color-mix(in_oklab,var(--warning)_16%,transparent)] px-1.5 py-px text-ui-2xs font-medium">
                {t("denoiseRemovesMusicBadge")}
              </span>
            )}
            {engine.installable && engine.size_bytes > 0 && engine.status !== "installed" && (
              <span className="text-ui-xs tabular-nums text-muted-foreground">
                {t("denoiseSizeApprox").replace("{size}", formatBytes(engine.size_bytes))}
              </span>
            )}
          </div>
          <small className="text-ui-xs leading-[1.45] text-muted-foreground">{engine.description}</small>
          {/* 不需要装、但现在用不了的(人声提取没有分离引擎):说清原因和去处。 */}
          {!engine.installable && !engine.ready && engine.setup_hint && (
            <small className="text-ui-xs text-foreground">{engine.setup_hint}</small>
          )}
          {engine.status === "unsupported" && <small className="text-ui-xs text-foreground">{t("denoiseUnsupported")}</small>}
          {/* 失败原因**原样显示**:校验不符、连不上 GitHub,用户能照着那句话去查。 */}
          {engine.status === "failed" && engine.message && (
            <small className="text-ui-xs text-destructive">{engine.message}</small>
          )}
          {engine.status === "installing" && engine.message && (
            <small className="text-ui-xs text-muted-foreground">{engine.message}</small>
          )}
        </div>
        <div className="shrink-0">
          {installed && (
            <span className="inline-flex items-center gap-[5px] text-xs font-medium text-primary">
              <CheckCircle2 size={14} /> {t(engine.installable ? "denoiseInstalled" : "denoiseReadyLabel")}
            </span>
          )}
          {!engine.installable && !engine.ready && (
            <span className="text-xs text-muted-foreground">{t("denoiseUnavailableLabel")}</span>
          )}
          {engine.status === "installing" && (
            <span className="inline-flex items-center gap-[5px] text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-mosael-spin" />
            </span>
          )}
          {engine.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onInstall}>
              <Download size={13} /> {t("denoiseInstall")}
            </Button>
          )}
          {engine.status === "failed" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onInstall}>
              <RotateCw size={13} /> {t("denoiseRetry")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

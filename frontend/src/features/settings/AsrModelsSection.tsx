import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { type AsrModel, downloadAsrModel, listAsrModels } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

function fmtBytes(n: number): string {
  if (n <= 0) return "0 MB";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} GB`;
  return `${Math.round(n / 1_000_000)} MB`;
}

function fmtSpeed(bps: number): string {
  if (bps <= 0) return "";
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} MB/s`;
  return `${Math.round(bps / 1000)} KB/s`;
}

/** Settings → 转写模型:预下载 funasr / whisperx 权重,展示进度、百分比、
    速度与剩余时间。转写首次会自动下载,这里给一个手动、可见的下载渠道。 */
export function AsrModelsSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ["asr-models"],
    queryFn: listAsrModels,
    // Poll fast while any model is downloading, otherwise idle.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((m) => m.status === "downloading") ? 1200 : false,
  });
  const download = useMutation({
    mutationFn: (id: string) => downloadAsrModel(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["asr-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <SettingsGroup title={t("asrModelsTitle")} description={t("asrModelsDesc")}>
      <SettingsBlock>
        <div className="grid gap-2">
          {models.data?.map((model) => (
            <AsrModelCard
              key={model.id}
              model={model}
              busy={download.isPending || models.data?.some((m) => m.status === "downloading")}
              onDownload={() => download.mutate(model.id)}
            />
          ))}
          {models.isLoading && <p className="text-[12.5px] text-muted-foreground">{t("connecting")}</p>}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function AsrModelCard({
  model,
  busy,
  onDownload,
}: {
  model: AsrModel;
  busy?: boolean;
  onDownload: () => void;
}) {
  const t = useI18n();
  const pct = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
  const downloading = model.status === "downloading";

  return (
    <div className={cn("grid gap-2 rounded-lg border border-border bg-background px-3 py-2.5", model.status === "installed" && "border-[color-mix(in_oklab,var(--primary)_30%,var(--border))]")}>
      <div className="flex items-start justify-between gap-3">
        <div className="grid min-w-0 gap-[3px]">
          <div className="flex flex-wrap items-center gap-2 [&_strong]:text-[13px]">
            <strong>{model.label}</strong>
            <span className="rounded-md border border-border px-[5px] text-[10.5px] uppercase leading-4 tracking-[0.03em] text-muted-foreground">{model.engine}</span>
            <span className="text-[11px] tabular-nums text-muted-foreground">{fmtBytes(model.expected_bytes)}</span>
          </div>
          <small className="text-[11.5px] text-muted-foreground">{model.detail}</small>
          {model.status === "installed" && !model.runtime_ready && (
            <small className="text-[11.5px] text-destructive">{t("asrModelNoRuntime")}</small>
          )}
        </div>
        <div className="shrink-0">
          {/* **两件事分开说**:文件在不在盘上(status),和跑不跑得起来(runtime_ready)。
              它们完全可以一真一假 —— 模型缓存是别的工具下的,而这台机器上没有任何解释器装了
              funasr/whisperx。此前这里只看前者,于是页面写着「已安装」、一转写就报「未找到
              转写环境」,而用户最容易做的事是去重下已经在盘上的那几个 GB。 */}
          {model.status === "installed" && model.runtime_ready && (
            <span className="inline-flex items-center gap-[5px] text-xs font-medium text-primary">
              <CheckCircle2 size={14} /> {t("asrModelInstalled")}
            </span>
          )}
          {model.status === "installed" && !model.runtime_ready && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <Download size={13} /> {t("asrModelInstallRuntime")}
            </Button>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <Download size={13} /> {t("asrModelDownload")}
            </Button>
          )}
          {downloading && (
            <span className="inline-flex items-center gap-[5px] text-xs tabular-nums text-muted-foreground">
              <Loader2 size={13} className="animate-openstudio-spin" /> {pct}%
            </span>
          )}
          {model.status === "failed" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <RotateCw size={13} /> {t("asrModelRetry")}
            </Button>
          )}
        </div>
      </div>
      {downloading && (
        <div className="grid gap-[5px]">
          {/* **装运行环境和下模型是两件事**,量纲也不同:前者跑的是 pip(装 torch 等,几 GB
              但我们不知道总量),后者才是这个模型的 2.2GB。没有分母时就别画进度条、也别摆
              「0 MB / 2.2 GB」—— 那个数是模型的,而此刻在跑的不是它。 */}
          {model.total_bytes > 0 ? (
            <>
              <Progress value={pct} />
              <div className="flex items-center justify-between gap-2 text-[11px] tabular-nums text-muted-foreground">
                <span>
                  {fmtBytes(model.downloaded_bytes)} / {fmtBytes(model.total_bytes)}
                </span>
                <span>
                  {fmtSpeed(model.speed_bps)}
                  {model.speed_bps > 0 && model.message ? " · " : ""}
                  {model.message}
                </span>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <Loader2 size={12} className="animate-openstudio-spin" /> {model.message}
            </div>
          )}
        </div>
      )}
      {model.status === "failed" && (
        <div className="flex items-center gap-1.5 text-[11.5px] text-destructive">
          <AlertCircle size={13} /> {model.message}
        </div>
      )}
    </div>
  );
}

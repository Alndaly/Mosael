import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { type AsrModel, downloadAsrModel, listAsrModels } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

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
        <div className="asr-model-list">
          {models.data?.map((model) => (
            <AsrModelCard
              key={model.id}
              model={model}
              busy={download.isPending || models.data?.some((m) => m.status === "downloading")}
              onDownload={() => download.mutate(model.id)}
            />
          ))}
          {models.isLoading && <p className="asr-model-empty">{t("connecting")}</p>}
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
    <div className={`asr-model asr-model-${model.status}`}>
      <div className="asr-model-main">
        <div className="asr-model-info">
          <div className="asr-model-title">
            <strong>{model.label}</strong>
            <span className="asr-model-engine">{model.engine}</span>
            <span className="asr-model-size">{fmtBytes(model.expected_bytes)}</span>
          </div>
          <small className="asr-model-detail">{model.detail}</small>
        </div>
        <div className="asr-model-action">
          {model.status === "installed" && (
            <span className="asr-model-ok">
              <CheckCircle2 size={14} /> {t("asrModelInstalled")}
            </span>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <Download size={13} /> {t("asrModelDownload")}
            </Button>
          )}
          {downloading && (
            <span className="asr-model-progresslabel">
              <Loader2 size={13} className="spin" /> {pct}%
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
        <div className="asr-model-progress">
          <Progress value={pct} />
          <div className="asr-model-progressmeta">
            <span>
              {fmtBytes(model.downloaded_bytes)} / {fmtBytes(model.total_bytes)}
            </span>
            <span>
              {fmtSpeed(model.speed_bps)}
              {model.speed_bps > 0 && model.message ? " · " : ""}
              {model.message}
            </span>
          </div>
        </div>
      )}
      {model.status === "failed" && (
        <div className="asr-model-error">
          <AlertCircle size={13} /> {model.message}
        </div>
      )}
    </div>
  );
}

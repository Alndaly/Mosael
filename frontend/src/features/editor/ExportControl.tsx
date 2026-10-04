import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";

import { exportSequence, type ExportParams, type Sequence } from "@/api/domains/editor";
import { getJob } from "@/api/domains/jobs";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const EXPORT_PARAMS_KEY = "mosael.export.params";
type RememberedExportParams = Omit<ExportParams, "ai_label">;

/**
 * 导出按钮 + 进行中的进度。**做完了不在这里说**(ADR-0018):导出完成 / 失败由任务中心统一
 * 弹提示、发系统通知、刷新素材 —— 这里再挂一个「✓ 导出完成」就是同一件事说两遍,而且它会
 * 一直钉在按钮旁边,直到换页。
 */
export function ExportControl({ sequence }: { sequence: Sequence }) {
  const t = useI18n();
  const qc = useQueryClient();
  const sequenceId = sequence.id;
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [configOpen, setConfigOpen] = React.useState(false);
  // 参数记住上次选择:批量出片时不必每次重选。
  //: 记住的是这几项;「AI 生成」标识不记(见下面 aiLabel)。
  const [params, setParams] = React.useState<RememberedExportParams>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(EXPORT_PARAMS_KEY) ?? "{}") as Partial<RememberedExportParams>;
      return {
        resolution: ["original", "1080p", "720p", "480p"].includes(saved.resolution ?? "") ? saved.resolution! : "original",
        fps: typeof saved.fps === "number" ? saved.fps : null,
        quality: ["high", "standard", "compact"].includes(saved.quality ?? "") ? saved.quality! : "standard",
        loudness_normalize: saved.loudness_normalize === true,
      };
    } catch {
      return { resolution: "original", fps: null, quality: "standard", loudness_normalize: false };
    }
  });
  const updateParams = (patch: Partial<RememberedExportParams>) => {
    setParams((current) => {
      const next = { ...current, ...patch };
      localStorage.setItem(EXPORT_PARAMS_KEY, JSON.stringify(next));
      return next;
    });
  };
  //: 「AI 生成」显式标识(ADR 0028 §5):**默认开、允许关,不记住关** —— 每次导出都从开着开始,关掉是这一次的决定。
  //: 记住的话,关过一次之后每一片都悄悄不带标识,而发布的人未必记得自己关过。
  const [aiLabel, setAiLabel] = React.useState(true);
  //: 时间线上有几段 AI 生成的片段(后端认的,见 SequenceOut.ai_asset_ids)。
  const aiClipCount = React.useMemo(() => {
    const ai = new Set(sequence.ai_asset_ids ?? []);
    return (sequence.tracks ?? []).flatMap((track) => track.clips ?? []).filter((clip) => clip.asset_id && ai.has(clip.asset_id)).length;
  }, [sequence]);
  React.useEffect(() => {
    if (configOpen) setAiLabel(true);
  }, [configOpen]);
  const startExport = useMutation({
    mutationFn: (body: ExportParams) => exportSequence(sequenceId, body),
    // 导出任务建好了再关配置框 —— 此前先关再发请求,按下去到任务出现之间什么反馈都没有。
    onSuccess: (job) => {
      setJobId(job.id);
      setConfigOpen(false);
      // 让任务中心马上看见这条任务,而不是等它下一轮轮询。
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => getJob(jobId!),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 700;
    },
    refetchOnWindowFocus: true,
  });

  const status = jobId ? (job.data?.status ?? "queued") : null;

  const busy = startExport.isPending || status === "queued" || status === "running";

  return (
    <span className="inline-flex items-center gap-1.5">
      {status === "running" && (
        <span className="inline-flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          {job.data?.message && <Truncate className="max-w-[190px]">{job.data.message}</Truncate>}
          <span className="timecode tabular-nums">{Math.round((job.data?.progress ?? 0) * 100)}%</span>
        </span>
      )}
      <Button size="sm" disabled={busy} onClick={() => setConfigOpen(true)}>
        {busy ? <Loader2 size={13} className="animate-mosael-spin" /> : <Download size={13} />}
        {busy ? t("exporting") : t("exportVideo")}
      </Button>
      <ModalShell
        open={configOpen}
        onOpenChange={setConfigOpen}
        title={t("exportConfigTitle")}
        className="w-[380px]"
        footer={
          <>
            <span className="mr-auto text-ui-xs text-muted-foreground">{t("exportConfigHint")}</span>
            <Button size="sm" loading={startExport.isPending} onClick={() => startExport.mutate({ ...params, ai_label: aiLabel })}>
              <Download size={13} /> {t("exportStart")}
            </Button>
          </>
        }
      >
        <div className="grid w-full gap-3.5">
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportResolution")}</span>
            <Select value={params.resolution} onValueChange={(v) => updateParams({ resolution: v as ExportParams["resolution"] })}>
              <SelectTrigger size="sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="original">{t("exportResolutionOriginal")}({sequence.width}×{sequence.height})</SelectItem>
                <SelectItem value="1080p">1080p</SelectItem>
                <SelectItem value="720p">720p</SelectItem>
                <SelectItem value="480p">480p</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportFps")}</span>
            <Select
              value={params.fps == null ? "follow" : String(params.fps)}
              onValueChange={(v) => updateParams({ fps: v === "follow" ? null : Number(v) })}
            >
              <SelectTrigger size="sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="follow">{t("exportFpsFollow")}({sequence.fps}fps)</SelectItem>
                {[24, 25, 30, 50, 60].map((rate) => (
                  <SelectItem key={rate} value={String(rate)}>{rate} fps</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportQuality")}</span>
            <Select value={params.quality} onValueChange={(v) => updateParams({ quality: v as ExportParams["quality"] })}>
              <SelectTrigger size="sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="high">{t("exportQualityHigh")}</SelectItem>
                <SelectItem value="standard">{t("exportQualityStandard")}</SelectItem>
                <SelectItem value="compact">{t("exportQualityCompact")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <label className="grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5" data-export-loudnorm="">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={params.loudness_normalize}
              onChange={(event) => updateParams({ loudness_normalize: event.target.checked })}
            />
            <span className="text-ui-sm font-medium">{t("exportLoudnorm")}</span>
            <span className="col-start-2 text-ui-xs leading-relaxed text-muted-foreground">{t("exportLoudnormHint")}</span>
          </label>
          {/* 只在时间线上真有 AI 生成的片段时出现,并说清是哪几段 —— 没有 AI 内容的片子摆一个「加 AI 标识」开关,
              只会让人以为自己的片子被当成了 AI 生成的。 */}
          {aiClipCount > 0 && (
            <label className="grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5" data-export-ai-label="">
              <input type="checkbox" className="mt-0.5" checked={aiLabel} onChange={(event) => setAiLabel(event.target.checked)} />
              <span className="text-ui-sm font-medium">{t("exportAiLabel")}</span>
              <span className="col-start-2 text-ui-xs leading-relaxed text-muted-foreground">
                {t("exportAiLabelFound").replace("{n}", String(aiClipCount))} {t("exportAiLabelHint")}
              </span>
              {!aiLabel && (
                <span role="alert" data-export-ai-label-off="" className="col-start-2 text-ui-xs leading-relaxed text-warning">
                  {t("exportAiLabelOffWarning")}
                </span>
              )}
            </label>
          )}
        </div>
      </ModalShell>
    </span>
  );
}

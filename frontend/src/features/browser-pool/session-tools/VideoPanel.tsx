import React from "react";
import { Download, Film, Loader2, Lock, RefreshCw, ShieldAlert, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";

import { downloadable, type VideoCandidate, type VideoProbe } from "./videoActions";

export interface DownloadEntry {
  jobId: string;
  title: string;
  status: "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  error?: string;
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds: number | null): string {
  if (!seconds || !Number.isFinite(seconds)) return "";
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function fileOf(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${decodeURIComponent(parsed.pathname)}`;
  } catch {
    return url;
  }
}

/**
 * 侧栏「页面里的视频」:平台页面一张卡(按整页走从链接导入),下面是页面里找到的候选(直链 / HLS / DASH),
 * 受保护的如实标出来、不给下载;最后是这一会儿发起的下载,带进度和取消。
 */
export function VideoPanel({
  probe,
  probing,
  platform,
  downloads,
  starting,
  onDownload,
  onCancel,
  onRefresh,
}: {
  probe: VideoProbe | null;
  probing: boolean;
  /** yt-dlp 有站点解析器时是站点名(B 站、抖音……),否则 null。 */
  platform: string | null;
  downloads: DownloadEntry[];
  /** 正在排哪一条(候选地址,或 "page" 是整页)。 */
  starting: string | null;
  onDownload: (candidate?: VideoCandidate) => void;
  onCancel: (jobId: string) => void;
  onRefresh: () => void;
}) {
  const t = useI18n();
  const kindLabel = { direct: t("browserToolsVideoKindDirect"), hls: t("browserToolsVideoKindHls"), dash: t("browserToolsVideoKindDash") };
  return (
    <div className="grid gap-3" data-video-panel="">
      {platform && (
        <section className="grid gap-2 rounded-lg border border-border bg-panel-inset p-3" data-video-platform="">
          <p className="m-0 text-ui-sm leading-relaxed">{t("browserToolsVideoPlatform").replace("{site}", platform)}</p>
          <Button size="sm" loading={starting === "page"} onClick={() => onDownload()} className="justify-self-start">
            <Download /> {t("browserToolsVideoPlatformAction")}
          </Button>
        </section>
      )}
      {probe?.drm && (
        <p className="m-0 flex items-start gap-2 rounded-lg border border-border bg-panel-inset p-3 text-ui-sm" role="status" data-video-drm="">
          <ShieldAlert size={16} className="mt-0.5 flex-none text-destructive" /> {t("browserToolsVideoDrmBanner")}
        </p>
      )}
      {probing && !probe && (
        <p className="m-0 flex items-center gap-2 text-ui-sm text-muted-foreground">
          <Loader2 size={14} className="animate-mosael-spin" /> {t("browserToolsLoading")}
        </p>
      )}
      {probe && probe.candidates.length === 0 && !platform && (
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground" data-video-empty="">
          {probe.streamOnly ? t("browserToolsVideoStreamOnly") : t("browserToolsVideoEmpty")}
        </p>
      )}
      {probe && probe.candidates.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {probe.candidates.map((candidate) => {
            const open = downloadable(candidate);
            const facts = [
              kindLabel[candidate.kind],
              candidate.width && candidate.height ? `${candidate.width}×${candidate.height}` : "",
              formatDuration(candidate.duration),
              formatBytes(candidate.bytes),
            ].filter(Boolean);
            return (
              <li key={candidate.url} className="grid gap-1.5 rounded-lg border border-border p-2.5" data-video-candidate={candidate.kind}>
                <span className="flex min-w-0 items-center gap-2 text-ui-sm">
                  <Film size={14} className="flex-none text-muted-foreground" />
                  {/* 显示文件名,悬停给完整地址(文件名在地址里,名字被截断时也能从这里读全)。 */}
                  <Hint label={candidate.url}>
                    <Truncate>{fileOf(candidate.url)}</Truncate>
                  </Hint>
                </span>
                <span className="text-ui-xs text-muted-foreground">{facts.join(" · ")}</span>
                {open ? (
                  <Button size="xs" variant="outline" className="justify-self-start" loading={starting === candidate.url} onClick={() => onDownload(candidate)}>
                    <Download /> {t("browserToolsVideoDownload")}
                  </Button>
                ) : (
                  <span className="flex items-center gap-1.5 text-ui-xs text-destructive" data-video-protected="">
                    <Lock size={12} /> {t("browserToolsVideoProtected")}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Button size="xs" variant="ghost" className="justify-self-start" onClick={onRefresh} loading={probing}>
        <RefreshCw /> {t("browserToolsVideoRefresh")}
      </Button>
      {downloads.length > 0 && (
        <section className="grid gap-2 border-t border-border pt-3" data-video-downloads="">
          <h3 className="m-0 text-ui-xs font-semibold text-muted-foreground">{t("browserToolsDownloads")}</h3>
          {downloads.map((entry) => (
            <div key={entry.jobId} className="grid gap-1.5" data-download-status={entry.status}>
              <span className="flex min-w-0 items-center gap-2 text-ui-sm">
                <Truncate className="flex-1">{entry.title}</Truncate>
                {entry.status === "running" && (
                  <IconButton size="icon-xs" onClick={() => onCancel(entry.jobId)} label={t("browserToolsDownloadCancel")}>
                    <X />
                  </IconButton>
                )}
              </span>
              {entry.status === "running" ? (
                <>
                  <Progress value={Math.round(entry.progress * 100)} />
                  <span className="text-ui-xs text-muted-foreground">{t("browserToolsDownloading").replace("{p}", String(Math.round(entry.progress * 100)))}</span>
                </>
              ) : (
                <span className={entry.status === "failed" ? "text-ui-xs text-destructive" : "text-ui-xs text-muted-foreground"}>
                  {entry.status === "succeeded"
                    ? t("browserToolsSavedAsset")
                    : entry.status === "cancelled"
                      ? t("browserToolsDownloadCancelled")
                      : t("browserToolsDownloadFailed").replace("{reason}", entry.error ?? "")}
                </span>
              )}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

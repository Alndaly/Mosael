import React from "react";
import { FileText, Film, Music } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, assetThumbnailUrl, type Job } from "@/api/client";
import { AudioPlayerBar } from "@/components/app/media-playback";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { noteHref } from "@/lib/deepLink";
import { useAssetDetails } from "@/lib/assetQueries";
import { useI18n } from "@/app/preferences";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";

/**
 * 一个任务**交回了什么**。和后端 boards/canvas.outputs_of 同一张表 —— 各种任务的结果本来就长得不一样:
 * 跑节点的交回 `outputs`(素材 / 文字 / JSON / 笔记),生成一次可能出好几张(`asset_ids`),念字、截取出一份
 * (`asset_id`),写字交回一段正文(`text`)。认不出的(工作流整份上下文、导出的内部字段)不摊出来 —— 它们各有
 * 自己的页面,这里只说「做出了什么」。
 */
export type JobOutput =
  | { type: "asset"; asset_id: string }
  | { type: "text"; text: string }
  | { type: "json"; value: unknown }
  | { type: "note"; note_id: string; revision?: number; title?: string };

export function jobOutputs(job: Pick<Job, "status" | "result">): JobOutput[] {
  if (job.status !== "succeeded") return [];
  const result = job.result as Record<string, unknown> | null | undefined;
  if (!result || typeof result !== "object") return [];
  if (Array.isArray(result.outputs)) {
    return result.outputs.filter((one): one is JobOutput => {
      const entry = one as Record<string, unknown> | null;
      if (!entry || typeof entry !== "object") return false;
      if (entry.type === "asset") return typeof entry.asset_id === "string" && Boolean(entry.asset_id);
      if (entry.type === "text") return typeof entry.text === "string";
      if (entry.type === "json") return "value" in entry;
      if (entry.type === "note") return typeof entry.note_id === "string" && Boolean(entry.note_id);
      return false;
    });
  }
  const ids = Array.isArray(result.asset_ids)
    ? result.asset_ids.filter((one): one is string => typeof one === "string" && Boolean(one))
    : [];
  if (!ids.length && typeof result.asset_id === "string" && result.asset_id) ids.push(result.asset_id);
  const outputs: JobOutput[] = ids.map((asset_id) => ({ type: "asset", asset_id }));
  if (typeof result.text === "string" && result.text.trim()) outputs.push({ type: "text", text: result.text });
  return outputs;
}

/** 任务详情里的「结果」一段:图 / 视频点开大图,音频就地播,文字和 JSON 摊开(能滚),笔记给一条链接。 */
export function JobResult({ job }: { job: Job }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const outputs = jobOutputs(job);
  const assetIds = outputs.flatMap((one) => (one.type === "asset" ? [one.asset_id] : []));
  //: 只取这次任务交出来的那几份(按 id 走详情缓存),不为了认出三张图把整个素材库拉回来。
  const { byId } = useAssetDetails(assetIds);
  if (!outputs.length) return null;
  const visual = assetIds.filter((id) => byId.get(id)?.kind !== "audio");
  const gallery: ImagePreviewItem[] = visual.map((id) => {
    const asset = byId.get(id);
    return asset?.kind === "video"
      ? { src: assetFileUrl(id), title: asset.name, video: true }
      : { src: assetPreviewUrl(id), title: asset?.name };
  });

  return (
    <div className="grid min-w-0 gap-1.5 border-t border-border pt-2" data-job-result="">
      <span className="text-ui-xs font-semibold text-muted-foreground">{t("jobDetailResult")}</span>
      {visual.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-1.5">
          {visual.map((id, index) => {
            const asset = byId.get(id);
            return (
              <IconButton
                unstyled
                key={id}
                label={asset?.name || t("imagePreviewTitle")}
                onClick={() => openImagePreview({ ...gallery[index], gallery })}
                className="relative aspect-square cursor-zoom-in overflow-hidden rounded-md border border-border bg-panel-inset p-0 hover:border-border-strong"
              >
                <img src={assetThumbnailUrl(id)} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />
                {asset?.kind === "video" && (
                  <Film size={12} className="absolute bottom-1 right-1 text-[#e8eaed] drop-shadow" aria-hidden />
                )}
              </IconButton>
            );
          })}
        </div>
      )}
      {assetIds
        .filter((id) => byId.get(id)?.kind === "audio")
        .map((id) => (
          <div key={id} className="flex min-w-0 items-center gap-2 rounded-md bg-secondary/40 px-2 py-1.5">
            <Music size={14} className="shrink-0 text-muted-foreground" />
            <Truncate className="max-w-[40%] text-ui-xs">{byId.get(id)?.name}</Truncate>
            <AudioPlayerBar src={assetFileUrl(id)} preload="none" showIcon={false} className="h-7 min-w-0 flex-1 px-0" />
          </div>
        ))}
      {outputs.map((one, index) =>
        one.type === "text" ? (
          <div
            key={`text-${index}`}
            className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-secondary/40 px-2.5 py-2 text-ui-xs leading-relaxed text-foreground [overflow-wrap:anywhere]"
          >
            {one.text}
          </div>
        ) : one.type === "json" ? (
          <pre
            key={`json-${index}`}
            className="m-0 max-h-56 overflow-auto rounded-md bg-secondary/40 px-2.5 py-2 font-mono text-ui-2xs leading-snug text-foreground"
          >
            {JSON.stringify(one.value, null, 2)}
          </pre>
        ) : one.type === "note" ? (
          <a
            key={`note-${one.note_id}`}
            href={noteHref(one.note_id, one.revision)}
            className="inline-flex min-w-0 items-center gap-1.5 text-ui-xs text-primary hover:underline"
          >
            <FileText size={13} className="shrink-0" />
            <Truncate>{one.title || t("documentUntitled")}</Truncate>
          </a>
        ) : null,
      )}
    </div>
  );
}

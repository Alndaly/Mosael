import React from "react";

import { Maximize2, Play } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl } from "@/api/client";
import { useImagePreview } from "@/components/app/image-preview";

/**
 * Renders a tool result as something you can read, falling back to JSON only when nothing
 * else fits.
 *
 * Dispatch is on the SHAPE of the value, not on the tool's name. The same tool returns
 * different shapes depending on which runtime executed it — the pi sidecar's `list_assets`
 * returns full asset records while the MCP one returns a four-key projection — so a
 * name→renderer table would render correctly under one runtime and fall back under the other.
 * A shape test is true of both.
 *
 * Every recogniser is deliberately strict: it must find the keys that make the card
 * meaningful. A loose test that matches "an array of objects" would render a KB search as a
 * broken asset list, which is worse than the JSON it replaced.
 */

/** Unwrap what actually reaches the UI, whatever the runtime wrapped it in. */
export function toolResultData(result: unknown): unknown {
  if (result == null) return null;
  // pi's AgentToolResult: `details.data` is the structured copy, `content` the model's text.
  if (typeof result === "object") {
    const asRecord = result as Record<string, unknown>;
    const details = asRecord.details as Record<string, unknown> | undefined;
    if (details && "data" in details) return details.data;
    // The MCP path wraps everything as {result: ...}.
    if ("result" in asRecord && Object.keys(asRecord).length === 1) return asRecord.result;
    const content = asRecord.content;
    if (Array.isArray(content)) {
      const text = content.find(
        (part) => (part as Record<string, unknown>)?.type === "text",
      ) as { text?: string } | undefined;
      if (typeof text?.text === "string") return parseMaybeJson(text.text);
    }
  }
  if (typeof result === "string") return parseMaybeJson(result);
  return result;
}

function parseMaybeJson(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return text;
  try {
    return JSON.parse(trimmed);
  } catch {
    return text;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function everyRecordHas(value: unknown, ...keys: string[]): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length > 0 && value.every((item) => isRecord(item) && keys.every((key) => key in item));
}

function seconds(value: unknown): string {
  const total = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(total)) return "";
  const mins = Math.floor(total / 60);
  const secs = Math.round(total % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

/* ---------- cards ---------- */

/** Inline player for one asset. Mounted only once its row is opened — a list of twenty
    assets would otherwise create twenty decoders for media nobody asked to see. */
function AssetPlayer({ id, kind, name }: { id: string; kind: string; name: string }) {
  const { openImagePreview } = useImagePreview();
  const src = assetFileUrl(id);
  // Bounded, not full-bleed: an inline preview sits inside a conversation, and a portrait
  // photo at full width pushes the rest of the answer off the screen. Click through to the
  // original for a real look at it.
  if (kind === "image") {
    return (
      <button
        type="button"
        className="block max-h-[200px] w-fit max-w-full cursor-zoom-in overflow-hidden rounded-md border-0 bg-transparent p-0"
        onClick={() => openImagePreview({ src, title: name })}
      >
        <img className="block max-h-[200px] w-auto max-w-full object-contain" src={src} alt={name} loading="lazy" />
      </button>
    );
  }
  if (kind === "video") return <video className="max-h-[260px] w-full rounded-md border border-border bg-black" src={src} controls autoPlay preload="metadata" />;
  if (kind === "audio") return <audio className="h-8 w-full rounded-md" src={src} controls autoPlay preload="metadata" />;
  return null;
}

const PLAYABLE = new Set(["video", "audio", "image"]);

function AssetRow({ row }: { row: Record<string, unknown> }) {
  const { openImagePreview } = useImagePreview();
  const [open, setOpen] = React.useState(false);
  const [thumbFailed, setThumbFailed] = React.useState(false);
  const id = String(row.id ?? "");
  const kind = String(row.kind ?? "");
  const name = String(row.name ?? id);
  // media_info is present on the full record and absent from the projection; the thumbnail
  // is a bonus, never a requirement for the row to render.
  const info = isRecord(row.media_info) ? row.media_info : undefined;
  // An image has no duration; showing "0:00" for one is noise that reads like a broken value.
  const duration = kind === "image" ? null : row.duration_seconds ?? info?.duration;
  const playable = Boolean(id) && PLAYABLE.has(kind);
  const isImage = kind === "image";
  const shouldTryThumb = Boolean(id) && !thumbFailed && (kind === "image" || kind === "video");

  const body = (
    <>
      <span className="relative inline-flex shrink-0">
        {info?.has_thumbnail || shouldTryThumb ? (
          <img
            className="h-[22px] w-[34px] shrink-0 rounded border border-border bg-muted object-cover"
            src={assetThumbnailUrl(id)}
            alt=""
            loading="lazy"
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span className="h-[22px] w-[34px] shrink-0 rounded border border-border bg-muted object-cover" data-kind={kind} />
        )}
        {playable && (
          <span className="absolute inset-0 flex items-center justify-center rounded bg-[color-mix(in_srgb,var(--background)_45%,transparent)] text-foreground opacity-0 transition-opacity duration-[120ms] group-hover/play:opacity-100 group-focus-visible/play:opacity-100 group-aria-expanded/play:opacity-100" aria-hidden>
            {/* An image is opened, not played. */}
            {isImage ? <Maximize2 size={10} /> : <Play size={10} />}
          </span>
        )}
      </span>
      <span className="min-w-0 flex-1 truncate text-foreground" title={name}>
        {name}
      </span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
        {kind}
        {duration != null && seconds(duration) ? ` · ${seconds(duration)}` : ""}
      </span>
    </>
  );

  return (
    <li className="grid gap-1">
      {playable ? (
        <button
          type="button"
          className="group/play flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-[5px] border-0 bg-transparent p-0 text-left hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
          onClick={() => {
            if (isImage) {
              openImagePreview({ src: assetFileUrl(id), title: name });
            } else {
              setOpen((v) => !v);
            }
          }}
          aria-expanded={isImage ? undefined : open}
        >
          {body}
        </button>
      ) : (
        <div className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left">{body}</div>
      )}
      {open && playable && <AssetPlayer id={id} kind={kind} name={name} />}
    </li>
  );
}

function AssetList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row, index) => (
        <AssetRow key={String(row.id ?? row.name ?? index)} row={row} />
      ))}
    </ul>
  );
}

function EmptyResult() {
  return <div className="text-xs text-muted-foreground">没有返回条目</div>;
}

function ProjectList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row) => (
        <li className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left" key={String(row.id)}>
          <span className="min-w-0 flex-1 truncate text-foreground">{String(row.name ?? row.id)}</span>
          {row.active_sequence_id ? <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">有活动序列</span> : null}
        </li>
      ))}
    </ul>
  );
}

function GenericRecordList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row, index) => {
        const title = String(row.name ?? row.title ?? row.label ?? row.tool_name ?? row.id ?? `条目 ${index + 1}`);
        const meta = String(row.kind ?? row.type ?? row.status ?? row.plugin_id ?? "");
        const snippet = String(row.description ?? row.snippet ?? row.summary ?? row.content ?? "");
        return (
          <li className="grid gap-0.5 text-xs" key={String(row.id ?? row.tool_name ?? row.title ?? index)}>
            <span className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left">
              <span className="min-w-0 flex-1 truncate text-foreground" title={title}>{title}</span>
              {meta && <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{meta}</span>}
            </span>
            {snippet && <span className="line-clamp-2 text-[11px] leading-[1.45] text-muted-foreground">{snippet}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function SequenceTree({ value }: { value: Record<string, unknown> }) {
  const tracks = Array.isArray(value.tracks) ? (value.tracks as Record<string, unknown>[]) : [];
  return (
    <div className="grid gap-1.5 text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <strong>{String(value.name ?? "")}</strong>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {String(value.format ?? "")}
          {value.duration_seconds != null ? ` · ${seconds(value.duration_seconds)}` : ""}
        </span>
      </div>
      {tracks.map((track, index) => {
        const clips = Array.isArray(track.clips) ? (track.clips as Record<string, unknown>[]) : [];
        return (
          <div className="flex min-w-0 items-center gap-2" key={String(track.id ?? track.name ?? index)}>
            <span className="w-[76px] shrink-0 grow-0 basis-[76px] truncate text-[11px] text-muted-foreground">
              {String(track.name ?? track.kind ?? `轨道 ${index + 1}`)}
            </span>
            <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
              {clips.map((clip, clipIndex) => (
                <span className="max-w-[140px] shrink-0 truncate rounded border border-border bg-muted px-[7px] py-0.5 text-[11px]" key={String(clip.clip_id ?? clip.id ?? clipIndex)}>
                  {String(clip.asset ?? clip.asset_id ?? "片段")}
                </span>
              ))}
              {clips.length === 0 && <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">空</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfirmationCard({ value }: { value: Record<string, unknown> }) {
  const status = String(value.status ?? "");
  return (
    <div className="flex items-center justify-between gap-2 text-xs" data-status={status}>
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.summary ?? value.permission ?? "")}</span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
        {status === "pending" ? "等待你确认" : status}
      </span>
    </div>
  );
}

function SearchResults({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row, index) => (
        <li className="grid gap-0.5 text-xs" key={String(row.url ?? index)}>
          <a href={String(row.url)} target="_blank" rel="noreferrer noopener" className="min-w-0 flex-1 truncate text-foreground">
            {String(row.title ?? row.url)}
          </a>
          <span className="line-clamp-2 text-[11px] leading-[1.45] text-muted-foreground">{String(row.snippet ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function KbResults({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row, index) => (
        <li className="grid gap-0.5 text-xs" key={`${row.document_id}-${row.chunk_index ?? index}`}>
          <span className="min-w-0 flex-1 truncate text-foreground">{String(row.title ?? row.document_id)}</span>
          <span className="line-clamp-2 text-[11px] leading-[1.45] text-muted-foreground">{String(row.snippet ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function NamedList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0">
      {rows.map((row, index) => (
        <li className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left" key={String(row.id ?? row.type ?? index)}>
          <span className="min-w-0 flex-1 truncate text-foreground">{String(row.name ?? row.label ?? row.type)}</span>
          <span className="line-clamp-2 text-[11px] leading-[1.45] text-muted-foreground">{String(row.description ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function WorkflowCard({ value }: { value: Record<string, unknown> }) {
  const graph = value.graph as { nodes: Record<string, unknown>[]; edges: unknown[] };
  const nodes = graph.nodes ?? [];
  const chips = nodes.slice(0, 8).map((node, index) => String(node.name ?? node.type ?? index));
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.name ?? "工作流")}</span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
        {nodes.length} 节点 · {(graph.edges ?? []).length} 连线
      </span>
      {chips.length > 0 && (
        <span className="flex min-w-0 flex-wrap gap-1">
          {chips.map((chip, index) => (
            <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground" key={`${chip}-${index}`}>{chip}</span>
          ))}
          {nodes.length > 8 && <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground">+{nodes.length - 8}</span>}
        </span>
      )}
    </div>
  );
}

function TaggedAsset({ value }: { value: Record<string, unknown> }) {
  const tags = (value.tags as unknown[]).map(String);
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.name ?? value.asset_id)}</span>
      <span className="flex min-w-0 flex-wrap gap-1">
        {tags.length === 0 && <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">已清空标签</span>}
        {tags.map((tag) => (
          <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground" key={tag}>{tag}</span>
        ))}
      </span>
    </div>
  );
}

function UpdatedList({ value }: { value: Record<string, unknown> }) {
  const rows = (value.updated as Record<string, unknown>[]).filter(isRecord);
  return (
    <div className="grid min-w-0 gap-1.5">
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">已更新 {String(value.count ?? rows.length)} 项</span>
      <ul className="m-0 grid list-none gap-1 p-0">
        {rows.map((row, index) => (
          <li className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left" key={String(row.id ?? index)}>
            <span className="min-w-0 flex-1 truncate text-foreground" title={String(row.name ?? row.id ?? "")}>
              {String(row.name ?? row.id ?? `条目 ${index + 1}`)}
            </span>
            {Array.isArray(row.tags) && (
              <span className="flex min-w-0 flex-wrap gap-1">
                {row.tags.map((tag) => (
                  <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground" key={String(tag)}>{String(tag)}</span>
                ))}
              </span>
            )}
            {typeof row.project_id === "string" && row.project_id && (
              <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">项目 {row.project_id.slice(0, 8)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssetBundle({ value }: { value: Record<string, unknown> }) {
  const rows = Array.isArray(value.assets) ? (value.assets as Record<string, unknown>[]).filter(isRecord) : [];
  if (rows.length > 0 && rows.every((row) => "id" in row && "name" in row && "kind" in row)) {
    return <AssetList rows={rows} />;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">素材集合</span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{String(value.count ?? rows.length)} 项</span>
    </div>
  );
}

function AssetRef({ value }: { value: Record<string, unknown> }) {
  const id = String(value.asset_id ?? "");
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.name ?? value.title ?? "素材")}</span>
      {id && <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground">{id.slice(0, 12)}</span>}
      {typeof value.generation_id === "string" && value.generation_id.trim() && (
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">生成任务 {value.generation_id.slice(0, 8)}</span>
      )}
    </div>
  );
}

function RefSummary({ value }: { value: Record<string, unknown> }) {
  const refs = [
    ["workflow_id", "工作流"],
    ["project_id", "项目"],
    ["sequence_id", "序列"],
    ["job_id", "任务"],
    ["generation_id", "生成"],
  ].filter(([key]) => typeof value[key] === "string" && String(value[key]).trim());
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.name ?? value.title ?? "已创建/已提交")}</span>
      {refs.map(([key, label]) => (
        <span className="max-w-[140px] truncate rounded border border-border bg-muted px-1.5 py-px text-[11px] text-muted-foreground" key={key}>
          {label} {String(value[key]).slice(0, 12)}
        </span>
      ))}
      {value.nodes != null && <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{String(value.nodes)} 节点</span>}
    </div>
  );
}

function PluginOutput({ value }: { value: Record<string, unknown> }) {
  const output = value.output;
  const error = value.error;
  return (
    <div className="grid min-w-0 gap-1.5">
      <div className="flex items-center justify-between gap-2 text-xs" data-status={String(value.status ?? "")}>
        <span className="min-w-0 flex-1 truncate text-foreground">插件工具</span>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{String(value.status ?? "done")}</span>
      </div>
      {error ? <LongText text={String(error)} /> : <ToolResultCard value={output} />}
    </div>
  );
}

function NestedResults({ value }: { value: Record<string, unknown> }) {
  return (
    <div className="grid min-w-0 gap-1.5">
      {typeof value.text === "string" && value.text.trim() && <LongText text={value.text} />}
      <ToolResultCard value={value.results} />
    </div>
  );
}

function DocRef({ value }: { value: Record<string, unknown> }) {
  return (
    <div className="flex w-full min-w-0 items-center gap-2 border-0 bg-transparent p-0 text-left">
      <span className="min-w-0 flex-1 truncate text-foreground">{String(value.title ?? value.document_id)}</span>
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">知识库笔记</span>
    </div>
  );
}

function LongText({ text }: { text: string }) {
  return <div className="max-h-[260px] overflow-y-auto whitespace-pre-wrap text-xs leading-[1.6] text-foreground">{text}</div>;
}

function valueLabel(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length === 0 ? "空列表" : `${value.length} 项`;
  if (isRecord(value)) return Object.keys(value).length === 0 ? "空对象" : `${Object.keys(value).length} 个字段`;
  return String(value);
}

function keyLabel(key: string): string {
  const map: Record<string, string> = {
    answer: "分析结果",
    asset_id: "素材",
    count: "数量",
    error: "错误",
    frames: "帧数",
    json: "JSON",
    length: "长度",
    message: "消息",
    model: "模型",
    output: "输出",
    provider: "供应商",
    result: "结果",
    sent: "通知",
    status: "状态",
    text: "文本",
    waited: "等待",
  };
  return map[key] ?? key.replaceAll("_", " ");
}

function SummaryCard({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value)
    .filter(([, item]) => item != null && item !== "")
    .slice(0, 8);
  if (entries.length === 0) return <EmptyResult />;
  return (
    <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2.5 gap-y-1 text-xs [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:truncate [&_dd]:text-foreground [&_dt]:text-muted-foreground">
      {entries.map(([key, item]) => (
        <React.Fragment key={key}>
          <dt>{keyLabel(key)}</dt>
          <dd title={typeof item === "string" ? item : undefined}>{valueLabel(item)}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

/**
 * The card for this result, or null when no shape matches and JSON is the honest answer.
 *
 * Order matters: the more specific tests come first, because several shapes are arrays of
 * objects and the first match wins.
 */
export type ResultShape =
  | "assets"
  | "kb"
  | "search"
  | "projects"
  | "named"
  | "sequence"
  | "confirmation"
  | "workflow"
  | "tagged"
  | "assetBundle"
  | "assetRef"
  | "updated"
  | "refs"
  | "pluginOutput"
  | "nestedResults"
  | "docref"
  | "records"
  | "empty"
  | "summary"
  | "text"
  | null;

/**
 * Which card fits this value, or null when JSON is the honest answer.
 *
 * Separated from the rendering so the decision itself is testable: it is the part that can
 * quietly regress into showing a KB search as a broken asset list. Order matters — several
 * shapes are arrays of objects, and the first match wins, so the specific tests come first.
 */
export function detectShape(value: unknown): ResultShape {
  if (value == null) return null;
  if (typeof value === "string") return value.trim() ? "text" : "empty";
  if (typeof value === "number" || typeof value === "boolean") return "summary";

  if (Array.isArray(value) && value.length === 0) return "empty";
  if (everyRecordHas(value, "id", "name", "kind")) return "assets";
  if (everyRecordHas(value, "document_id", "snippet")) return "kb";
  if (everyRecordHas(value, "url", "title")) return "search";
  if (everyRecordHas(value, "id", "name", "active_sequence_id")) return "projects";
  if (everyRecordHas(value, "id", "name") || everyRecordHas(value, "type", "label")) return "named";
  if (Array.isArray(value) && value.every(isRecord)) return "records";

  if (isRecord(value)) {
    if (Array.isArray(value.assets) && "count" in value) return "assetBundle";
    if (Array.isArray(value.updated) && "count" in value) return "updated";
    if ("status" in value && "output" in value && "error" in value) return "pluginOutput";
    if (Array.isArray(value.results)) return "nestedResults";
    if ("tracks" in value && Array.isArray(value.tracks)) return "sequence";
    if ("confirmation_id" in value && "status" in value) return "confirmation";
    // get_workflow(以及确认卡执行后的 workflow 结果):graph 里有 nodes/edges 就是一张图。
    if (isRecord(value.graph) && Array.isArray(value.graph.nodes) && Array.isArray(value.graph.edges)) {
      return "workflow";
    }
    // update_asset_tags:单素材 + 新标签集。
    if ("asset_id" in value && Array.isArray(value.tags) && "name" in value) return "tagged";
    if (typeof value.asset_id === "string" && value.asset_id.trim()) return "assetRef";
    if (["workflow_id", "project_id", "sequence_id", "job_id", "generation_id"].some((key) => typeof value[key] === "string" && String(value[key]).trim())) {
      return "refs";
    }
    // create_kb_note:单条文档引用(数组版是 kb 搜索,已在上面命中)。
    if ("document_id" in value && "title" in value && !("snippet" in value)) return "docref";
    // analyze_asset / fetch_url / read_kb_document / llm nodes: prose, not raw data.
    for (const key of ["answer", "text", "content", "body"]) {
      const text = value[key];
      if (typeof text === "string" && text.trim()) return "text";
    }
    return "summary";
  }
  return null;
}

function longTextOf(value: Record<string, unknown> | string): string {
  if (typeof value === "string") return value;
  for (const key of ["answer", "text", "content", "body"]) {
    const text = value[key];
    if (typeof text === "string" && text.trim()) return text;
  }
  return "";
}

export function ToolResultCard({ value }: { value: unknown }): React.ReactElement | null {
  switch (detectShape(value)) {
    case "assets":
      return <AssetList rows={value as Record<string, unknown>[]} />;
    case "kb":
      return <KbResults rows={value as Record<string, unknown>[]} />;
    case "search":
      return <SearchResults rows={value as Record<string, unknown>[]} />;
    case "projects":
      return <ProjectList rows={value as Record<string, unknown>[]} />;
    case "named":
      return <NamedList rows={value as Record<string, unknown>[]} />;
    case "sequence":
      return <SequenceTree value={value as Record<string, unknown>} />;
    case "confirmation":
      return <ConfirmationCard value={value as Record<string, unknown>} />;
    case "workflow":
      return <WorkflowCard value={value as Record<string, unknown>} />;
    case "tagged":
      return <TaggedAsset value={value as Record<string, unknown>} />;
    case "assetBundle":
      return <AssetBundle value={value as Record<string, unknown>} />;
    case "assetRef":
      return <AssetRef value={value as Record<string, unknown>} />;
    case "updated":
      return <UpdatedList value={value as Record<string, unknown>} />;
    case "refs":
      return <RefSummary value={value as Record<string, unknown>} />;
    case "pluginOutput":
      return <PluginOutput value={value as Record<string, unknown>} />;
    case "nestedResults":
      return <NestedResults value={value as Record<string, unknown>} />;
    case "docref":
      return <DocRef value={value as Record<string, unknown>} />;
    case "records":
      return <GenericRecordList rows={value as Record<string, unknown>[]} />;
    case "empty":
      return <EmptyResult />;
    case "summary":
      return isRecord(value) ? <SummaryCard value={value} /> : <SummaryCard value={{ value }} />;
    case "text":
      return <LongText text={longTextOf(value as Record<string, unknown> | string)} />;
    default:
      return null;
  }
}

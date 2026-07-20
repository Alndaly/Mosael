import React from "react";

import { assetThumbnailUrl } from "@/api/client";

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

function AssetList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="tool-card-list">
      {rows.map((row) => {
        const id = String(row.id ?? "");
        const kind = String(row.kind ?? "");
        // media_info is present on the full record and absent from the projection; the
        // thumbnail is a bonus, never a requirement for the row to render.
        const info = isRecord(row.media_info) ? row.media_info : undefined;
        const duration = row.duration_seconds ?? info?.duration;
        return (
          <li className="tool-card-row" key={id || String(row.name)}>
            {info?.has_thumbnail ? (
              <img className="tool-card-thumb" src={assetThumbnailUrl(id)} alt="" loading="lazy" />
            ) : (
              <span className="tool-card-thumb tool-card-thumb-empty" data-kind={kind} />
            )}
            <span className="tool-card-name" title={String(row.name ?? "")}>
              {String(row.name ?? id)}
            </span>
            <span className="tool-card-meta">
              {kind}
              {duration != null && seconds(duration) ? ` · ${seconds(duration)}` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function ProjectList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="tool-card-list">
      {rows.map((row) => (
        <li className="tool-card-row" key={String(row.id)}>
          <span className="tool-card-name">{String(row.name ?? row.id)}</span>
          {row.active_sequence_id ? <span className="tool-card-meta">有活动序列</span> : null}
        </li>
      ))}
    </ul>
  );
}

function SequenceTree({ value }: { value: Record<string, unknown> }) {
  const tracks = Array.isArray(value.tracks) ? (value.tracks as Record<string, unknown>[]) : [];
  return (
    <div className="tool-card-seq">
      <div className="tool-card-seq-head">
        <strong>{String(value.name ?? "")}</strong>
        <span className="tool-card-meta">
          {String(value.format ?? "")}
          {value.duration_seconds != null ? ` · ${seconds(value.duration_seconds)}` : ""}
        </span>
      </div>
      {tracks.map((track, index) => {
        const clips = Array.isArray(track.clips) ? (track.clips as Record<string, unknown>[]) : [];
        return (
          <div className="tool-card-track" key={String(track.id ?? track.name ?? index)}>
            <span className="tool-card-track-name">
              {String(track.name ?? track.kind ?? `轨道 ${index + 1}`)}
            </span>
            <div className="tool-card-clips">
              {clips.map((clip, clipIndex) => (
                <span className="tool-card-clip" key={String(clip.clip_id ?? clip.id ?? clipIndex)}>
                  {String(clip.asset ?? clip.asset_id ?? "片段")}
                </span>
              ))}
              {clips.length === 0 && <span className="tool-card-meta">空</span>}
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
    <div className="tool-card-confirm" data-status={status}>
      <span className="tool-card-name">{String(value.summary ?? value.permission ?? "")}</span>
      <span className="tool-card-meta">
        {status === "pending" ? "等待你确认" : status}
      </span>
    </div>
  );
}

function SearchResults({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="tool-card-list">
      {rows.map((row, index) => (
        <li className="tool-card-result" key={String(row.url ?? index)}>
          <a href={String(row.url)} target="_blank" rel="noreferrer noopener" className="tool-card-name">
            {String(row.title ?? row.url)}
          </a>
          <span className="tool-card-snippet">{String(row.snippet ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function KbResults({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="tool-card-list">
      {rows.map((row, index) => (
        <li className="tool-card-result" key={`${row.document_id}-${row.chunk_index ?? index}`}>
          <span className="tool-card-name">{String(row.title ?? row.document_id)}</span>
          <span className="tool-card-snippet">{String(row.snippet ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function NamedList({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="tool-card-list">
      {rows.map((row, index) => (
        <li className="tool-card-row" key={String(row.id ?? row.type ?? index)}>
          <span className="tool-card-name">{String(row.name ?? row.label ?? row.type)}</span>
          <span className="tool-card-snippet">{String(row.description ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function LongText({ text }: { text: string }) {
  return <div className="tool-card-text">{text}</div>;
}

/**
 * The card for this result, or null when no shape matches and JSON is the honest answer.
 *
 * Order matters: the more specific tests come first, because several shapes are arrays of
 * objects and the first match wins.
 */
export function ToolResultCard({ value }: { value: unknown }): React.ReactElement | null {
  if (value == null) return null;

  if (everyRecordHas(value, "id", "name", "kind")) return <AssetList rows={value} />;
  if (everyRecordHas(value, "document_id", "snippet")) return <KbResults rows={value} />;
  if (everyRecordHas(value, "url", "title")) return <SearchResults rows={value} />;
  if (everyRecordHas(value, "id", "name", "active_sequence_id")) return <ProjectList rows={value} />;
  if (everyRecordHas(value, "id", "name") || everyRecordHas(value, "type", "label")) {
    return <NamedList rows={value} />;
  }

  if (isRecord(value)) {
    if ("tracks" in value && Array.isArray(value.tracks)) return <SequenceTree value={value} />;
    if ("confirmation_id" in value && "status" in value) return <ConfirmationCard value={value} />;
    // analyze_asset / fetch_url / read_kb_document: one long body is prose, not data.
    for (const key of ["answer", "text", "content", "body"]) {
      const text = value[key];
      if (typeof text === "string" && text.trim().length > 80) return <LongText text={text} />;
    }
  }
  return null;
}

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronRight, CircleAlert, FileWarning, Loader2, Wrench } from "lucide-react";

import { api, assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/ui/image-preview";
import { ToolResultCard, toolResultData } from "./toolResultShapes";

/** 工具调用卡的数据形态:后端从 sidecar 事件累积(host.py),流里实时更新、消息 payload 里持久化。 */
export type ToolCall = {
  id: string;
  name: string;
  args?: unknown;
  status: "running" | "done" | "error";
  result?: unknown;
};

/** 取一段短摘要塞进折叠态标题(参考 Claude/Codex:折叠时也能看出这步在干嘛)。 */
function summarize(args: unknown): string | null {
  if (args == null) return null;
  if (typeof args === "string") return args;
  if (typeof args === "number" || typeof args === "boolean") return String(args);
  if (Array.isArray(args)) {
    const first = args.find((item) => typeof item === "string");
    return typeof first === "string" ? first : null;
  }
  if (typeof args === "object") {
    for (const value of Object.values(args as Record<string, unknown>)) {
      if (typeof value === "string" && value.trim()) return value;
    }
  }
  return null;
}

/**
 * Asset ids mentioned anywhere in args/result, for the media preview cards.
 *
 * Only `asset_id`-shaped keys count. A bare `id` is deliberately NOT collected: a list of
 * assets already renders as a card with its own inline players, and treating every `id` as an
 * asset would also drag in workflow, project and confirmation ids, each costing a failed
 * request and a "missing media" tile.
 */
function collectAssetIds(value: unknown, out: Set<string> = new Set()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectAssetIds(item, out);
  } else if (value && typeof value === "object") {
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      if (/asset_?id/i.test(key) && typeof val === "string" && val.trim()) out.add(val.trim());
      else collectAssetIds(val, out);
    }
  }
  return out;
}

/** 媒体预览卡:按素材 kind 渲染图/视频/音频,让智能体「返回」的素材在聊天里可见可播。 */
function MediaPreview({ assetId }: { assetId: string }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const asset = useQuery({
    queryKey: ["agent-asset", assetId],
    queryFn: () => api<Asset>(`/api/assets/${assetId}`),
    staleTime: 60_000,
    retry: false,
  });
  if (asset.isLoading) {
    return (
      <div className="agent-media loading">
        <Loader2 size={13} className="spin" />
      </div>
    );
  }
  if (asset.isError || !asset.data) {
    return (
      <div className="agent-media missing">
        <FileWarning size={13} /> {t("agentMediaMissing")}
      </div>
    );
  }
  const src = assetFileUrl(asset.data.id);
  return (
    <figure className="agent-media">
      {asset.data.kind === "image" ? (
        <button
          type="button"
          className="agent-media-image-button"
          onClick={() => openImagePreview({ src, title: asset.data.name })}
        >
          <img src={src} alt={asset.data.name} loading="lazy" />
        </button>
      ) : asset.data.kind === "video" ? (
        <video src={src} controls preload="metadata" />
      ) : asset.data.kind === "audio" ? (
        <audio src={src} controls preload="metadata" />
      ) : (
        <div className="agent-media missing">
          <FileWarning size={13} /> {asset.data.name}
        </div>
      )}
      <figcaption>{asset.data.name}</figcaption>
    </figure>
  );
}

/** 把 args/result 渲染成可读文本:字符串原样,其余美化成 JSON。 */
function format(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ToolCallCard({ tool }: { tool: ToolCall }) {
  const t = useI18n();
  // 失败默认展开(让人一眼看到出错原因),其余默认折叠。
  const [open, setOpen] = React.useState(tool.status === "error");
  const preview = summarize(tool.args);
  const argText = format(tool.args);
  // Structure first: the runtimes hand us the result pre-stringified, so without unwrapping
  // there is nothing to render but the string.
  const data = React.useMemo(() => toolResultData(tool.result), [tool.result]);
  const card = tool.status === "error" ? null : <ToolResultCard value={data} />;
  const resultText = format(data ?? tool.result);
  const hasBody = Boolean(argText || resultText);
  // Media the tool touched (an analyzed image, a generated clip, synthesized audio…) — shown as
  // playable/viewable cards so the agent's media "returns" are visible in chat, not just text.
  const assetIds = React.useMemo(
    () => (tool.status === "error" ? [] : [...collectAssetIds(tool.args, collectAssetIds(data))]),
    [tool.args, data, tool.status],
  );

  return (
    <div className={`agent-tool ${tool.status}`}>
      <button
        type="button"
        className="agent-tool-head"
        onClick={() => hasBody && setOpen((value) => !value)}
        aria-expanded={hasBody ? open : undefined}
        disabled={!hasBody}
      >
        <span className="agent-tool-glyph" aria-hidden>
          {tool.status === "running" ? (
            <Loader2 size={12} className="spin" />
          ) : tool.status === "error" ? (
            <CircleAlert size={12} />
          ) : (
            <Check size={12} />
          )}
        </span>
        <Wrench size={11} className="agent-tool-icon" aria-hidden />
        <span className="agent-tool-name">{tool.name}</span>
        {preview && !open && <span className="agent-tool-preview">{preview}</span>}
        <span className="agent-tool-status">
          {tool.status === "running" ? t("toolRunning") : tool.status === "error" ? t("toolFailed") : t("toolDone")}
        </span>
        {hasBody && <ChevronRight size={13} className={`agent-tool-chevron ${open ? "open" : ""}`} aria-hidden />}
      </button>
      {card && <div className="agent-tool-card">{card}</div>}
      {open && hasBody && (
        <div className="agent-tool-body">
          {argText && (
            <div className="agent-tool-section">
              <span className="agent-tool-label">{t("toolInput")}</span>
              <pre>{argText}</pre>
            </div>
          )}
          {resultText && (
            <div className="agent-tool-section">
              <span className="agent-tool-label">{t("toolResult")}</span>
              <pre>{resultText}</pre>
            </div>
          )}
        </div>
      )}
      {assetIds.length > 0 && (
        <div className="agent-media-grid">
          {assetIds.map((id) => (
            <MediaPreview key={id} assetId={id} />
          ))}
        </div>
      )}
    </div>
  );
}

/** 一轮里的工具调用序列,竖排成「任务步骤」(带左侧连接轨)。 */
export function ToolCalls({ tools }: { tools: ToolCall[] | undefined }) {
  if (!tools || tools.length === 0) return null;
  return (
    <div className="agent-tools">
      {tools.map((tool) => (
        <ToolCallCard key={tool.id} tool={tool} />
      ))}
    </div>
  );
}

/** 失败轮的错误卡:标题 + 可展开的原始错误,而不是把「执行失败」当正常回答铺开。 */
export function AgentErrorCard({ content, error }: { content: string; error?: string | null }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <div className="agent-error">
      <div className="agent-error-head">
        <CircleAlert size={14} />
        <span>{content || t("agentFailedTitle")}</span>
      </div>
      {error && (
        <>
          <button type="button" className="agent-error-toggle" onClick={() => setOpen((value) => !value)}>
            {t("chatErrorDetail")}
          </button>
          {open && <pre className="agent-error-detail">{error}</pre>}
        </>
      )}
    </div>
  );
}

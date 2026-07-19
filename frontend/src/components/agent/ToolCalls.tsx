import React from "react";
import { Check, ChevronRight, CircleAlert, Loader2, Wrench } from "lucide-react";

import { useI18n } from "@/app/preferences";

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
  const resultText = format(tool.result);
  const hasBody = Boolean(argText || resultText);

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

import React from "react";
import { useQueries } from "@tanstack/react-query";
import { Check, ChevronRight, Copy } from "lucide-react";

import { api, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { outputType, type RegistryLike } from "@/features/workflows/analyze";
import type { Step } from "@/features/workflows/runSteps";
import { WorkflowFailureDetails } from "@/features/workflows/WorkflowFailureDetails";

/**
 * 一次运行里,某个节点**真正产出了什么**。
 *
 * 这份数据一直都在(`workflow.node.finished` 事件带着完整的 outputs),但画布只从里面挖素材 id,
 * 别的一概丢掉。于是 LLM 出的那段文案、json_extract 抽出来的值、模板拼好的字符串 —— 跑完了
 * 也看不见,想知道它到底给了什么,只能在下一个节点上再接一个"通知"把它打出来。
 *
 * 检查器里那一栏「输出变量」列的是**名字**(`{{llm-1.text}}`),不是值。名字回答"我怎么引用它",
 * 而调工作流时真正要问的是"它这次给了什么" —— 两个问题,此前只答了第一个。
 */

/** 值太长就先折起来:一段两千字的模型回复会把检查器顶成一条竖着的绳子。 */
const INLINE_LIMIT = 240;

function CopyButton({ value }: { value: string }) {
  const t = useI18n();
  const [done, setDone] = React.useState(false);
  return (
    <button
      type="button"
      className="shrink-0 cursor-pointer rounded-md border-0 bg-transparent p-1 text-muted-foreground transition-colors hover:text-foreground"
      title={t("copy")}
      onClick={() => {
        void navigator.clipboard.writeText(value);
        setDone(true);
        window.setTimeout(() => setDone(false), 1200);
      }}
    >
      {done ? <Check size={11} /> : <Copy size={11} />}
    </button>
  );
}

/** 把任意输出值变成可读的一段文本。对象/数组给缩进过的 JSON,别的直接 String()。 */
export function outputText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

/** 一行摘要:给节点卡片用 —— 一眼看见"这步给了什么",不用点开检查器。 */
export function outputSummary(
  registry: RegistryLike,
  nodeType: string,
  outputs: Record<string, unknown> | undefined,
): string {
  if (!outputs) return "";
  for (const [key, value] of Object.entries(outputs)) {
    // 素材另有缩略图,不在这儿重复;裸 id 也不是给人看的东西。
    if (outputType(registry, nodeType, key) === "asset") continue;
    const text = outputText(value).replace(/\s+/g, " ").trim();
    if (text) return text;
  }
  return "";
}

function ValueRow({ name, value }: { name: string; value: unknown }) {
  const text = outputText(value);
  const long = text.length > INLINE_LIMIT;
  return (
    <div className="grid min-w-0 gap-1 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] p-1.5">
      <div className="flex min-w-0 items-center gap-1">
        <span className="truncate font-mono text-ui-2xs text-muted-foreground">{name}</span>
        <span className="ml-auto" />
        <CopyButton value={text} />
      </div>
      {long ? (
        // 折起来的那一份仍然要能一眼看见开头 —— 只给个"展开"按钮的话,用户得点开才知道
        // 值不值得点开。
        <details className="group min-w-0">
          <summary className="flex cursor-pointer list-none items-start gap-1 marker:content-none">
            <ChevronRight size={11} className="mt-0.5 shrink-0 transition-transform group-open:rotate-90" />
            <span className="line-clamp-2 whitespace-pre-wrap break-words text-ui-xs text-foreground group-open:hidden">
              {text.slice(0, INLINE_LIMIT)}…
            </span>
          </summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-panel p-1.5 text-ui-2xs text-foreground">
            {text}
          </pre>
        </details>
      ) : (
        <pre className="whitespace-pre-wrap break-words text-ui-xs text-foreground">{text}</pre>
      )}
    </div>
  );
}

function AssetRow({ assetIds }: { assetIds: string[] }) {
  const assets = useQueries({
    queries: assetIds.map((id) => ({
      queryKey: ["asset", id],
      queryFn: () => api<Asset>(`/api/assets/${id}`),
      staleTime: 60_000,
      retry: false,
    })),
  });
  // 素材可能已经被删掉 —— 取不到就不画,这是正常路径而不是错误。
  const ready = assets.map((one) => one.data).filter(Boolean) as Asset[];
  if (ready.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-1">
      {ready.map((asset) => (
        <AssetInlinePreview
          key={asset.id}
          assetId={asset.id}
          name={asset.name || asset.original_filename}
          kind={asset.kind}
          lazy={false}
          plain
          className={
            asset.kind === "image"
              ? "block h-[78px] w-full rounded-md border border-border object-cover"
              : "h-[78px] w-full rounded-md border border-border bg-black object-cover"
          }
        />
      ))}
    </div>
  );
}

export function RunOutputs({ registry, nodeType, step }: { registry: RegistryLike; nodeType: string; step: Step }) {
  const t = useI18n();
  const entries = Object.entries(step.outputs ?? {});
  const assetIds = entries
    .filter(
      ([key, value]) =>
        outputType(registry, nodeType, key) === "asset" && typeof value === "string" && value.trim(),
    )
    .map(([, value]) => String(value));
  const scalars = entries.filter(([key]) => outputType(registry, nodeType, key) !== "asset");

  return (
    <div className="grid min-w-0 gap-1.5 border-t border-border pt-2.5">
      <div className="flex items-center gap-1.5 text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        <span>{t("wfRunOutputs")}</span>
        <span className={`ml-auto font-normal normal-case tracking-normal ${step.status === "failed" ? "text-destructive" : ""}`}>
          {t(RUN_STATUS_LABELS[step.status])}
          {step.ms != null && ` · ${step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`}`}
        </span>
      </div>
      {step.error && (
        <pre className="whitespace-pre-wrap break-words rounded-md border border-destructive/40 bg-destructive/10 p-1.5 text-ui-xs text-destructive">
          {step.error}
        </pre>
      )}
      <WorkflowFailureDetails details={step.details} />
      {assetIds.length > 0 && <AssetRow assetIds={assetIds} />}
      {scalars.map(([key, value]) => (
        <ValueRow key={key} name={key} value={value} />
      ))}
      {assetIds.length === 0 && scalars.length === 0 && !step.error && (
        <span className="text-ui-xs font-normal text-muted-foreground">{t("wfRunNoOutputs")}</span>
      )}
    </div>
  );
}

const RUN_STATUS_LABELS = {
  running: "wfStepRunning",
  done: "wfStepDone",
  skipped: "wfStepSkipped",
  failed: "wfStepFailed",
} as const;

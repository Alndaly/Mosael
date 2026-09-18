import React from "react";
import { Check, ChevronRight, Copy } from "lucide-react";

import { useI18n } from "@/app/preferences";
import type { RegistryLike } from "@/features/workflows/analyze";
import { OutputAssets } from "@/features/workflows/OutputAssets";
import { assetOutputs, outputRows, type OutputRow, type Step } from "@/features/workflows/runSteps";
import { WorkflowFailureDetails } from "@/components/app/FailureDetails";

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

/** 一行摘要:给节点卡片用 —— 一眼看见"这步给了什么",**以及那是哪一个产出**。
 *
 *  名字一起给:只有值的话,`demucs` 这种短值在卡片上就是一个无从判断的词。 */
export function outputSummary(
  registry: RegistryLike,
  nodeType: string,
  outputs: Record<string, unknown> | undefined,
): { label: string; text: string } | null {
  for (const row of outputRows(registry, nodeType, outputs)) {
    // 素材另有缩略图,不在这儿重复;裸 id 也不是给人看的东西。
    if (row.type === "asset") continue;
    const text = outputText(row.value).replace(/\s+/g, " ").trim();
    if (text) return { label: row.label, text };
  }
  return null;
}

function ValueRow({ row }: { row: OutputRow }) {
  const text = outputText(row.value);
  const long = text.length > INLINE_LIMIT;
  return (
    <div className="grid min-w-0 gap-1 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] p-1.5">
      <div className="flex min-w-0 items-center gap-1">
        {/* 名字在前、稳定 key 在后:前者回答"这是什么",后者是 `{{节点.key}}` 里要写的那个词。
            此前只有 key,而它是英文的 —— 同一个输出在右边接点上叫「引擎」,在这里叫 engine。 */}
        <span className="truncate text-ui-2xs text-foreground">{row.label}</span>
        {row.label !== row.key && (
          <span className="shrink-0 font-mono text-ui-2xs text-muted-foreground">{row.key}</span>
        )}
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

export function RunOutputs({ registry, nodeType, step }: { registry: RegistryLike; nodeType: string; step: Step }) {
  const t = useI18n();
  const rows = outputRows(registry, nodeType, step.outputs);
  const assets = assetOutputs(rows);
  const scalars = rows.filter((row) => row.type !== "asset");

  return (
    <div className="grid min-w-0 gap-1.5 pt-2.5">
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
      {assets.length > 0 && <OutputAssets items={assets} density="panel" className="gap-2" />}
      {scalars.map((row) => (
        <ValueRow key={row.key} row={row} />
      ))}
      {assets.length === 0 && scalars.length === 0 && !step.error && (
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

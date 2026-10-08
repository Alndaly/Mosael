import React from "react";
import { FailureCard } from "@/components/failure/FailureCard";
import { Check, ChevronRight, Copy, Download } from "lucide-react";
import { toast } from "sonner";

import { getWorkflowRunOutput } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import type { RegistryLike } from "@/features/workflows/analyze";
import { OutputAssets } from "@/features/workflows/OutputAssets";
import {
  assetOutputs,
  outputRows,
  repeatsOf,
  STEP_STATUS_LABELS,
  truncatedInside,
  type OutputRow,
  type RepeatOf,
  type Step,
} from "@/features/workflows/runSteps";
import { WorkflowFailureDetails } from "@/components/app/FailureDetails";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { saveBlobToDisk } from "@/lib/download";

/**
 * 一次运行里,某个节点**真正产出了什么**。
 *
 * 这份数据一直都在(`workflow.node.finished` 事件带着 outputs;长文字只留开头,全文另取),但画布只从里面挖素材 id,
 * 别的一概丢掉。于是 LLM 出的那段文案、json_extract 抽出来的值、模板拼好的字符串 —— 跑完了
 * 也看不见,想知道它到底给了什么,只能在下一个节点上再接一个"通知"把它打出来。
 *
 * 检查器里那一栏「输出变量」列的是**名字**(`{{llm-1.text}}`),不是值。名字回答"我怎么引用它",
 * 而调工作流时真正要问的是"它这次给了什么" —— 两个问题,此前只答了第一个。
 */

/** 值太长就先折起来:一段两千字的模型回复会把检查器顶成一条竖着的绳子。 */
const INLINE_LIMIT = 240;

/** 复制:值在手里就直接给;被截断的那种给一个「去取全文」的动作 —— 复制到的得是全文,不是开头。 */
function CopyButton({ value }: { value: string | (() => Promise<string>) }) {
  const t = useI18n();
  const [done, setDone] = React.useState(false);
  return (
    <IconButton
      unstyled
      type="button"
      className="shrink-0 cursor-pointer rounded-md border-0 bg-transparent p-1 text-muted-foreground transition-colors hover:text-foreground"
      label={t("copy")}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(typeof value === "string" ? value : await value());
        } catch (error) {
          toast.error(t("wfOutputFullFailed"), { description: errorText(error) });
          return;
        }
        setDone(true);
        window.setTimeout(() => setDone(false), 1200);
      }}
    >
      {done ? <Check size={11} /> : <Copy size={11} />}
    </IconButton>
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

/** 这次什么都没给的值:空串、空列表、空对象。 */
function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  return typeof value === "object" && Object.keys(value).length === 0;
}

/** 一行摘要:给节点卡片用 —— 一眼看见"这步给了什么",**以及那是哪一个产出**。
 *
 *  名字一起给:只有值的话,`demucs` 这种短值在卡片上就是一个无从判断的词。 */
export function outputSummary(
  registry: RegistryLike,
  nodeType: string,
  outputs: Record<string, unknown> | undefined,
): { label: string; text: string } | null {
  const rows = outputRows(registry, nodeType, outputs);
  const repeats = repeatsOf(rows);
  for (const row of rows) {
    // 素材另有缩略图,不在这儿重复;裸 id 也不是给人看的东西 —— 「全部产出」那串 id 也一样(它不是素材口,是 JSON)。
    if (row.type === "asset" || repeats.has(row.key) || isEmptyValue(row.value)) continue;
    const text = outputText(row.value).replace(/\s+/g, " ").trim();
    if (text) return { label: row.label, text };
  }
  return null;
}

/** 下载全文:被截断的那种去取回来再存。 */
function DownloadButton({ name, load }: { name: string; load: () => Promise<string> }) {
  const t = useI18n();
  return (
    <IconButton
      unstyled
      type="button"
      className="shrink-0 cursor-pointer rounded-md border-0 bg-transparent p-1 text-muted-foreground transition-colors hover:text-foreground"
      label={t("wfOutputDownload")}
      onClick={async () => {
        try {
          saveBlobToDisk(new Blob([await load()], { type: "text/plain;charset=utf-8" }), `${name}.txt`);
        } catch (error) {
          toast.error(t("wfOutputFullFailed"), { description: errorText(error) });
        }
      }}
    >
      <Download size={11} />
    </IconButton>
  );
}

/** 快照里截断了的那一格:全文多少字,和去取全文的动作。 */
interface FullText {
  chars: number;
  load: () => Promise<string>;
}

/** 输出里面被截断的一处:路径(取全文的 key)、全文多少字、去取全文的动作(不知道是哪次运行时没有)。 */
interface InsideText {
  path: string;
  chars: number;
  load?: () => Promise<string>;
}

function ValueRow({ row, full, inside = [] }: { row: OutputRow; full?: FullText; inside?: InsideText[] }) {
  const t = useI18n();
  const text = outputText(row.value);
  if (!full && isEmptyValue(row.value)) {
    //: 出图的工作流,「文字产出」这次就是空的 —— 说一句「这次没有」,不摆一个 `[]` 让人猜。
    return (
      <div
        className="flex min-w-0 items-center gap-1 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] px-1.5 py-1"
        data-output-empty={row.key}
      >
        <Truncate className="shrink-0 text-ui-2xs text-foreground">{row.label}</Truncate>
        {row.label !== row.key && <span className="shrink-0 font-mono text-ui-2xs text-muted-foreground">{row.key}</span>}
        <span className="text-ui-2xs text-muted-foreground">{t("wfOutputEmpty")}</span>
      </div>
    );
  }
  const long = text.length > INLINE_LIMIT;
  return (
    <div className="grid min-w-0 gap-1 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] p-1.5">
      <div className="flex min-w-0 items-center gap-1">
        {/* 名字在前、稳定 key 在后:前者回答"这是什么",后者是 `{{节点.key}}` 里要写的那个词。
            此前只有 key,而它是英文的 —— 同一个输出在右边接点上叫「引擎」,在这里叫 engine。 */}
        <Truncate className="text-ui-2xs text-foreground">{row.label}</Truncate>
        {row.label !== row.key && (
          <span className="shrink-0 font-mono text-ui-2xs text-muted-foreground">{row.key}</span>
        )}
        <span className="ml-auto" />
        {full && <DownloadButton name={row.key} load={full.load} />}
        <CopyButton value={full ? full.load : text} />
      </div>
      {full && (
        //: 事件里只存了开头(见后端 run_outputs):不说的话,用户以为看到的、复制到的就是全部。
        <span className="text-ui-2xs text-warning" data-output-truncated="">
          {t("wfOutputTruncated").replace("{n}", String(full.chars))}
        </span>
      )}
      {inside.length > 0 && (
        //: 里面(循环每一项、子图的产出)的长文字也只留了开头:说清哪几处被截了、全文多长,每一处单独
        //: 复制 / 下载 —— 按路径去取全文(整格的复制给的仍是快照,它里面那几段是开头)。
        <div className="grid gap-0.5 text-ui-2xs text-warning" data-output-truncated="">
          <span>{t("wfOutputNestedTruncated")}</span>
          {inside.map(({ path, chars, load }) => (
            <span key={path} className="flex min-w-0 items-center gap-1.5" data-truncated-path={path}>
              <Truncate as="code" className="font-mono">{path}</Truncate>
              <span className="shrink-0">{t("wfOutputNestedChars").replace("{n}", String(chars))}</span>
              <span className="ml-auto" />
              {load && <DownloadButton name={path} load={load} />}
              {load && <CopyButton value={load} />}
            </span>
          ))}
        </div>
      )}
      {long ? (
        // 折起来的那一份仍然要能一眼看见开头 —— 只给个"展开"按钮的话,用户得点开才知道
        // 值不值得点开。
        <details className="group min-w-0">
          <summary className="flex cursor-pointer list-none items-start gap-1 marker:content-none">
            <ChevronRight size={11} className="mt-0.5 shrink-0 transition-transform group-open:rotate-90" />
            <Truncate lines={2} className="whitespace-pre-wrap text-ui-xs text-foreground group-open:hidden">
              {text.slice(0, INLINE_LIMIT)}…
            </Truncate>
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

/** 「就是上面「图 · 预览图像」的第 1 份」:这个口给的就是上面摆出图的那几份。 */
function repeatText(t: (key: MessageKey) => string, repeat: RepeatOf): string {
  const key: MessageKey =
    repeat.whole ? (repeat.count === 1 ? "wfOutputSameAs" : "wfOutputSameAsAll") : repeat.index != null ? "wfOutputSameAsNth" : "wfOutputSameAsSome";
  return t(key).replace("{label}", repeat.label).replace("{n}", String(repeat.count)).replace("{i}", String(repeat.index));
}

/**
 * 交的就是上面那几份的口(「第一份产出」「全部产出」):一行,名字和 key 照报,后面说它是上面哪一份。
 * 此前它们各摆一遍 —— 第一张图出现两次,底下再跟一段两个 32 位 id 的 JSON,维护者问「这个有啥用」。
 * 复制照旧给 id:写脚本、查素材时要的就是它。
 */
function RepeatRow({ row, repeat }: { row: OutputRow; repeat: RepeatOf }) {
  const t = useI18n();
  return (
    <div
      className="flex min-w-0 items-center gap-1 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] py-0.5 pl-1.5 pr-0.5"
      data-output-repeat={row.key}
    >
      <Truncate className="shrink-0 text-ui-2xs text-foreground">{row.label}</Truncate>
      {row.label !== row.key && <span className="shrink-0 font-mono text-ui-2xs text-muted-foreground">{row.key}</span>}
      <Truncate className="text-ui-2xs text-muted-foreground">{repeatText(t, repeat)}</Truncate>
      <span className="ml-auto" />
      <CopyButton value={outputText(row.value)} />
    </div>
  );
}

export function RunOutputs({ registry, nodeType, step }: { registry: RegistryLike; nodeType: string; step: Step }) {
  const t = useI18n();
  const rows = outputRows(registry, nodeType, step.outputs);
  const repeats = repeatsOf(rows);
  const assets = assetOutputs(rows.filter((row) => !repeats.has(row.key)));
  const scalars = rows.filter((row) => row.type !== "asset" && !repeats.has(row.key));

  return (
    <div className="grid min-w-0 gap-1.5 pt-2.5">
      <div className="flex items-center gap-1.5 text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        <span>{t("wfRunOutputs")}</span>
        <span className={`ml-auto font-normal normal-case tracking-normal ${step.status === "failed" ? "text-destructive" : ""}`}>
          {t(STEP_STATUS_LABELS[step.status])}
          {step.ms != null && ` · ${step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`}`}
        </span>
      </div>
      {step.failure && <FailureCard title={t("wfRunFailed")} {...step.failure} data-step-failed={step.nid} />}
      <WorkflowFailureDetails details={step.details} />
      {assets.length > 0 && <OutputAssets items={assets} density="panel" className="gap-2" />}
      {rows.flatMap((row) => {
        const repeat = repeats.get(row.key);
        return repeat ? [<RepeatRow key={row.key} row={row} repeat={repeat} />] : [];
      })}
      {scalars.map((row) => {
        const chars = step.truncated?.[row.key];
        const jobId = step.jobId;
        const full =
          chars != null && jobId
            ? { chars, load: async () => (await getWorkflowRunOutput(jobId, step.nid, row.key)).value }
            : undefined;
        const inside = truncatedInside(step.truncated, row.key).map(({ path, chars }) => ({
          path,
          chars,
          load: jobId ? async () => (await getWorkflowRunOutput(jobId, step.nid, path)).value : undefined,
        }));
        return <ValueRow key={row.key} row={row} full={full} inside={inside} />;
      })}
      {assets.length === 0 && scalars.length === 0 && !step.error && (
        <span className="text-ui-xs font-normal text-muted-foreground">{t("wfRunNoOutputs")}</span>
      )}
    </div>
  );
}

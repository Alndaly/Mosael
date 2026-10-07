import type { TaskEvent } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { DataType } from "@/features/nodeForms/fieldTypes";
import { outputType, type RegistryLike } from "@/features/workflows/analyze";
import { outputPortName } from "@/features/workflows/portNames";
import { parseServerTime } from "@/lib/time";

/**
 * 一次运行的事件流 → 每个节点的状态。
 *
 * 抽成共用模块是因为有两个消费方:执行历史面板,和画布上的实时状态叠加。同一份归约写两遍,
 * 迟早会在某一处漏掉一种事件(比如 skipped —— 条件分支没走到的那一侧),于是两处对同一次运行
 * 给出不同的说法。
 */

export type Step = {
  nid: string;
  name: string;
  /** cancelled:总任务被取消时还在跑的那一步 —— 它没有出错,是被停下的。 */
  status: "running" | "done" | "skipped" | "failed" | "cancelled";
  ms?: number;
  startAt?: number;
  outputs?: Record<string, unknown>;
  /** 快照里截断了的输出 → 全文多少字。全文按 `jobId` 去取(见 getWorkflowRunOutput)。 */
  truncated?: Record<string, number>;
  /** 这一步属于哪一次运行。 */
  jobId?: string;
  error?: string;
  details?: Record<string, unknown>;
  /** 跑着的时候节点自己报的进度(插件跑一张 ComfyUI 工作流:「采样 12/20」)。跑完就不再显示。 */
  progress?: number;
  message?: string;
};

/** 一步的状态怎么说。执行历史的步骤格和产出面板共用这一张;任务的状态是另一组(components/jobs/runStatus)。 */
export const STEP_STATUS_LABELS: Readonly<Record<Step["status"], MessageKey>> = {
  running: "wfStepRunning",
  done: "wfStepDone",
  skipped: "wfStepSkipped",
  failed: "wfStepFailed",
  cancelled: "wfStepCancelled",
};

const TERMINAL_RUN_EVENTS = new Set(["workflow.failed", "workflow.cancelled", "job.failed", "job.cancelled"]);
const CANCEL_RUN_EVENTS = new Set(["workflow.cancelled", "job.cancelled"]);

/** 总任务已经失败或取消时，节点投影也必须收口；否则最后一个 started 会永远转圈。 */
export function runEventIsTerminal(event: TaskEvent): boolean {
  return event.type === "workflow.finished" || TERMINAL_RUN_EVENTS.has(event.type);
}

/** Reduce a run's task events into an ordered per-node step list (Dify-style detail). */
export function toSteps(events: TaskEvent[]): Step[] {
  const order: string[] = [];
  const byNode = new Map<string, Step>();
  const sorted = [...events].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  let terminalAt: number | undefined;
  let terminal: "failed" | "cancelled" | undefined;
  for (const e of sorted) {
    if (TERMINAL_RUN_EVENTS.has(e.type)) {
      terminalAt = e.created_at ? parseServerTime(e.created_at).getTime() : undefined;
      //: 取消和失败一样要收口在跑的那一步,但说法不同:此前一律标成 failed,
      //: 用户点了停止,画布和历史里却是一片红框「失败」。有一条取消就按取消说。
      if (terminal !== "cancelled") terminal = CANCEL_RUN_EVENTS.has(e.type) ? "cancelled" : "failed";
      continue;
    }
    const p = (e.payload ?? {}) as {
      node_id?: string;
      name?: string;
      outputs?: Record<string, unknown>;
      truncated?: Record<string, number>;
      error?: string;
      details?: Record<string, unknown>;
      progress?: number;
      message?: string;
    };
    const nid = p.node_id ?? "";
    if (!nid) continue;
    if (e.type === "workflow.node.started") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "running", startAt: e.created_at ? parseServerTime(e.created_at).getTime() : undefined });
    } else if (e.type === "workflow.node.finished") {
      let s = byNode.get(nid);
      if (!s) {
        order.push(nid);
        s = { nid, name: p.name ?? nid, status: "done" };
        byNode.set(nid, s);
      }
      s.status = "done";
      s.outputs = p.outputs;
      s.truncated = p.truncated;
      s.jobId = e.job_id;
      if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseServerTime(e.created_at).getTime() - s.startAt);
    } else if (e.type === "workflow.node.failed") {
      let s = byNode.get(nid);
      if (!s) {
        order.push(nid);
        s = { nid, name: p.name ?? nid, status: "failed" };
        byNode.set(nid, s);
      }
      s.status = "failed";
      s.error = p.error;
      s.details = p.details;
      if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseServerTime(e.created_at).getTime() - s.startAt);
    } else if (e.type === "workflow.node.progress") {
      const s = byNode.get(nid);
      if (s && s.status === "running") {
        s.progress = typeof p.progress === "number" ? p.progress : s.progress;
        s.message = p.message || s.message;
      }
    } else if (e.type === "workflow.node.skipped") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "skipped" });
    }
  }
  if (terminal) {
    for (const step of byNode.values()) {
      if (step.status !== "running") continue;
      step.status = terminal;
      if (step.startAt != null && terminalAt != null) {
        step.ms = Math.max(0, terminalAt - step.startAt);
      }
    }
  }
  return order.map((nid) => byNode.get(nid)!).filter(Boolean);
}

/** 节点 id → 这一步的状态。画布按它给节点/边上色。 */
export function stepsByNode(events: TaskEvent[]): Record<string, Step> {
  return Object.fromEntries(toSteps(events).map((step) => [step.nid, step]));
}

/**
 * 这一步产出了什么,**按节点自己的声明摊开**:稳定 key、给人看的名字、数据类型、这次的值。
 *
 * 以前历史面板把 `asset_id: 535f288eaeb4…` 一串裸十六进制直接铺在文本块里 —— 同一次生成,
 * 在智能体对话里是一张图,在执行历史里却要用户自己拿着 id 去素材库翻。后来出了缩略图,
 * 但**名字仍然被丢在这一步**:只剩下一串素材 id。于是「分离人声与背景音」跑完,卡片上是两个
 * 一模一样的音频条,而右边接点上明明写着「人声」「背景音」—— 同一份产出,一边有名字一边没有。
 *
 * 画布和检查器都读这一份:两处各拼一遍,就是两种说法(此前一处给 id 列表、一处给首个标量)。
 */
export interface OutputRow {
  /** 稳定 key —— 连线和 `{{node.key}}` 引用用的就是它。 */
  key: string;
  /** 给人看的名字 —— 和画布上那个输出口同一个(portNames.outputPortName)。 */
  label: string;
  type: DataType;
  value: unknown;
}

export function outputRows(
  registry: RegistryLike,
  nodeType: string,
  outputs: Record<string, unknown> | undefined,
): OutputRow[] {
  if (!nodeType || !outputs) return [];
  return Object.entries(outputs).map(([key, value]) => ({
    key,
    label: outputPortName(registry, { type: nodeType }, key),
    type: outputType(registry, nodeType, key),
    value,
  }));
}

/**
 * 某个输出**里面**被截断的那几处。`truncated` 的键是从输出名开始的点号路径(后端 run_outputs.snapshot:
 * 顶层 `text`、嵌套 `results.3.text`,列表按下标、对象按键),值是全文字数;取全文的接口 key 就是这条路径。
 * 顶层那一格自己被截(键就是输出名)不算在这里。
 */
export function truncatedInside(truncated: Record<string, number> | undefined, key: string): Array<{ path: string; chars: number }> {
  return Object.entries(truncated ?? {})
    .filter(([path]) => path.startsWith(`${key}.`))
    .map(([path, chars]) => ({ path, chars }));
}

/** 一份产出素材:名字跟着 id 一起走,到哪儿都还认得出它是哪一个输出。 */
export interface AssetOutput {
  key: string;
  label: string;
  assetId: string;
}

/**
 * 这些行里指向素材的那些。空值不算 —— 没产出的输出不该在界面上占一个位置。
 *
 * **一个素材口可以是一串**(一次出两张的 ComfyUI 工作流那个保存节点的口、宫格切分的 `asset_ids`):每一份各是一项,
 * 带着同一个口的名字。此前只认一个 id,一串的整行丢掉 —— 维护者跑 batch 2 的工作流,那个口上只看得到一张。
 */
export function assetOutputs(rows: OutputRow[]): AssetOutput[] {
  return rows.flatMap((row) =>
    row.type === "asset" ? assetIdsOf(row.value).map((assetId) => ({ key: row.key, label: row.label, assetId })) : [],
  );
}

function assetIdsOf(value: unknown): string[] {
  const ids = Array.isArray(value) ? value : [value];
  return ids.filter((one): one is string => typeof one === "string" && Boolean(one.trim()));
}

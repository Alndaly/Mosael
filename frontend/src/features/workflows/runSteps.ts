import type { TaskEvent } from "@/api/client";
import { outputType } from "@/features/workflows/analyze";

/**
 * 一次运行的事件流 → 每个节点的状态。
 *
 * 抽成共用模块是因为有两个消费方:执行历史面板,和画布上的实时状态叠加。同一份归约写两遍,
 * 迟早会在某一处漏掉一种事件(比如 skipped —— 条件分支没走到的那一侧),于是两处对同一次运行
 * 给出不同的说法。
 */
export function parseIso(iso: string): number {
  return Date.parse(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
}

export type Step = {
  nid: string;
  name: string;
  status: "running" | "done" | "skipped" | "failed";
  ms?: number;
  startAt?: number;
  outputs?: Record<string, unknown>;
  error?: string;
};


/** Reduce a run's task events into an ordered per-node step list (Dify-style detail). */
export function toSteps(events: TaskEvent[]): Step[] {
  const order: string[] = [];
  const byNode = new Map<string, Step>();
  const sorted = [...events].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
  for (const e of sorted) {
    const p = (e.payload ?? {}) as { node_id?: string; name?: string; outputs?: Record<string, unknown>; error?: string };
    const nid = p.node_id ?? "";
    if (!nid) continue;
    if (e.type === "workflow.node.started") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "running", startAt: e.created_at ? parseIso(e.created_at) : undefined });
    } else if (e.type === "workflow.node.finished") {
      const s = byNode.get(nid);
      if (s) {
        s.status = "done";
        s.outputs = p.outputs;
        if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseIso(e.created_at) - s.startAt);
      }
    } else if (e.type === "workflow.node.failed") {
      const s = byNode.get(nid);
      if (s) {
        s.status = "failed";
        s.error = p.error;
        if (s.startAt != null && e.created_at) s.ms = Math.max(0, parseIso(e.created_at) - s.startAt);
      }
    } else if (e.type === "workflow.node.skipped") {
      if (!byNode.has(nid)) order.push(nid);
      byNode.set(nid, { nid, name: p.name ?? nid, status: "skipped" });
    }
  }
  return order.map((nid) => byNode.get(nid)!).filter(Boolean);
}

/** 节点 id → 这一步的状态。画布按它给节点/边上色。 */
export function stepsByNode(events: TaskEvent[]): Record<string, Step> {
  return Object.fromEntries(toSteps(events).map((step) => [step.nid, step]));
}

/** 这一步输出里声明为素材的那些(节点注册表里 outputType === "asset")。
 *
 *  以前历史面板把 `asset_id: 535f288eaeb4…` 一串裸十六进制直接铺在文本块里 —— 同一次生成,
 *  在智能体对话里是一张图,在执行历史里却要用户自己拿着 id 去素材库翻。 */
export function assetOutputs(nodeType: string, outputs: Record<string, unknown>): string[] {
  if (!nodeType) return [];
  return Object.entries(outputs)
    .filter(([key, value]) => outputType(nodeType, key) === "asset" && typeof value === "string" && value.trim())
    .map(([, value]) => String(value));
}

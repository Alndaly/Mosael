/**
 * ComfyUI 工作台的会话(渲染层这一侧,ADR 0038 §3):开着的是哪个连接、桥那边看到的(主进程每 300ms 轮询一次、规整过才发来)、
 * 跑的事件、这次会话里跑过的几次。整个应用只有一个(前台一次只亮一个内嵌视图)。
 *
 * - 开:先记下要开的是谁(视图一亮出来,App 就把浏览器的顶栏换成工作台的),再让主进程亮出视图、注入桥、打开那一张 / 新建一张;
 * - 关:主进程发来 `state: null`(视图收起、开成了普通的编辑器)就结束;
 * - 面板要桥做的事(填值、导出、保存、写标记)经 `workbenchCall` 交给主进程,数据逐项校验,送不进代码。
 */
import React from "react";

import { comfyPartition } from "@/features/plugins/comfyNavigation";

/** 开的是哪个 ComfyUI 连接(面板问插件、建任务都要它)。 */
export interface WorkbenchTarget {
  instanceId: string;
  instanceName: string;
  workspaceId: string;
  /** 那台 ComfyUI 的地址(插件报的编辑器地址) */
  url: string;
}

/** 这次会话里跑过的一次(「运行与结果」面板列出来)。 */
export interface WorkbenchRun {
  jobId: string;
  path: string;
  /** 跑的是画布上的哪一张(桥报的 `workflow.key`):面板先列开着的这一张跑过的,别的那几张收在后面 */
  workflowKey: string;
  workflowName: string;
  /** 产出是什么(image / video / audio …,生成记录的 kind):看大图时视频换播放器 */
  kind: string;
  startedAt: number;
  /**
   * 跑的那一刻导出的图里每个节点叫什么(产出按节点分组、正在跑哪个时标名字):先是图里的标题(没起就是类型),插件报来
   * 给人看的名字之后换成那个(见 nameRun)
   */
  labels: [string, string][];
}

export interface WorkbenchSnapshot {
  target: WorkbenchTarget | null;
  state: ComfyWorkbenchState | null;
  /** 画布上跑的事件(最近的若干条) */
  events: ComfyWorkbenchEvent[];
  runs: WorkbenchRun[];
}

const MAX_EVENTS = 400;
const EMPTY: WorkbenchSnapshot = { target: null, state: null, events: [], runs: [] };

let snapshot: WorkbenchSnapshot = EMPTY;
const listeners = new Set<() => void>();
let unsubscribe: (() => void) | null = null;

function set(next: WorkbenchSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

/** 主进程发来的:同一个连接的才收;`state: null` 是会话结束了。 */
function receive(update: { connectionId: string; state: ComfyWorkbenchState | null }) {
  if (!snapshot.target || snapshot.target.instanceId !== update.connectionId) return;
  if (!update.state) {
    set(EMPTY);
    return;
  }
  const { events, ...rest } = update.state;
  set({ ...snapshot, state: { ...rest, events: [] }, events: [...snapshot.events, ...events].slice(-MAX_EVENTS) });
}

function listen() {
  if (unsubscribe || typeof window.mosaelBrowser?.onComfyWorkbench !== "function") return;
  unsubscribe = window.mosaelBrowser.onComfyWorkbench(receive);
}

export function subscribeWorkbench(listener: () => void): () => void {
  listen();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const workbenchSnapshot = () => snapshot;

export function useWorkbench(): WorkbenchSnapshot {
  return React.useSyncExternalStore(subscribeWorkbench, workbenchSnapshot, workbenchSnapshot);
}

/** 这个界面开得了工作台吗(桌面版、主进程是带工作台那座桥的那一版)。 */
export const workbenchAvailable = () => typeof window.mosaelBrowser?.openComfyWorkbench === "function";

/** 这个视图分区是不是开着的工作台。 */
export const isWorkbenchPartition = (target: WorkbenchTarget | null, partition: string | null | undefined) =>
  Boolean(target && partition && partition === comfyPartition(target.instanceId));

export type WorkbenchOpenOutcome = "opened" | "created" | "missing" | "unsupported" | "elsewhere" | "notReady";

/**
 * 开工作台:先记下要开的是谁(视图一亮出来顶栏就是工作台的),再让主进程亮出视图、注入桥;`path` 打开那一张,`fresh` 新建一张。
 * 没开成(前台被别的视图占着、参数不对)回原因,会话撤掉。
 */
export async function openWorkbench(
  target: WorkbenchTarget,
  open: { path?: string | null; fresh?: boolean } = {},
): Promise<{ ok: true; outcome: WorkbenchOpenOutcome } | { ok: false; error: string }> {
  listen();
  const same = snapshot.target?.instanceId === target.instanceId;
  set({ ...EMPTY, target, runs: same ? snapshot.runs : [] });
  const result = await window.mosaelBrowser!.openComfyWorkbench({
    connectionId: target.instanceId,
    url: target.url,
    name: target.instanceName,
    ...(open.path ? { path: open.path } : {}),
    ...(open.fresh ? { fresh: true } : {}),
  });
  if (!result.ok) {
    if (snapshot.target?.instanceId === target.instanceId) set(EMPTY);
    return { ok: false, error: result.error ?? "" };
  }
  return { ok: true, outcome: result.outcome ?? "opened" };
}

/** 面板要桥做的一件事。没开着工作台、会话已经结束都回原因码。 */
export async function workbenchCall(call: ComfyWorkbenchCall): Promise<ComfyWorkbenchCallResult> {
  const target = snapshot.target;
  if (!target || typeof window.mosaelBrowser?.comfyWorkbench !== "function") return { ok: false, error: "closed" };
  return window.mosaelBrowser.comfyWorkbench({ connectionId: target.instanceId, call });
}

/** 桥没做成:原因码(界面按它说话)和桥说的原话。 */
export class WorkbenchCallError extends Error {
  constructor(
    readonly code: string,
    message = "",
  ) {
    super(message || code);
  }
}

/** 导出画布上现在这张(界面格式 + API 格式 + 前端的 clientId)。没成抛 WorkbenchCallError。 */
export async function exportCanvas(): Promise<ComfyWorkbenchExport> {
  const result = await workbenchCall({ op: "export" });
  if (!result.ok) throw new WorkbenchCallError(result.error, "message" in result ? result.message : "");
  if (!("export" in result) || !result.export) throw new WorkbenchCallError("failed");
  return result.export;
}

/** 记下这次会话里跑的一次。 */
export function rememberRun(run: WorkbenchRun): void {
  if (!snapshot.target) return;
  set({ ...snapshot, runs: [run, ...snapshot.runs].slice(0, 20) });
}

/** 跑的那一次的节点名换成插件报的(和应用表单、「结果取自」同一种叫法,如「预览图像」而不是 PreviewImage)。 */
export function nameRun(jobId: string, labels: [string, string][]): void {
  if (!snapshot.target) return;
  set({ ...snapshot, runs: snapshot.runs.map((run) => (run.jobId === jobId ? { ...run, labels } : run)) });
}

/** 测试用:回到没开的样子(连同订阅)。 */
export function resetWorkbench(): void {
  unsubscribe?.();
  unsubscribe = null;
  set(EMPTY);
}

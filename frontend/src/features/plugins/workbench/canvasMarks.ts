/**
 * 表单 / 「只要这个节点的图」写进**画布**(ADR 0038 §2:画布开着时改的是画布上那几个节点的 `properties`,存盘是 ComfyUI
 * 自己的保存)。标记长什么样只有插件知道(和 `annotate` 写文件同一个函数):宿主问插件要「这张图换上这几张表单要改成的那几处」,
 * 再经桥改画布上的节点。不写那台机器上的文件。每次交全部表单(ADR 0045 §7)。
 *
 * **写给哪一张**:草稿是哪一张的,调用方说(`workflowKey`,轮询报的那张的 key)。导出时先比一次 —— 刚在 ComfyUI 里换到别的一张、
 * 面板还没跟上的那一拍,不拿这张的草稿去算那张;写的时候桥再比一次(导出到写之间隔着一次插件往返,见桥的 `expect`)。
 */
import { getCanvasApp, getCanvasMarks, type WorkflowApp } from "@/api/client";
import { translateNow } from "@/app/preferences";
import { annotatePayload, formsLock, initialDraft, type FormsDraft, type FormsLock } from "@/features/plugins/workflowAppForm";
import { onlyResult, withoutResult } from "@/features/plugins/workbench/workbenchLogic";
import { WorkbenchCallError, exportCanvas, workbenchCall } from "@/features/plugins/workbench/workbenchSession";

/** 读画布上现在这张(含没存的改动)的表单:先经桥导出,再问插件。`path` 是画布开的是哪张(新建没存的是空串):插件据此说出
 *  每张表单的模型 id 和工具名(删之前数在用的几处)。 */
export async function readCanvasApp(instanceId: string, path = ""): Promise<{ content: Record<string, unknown>; data: WorkflowApp }> {
  const exported = await exportCanvas();
  return { content: exported.workflow, data: await getCanvasApp(instanceId, exported.workflow, path) };
}

/**
 * 写的时候画布上已经不是这一张(`switched`),或者这一张在写的同时接连又改过(重算一次也没赶上):一处标记都没写。
 * 文案在这里就取好(不带 hook 的 translateNow):换了一张时面板跟着重挂、这一块已经卸掉了,这句话靠全局的失败提示说出来。
 */
export class CanvasMovedError extends Error {
  constructor(switched: boolean) {
    super(translateNow(switched ? "workbenchCanvasSwitched" : "workbenchCanvasBusy"));
  }
}

/** 按画布上**现在**这张(重新导出)算出要改的标记,经桥改节点;回桥的回答。导出的已经不是 `workflowKey` 那张就不算、不写。 */
async function markOnce(instanceId: string, workflowKey: string, draft: FormsDraft) {
  const exported = await exportCanvas();
  if (!exported.at || exported.at.key !== workflowKey) throw new CanvasMovedError(true);
  const payload = annotatePayload("", 0, draft);
  const marks = await getCanvasMarks(instanceId, { content: exported.workflow, forms: payload.forms ?? [], results: payload.results ?? [] });
  return workbenchCall({ op: "setMarks", marks: { nodes: marks.nodes ?? {}, extra: marks.extra ?? null }, expect: exported.at });
}

/**
 * 把 `workflowKey` 那一张的草稿写进画布。算标记的那一下这张又改过(桥回 changed):按改过的那份再算一次 —— 和晚点一下按钮
 * 一样;换了一张就一处不写。没成抛错(CanvasMovedError、桥的原因码或插件的原话)。
 */
export async function writeCanvasApp(instanceId: string, workflowKey: string, draft: FormsDraft): Promise<void> {
  let result = await markOnce(instanceId, workflowKey, draft);
  if (!result.ok && result.error === "changed") result = await markOnce(instanceId, workflowKey, draft);
  if (result.ok) return;
  if (result.error === "otherWorkflow" || result.error === "changed") throw new CanvasMovedError(result.error === "otherWorkflow");
  throw new WorkbenchCallError(result.error, "message" in result ? result.message : "");
}

/** 画布上这张现在标着哪几个输出节点是结果,和每个输出节点叫什么(插件报的给人看的名字,和表单同一种叫法)。`lock`:这张的
 *  表单是上一版 / 更新版插件写的,这一版不能改标记(见 formsLock)。 */
export interface CanvasResults {
  results: string[];
  labels: Record<string, string>;
  lock: FormsLock | null;
}

/** 这张的表单这一版不能改(上一版 / 更新版插件写的):照「没有表单」写回去会把它们抹掉,一个字都不写。 */
export class FormsLockedError extends Error {
  readonly lock: FormsLock;

  constructor(lock: FormsLock) {
    super("forms locked");
    this.lock = lock;
  }
}

const resultsOf = (data: WorkflowApp, results: string[]): CanvasResults => ({
  results,
  labels: Object.fromEntries((data.outputs ?? []).map((one) => [one.node, one.label || one.title || one.class_type])),
  lock: formsLock(data),
});

export async function readCanvasResults(instanceId: string): Promise<CanvasResults> {
  const { data } = await readCanvasApp(instanceId);
  return resultsOf(data, initialDraft(data).results);
}

/** 改 `workflowKey` 那一张的结果标记(读画布上现在的那份,只动 `results`,每张表单照旧);回改完的样子。 */
async function changeResults(instanceId: string, workflowKey: string, change: (draft: FormsDraft) => FormsDraft): Promise<CanvasResults> {
  const { data } = await readCanvasApp(instanceId);
  const lock = formsLock(data);
  if (lock) throw new FormsLockedError(lock);
  const next = change(initialDraft(data));
  await writeCanvasApp(instanceId, workflowKey, next);
  return resultsOf(data, next.results);
}

/** 「只要这个节点的图」:画布上这张的结果只标这一个输出节点。 */
export const markOnlyResult = (instanceId: string, workflowKey: string, node: string) =>
  changeResults(instanceId, workflowKey, (draft) => onlyResult(draft, node));

/** 撤销:这个节点不再标成结果(走同一条路)。 */
export const unmarkResult = (instanceId: string, workflowKey: string, node: string) =>
  changeResults(instanceId, workflowKey, (draft) => withoutResult(draft, node));

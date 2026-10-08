/**
 * 表单 / 「只要这个节点的图」写进**画布**(ADR 0038 §2:画布开着时改的是画布上那几个节点的 `properties`,存盘是 ComfyUI
 * 自己的保存)。标记长什么样只有插件知道(和 `annotate` 写文件同一个函数):宿主问插件要「这张图换上这几张表单要改成的那几处」,
 * 再经桥改画布上的节点。不写那台机器上的文件。每次交全部表单(ADR 0045 §7)。
 */
import { getCanvasApp, getCanvasMarks, type WorkflowApp } from "@/api/client";
import { annotatePayload, initialDraft, type FormsDraft } from "@/features/plugins/workflowAppForm";
import { onlyResult, withoutResult } from "@/features/plugins/workbench/workbenchLogic";
import { WorkbenchCallError, exportCanvas, workbenchCall } from "@/features/plugins/workbench/workbenchSession";

/** 读画布上现在这张(含没存的改动)的表单:先经桥导出,再问插件。`path` 是画布开的是哪张(新建没存的是空串):插件据此说出
 *  每张表单的模型 id 和工具名(删之前数在用的几处)。 */
export async function readCanvasApp(instanceId: string, path = ""): Promise<{ content: Record<string, unknown>; data: WorkflowApp }> {
  const exported = await exportCanvas();
  return { content: exported.workflow, data: await getCanvasApp(instanceId, exported.workflow, path) };
}

/** 把草稿写进画布:按画布上**现在**这张(重新导出)算出要改的标记,经桥改节点。没成抛错(桥的原因码或插件的原话)。 */
export async function writeCanvasApp(instanceId: string, draft: FormsDraft): Promise<void> {
  const exported = await exportCanvas();
  const payload = annotatePayload("", 0, draft);
  const marks = await getCanvasMarks(instanceId, { content: exported.workflow, forms: payload.forms ?? [], results: payload.results ?? [] });
  const result = await workbenchCall({ op: "setMarks", marks: { nodes: marks.nodes ?? {}, extra: marks.extra ?? null } });
  if (!result.ok) throw new WorkbenchCallError(result.error, "message" in result ? result.message : "");
}

/** 画布上这张现在标着哪几个输出节点是结果,和每个输出节点叫什么(插件报的给人看的名字,和表单同一种叫法)。 */
export interface CanvasResults {
  results: string[];
  labels: Record<string, string>;
}

const resultsOf = (data: WorkflowApp, results: string[]): CanvasResults => ({
  results,
  labels: Object.fromEntries((data.outputs ?? []).map((one) => [one.node, one.label || one.title || one.class_type])),
});

export async function readCanvasResults(instanceId: string): Promise<CanvasResults> {
  const { data } = await readCanvasApp(instanceId);
  return resultsOf(data, initialDraft(data).results);
}

/** 改结果标记(读画布上现在的那份,只动 `results`,每张表单照旧);回改完的样子。 */
async function changeResults(instanceId: string, change: (draft: FormsDraft) => FormsDraft): Promise<CanvasResults> {
  const { data } = await readCanvasApp(instanceId);
  const next = change(initialDraft(data));
  await writeCanvasApp(instanceId, next);
  return resultsOf(data, next.results);
}

/** 「只要这个节点的图」:画布上这张的结果只标这一个输出节点。 */
export const markOnlyResult = (instanceId: string, node: string) => changeResults(instanceId, (draft) => onlyResult(draft, node));

/** 撤销:这个节点不再标成结果(走同一条路)。 */
export const unmarkResult = (instanceId: string, node: string) => changeResults(instanceId, (draft) => withoutResult(draft, node));

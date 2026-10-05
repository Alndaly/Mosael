/**
 * 应用表单 / 「以后只要这张」写进**画布**(ADR 0038 §2:画布开着时改的是画布上那几个节点的 `properties`,存盘是 ComfyUI 自己的
 * 保存)。标记长什么样只有插件知道(和 `annotate` 写文件同一个函数):宿主问插件要「这张图换上这份表单要改成的那几处」,
 * 再经桥改画布上的节点。不写那台机器上的文件。
 */
import { getCanvasApp, getCanvasMarks, type WorkflowApp } from "@/api/client";
import { annotatePayload, initialDraft, type AppDraft } from "@/features/plugins/workflowAppForm";
import { onlyResult } from "@/features/plugins/workbench/workbenchLogic";
import { WorkbenchCallError, exportCanvas, workbenchCall } from "@/features/plugins/workbench/workbenchSession";

/** 读画布上现在这张(含没存的改动)的应用表单:先经桥导出,再问插件。 */
export async function readCanvasApp(instanceId: string): Promise<{ content: Record<string, unknown>; data: WorkflowApp }> {
  const exported = await exportCanvas();
  return { content: exported.workflow, data: await getCanvasApp(instanceId, exported.workflow) };
}

/** 把草稿写进画布:按画布上**现在**这张(重新导出)算出要改的标记,经桥改节点。没成抛错(桥的原因码或插件的原话)。 */
export async function writeCanvasApp(instanceId: string, draft: AppDraft): Promise<void> {
  const exported = await exportCanvas();
  const payload = annotatePayload("", 0, draft);
  const marks = await getCanvasMarks(instanceId, { content: exported.workflow, app: payload.app, results: payload.results ?? [] });
  const result = await workbenchCall({ op: "setMarks", marks: { nodes: marks.nodes ?? {}, extra: marks.extra ?? null } });
  if (!result.ok) throw new WorkbenchCallError(result.error, "message" in result ? result.message : "");
}

/** 「以后只要这张」:画布上这张的结果只标这一个输出节点,应用表单的别的部分照旧(读画布上现在的那份)。 */
export async function markOnlyResult(instanceId: string, node: string): Promise<void> {
  const { data } = await readCanvasApp(instanceId);
  await writeCanvasApp(instanceId, onlyResult(initialDraft(data), node));
}

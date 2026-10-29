import type { QueryClient } from "@tanstack/react-query";

import { getWorkflowLibrary, type PluginInstance, type PluginPackage } from "@/api/client";

/**
 * 进工作台(或新标签页里的 ComfyUI)用哪个地址。**连接工具栏、创作页、画板节点共用这一份**,判据不分叉。
 *
 * 1. 插件报的编辑器地址(`workflow_library` 的 `editor.url`,宿主校验过只认 http(s))—— 权威;
 * 2. 工作流库**读不回来**时(目录类回答有输出预算,整份太大就整份不收;本机服务停着;超时),用**这个连接自己写的地址**
 *    (清单的 `summary_field`,原样用)。ComfyUI 的网页和 API 在同一个源上,插件报的 `editor.url` 就是它 —— 所以这不是猜。
 *
 * 插件报了别的编辑器(不是 ComfyUI)回空串:那不是这个入口的事。
 */
export async function workbenchAddress(
  queryClient: QueryClient,
  pkg: PluginPackage,
  instance: PluginInstance,
  workspaceId: string,
): Promise<string> {
  const library = await queryClient
    .fetchQuery({
      queryKey: ["workflow-library", instance.id, workspaceId],
      queryFn: () => getWorkflowLibrary(instance.id, workspaceId),
      staleTime: 60_000,
      retry: false,
    })
    .catch(() => null);
  const editor = library?.editor;
  if (editor) return editor.kind === "comfyui" ? editor.url : "";
  return connectionAddress(pkg, instance);
}

/**
 * 这个连接自己写的地址(清单的 `summary_field`;本机服务的连接是宿主写进去的那个)。**原样用**:不改写、不拼路径 ——
 * 只认能直接打开的 http(s),别的当没有(那就不摆能点的按钮,并说为什么)。
 */
export function connectionAddress(pkg: PluginPackage, instance: PluginInstance): string {
  const key = pkg.summary_field ?? "";
  if (!key) return "";
  const raw = String(((instance.config ?? {}) as Record<string, unknown>)[key] ?? "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? raw : "";
  } catch {
    return "";
  }
}

/** 认领了工作流库(ADR 0035)的连接才有编辑界面,才有「进它的界面」这回事。 */
export const hasWorkflowEditor = (pkg: PluginPackage) => (pkg.provides ?? []).includes("workflow_library");

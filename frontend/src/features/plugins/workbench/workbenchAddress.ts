import type { QueryClient } from "@tanstack/react-query";

import { getWorkflowLibrary, type PluginInstance, type PluginPackage } from "@/api/client";

/**
 * 进工作台(或新标签页里的 ComfyUI)用哪个地址。创作页、画板节点共用这一份,判据不分叉。
 *
 * 1. **连接自己写的地址**(清单的 `summary_field`;本机服务的连接是宿主写进去的那个),原样用。ComfyUI 的网页和 API 在同一个源上,
 *    插件报的编辑器地址(`editor.url`)就是它 —— 所以这不是猜,而且**不走网络**:点下去立刻有;
 * 2. 连接没写地址时才去问工作流库要 `editor.url`,**最多等 `LIBRARY_PATIENCE_MS`**。
 *
 * 此前反过来(先现问整份工作流库):本机服务停着时,这一问在「请宿主把服务起起来」之前就发出去,一直等到插件超时,按钮就一直转;
 * 目录大的那台一次要传 1MB 多。维护者报的「点了一直 loading、打不开」就是这个。
 *
 * 插件报了别的编辑器(不是 ComfyUI)回空串:那不是这个入口的事。
 */
export async function workbenchAddress(
  queryClient: QueryClient,
  pkg: PluginPackage,
  instance: PluginInstance,
  workspaceId: string,
): Promise<string> {
  const own = connectionAddress(pkg, instance);
  if (own) return own;
  const library = await withPatience(
    queryClient.fetchQuery({
      queryKey: ["workflow-library", instance.id, workspaceId],
      queryFn: () => getWorkflowLibrary(instance.id, workspaceId),
      staleTime: 60_000,
      retry: false,
    }),
  ).catch(() => null);
  const editor = library?.editor;
  return editor?.kind === "comfyui" ? editor.url : "";
}

/** 问工作流库最多等多久。等不到就当问不到 —— 按钮不能因为一次慢请求一直转。 */
const LIBRARY_PATIENCE_MS = 8_000;

function withPatience<T>(pending: Promise<T>): Promise<T | null> {
  return Promise.race([pending, new Promise<null>((resolve) => setTimeout(() => resolve(null), LIBRARY_PATIENCE_MS))]);
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

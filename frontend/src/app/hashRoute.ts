import type { StudioView } from "@/components/layout/AppShell";
import { STUDIO_VIEWS } from "@/components/layout/navLabels";

/**
 * 整个应用的路由是地址里的 hash(`#/<页面>?<参数>`):打包成 file:// 也活得下来 —— hash 不会发到 HTTP。
 * 启动时读一次(哪一页、哪个项目),之后页面一换就把 hash 写回规范的样子。
 */
// 路由认哪些页面,和侧栏/面包屑认哪些页面,是同一件事 —— 手抄第三遍就会漏第三次。
export const VALID_VIEWS: readonly string[] = STUDIO_VIEWS;

export function readHash(): { view: StudioView; projectId: string | null } {
  // Hash routing survives file:// packaging — the fragment never hits HTTP.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const view = VALID_VIEWS.includes(path) ? (path as StudioView) : "home";
  const projectId = new URLSearchParams(query ?? "").get("p");
  return { view, projectId };
}

export function writeHash(view: StudioView, projectId: string | null) {
  //: 这几页地址里带着自己的参数(打开哪一条;AI Studio 是分区和创作会话,ADR 0055),由那一页读完自己清掉 ——
  //: 这里不能先把它抹了:页面是按需加载的,第一次提交时它还没挂上。
  const noteQuery = ["notes", "scenes", "boards", "entities", "ai"].includes(view) && window.location.hash.startsWith(`#/${view}?`) ? window.location.hash.split("?")[1] : "";
  const query = noteQuery ? `?${noteQuery}` : projectId ? `?p=${projectId}` : "";
  const next = `#/${view}${query}`;
  if (window.location.hash !== next)
    window.history.replaceState(null, "", next);
}


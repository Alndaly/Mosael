import type { StudioView } from "@/components/layout/AppShell";
import { STUDIO_VIEWS } from "@/components/layout/navLabels";

/**
 * 整个应用的路由是地址里的 hash(`#/<页面>?<参数>`):打包成 file:// 也活得下来 —— hash 不会发到 HTTP。
 * 启动时读一次(哪一页、哪个项目),之后页面一换就把 hash 写回规范的样子。
 */
// 路由认哪些页面,和侧栏/面包屑认哪些页面,是同一件事 —— 手抄第三遍就会漏第三次。
const VALID_VIEWS: readonly string[] = STUDIO_VIEWS;

export function readHash(): { view: StudioView; projectId: string | null } {
  // Hash routing survives file:// packaging — the fragment never hits HTTP.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  //: 不认识的页面(包括已经不存在的 `home`)落到剪辑页:没有项目时它就是项目浏览器。
  const view = VALID_VIEWS.includes(path) ? (path as StudioView) : "editor";
  const projectId = new URLSearchParams(query ?? "").get("p");
  return { view, projectId };
}

/** 这些页的地址里带自己的参数(打开哪一条;AI Studio 是分区和创作会话,ADR 0055)。 */
const PAGE_QUERY_VIEWS: readonly StudioView[] = ["notes", "scenes", "boards", "entities", "ai"];

/**
 * 换页之后项目 id 怎么取。
 *
 * - 新地址明确带了 `p` → 用它;
 * - 目标是剪辑且没带 `p` → 这是“回到项目列表”,清掉;
 * - 其它页(笔记/画板/场景/实体/AI)没带 `p` → **沿用当前项目**。侧栏只是换页,
 *   不该把正在剪的项目丢掉;以前这里一律 `setProjectId(next.projectId)`,点一下
 *   “3D 场景”再回剪辑就只剩项目列表了。
 */
export function projectAfterHashChange(
  currentProjectId: string | null,
  next: { view: StudioView; projectId: string | null },
): string | null {
  if (next.projectId) return next.projectId;
  return next.view === "editor" ? null : currentProjectId;
}

export function writeHash(view: StudioView, projectId: string | null) {
  const sameView = window.location.hash.startsWith(`#/${view}?`);
  const current = new URLSearchParams(sameView ? (window.location.hash.split("?")[1] ?? "") : "");
  const params = new URLSearchParams();
  //: 页面自己的参数只在“还是同一页”时保留:从一个页面换到另一个页面时,
  //: 上一条记录的 `?note=` / `?board=` 不该跟过去。
  if (sameView && PAGE_QUERY_VIEWS.includes(view)) {
    current.forEach((value, key) => {
      if (key !== "p") params.append(key, value);
    });
  } else if (sameView && view === "editor" && current.get("s")) {
    //: 剪辑页的 `?s=` 是“打开另一条时间线”的入口,不是可以被路由顺手抹掉的临时参数。
    params.set("s", current.get("s")!);
  }
  if (projectId) params.set("p", projectId);
  const query = params.size ? `?${params.toString()}` : "";
  const next = `#/${view}${query}`;
  if (window.location.hash !== next) {
    window.history.replaceState(null, "", next);
  }
}


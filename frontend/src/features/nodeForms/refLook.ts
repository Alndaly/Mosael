import type { MessageKey } from "@/app/messages";
import type { RefCatalog, RefProblem } from "@/features/nodeForms/refCatalog";
import { bareRef } from "@/features/nodeForms/refDoc";

/**
 * 一格里的引用**按这一格的上游清单放行**:清单里列着的(连同它底下的字段)一定指得到。
 *
 * 宿主给的引用目录按「这一层的图」判;可有的格子看得见的不是这一层 —— 容器自己的输出 / 条件读的是体里的节点
 * (见 NodeInspector 的 fieldVariables),这一层的图里没有它们,目录会说「找不到节点」。那一格的清单是对的,以它为准。
 * 整格引用的下拉(RefCombobox)和混写编辑器里的引用标签(RefEditor)都经这里取样子,同一个引用在两处说同一句话。
 */
export function listedRefs(catalog: RefCatalog, variables: readonly string[]): RefCatalog {
  const roots = variables.map(bareRef);
  const listed = (path: string) => roots.some((root) => path === root || path.startsWith(`${root}.`));
  return {
    look: (path) => {
      const look = catalog.look(path);
      return look.problem && listed(path) ? { ...look, problem: null } : look;
    },
    fields: (path) => catalog.fields(path),
  };
}

/** 指不到东西时那句话(错误样式的引用标签底下 / 悬停时说)。 */
export function refProblemText(t: (key: MessageKey) => string, problem: RefProblem): string {
  return problem.kind === "node"
    ? t("wfRefMissingNode").replace("{node}", problem.node)
    : t("wfRefMissingOutput").replace("{node}", problem.node).replace("{output}", problem.output);
}

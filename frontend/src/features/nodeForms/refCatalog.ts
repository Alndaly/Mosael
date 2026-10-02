import React from "react";

/**
 * **一个引用给人看是什么样**:`{{report.json.verdict}}` → 「写运营诊断 · JSON · verdict」,以及它指得到东西吗。
 *
 * 存下去的永远是 `{{节点.输出.子路径}}`(插值引擎认的就是它);屏幕上摆的是节点的名字、输出的显示名、子路径的每一段。
 * 节点叫什么、有哪些输出、输出底下有哪些字段,只有宿主知道(工作流里是这张图和节点注册表,见
 * workflows/workflowRefCatalog),所以由宿主经 context 给;表单这一层不认识任何具体节点。
 * 没有宿主给的(画板、插件的「试一下」—— 那里本来就没有引用)按路径原样分段,不判对错。
 */

/** 指不到东西的原因:没有这个节点(删了、改了名、写错了),或者节点在、没有这个输出。 */
export type RefProblem = { kind: "node"; node: string } | { kind: "output"; node: string; output: string };

export interface RefLook {
  /** 给人看的几段:节点名、输出的显示名、子路径的每一段。 */
  parts: string[];
  /** 指不到东西时为什么;null = 指得到(或这里无从判断)。 */
  problem: RefProblem | null;
}

export interface RefCatalog {
  /** 一个引用(不带花括号的路径,`report.json.verdict`)长什么样、指不指得到。 */
  look(path: string): RefLook;
  /** 一个输出(`report.json`)底下已知的字段路径:输出声明了结构的(JSON Schema)、上次运行交回过的,如 `["verdict", "account.name"]`。 */
  fields(path: string): string[];
}

export const PLAIN_REF_CATALOG: RefCatalog = {
  look: (path) => ({ parts: path.split("."), problem: null }),
  fields: () => [],
};

export const RefCatalogContext = React.createContext<RefCatalog>(PLAIN_REF_CATALOG);

export function useRefCatalog(): RefCatalog {
  return React.useContext(RefCatalogContext);
}

/** 引用给人看的那一行:节点 · 输出 · 子路径。 */
export function refLabel(look: RefLook): string {
  return look.parts.join(" · ");
}

/**
 * 换了父字段,依赖它的子字段就该失效。
 *
 * 用户报的原话:「更新了供应商 模型可能依然是原先的模型 导致两者不匹配」。
 * 换成 Ollama 那条供应商配置之后,模型栏里还挂着上一家的 `kimi-for-coding` ——
 * 两个下拉各自都有值,界面看着完全正常,跑起来才报错。
 *
 * **依赖关系由后端声明**(NODE_TYPES 的 `depends_on`,经 /api/workflows/node-types 发下来),
 * 不是前端一张写死的表:插件节点是运行时才知道的,写死的表永远覆盖不到它们 ——
 * 这个仓库已经因为同一个形状修过好几次(智能体角色表、字段类型表、界面标签表、分段表)。
 *
 * 抽成纯函数是为了能测:它原本是巨型组件里 setConfig 的一段内联闭包,而那一段正是
 * 「改对了没有」最需要被钉住的地方。
 */

/** 只用到 depends_on 这一条 —— 别的字段这里不关心。 */
export interface DependencySpec {
  depends_on?: string;
}

/**
 * 把 `key` 改成 `value` 之后的完整配置。依赖 `key` 的子字段一律清空。
 *
 * 几条边界,每条都有理由:
 *  · **值没变就什么都不做** —— 重新选中同一项(或组件重渲染回填)不该清掉用户填好的模型;
 *  · 子字段本来就是空的就不动它,免得把 `undefined` 写成 `""` 造出一次无谓的改动;
 *  · 只清**直接**依赖 `key` 的那一层。链式(A→B→C)时改 A 只清 B,而清 B 这个动作
 *    本身会再走一次这里,C 跟着 B 一起清 —— 不需要在这里递归。
 */
export function withDependentsCleared(
  config: Record<string, unknown>,
  key: string,
  value: unknown,
  specs: Record<string, DependencySpec | undefined>,
): Record<string, unknown> {
  const next = { ...config, [key]: value };
  if (config[key] === value) return next;
  for (const [dependent, spec] of Object.entries(specs)) {
    if (spec?.depends_on !== key) continue;
    if (next[dependent] === undefined || next[dependent] === "") continue;
    next[dependent] = "";
  }
  return next;
}

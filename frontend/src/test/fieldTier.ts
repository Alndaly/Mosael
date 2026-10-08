/**
 * DOM 一致性:一个容器里的字段(输入框、下拉触发器 —— 都带输入框的描边 `border-field-border` 和一档高度)是不是同一档。
 *
 * 静态的那一道(design/fieldTiers.test.ts)看不见 `size={…}` 算出来的档位;用到这种写法的表单(节点表单的检查器 / 紧凑排法、
 * AI Studio 右栏)在自己的 DOM 测试里用它。返回这个容器里出现过的字段高度类(`h-7` / `h-8` / `h-10`)。
 */
const HEIGHTS = ["h-7", "h-8", "h-10"];

export function fieldHeights(root: ParentNode): string[] {
  const found = new Set<string>();
  for (const element of Array.from(root.querySelectorAll<HTMLElement>(".border-field-border"))) {
    if (element.tagName === "TEXTAREA") continue;
    const classes = element.className.split(/\s+/);
    for (const height of HEIGHTS) if (classes.includes(height)) found.add(height);
  }
  return [...found].sort();
}

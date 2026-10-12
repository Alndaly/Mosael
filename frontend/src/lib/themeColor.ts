import * as React from "react";

/**
 * 主题 token → canvas 认得的颜色。
 *
 * 2D 上下文只认**已经算好的**颜色(`#rrggbb` / `rgb(...)`),不认 `var(--…)` —— 所以「颜色跟主题走」
 * 这件事必须在画之前把 token 解析成一个具体颜色。而解析是一次样式读(`getComputedStyle` 会把样式
 * 算一遍),`paint()` 在拖着笔的时候每秒要被叫几十次:**每帧读一次样式是不行的**(上一轮实测过这个
 * 代价,见 MaskEditor 的 fit / drawingRef 那一套)。所以这里按**主题**解析:
 *
 * - 挂载时读一次,之后**用缓存的那个字符串**画每一帧;
 * - 主题一变(浅 ↔ 深)重读一次,并把新颜色交出去 —— 调用方照着重画。
 *
 * 订阅的是 `<html>` 上那三个属性:主题写在 `class="dark"` 和 `data-theme` 上(见 app/preferences.tsx),
 * 外观(磨砂)写在 `data-appearance` 上(见 app/appearance.tsx)。切主题是个**改属性**的动作,而
 * `paint()` 那头不会自己知道 —— 少了这条订阅,屏幕上就一直是上一个主题的颜色,直到用户下一次动手。
 *
 * **不在这里编兜底色**:读不到就是空串(tokens.css 改了名、jsdom 里没有样式表、没有 document)。
 * 兜底色等于第二份主题,浅深两套迟早分叉;拿不到颜色的调用方各自按「这一层没有颜色」处理
 * (蒙版那边是铺黑 = 那一层空转,屏幕上还有压暗那一笔兜着)。
 */

/**
 * 读一个主题 token 的当前值。**读不到就是空串**。
 *
 * token 的值必须是 canvas 认得的颜色字面量(tokens.css 里的语义色都是 `#rrggbb`)—— 写成
 * `color-mix(...)` 这种表达式的话,`fillStyle` 会**静默地不生效**(它不抛错,只是保持上一个值)。
 */
export function readThemeColor(token: string): string {
  if (typeof document === "undefined") return "";
  return window.getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

/**
 * 主题变了就叫一声,返回退订。
 *
 * `attributeFilter` 只列主题真会写的那三个:`data-font` 和行内 `--font-sans` 也在同一个元素上
 * (见 app/preferences.tsx),但它们和颜色无关,不过滤的话每换一次字体都要白读一次样式。
 */
export function observeThemeColor(onChange: () => void): () => void {
  if (typeof MutationObserver === "undefined") return () => undefined;
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme", "data-appearance"] });
  return () => observer.disconnect();
}

/**
 * 一个主题 token 的当前颜色,**按主题解析**:挂载一次、主题切换一次 —— 渲染期间一次样式都不读。
 */
export function useThemeColor(token: string): string {
  const [color, setColor] = React.useState(() => readThemeColor(token));
  React.useEffect(() => {
    const sync = () => setColor(readThemeColor(token));
    //: 挂载后再读一次:首帧那次渲染可能早于 `<html>` 上的 class(PreferencesProvider 的 effect 比
    //: 子组件的晚跑),那时读到的是上一个主题的颜色。补这一次,后面的切换交给订阅。
    sync();
    return observeThemeColor(sync);
  }, [token]);
  return color;
}

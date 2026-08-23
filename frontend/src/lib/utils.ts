import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * 合并 class,并且**告诉 tailwind-merge 我们自己的字号叫什么**。
 *
 * 不告诉它的代价是静默的:`text-ui-xs` 这种自定义字号不在它的内置表里,于是它按前缀把
 * `text-ui-xs` 和 `text-muted-foreground` 判成同一组(text-color)冲突,只保留后写的那个 ——
 * **字号被悄悄丢掉**,元素回落到继承的大小。
 *
 * 真机上量到的样子:同一行里「已完成」12.5px、「耗时 0.0s」10.5px,而两处源码写的都是
 * `text-ui-xs`。差别只在于前者经过 cn()、后者是纯字符串。于是那个最不重要的状态词,渲染得
 * 和正文一样大。
 *
 * 这里登记一次,全站 80 多个用 cn() 拼字号的地方一起好 —— 逐个把 cn() 拆成纯字符串是修表象,
 * 而且下一个人还会再踩。
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      // 与 design/tokens.css 的 --text-ui-* 一一对应。加新字号要同时加到这里,
      // 否则它在 cn() 里就是不生效 —— 而这件事在页面上看不出是 bug,只看得出"有点怪"。
      "font-size": [{ text: ["ui-2xs", "ui-xs", "ui-sm", "ui-md"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

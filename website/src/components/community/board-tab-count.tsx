"use client";

/**
 * 页头「创意画板」tab 上那一个数字。
 *
 * **为什么只有这一格是 client**:另外两个 tab 的数字(插件 / 工作流)来自构建期读好的
 * registry,服务端直接给;画布分享只在浏览器里按当前语言取,服务端渲染时不知道有几条。
 * 把整块页头变成 client component 会白搭一大段静态 HTML,所以只让这一格挂在
 * `useListedShares("board", locale)` 上。
 *
 * **为什么不多发一次请求**:取数键就是列表自己用的那一个
 * `[...queryKeys.shareList(), "board", locale]`(见 `browse.tsx` 的 `listKey`),
 * `/boards` 的 `BoardBrowser` 和社区首页的第三组读的是同一份缓存。已经取过就是命中
 * (staleTime 5 分钟),没取过才补一次,拿到的结果和列表页共享。
 *
 * 取数中 / 取不到 / 一条都没有时都不渲染数字(见 `boardTabCount`)—— 不闪 0。
 */
import { useListedShares } from "@/components/community/browse";
import { boardTabCount, TAB_COUNT_CLASS } from "@/components/community/community-tabs";
import type { Locale } from "@/i18n/config";

export function BoardTabCount({ locale }: { locale: Locale }) {
  const count = boardTabCount(useListedShares("board", locale));
  if (count === undefined) return null;
  return <span className={TAB_COUNT_CLASS}>{count}</span>;
}

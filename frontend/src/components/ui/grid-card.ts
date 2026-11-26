/**
 * 网格卡片的外壳、封面和信息区。
 *
 * 资产库、实体库、画板库这类「一张图/一块画布 + 名字 + 一行元信息」的卡片曾经各写一遍：
 * 有的封面自己描边、有的整卡无边框，圆角也落在不同层。这里只定义一套——**整张卡是一个圆角
 * 容器，封面从卡片顶部通栏铺满，信息区留在下面**；列表视图不套这套。
 */
export const GRID_CARD =
  "group grid min-w-0 overflow-hidden rounded-xl border border-border bg-panel transition-colors hover:border-border-strong hover:bg-panel-subtle";

/** 卡片顶部通栏封面：自身不再画第二圈圆角/边框，由 GRID_CARD 的 overflow-hidden 裁切。 */
export const GRID_CARD_MEDIA = "relative w-full overflow-hidden bg-panel-inset";

/** 封面下面的信息区：内边距、列间距和标题/元信息对齐。 */
export const GRID_CARD_BODY = "grid min-w-0 gap-1.5 p-3";

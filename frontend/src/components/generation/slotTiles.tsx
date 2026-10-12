import React from "react";
import { ArrowLeftRight } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";

/**
 * 生成面板和表单预览**共用的那两样摆样子**:一格素材的外壳(+ 格子里那一行),以及首尾帧那一组的成对壳
 * (+ 中间那颗对调箭头)。
 *
 * 它们此前住在 `features/ai-studio/FrameSlotField` 里 —— 那是真面板自己的家,而预览要照它那一栏写着的
 * 「用的人看到的就是这样」画同一组东西,就只能反过来 import 那个功能模块,于是
 * `features/ai-studio` ↔ `features/plugins` 互相依赖(`features/featureBoundaries.test.ts` 的
 * 「互相依赖的功能:把它们共用的那个东西挪到 lib/ 或 components/」)。
 *
 * **为什么是 `components/generation/`,不是 `lib/`**:这里是**界面零件** —— JSX、className、DOM 抓手;
 * 数据与判据那一半(`SourceRole`、`ROLE_COPY`、`slotColumns`、名字链 `slotName`)住在 `lib/sourceFrames`。
 * 分成两处之后,两边的**结构**由同一份代码画出来:标题、说明、并排的列宽、箭头的位置与尺寸、
 * 格子的高度与圆角,谁都摆不出第二种样子(面板 vs 预览逐项比对的用例见
 * `plugins/appForm/PreviewPanel.keyframes.dom.test.tsx`)。
 */

/** 一格素材。
 *
 * **固定高度而不是固定比例。** 用 aspect-video 的话,一行只挂一份时那一格会被拉成整个面板宽
 * (280×157),一个空的加号占掉半屏;而挂满三份时又缩成邮票。固定高度让"一份"和"三份"看起来
 * 是同一种东西,只是宽窄不同。
 *
 * **`content-center` 不是 `place-items-center`**(维护者截图:首/尾帧那一格的标题
 * `Optional Load Image : …` 左右各被切掉一截、连省略号都没有)。这一格是网格子项,里面的
 * 「图标 + 名字」那一行是它的网格项 —— 而 `place-items` 里的 `justify-items: center` 会把那一行
 * 按 **max-content** 排版:一行 300px 的面板里,120px 的格子里那一行量出来 310px,再由
 * `overflow-hidden` 从**两边**硬裁;里面的 `Truncate` 拿到的是 280px(正好等于文字宽度),
 * `scrollWidth == clientWidth`,省略号永远不触发。实测(真浏览器,面板 300px):
 * `place-items-center` → 格子 120px、那一行 310px、左右各被切掉 9 / 14 个字;
 * `content-center`(justify-items 回到 stretch)→ 那一行 118px、标题 88px / 文字 280px、
 * 省略号出来。`content-center` 只把格子里那一行**竖着**居中,横着照旧铺满 —— 图片那种要填满的
 * 内容不受影响(它本来就是 `absolute inset-0`)。
 *
 * **居中在那一行上做,不在这一格上做**(维护者截图:「参考图」那一格是 `+ 图一` **整行靠左**)。
 * 这一格横着铺满那一行之后,那一行自己用 `justify-center` 把「图标 + 名字」这一组摆在中间
 * (见 EmptyTile)。这是**唯一**两头都占的写法:`justify-items: center` 在这一格上会退回上面那个
 * max-content 的坑(截断失效 + 两边硬裁),而只写 `justify-center` 在这一格上也一样 —— 它居中的是
 * **网格轨道里的那一行**(那行本来就铺满,没有可挪的余量),不是在居**行里的两个子项**。
 *
 * 这一轮的实测(真 Chromium,面板 300px,同一份探针里还挂了一栏把格子改回 `place-items-center` 的对照):
 *
 * | 那一格 | 那一行 | `图一` 左右留白 | 长名字 `Optional Load Image : … #10` |
 * | --- | --- | --- | --- |
 * | 288px(一列) | 286px | 各 **123px** | 那一行 286px、标题 256/274 → 省略号 |
 * | 92px(三列并排) | 90px | 各 **25px** | 那一行 90px、标题 60/274 → 省略号 |
 * | 92px(对照:`place-items-center`) | **303.94px** | 各 −99.97px(两头都露出去) | 标题 274/274 → **没有省略号**,两头硬裁 |
 *
 * `min-w-0` 留着:`Truncate` 的父级得能收缩,这条进 docs/CONVENTIONS 的「字段名 / 表单名外面
 * 那一层必须能收缩」。
 *
 * 谁在用它:真面板那一格(`ai-studio/FrameSlotField.Tile` 与 `EmptyTile`)和表单预览那一格
 * (`plugins/appForm/PreviewPanel.KeyframesTile`)。
 */
export const SLOT_TILE = "grid h-[68px] w-full min-w-0 content-center overflow-hidden rounded-lg border border-border bg-muted/40";

/** 一格里的「图标 + 名字」那一行 —— 面板那一格和预览那一格**共用这一份**(名字长了的截法就同一条)。
 *
 * 居中由**这一行自己**做(`justify-center`),不是由那一格做(见 SLOT_TILE 上头那段):这一行是那一格的网格子项、
 * 照旧被 stretch 铺满,`Truncate` 才能拿到正确的宽度、名字长了才出省略号。短名字时多出来的空位由 `justify-center`
 * 分给两边;名字长到放不下时这一行**不溢出**:`Truncate` 带 `min-w-0`、`flex-shrink` 是默认的 1,它一路收缩到
 * 剩下的宽度(图标 `shrink-0` 不动),自由空间正好为零 —— 居中没有可以挪的余量,也就不会两头露出去。
 *
 * 图标可以没有 —— 预览里那一格按不动,没有可点的东西,就不摆那个加号。
 */
export function SlotTileText({ icon, name }: { icon?: React.ReactNode; name: string }) {
  return (
    <span className="flex min-w-0 items-center justify-center gap-1 px-1.5">
      {icon ? <span className="shrink-0">{icon}</span> : null}
      <Truncate>{name}</Truncate>
    </span>
  );
}

/**
 * 「对调首尾帧」那一颗箭头 —— 首尾帧那一组的**中间那一格**。
 *
 * 面板和预览里是同一颗:预览里按不动(预览没有可对调的东西,值都不存),面板里两边都挂上了才按得动。
 * 两处各画一颗的话,位置(中间那一列 28px)、尺寸(24×24)、图标迟早不一样。
 */
export function KeyframeSwapButton({
  canSwap,
  onSwap,
  groupDisabled = false,
}: {
  /** 两边都挂上了才换得动 —— 只挂了一边那不是对调,是搬家。 */
  canSwap: boolean;
  onSwap?: () => void;
  groupDisabled?: boolean;
}) {
  const t = useI18n();
  return (
    <IconButton
      variant="ghost"
      size="icon"
      className="mx-auto h-6 w-6"
      disabled={groupDisabled || !canSwap}
      onClick={() => onSwap?.()}
      label={t("genSwapKeyframes")}
      //: 「少了一张」这一句两边都写:面板里空着的时候也是这一句,预览里那一组和面板空着时长得一样。
      //: (整组被锁住时上面已经写了原因,这里不再重复 —— `Hint` 只在 `disabled` 时看这一条。)
      disabledReason={!groupDisabled && !canSwap ? t("genSwapKeyframesNeedsBoth") : undefined}
    >
      <ArrowLeftRight size={13} />
    </IconButton>
  );
}

/**
 * 首尾帧那一**组**:一行标题、一句说明,然后是左右两格并排、中间一个对调箭头(模型只认首帧时只有左边一格)。
 *
 * 这一组有**两处**要画:生成面板的「引擎参数」和表单编辑器的预览。维护者 2026-10-12 的截图:同一张表单,
 * 面板里是一组(「首尾帧」+ 并排两格 + 中间那个箭头),预览里却是两个各自独立的竖框 —— 而预览那一栏写的是
 * 「用的人看到的就是这样」。所以标题、说明、并排的列宽、箭头的位置与尺寸**只有这一份**:
 * 两处各自给的只有格子里的东西 —— 面板给的是能传图的那一格(ai-studio/FrameSlotField.Tile),
 * 预览给的是画着名字、按不动的静态格(plugins/appForm/PreviewPanel.KeyframesTile)。
 *
 * 它是**纯摆样子**的:状态(挂了哪几张、能不能对调)全在调用方,所以两个界面能共用它而不搅在一起。
 */
export function KeyframePairFrame({
  showLast,
  first,
  last,
  hint,
  note,
  disabled = false,
  swap,
}: {
  /** 尾帧那一格画不画:模型只认首帧时就没有右边那一格,也没有箭头(见 GenerateWorkspace 的 withLast)。 */
  showLast: boolean;
  first: React.ReactNode;
  last: React.ReactNode;
  /** 这一组的说明那句话;不传就按 showLast 取既有文案(和面板传的是同一句)。 */
  hint?: string;
  /** 整组被锁住时写出来的那句原因(面板:首尾帧和参考素材互斥)。 */
  note?: string;
  disabled?: boolean;
  /** 对调那一下。预览不传:箭头照旧在,但是按不动(和面板里一张都没挂时同一个样子)。 */
  swap?: { canSwap: boolean; onSwap?: () => void };
}) {
  const t = useI18n();
  const hintText = hint ?? (showLast ? t("genLastFrameHint") : t("genKeyframeHint"));
  return (
    <div
      //: 这一组的抓手:面板与预览里都是它(用例和探针照它比两边的结构 —— 见 docs/CONVENTIONS 那条「预览必须与真面板一致」)。
      data-keyframe-pair={showLast ? "both" : "first"}
      className={`grid gap-1.5 text-ui-xs font-semibold text-muted-foreground ${disabled ? "opacity-45" : ""}`}
    >
      <span>{showLast ? t("genKeyframes") : t("genFirstFrame")}</span>
      {hintText && <span className="font-normal leading-[1.5] text-muted-foreground/80">{hintText}</span>}
      {disabled && note && <span className="font-normal leading-[1.5] text-muted-foreground/80">{note}</span>}
      {showLast ? (
        <div data-keyframe-row="" className="grid grid-cols-[minmax(0,1fr)_28px_minmax(0,1fr)] items-center gap-1">
          {first}
          <KeyframeSwapButton canSwap={swap?.canSwap ?? false} onSwap={swap?.onSwap} groupDisabled={disabled} />
          {last}
        </div>
      ) : (
        <div className="grid gap-1.5">{first}</div>
      )}
    </div>
  );
}

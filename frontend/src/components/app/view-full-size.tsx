import React from "react";
import { Maximize2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/utils";

/**
 * 「看大图」:压在缩略图角上的一颗小按钮,点开全站共用的那个灯箱(image-preview)。
 *
 * **给点一下另有意思的地方用。** 素材库里点一下是开详情、勾选模式里是勾选,挑素材的弹窗里是挑,
 * 画布上是选中节点,笔记里是选中这张图去改链接 —— 让缩略图自己接管点击,原来那件事就做不成了。
 * 看大图于是是一个**明确的动作**:平时藏着,悬停或者键盘走到这一格(`group/preview` 里有东西拿到焦点)
 * 时露出来;它自己能 Tab 到,读屏念「看大图:名字」。
 *
 * 外层要挂 `group/preview`(再加 `relative`,按钮按绝对定位摆;位置由 className 给)。
 * 点下去不冒泡:外层那一格的点击(开详情、勾选、选中)不跟着发生。
 */
export function ViewFullSizeButton({
  name,
  onOpen,
  className,
}: {
  /** 这一张叫什么 —— 进读屏和悬停说明,一排里几十颗按钮才分得清。 */
  name: string;
  onOpen: () => void;
  className?: string;
}) {
  const t = useI18n();
  return (
    <IconButton
      unstyled
      type="button"
      data-view-full-size=""
      label={t("viewFullSizeOf").replace("{name}", name)}
      //: **按下不拦。** 拖进时间线、拖着排序的那一格里,从这颗上按下去拖照样拖得动(dnd-kit 要挪够 6px 才算拖,
      //: 原地点一下仍然是点);而按下若被拦住,别处开着的菜单、弹层也就收不到「点了外面」,关不掉了。
      //: 画布上靠 nodrag 让 React Flow 别把这一下当成拖节点。
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      className={cn(
        "nodrag nopan absolute z-[3] grid size-7 cursor-zoom-in place-items-center rounded-md border-0 bg-[rgba(10,12,15,0.72)] p-0 text-[#e8eaed] backdrop-blur-sm transition-opacity duration-150",
        "opacity-0 hover:bg-[rgba(10,12,15,0.86)] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/preview:opacity-100 group-focus-within/preview:opacity-100",
        //: 没有悬停的设备(触屏)上一直露着 —— 不然那里永远看不到它。
        "[@media(hover:none)]:opacity-100",
        className,
      )}
    >
      <Maximize2 size={13} aria-hidden />
    </IconButton>
  );
}

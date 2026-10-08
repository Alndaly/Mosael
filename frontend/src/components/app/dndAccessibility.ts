import React from "react";
import type { Announcements, ScreenReaderInstructions } from "@dnd-kit/core";

import { useI18n } from "@/app/preferences";

/**
 * 能拖的那几处(AI 工作台的会话列表、剪辑页把素材拖上时间线、画板时间线格里的片段、资产的参考墙)给读屏的说明和播报。
 *
 * dnd-kit 不给就用它自带的英文那一套,而且播报的是内部 id(「Picked up draggable item 3f9c…」)—— 中文界面里
 * 读屏念一串英文和十六进制。它自带的说明讲的还是键盘拖法(空格拿起、方向键移动),而这几处只装了指针的传感器,
 * 照念就是骗人。每个 `<DndContext>` 都传 `accessibility={useDndAccessibility()}`,不各写一份;自己接了键盘、
 * 自己念的(插件表单搭建器)照旧。
 */
export function useDndAccessibility(): { screenReaderInstructions: ScreenReaderInstructions; announcements: Announcements } {
  const t = useI18n();
  return React.useMemo(
    () => ({
      screenReaderInstructions: { draggable: t("dndInstructions") },
      announcements: {
        onDragStart: () => t("dndPickedUp"),
        onDragOver: ({ over }) => (over ? t("dndMovedOver") : t("dndMovedNowhere")),
        onDragEnd: ({ over }) => (over ? t("dndDropped") : t("dndCancelled")),
        onDragCancel: () => t("dndCancelled"),
      },
    }),
    [t],
  );
}

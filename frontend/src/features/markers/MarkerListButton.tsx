import React from "react";
import { Flag, List } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { CanvasMarker } from "@/features/markers/markers";
import { formatCombo } from "@/lib/shortcuts";

/**
 * 工具条上的**标记清单**:这张画布上都有哪些标记、各绑了什么键,点一条就跳过去。
 *
 * 快捷键让熟了之后快,清单让还没熟的时候找得到 —— 只有快捷键的话,一个绑了键却想不起来是
 * 哪个键的标记,和没有这个功能是一样的。
 *
 * **只读,不生产**:这里曾经在清单底下挂过一个「添加标记」。它和左边那枚进入标记模式的按钮
 * 是同一件事的两个入口,而放在清单里的那个还得先展开清单才看得见 —— 更远的一条路,做的却是
 * 旁边那枚按钮已经在做的事。清单回答「有哪些、在哪儿」,加标记是工具条的事。
 */
export function MarkerListButton({
  markers,
  onJump,
}: {
  markers: CanvasMarker[];
  onJump: (marker: CanvasMarker) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <IconButton
          variant="ghost"
          size="icon-sm"
          label={t("markers")}
          className={cn(markers.length > 0 && "text-foreground")}
        >
          <List size={14} />
        </IconButton>
      </PopoverTrigger>
      {/* 高度封顶,内部滚动 —— 六十几个标记不该把弹层撑到屏幕外。 */}
      <MenuContent label={t("markers")} align="end" className="max-h-72 overflow-y-auto">
        {markers.length === 0 ? (
          <p className="px-2 py-3 text-center text-ui-xs text-muted-foreground">{t("markerEmpty")}</p>
        ) : (
          markers.map((marker) => (
            <MenuItem
              key={marker.id}
              icon={<Flag className="text-action" />}
              label={marker.name || t("markerUnnamed")}
              truncate
              shortcut={marker.shortcut ? formatCombo(marker.shortcut) : null}
              onClick={() => {
                setOpen(false);
                onJump(marker);
              }}
            />
          ))
        )}
      </MenuContent>
    </Popover>
  );
}

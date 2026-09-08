import React from "react";
import { Flag } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { CanvasMarker } from "@/features/markers/markers";
import { formatCombo } from "@/lib/shortcuts";

/**
 * 工具条上的**标记清单**:这张画布上都有哪些标记、各绑了什么键,点一条就跳过去。
 *
 * 快捷键让熟了之后快,清单让还没熟的时候找得到 —— 只有快捷键的话,一个绑了键却想不起来是
 * 哪个键的标记,和没有这个功能是一样的。
 */
export function MarkerListButton({
  markers,
  onJump,
  onAdd,
}: {
  markers: CanvasMarker[];
  onJump: (marker: CanvasMarker) => void;
  onAdd: () => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("markers")}
          title={t("markers")}
          className={cn(markers.length > 0 && "text-foreground")}
        >
          <Flag size={14} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-1">
        {markers.length === 0 ? (
          <p className="px-2 py-3 text-center text-ui-xs text-muted-foreground">{t("markerEmpty")}</p>
        ) : (
          // 高度封顶,内部滚动 —— 六十几个标记不该把弹层撑到屏幕外。
          <div className="max-h-64 overflow-y-auto">
            {markers.map((marker) => (
              <button
                key={marker.id}
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ui-xs hover:bg-accent"
                onClick={() => {
                  setOpen(false);
                  onJump(marker);
                }}
              >
                <Flag size={12} className="shrink-0 text-action" />
                <span className="min-w-0 flex-1 truncate">{marker.name || t("markerUnnamed")}</span>
                {marker.shortcut ? (
                  <kbd className="shrink-0 rounded border border-border bg-secondary px-1 font-mono text-ui-2xs leading-4 text-muted-foreground">
                    {formatCombo(marker.shortcut)}
                  </kbd>
                ) : null}
              </button>
            ))}
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 w-full justify-start"
          onClick={() => {
            setOpen(false);
            onAdd();
          }}
        >
          {t("markerAdd")}
        </Button>
      </PopoverContent>
    </Popover>
  );
}

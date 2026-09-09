import React from "react";
import { Flag, Trash2, X } from "lucide-react";
import type { NodeProps } from "@xyflow/react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { ShortcutRecorder } from "@/features/markers/ShortcutRecorder";
import type { CanvasMarker } from "@/features/markers/markers";
import { formatCombo } from "@/lib/shortcuts";
import { useMarkerEditor } from "./MarkerEditorProvider";

export type MarkerNodeData = {
  editable?: boolean;
  marker: CanvasMarker;
  /** 同一张画布上的全部标记 —— 查重要用它(见 markerShortcutConflict)。 */
  markers: CanvasMarker[];
  onChange: (next: CanvasMarker) => void;
  onDelete: (id: string) => void;
};

/**
 * 画布上的标记:一枚**小旗**,不是一个方块。
 *
 * 刻意做得比任何节点都轻(一行高、没有接点、没有运行态):它不参与图的结构,如果长得像节点,
 * 用户第一件想做的事就是从它上面拉一根线出去 —— 而那件事不存在。
 *
 * 配置就开在旗子上,不收进设置页:要绑的那个键属于**这一处位置**,离开这个位置去设置里绑,
 * 用户得先记住自己要绑的是哪一个。
 */
export function MarkerPin({ data, selected }: NodeProps) {
  const t = useI18n();
  const { marker, markers, onChange, onDelete, editable = false } = data as unknown as MarkerNodeData;
  const { open, setOpen, onCloseAutoFocus } = useMarkerEditor();
  React.useEffect(() => { if (!editable) setOpen(false); }, [editable, setOpen]);

  return (
    <Popover open={editable && open} onOpenChange={(next) => editable && setOpen(next)}>
      <PopoverTrigger asChild>
        <button
          type="button"
          tabIndex={editable ? 0 : -1}
          aria-disabled={!editable}
          style={!editable ? { pointerEvents: "none" } : undefined}
          data-marker-pin={marker.id}
          title={t("markerConfigure")}
          className={cn(
            "flex h-7 max-w-[220px] items-center gap-1.5 rounded-full border border-border bg-panel/95 pl-2 pr-2.5 text-ui-xs text-foreground shadow-sm backdrop-blur",
            "hover:border-action",
            selected && "border-action ring-1 ring-action",
          )}
        >
          <Flag size={12} className="shrink-0 text-action" />
          <span className="truncate">{marker.name || t("markerUnnamed")}</span>
          {marker.shortcut ? (
            // 键位就印在旗子上 —— 不然「绑过了没有」只能靠回忆。
            <kbd className="ml-0.5 shrink-0 rounded border border-border bg-secondary px-1 font-mono text-ui-2xs leading-4 text-muted-foreground">
              {formatCombo(marker.shortcut)}
            </kbd>
          ) : null}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 overflow-hidden p-0" onCloseAutoFocus={onCloseAutoFocus} onClick={(event) => event.stopPropagation()}>
        <div className="flex h-11 items-center gap-2 border-b border-border px-3">
          <Flag size={14} className="text-primary" />
          <span className="flex-1 text-ui-xs font-medium">{t("markerConfigure")}</span>
          <Button variant="ghost" size="icon-xs" aria-label={t("close")} onClick={() => setOpen(false)}><X size={14} /></Button>
        </div>
        <div className="grid gap-3 p-3">
          <div className="grid gap-1.5">
            <label className="text-ui-xs text-muted-foreground" htmlFor={`marker-name-${marker.id}`}>
              {t("markerName")}
            </label>
            <Input
              id={`marker-name-${marker.id}`}
              className="h-8 px-2 text-ui-xs"
              value={marker.name}
              maxLength={80}
              onChange={(event) => onChange({ ...marker, name: event.target.value })}
            />
          </div>
          <ShortcutRecorder
            marker={marker}
            markers={markers}
            onChange={(shortcut) => onChange({ ...marker, shortcut })}
          />
        </div>
        <div className="border-t border-border px-3 py-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-center text-destructive hover:text-destructive"
            onClick={() => {
              setOpen(false);
              onDelete(marker.id);
            }}
          >
            <Trash2 size={14} /> {t("markerDelete")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

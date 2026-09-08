import React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { markerShortcutConflict, type CanvasMarker, type MarkerShortcutConflict } from "@/features/markers/markers";
import { comboFromEvent, formatCombo } from "@/lib/shortcuts";

/**
 * 录一个快捷键:点一下,按一下,就绑上了。
 *
 * **撞了就不给绑。** 冲突不是提示,是拒绝 —— 允许配上去再靠"谁先注册谁赢"决定胜负的话,
 * 用户看到的是一个时灵时不灵的键,而他没有任何办法查出来是被谁抢走的。所以录到冲突的组合时
 * 这里什么都不改,只把「它现在归谁」说出来,让用户知道该换一个还是该去解绑那一个。
 *
 * 让用户**按**而不是从下拉里挑:一个组合有三个修饰位,列成下拉是几百条;而"按一下"这个动作
 * 本身就是它将来被使用的方式。
 */
export function ShortcutRecorder({
  marker,
  markers,
  onChange,
}: {
  marker: CanvasMarker;
  markers: CanvasMarker[];
  onChange: (shortcut: string | undefined) => void;
}) {
  const t = useI18n();
  const [recording, setRecording] = React.useState(false);
  const [rejected, setRejected] = React.useState<{ combo: string; conflict: MarkerShortcutConflict } | null>(null);

  const reason = (combo: string, conflict: MarkerShortcutConflict): string => {
    if (conflict.reason === "invalid") return t("markerConflictInvalid");
    if (conflict.reason === "reserved") {
      return t("markerConflictReserved").replace("{combo}", formatCombo(combo)).replace("{owner}", t(conflict.owner));
    }
    return t("markerConflictMarker")
      .replace("{combo}", formatCombo(combo))
      .replace("{name}", conflict.markerName || t("markerUnnamed"));
  };

  return (
    <div className="grid gap-1.5">
      <div className="text-ui-xs text-muted-foreground">{t("markerShortcut")}</div>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          // 录制期间**所有**按键都归它:不 preventDefault 的话,录 ⌘S 会顺手把工作流存一遍。
          onKeyDown={(event) => {
            if (!recording) return;
            event.preventDefault();
            event.stopPropagation();
            if (event.key === "Escape") {
              setRecording(false);
              return;
            }
            const combo = comboFromEvent(event.nativeEvent);
            if (!combo) return; // 只按下了修饰键,继续等
            const conflict = markerShortcutConflict(combo, markers, marker.id);
            if (conflict) {
              setRejected({ combo, conflict });
              return; // 停在录制态:换一个键就行,不用再点一次
            }
            setRejected(null);
            setRecording(false);
            onChange(combo);
          }}
          onClick={() => {
            setRejected(null);
            setRecording(true);
          }}
          onBlur={() => setRecording(false)}
          className={cn(
            "h-8 flex-1 rounded-md border border-field-border bg-field px-2 text-left text-ui-xs",
            recording && "border-action text-action",
            !recording && !marker.shortcut && "text-muted-foreground",
          )}
        >
          {recording
            ? t("markerShortcutRecording")
            : marker.shortcut
              ? formatCombo(marker.shortcut)
              : t("markerShortcutNone")}
        </button>
        {marker.shortcut ? (
          <Button
            variant="secondary"
            size="icon-sm"
            aria-label={t("markerShortcutClear")}
            title={t("markerShortcutClear")}
            onClick={() => {
              setRejected(null);
              setRecording(false);
              onChange(undefined);
            }}
          >
            <X size={14} />
          </Button>
        ) : null}
      </div>
      {rejected ? (
        <p role="alert" className="text-ui-xs text-destructive">
          {reason(rejected.combo, rejected.conflict)}
        </p>
      ) : null}
    </div>
  );
}

import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { Loader2, Scissors, Volume2, VolumeX } from "lucide-react";

import { type BoardItem } from "@/api/client";
import { Input } from "@/components/ui/input";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/**
 * 「剪一段」面板:定起止、要不要声音。
 *
 * **原素材不动**,产出是一份新素材落到一个新节点上 —— 画板上的每一步都该是可回头的,
 * 就地改会让上一版消失,而「上一版」往往正是几分钟后想比对的那个。
 *
 * 这里不做时间线该做的事(多段拼接、转场、调色)。那是编辑器,而画板上的剪辑是**探索期的
 * 动作**:先截出想要的那几秒。硬把时间线搬上画布,得到的是一个两边都不好用的东西。
 */
export function TrimComposer({
  item,
  duration,
  busy,
  onTrim,
}: {
  item: BoardItem;
  /** 素材总时长(秒)。拿不到就不限制上界 —— 猜一个反而会把长素材截短。 */
  duration?: number;
  busy: boolean;
  onTrim: (input: { start: number; end: number; mute: boolean }) => void;
}) {
  const t = useI18n();
  const [start, setStart] = React.useState("0");
  const [end, setEnd] = React.useState(duration ? String(Math.round(duration * 10) / 10) : "");
  const [mute, setMute] = React.useState(false);
  //: 点下去立刻转、落地就停(**失败也要停** —— 否则那个圈会一直转下去)。见 useSubmitting。
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const from = Number(start);
  const to = Number(end);
  //: 范围不对时按钮就该是灰的 —— 让后端去拒的话,用户要等一次往返才知道自己填错了。
  const ok = Number.isFinite(from) && Number.isFinite(to) && from >= 0 && to > from;

  const send = () => {
    if (!ok || working) return;
    run(() => onTrim({ start: from, end: to, mute }));
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={12}>
      <div className="nodrag nopan nowheel flex w-[420px] items-center gap-2 rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        <Scissors size={13} className="shrink-0 text-muted-foreground" />
        <label className="flex items-center gap-1 text-ui-2xs text-muted-foreground">
          {t("boardTrimFrom")}
          <Input
            value={start}
            onChange={(event) => setStart(event.target.value)}
            inputMode="decimal"
            className="h-7 w-16 px-1.5 text-center text-ui-xs"
            aria-label={t("boardTrimStartLabel")}
          />
        </label>
        <label className="flex items-center gap-1 text-ui-2xs text-muted-foreground">
          {t("boardTrimTo")}
          <Input
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            inputMode="decimal"
            placeholder={duration ? String(Math.round(duration * 10) / 10) : t("boardTrimSeconds")}
            className="h-7 w-16 px-1.5 text-center text-ui-xs"
            aria-label={t("boardTrimEndLabel")}
          />
        </label>
        <span className="text-ui-2xs text-muted-foreground">{t("boardTrimSeconds")}</span>

        <button
          type="button"
          aria-pressed={mute}
          title={t(mute ? "boardDropSound" : "boardKeepSound")}
          onClick={() => setMute((on) => !on)}
          className={cn(
            "grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full transition-colors",
            mute ? "text-foreground" : "text-muted-foreground/60 hover:text-foreground",
          )}
        >
          {mute ? <VolumeX size={13} /> : <Volume2 size={13} />}
        </button>

        <button
          type="button"
          disabled={!ok || working}
          onClick={send}
          className={cn(
            "ml-auto flex h-7 shrink-0 items-center gap-1 rounded-full px-3 text-ui-2xs transition-colors",
            !ok || working
              ? "cursor-not-allowed bg-secondary text-muted-foreground"
              : "cursor-pointer bg-primary text-primary-foreground hover:opacity-90",
          )}
        >
          {working ? <Loader2 size={12} className="animate-spin" /> : <Scissors size={12} />} {t("boardTrimSubmit")}
        </button>
      </div>
    </NodeToolbar>
  );
}

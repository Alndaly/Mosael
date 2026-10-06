import React from "react";
import { ChevronDown, Loader2, Proportions } from "lucide-react";

import type { Sequence } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/** 常用画幅。别的尺寸(比如从素材建出来的序列)照样显示,只是没有哪一档亮着。 */
export const ASPECT_PRESETS = [
  { label: "16:9", width: 1920, height: 1080 },
  { label: "9:16", width: 1080, height: 1920 },
  { label: "1:1", width: 1080, height: 1080 },
  { label: "4:5", width: 1080, height: 1350 },
] as const;

/** 底层画面和画幅比例不一致时怎么铺(后端 SetSequenceReframeRequest 收的就是这三个)。 */
export const FILL_MODES = ["cover", "contain", "blur"] as const;
export type FillMode = (typeof FILL_MODES)[number];

const FILL_LABELS: Record<FillMode, MessageKey> = {
  cover: "fillCover",
  contain: "fillContain",
  blur: "fillBlur",
};

const SECTION_LABEL = "text-ui-xs font-medium text-muted-foreground";
//: 剪辑台自己那套分段(.editor-mode-tab,见 editor.css),和左栏、检查器页签同一个长相。
const OPTIONS = "grid auto-cols-fr grid-flow-col gap-1";
const option = (active: boolean) =>
  cn("editor-mode-tab gap-1 px-1 disabled:cursor-default disabled:opacity-50", active && "is-active");

export function fillModeOf(sequence: Sequence): FillMode {
  const raw = (sequence.reframe as { fill_mode?: unknown } | null)?.fill_mode;
  return FILL_MODES.find((mode) => mode === raw) ?? "cover";
}

/**
 * 时间线工具栏上的「序列设置」:画幅和填充方式。它们属于整条序列,不属于哪个片段,所以不在
 * 右栏检查器里(检查器只在选中片段时出现)。改一下就提交一次,和轨道头上的开关一样。
 */
export function SequenceSettings({
  sequence,
  onReframe,
  pending = false,
}: {
  sequence: Sequence;
  onReframe: (width: number, height: number, fillMode: FillMode) => void;
  pending?: boolean;
}) {
  const t = useI18n();
  //: 改的请求在路上时,点的那一档转圈(别的几档点不了):不然一排选项只是一起变灰,看不出点没点上
  const [picked, setPicked] = React.useState("");
  const busy = (key: string) => pending && picked === key;
  const fill = fillModeOf(sequence);
  const preset = ASPECT_PRESETS.find((one) => one.width === sequence.width && one.height === sequence.height);
  const size = `${sequence.width}×${sequence.height}`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm">
          <Proportions size={14} />
          {t("sequenceSettings")}
          <span className="tabular-nums text-muted-foreground">{preset?.label ?? size}</span>
          <ChevronDown size={12} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="grid w-72 gap-4 p-3">
        <div className="grid gap-0.5">
          <strong className="text-ui-sm font-semibold">{t("sequenceSettings")}</strong>
          <span className="timecode text-ui-xs text-muted-foreground">
            {size} · {sequence.fps}fps
          </span>
        </div>
        <div className="grid gap-2">
          <span className={SECTION_LABEL}>{t("reframeTitle")}</span>
          <div className={OPTIONS} role="radiogroup" aria-label={t("reframeTitle")}>
            {ASPECT_PRESETS.map((one) => (
              <button
                key={one.label}
                type="button"
                role="radio"
                aria-checked={one === preset}
                aria-busy={busy(one.label) || undefined}
                disabled={pending}
                className={cn(option(one === preset), "tabular-nums")}
                onClick={() => {
                  if (one === preset) return;
                  setPicked(one.label);
                  onReframe(one.width, one.height, fill);
                }}
              >
                {busy(one.label) && <Loader2 size={12} className="animate-mosael-spin" />}
                {one.label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid gap-2">
          <span className={SECTION_LABEL}>{t("reframeFill")}</span>
          <div className={OPTIONS} role="radiogroup" aria-label={t("reframeFill")}>
            {FILL_MODES.map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={mode === fill}
                aria-busy={busy(mode) || undefined}
                disabled={pending}
                className={option(mode === fill)}
                onClick={() => {
                  if (mode === fill) return;
                  setPicked(mode);
                  onReframe(sequence.width, sequence.height, mode);
                }}
              >
                {busy(mode) && <Loader2 size={12} className="animate-mosael-spin" />}
                {t(FILL_LABELS[mode])}
              </button>
            ))}
          </div>
          <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("reframeFillHint")}</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

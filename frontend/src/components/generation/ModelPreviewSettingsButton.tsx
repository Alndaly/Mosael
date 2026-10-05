import React from "react";
import { Eye, EyeOff } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { LocalNsfwRow, useLocalNsfw } from "@/components/generation/LocalNsfw";
import {
  NSFW_MODES,
  PREVIEW_LEVELS,
  useModelPreviewSettings,
  type NsfwMode,
  type PreviewLevel,
} from "@/components/generation/modelPreviewSettings";
import { IconButton } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const LEVEL_LABELS = {
  clear: "modelPreviewLevelClear",
  light: "modelPreviewLevelLight",
  heavy: "modelPreviewLevelHeavy",
  hidden: "modelPreviewLevelHidden",
} as const satisfies Record<PreviewLevel, string>;
const NSFW_LABELS = {
  show: "modelPreviewNsfwShow",
  blur: "modelPreviewNsfwBlur",
  hidden: "modelPreviewNsfwHidden",
} as const satisfies Record<NsfwMode, string>;

/**
 * 模型预览图的两组设置(见 modelPreviewSettings):模型库的工具条、工作台的模型库面板上各一颗,改的是同一份。
 * 不是默认值时按钮点亮,一眼看得出「这台电脑上的预览图被藏过」。面板底下是本机识别那一行;按钮挂着的时候顺带盯着识别的
 * 进度(识别完了让模型库重新列一遍,见 useLocalNsfw)。
 */
export function ModelPreviewSettingsButton({
  compact = false,
}: {
  /** 小一号(工作台面板的标题行上)。 */
  compact?: boolean;
}) {
  const t = useI18n();
  const [settings, setSettings] = useModelPreviewSettings();
  useLocalNsfw();
  const covered = settings.level !== "clear";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <IconButton
          variant="outline"
          size={compact ? "icon-sm" : "default"}
          aria-haspopup="dialog"
          className={cn("text-muted-foreground", !compact && "px-3",
                        covered && "border-primary/40 bg-accent text-primary hover:bg-accent hover:text-primary")}
          label={t("modelPreviewSettings")}
          hint={t("modelPreviewSettingsHint")}
        >
          {covered ? <EyeOff size={13} /> : <Eye size={13} />}
        </IconButton>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label={t("modelPreviewSettings")} className="grid gap-3.5">
        <Choice
          label={t("modelPreviewLevel")}
          value={settings.level}
          options={PREVIEW_LEVELS.map((value) => ({ value, label: t(LEVEL_LABELS[value]) }))}
          onChange={(level) => setSettings({ ...settings, level })}
        />
        <Choice
          label={t("modelPreviewNsfw")}
          value={settings.nsfw}
          options={NSFW_MODES.map((value) => ({ value, label: t(NSFW_LABELS[value]) }))}
          onChange={(nsfw) => setSettings({ ...settings, nsfw })}
        />
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("modelPreviewSettingsNote")}</p>
        <LocalNsfwRow />
      </PopoverContent>
    </Popover>
  );
}

/** 一组单选:一排分段按钮。 */
function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const id = React.useId();
  return (
    <div className="grid gap-1.5">
      <span id={id} className="text-ui-xs font-medium text-foreground">{label}</span>
      <div role="radiogroup" aria-labelledby={id} className="flex flex-wrap gap-1 rounded-md border border-border p-1">
        {options.map((one) => (
          <button
            key={one.value}
            type="button"
            role="radio"
            aria-checked={value === one.value}
            className={cn(
              "h-7 flex-1 cursor-pointer whitespace-nowrap rounded px-2 text-ui-xs text-muted-foreground hover:bg-secondary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              value === one.value && "bg-accent font-medium text-primary hover:bg-accent",
            )}
            onClick={() => onChange(one.value)}
          >
            {one.label}
          </button>
        ))}
      </div>
    </div>
  );
}

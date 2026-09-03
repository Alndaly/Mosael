import React from "react";
import { ImageIcon, MonitorCog, Moon, RotateCcw, Sun, Upload, X } from "lucide-react";
import { toast } from "sonner";

import { BACKGROUND_PRESETS, type BackgroundKind, compressImageFile, useAppearance } from "@/app/appearance";
import { useCustomCss } from "@/app/customCss";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

export function AppearanceSection() {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  return (
    <SettingsGroup title={t("settingsAppearance")} description={t("settingsAppearanceDesc")}>
      <SettingsRow label={t("settingsTheme")} description={t("settingsThemeDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "light" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("light")}
          >
            <Sun size={13} /> {t("themeLight")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "dark" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("dark")}
          >
            <Moon size={13} /> {t("themeDark")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "system" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("system")}
          >
            <MonitorCog size={13} /> {t("themeSystem")}
          </button>
        </div>
      </SettingsRow>
      <SettingsRow label={t("settingsLanguage")} description={t("settingsLanguageDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", locale === "zh-CN" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setLocale("zh-CN")}
          >
            {t("languageZh")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", locale === "en-US" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setLocale("en-US")}
          >
            {t("languageEn")}
          </button>
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}

/** 用户自定义 CSS:一个磁盘上的文件,存盘即生效。文件住在客户端自己的存储里
    (`<userData>/custom.css`),不在后端的数据目录 —— 后端可能压根不在这台机器上。
    应用只读不写:内容始终由用户在自己的编辑器里改。 */
export function CustomCssSection() {
  const t = useI18n();
  const custom = useCustomCss();

  if (!custom.supported) {
    return (
      <SettingsGroup title={t("customCssTitle")} description={t("customCssDesktopOnly")} />
    );
  }

  const lines = custom.css.trim() ? custom.css.trimEnd().split("\n").length : 0;

  return (
    <SettingsGroup title={t("customCssTitle")} description={t("customCssDesc")}>
      <SettingsRow label={t("customCssFile")} description={t("customCssFileDesc")}>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => void custom.open()}>
            {t("customCssOpen")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void custom.reveal()}>
            {t("customCssReveal")}
          </Button>
        </div>
      </SettingsRow>
      <SettingsBlock>
        {/* 路径常驻显示:自定义 CSS 的第一个问题永远是「那个文件到底在哪」,而这个目录
            在 mac 和 Windows 上长得完全不一样,让用户照着文档拼路径不如直接把它印出来。 */}
        <code className="block overflow-x-auto whitespace-nowrap rounded-sm bg-panel-inset px-2 py-1.5 text-ui-2xs text-muted-foreground">
          {custom.path || "—"}
        </code>
        <p className="text-ui-2xs text-muted-foreground">
          {lines > 0 ? t("customCssActive").replace("{lines}", String(lines)) : t("customCssEmpty")}
        </p>
      </SettingsBlock>
      <SettingsRow label={t("customCssEnabled")} description={t("customCssEnabledDesc")}>
        <Switch checked={custom.enabled} onCheckedChange={custom.setEnabled} aria-label={t("customCssEnabled")} />
      </SettingsRow>
    </SettingsGroup>
  );
}

/** 自定义外观:整体背景(渐变预设 / 上传图片)+ 表面透明度、磨玻璃模糊、背景压暗。
    全部即时预览,存 localStorage(逐设备)。无背景时应用保持原不透明外观。 */
export function BackgroundSection() {
  const t = useI18n();
  const appearance = useAppearance();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const active = appearance.kind !== "none" && !(appearance.kind === "image" && !appearance.image);

  const pickImage = async (file: File | undefined) => {
    if (!file) return;
    try {
      appearance.setImage(await compressImageFile(file));
    } catch (error) {
      toast.error((error as Error).message);
    }
  };
  const chooseKind = (kind: BackgroundKind) => {
    if (kind === "image" && !appearance.image) fileRef.current?.click();
    else appearance.update({ kind });
  };

  return (
    <SettingsGroup title={t("appearanceBgTitle")} description={t("appearanceBgDesc")}>
      <SettingsRow label={t("appearanceBgSource")} description={t("appearanceBgSourceDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          {(["none", "preset", "image"] as BackgroundKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", appearance.kind === kind && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => chooseKind(kind)}
            >
              {kind === "none" ? t("appearanceBgNone") : kind === "preset" ? t("appearanceBgPreset") : t("appearanceBgImage")}
            </button>
          ))}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(event) => {
              void pickImage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </SettingsRow>

      {appearance.kind === "preset" && (
        <SettingsBlock>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
            {BACKGROUND_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={cn(
                  "relative h-14 cursor-pointer overflow-hidden rounded-lg border border-border bg-cover bg-center transition-[box-shadow,transform] duration-[120ms] hover:-translate-y-px [&>span]:absolute [&>span]:bottom-1.5 [&>span]:left-[7px] [&>span]:text-ui-xs [&>span]:font-semibold [&>span]:text-white [&>span]:[text-shadow:0_1px_3px_rgba(0,0,0,0.55)]",
                  appearance.preset === preset.id && "border-primary shadow-[0_0_0_2px_var(--primary)]",
                )}
                style={{ backgroundImage: preset.css }}
                onClick={() => appearance.update({ preset: preset.id })}
              >
                <span>{preset.label}</span>
              </button>
            ))}
          </div>
        </SettingsBlock>
      )}

      {appearance.kind === "image" && (
        <SettingsBlock>
          <div className="flex items-center gap-3">
            {appearance.image ? (
              <div className="h-[72px] w-32 shrink-0 rounded-lg border border-border bg-cover bg-center" style={{ backgroundImage: `url(${appearance.image})` }} />
            ) : (
              <div className="flex h-[72px] w-32 shrink-0 items-center gap-1.5 rounded-lg border border-dashed border-border-strong px-2.5 text-ui-xs text-muted-foreground">
                <ImageIcon size={16} /> {t("appearanceBgNoImage")}
              </div>
            )}
            <div className="flex flex-col items-start gap-1.5">
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload size={13} /> {appearance.image ? t("appearanceBgReplace") : t("appearanceBgUpload")}
              </Button>
              {appearance.image && (
                <Button variant="ghost" size="sm" onClick={() => appearance.clearImage()}>
                  <X size={13} /> {t("appearanceBgRemove")}
                </Button>
              )}
            </div>
          </div>
        </SettingsBlock>
      )}

      {active && (
        <>
          <SliderRow
            label={t("appearanceOpacity")}
            value={appearance.surfaceOpacity}
            min={0.35}
            max={1}
            step={0.01}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => appearance.update({ surfaceOpacity: v })}
          />
          <SliderRow
            label={t("appearanceBlur")}
            value={appearance.blur}
            min={0}
            max={32}
            step={1}
            format={(v) => `${Math.round(v)}px`}
            onChange={(v) => appearance.update({ blur: v })}
          />
          <SliderRow
            label={t("appearanceDim")}
            value={appearance.dim}
            min={0}
            max={0.75}
            step={0.01}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => appearance.update({ dim: v })}
          />
        </>
      )}

      <SettingsRow label={t("appearanceReset")} description={t("appearanceResetDesc")}>
        <Button variant="outline" size="sm" onClick={() => appearance.reset()}>
          <RotateCcw size={13} /> {t("appearanceReset")}
        </Button>
      </SettingsRow>
    </SettingsGroup>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}) {
  return (
    <SettingsRow label={label}>
      <div className="flex min-w-[220px] items-center gap-2.5">
        <Slider value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} />
        <span className="w-[42px] text-right text-xs tabular-nums text-muted-foreground">{format(value)}</span>
      </div>
    </SettingsRow>
  );
}

/** 本地/远程服务器切换,与登录页复用同一 ServerPicker(探活 + 强连兜底 + 整页重载)。 */

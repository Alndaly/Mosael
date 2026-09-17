import React from "react";

import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { MessageKey } from "@/app/messages";
import { runtimeState, type SpeechVoice } from "@/features/voice/useSpeechVoice";
import { cn } from "@/lib/utils";

/** 带小标签的紧凑表单格:下拉全长一个样,没有标签就分不清「音色」「语速」「发音人 B」谁是谁 ——
    标签贴在控件上方而不是靠占位符。 */
export function VoiceField({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid min-w-0 content-start gap-1.5", className)}>
      <span className="text-ui-xs font-medium leading-snug text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

/** 一行控件。**容器宽度是会变的**(剪辑台左栏可拖、窗口可缩),所以行按内容需要换行,
    不按写死的列数排 —— 实测 250px 下 `grid-cols-[1fr_1fr_88px]` 把引擎那一格压到 65px,
    选项读成「F5…」「Fi…」。**读不出选项的选择器等于没有这个功能。** */
export function FieldRow({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-start gap-1.5", className)}>{children}</div>;
}

//: 一格下拉挤到什么宽度就该换行了。引擎名(「Fish Speech S2 Pro · 未就绪」)最长,给得多些。
export const FIELD = "min-w-[9rem] flex-1";
const FIELD_WIDE = "min-w-[10.5rem] flex-1";
//: 语速永远是「1.25×」这种两三个字符,给固定窄宽,不参与瓜分。
export const FIELD_SPEED = "w-[76px] shrink-0";

export function VoicePicker({
  value,
  onChange,
  choices,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  choices: { value: string; label: string }[];
  ariaLabel: string;
}) {
  // 一个引擎挂几十个音色是常态 —— 超过阈值 OptionPicker 自己换成可搜索的那一版。
  return <OptionPicker value={value} onChange={onChange} options={choices} ariaLabel={ariaLabel} className="w-full min-w-0" />;
}

export function SpeedPicker({ value, onChange, ariaLabel }: { value: number; onChange: (value: number) => void; ariaLabel: string }) {
  return (
    <Select value={String(value)} onValueChange={(next) => onChange(Number(next))}>
      <SelectTrigger className="w-full min-w-0" aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {[0.75, 1, 1.25, 1.5, 2].map((option) => (
          <SelectItem key={option} value={String(option)}>
            {option}×
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

//: 本地引擎名后面缀什么。装好了不缀 —— 只有异常才值得占地方。
const RUNTIME_SUFFIX: Record<ReturnType<typeof runtimeState>, MessageKey | null> = {
  checking: "runtimeChecking",
  ready: null,
  unready: "voiceCloneEngineUnready",
};

/** 引擎 → (克隆引擎 + 音色 | 发音人 | 手填 id) → 语速。状态全在 `voice` 里。 */
export function SpeechVoiceFields({ voice }: { voice: SpeechVoice }) {
  const t = useI18n();
  const { engine, activeEngine, voiceChoices } = voice;
  const runtimeSuffix = (runtime: Parameters<typeof runtimeState>[0]) => {
    const key = RUNTIME_SUFFIX[runtimeState(runtime)];
    return key ? ` · ${t(key)}` : "";
  };
  return (
    <div className="grid gap-3">
      <VoiceField label={t("voiceEngine")}>
        <Select value={engine} onValueChange={voice.setEngine}>
          <SelectTrigger className="w-full min-w-0" aria-label={t("voiceEngine")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {voice.engines.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </VoiceField>

      {/* 本地克隆:**音色也在这里选**,和远端引擎的发音人同一个位置 ——
          此前唯一的选法是去下面的音色库点卡片,没点之前悄悄用第一个。 */}
      {engine === "clone" && (
        <FieldRow>
          {/* 没装好的照样列出来但标明白,而不是藏起来让人猜为什么少了一个。 */}
          <VoiceField label={t("voicePanelCloneEngine")} className={FIELD_WIDE}>
            <Select value={voice.cloneEngine} onValueChange={voice.setCloneEngine}>
              <SelectTrigger className="w-full min-w-0" aria-label={t("voicePanelCloneEngine")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {voice.runtimes.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.label}
                    {/* 「还没测过」不能显示成「未装好」—— 那是拿一个未知冒充结论。 */}
                    {runtimeSuffix(item)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </VoiceField>
          {/* 音色和语速**一起**换行:语速只有「1.25×」那么宽,单独甩到下一行最难看。 */}
          <FieldRow className="min-w-[12rem] flex-1 flex-nowrap">
            <VoiceField label={t("voiceLibraryPick")} className="min-w-0 flex-1">
              {voice.library.length > 0 ? (
                <OptionPicker
                  value={voice.voiceId}
                  onChange={voice.setVoiceId}
                  options={voice.library.map((item) => ({ value: item.id, label: item.name }))}
                  ariaLabel={t("voiceLibraryPick")}
                  placeholder={t("voiceLibraryPickPlaceholder")}
                  className="w-full min-w-0"
                />
              ) : (
                <Input value="" disabled readOnly aria-label={t("voiceLibraryPick")} placeholder={t("voiceLibraryPickEmpty")} />
              )}
            </VoiceField>
            {voice.speedSupported && (
              <VoiceField label={t("voiceSpeed")} className={FIELD_SPEED}>
                <SpeedPicker value={voice.speed} onChange={voice.setSpeed} ariaLabel={t("voiceSpeed")} />
              </VoiceField>
            )}
          </FieldRow>
        </FieldRow>
      )}

      {engine !== "clone" && voiceChoices.length > 0 && (
        <FieldRow className="flex-nowrap">
          {/* 语速藏起来时音色独占一行 —— flex-1 自然铺满,不必另给宽度。 */}
          <VoiceField label={t("voiceEngineVoice")} className="min-w-0 flex-1">
            <VoicePicker value={voice.engineVoice} onChange={voice.setEngineVoice} choices={voiceChoices} ariaLabel={t("voiceEngineVoice")} />
          </VoiceField>
          {voice.speedSupported && (
            <VoiceField label={t("voiceSpeed")} className={FIELD_SPEED}>
              <SpeedPicker value={voice.speed} onChange={voice.setSpeed} ariaLabel={t("voiceSpeed")} />
            </VoiceField>
          )}
        </FieldRow>
      )}

      {/* 目录拉不到、需要手填发音人 id 的引擎。两样都没有就**整行不渲染** ——
          此前这里会剩下一个 76px 宽、孤零零的语速下拉。 */}
      {engine !== "clone" && voiceChoices.length === 0 && (activeEngine?.needs_voice_id || voice.speedSupported) && (
        <FieldRow className="flex-nowrap">
          {activeEngine?.needs_voice_id && (
            <VoiceField label={t("voiceEngineVoiceId")} className="min-w-0 flex-1">
              <Input
                className="min-w-0"
                value={voice.engineVoiceChoice}
                placeholder={t("voiceEngineVoiceIdHint")}
                aria-label={t("voiceEngineVoiceId")}
                onChange={(event) => voice.setEngineVoice(event.target.value)}
              />
            </VoiceField>
          )}
          {voice.speedSupported && (
            <VoiceField label={t("voiceSpeed")} className={activeEngine?.needs_voice_id ? FIELD_SPEED : "min-w-0 flex-1"}>
              <SpeedPicker value={voice.speed} onChange={voice.setSpeed} ariaLabel={t("voiceSpeed")} />
            </VoiceField>
          )}
        </FieldRow>
      )}

      {engine !== "clone" && voiceChoices.length === 0 && activeEngine?.needs_voice_id && !voice.engineVoiceChoice.trim() && (
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("voiceNeedEngineVoice")}</p>
      )}
      {engine !== "clone" && activeEngine?.note && (
        <p className={cn("m-0 text-ui-xs leading-[1.45] text-muted-foreground", activeEngine.ready === false && "text-destructive")}>
          {activeEngine.note}
        </p>
      )}
    </div>
  );
}

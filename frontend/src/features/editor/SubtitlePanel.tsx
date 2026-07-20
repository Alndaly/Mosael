import React from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Languages, Loader2, Plus, Sparkles, Trash2, Type } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { readSubtitleStyle, SUBTITLE_FONTS, type SubtitleStyle } from "@/features/editor/subtitleStyle";

import { translateTexts, type Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { useEditorStore } from "@/stores/editorStore";

const TRANSLATE_LANGS = ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"] as const;

/**
 * Subtitle list editor (老版 mibu-video 的字幕可见入口): every text clip on
 * every subtitle track, in timeline order — click the timecode to seek, edit
 * the text inline, delete, or add a new one at the playhead.
 */
export function SubtitlePanel({
  sequence,
  onSetText,
  onAddSubtitle,
  onGenerate,
  generating,
  style,
  onPreviewStyle,
  onSetStyle,
  onDeleteClip,
}: {
  sequence: Sequence;
  onSetText: (clipId: string, text: string) => void;
  onAddSubtitle: () => void;
  onGenerate?: () => void;
  generating?: boolean;
  style?: Record<string, unknown>;
  /** Fires continuously while a control is being dragged — preview only, never persisted. */
  onPreviewStyle?: (style: Record<string, unknown>) => void;
  onSetStyle?: (style: Record<string, unknown>) => void;
  onDeleteClip: (clipId: string) => void;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const selectClip = useEditorStore((state) => state.selectClip);

  const subtitles = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((track) => track.kind === "subtitle")
        .flatMap((track) => track.clips ?? [])
        .sort((a, b) => a.timeline_start - b.timeline_start),
    [sequence],
  );

  return (
    <div className="sub-panel">
      {onSetStyle && (
        <SubtitleStyleControls style={style} onPreviewStyle={onPreviewStyle} onSetStyle={onSetStyle} />
      )}
      <div className="sub-list">
        {subtitles.length === 0 && (
          <div className="empty-inline">
            <Type size={16} />
            {t("subtitleEmptyBody")}
          </div>
        )}
        {subtitles.map((clip) => {
          const active = playhead >= clip.timeline_start && playhead < clipEnd(clip);
          return (
            <div key={clip.id} className={active ? "sub-item active" : "sub-item"}>
              <div className="sub-item-head">
                <button
                  type="button"
                  className="ts-time timecode ts-time-btn"
                  title={t("seekToSubtitle")}
                  onClick={() => {
                    useEditorStore.getState().setPlayhead(clip.timeline_start);
                    selectClip(clip.id);
                  }}
                >
                  {formatTimecode(clip.timeline_start)} – {formatTimecode(clipEnd(clip))}
                </button>
                <button
                  type="button"
                  className="sub-delete"
                  title={t("deleteClip")}
                  aria-label={t("deleteClip")}
                  onClick={() => onDeleteClip(clip.id)}
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <textarea
                key={`sub-${clip.id}-${clip.text_override}`}
                className="subtitle-input"
                rows={2}
                defaultValue={clip.text_override ?? ""}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value && value !== clip.text_override) onSetText(clip.id, value);
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="sub-footer">
        {onGenerate && (
          <button type="button" className="ts-tool" title={t("subtitleGenerateHint")} onClick={onGenerate} disabled={generating}>
            {generating ? <Loader2 size={12} className="spin" /> : <Sparkles size={12} />} {t("subtitleGenerate")}
          </button>
        )}
        <button type="button" className="ts-tool" title={t("addSubtitleAtPlayhead")} onClick={onAddSubtitle}>
          <Plus size={12} /> {t("addSubtitleAtPlayhead")}
        </button>
        {subtitles.length > 0 && <SubtitleTranslate subtitles={subtitles} onSetText={onSetText} />}
      </div>
    </div>
  );
}

/** 一键翻译:把整轨字幕批量译成目标语言(Google 免费),就地替换文本(可撤销)。 */
function SubtitleTranslate({
  subtitles,
  onSetText,
}: {
  subtitles: { id: string; text_override?: string | null }[];
  onSetText: (clipId: string, text: string) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [lang, setLang] = React.useState<string>("en");

  const run = useMutation({
    mutationFn: async () => {
      const items = subtitles.filter((clip) => (clip.text_override ?? "").trim());
      const { translations } = await translateTexts(
        items.map((clip) => clip.text_override ?? ""),
        lang,
      );
      let applied = 0;
      translations.forEach((translated, i) => {
        const original = items[i].text_override ?? "";
        if (translated && translated !== original) {
          onSetText(items[i].id, translated);
          applied += 1;
        }
      });
      return applied;
    },
    onSuccess: (applied) => {
      setOpen(false);
      toast.success(t("subtitleTranslateDone").replace("{n}", String(applied)));
    },
    onError: (error: Error) => toast.error(t("subtitleTranslateFailed"), { description: error.message }),
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="ts-tool" title={t("subtitleTranslate")}>
          <Languages size={12} /> {t("subtitleTranslate")}
        </button>
      </PopoverTrigger>
      <PopoverContent className="sub-translate-pop" align="end">
        <strong>{t("subtitleTranslate")}</strong>
        <label className="sub-translate-row">
          <span>{t("subtitleTranslateTo")}</span>
          <Select value={lang} onValueChange={setLang}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TRANSLATE_LANGS.map((code) => (
                <SelectItem key={code} value={code}>
                  {t(("lang_" + code.replace("-", "_")) as never)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <Button size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? <Loader2 size={13} className="spin" /> : <Languages size={13} />}
          {t("subtitleTranslateApply").replace("{n}", String(subtitles.length))}
        </Button>
        <small className="sub-translate-note">{t("subtitleTranslateNote")}</small>
      </PopoverContent>
    </Popover>
  );
}

function SubtitleStyleControls({
  style,
  onPreviewStyle,
  onSetStyle,
}: {
  style?: Record<string, unknown>;
  onPreviewStyle?: (style: Record<string, unknown>) => void;
  onSetStyle: (style: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const s = readSubtitleStyle(style);
  const patch = (next: Partial<SubtitleStyle>) => onSetStyle({ ...s, ...next });
  // Sliders are controlled off `s` (which is the draft while one is in flight) so the value
  // readout and the monitor both track the drag; only the release writes to the server.
  const preview = (next: Partial<SubtitleStyle>) => onPreviewStyle?.({ ...s, ...next });

  return (
    <div className="sub-style">
      <button type="button" className="sub-style-head" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} {t("subtitleStyle")}
      </button>
      {open && (
        <div className="sub-style-body">
          <label className="sub-style-row">
            <span>{t("subFont")}</span>
            <Select value={s.font_family} onValueChange={(v) => patch({ font_family: v })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUBTITLE_FONTS.map((font) => (
                  <SelectItem key={font.value} value={font.value} style={{ fontFamily: font.value }}>
                    {t(font.labelKey as Parameters<typeof t>[0])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="sub-style-row">
            <span>{t("subFontSize")}</span>
            <Slider
              min={10}
              max={120}
              step={1}
              value={[s.font_size]}
              onValueChange={([v]) => preview({ font_size: v })}
              onValueCommit={([v]) => patch({ font_size: v })}
            />
            <em>{Math.round(s.font_size)}</em>
          </label>
          <label className="sub-style-row">
            <span>{t("subColor")}</span>
            <input type="color" value={s.color} onChange={(e) => patch({ color: e.target.value })} />
          </label>
          <label className="sub-style-row">
            <span>{t("subBg")}</span>
            <input type="color" value={s.bg_color} onChange={(e) => patch({ bg_color: e.target.value })} />
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={[s.bg_opacity]}
              onValueChange={([v]) => preview({ bg_opacity: v })}
              onValueCommit={([v]) => patch({ bg_opacity: v })}
            />
          </label>
          <label className="sub-style-row">
            <span>{t("subBold")}</span>
            <Switch checked={s.bold} onCheckedChange={(v) => patch({ bold: v })} />
          </label>
          <label className="sub-style-row">
            <span>{t("subPosition")}</span>
            <Select value={s.position} onValueChange={(v) => patch({ position: v as SubtitleStyle["position"] })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="bottom">{t("subPosBottom")}</SelectItem>
                <SelectItem value="center">{t("subPosCenter")}</SelectItem>
                <SelectItem value="top">{t("subPosTop")}</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="sub-style-row">
            <span>{t("subOffset")}</span>
            <Slider
              min={0}
              max={45}
              step={1}
              value={[s.offset]}
              onValueChange={([v]) => preview({ offset: v })}
              onValueCommit={([v]) => patch({ offset: v })}
            />
            <em>{Math.round(s.offset)}%</em>
          </label>
        </div>
      )}
    </div>
  );
}

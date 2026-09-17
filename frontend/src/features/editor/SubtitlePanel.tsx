import React from "react";
import { useMutation } from "@tanstack/react-query";
import { AudioLines, ChevronDown, ChevronRight, Languages, Loader2, Plus, Sparkles, Trash2, Type, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { OptionPicker } from "@/components/ui/option-picker";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { readSubtitleStyle, SUBTITLE_FONTS, TRANSLATE_LANGS, type SubtitleStyle } from "@/features/editor/subtitleStyle";
import { uploadedFontStack } from "@/features/editor/FontFaces";
import type { Font } from "@/api/client";

import { translateTexts, type Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { PILL } from "@/features/editor/pill";
import { SaveToNote } from "@/features/notes/SaveToNote";
import { useNoteStrings } from "@/features/notes/strings";
import { noteExportVariants, type NoteExportLine } from "@/features/editor/noteExport";
import { useEditorStore } from "@/stores/editorStore";
import { cn } from "@/lib/utils";


/**
 * Subtitle list editor (沿用前身项目的字幕可见入口): every text clip on
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
  onApplyTexts,
  fonts,
  onUploadFont,
  onDeleteFont,
  uploadingFont,
  onPreviewStyle,
  onSetStyle,
  onDeleteClip,
  onDub,
}: {
  sequence: Sequence;
  onSetText: (clipId: string, text: string) => void;
  onAddSubtitle: () => void;
  onGenerate?: () => void;
  generating?: boolean;
  style?: Record<string, unknown>;
  onApplyTexts?: (texts: { clip_id: string; text: string }[]) => Promise<unknown>;
  fonts?: Font[];
  onUploadFont?: (file: File) => void;
  onDeleteFont?: (fontId: string) => void;
  uploadingFont?: boolean;
  /** Fires continuously while a control is being dragged — preview only, never persisted. */
  onPreviewStyle?: (style: Record<string, unknown>) => void;
  onSetStyle?: (style: Record<string, unknown>) => void;
  onDeleteClip: (clipId: string) => void;
  /** 切到「配音」页。配音在那里做,这里只给入口。 */
  onDub?: () => void;
}) {
  const t = useI18n();
  const noteStrings = useNoteStrings();
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

  // 双语字幕存成一条 `原文\n译文`(见下面的 SubtitleTranslate),导出时拆回两行 ——
  // 揉成一行会让笔记里中英黏在一起,而那正是双语最该分开的地方。
  const noteLines: NoteExportLine[] = React.useMemo(
    () => subtitles.map((clip) => {
      const [primary, ...rest] = (clip.text_override ?? "").split("\n");
      return {
        text: primary ?? "", secondary: rest.join("\n") || undefined,
        start: clip.timeline_start, end: clipEnd(clip),
        // 字幕是文本片段,没有来源素材;不编一个出处出来(见 buildNoteExport)。
        assetId: undefined,
      };
    }),
    [subtitles],
  );
  const noteVariants = React.useMemo(
    () => noteExportVariants(noteLines, sequence.name, noteStrings),
    [noteLines, noteStrings, sequence.name],
  );

  // 列轴要和行轴一起锁:不声明 grid-cols 的话隐式列按 max-content 定尺,样式条里任何一段
  // nowrap 文案(字体名、时间码)都会把整栏撑过左侧面板的固定宽度。
  return (
    <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto]">
      {onSetStyle && (
        <SubtitleStyleControls
          style={style}
          fonts={fonts ?? []}
          onUploadFont={onUploadFont}
          onDeleteFont={onDeleteFont}
          uploadingFont={uploadingFont}
          onPreviewStyle={onPreviewStyle}
          onSetStyle={onSetStyle}
        />
      )}
      <div
        className={cn(
          // 行与行之间用细分隔线,不用逐行边框(行自己是无框的)。**行不带圆角**:
          // 圆角 + 横贯的分隔线拼在一起,看上去就是一摞缺了口的卡片(试过,被打回)。
          "grid content-start divide-y divide-border overflow-y-auto overflow-x-hidden px-3 py-2",
          // 空态整块居中,有内容时才贴顶 —— `content-start` 恒定的话,空状态会钉在顶上,
          // 下面留一屏空白(会话列表、轨迹视图都是这个处理)。
          subtitles.length === 0 ? "content-center justify-items-center" : "content-start",
        )}
      >
        {subtitles.length === 0 && (
          <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-ui-sm leading-[1.6] text-muted-foreground">
            <Type size={16} />
            {t("subtitleEmptyBody")}
          </div>
        )}
        {/* 一条字幕是一行,不是一张卡片:此前每条都是「卡片边框套输入框边框」的双层框,
            三十条字幕就是六十个框。改成分隔线列表 + 点进去才像输入框的正文 ——
            绝大多数时候用户在**读**这一列,编辑是偶发的。 */}
        {subtitles.map((clip) => {
          const active = playhead >= clip.timeline_start && playhead < clipEnd(clip);
          return (
            <div key={clip.id} className={cn(
              // **不在行上留 border-l**:父容器的 divide-border 选择器特异性更高,会把子项的
              // 整圈 border-color 一起改掉 —— "透明的左边框"于是显形成一条实线(实测计算样式
              // 里 border-l-transparent 被覆盖成了主题边框色)。选中态的色条用绝对定位画,
              // 不占边框,谁也覆盖不了它。
              "relative grid gap-2 py-3 pl-2 pr-1",
              active && "bg-[color-mix(in_oklab,var(--primary)_5%,transparent)] before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-primary",
            )}>
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  className="timecode cursor-pointer border-0 bg-transparent p-0 pl-1 text-ui-2xs text-muted-foreground hover:text-foreground"
                  title={t("seekToSubtitle")}
                  onClick={() => {
                    useEditorStore.getState().setPlayhead(clip.timeline_start);
                    selectClip(clip.id);
                  }}
                >
                  {formatTimecode(clip.timeline_start)} – {formatTimecode(clipEnd(clip))}
                </button>
                <span className="flex shrink-0 items-center gap-1">
                  {/* 给这一条配音 = 选中它、切到「配音」页。配音页的范围跟着选中走,
                      所以不需要第二套"只配这一条"的表单。 */}
                  {onDub && (
                    <button
                      type="button"
                      className="cursor-pointer rounded-sm border-0 bg-transparent p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                      title={t("subtitleDubThis")}
                      aria-label={t("subtitleDubThis")}
                      onClick={() => {
                        selectClip(clip.id);
                        onDub();
                      }}
                    >
                      <AudioLines size={12} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="cursor-pointer rounded-sm border-0 bg-transparent p-0.5 text-muted-foreground hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
                    title={t("deleteClip")}
                    aria-label={t("deleteClip")}
                    onClick={() => onDeleteClip(clip.id)}
                  >
                    <Trash2 size={12} />
                  </button>
                </span>
              </div>
              {/* 原生 textarea,不走 <Textarea>:基础组件的 border-field-border 在 twMerge 里赢过
                  border-transparent(实测计算样式里边框还在),而这里要的是**零装饰** ——
                  静止时它就是一行正文,聚焦才垫一块浅底 + ring 说明"正在编辑"。
                  `field-sizing:content` 让高度贴内容走(实测生效,单行字幕一行高);
                  padding 恒定,聚焦时不会发生文字跳位。 */}
              <textarea
                key={`sub-${clip.id}-${clip.text_override}`}
                className="w-full resize-none rounded-sm border-0 bg-transparent px-1 py-0.5 text-ui-sm leading-[1.55] text-foreground transition-colors duration-100 [field-sizing:content] hover:bg-[color-mix(in_oklab,var(--foreground)_4%,transparent)] focus-visible:bg-field focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                rows={1}
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
      <div className="flex flex-wrap justify-start gap-2 border-t border-border px-3 py-3">
        {onGenerate && (
          <button type="button" className={PILL} title={t("subtitleGenerateHint")} onClick={onGenerate} disabled={generating}>
            {generating ? <Loader2 size={12} className="animate-mosael-spin" /> : <Sparkles size={12} />} {t("subtitleGenerate")}
          </button>
        )}
        <button type="button" className={PILL} title={t("addSubtitleAtPlayhead")} onClick={onAddSubtitle}>
          <Plus size={12} /> {t("addSubtitleAtPlayhead")}
        </button>
        {subtitles.length > 0 && onApplyTexts && (
          <SubtitleTranslate workspaceId={sequence.workspace_id} subtitles={subtitles} onApplyTexts={onApplyTexts} />
        )}
        {subtitles.length > 0 && onDub && (
          <button type="button" className={PILL} title={t("subtitleDub")} onClick={onDub}>
            <AudioLines size={12} /> {t("subtitleDub")}
          </button>
        )}
        {subtitles.length > 0 && (
          <SaveToNote workspaceId={sequence.workspace_id} variants={noteVariants} className={PILL}
            label={noteStrings.saveAll} />
        )}
      </div>
    </div>
  );
}

/** 一键翻译:把整轨字幕批量译成目标语言,一次提交、一步撤销。 */
function SubtitleTranslate({
  workspaceId,
  subtitles,
  onApplyTexts,
}: {
  workspaceId: string;
  subtitles: { id: string; text_override?: string | null }[];
  onApplyTexts: (texts: { clip_id: string; text: string }[]) => Promise<unknown>;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [lang, setLang] = React.useState<string>("en");
  const [bilingual, setBilingual] = React.useState(false);
  // 翻译引擎。后端两条路早就都在(domain/translate 的 google / ai),缺的只是界面上的这个选择 ——
  // 于是字幕永远走免费的 Google:它快、不要密钥,但整句直译、不看上下文,人名和口语常年翻车。
  // 走 LLM 则用当前工作区配好的模型,能顺着上下文润色。默认仍是 google:它不花钱也不要配置。
  const [engine, setEngine] = React.useState<"google" | "ai">("google");
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  // Only cues that are actually selected count — selecting a video clip should not silently
  // narrow a translation down to nothing.
  const selectedSubtitles = React.useMemo(
    () => subtitles.filter((clip) => selectedClipIds.includes(clip.id)),
    [subtitles, selectedClipIds],
  );
  const [selectedOnly, setSelectedOnly] = React.useState(true);
  const scoped = selectedOnly && selectedSubtitles.length > 0;
  const targets = scoped ? selectedSubtitles : subtitles;

  //: 进行到哪了。null = 没在翻。分母是**要翻的条数**,不是批次数 —— 用户数的是字幕。
  const [progress, setProgress] = React.useState<{ done: number; total: number } | null>(null);
  //: 已经写进轨道的条数。中途失败时靠它把话说全:「前 N 条已写入」—— 只报"失败"的话,
  //: 用户不知道轨道此刻是半翻译状态,更不知道该从哪续。
  const appliedRef = React.useRef(0);

  const run = useMutation({
    mutationFn: async () => {
      const items = targets.filter((clip) => (clip.text_override ?? "").trim());
      appliedRef.current = 0;
      setProgress({ done: 0, total: items.length });
      try {
        // **边翻边落地**:每一批译完立即写进轨道,而不是攒到全部翻完。上千条字幕走 LLM
        // 引擎是分钟级的 —— 攒到最后意味着这几分钟里界面毫无动静,而中途一个失败会把
        // 已经译好的几百条一起扔掉。代价是撤销从"一步"变成"一批一步",以及中途失败时
        // 轨道处于部分翻译状态 —— 所以失败提示必须说清写到了第几条。
        await translateTexts(
          workspaceId,
          items.map((clip) => clip.text_override ?? ""),
          lang,
          engine,
          async (batch, offset) => {
            const texts = batch.flatMap((translated, j) => {
              const clip = items[offset + j];
              const original = clip.text_override ?? "";
              if (!clip || !translated || translated === original) return [];
              // Bilingual keeps the source line above the translation. The subtitle renders with
              // white-space: pre-wrap, so the newline is a real second line in the preview and,
              // via the ASS \N we emit at export, in the burned-in output too.
              return [{ clip_id: clip.id, text: bilingual ? `${original}\n${translated}` : translated }];
            });
            if (texts.length > 0) {
              await onApplyTexts(texts);
              appliedRef.current += texts.length;
            }
            setProgress({ done: Math.min(offset + batch.length, items.length), total: items.length });
          },
        );
        return appliedRef.current;
      } finally {
        setProgress(null);
      }
    },
    onSuccess: (applied) => {
      setOpen(false);
      toast.success(t("subtitleTranslateDone").replace("{n}", String(applied)));
    },
    onError: (error: Error) =>
      toast.error(t("subtitleTranslateFailed"), {
        // 半路失败时已写入的留在轨道上(这是"边翻边落地"的另一面),必须说出来 ——
        // 否则用户以为一条都没动,而轨道已经是两种语言各一半。
        description: appliedRef.current > 0
          ? `${t("subtitleTranslatePartial").replace("{n}", String(appliedRef.current))} ${error.message}`
          : error.message,
      }),
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className={PILL} title={t("subtitleTranslate")}>
          <Languages size={12} /> {t("subtitleTranslate")}
        </button>
      </PopoverTrigger>
      <PopoverContent className="flex w-[220px] flex-col gap-2 p-2.5 [&>strong]:text-ui-sm" align="end">
        <strong>{t("subtitleTranslate")}</strong>
        <label className="grid gap-1 text-xs text-muted-foreground">
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
        <label className="grid gap-1 [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground">
          <span>{t("subtitleTranslateEngine")}</span>
          <Select value={engine} onValueChange={(next) => setEngine(next as "google" | "ai")}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="google">{t("subtitleTranslateEngineGoogle")}</SelectItem>
              <SelectItem value="ai">{t("subtitleTranslateEngineAi")}</SelectItem>
            </SelectContent>
          </Select>
        </label>
        {selectedSubtitles.length > 0 && (
          <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{t("subtitleTranslateSelectedOnly").replace("{n}", String(selectedSubtitles.length))}</span>
            <Switch checked={selectedOnly} onCheckedChange={setSelectedOnly} />
          </label>
        )}
        <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{t("subtitleTranslateBilingual")}</span>
          <Switch checked={bilingual} onCheckedChange={setBilingual} />
        </label>
        <Button size="sm" loading={run.isPending} onClick={() => run.mutate()}>
          <Languages size={13} />
          {progress
            ? t("subtitleTranslateProgress")
                .replace("{done}", String(progress.done))
                .replace("{total}", String(progress.total))
            : (scoped ? t("subtitleTranslateApplySelected") : t("subtitleTranslateApply")).replace(
                "{n}",
                String(targets.length),
              )}
        </Button>
        <small className="text-ui-xs leading-[1.4] text-muted-foreground">
          {bilingual ? t("subtitleTranslateNoteBilingual") : t("subtitleTranslateNote")}
        </small>
      </PopoverContent>
    </Popover>
  );
}

/** Distinguishes an uploaded font from a built-in stack in the one Select. */
const UPLOAD_PREFIX = "upload:";

function SubtitleStyleControls({
  style,
  fonts,
  onUploadFont,
  onDeleteFont,
  uploadingFont,
  onPreviewStyle,
  onSetStyle,
}: {
  style?: Record<string, unknown>;
  fonts: Font[];
  onUploadFont?: (file: File) => void;
  onDeleteFont?: (fontId: string) => void;
  uploadingFont?: boolean;
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
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  return (
    <div className="border-b border-border">
      <button type="button" className="flex w-full cursor-pointer items-center gap-1 border-0 bg-transparent px-2.5 py-[7px] text-xs font-semibold text-muted-foreground" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} {t("subtitleStyle")}
      </button>
      {open && (
        // 样式是**设一次**的东西,列表才是天天碰的 —— 它不该占掉大半个面板。
        // 此前 8 行、每行一个吃满宽度的大控件(3 个选项的「位置」也占满一行,「上传字体」
        // 独占一行还带一格空缩进);收成 5 行紧凑排布,相关的项并到同一行。
        <div className="grid gap-1.5 px-2.5 pb-2.5 pt-0.5">
          <StyleGroup label={t("subGroupText")} first />
          <StyleRow label={t("subFont")}>
            {/* 每一项按自己的字体渲染 —— 字体是用**样子**挑的,名字帮不上忙。装了几十个字体
                之后名字就帮得上了,所以超过阈值 OptionPicker 会换成可搜索的那一版。 */}
            <OptionPicker
              value={s.font_id ? `${UPLOAD_PREFIX}${s.font_id}` : s.font_family}
              onChange={(v) => {
                if (!v.startsWith(UPLOAD_PREFIX)) {
                  patch({ font_family: v, font_id: "" });
                  return;
                }
                const id = v.slice(UPLOAD_PREFIX.length);
                const picked = fonts.find((font) => font.id === id);
                if (picked) patch({ font_id: id, font_family: uploadedFontStack(picked.family) });
              }}
              options={[
                ...SUBTITLE_FONTS.map((font) => ({
                  value: font.value,
                  label: t(font.labelKey as Parameters<typeof t>[0]),
                  style: { fontFamily: font.value },
                })),
                ...fonts.map((font) => ({
                  value: `${UPLOAD_PREFIX}${font.id}`,
                  label: font.family,
                  style: { fontFamily: uploadedFontStack(font.family) },
                })),
              ]}
              className="h-7 min-w-0 flex-1 text-xs"
            />
            {/* 上传/移除跟在字体选择器旁边,而不是独占一行 —— 它们就是对这个选择器的操作。 */}
            {onUploadFont && (
              <Button
                variant="ghost"
                size="icon-xs"
                className="shrink-0 text-muted-foreground hover:text-foreground"
                disabled={uploadingFont}
                aria-label={t("subFontUpload")}
                title={t("subFontUpload")}
                onClick={() => fileRef.current?.click()}
              >
                {uploadingFont ? <Loader2 size={12} className="animate-mosael-spin" /> : <Upload size={12} />}
              </Button>
            )}
            {s.font_id && onDeleteFont && (
              <Button
                variant="ghost"
                size="icon-xs"
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label={t("subFontRemove")}
                title={t("subFontRemove")}
                onClick={() => {
                  // Point the style back at a built-in BEFORE the font goes away, so the
                  // sequence never references a font id that no longer resolves.
                  const removing = s.font_id;
                  patch({ font_id: "", font_family: SUBTITLE_FONTS[0].value });
                  onDeleteFont(removing);
                }}
              >
                <Trash2 size={12} />
              </Button>
            )}
            {onUploadFont && (
              <input
                ref={fileRef}
                type="file"
                accept=".ttf,.otf,.ttc,.otc"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onUploadFont(file);
                  event.target.value = ""; // re-selecting the same file must fire change again
                }}
              />
            )}
          </StyleRow>
          <StyleRow label={t("subFontSize")}>
            <Slider
              min={10}
              max={120}
              step={1}
              value={[s.font_size]}
              onValueChange={([v]) => preview({ font_size: v })}
              onValueCommit={([v]) => patch({ font_size: v })}
            />
            <StyleValue>{Math.round(s.font_size)}</StyleValue>
          </StyleRow>
          <StyleRow label={t("subColor")}>
            {/* 色块铺满这一行剩下的宽度 —— 一个 36px 的小方块漂在一整行空白里,读起来
                像是这行没做完。加粗留在右端:它是另一个开关,不是这块颜色的一部分。 */}
            <ColorSwatch value={s.color} onChange={(v) => patch({ color: v })} grow />
            <span className="ml-auto shrink-0 whitespace-nowrap text-xs text-muted-foreground">{t("subBold")}</span>
            <Switch checked={s.bold} onCheckedChange={(v) => patch({ bold: v })} />
          </StyleRow>

          {/* 衬底自成一组。**此前它和前景色挤在「颜色」那一行**,而那一行末尾还挂着一个
              没有名字的滑杆 —— 光看界面猜不出它调的是什么(是背景的不透明度)。
              一个控件如果需要用户猜它管什么,那它就还没做完。 */}
          <StyleGroup label={t("subGroupBackplate")} />
          <StyleRow label={t("subBg")}>
            <ColorSwatch value={s.bg_color} onChange={(v) => patch({ bg_color: v })} grow />
            {/* 不透明度归零就是「没有衬底」—— 说出来,免得用户以为自己把颜色调错了。 */}
            <span className="ml-auto shrink-0 whitespace-nowrap text-xs text-muted-foreground">
              {s.bg_opacity <= 0.001 ? t("subBgNone") : ""}
            </span>
          </StyleRow>
          <StyleRow label={t("subBgOpacity")}>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={[s.bg_opacity]}
              onValueChange={([v]) => preview({ bg_opacity: v })}
              onValueCommit={([v]) => patch({ bg_opacity: v })}
            />
            <StyleValue>{Math.round(s.bg_opacity * 100)}%</StyleValue>
          </StyleRow>

          {/* 位置和边距是**同一件事的两半**(摆在哪儿、离边多远),此前边距孤零零挂在最后一行,
              而位置那行却和「加粗」并排 —— 加粗是字的形态,和摆位不是一类事。 */}
          <StyleGroup label={t("subGroupPlacement")} />
          <StyleRow label={t("subPosition")}>
            <Select value={s.position} onValueChange={(v) => patch({ position: v as SubtitleStyle["position"] })}>
              <SelectTrigger className="h-7 w-full text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="bottom">{t("subPosBottom")}</SelectItem>
                <SelectItem value="center">{t("subPosCenter")}</SelectItem>
                <SelectItem value="top">{t("subPosTop")}</SelectItem>
              </SelectContent>
            </Select>
          </StyleRow>
          <StyleRow label={t("subOffset")}>
            <Slider
              min={0}
              max={45}
              step={1}
              value={[s.offset]}
              onValueChange={([v]) => preview({ offset: v })}
              onValueCommit={([v]) => patch({ offset: v })}
            />
            <StyleValue>{Math.round(s.offset)}%</StyleValue>
          </StyleRow>
        </div>
      )}
    </div>
  );
}

/** 一组的小标题。**分组不是装饰** —— 此前七个控件平铺,而它们其实分属三件事(字长什么样、
    衬底、摆在哪儿);混在一起时,用户读到「颜色」和「边距」之间没有任何提示说这是两码事。 */
function StyleGroup({ label, first }: { label: string; first?: boolean }) {
  return (
    <span className={cn("text-ui-2xs font-medium text-muted-foreground/70", first ? "pb-0.5" : "pt-1.5")}>
      {label}
    </span>
  );
}

/** 样式面板的一行:左边 42px 标签列,右边内容横排。此前这段布局类(连同色块、数值的样式)
    在每一行上原样抄了七遍 —— 一坨 400 字符的 className,改一处漏六处。 */
function StyleRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    //: 标签列 56px:42px 装不下三个字的标签(「不透明度」会折成两行,把整行撑高)。
    <label className="grid grid-cols-[56px_minmax(0,1fr)] items-center gap-2 text-xs text-foreground">
      <span className="truncate text-muted-foreground">{label}</span>
      <span className="flex min-w-0 items-center gap-1.5">{children}</span>
    </label>
  );
}

/** 滑杆右侧的数值读出:定宽 + 等宽数字,拖动时数字变长不挤动滑杆。 */
function StyleValue({ children }: { children: React.ReactNode }) {
  return <em className="min-w-[30px] shrink-0 text-right text-xs not-italic tabular-nums text-muted-foreground">{children}</em>;
}

function ColorSwatch({ value, onChange, grow }: { value: string; onChange: (v: string) => void; grow?: boolean }) {
  return (
    <input
      type="color"
      className={cn(
        "h-7 cursor-pointer rounded-lg border border-field-border bg-transparent p-0.5 [&::-webkit-color-swatch]:rounded-md [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0",
        grow ? "min-w-0 flex-1" : "w-9 shrink-0",
      )}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

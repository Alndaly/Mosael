import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, ChevronDown, ChevronRight, Languages, Loader2, Plus, Sparkles, Trash2, Type, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { readSubtitleStyle, SUBTITLE_FONTS, TRANSLATE_LANGS, type SubtitleStyle } from "@/features/editor/subtitleStyle";
import { uploadedFontStack } from "@/features/editor/FontFaces";
import type { Font } from "@/api/client";

import {
  api,
  dubSubtitles,
  listTtsEngines,
  listTtsVoices,
  listVoices,
  translateTexts,
  type Clip,
  type Job,
  type Sequence,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { dubEngineChoices } from "@/features/editor/dubEngines";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { PILL } from "@/features/editor/pill";
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
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto]">
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
          "grid gap-1.5 overflow-y-auto p-1.5",
          // 空态整块居中,有内容时才贴顶 —— `content-start` 恒定的话,空状态会钉在顶上,
          // 下面留一屏空白(会话列表、轨迹视图都是这个处理)。
          subtitles.length === 0 ? "content-center justify-items-center" : "content-start",
        )}
      >
        {subtitles.length === 0 && (
          <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-ui-md leading-[1.6] text-muted-foreground">
            <Type size={16} />
            {t("subtitleEmptyBody")}
          </div>
        )}
        {subtitles.map((clip) => {
          const active = playhead >= clip.timeline_start && playhead < clipEnd(clip);
          return (
            <div key={clip.id} className={cn(
              "grid gap-[5px] rounded-md border border-border bg-panel px-[9px] py-1.5",
              active && "border-[color-mix(in_oklab,var(--primary)_50%,var(--border))] bg-[color-mix(in_oklab,var(--primary)_5%,var(--panel))]",
            )}>
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  className="timecode cursor-pointer border-0 bg-transparent p-0 pt-0.5 text-ui-xs text-muted-foreground"
                  title={t("seekToSubtitle")}
                  onClick={() => {
                    useEditorStore.getState().setPlayhead(clip.timeline_start);
                    selectClip(clip.id);
                  }}
                >
                  {formatTimecode(clip.timeline_start)} – {formatTimecode(clipEnd(clip))}
                </button>
                <span className="flex items-center gap-0.5">
                  {/* 段落配音:你点的这一条就是范围,不必先去时间线上选中它。 */}
                  <SubtitleDub sequence={sequence} subtitles={subtitles} only={clip} />
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
              <Textarea
                key={`sub-${clip.id}-${clip.text_override}`}
                className="w-full resize-y rounded-md border border-border bg-field px-[9px] py-[7px] text-ui-sm leading-normal text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-ring"
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
      <div className="flex flex-wrap justify-center gap-1.5 border-t border-border px-2 py-1.5">
        {onGenerate && (
          <button type="button" className={PILL} title={t("subtitleGenerateHint")} onClick={onGenerate} disabled={generating}>
            {generating ? <Loader2 size={12} className="animate-openstudio-spin" /> : <Sparkles size={12} />} {t("subtitleGenerate")}
          </button>
        )}
        <button type="button" className={PILL} title={t("addSubtitleAtPlayhead")} onClick={onAddSubtitle}>
          <Plus size={12} /> {t("addSubtitleAtPlayhead")}
        </button>
        {subtitles.length > 0 && onApplyTexts && (
          <SubtitleTranslate workspaceId={sequence.workspace_id} subtitles={subtitles} onApplyTexts={onApplyTexts} />
        )}
        {subtitles.length > 0 && <SubtitleDub sequence={sequence} subtitles={subtitles} />}
      </div>
    </div>
  );
}

/** 一键翻译:把整轨字幕批量译成目标语言(Google 免费),一次提交、一步撤销。 */
/**
 * 字幕配音:选中的字幕条 → 逐条合成 → 落到一条新的音频轨。
 *
 * **只列克隆音色**。远端引擎(火山等)的发音人挑选牵着资源族、模型、供应商三层选择,那套完整的
 * 选择器在「配音」标签页里 —— 在这儿再实现一遍就是同一个问题两处答案。这里要的是「用我已经
 * 建好的那个声音,把这几条念出来」。
 */
function SubtitleDub({
  sequence,
  subtitles,
  only,
}: {
  sequence: Sequence;
  subtitles: Clip[];
  /** 只配这一条(字幕卡片上的入口)。给了它就不再谈「选中的几条」—— 你点的就是范围。 */
  only?: Clip;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  // 引擎:克隆(用自己建的音色)或某个远端引擎(自带发音人)。此前这里写死了克隆 ——
  // 于是没建过音色的人一个字都配不出来,而他明明配好了火山。
  const [engine, setEngine] = React.useState("clone");
  const [voiceId, setVoiceId] = React.useState("");
  const [engineVoice, setEngineVoice] = React.useState("");
  // 匹配段落长度默认**关**:变速会改语速听感,超出 ±20% 就明显不自然。值不值这个代价由用户
  // 按素材决定,而不是替他默认承受。开着时用的是片段自己的 speed,无损、可撤销、事后能微调。
  const [matchDuration, setMatchDuration] = React.useState(false);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const selectedSubtitles = React.useMemo(
    () => subtitles.filter((clip) => selectedClipIds.includes(clip.id)),
    [subtitles, selectedClipIds],
  );
  const [selectedOnly, setSelectedOnly] = React.useState(true);
  // 双语字幕是「原文\n译文」两行。整段念 = 先念一遍原文再念一遍译文,一条 3 秒的字幕配出
  // 12 秒的音。默认全念(单语字幕就该全念),有多行时才把这个选择摆出来。
  const [line, setLine] = React.useState<"all" | "first" | "last">("all");
  const scoped = selectedOnly && selectedSubtitles.length > 0;
  const pool = only ? [only] : scoped ? selectedSubtitles : subtitles;
  const targets = pool.filter((clip) => (clip.text_override ?? "").trim());
  const hasBilingual = targets.some((clip) => (clip.text_override ?? "").trim().includes("\n"));

  const voices = useQuery({
    queryKey: ["voices", sequence.workspace_id],
    queryFn: () => listVoices(sequence.workspace_id),
    enabled: open && engine === "clone",
  });
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000, enabled: open });
  // 发音人按引擎现拉:火山的目录跟着账号走,不是引擎列表的一部分。
  const engineVoices = useQuery({
    queryKey: ["tts-voices", engine],
    queryFn: () => listTtsVoices(engine),
    enabled: open && engine !== "clone",
  });
  const voiceChoices = engineVoices.data ?? [];
  const activeEngine = engines.data?.find((item) => item.id === engine);
  const engineChoices = dubEngineChoices(engines.data);
  React.useEffect(() => {
    if (engine === "clone" && !voiceId && voices.data?.length) setVoiceId(voices.data[0].id);
  }, [voices.data, voiceId, engine]);
  React.useEffect(() => {
    setEngineVoice("");
  }, [engine]);
  const chosenVoice = voiceChoices.find((item) => item.value === (engineVoice || voiceChoices[0]?.value));
  // 能不能配:克隆要有音色;远端引擎要么有目录、要么它自己说需要手填 id 而用户填了。
  const ready =
    engine === "clone"
      ? Boolean(voiceId)
      : voiceChoices.length > 0 || Boolean(engineVoice) || !activeEngine?.needs_voice_id;

  // 配音是个后台任务:发起时时间线上什么都不会变,音频要等它跑完才落轨。**得有人盯着它** ——
  // 不盯的话用户看到的是「点了没反应」,过一会儿也不会自己出现,除非手动切走再切回来。
  // 这条 bug 就是这么被报上来的:配音其实成功了,只是那条新轨没进到界面里。
  const qc = useQueryClient();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 1000;
    },
  });
  const jobStatus = job.data?.status ?? null;
  React.useEffect(() => {
    if (jobStatus !== "succeeded" && jobStatus !== "failed") return;
    // 成功要刷时间线(新轨在那儿),失败也要刷 —— 部分成功时已经落地的那几段同样得看得见。
    void qc.invalidateQueries({ queryKey: ["sequences"] });
    if (jobStatus === "succeeded") toast.success(job.data?.message ?? t("subtitleDubDone"));
    else toast.error(job.data?.message ?? t("subtitleDubFailed"), { description: job.data?.error ?? undefined });
    setJobId(null);
  }, [jobStatus, job.data, qc, t]);

  const run = useMutation({
    mutationFn: () =>
      dubSubtitles(sequence.id, {
        clip_ids: targets.map((clip) => clip.id),
        match_duration: matchDuration,
        line,
        engine,
        ...(engine === "clone"
          ? { voice_id: voiceId }
          : {
              // 下拉在没选时**显示**第一个,那就提交同一个 —— 否则引擎会安静地用它自己的默认音。
              engine_voice: engineVoice || voiceChoices[0]?.value || "",
              // 只有目录知道的资源族;不带的话火山回一个 55000000。
              engine_voice_resource: chosenVoice?.resource_id ?? "",
            }),
      }),
    onSuccess: (queued) => {
      setOpen(false);
      setJobId(queued.id);
      // 只确认"排上了",不假装已经配好 —— 真正配好由上面那个 effect 在任务终态时说。
      toast.success(t("subtitleDubQueued").replace("{n}", String(targets.length)));
    },
    onError: (error: Error) => toast.error(t("subtitleDubFailed"), { description: error.message }),
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {only ? (
          <button
            type="button"
            className="cursor-pointer rounded-sm border-0 bg-transparent p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
            title={t("subtitleDubThis")}
            aria-label={t("subtitleDubThis")}
          >
            <AudioLines size={12} />
          </button>
        ) : (
          <button type="button" className={PILL} title={t("subtitleDub")}>
            <AudioLines size={12} /> {t("subtitleDub")}
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent className="flex w-[240px] flex-col gap-2 p-2.5 [&>strong]:text-ui-sm" align="end">
        <strong>{t("subtitleDub")}</strong>
        <label className="grid gap-1 text-xs text-muted-foreground">
          <span>{t("subtitleDubEngine")}</span>
          <Select value={engine} onValueChange={setEngine}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {engineChoices.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        {engine === "clone" ? (
          voices.isSuccess && (voices.data ?? []).length === 0 ? (
            // 没有音色时不摆一个空下拉让人点 —— 直说下一步在哪。
            <p className="m-0 text-xs leading-[1.6] text-muted-foreground">{t("subtitleDubNoVoice")}</p>
          ) : (
            <label className="grid gap-1 text-xs text-muted-foreground">
              <span>{t("subtitleDubVoice")}</span>
              <Select value={voiceId} onValueChange={setVoiceId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(voices.data ?? []).map((voice) => (
                    <SelectItem key={voice.id} value={voice.id}>
                      {voice.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          )
        ) : voiceChoices.length > 0 ? (
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("subtitleDubVoice")}</span>
            <Select value={engineVoice || voiceChoices[0].value} onValueChange={setEngineVoice}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {voiceChoices.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        ) : activeEngine?.needs_voice_id ? (
          // 目录拉不到(没配密钥、或这个引擎本来就要手填)时给输入框,而不是一个空下拉。
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("voiceEngineVoiceId")}</span>
            <Input
              className="h-7"
              value={engineVoice}
              placeholder={t("voiceEngineVoiceIdHint")}
              onChange={(event) => setEngineVoice(event.target.value)}
            />
          </label>
        ) : null}
        {!only && selectedSubtitles.length > 0 && (
          <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{t("subtitleTranslateSelectedOnly").replace("{n}", String(selectedSubtitles.length))}</span>
            <Switch checked={selectedOnly} onCheckedChange={setSelectedOnly} />
          </label>
        )}
        {/* 只在真有双语字幕时出现 —— 单语字幕摆一个「念哪一行」只会让人以为自己漏配了什么。 */}
        {hasBilingual && (
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("subtitleDubLine")}</span>
            <Select value={line} onValueChange={(next) => setLine(next as "all" | "first" | "last")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("subtitleDubLineAll")}</SelectItem>
                <SelectItem value="first">{t("subtitleDubLineFirst")}</SelectItem>
                <SelectItem value="last">{t("subtitleDubLineLast")}</SelectItem>
              </SelectContent>
            </Select>
          </label>
        )}
        <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span title={t("subtitleDubMatchHint")}>{t("subtitleDubMatch")}</span>
          <Switch checked={matchDuration} onCheckedChange={setMatchDuration} />
        </label>
        <p className="m-0 text-ui-2xs leading-[1.5] text-muted-foreground">{t("subtitleDubTrackNote")}</p>
        <Button size="sm" disabled={targets.length === 0 || !ready} loading={run.isPending} onClick={() => run.mutate()}>
          {only ? t("subtitleDubApplyOne") : t("subtitleDubApply").replace("{n}", String(targets.length))}
        </Button>
      </PopoverContent>
    </Popover>
  );
}

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

  const run = useMutation({
    mutationFn: async () => {
      const items = targets.filter((clip) => (clip.text_override ?? "").trim());
      const { translations } = await translateTexts(
        workspaceId,
        items.map((clip) => clip.text_override ?? ""),
        lang,
        engine,
      );
      const texts = items.flatMap((clip, i) => {
        const original = clip.text_override ?? "";
        const translated = translations[i];
        if (!translated || translated === original) return [];
        // Bilingual keeps the source line above the translation. The subtitle renders with
        // white-space: pre-wrap, so the newline is a real second line in the preview and,
        // via the ASS \N we emit at export, in the burned-in output too.
        return [{ clip_id: clip.id, text: bilingual ? `${original}\n${translated}` : translated }];
      });
      if (texts.length === 0) return 0;
      // One request, one revision, one undo — and nothing is written unless every cue resolves,
      // so a failure can no longer leave the track half in each language.
      await onApplyTexts(texts);
      return texts.length;
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
          {(scoped ? t("subtitleTranslateApplySelected") : t("subtitleTranslateApply")).replace(
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
        <div className="grid gap-2 px-2.5 pb-2.5 pt-1">
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
            <span>{t("subFont")}</span>
            <Select
              value={s.font_id ? `${UPLOAD_PREFIX}${s.font_id}` : s.font_family}
              onValueChange={(v) => {
                if (!v.startsWith(UPLOAD_PREFIX)) {
                  patch({ font_family: v, font_id: "" });
                  return;
                }
                const id = v.slice(UPLOAD_PREFIX.length);
                const picked = fonts.find((font) => font.id === id);
                if (picked) patch({ font_id: id, font_family: uploadedFontStack(picked.family) });
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUBTITLE_FONTS.map((font) => (
                  <SelectItem key={font.value} value={font.value} style={{ fontFamily: font.value }}>
                    {t(font.labelKey as Parameters<typeof t>[0])}
                  </SelectItem>
                ))}
                {fonts.map((font) => (
                  <SelectItem
                    key={font.id}
                    value={`${UPLOAD_PREFIX}${font.id}`}
                    style={{ fontFamily: uploadedFontStack(font.family) }}
                  >
                    {font.family}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          {onUploadFont && (
            <div className="grid grid-cols-[42px_auto_auto_minmax(0,1fr)] items-center gap-1 text-xs text-foreground [&>span:first-child]:text-muted-foreground">
              <span />
              <Button variant="ghost" size="sm" disabled={uploadingFont} onClick={() => fileRef.current?.click()}>
                {uploadingFont ? <Loader2 size={12} className="animate-openstudio-spin" /> : <Upload size={12} />} {t("subFontUpload")}
              </Button>
              {s.font_id && onDeleteFont && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    // Point the style back at a built-in BEFORE the font goes away, so the
                    // sequence never references a font id that no longer resolves.
                    const removing = s.font_id;
                    patch({ font_id: "", font_family: SUBTITLE_FONTS[0].value });
                    onDeleteFont(removing);
                  }}
                >
                  <Trash2 size={12} /> {t("subFontRemove")}
                </Button>
              )}
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
            </div>
          )}
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
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
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
            <span>{t("subColor")}</span>
            <input type="color" className="h-7! w-10! cursor-pointer rounded-lg! border! border-input! bg-transparent! p-0.5! [&::-webkit-color-swatch]:rounded-md [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0" value={s.color} onChange={(e) => patch({ color: e.target.value })} />
          </label>
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
            <span>{t("subBg")}</span>
            <input type="color" className="h-7! w-10! cursor-pointer rounded-lg! border! border-input! bg-transparent! p-0.5! [&::-webkit-color-swatch]:rounded-md [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0" value={s.bg_color} onChange={(e) => patch({ bg_color: e.target.value })} />
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={[s.bg_opacity]}
              onValueChange={([v]) => preview({ bg_opacity: v })}
              onValueCommit={([v]) => patch({ bg_opacity: v })}
            />
          </label>
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
            <span>{t("subBold")}</span>
            <Switch checked={s.bold} onCheckedChange={(v) => patch({ bold: v })} />
          </label>
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
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
          <label className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 text-xs text-foreground [&>span:first-child]:text-muted-foreground [&_em]:min-w-[30px] [&_em]:text-right [&_em]:not-italic [&_em]:tabular-nums [&_em]:text-muted-foreground [&_input[type=color]]:h-[22px] [&_input[type=color]]:w-7 [&_input[type=color]]:cursor-pointer [&_input[type=color]]:rounded [&_input[type=color]]:border [&_input[type=color]]:border-border [&_input[type=color]]:bg-transparent [&_input[type=color]]:p-0">
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

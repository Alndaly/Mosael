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
  downloadF5Model,
  listF5Models,
  listTtsEngines,
  listTtsVoices,
  listVoices,
  translateTexts,
  type Clip,
  type Job,
  type Sequence,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { NONE, optionalValue } from "@/components/ui/selectSentinel";
import { dubEngineChoices } from "@/features/editor/dubEngines";
import { detectScript, dubTextOf, hasVoiceFor, pickVoiceFor, unspeakable } from "@/features/editor/dubLanguage";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { PILL } from "@/features/editor/pill";
import { useEditorStore } from "@/stores/editorStore";
import { formatBytes } from "@/lib/bytes";
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
          // 行与行之间用细分隔线,不用逐行边框(行自己是无框的)。**行不带圆角**:
          // 圆角 + 横贯的分隔线拼在一起,看上去就是一摞缺了口的卡片(试过,被打回)。
          "grid content-start divide-y divide-border/40 overflow-y-auto px-1.5 py-1",
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
              "relative grid gap-0 py-1.5 pl-2 pr-1",
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
              {/* 原生 textarea,不走 <Textarea>:基础组件的 border-input 在 twMerge 里赢过
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
  //: 用哪份克隆权重。空 = 按文字自动挑 —— 中日韩俄阿印能自动认出来,而法德西意芬都写拉丁
  //: 字母,没有任何字符能证明"这是法语而不是英语",只能由用户明说。
  const [cloneModel, setCloneModel] = React.useState(NONE);
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
  // 本地克隆的语言能力由**装了哪几份权重**决定,不是引擎的固有属性 —— 所以要问一下这台机器。
  const f5Models = useQuery({
    queryKey: ["f5-models"],
    queryFn: listF5Models,
    enabled: open && engine === "clone",
    // 下载中就跟着刷:用户点完下载不该盯着一个不动的界面猜它有没有在跑。
    refetchInterval: (query) => (query.state.data?.some((item) => item.status === "downloading") ? 1500 : false),
  });
  // 这段字幕是什么文字。每次算,不缓存 —— 判据只扫几行字符,比维护一个依赖数组便宜。
  const wantScript = detectScript(targets.map((clip) => dubTextOf(clip, line)).join("\n"));
  // 能念这段文字、但还没下的那份权重 —— 有它就把「下载」直接摆在这儿,而不是让用户去设置页找。
  const missingModel = (f5Models.data ?? []).find(
    // `?? []`:一个字段缺失的响应不该把整个字幕面板炸掉(测试里的桩就这么炸过一次)。
    (model) => wantScript && (model.languages ?? []).includes(wantScript) && !model.installed,
  );
  const downloadModel = useMutation({
    mutationFn: (modelId: string) => downloadF5Model(modelId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["f5-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });
  // **默认就选对**,而不是先落在第一个音色上再弹警告让用户猜要改什么。只在用户还没手动选过
  // (engineVoice 为空)时动手,选过就不再覆盖 —— 那是他的决定。
  React.useEffect(() => {
    if (engine === "clone" || engineVoice || voiceChoices.length === 0) return;
    const match = pickVoiceFor(wantScript, engine, voiceChoices);
    if (match) setEngineVoice(match);
  }, [engine, engineVoice, voiceChoices, wantScript]);
  // 语言对不上时,引擎**不会报错** —— 它按自己那套发音规则硬念一遍,交出一段听不懂的声音。
  // 后端会拦(audio/tts_language),但那是在排队之后;文本就在眼前,这一刻就该说。
  // 克隆能念什么,取决于这台机器上装了哪几份权重 —— 现算,不写死。
  const cloneLanguages = (f5Models.data ?? []).filter((m) => m.installed).flatMap((m) => m.languages ?? []);
  const mismatch = unspeakable(
    targets.map((clip) => dubTextOf(clip, line)),
    engine,
    engine === "clone" ? "" : engineVoice || voiceChoices[0]?.value || "",
    cloneLanguages,
  );
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
    // 时间线和**素材库**都要刷。只刷时间线的话,新片段引用的素材前端还不知道 ——
    // 片段标题会回退成一串 id、波形也无从查起(它是按 asset.media_info.has_waveform 拉的),
    // 看起来就像"配音没有波形"。失败也刷:部分成功时已经落地的那几段同样得看得见。
    void qc.invalidateQueries({ queryKey: ["sequences"] });
    void qc.invalidateQueries({ queryKey: ["assets"] });
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
          ? { voice_id: voiceId, clone_model: optionalValue(cloneModel) ?? "" }
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
        {engine === "clone" && (f5Models.data ?? []).filter((m) => m.installed).length > 1 && (
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("subtitleDubWeights")}</span>
            <Select value={cloneModel} onValueChange={setCloneModel}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* 「自动」排第一:中日韩俄阿印能按文字认出来,那是绝大多数情况。 */}
                <SelectItem value={NONE}>{t("subtitleDubWeightsAuto")}</SelectItem>
                {(f5Models.data ?? [])
                  .filter((model) => model.installed)
                  .map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.label}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </label>
        )}
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
        {mismatch && (
          <p className="m-0 rounded-md border border-[color-mix(in_srgb,var(--destructive)_35%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)] px-2 py-1.5 text-ui-2xs leading-[1.5] text-foreground">
            {/* 说清楚**下一步动哪儿**:这个引擎里有能念的音色就让他换音色 —— 已经选对引擎却被
                告知「换引擎」,只会让人以为选的这个不行(用户就是这么被绕进去的)。 */}
            {engine === "clone" && missingModel
              ? // 同一个占位符出现两次,replace 只换第一个 —— 界面上会留一个字面的 {lang}(真出过)。
                t("subtitleDubModelMissing")
                  .replaceAll("{lang}", t(`langName_${mismatch}` as never))
                  .replace("{size}", (missingModel.expected_bytes / 1_000_000_000).toFixed(1))
                : hasVoiceFor(mismatch, engine, voiceChoices)
                  ? t("subtitleDubLangVoice").replaceAll("{lang}", t(`langName_${mismatch}` as never))
                  : t("subtitleDubLangEngine").replaceAll("{lang}", t(`langName_${mismatch}` as never))}
            {engine === "clone" && missingModel && (
              <Button
                size="sm"
                variant="outline"
                className="mt-1.5 w-full"
                loading={downloadModel.isPending || missingModel.status === "downloading"}
                onClick={() => downloadModel.mutate(missingModel.id)}
              >
                {/* 光有百分比不够:这些权重 1.3–5.4 GB,慢网络下一个百分点要好几分钟,
                    而"看不出还要多久"和"卡住了"在用户眼里是同一件事。有实测总量就一并报出来。 */}
                {missingModel.status === "downloading"
                  ? missingModel.total_bytes > 0
                    ? t("subtitleDubModelDownloadingSize")
                        .replace("{n}", String(Math.round(missingModel.progress * 100)))
                        .replace("{done}", formatBytes(missingModel.downloaded_bytes))
                        .replace("{total}", formatBytes(missingModel.total_bytes))
                    : t("subtitleDubModelDownloading").replace("{n}", String(Math.round(missingModel.progress * 100)))
                  : t("subtitleDubModelDownload")}
              </Button>
            )}
          </p>
        )}
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
              <SelectTrigger className="h-7 min-w-0 flex-1 text-xs">
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
            {/* 上传/移除跟在字体选择器旁边,而不是独占一行 —— 它们就是对这个选择器的操作。 */}
            {onUploadFont && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
                disabled={uploadingFont}
                aria-label={t("subFontUpload")}
                title={t("subFontUpload")}
                onClick={() => fileRef.current?.click()}
              >
                {uploadingFont ? <Loader2 size={12} className="animate-openstudio-spin" /> : <Upload size={12} />}
              </Button>
            )}
            {s.font_id && onDeleteFont && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
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
        "h-7 cursor-pointer rounded-lg border border-input bg-transparent p-0.5 [&::-webkit-color-swatch]:rounded-md [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0",
        grow ? "min-w-0 flex-1" : "w-9 shrink-0",
      )}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

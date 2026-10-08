import { SaveToNote } from "@/features/notes/SaveToNote";
import { useNoteStrings } from "@/features/notes/strings";
import { noteExportVariants, type NoteExportLine } from "@/features/editor/noteExport";
import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Captions, Loader2, MessageSquareText, Mic, Scissors, Split, SplitSquareVertical, Trash2, UserRound, X } from "lucide-react";

import { getAssetTranscript, getJob, listAsrModels, listJobs, transcribeAsset, type Clip, type Sequence } from "@/api/client";
import { jobSettled } from "@/components/jobs/runStatus";
import { transcriptKeys } from "@/api/queryKeys";
import { asrEngineMissing, pendingTranscribeIds } from "@/features/editor/transcribeQueue";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { EngineNotice } from "@/components/app/ConfigNotice";
import { kindHasSound } from "@/lib/assetKinds";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { tokenTimelineRange } from "@/domain/timeline/karaoke";
import { speakerChipStyle, speakerLabel, speakerShort, speakersAreMeaningful } from "@/features/editor/transcriptSpeakers";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/lib/time";
import {
  DEFAULT_FILLER_CATEGORIES,
  detectSilences,
  fillerMatches,
  isFillerToken,
  projectTranscript,
  projectedRowKey,
  transcriptDocument,
  transcriptSegmentsFromApi,
  type FillerCategoryId,
  type FillerMatch,
  type ProjectedSegment,
  type SegmentLike,
  type TranscriptDocItem,
} from "@/domain/timeline/transcriptProjection";
import { FillerPicker } from "@/features/editor/FillerPicker";
import { transcriptSourceClips } from "@/domain/timeline/transcriptSources";
import { PILL } from "@/features/editor/pill";
import { useEditorStore } from "@/features/editor/editorStore";
import { useVirtualRows } from "@/lib/useVirtualRows";
import { cn } from "@/lib/utils";


export interface CutRange {
  srcStart: number;
  srcEnd: number;
}

/** Selected word key → its cut payload. */
type TokenSelection = Map<string, { clipId: string; srcStart: number; srcEnd: number }>;

/**
 * 时间码那一栏。句子和静音块共用它 —— 对齐是**结构**给的,不是手调出来的边距。
 *
 * 宽度按**最长**的时间码定(`1:23:45.6`,JetBrains Mono 10.5px 实测 58px):按 `00:06.6`
 * 那种短的定宽,一条超过一小时的时间线就会把这一栏撑破、正好吃掉它和正文之间的空隙。
 * 栏内右对齐,于是不论几位数,时间码到正文的距离都一样。
 */
const GUTTER = "grid-cols-[58px_minmax(0,1fr)]";

/**
 * 多说话人的元数据栏只比纯时间码多留一枚说话人标签(人形图标 + 序号)的宽度。时间码和说话人同组、
 * 同顶线,正文列仍保持 `minmax(0, 1fr)`,内容过长时自然换行而不截断。
 * 按最长时间码 58px + 间距 + 标签约 30px 定,不按 `00:06.6` 那种短的定。
 */
const SPEAKER_GUTTER = "grid-cols-[92px_minmax(0,1fr)]";

interface TranscriptRowActions {
  beginWordDrag: (flatIndex: number) => void;
  toggleToken: (key: string, clipId: string, srcStart: number, srcEnd: number) => void;
  splitSentenceOut: (clipId: string, srcStart: number, srcEnd: number) => void;
  cutSentence: (clipId: string, srcStart: number, srcEnd: number) => void;
}

function docItemKey(item: TranscriptDocItem): string {
  return item.kind === "silence" ? `${item.gap.clipId}:sil:${item.gap.srcStart}` : projectedRowKey(item.sentence);
}

/** 播放头落在哪个片段、对应源时间多少;不在任何片段上则为 null。 */
function activeSourceAt(clips: readonly Clip[], playhead: number): { clipId: string; src: number } | null {
  for (const clip of clips) {
    const end = clip.timeline_start + (clip.src_out - clip.src_in) / (clip.speed || 1);
    if (playhead >= clip.timeline_start && playhead < end) {
      return { clipId: clip.id, src: clip.src_in + (playhead - clip.timeline_start) * (clip.speed || 1) };
    }
  }
  return null;
}

function activeSentenceKeyAt(projected: readonly ProjectedSegment[], playhead: number): string | null {
  const hit = projected.find((item) => playhead >= item.timelineStart && playhead < item.timelineEnd);
  return hit ? projectedRowKey(hit) : null;
}

interface TokenSpans {
  starts: number[];
  ends: number[];
  keys: string[];
  /** 最长的一个词有多长:二分到「起点 ≤ 播放头」之后,往回只需看这么远。 */
  longest: number;
}

/**
 * 每个词在时间线上的区间,按起点排序。问的是「这个词落在时间线的哪一段」,而不是「当前是哪个
 * 片段」—— 视频轨和音频轨时间上重叠,而逐字稿来自音频片段,按「第一个覆盖播放头的片段」去比对,
 * 命中的永远是排在前面的视频片段。
 */
function buildTokenSpans(items: readonly TranscriptDocItem[], clipById: Map<string, Clip>): TokenSpans {
  const spans: { start: number; end: number; key: string }[] = [];
  for (const item of items) {
    if (item.kind !== "sentence") continue;
    const sentence = item.sentence;
    const clip = clipById.get(sentence.clipId);
    sentence.tokens.forEach((token, index) => {
      const span = tokenTimelineRange(clip, token);
      if (span) spans.push({ start: span[0], end: span[1], key: `${sentence.clipId}:${sentence.segmentId}:${index}` });
    });
  }
  spans.sort((a, b) => a.start - b.start);
  let longest = 0;
  for (const span of spans) longest = Math.max(longest, span.end - span.start);
  return { starts: spans.map((x) => x.start), ends: spans.map((x) => x.end), keys: spans.map((x) => x.key), longest };
}

/** 播放头所在的词(可能不止一个:两条轨上的逐字稿时间重叠),以换行连成一个可 === 比较的字符串。 */
export function currentTokenKeys(spans: TokenSpans, playhead: number): string {
  let lo = 0;
  let hi = spans.starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (spans.starts[mid] <= playhead) lo = mid + 1;
    else hi = mid;
  }
  const hits: string[] = [];
  for (let i = lo - 1; i >= 0 && spans.starts[i] >= playhead - spans.longest; i--) {
    if (playhead < spans.ends[i]) hits.push(spans.keys[i]);
  }
  return hits.sort().join("\n");
}

/** 只把属于这一句的当前词交给这一行:其余行拿到空串,memo 让它们整行跳过。 */
function tokensOfSentence(current: string, sentence: ProjectedSegment): string {
  if (!current) return "";
  const prefix = `${sentence.clipId}:${sentence.segmentId}:`;
  return current
    .split("\n")
    .filter((key) => key.startsWith(prefix))
    .join("\n");
}

/** 逐字稿里的一行(一句,或一段静音)。memo:播放时只有当前词所在的那一句重渲。 */
const TranscriptRow = React.memo(function TranscriptRow({
  rowRef,
  item,
  active,
  currentTokens,
  selected,
  showSpeakers,
  flatIndexByKey,
  canSplit,
  fillerKinds,
  actions,
}: {
  rowRef: (element: HTMLElement | null) => void;
  item: TranscriptDocItem;
  active: boolean;
  currentTokens: string;
  selected: TokenSelection;
  showSpeakers: boolean;
  flatIndexByKey: Map<string, number>;
  canSplit: boolean;
  /** 哪几类口癖算(高亮跟着走,见 FillerPicker)。 */
  fillerKinds: ReadonlySet<FillerCategoryId>;
  actions: TranscriptRowActions;
}) {
  const t = useI18n();
  const currentSet = React.useMemo(() => new Set(currentTokens ? currentTokens.split("\n") : []), [currentTokens]);
  return <div ref={rowRef} className="pb-1.5">{renderRow()}</div>;

  function renderRow() {
    if (item.kind === "silence") {
      const gap = item.gap;
      const gapKey = `${gap.clipId}:sil:${gap.srcStart}`;
      return (
        // 静音块走**同一套栅格**:空掉时间码那一栏,正文那一栏自然对齐。
        // 此前是 `ml-[46px]` —— 一个照着时间码宽度手调出来的数,时间码一改就错开。
        <div
          className={cn(
            "grid items-center gap-x-2 pl-3",
            showSpeakers ? SPEAKER_GUTTER : GUTTER,
          )}
        >
          <span aria-hidden />
          <Hint label={t("silenceGapHint")}>
            <button
              type="button"
              className={cn(
                "inline-flex cursor-pointer items-center gap-1 justify-self-start rounded-full border border-dashed border-border-strong bg-secondary px-[9px] py-px text-ui-xs text-muted-foreground hover:border-destructive hover:text-destructive",
                selected.has(gapKey) && "border-destructive bg-[color-mix(in_oklab,var(--destructive)_8%,transparent)] text-destructive line-through",
              )}
              onClick={() => actions.toggleToken(gapKey, gap.clipId, gap.srcStart, gap.srcEnd)}
            >
              <AudioLines size={10} /> {gap.duration.toFixed(1)}s
            </button>
          </Hint>
        </div>
      );
    }
    const sentence = item.sentence;
    const key = projectedRowKey(sentence);
    return (
      <div
        className={cn(
          "group/sentence relative grid items-start gap-x-2 rounded-md py-1 pl-3 pr-2 transition-[background] duration-100 hover:bg-[color-mix(in_oklab,var(--foreground)_4%,transparent)]",
          showSpeakers ? SPEAKER_GUTTER : GUTTER,
          active && "bg-[color-mix(in_oklab,var(--primary)_7%,transparent)]",
        )}
      >
        {/* 当前句的指示条:上下内缩的圆角条,而不是贴着行高的直角边框。
            边框还得在每一行都占着 2px 透明位置(不占就会在切换时整行横跳),
            一个绝对定位的条子既不参与布局,也能圆角。 */}
        {active && (
          <span aria-hidden className="pointer-events-none absolute bottom-[5px] left-[3px] top-[5px] w-[3px] rounded-full bg-primary" />
        )}
        <div className="flex h-6 min-w-0 items-center justify-start gap-1 whitespace-nowrap">
          <Hint label={t("seekToSentence")}>
            <button
              type="button"
              className={cn(
                "timecode cursor-pointer border-0 bg-transparent p-0 text-ui-2xs leading-6 tabular-nums text-muted-foreground hover:text-primary",
                active && "font-medium text-primary",
              )}
              onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
            >
              {formatTimecode(sentence.timelineStart)}
            </button>
          </Hint>
          {/* 说话人与时间码在正文首行的同一个元数据组里,不再垂直居中到多行正文中间。 */}
          {showSpeakers && sentence.speaker && (
            // 人形图标 + 从 1 数的序号:光一个 `00` 挨着时间码 `00:00.4`,读起来像时间码的一部分。
            <Hint label={speakerLabel(sentence.speaker, t)}>
              <span
                role="img"
                className="inline-flex h-5 min-w-6 shrink-0 items-center justify-center gap-0.5 rounded-full px-1.5 text-ui-2xs font-semibold leading-5 tabular-nums"
                style={speakerChipStyle(sentence.speaker)}
                aria-label={speakerLabel(sentence.speaker, t)}
              >
                <UserRound size={9} aria-hidden className="shrink-0" />
                {speakerShort(sentence.speaker)}
              </span>
            </Hint>
          )}
        </div>
        {/* 操作浮层不参与栅格宽度:平时完全不占正文空间,悬停或键盘聚焦时才出现。 */}
        <div className="pointer-events-none absolute right-1 top-1 z-10 flex items-center gap-0.5 rounded-md border border-border bg-popover/95 p-0.5 opacity-0 shadow-sm transition-opacity group-hover/sentence:pointer-events-auto group-hover/sentence:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100">
          {canSplit && (
            <IconButton
              unstyled
              className="inline-flex size-5 cursor-pointer items-center justify-center rounded-sm border-0 bg-transparent p-0 text-muted-foreground hover:bg-[color-mix(in_oklab,var(--primary)_12%,transparent)] hover:text-primary"
              label={t("splitSentenceOut")}
              hint={t("splitSentenceOutHint")}
              onClick={() => actions.splitSentenceOut(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
            >
              <SplitSquareVertical size={12} />
            </IconButton>
          )}
          <IconButton
            unstyled
            className="inline-flex size-5 cursor-pointer items-center justify-center rounded-sm border-0 bg-transparent p-0 text-muted-foreground hover:bg-[color-mix(in_oklab,var(--destructive)_12%,transparent)] hover:text-destructive"
            label={t("cutSentence")}
            hint={t("cutSentenceHint")}
            onClick={() => actions.cutSentence(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
          >
            <X size={12} />
          </IconButton>
        </div>
        <p className="m-0 min-w-0 whitespace-normal text-ui-md leading-6 [overflow-wrap:anywhere]">
          {sentence.tokens.length > 0
            ? sentence.tokens.map((token, index) => {
                const tokenKey = `${sentence.clipId}:${sentence.segmentId}:${index}`;
                const flatIndex = flatIndexByKey.get(tokenKey) ?? -1;
                // 问"这个词落在时间线的哪一段",而不是"当前是哪个片段" ——
                // 视频轨和音频轨时间上重叠,而逐字稿来自音频片段,按"第一个覆盖
                // 播放头的片段"去比对,命中的永远是排在前面的视频片段。
                const current = currentSet.has(tokenKey);
                const classes = cn(
                  // 悬停用**中性**灰。此前用 `bg-accent`,而深色下 accent 是 #2b2542 ——
                  // 一块紫色,和播放头所在词的高亮长得一模一样:鼠标扫过哪个词,哪个词就
                  // 像"正在播"。一种颜色不能同时表示两件事。
                  // **横向不留内边距**:中文每个词就是一两个字,左右各 1px 会把
                  // 「喂喂喂喂喂」拆成「喂 喂 喂 喂 喂」—— 一句话被排版成了五个字。
                  // 纵向留着:行内元素的上下内边距不参与布局,只把高亮的底色撑高一点。
                  "m-0 inline cursor-pointer rounded-[3px] border-0 bg-transparent px-0 py-px text-foreground [font:inherit] [box-decoration-break:clone] hover:bg-[color-mix(in_oklab,var(--foreground)_10%,transparent)]",
                  isFillerToken(token.text, fillerKinds) && "bg-[color-mix(in_oklab,#eab308_20%,transparent)]",
                  // 播放头所在的词:实心一点、字重一点,不再拿 1px 硬阴影当下划线 ——
                  // 那道线在换行处断开,看着像输入框的边。
                  current && "bg-[color-mix(in_oklab,var(--primary)_28%,transparent)] font-medium",
                  // 标记要删的词:8% 在深色下几乎看不出来,全靠那道删除线撑着。
                  selected.has(tokenKey) &&
                    "bg-[color-mix(in_oklab,var(--destructive)_16%,transparent)] text-muted-foreground line-through [text-decoration-color:var(--destructive)] [text-decoration-thickness:1.5px]",
                );
                return (
                  <button
                    key={tokenKey}
                    type="button"
                    className={classes}
                    data-flat={flatIndex}
                    onPointerDown={(event) => {
                      if (event.button === 0) actions.beginWordDrag(flatIndex);
                    }}
                    onDoubleClick={() => actions.toggleToken(tokenKey, sentence.clipId, token.start_time, token.end_time)}
                  >
                    {token.text}
                  </button>
                );
              })
            : (
                <Hint label={t("markSentenceHint")}>
                  <button
                    type="button"
                    className={cn(
                      "m-0 inline cursor-pointer rounded-[3px] border-0 bg-transparent px-0 py-px text-left text-foreground [font:inherit] [box-decoration-break:clone] hover:bg-[color-mix(in_oklab,var(--foreground)_10%,transparent)]",
                      selected.has(`${key}:all`) &&
                        "bg-[color-mix(in_oklab,var(--destructive)_16%,transparent)] text-muted-foreground line-through [text-decoration-color:var(--destructive)] [text-decoration-thickness:1.5px]",
                    )}
                    onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
                    onDoubleClick={() => actions.toggleToken(`${key}:all`, sentence.clipId, sentence.srcStart, sentence.srcEnd)}
                  >
                    {sentence.text}
                  </button>
                </Hint>
              )}
        </p>
      </div>
    );
  }
});

export function TranscriptPanel({
  sequence,
  onCutSegment,
  onCutRanges,
  onSplitPoints,
  onGenerateSubtitles,
  generatingSubtitles,
}: {
  sequence: Sequence;
  onCutSegment: (clipId: string, srcStart: number, srcEnd: number) => void;
  /** 从这份逐字稿生成字幕轨。**不带语言** —— 翻译是字幕那一页的事(见 SubtitlePanel)。 */
  onGenerateSubtitles?: () => void;
  generatingSubtitles?: boolean;
  onCutRanges?: (cuts: Array<{ clipId: string; ranges: CutRange[] }>) => void;
  // Split (not remove) the named clips at these source-time points → 按句切分 / 单句独立 / 切一刀.
  onSplitPoints?: (cuts: Array<{ clipId: string; srcTimes: number[] }>) => void;
}) {
  const t = useI18n();
  const s = useNoteStrings();
  const qc = useQueryClient();
  const [selected, setSelected] = React.useState<TokenSelection>(new Map());
  const [showSilences, setShowSilences] = React.useState(false);
  const [asrJobId, setAsrJobId] = React.useState<string | null>(null);
  const [asrError, setAsrError] = React.useState<string | null>(null);

  // 逐字稿覆盖 V1(主叙事画面)加音轨(口播/旁白常在 A1)—— 不算配音轨和分离出来的派生素材,
  // 同一段素材在视频轨和分离音频上只算一份(见 transcriptSourceClips,生成字幕用的是同一份)。
  const videoClips = React.useMemo(() => transcriptSourceClips(sequence.tracks ?? []), [sequence]);
  // **按素材类型筛,不按轨道类型。** 视频轨上完全可以放图片,而图片没有声音:不筛的话一张静图排在
  // 最前时,「AI 转写」拿它去调接口,只换回一句「只有视频或音频素材可以转写」。
  const assetIds = React.useMemo(
    () => [
      ...new Set(
        videoClips
          .filter((clip) => kindHasSound(clip.asset_kind))
          .map((clip) => clip.asset_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ],
    [videoClips],
  );

  const transcriptQueries = useQueries({
    queries: assetIds.map((assetId) => ({
      queryKey: transcriptKeys.of(assetId),
      queryFn: () => getAssetTranscript(assetId),
      staleTime: 30_000,
    })),
  });

  //: 依赖写成**定长**的一串:各条逐字稿何时取回的时间戳拼成一个字符串。此前是 `[assetIds, ...每条的 data]` ——
  //: 素材从 0 条变成 7 条时依赖数组的长度跟着变,React 每次打开剪辑页都在控制台报「changed size between renders」。
  const transcriptStamp = transcriptQueries.map((query) => query.dataUpdatedAt).join(",");
  const segmentsByAsset = React.useMemo(() => {
    const map = new Map<string, SegmentLike[]>();
    transcriptQueries.forEach((query, index) => {
      if (query.data) map.set(assetIds[index], transcriptSegmentsFromApi(query.data.segments));
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetIds, transcriptStamp]);

  const projected = React.useMemo(
    () => projectTranscript(videoClips, segmentsByAsset),
    [videoClips, segmentsByAsset],
  );
  const silences = React.useMemo(
    () => (showSilences ? detectSilences(videoClips, segmentsByAsset) : []),
    [showSilences, videoClips, segmentsByAsset],
  );
  //: 口癖:哪几类算(歧义词默认不算,见 FILLER_CATEGORIES),以及逐字稿里每一处 —— 选中之前先给看(FillerPicker)。
  const [fillerKinds, setFillerKinds] = React.useState<Set<FillerCategoryId>>(() => new Set(DEFAULT_FILLER_CATEGORIES));
  const fillers = React.useMemo(() => fillerMatches(projected), [projected]);
  // 只有一个说话人时,那个标签每行都一样 —— 不是信息,是噪声。
  const showSpeakers = React.useMemo(
    () => speakersAreMeaningful(projected.map((item) => item.speaker)),
    [projected],
  );

  // Selection keys go stale whenever the sequence changes underneath us.
  React.useEffect(() => setSelected(new Map()), [sequence.revision]);

  // ASR:**把这条时间线上所有转得了的素材都转一遍**,一个接一个。
  //
  // 此前只转第一个 —— 而下面的逐字稿是把所有素材的结果拼起来显示的,读是多个、写是一个,
  // 这不一致。串行是因为后端本来就有并发闸(转写吃满 CPU/显存),并排发只会排队,还让
  // "是哪一个失败了"变难说清。
  //
  // 一个失败不拖累其余:没有音轨的素材(屏幕录制、无声的生成视频)会被后端拒绝,那是正常输入,
  // 不该让整条队列停在那儿。失败的攒起来,最后一并说。
  const [queue, setQueue] = React.useState<string[]>([]);
  const [queueTotal, setQueueTotal] = React.useState(0);
  const [failures, setFailures] = React.useState<string[]>([]);
  // 转写语言。**默认空 = 让引擎自己判** —— FunASR 的 SenseVoice 支持 50+ 语种,WhisperX 也自带
  // 检测,所以不必先问用户。留着这个入参是给"我知道它是什么语言、别猜"的场合用的(接口收
  // ?language=),界面上暂不摆控件:多数时候它只会变成一个要人回答的多余问题。
  const [asrLanguage] = React.useState("");
  const hasTranscript = React.useCallback(
    (assetId: string) => (segmentsByAsset.get(assetId)?.length ?? 0) > 0,
    [segmentsByAsset],
  );
  // 还没转过的那几段。**已有逐字稿的不再转**(见 pendingTranscribeIds),同一素材用两次只算一段。
  const pendingIds = React.useMemo(() => pendingTranscribeIds(assetIds, hasTranscript), [assetIds, hasTranscript]);
  // 逐字稿还在读的时候不知道哪些已经转过 —— 这时点下去会把转过的再转一遍(真实的耗时调用)。
  const transcriptsLoading = transcriptQueries.some((query) => query.isLoading);
  // 有要转的才去问引擎在不在:问一次要在后端起子进程探 torch,没有要转的就不必惊动它。
  // 和设置页「转写」同一个缓存键 —— 在那边装好,回到这里就跟着变。
  const asrModels = useQuery({
    queryKey: ["asr-models"],
    queryFn: listAsrModels,
    enabled: pendingIds.length > 0,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const noAsrEngine = asrEngineMissing(asrModels.data);

  const startAsr = useMutation({
    mutationFn: (assetId: string) => transcribeAsset(assetId, asrLanguage),
    onSuccess: (job) => {
      setAsrError(null);
      setAsrJobId(job.id);
    },
    // 这一个转不了(多半是没有音轨)就跳过它,继续下一个。
    onError: (error) => {
      setFailures((prev) => [...prev, String((error as Error).message)]);
      setQueue((prev) => prev.slice(1));
    },
  });

  // 队头有活、又没有在跑的任务时,发下一个。
  React.useEffect(() => {
    if (asrJobId || startAsr.isPending || queue.length === 0) return;
    startAsr.mutate(queue[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue, asrJobId, startAsr.isPending]);

  const startAll = React.useCallback(() => {
    const pending = pendingIds;
    // 全都转过了时两颗按钮本身就是禁用的(见 allTranscribed),这里不会走到。
    if (pending.length === 0) return;
    setFailures([]);
    setAsrError(null);
    setQueueTotal(pending.length);
    setQueue(pending);
  }, [pendingIds]);
  // **换个页面再回来,进度还在。**
  //
  // 队列活在组件的 state 里,一卸载就没了 —— 而任务在后端还跑着。此前回来看到的是一个安静的
  // 「AI 转写」按钮,像是什么都没发生过;再点一次会再排一遍队。
  //
  // 状态的真相在服务端(它有这些任务),所以挂载时去认领:这个工作区里还在跑的转写任务。
  const runningTranscribes = useQuery({
    queryKey: ["jobs", sequence.workspace_id, "transcribe"],
    queryFn: () => listJobs(sequence.workspace_id, { kind: "transcribe" }),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => job.status === "running" || job.status === "queued") ? 1500 : false,
  });
  React.useEffect(() => {
    if (asrJobId || queue.length > 0) return;
    const live = (runningTranscribes.data ?? []).find(
      (job) => job.status === "running" || job.status === "queued",
    );
    if (live) setAsrJobId(live.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningTranscribes.data]);

  /**
   * **这些素材上有没有正在跑的转写 —— 问后端,不问自己。**
   *
   * 原先只认 `asrJobId`(这个面板自己发起的那一次):从素材页发起、或者切走再回来,面板就一无所知,
   * 于是转写正跑着,它却显示「时间线上的素材还没有转写结果」—— 一句在字面上成立、但把用户引向
   * "是不是没点上"的话。任务的真相在后端。
   */
  const transcribeJobs = useQuery({
    queryKey: ["jobs", sequence.workspace_id, "transcribe"],
    queryFn: () => listJobs(sequence.workspace_id, { kind: "transcribe" }),
    // **一直轮询,不是"有在跑才轮询"。** 后者是个死结:挂载那一刻没有在跑的任务,它就再也不查了,
    // 而"转写是在面板挂载之后才开始的"恰恰是最常见的情形 —— 从素材页发起,或者切一下标签页
    // (这个面板在标签里,切走即卸载)。跑起来之后收紧到 1.5 秒,好让进度看着是活的。
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 1500 : 4000,
    refetchOnWindowFocus: true,
  });
  const runningJob = React.useMemo(() => {
    const ids = new Set(assetIds);
    return (transcribeJobs.data ?? []).find(
      (job) =>
        (job.status === "queued" || job.status === "running") &&
        ids.has(String((job.payload as { asset_id?: string } | undefined)?.asset_id ?? "")),
    );
  }, [transcribeJobs.data, assetIds]);

  // 后端那边跑完了,这边得**自己**去把结果取回来 —— 否则又变成"跑完了界面不知道",
  // 用户只能靠切页面或刷新触发一次重取。跟着"有没有在跑"这件事的边沿走:由跑到不跑就重取。
  const wasRunning = React.useRef(false);
  React.useEffect(() => {
    const now = Boolean(runningJob);
    if (wasRunning.current && !now) {
      assetIds.forEach((assetId) => void qc.invalidateQueries({ queryKey: transcriptKeys.of(assetId) }));
    }
    wasRunning.current = now;
  }, [runningJob, assetIds, qc]);

  const asrJob = useQuery({
    queryKey: ["job", asrJobId],
    enabled: Boolean(asrJobId),
    queryFn: () => getJob(asrJobId!),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return jobSettled(status) ? false : 1500;
    },
    refetchOnWindowFocus: true,
  });
  React.useEffect(() => {
    if (asrJob.data?.status === "succeeded") {
      setAsrJobId(null);
      setQueue((prev) => prev.slice(1));
      void qc.invalidateQueries({ queryKey: transcriptKeys.all() });
    } else if (asrJob.data?.status === "failed") {
      setAsrJobId(null);
      setFailures((prev) => [...prev, asrJob.data?.error ?? t("transcribeFailed")]);
      setQueue((prev) => prev.slice(1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asrJob.data?.status]);

  // 队列跑完了才把失败一并说出来 —— 中途弹一条会盖住后面还在跑的进度。
  React.useEffect(() => {
    if (queue.length === 0 && !asrJobId && failures.length > 0) {
      setAsrError(failures.join("\n"));
      setFailures([]);
      setQueueTotal(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue.length, asrJobId, failures.length]);
  const asrRunning = startAsr.isPending || Boolean(asrJobId) || queue.length > 0;
  // 能转的都转过了:按钮禁用,并用普通的说明文字说一声 —— 这是正常状态,不是出错,不该是红字;
  // 而一颗点下去什么都不发生的按钮比一句话更让人困惑。
  const allTranscribed = assetIds.length > 0 && pendingIds.length === 0;
  // 进度按**素材**数报,不按任务数 —— 用户看的是"这条时间线转到哪了"。
  const asrProgress = queueTotal > 1 ? `${Math.min(queueTotal - queue.length + 1, queueTotal)}/${queueTotal}` : "";
  const transcribeButton = assetIds.length > 0 && (
    // 已经有逐字稿之后,这颗按钮转的是**后来加上来的**那几段 —— 数字让人知道点下去会转什么。
    <Hint
      label={allTranscribed ? undefined : t("transcribePendingHint").replace("{n}", String(pendingIds.length))}
      disabledReason={allTranscribed ? t("transcribeAllDone") : undefined}
    >
      <button
        type="button"
        className={PILL}
        disabled={asrRunning || noAsrEngine || transcriptsLoading || allTranscribed}
        onClick={startAll}
      >
        {/* 按钮只放**短**的:一个动词 + 进度。后端那句状态("funasr 转写中(首次会自动下载模型)")
            可以很长,塞进这个为四个字做的胶囊里会折成两行、把图标挤到一边 —— 它属于下面那行状态,
            不属于控件本身。 */}
        {asrRunning ? <Loader2 size={12} className="shrink-0 animate-mosael-spin" /> : <Mic size={12} className="shrink-0" />}
        {/* 已有逐字稿、又有没转过的素材时,**把数字写进动作里**:「转写其余 12 段」。
            此前是「AI 转写」后面挂一个光秃秃的 12 —— 同一排「静音」「口癖」后面的数字是"点下去会选中几处",
            它却是"还有几个素材没转写",没有悬停就读不出来,用户只能问这个数字是什么意思。 */}
        <span className="whitespace-nowrap">
          {asrRunning
            ? `${t("transcribing")}${asrProgress ? ` ${asrProgress}` : ""}`
            : projected.length > 0 && pendingIds.length > 0
              ? t("transcribePending").replace("{n}", String(pendingIds.length))
              : t("aiTranscribe")}
        </span>
      </button>
    </Hint>
  );
  // 引擎没装:说清楚,并给出路 —— 管理员直达管理页「引擎」,成员被告知由部署管理员安装(EngineNotice)。
  // 按钮同时禁用 —— 点下去只会排一个注定失败的任务。
  const engineNotice = noAsrEngine && pendingIds.length > 0 && (
    <EngineNotice message={t("transcribeNoEngine")} className="text-left" />
  );

  const toggleToken = (key: string, clipId: string, srcStart: number, srcEnd: number) => {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(key)) next.delete(key);
      else next.set(key, { clipId, srcStart, srcEnd });
      return next;
    });
  };

  const groupCuts = (entries: Array<{ clipId: string; srcStart: number; srcEnd: number }>) => {
    const byClip = new Map<string, CutRange[]>();
    for (const entry of entries) {
      const ranges = byClip.get(entry.clipId) ?? [];
      ranges.push({ srcStart: entry.srcStart, srcEnd: entry.srcEnd });
      byClip.set(entry.clipId, ranges);
    }
    return [...byClip.entries()].map(([clipId, ranges]) => ({ clipId, ranges }));
  };

  const applySelected = () => {
    if (!onCutRanges || selected.size === 0) return;
    onCutRanges(groupCuts([...selected.values()]));
    setSelected(new Map());
  };

  const selectFillers = (chosen: FillerMatch[]) => {
    setSelected((current) => {
      const next = new Map(current);
      for (const match of chosen) {
        next.set(match.key, { clipId: match.clipId, srcStart: match.srcStart, srcEnd: match.srcEnd });
      }
      return next;
    });
  };

  const selectAllSilences = () => {
    setSelected((current) => {
      const next = new Map(current);
      for (const gap of silences) {
        next.set(`${gap.clipId}:sil:${gap.srcStart}`, {
          clipId: gap.clipId,
          srcStart: gap.srcStart,
          srcEnd: gap.srcEnd,
        });
      }
      return next;
    });
  };

  // 文档视图:句子与静音间隙按时间线顺序交织成一篇连续文本;切开的一句两半挨着(见 transcriptDocument)。
  const docItems = React.useMemo(
    () => transcriptDocument(projected, showSilences ? silences : []),
    [projected, silences, showSilences],
  );

  // 卡拉OK定位:播放头映射回当前片段的源时间,命中的词高亮。
  //
  // **这里不订阅播放头本身。** 播放时它一秒变二十几次,而面板关心的只是「当前是哪一句、哪个词、
  // 播放头下有没有片段」—— 一个词要几百毫秒才换一次。此前每一帧都把上万个词按钮整个重渲。
  // 选择器只返回这些低频派生值(字符串 / 布尔,=== 可比),值不变就不重渲。
  const clipById = React.useMemo(() => new Map(videoClips.map((clip) => [clip.id, clip])), [videoClips]);
  const overClip = useEditorStore((state) => activeSourceAt(videoClips, state.playhead) !== null);
  const activeSentenceKey = useEditorStore((state) => activeSentenceKeyAt(projected, state.playhead));

  const selectedSeconds = React.useMemo(() => {
    let total = 0;
    for (const entry of selected.values()) {
      const speed = clipById.get(entry.clipId)?.speed || 1;
      total += (entry.srcEnd - entry.srcStart) / speed;
    }
    return total;
  }, [selected, clipById]);

  // 文档序的扁平词表:拖选按它计算范围,单击按它定位播放头。
  const docTokens = React.useMemo(() => {
    const list: Array<{ key: string; clipId: string; srcStart: number; srcEnd: number; timelineAt: number }> = [];
    for (const item of docItems) {
      if (item.kind !== "sentence") continue;
      const sentence = item.sentence;
      const clip = clipById.get(sentence.clipId);
      const speed = clip?.speed || 1;
      sentence.tokens.forEach((token, index) => {
        list.push({
          key: `${sentence.clipId}:${sentence.segmentId}:${index}`,
          clipId: sentence.clipId,
          srcStart: token.start_time,
          srcEnd: token.end_time,
          timelineAt: clip ? clip.timeline_start + (token.start_time - clip.src_in) / speed : sentence.timelineStart,
        });
      });
    }
    return list;
  }, [docItems, clipById]);
  const flatIndexByKey = React.useMemo(
    () => new Map(docTokens.map((token, index) => [token.key, index])),
    [docTokens],
  );
  const docTokensRef = React.useRef(docTokens);
  docTokensRef.current = docTokens;
  // 词的时间线区间按起点排好,播放头下是哪几个词靠二分找(见 currentTokenKeys)。
  const tokenSpans = React.useMemo(() => buildTokenSpans(docItems, clipById), [docItems, clipById]);
  const currentTokens = useEditorStore((state) => currentTokenKeys(tokenSpans, state.playhead));

  // 交互模型(Descript/剪映):单击 = 定位播放头;按住拖过多个词 = 标记
  // 范围(在既有选择上追加);双击 = 单词标记/取消。
  const dragRef = React.useRef<{ anchor: number; base: TokenSelection; moved: boolean } | null>(null);
  const beginWordDrag = (flatIndex: number) => {
    dragRef.current = { anchor: flatIndex, base: new Map(selected), moved: false };
  };
  const dragOverWord = (flatIndex: number) => {
    const drag = dragRef.current;
    if (!drag || (flatIndex === drag.anchor && !drag.moved)) return;
    drag.moved = true;
    const [from, to] = [Math.min(drag.anchor, flatIndex), Math.max(drag.anchor, flatIndex)];
    const next = new Map(drag.base);
    for (let index = from; index <= to; index += 1) {
      const token = docTokensRef.current[index];
      next.set(token.key, { clipId: token.clipId, srcStart: token.srcStart, srcEnd: token.srcEnd });
    }
    setSelected(next);
  };
  React.useEffect(() => {
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag && !drag.moved) {
        const token = docTokensRef.current[drag.anchor];
        if (token) useEditorStore.getState().setPlayhead(token.timelineAt);
      }
    };
    window.addEventListener("pointerup", onUp);
    return () => window.removeEventListener("pointerup", onUp);
  }, []);

  // 按句切分:每个片段在其句子起点处切开,每句(含其后停顿)成为独立片段。
  const splitBySentence = () => {
    if (!onSplitPoints) return;
    const byClip = new Map<string, number[]>();
    for (const sentence of projected) {
      const list = byClip.get(sentence.clipId) ?? [];
      list.push(sentence.srcStart);
      byClip.set(sentence.clipId, list);
    }
    const cuts = [...byClip.entries()].map(([clipId, srcTimes]) => ({ clipId, srcTimes }));
    if (cuts.length) onSplitPoints(cuts);
  };
  // 单句独立成片段:在句首、句尾各切一刀,把该句从原片段切出来。
  const splitSentenceOut = (clipId: string, srcStart: number, srcEnd: number) => {
    onSplitPoints?.([{ clipId, srcTimes: [srcStart, srcEnd] }]);
  };
  // 在播放头当前词处切一刀(单点)。播放头在点下去那一刻读,不订阅。
  const splitAtPlayhead = () => {
    const activeSrc = activeSourceAt(videoClips, useEditorStore.getState().playhead);
    if (onSplitPoints && activeSrc) onSplitPoints([{ clipId: activeSrc.clipId, srcTimes: [activeSrc.src] }]);
  };

  // 行的回调身份要稳定,memo 过的行才跳得过去;调用时读最新的闭包。
  const latestActions = React.useRef({ beginWordDrag, toggleToken, splitSentenceOut, onCutSegment });
  React.useLayoutEffect(() => {
    latestActions.current = { beginWordDrag, toggleToken, splitSentenceOut, onCutSegment };
  });
  const rowActions = React.useMemo<TranscriptRowActions>(
    () => ({
      beginWordDrag: (flatIndex) => latestActions.current.beginWordDrag(flatIndex),
      toggleToken: (key, clipId, srcStart, srcEnd) => latestActions.current.toggleToken(key, clipId, srcStart, srcEnd),
      splitSentenceOut: (clipId, srcStart, srcEnd) => latestActions.current.splitSentenceOut(clipId, srcStart, srcEnd),
      cutSentence: (clipId, srcStart, srcEnd) => latestActions.current.onCutSegment(clipId, srcStart, srcEnd),
    }),
    [],
  );

  // 长逐字稿只渲染视口里的几十句(一小时是上万个词按钮)。
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const listRef = React.useRef<HTMLDivElement | null>(null);
  //: 量高用的键:同一个 key 但内容变了(重断句、改了词)不能沿用旧高度 —— 带上内容长度当签名,
  //: 变了就重新量。注意这不是 React key(那个还是 docItemKey,改字不该让行重挂载丢焦点)。
  const rowKeys = React.useMemo(
    () => docItems.map((item) => `${docItemKey(item)}:${item.kind === "sentence" ? item.sentence.text.length : 0}`),
    [docItems],
  );
  const rows = useVirtualRows({ keys: rowKeys, scrollRef, listRef, estimate: 56 });
  // 当前句换了就把它滚进视野。没渲染的行没有 DOM,所以按算出来的偏移滚,而不是 scrollIntoView。
  const revealRow = rows.reveal;
  React.useEffect(() => {
    if (activeSentenceKey) revealRow(rowKeys.indexOf(activeSentenceKey));
    // 只跟着「当前句」走:行高量到新值时不该把用户手动滚开的列表拽回来。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSentenceKey]);

  if (projected.length === 0) {
    // **正在转写时不说「还没有转写结果」。** 那句话字面上成立,却把用户引向"是不是没点上" ——
    // 而任务正跑着。转写中就说转写中,并把后端那句状态原样带上(下模型、装环境、第几段)。
    const busy = asrRunning || Boolean(runningJob);
    const busyMessage = asrJob.data?.message || runningJob?.message || "";
    return (
      <div className="m-auto grid max-w-[260px] content-center justify-items-center gap-1.5 px-3.5 py-5 text-center text-muted-foreground [&_p]:m-0 text-ui-sm [&_p]:leading-[1.55] [&>button]:mt-1">
        {busy ? <Loader2 size={18} className="animate-mosael-spin" /> : <MessageSquareText size={18} />}
        {/* **转写中只说一次。** 后端有具体状态("funasr 转写中(首次会自动下载模型)")就拿它当这一行,
            没有才说通用的「转写中…」。此前是一行「转写中…」、底下再一行后端的「……转写中……」,
            (更早还夹着一颗同样写着「转写中…」的禁用按钮)—— 同一件事说三遍。 */}
        <p className="text-ui-sm">{busy ? busyMessage || t("transcribing") : t("transcriptEmpty")}</p>
        {/* 空状态**给出动作,不只描述流程**:此前这里是一段"外部智能体可以通过 API 附加逐字稿"
            加一行流程说明,时间线上只有图片时连按钮都没有 —— 用户读完不知道下一步点哪。 */}
        {!busy && (
          <p className="max-w-[240px] text-ui-xs leading-[1.6] text-muted-foreground">
            {assetIds.length === 0
              ? t("transcriptNoAudioClips")
              : allTranscribed
                ? t("transcribeAllDone")
                : t("transcriptFlowHint").replace("{n}", String(pendingIds.length))}
          </p>
        )}
        {busy && asrProgress && <p className="text-ui-xs tabular-nums">{asrProgress}</p>}
        {!busy && assetIds.length > 0 && (
          <Button size="sm" disabled={noAsrEngine || transcriptsLoading || allTranscribed} onClick={startAll}>
            <Mic size={13} /> {t("transcribeTimeline")}
          </Button>
        )}
        {!busy && engineNotice}
        {asrError && <p className="m-0 max-w-[240px] whitespace-pre-line text-xs text-destructive">{asrError}</p>}
      </div>
    );
  }

  // **有选中就导选中,没选中就导全文。** 此前"没选中"落到播放头那一句 —— 于是把一份
  // 逐字稿搬进文档只能一句一句点。范围是一条规则,不是对话框里的又一个开关。
  const exportSegments = selected.size
    ? projected.filter(segment => [...selected.values()].some(token =>
        token.clipId === segment.clipId && token.srcStart < segment.srcEnd && token.srcEnd > segment.srcStart))
    : projected;
  const exportLines: NoteExportLine[] = exportSegments.map(segment => ({
    text: segment.text, start: segment.srcStart, end: segment.srcEnd,
    assetId: clipById.get(segment.clipId)?.asset_id ?? undefined,
  }));
  const exportVariants = noteExportVariants(exportLines, sequence.name, s);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap gap-2 border-b border-border px-3 py-3">
        {transcribeButton}
        <SaveToNote workspaceId={sequence.workspace_id} variants={exportVariants} className={PILL}
          label={selected.size ? s.excerpt : s.saveAll} />
        <Hint label={t("silencesHint")}>
          <button
            type="button"
            className={cn(PILL, showSilences && "border-[color-mix(in_oklab,var(--primary)_40%,var(--border))] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))] text-primary enabled:hover:text-primary")}
            aria-pressed={showSilences}
            onClick={() => setShowSilences((value) => !value)}
          >
            <AudioLines size={12} /> {t("silences")}
            {showSilences && silences.length > 0 && <em>{silences.length}</em>}
          </button>
        </Hint>
        <FillerPicker matches={fillers} enabled={fillerKinds} onEnabledChange={setFillerKinds} onSelect={selectFillers} />
        {onSplitPoints && (
          <>
            <Hint label={t("splitBySentenceHint")}>
              <button type="button" className={PILL} onClick={splitBySentence}>
                <Split size={12} /> {t("splitBySentence")}
              </button>
            </Hint>
            <Hint label={t("splitAtWordHint")} disabledReason={!overClip ? t("splitAtWordNoClip") : undefined}>
              <button
                type="button"
                className={PILL}
                onClick={splitAtPlayhead}
                disabled={!overClip}
              >
                <Scissors size={12} /> {t("splitAtWord")}
              </button>
            </Hint>
          </>
        )}
        {/* 逐字稿这边只做一件事:**把它变成字幕**。
            翻译是字幕的事(译的是已经成型的字幕),放在字幕那一页 —— 逐字稿是"这段音频说了什么"
            的记录,给它挂一个语言选择器,等于让人在记录里做译制。 */}
        {onGenerateSubtitles && (
          <Hint label={t("transcriptGenerateSubtitlesHint")}>
            <button type="button" className={PILL} disabled={generatingSubtitles} onClick={onGenerateSubtitles}>
              {generatingSubtitles ? <Loader2 size={12} className="animate-mosael-spin" /> : <Captions size={12} />}
              {t("transcriptGenerateSubtitles")}
            </button>
          </Hint>
        )}
        {showSilences && silences.length > 0 && (
          <Hint label={t("removeAllSilences")}>
            <button type="button" className={PILL} onClick={selectAllSilences}>
              {t("selectAllSilences")}
            </button>
          </Hint>
        )}
        <span className="ml-auto self-center whitespace-nowrap text-ui-xs text-muted-foreground">
          {t("transcriptStats")
            .replace("{n}", String(projected.length))
            .replace("{c}", String(projected.reduce((sum, item) => sum + item.text.length, 0)))}
        </span>
      </div>

      {/* 在已有逐字稿上再转(后来加上来的片段):状态和失败也要说出来。此前这两行只在空状态里渲染,
          于是在这里点「AI 转写」失败了、或者全都转过了,界面上什么都不发生。 */}
      {(engineNotice || asrError) && (
        <div className="grid gap-1.5 px-3 pt-2">
          {engineNotice}
          {asrError && <p className="m-0 whitespace-pre-line text-xs text-destructive">{asrError}</p>}
        </div>
      )}
      <p className="m-0 px-3 pb-0.5 pt-2 text-ui-xs leading-[1.5] text-muted-foreground/80">{t("transcriptUsage")}</p>
      <div
        ref={scrollRef}
        className="flex min-h-0 flex-1 select-none flex-col overflow-y-auto px-2 pb-3 pt-2"
        onPointerOver={(event) => {
          if (!(event.buttons & 1) || !dragRef.current) return;
          const el = (event.target as HTMLElement).closest("[data-flat]");
          if (el) dragOverWord(Number(el.getAttribute("data-flat")));
        }}
      >
        {/* 视口外的句子不渲染,上下留白按(量过的 / 估计的)行高占位。行间距放在每行自己的下内边距里
            (而不是容器的 gap),量到的行高才包含它,占位才对得上。 */}
        <div ref={listRef} className="flex flex-col" style={{ paddingTop: rows.padTop, paddingBottom: rows.padBottom }}>
          {docItems.slice(rows.start, rows.end).map((item) => {
            const key = docItemKey(item);
            return (
              <TranscriptRow
                key={key}
                rowRef={rows.measure(key)}
                item={item}
                active={key === activeSentenceKey}
                currentTokens={item.kind === "sentence" ? tokensOfSentence(currentTokens, item.sentence) : ""}
                selected={selected}
                showSpeakers={showSpeakers}
                flatIndexByKey={flatIndexByKey}
                canSplit={Boolean(onSplitPoints)}
                fillerKinds={fillerKinds}
                actions={rowActions}
              />
            );
          })}
        </div>
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-1.5 border-t border-border bg-panel px-2.5 py-1.5">
          <span className="flex-1 text-xs tabular-nums text-muted-foreground">
            {t("selectedWordsInfo").replace("{n}", String(selected.size)).replace("{s}", selectedSeconds.toFixed(1))}
          </span>
          <button type="button" className={PILL} onClick={() => setSelected(new Map())}>
            {t("clearSelection")}
          </button>
          <button type="button" className={cn(PILL, "border-[color-mix(in_oklab,var(--destructive)_35%,var(--border))] text-destructive enabled:hover:border-destructive enabled:hover:bg-[color-mix(in_oklab,var(--destructive)_8%,var(--background))] enabled:hover:text-destructive")} onClick={applySelected}>
            <Trash2 size={12} /> {t("removeSelectedWords")}
          </button>
        </div>
      )}
    </div>
  );
}

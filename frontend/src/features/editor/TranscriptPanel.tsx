import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Captions, Loader2, MessageSquareText, Mic, Scissors, Sparkles, Split, SplitSquareVertical, Trash2, X } from "lucide-react";

import { API_BASE, api, fetchJob, getAuthToken, transcribeAsset, type Job, type Sequence } from "@/api/client";
import { pendingTranscribeIds } from "@/features/editor/transcribeQueue";
import { tokenTimelineRange } from "@/domain/timeline/karaoke";
import { speakerChipStyle, speakerLabel, speakerShort, speakersAreMeaningful } from "@/features/editor/transcriptSpeakers";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { formatTimecode } from "@/domain/timeline/geometry";
import {
  detectSilences,
  isFillerToken,
  projectTranscript,
  type SegmentLike,
} from "@/domain/timeline/transcriptProjection";
import { PILL } from "@/features/editor/pill";
import { useEditorStore } from "@/stores/editorStore";
import { cn } from "@/lib/utils";

type TranscriptOut = components["schemas"]["TranscriptOut"];

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
  const qc = useQueryClient();
  const playhead = useEditorStore((state) => state.playhead);
  const [selected, setSelected] = React.useState<TokenSelection>(new Map());
  const [showSilences, setShowSilences] = React.useState(false);
  const [asrJobId, setAsrJobId] = React.useState<string | null>(null);
  const [asrError, setAsrError] = React.useState<string | null>(null);

  // 逐字稿覆盖 V1(主叙事画面)加所有音轨(口播/旁白常在 A1)。
  // **按素材类型挑,不按轨道类型挑。** 视频轨上完全可以放图片(AI 生成的静图就是这么落上去的),
  // 而图片没有声音 —— 此前这里收的是"第一条视频轨 + 所有音频轨"的全部片段,于是一张静图排在
  // 最前时,转写就拿它去调接口,回来一句「只有视频或音频素材可以转写」。
  const videoClips = React.useMemo(() => {
    const tracks = sequence.tracks ?? [];
    const mainVideo = tracks.find((item) => item.kind === "video");
    const audioTracks = tracks.filter((item) => item.kind === "audio");
    return [...(mainVideo?.clips ?? []), ...audioTracks.flatMap((track) => track.clips ?? [])];
  }, [sequence]);
  // **按素材类型筛,不按轨道类型。** 视频轨上完全可以放图片(AI 生成的静图就是这么落上去的),
  // 而图片没有声音。此前这里不筛,于是一张静图排在最前时,「AI 转写」拿它去调接口,回来一句
  // 「只有视频或音频素材可以转写」—— 而同一条时间线的音频轨上明明躺着一段录音。
  const assetIds = React.useMemo(
    () => [
      ...new Set(
        videoClips
          .filter((clip) => clip.asset_kind === "video" || clip.asset_kind === "audio")
          .map((clip) => clip.asset_id)
          .filter((id): id is string => Boolean(id)),
      ),
    ],
    [videoClips],
  );

  const transcriptQueries = useQueries({
    queries: assetIds.map((assetId) => ({
      queryKey: ["transcript", assetId],
      queryFn: async (): Promise<TranscriptOut | null> => {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/api/assets/${assetId}/transcript`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(await res.text());
        return (await res.json()) as TranscriptOut;
      },
      staleTime: 30_000,
    })),
  });

  const segmentsByAsset = React.useMemo(() => {
    const map = new Map<string, SegmentLike[]>();
    transcriptQueries.forEach((query, index) => {
      const transcript = query.data;
      if (transcript) {
        map.set(
          assetIds[index],
          (transcript.segments ?? []).map((segment) => ({
            id: segment.id,
            start_time: segment.start_time,
            end_time: segment.end_time,
            text: segment.text,
            speaker: segment.speaker,
            tokens: (segment.tokens ?? []).map((token) => ({
              start_time: token.start_time,
              end_time: token.end_time,
              text: token.text,
            })),
          })),
        );
      }
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetIds, ...transcriptQueries.map((query) => query.data)]);

  const projected = React.useMemo(
    () => projectTranscript(videoClips, segmentsByAsset),
    [videoClips, segmentsByAsset],
  );
  const silences = React.useMemo(
    () => (showSilences ? detectSilences(videoClips, segmentsByAsset) : []),
    [showSilences, videoClips, segmentsByAsset],
  );
  const fillerCount = React.useMemo(
    () => projected.reduce((count, item) => count + item.tokens.filter((tok) => isFillerToken(tok.text)).length, 0),
    [projected],
  );
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
    const pending = pendingTranscribeIds(assetIds, hasTranscript);
    setFailures([]);
    setAsrError(null);
    // 全都转过了 → 点下去什么都不会发生。**说一声** —— 一个没有反应的按钮比一句话更让人困惑,
    // 而这一屏此刻显示的正是那些已有的逐字稿,他要的东西其实已经在眼前了。
    if (pending.length === 0) {
      setAsrError(t("transcribeAllDone"));
      return;
    }
    setQueueTotal(pending.length);
    setQueue(pending);
  }, [assetIds, hasTranscript, t]);
  // **换个页面再回来,进度还在。**
  //
  // 队列活在组件的 state 里,一卸载就没了 —— 而任务在后端还跑着。此前回来看到的是一个安静的
  // 「AI 转写」按钮,像是什么都没发生过;再点一次会再排一遍队。
  //
  // 状态的真相在服务端(它有这些任务),所以挂载时去认领:这个工作区里还在跑的转写任务。
  const runningTranscribes = useQuery({
    queryKey: ["jobs", sequence.workspace_id, "transcribe"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${sequence.workspace_id}&kind=transcribe`),
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
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${sequence.workspace_id}&kind=transcribe`),
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
      assetIds.forEach((assetId) => void qc.invalidateQueries({ queryKey: ["transcript", assetId] }));
    }
    wasRunning.current = now;
  }, [runningJob, assetIds, qc]);

  const asrJob = useQuery({
    queryKey: ["job", asrJobId],
    enabled: Boolean(asrJobId),
    queryFn: () => fetchJob(asrJobId!),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 1500;
    },
    refetchOnWindowFocus: true,
  });
  React.useEffect(() => {
    if (asrJob.data?.status === "succeeded") {
      setAsrJobId(null);
      setQueue((prev) => prev.slice(1));
      void qc.invalidateQueries({ queryKey: ["transcript"] });
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
  // 进度按**素材**数报,不按任务数 —— 用户看的是"这条时间线转到哪了"。
  const asrProgress = queueTotal > 1 ? `${Math.min(queueTotal - queue.length + 1, queueTotal)}/${queueTotal}` : "";
  const transcribeButton = assetIds.length > 0 && (
    <button
      type="button"
      className={PILL}
      disabled={asrRunning}
      onClick={startAll}
    >
      {/* 按钮只放**短**的:一个动词 + 进度。后端那句状态("funasr 转写中(首次会自动下载模型)")
          可以很长,塞进这个为四个字做的胶囊里会折成两行、把图标挤到一边 —— 它属于下面那行状态,
          不属于控件本身。 */}
      {asrRunning ? <Loader2 size={12} className="shrink-0 animate-openstudio-spin" /> : <Mic size={12} className="shrink-0" />}
      <span className="whitespace-nowrap">
        {asrRunning ? `${t("transcribing")}${asrProgress ? ` ${asrProgress}` : ""}` : t("aiTranscribe")}
      </span>
    </button>
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

  const selectAllFillers = () => {
    setSelected((current) => {
      const next = new Map(current);
      projected.forEach((item) => {
        item.tokens.forEach((token, index) => {
          if (!isFillerToken(token.text)) return;
          next.set(`${item.clipId}:${item.segmentId}:${index}`, {
            clipId: item.clipId,
            srcStart: token.start_time,
            srcEnd: token.end_time,
          });
        });
      });
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

  // 文档视图:句子与静音间隙按时间线顺序交织成一篇连续文本。
  const docItems = React.useMemo(() => {
    const items: Array<
      | { kind: "sentence"; sentence: (typeof projected)[number] }
      | { kind: "silence"; gap: (typeof silences)[number] }
    > = projected.map((sentence) => ({ kind: "sentence" as const, sentence }));
    if (showSilences) {
      for (const gap of silences) items.push({ kind: "silence", gap });
    }
    return items.sort((a, b) => {
      const ta = a.kind === "sentence" ? a.sentence.timelineStart : a.gap.timelineStart;
      const tb = b.kind === "sentence" ? b.sentence.timelineStart : b.gap.timelineStart;
      return ta - tb;
    });
  }, [projected, silences, showSilences]);

  // 卡拉OK定位:播放头映射回当前片段的源时间,命中的词高亮。
  const clipById = React.useMemo(() => new Map(videoClips.map((clip) => [clip.id, clip])), [videoClips]);
  const activeSrc = React.useMemo(() => {
    for (const clip of videoClips) {
      const end = clip.timeline_start + (clip.src_out - clip.src_in) / (clip.speed || 1);
      if (playhead >= clip.timeline_start && playhead < end) {
        return { clipId: clip.id, src: clip.src_in + (playhead - clip.timeline_start) * (clip.speed || 1) };
      }
    }
    return null;
  }, [videoClips, playhead]);

  const activeSentenceRef = React.useRef<HTMLDivElement | null>(null);
  const activeSentenceKey = React.useMemo(() => {
    const hit = projected.find((item) => playhead >= item.timelineStart && playhead < item.timelineEnd);
    return hit ? `${hit.clipId}:${hit.segmentId}` : null;
  }, [projected, playhead]);
  React.useEffect(() => {
    activeSentenceRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeSentenceKey]);

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
  // 在播放头当前词处切一刀(单点)。
  const splitAtPlayhead = () => {
    if (onSplitPoints && activeSrc) onSplitPoints([{ clipId: activeSrc.clipId, srcTimes: [activeSrc.src] }]);
  };

  if (projected.length === 0) {
    // **正在转写时不说「还没有转写结果」。** 那句话字面上成立,却把用户引向"是不是没点上" ——
    // 而任务正跑着。转写中就说转写中,并把后端那句状态原样带上(下模型、装环境、第几段)。
    const busy = asrRunning || Boolean(runningJob);
    const busyMessage = asrJob.data?.message || runningJob?.message || "";
    return (
      <div className="m-auto grid max-w-[260px] content-center justify-items-center gap-1.5 px-3.5 py-5 text-center text-muted-foreground [&_p]:m-0 [&_p]:text-xs [&_p]:leading-[1.55] [&>button]:mt-1">
        {busy ? <Loader2 size={18} className="animate-openstudio-spin" /> : <MessageSquareText size={18} />}
        <p>{busy ? t("transcribing") : t("transcriptEmpty")}</p>
        {!busy && (
          <p className="max-w-[220px] text-ui-xs leading-[1.6] text-muted-foreground">{t("transcriptFlowHint")}</p>
        )}
        {transcribeButton}
        {/* 后端那句状态单独一行:它会长(下模型、装环境、第几段),而且**会变** —— 放在按钮里
            意味着控件的宽度跟着它跳。 */}
        {busy && busyMessage && (
          <p className="m-0 max-w-[240px] text-ui-xs leading-[1.5] text-muted-foreground">{busyMessage}</p>
        )}
        {asrError && <p className="m-0 max-w-[240px] whitespace-pre-line text-xs text-destructive">{asrError}</p>}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap gap-1.5 border-b border-border px-2 py-1.5">
        {transcribeButton}
        <button
          type="button"
          className={cn(PILL, showSilences && "border-[color-mix(in_oklab,var(--primary)_40%,var(--border))] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))] text-primary enabled:hover:text-primary")}
          title={t("silencesHint")}
          onClick={() => setShowSilences((value) => !value)}
        >
          <AudioLines size={12} /> {t("silences")}
          {showSilences && silences.length > 0 && <em>{silences.length}</em>}
        </button>
        <button type="button" className={PILL} title={t("fillersHint")} onClick={selectAllFillers} disabled={fillerCount === 0}>
          <Sparkles size={12} /> {t("fillers")}
          {fillerCount > 0 && <em>{fillerCount}</em>}
        </button>
        {onSplitPoints && (
          <>
            <button type="button" className={PILL} title={t("splitBySentenceHint")} onClick={splitBySentence}>
              <Split size={12} /> {t("splitBySentence")}
            </button>
            <button
              type="button"
              className={PILL}
              title={t("splitAtWordHint")}
              onClick={splitAtPlayhead}
              disabled={!activeSrc}
            >
              <Scissors size={12} /> {t("splitAtWord")}
            </button>
          </>
        )}
        {/* 逐字稿这边只做一件事:**把它变成字幕**。
            翻译是字幕的事(译的是已经成型的字幕),放在字幕那一页 —— 逐字稿是"这段音频说了什么"
            的记录,给它挂一个语言选择器,等于让人在记录里做译制。 */}
        {onGenerateSubtitles && (
          <button type="button" className={PILL} disabled={generatingSubtitles} title={t("transcriptGenerateSubtitlesHint")} onClick={onGenerateSubtitles}>
            {generatingSubtitles ? <Loader2 size={12} className="animate-openstudio-spin" /> : <Captions size={12} />}
            {t("transcriptGenerateSubtitles")}
          </button>
        )}
        {showSilences && silences.length > 0 && (
          <button type="button" className={PILL} title={t("removeAllSilences")} onClick={selectAllSilences}>
            {t("selectAllSilences")}
          </button>
        )}
        <span className="ml-auto self-center whitespace-nowrap text-ui-xs text-muted-foreground">
          {t("transcriptStats")
            .replace("{n}", String(projected.length))
            .replace("{c}", String(projected.reduce((sum, item) => sum + item.text.length, 0)))}
        </span>
      </div>

      <p className="m-0 px-3 pb-0.5 pt-2 text-ui-xs leading-[1.5] text-muted-foreground/80">{t("transcriptUsage")}</p>
      <div
        className="flex min-h-0 flex-1 select-none flex-col gap-1.5 overflow-y-auto px-2 pb-3 pt-2"
        onPointerOver={(event) => {
          if (!(event.buttons & 1) || !dragRef.current) return;
          const el = (event.target as HTMLElement).closest("[data-flat]");
          if (el) dragOverWord(Number(el.getAttribute("data-flat")));
        }}
      >
        {docItems.map((item) => {
          if (item.kind === "silence") {
            const gap = item.gap;
            const gapKey = `${gap.clipId}:sil:${gap.srcStart}`;
            return (
              // 静音块走**同一套栅格**:空掉时间码那一栏,正文那一栏自然对齐。
              // 此前是 `ml-[46px]` —— 一个照着时间码宽度手调出来的数,时间码一改就错开。
              <div key={gapKey} className={cn("grid items-center gap-2.5 pl-3", GUTTER)}>
                <span aria-hidden />
                <button
                  type="button"
                  className={cn(
                    "inline-flex cursor-pointer items-center gap-1 justify-self-start rounded-full border border-dashed border-border-strong bg-secondary px-[9px] py-px text-ui-xs text-muted-foreground hover:border-destructive hover:text-destructive",
                    selected.has(gapKey) && "border-destructive bg-[color-mix(in_oklab,var(--destructive)_8%,transparent)] text-destructive line-through",
                  )}
                  title={t("silenceGapHint")}
                  onClick={() => toggleToken(gapKey, gap.clipId, gap.srcStart, gap.srcEnd)}
                >
                  <AudioLines size={10} /> {gap.duration.toFixed(1)}s
                </button>
              </div>
            );
          }
          const sentence = item.sentence;
          const key = `${sentence.clipId}:${sentence.segmentId}`;
          const active = key === activeSentenceKey;
          return (
            <div
              key={key}
              ref={active ? activeSentenceRef : undefined}
              className={cn(
                "group/sentence relative grid items-baseline gap-2.5 rounded-md py-1 pl-3 transition-[background] duration-100 hover:bg-[color-mix(in_oklab,var(--foreground)_4%,transparent)]",
                GUTTER,
                // 右边给悬停按钮留位:一个是 22px,两个就得是 40px —— 少留的那 18px 会让
                // 「切一刀」压在正文最后几个字上,而那几个字是可以点的。
                onSplitPoints ? "pr-[40px]" : "pr-[22px]",
                active && "bg-[color-mix(in_oklab,var(--primary)_7%,transparent)]",
              )}
            >
              {/* 当前句的指示条:上下内缩的圆角条,而不是贴着行高的直角边框。
                  边框还得在每一行都占着 2px 透明位置(不占就会在切换时整行横跳),
                  一个绝对定位的条子既不参与布局,也能圆角。 */}
              {active && (
                <span aria-hidden className="pointer-events-none absolute bottom-[5px] left-[3px] top-[5px] w-[3px] rounded-full bg-primary" />
              )}
              <div className="grid justify-items-end gap-[3px]">
                <button
                  type="button"
                  className={cn(
                    "timecode cursor-pointer whitespace-nowrap border-0 bg-transparent p-0 text-ui-2xs leading-[1.9] tabular-nums text-muted-foreground hover:text-primary",
                    active && "font-medium text-primary",
                  )}
                  title={t("seekToSentence")}
                  onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
                >
                  {formatTimecode(sentence.timelineStart)}
                </button>
                {/* 说话人挪到时间码底下:它是这一句的**属性**,不是这一句的第一个词。
                    夹在正文里时它每行都把第一句话往右顶,还会跟着文字重排。 */}
                {showSpeakers && sentence.speaker && (
                  <span
                    className="max-w-full truncate rounded-full px-[6px] text-ui-2xs font-semibold leading-[15px] tabular-nums"
                    style={speakerChipStyle(sentence.speaker)}
                    title={speakerLabel(sentence.speaker)}
                  >
                    {speakerShort(sentence.speaker)}
                  </span>
                )}
              </div>
              {onSplitPoints && (
                <button
                  type="button"
                  className="absolute top-[6px] cursor-pointer rounded-sm border-0 bg-transparent p-0.5 leading-none text-transparent group-hover/sentence:text-muted-foreground right-[22px] hover:bg-[color-mix(in_oklab,var(--primary)_10%,transparent)] hover:text-primary!"
                  title={t("splitSentenceOutHint")}
                  aria-label={t("splitSentenceOut")}
                  onClick={() => splitSentenceOut(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
                >
                  <SplitSquareVertical size={11} />
                </button>
              )}
              <button
                type="button"
                className="absolute top-[6px] cursor-pointer rounded-sm border-0 bg-transparent p-0.5 leading-none text-transparent group-hover/sentence:text-muted-foreground right-0 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive!"
                title={t("cutSentenceHint")}
                aria-label={t("cutSentence")}
                onClick={() => onCutSegment(sentence.clipId, sentence.srcStart, sentence.srcEnd)}
              >
                <X size={11} />
              </button>
              <p className="m-0 text-ui-md leading-[1.9] [word-break:break-word]">
                {sentence.tokens.length > 0
                  ? sentence.tokens.map((token, index) => {
                      const tokenKey = `${sentence.clipId}:${sentence.segmentId}:${index}`;
                      const flatIndex = flatIndexByKey.get(tokenKey) ?? -1;
                      // 问"这个词落在时间线的哪一段",而不是"当前是哪个片段" ——
                      // 视频轨和音频轨时间上重叠,而逐字稿来自音频片段,按"第一个覆盖
                      // 播放头的片段"去比对,命中的永远是排在前面的视频片段。
                      const span = tokenTimelineRange(clipById.get(sentence.clipId), token);
                      const current = span !== null && playhead >= span[0] && playhead < span[1];
                      const classes = cn(
                        // 悬停用**中性**灰。此前用 `bg-accent`,而深色下 accent 是 #2b2542 ——
                        // 一块紫色,和播放头所在词的高亮长得一模一样:鼠标扫过哪个词,哪个词就
                        // 像"正在播"。一种颜色不能同时表示两件事。
                        // **横向不留内边距**:中文每个词就是一两个字,左右各 1px 会把
                        // 「喂喂喂喂喂」拆成「喂 喂 喂 喂 喂」—— 一句话被排版成了五个字。
                        // 纵向留着:行内元素的上下内边距不参与布局,只把高亮的底色撑高一点。
                        "m-0 inline cursor-pointer rounded-[3px] border-0 bg-transparent px-0 py-px text-foreground [font:inherit] [box-decoration-break:clone] hover:bg-[color-mix(in_oklab,var(--foreground)_10%,transparent)]",
                        isFillerToken(token.text) && "bg-[color-mix(in_oklab,#eab308_20%,transparent)]",
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
                            if (event.button === 0) beginWordDrag(flatIndex);
                          }}
                          onDoubleClick={() => toggleToken(tokenKey, sentence.clipId, token.start_time, token.end_time)}
                        >
                          {token.text}
                        </button>
                      );
                    })
                  : (
                      <button
                        type="button"
                        className={cn(
                          "m-0 inline cursor-pointer rounded-[3px] border-0 bg-transparent px-0 py-px text-left text-foreground [font:inherit] [box-decoration-break:clone] hover:bg-[color-mix(in_oklab,var(--foreground)_10%,transparent)]",
                          selected.has(`${key}:all`) &&
                            "bg-[color-mix(in_oklab,var(--destructive)_16%,transparent)] text-muted-foreground line-through [text-decoration-color:var(--destructive)] [text-decoration-thickness:1.5px]",
                        )}
                        title={t("markSentenceHint")}
                        onClick={() => useEditorStore.getState().setPlayhead(sentence.timelineStart)}
                        onDoubleClick={() => toggleToken(`${key}:all`, sentence.clipId, sentence.srcStart, sentence.srcEnd)}
                      >
                        {sentence.text}
                      </button>
                    )}
              </p>
            </div>
          );
        })}
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

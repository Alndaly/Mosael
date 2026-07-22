import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Download, Loader2, Plus, Redo2, Scissors, Type, Undo2 } from "lucide-react";

import { toast } from "sonner";

import {
  API_BASE,
  addTrack,
  api,
  generateSubtitles,
  getAuthToken,
  setSubtitleStyle,
  listFonts,
  uploadFont,
  deleteFont,
  cutClipRange,
  cutClipRanges,
  deleteClip,
  rippleDeleteClip,
  exportSequence,
  importAsset,
  insertClip,
  insertTextClip,
  moveClip,
  redoSequence,
  moveTrack,
  removeTrack,
  setTrackState,
  splitClip,
  splitClipAtPoints,
  setClipEffects,
  detachClipAudio,
  setClipGain,
  setClipSpeed,
  setClipTransform,
  setSequenceReframe,
  setClipText,
  setClipTexts,
  translateTexts,
  trimClip,
  undoSequence,
  type Asset,
  type Font,
  type Job,
  type Project,
  type Sequence,
  type Workspace,
} from "@/api/client";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { clipEnd } from "@/domain/timeline/geometry";
import { projectTranscript, type SegmentLike } from "@/domain/timeline/transcriptProjection";
import { useEditorStore } from "@/stores/editorStore";
import { ConfirmDialog } from "@/components/app/modals";
import { FontFaces } from "@/features/editor/FontFaces";
import { Inspector } from "./Inspector";
import { MediaPool } from "./MediaPool";
import { Monitor } from "./Monitor";
import { SubtitlePanel } from "./SubtitlePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoicePanel } from "./VoicePanel";
import { Timeline, trackAcceptsAsset, type TrimPayload } from "./timeline/Timeline";
import { cn } from "@/lib/utils";

export function EditorView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  if (!project) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2.5 [&>*]:shrink-0">
        <EmptyState icon={<Scissors size={22} />} title={t("emptyProject")} body={t("homeEmptyBody")} />
      </div>
    );
  }
  return <Editor workspace={workspace} project={project} />;
}

const PANEL_SIZES_KEY = "mibu.editor.panels.v2";

type LeftTab = "media" | "transcript" | "subtitle" | "voice";

/** 素材是缩略图列表,窄即可;逐字稿是整篇文档,需要宽栏。宽度按页签分别记忆。 */
const LEFT_WIDTH_BOUNDS: Record<LeftTab, { min: number; max: number; fallback: number }> = {
  media: { min: 180, max: 480, fallback: 252 },
  transcript: { min: 300, max: 620, fallback: 420 },
  subtitle: { min: 240, max: 520, fallback: 320 },
  voice: { min: 240, max: 520, fallback: 320 },
};

interface PanelSizes {
  left: Record<LeftTab, number>;
  right: number;
  timeline: number;
}

function clampLeft(tab: LeftTab, value: unknown): number {
  const bounds = LEFT_WIDTH_BOUNDS[tab];
  return Math.min(bounds.max, Math.max(bounds.min, Number(value) || bounds.fallback));
}

/** 紧凑断点(Global rhythm):≤1000px 时编辑器收成两列,检查器改为浮动抽屉。 */
function useCompact(): boolean {
  const query = "(max-width: 1000px)";
  return React.useSyncExternalStore(
    (notify) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", notify);
      return () => media.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
  );
}

function readPanelSizes(): PanelSizes {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PANEL_SIZES_KEY) ?? "{}");
    return {
      left: {
        media: clampLeft("media", parsed.left?.media),
        transcript: clampLeft("transcript", parsed.left?.transcript),
        subtitle: clampLeft("subtitle", parsed.left?.subtitle),
        voice: clampLeft("voice", parsed.left?.voice),
      },
      right: Math.min(480, Math.max(200, Number(parsed.right) || 264)),
      timeline: Math.min(560, Math.max(160, Number(parsed.timeline) || 252)),
    };
  } catch {
    return {
      left: { media: 252, transcript: 420, subtitle: 320, voice: 320 },
      right: 264,
      timeline: 252,
    };
  }
}

function Editor({ workspace, project }: { workspace: Workspace; project: Project }) {
  const t = useI18n();
  const qc = useQueryClient();
  const selectedClipId = useEditorStore((state) => state.selectedClipId);
  const [leftTab, setLeftTab] = React.useState<LeftTab>("media");
  const [panels, setPanels] = React.useState(readPanelSizes);
  const compact = useCompact();
  const leftWidth = Math.min(panels.left[leftTab], compact ? 300 : Number.POSITIVE_INFINITY);

  React.useEffect(() => {
    window.localStorage.setItem(PANEL_SIZES_KEY, JSON.stringify(panels));
  }, [panels]);

  const startPanelDrag = (which: "left" | "right" | "timeline") => (event: React.PointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...panels, left: { ...panels.left } };
    const tab = leftTab;
    const onMove = (moveEvent: PointerEvent) => {
      if (which === "left") {
        setPanels((current) => ({
          ...current,
          left: { ...current.left, [tab]: clampLeft(tab, origin.left[tab] + (moveEvent.clientX - startX)) },
        }));
      } else if (which === "right") {
        setPanels((current) => ({ ...current, right: Math.min(480, Math.max(200, origin.right - (moveEvent.clientX - startX))) }));
      } else {
        setPanels((current) => ({ ...current, timeline: Math.min(560, Math.max(160, origin.timeline - (moveEvent.clientY - startY))) }));
      }
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    // Hold the resize cursor and suppress selection for the whole drag — otherwise moving off
    // the 7px strip reverts the cursor and starts selecting whatever is underneath.
    document.body.style.cursor = which === "timeline" ? "row-resize" : "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}&project_id=${project.id}`),
  });
  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  const sequence = sequences.data?.[0] ?? null;

  // Uploaded subtitle fonts are workspace-level, like assets and LUTs.
  const fonts = useQuery({
    queryKey: ["fonts", workspace.id],
    queryFn: () => listFonts(workspace.id),
    staleTime: 5 * 60_000,
  });
  const refreshFonts = () => qc.invalidateQueries({ queryKey: ["fonts", workspace.id] });
  const uploadFontMutation = useMutation({
    mutationFn: (file: File) => uploadFont({ workspaceId: workspace.id, file }),
    onSuccess: () => void refreshFonts(),
    onError: (error: Error) => toast.error(error.message),
  });
  const deleteFontMutation = useMutation({
    mutationFn: (fontId: string) => deleteFont(fontId),
    onSuccess: () => void refreshFonts(),
    onError: (error: Error) => toast.error(error.message),
  });

  const refreshSequences = () => qc.invalidateQueries({ queryKey: ["sequences", project.id] });
  // Drag ops return the updated sequence — write it straight into the cache (no refetch
  // round-trip) so the clip lands at its final spot in the SAME commit the draft clears.
  // Awaiting an invalidate/refetch here instead left a stale-data window: the clip flashed
  // back to its original slot/track ("闪烁 / 换轨失败") and added drop lag.
  const applySequence = (updated: Sequence) =>
    qc.setQueryData<Sequence[]>(["sequences", project.id], (old) =>
      (old ?? []).map((item) => (item.id === updated.id ? updated : item)),
    );
  // Clearing the drag draft the instant a move settles renders ONE stale frame — the draft
  // (zustand) clears synchronously while the fresh sequence (react-query) propagates on a
  // deferred notification, so the clip flashes back to its old slot. Instead, arm this flag on
  // settle and let the effect below drop the draft on the render that actually shows the new
  // data. The draft pins the clip at its dropped spot the whole time → no flicker.
  // Live subtitle-style preview. The sliders used to persist only on release, so the monitor
  // showed nothing until the round-trip landed and you were styling blind. Hold the in-progress
  // style here, render the monitor from it, and let the committed value clear it.
  const [styleDraft, setStyleDraft] = React.useState<Record<string, unknown> | null>(null);
  const draftSettleRef = React.useRef(false);
  const settleWith = (updated: Sequence) => {
    applySequence(updated);
    draftSettleRef.current = true;
  };
  const resyncAfterFailedDrag = () => {
    draftSettleRef.current = true;
    void refreshSequences();
  };
  React.useEffect(() => {
    if (draftSettleRef.current) {
      draftSettleRef.current = false;
      useEditorStore.getState().setDragDraft(null);
    }
  }, [sequence]);

  const uploadAsset = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, projectId: project.id, file }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] }),
  });
  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, project_id: project.id, name: t("mainSequence") }),
      }),
    onSuccess: refreshSequences,
  });
  const insertClipMutation = useMutation({
    mutationFn: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) =>
      insertClip(sequence!.id, {
        track_id: args.trackId,
        asset_id: args.assetId,
        timeline_start: args.timelineStart,
        src_in: args.srcIn,
        src_out: args.srcOut,
      }),
    onSuccess: refreshSequences,
  });
  const moveClipMutation = useMutation({
    mutationFn: ({
      clipId,
      timelineStart,
      trackId,
      ripple,
    }: {
      clipId: string;
      timelineStart: number;
      trackId?: string;
      ripple?: boolean;
    }) => moveClip(sequence!.id, clipId, { timeline_start: timelineStart, track_id: trackId ?? null, ripple }),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const trimClipMutation = useMutation({
    mutationFn: ({ clipId, payload }: { clipId: string; payload: TrimPayload }) =>
      trimClip(sequence!.id, clipId, payload),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const deleteClipMutation = useMutation({
    mutationFn: (clipId: string) => deleteClip(sequence!.id, clipId),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const deleteClipsMutation = useMutation({
    mutationFn: async (clipIds: string[]) => {
      for (const clipId of clipIds) await deleteClip(sequence!.id, clipId);
    },
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const rippleDeleteMutation = useMutation({
    mutationFn: async (clipIds: string[]) => {
      // Later clips first so earlier ripples don't move the remaining targets.
      const byStart = new Map(allClips.map((clip) => [clip.id, clip.timeline_start]));
      const ordered = [...clipIds].sort((a, b) => (byStart.get(b) ?? 0) - (byStart.get(a) ?? 0));
      for (const clipId of ordered) await rippleDeleteClip(sequence!.id, clipId);
    },
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const addTrackMutation = useMutation({
    mutationFn: (kind: "video" | "audio" | "subtitle") => addTrack(sequence!.id, kind),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const moveTrackMutation = useMutation({
    mutationFn: ({ trackId, direction }: { trackId: string; direction: "up" | "down" }) =>
      moveTrack(sequence!.id, trackId, direction),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  // Drag a clip above the top video track → create a new video layer and drop it there.
  const moveClipToNewLayerMutation = useMutation({
    mutationFn: async ({ clipId, timelineStart }: { clipId: string; timelineStart: number }) => {
      const before = new Set((sequence!.tracks ?? []).map((tk) => tk.id));
      const updated = await addTrack(sequence!.id, "video");
      const created = (updated.tracks ?? []).find((tk) => tk.kind === "video" && !before.has(tk.id));
      if (!created) return updated;
      return moveClip(sequence!.id, clipId, { timeline_start: timelineStart, track_id: created.id });
    },
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const setTextMutation = useMutation({
    mutationFn: ({ clipId, text }: { clipId: string; text: string }) => setClipText(sequence!.id, clipId, text),
    onSuccess: (updated) => applySequence(updated),
  });
  const setTextsMutation = useMutation({
    mutationFn: (texts: { clip_id: string; text: string }[]) => setClipTexts(sequence!.id, texts),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const addSubtitleMutation = useMutation({
    mutationFn: async () => {
      let track = (sequence!.tracks ?? []).find((item) => item.kind === "subtitle" && !item.locked);
      if (!track) {
        const updated = await addTrack(sequence!.id, "subtitle");
        track = (updated.tracks ?? []).find((item) => item.kind === "subtitle");
      }
      if (!track) return;
      await insertTextClip(sequence!.id, {
        track_id: track.id,
        text: t("subtitleDefaultText"),
        timeline_start: useEditorStore.getState().playhead,
        duration: 2,
      });
    },
    onSuccess: refreshSequences,
  });
  // 一键从逐字稿生成字幕:拉齐所有视频/音频片段的转写,投影到时间线句子,批量插到字幕轨。
  // One pipeline, two entry points. Passing a target language inserts a translation step
  // between projecting the transcript and writing the cues — "翻译成字幕" is the same job as
  // "从逐字稿生成", not a parallel implementation of it.
  const generateSubtitlesMutation = useMutation({
    mutationFn: async (targetLang?: string) => {
      const seq = sequence!;
      const tracks = seq.tracks ?? [];
      const clips = [
        ...(tracks.find((tk) => tk.kind === "video")?.clips ?? []),
        ...tracks.filter((tk) => tk.kind === "audio").flatMap((tk) => tk.clips ?? []),
      ];
      const assetIds = [...new Set(clips.map((c) => c.asset_id).filter((id): id is string => Boolean(id)))];
      const token = getAuthToken();
      const fetched = await Promise.all(
        assetIds.map(async (id) => {
          const res = await fetch(`${API_BASE}/api/assets/${id}/transcript`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          });
          return res.ok ? await res.json() : null;
        }),
      );
      const segmentsByAsset = new Map<string, SegmentLike[]>();
      fetched.forEach((tr, index) => {
        if (tr) {
          segmentsByAsset.set(
            assetIds[index],
            (tr.segments ?? []).map((s: { id: string; start_time: number; end_time: number; text: string; speaker?: string }) => ({
              id: s.id,
              start_time: s.start_time,
              end_time: s.end_time,
              text: s.text,
              speaker: s.speaker,
              tokens: [],
            })),
          );
        }
      });
      const sentences = projectTranscript(clips, segmentsByAsset);
      if (sentences.length === 0) throw new Error(t("subtitleNoTranscript"));
      let track = tracks.find((tk) => tk.kind === "subtitle" && !tk.locked);
      if (!track) track = (await addTrack(seq.id, "subtitle")).tracks?.find((tk) => tk.kind === "subtitle");
      if (!track) throw new Error(t("subtitleNoTranscript"));
      // Translated in one batched, concurrent request — the same path the subtitle panel uses,
      // so a 200-cue transcript costs one round-trip's latency rather than 200.
      const texts = targetLang
        ? (await translateTexts(sentences.map((s) => s.text), targetLang)).translations
        : sentences.map((s) => s.text);
      const cues = sentences.map((s, i) => ({
        text: (texts[i] || s.text).trim() || s.text,
        timeline_start: s.timelineStart,
        duration: Math.max(0.4, s.timelineEnd - s.timelineStart),
      }));
      return { updated: await generateSubtitles(seq.id, track.id, cues), count: cues.length };
    },
    onSuccess: ({ updated, count }) => {
      applySequence(updated);
      toast.success(t("subtitleGenerated").replace("{n}", String(count)));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const subtitleStyleMutation = useMutation({
    mutationFn: (style: Record<string, unknown>) => setSubtitleStyle(sequence!.id, style),
    onSuccess: (updated) => {
      applySequence(updated);
      setStyleDraft(null);
    },
    onError: (error: Error) => {
      setStyleDraft(null); // drop the preview so the monitor snaps back to the saved style
      toast.error(error.message);
    },
  });
  // A populated track is only removed after the user confirms, and the prompt says how many
  // clips go with it — the backend refuses the unconfirmed call as a second line of defence.
  const [trackPendingRemoval, setTrackPendingRemoval] = React.useState<{ id: string; name: string; clips: number } | null>(
    null,
  );
  const removeTrackMutation = useMutation({
    mutationFn: ({ trackId, withClips }: { trackId: string; withClips: boolean }) =>
      removeTrack(sequence!.id, trackId, withClips),
    onSuccess: (updated) => {
      applySequence(updated);
      setTrackPendingRemoval(null);
    },
    onError: (error: Error) => {
      setTrackPendingRemoval(null); // never leave the dialog hanging on a failure
      toast.error(error.message);
    },
  });
  const setSpeedMutation = useMutation({
    mutationFn: ({ clipId, speed }: { clipId: string; speed: number }) => setClipSpeed(sequence!.id, clipId, speed),
    onSuccess: refreshSequences,
  });
  const setGainMutation = useMutation({
    mutationFn: ({ clipId, gain, muted }: { clipId: string; gain: number; muted: boolean }) =>
      setClipGain(sequence!.id, clipId, gain, muted),
    onSuccess: (updated) => applySequence(updated),
  });
  const detachAudioMutation = useMutation({
    mutationFn: (clipId: string) => detachClipAudio(sequence!.id, clipId),
    onSuccess: (updated) => {
      applySequence(updated);
      toast.success(t("detachAudioDone"));
    },
    onError: (error) => toast.error(String((error as Error).message)),
  });
  const setEffectsMutation = useMutation({
    mutationFn: ({ clipId, effects }: { clipId: string; effects: Record<string, unknown> }) =>
      setClipEffects(sequence!.id, clipId, effects),
    onSuccess: refreshSequences,
  });
  const setTransformMutation = useMutation({
    mutationFn: ({ clipId, transform }: { clipId: string; transform: Record<string, number> }) =>
      setClipTransform(sequence!.id, clipId, transform),
    // Apply the returned sequence straight to the cache (no refetch gap) so the resized clip
    // lands at its final transform in the same tick the Monitor drops its drag draft.
    onSuccess: (updated) => applySequence(updated),
    onError: refreshSequences,
  });
  const reframeMutation = useMutation({
    mutationFn: ({ width, height, fillMode }: { width: number; height: number; fillMode: string }) =>
      setSequenceReframe(sequence!.id, { width, height, fill_mode: fillMode }),
    onSuccess: refreshSequences,
  });
  const cutRangeMutation = useMutation({
    mutationFn: ({ clipId, srcStart, srcEnd }: { clipId: string; srcStart: number; srcEnd: number }) =>
      cutClipRange(sequence!.id, clipId, { src_start: srcStart, src_end: srcEnd }),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const cutRangesMutation = useMutation({
    mutationFn: async (cuts: Array<{ clipId: string; ranges: Array<{ srcStart: number; srcEnd: number }> }>) => {
      for (const cut of cuts) {
        await cutClipRanges(
          sequence!.id,
          cut.clipId,
          cut.ranges.map((range) => ({ src_start: range.srcStart, src_end: range.srcEnd })),
        );
      }
    },
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const splitMutation = useMutation({
    mutationFn: ({ clipId, srcTime }: { clipId: string; srcTime: number }) => splitClip(sequence!.id, clipId, srcTime),
    onSuccess: refreshSequences,
  });
  // Transcript-driven split (按句切分 / 单句独立 / 在此切一刀): divide each named clip at
  // its source-time points. Per-clip try/catch so a clip with no interior cut just no-ops.
  const splitPointsMutation = useMutation({
    mutationFn: async (cuts: Array<{ clipId: string; srcTimes: number[] }>) => {
      let latest: Sequence | null = null;
      for (const cut of cuts) {
        if (cut.srcTimes.length === 0) continue;
        try {
          latest = await splitClipAtPoints(sequence!.id, cut.clipId, cut.srcTimes);
        } catch {
          /* clip had no valid interior split point — skip it */
        }
      }
      return latest;
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
      else void refreshSequences();
    },
    onError: () => void refreshSequences(),
  });
  const trackStateMutation = useMutation({
    mutationFn: ({
      trackId,
      body,
    }: {
      trackId: string;
      body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean };
    }) => setTrackState(sequence!.id, trackId, body),
    // Write the returned sequence straight into the cache. An invalidate/refetch leaves a window
    // where the rail still shows the pre-change track, and a click landing in that window targets
    // a track the server has already changed or removed — which then fails as "Track not found".
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const undoMutation = useMutation({
    mutationFn: () => undoSequence(sequence!.id),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const redoMutation = useMutation({
    mutationFn: () => redoSequence(sequence!.id),
    onSuccess: refreshSequences,
  });

  const allClips = React.useMemo(
    () => (sequence?.tracks ?? []).flatMap((track) => track.clips ?? []),
    [sequence],
  );
  const selectedClip = allClips.find((clip) => clip.id === selectedClipId) ?? null;
  const isOverlayClip = React.useMemo(() => {
    if (!selectedClip || !sequence) return false;
    const videoTracks = (sequence.tracks ?? [])
      .filter((track) => track.kind === "video")
      .sort((a, b) => a.position - b.position);
    // Base = bottom-most video track (see Monitor z-order); every track above it is an overlay.
    return videoTracks.slice(0, -1).some((track) => track.id === selectedClip.track_id);
  }, [selectedClip, sequence]);

  const splitAtPlayhead = React.useCallback(
    (clipId?: string) => {
      if (!sequence) return;
      const playhead = useEditorStore.getState().playhead;
      const targetId = clipId ?? useEditorStore.getState().selectedClipId;
      const all = (sequence.tracks ?? []).flatMap((track) => track.clips ?? []);
      const clip = targetId
        ? all.find((item) => item.id === targetId)
        : all.find((item) => playhead > item.timeline_start && playhead < clipEnd(item));
      if (!clip) return;
      if (!(playhead > clip.timeline_start && playhead < clipEnd(clip))) return;
      const srcTime = clip.src_in + (playhead - clip.timeline_start);
      splitMutation.mutate({ clipId: clip.id, srcTime });
    },
    [sequence, splitMutation],
  );

  const duplicateClip = React.useCallback(
    (clipId?: string) => {
      if (!sequence) return;
      const targetId = clipId ?? useEditorStore.getState().selectedClipId;
      if (!targetId) return;
      for (const track of sequence.tracks ?? []) {
        const clip = (track.clips ?? []).find((item) => item.id === targetId);
        if (clip) {
          if (!clip.asset_id) return;
          const trackEnd = (track.clips ?? []).reduce((end, item) => Math.max(end, clipEnd(item)), 0);
          insertClipMutation.mutate({
            trackId: track.id,
            assetId: clip.asset_id,
            timelineStart: trackEnd,
            srcIn: clip.src_in,
            srcOut: clip.src_out,
          });
          return;
        }
      }
    },
    [sequence, insertClipMutation],
  );

  // 剪贴板(片段级复制/剪切/粘贴)+ 图层上下移。
  const clipboardRef = React.useRef<{ assetId: string; srcIn: number; srcOut: number; trackId: string } | null>(null);
  const findSelectedClip = React.useCallback(() => {
    if (!sequence) return null;
    const id = useEditorStore.getState().selectedClipId;
    if (!id) return null;
    for (const track of sequence.tracks ?? []) {
      const clip = (track.clips ?? []).find((item) => item.id === id);
      if (clip) return clip;
    }
    return null;
  }, [sequence]);
  const copyClip = React.useCallback(() => {
    const clip = findSelectedClip();
    if (!clip?.asset_id) return;
    clipboardRef.current = { assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out, trackId: clip.track_id };
  }, [findSelectedClip]);
  const pasteClip = React.useCallback(() => {
    const cb = clipboardRef.current;
    if (!cb || !sequence) return;
    const playhead = useEditorStore.getState().playhead;
    const track =
      (sequence.tracks ?? []).find((item) => item.id === cb.trackId) ??
      (sequence.tracks ?? []).find((item) => item.kind === "video");
    if (!track) return;
    insertClipMutation.mutate({ trackId: track.id, assetId: cb.assetId, timelineStart: playhead, srcIn: cb.srcIn, srcOut: cb.srcOut });
  }, [sequence, insertClipMutation]);
  const cutClip = React.useCallback(() => {
    const clip = findSelectedClip();
    if (!clip?.asset_id) return;
    clipboardRef.current = { assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out, trackId: clip.track_id };
    deleteClipMutation.mutate(clip.id);
  }, [findSelectedClip, deleteClipMutation]);
  const moveClipLayer = React.useCallback(
    (direction: -1 | 1) => {
      const clip = findSelectedClip();
      if (!clip || !sequence) return;
      const videoTracks = (sequence.tracks ?? []).filter((item) => item.kind === "video").sort((a, b) => a.position - b.position);
      const index = videoTracks.findIndex((item) => item.id === clip.track_id);
      const target = index >= 0 ? videoTracks[index + direction] : undefined;
      if (!target) return;
      moveClipMutation.mutate({ clipId: clip.id, timelineStart: clip.timeline_start, trackId: target.id });
    },
    [findSelectedClip, sequence, moveClipMutation],
  );

  const addAssetToTimeline = (asset: Asset) => {
    if (!sequence) return;
    const track = (sequence.tracks ?? []).find((item) => trackAcceptsAsset(item, asset));
    if (!track) return;
    const trackEnd = (track.clips ?? []).reduce((end, clip) => Math.max(end, clipEnd(clip)), 0);
    const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
    insertClipMutation.mutate({
      trackId: track.id,
      assetId: asset.id,
      timelineStart: trackEnd,
      srcIn: 0,
      srcOut: duration,
    });
  };

  // Keyboard: space toggles playback, delete removes selection.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redoMutation.mutate();
        else undoMutation.mutate();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copyClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "x") {
        event.preventDefault();
        cutClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        pasteClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key === "]") {
        event.preventDefault();
        moveClipLayer(1);
      } else if ((event.metaKey || event.ctrlKey) && event.key === "[") {
        event.preventDefault();
        moveClipLayer(-1);
      } else if (event.key.toLowerCase() === "s" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        splitAtPlayhead();
      } else if (event.key.toLowerCase() === "a" && !event.metaKey && !event.ctrlKey) {
        useEditorStore.getState().setTool("select");
      } else if (event.key.toLowerCase() === "b" && !event.metaKey && !event.ctrlKey) {
        useEditorStore.getState().setTool("blade");
      } else if (event.code === "Space") {
        event.preventDefault();
        useEditorStore.getState().togglePlaying();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const fps = sequence?.fps || 30;
        const step = (event.shiftKey ? 10 : 1) / fps;
        const store = useEditorStore.getState();
        store.setPlayhead(store.playhead + (event.key === "ArrowLeft" ? -step : step));
      } else if (event.key === "Delete" || event.key === "Backspace") {
        const clipIds = useEditorStore.getState().selectedClipIds;
        if (clipIds.length > 0 && sequence) {
          event.preventDefault();
          if (event.shiftKey) rippleDeleteMutation.mutate(clipIds);
          else if (clipIds.length === 1) deleteClipMutation.mutate(clipIds[0]);
          else deleteClipsMutation.mutate(clipIds);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence?.id, splitAtPlayhead, duplicateClip, copyClip, cutClip, pasteClip, moveClipLayer]);

  if (!sequence) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2.5 [&>*]:shrink-0">
        <EmptyState
          icon={<Scissors size={22} />}
          title={t("emptyTimeline")}
          body={t("mediaEmptyBody")}
          action={
            <Button onClick={() => createSequence.mutate()} disabled={createSequence.isPending}>
              <Plus size={15} /> {t("createMainSequence")}
            </Button>
          }
        />
      </div>
    );
  }

  // 检查器只在选中片段时占用右栏 — 空的「未选中片段」面板不该
  // 一直吃掉宽度;紧凑模式(≤1000px)下改为浮动抽屉,不占列。
  const showInspector = selectedClip !== null;
  // Where the panels row ends, measured from the grid's bottom edge: padding (10) + the
  // timeline's height + the row gap (6). Keeps the column resizers out of the timeline.
  const panelsRowBottom = panels.timeline + 16;
  const inspectorInGrid = showInspector && !compact;

  return (
    <div
      className="relative grid h-full grid-cols-[252px_minmax(0,1fr)_264px] grid-rows-[minmax(0,1fr)_252px] gap-1.5 p-2.5"
      style={{
        gridTemplateColumns: inspectorInGrid
          ? `${leftWidth}px minmax(0, 1fr) ${panels.right}px`
          : `${leftWidth}px minmax(0, 1fr)`,
        gridTemplateRows: `minmax(0, 1fr) ${panels.timeline}px`,
      }}
    >
      {/* Uploaded fonts must be registered before the monitor or the style panel can paint
          text in them. */}
      <FontFaces fonts={fonts.data ?? []} />
      <ConfirmDialog
        open={trackPendingRemoval !== null}
        title={t("removeTrackConfirmTitle")}
        body={t("removeTrackConfirmBody")
          .replace("{name}", trackPendingRemoval?.name ?? "")
          .replace("{n}", String(trackPendingRemoval?.clips ?? 0))}
        onCancel={() => setTrackPendingRemoval(null)}
        onConfirm={() =>
          trackPendingRemoval &&
          removeTrackMutation.mutate({ trackId: trackPendingRemoval.id, withClips: true })
        }
      />
      {/* Resizers sit on the 8px gap centers; grid pads 12px (Global rhythm). */}
      {/* A column resizer must not extend past the row whose columns it separates. These are
          absolutely positioned over the whole grid, so without an explicit bottom they run down
          through the timeline — and a drag started in the timeline, merely aligned with the
          monitor's left edge, resized the panel instead. Stop them at the panels row: grid
          padding + timeline height + row gap. */}
      <div
        className="absolute bottom-3 top-3 z-10 w-[7px] cursor-col-resize touch-none before:absolute before:inset-0 before:m-auto before:h-9 before:w-0.5 before:rounded-sm before:bg-border before:transition-colors before:duration-100 before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)] active:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)]"
        style={{ left: leftWidth + 12 + 4 - 3, bottom: panelsRowBottom }}
        onPointerDown={startPanelDrag("left")}
      />
      {inspectorInGrid && (
        <div
          className="absolute bottom-3 top-3 z-10 w-[7px] cursor-col-resize touch-none before:absolute before:inset-0 before:m-auto before:h-9 before:w-0.5 before:rounded-sm before:bg-border before:transition-colors before:duration-100 before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)] active:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)]"
          style={{ right: panels.right + 12 + 4 - 3, bottom: panelsRowBottom }}
          onPointerDown={startPanelDrag("right")}
        />
      )}
      <div
        className="absolute left-3 right-3 z-10 h-[7px] cursor-row-resize touch-none before:absolute before:inset-0 before:m-auto before:h-0.5 before:w-9 before:rounded-sm before:bg-border before:transition-colors before:duration-100 before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)] active:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)]"
        style={{ bottom: panels.timeline + 12 + 4 - 3 }}
        onPointerDown={startPanelDrag("timeline")}
      />
      {leftTab === "media" ? (
        <MediaPool
          assets={assets.data ?? []}
          uploading={uploadAsset.isPending}
          onImportFile={(file) => uploadAsset.mutate(file)}
          onAddToTimeline={addAssetToTimeline}
          tabs={<LeftTabs tab={leftTab} onChange={setLeftTab} />}
        />
      ) : leftTab === "voice" ? (
        <VoicePanel workspace={workspace} project={project} tabs={<LeftTabs tab={leftTab} onChange={setLeftTab} />} />
      ) : (
        <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)]">
          <div className="flex min-h-[38px] items-center justify-between border-b border-border px-2.5 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <LeftTabs tab={leftTab} onChange={setLeftTab} />
          </div>
          {leftTab === "transcript" ? (
            <TranscriptPanel
              sequence={sequence}
              onCutSegment={(clipId, srcStart, srcEnd) => cutRangeMutation.mutate({ clipId, srcStart, srcEnd })}
              onCutRanges={(cuts) => cutRangesMutation.mutate(cuts)}
              onSplitPoints={(cuts) => splitPointsMutation.mutate(cuts)}
              onTranslateToSubtitles={(lang) => generateSubtitlesMutation.mutate(lang)}
              translating={generateSubtitlesMutation.isPending}
            />
          ) : (
            <SubtitlePanel
              sequence={sequence}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              onApplyTexts={(texts) => setTextsMutation.mutateAsync(texts)}
              onAddSubtitle={() => addSubtitleMutation.mutate()}
              onGenerate={() => generateSubtitlesMutation.mutate(undefined)}
              generating={generateSubtitlesMutation.isPending}
              style={styleDraft ?? ((sequence.subtitle_style ?? {}) as Record<string, unknown>)}
              fonts={fonts.data ?? []}
              onUploadFont={(file) => uploadFontMutation.mutate(file)}
              onDeleteFont={(fontId) => deleteFontMutation.mutate(fontId)}
              uploadingFont={uploadFontMutation.isPending}
              onPreviewStyle={setStyleDraft}
              onSetStyle={(style) => {
                setStyleDraft(style);
                subtitleStyleMutation.mutate(style);
              }}
              onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
            />
          )}
        </section>
      )}
      <section className="min-h-0 overflow-hidden rounded-md border border-border shadow-[var(--shadow-panel)] bg-[var(--monitor-bg)]">
        <Monitor
          sequence={sequence}
          subtitleStyleOverride={styleDraft}
          assets={assets.data ?? []}
          onSetTransform={(clipId, transform) => setTransformMutation.mutate({ clipId, transform })}
        />
      </section>
      {showInspector &&
        (() => {
          const inspector = (
            <Inspector
              sequence={sequence}
              workspaceId={workspace.id}
              selectedClip={selectedClip}
              assets={assets.data ?? []}
              isOverlayClip={isOverlayClip}
              onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
              onSetEffects={(clipId, effects) => setEffectsMutation.mutate({ clipId, effects })}
              onSetTransform={(clipId, transform) => setTransformMutation.mutate({ clipId, transform })}
              onReframe={(width, height, fillMode) => reframeMutation.mutate({ width, height, fillMode })}
              onSetSpeed={(clipId, speed) => setSpeedMutation.mutate({ clipId, speed })}
              onSetGain={(clipId, gain, muted) => setGainMutation.mutate({ clipId, gain, muted })}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              onClose={compact ? () => useEditorStore.getState().selectClip(null) : undefined}
            />
          );
          return compact ? <div className="fixed bottom-0 right-0 top-11 z-[60] grid w-[min(320px,calc(100vw-96px))] border-l border-border-strong bg-panel [&>section]:h-full [&>section]:rounded-none [&>section]:border-0">{inspector}</div> : inspector;
        })()}
      <section className="col-span-full min-h-0 overflow-hidden rounded-md border border-border shadow-[var(--shadow-panel)] bg-[var(--timeline-bg)]">
        <Timeline
          sequence={sequence}
          assets={assets.data ?? []}
          onInsertClip={(args) => insertClipMutation.mutate(args)}
          onMoveClip={(clipId, timelineStart, trackId, ripple) =>
            moveClipMutation.mutate({ clipId, timelineStart, trackId, ripple })
          }
          onMoveClipToNewLayer={(clipId, timelineStart) =>
            moveClipToNewLayerMutation.mutate({ clipId, timelineStart })
          }
          onTrimClip={(clipId, payload) => trimClipMutation.mutate({ clipId, payload })}
          onAddTrack={(kind) => addTrackMutation.mutate(kind)}
          onMoveTrack={(trackId, direction) => moveTrackMutation.mutate({ trackId, direction })}
          onRemoveTrack={(trackId, clipCount) => {
            if (clipCount === 0) {
              removeTrackMutation.mutate({ trackId, withClips: false });
              return;
            }
            const track = (sequence.tracks ?? []).find((item) => item.id === trackId);
            setTrackPendingRemoval({ id: trackId, name: track?.name ?? "", clips: clipCount });
          }}
          onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
          onRippleDeleteClip={(clipId) => rippleDeleteMutation.mutate([clipId])}
          onSplitClip={(clipId) => splitAtPlayhead(clipId)}
          onSplitClipAt={(clipId, srcTime) => splitMutation.mutate({ clipId, srcTime })}
          onDuplicateClip={(clipId) => duplicateClip(clipId)}
          onDetachAudio={(clipId) => detachAudioMutation.mutate(clipId)}
          onSetTrackState={(trackId, body) => trackStateMutation.mutate({ trackId, body })}
          toolbarExtra={
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={!sequence.can_undo || undoMutation.isPending}
                    onClick={() => undoMutation.mutate()}
                    aria-label={t("undo")}
                  >
                    <Undo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("undo")} (⌘Z)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={!sequence.can_redo || redoMutation.isPending}
                    onClick={() => redoMutation.mutate()}
                    aria-label={t("redoAction")}
                  >
                    <Redo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("redoAction")} (⇧⌘Z)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={addSubtitleMutation.isPending}
                    onClick={() => addSubtitleMutation.mutate()}
                    aria-label={t("addSubtitleAtPlayhead")}
                  >
                    <Type size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("addSubtitleAtPlayhead")}</TooltipContent>
              </Tooltip>
              <ExportControl workspaceId={workspace.id} projectId={project.id} sequenceId={sequence.id} />
            </>
          }
        />
      </section>
    </div>
  );
}

function LeftTabs({
  tab,
  onChange,
}: {
  tab: LeftTab;
  onChange: (tab: LeftTab) => void;
}) {
  const t = useI18n();
  return (
    <div className="flex shrink-0 gap-0.5">
      <button
        type="button"
        className={cn("cursor-pointer whitespace-nowrap rounded border-0 bg-transparent px-[7px] py-1 text-[11px] font-semibold uppercase tracking-[0.03em] text-muted-foreground transition-[background-color,color] duration-100 hover:text-foreground", tab === "media" && "bg-secondary text-foreground hover:bg-secondary")}
        onClick={() => onChange("media")}
      >
        {t("media")}
      </button>
      <button
        type="button"
        className={cn("cursor-pointer whitespace-nowrap rounded border-0 bg-transparent px-[7px] py-1 text-[11px] font-semibold uppercase tracking-[0.03em] text-muted-foreground transition-[background-color,color] duration-100 hover:text-foreground", tab === "transcript" && "bg-secondary text-foreground hover:bg-secondary")}
        onClick={() => onChange("transcript")}
      >
        {t("transcriptTab")}
      </button>
      <button
        type="button"
        className={cn("cursor-pointer whitespace-nowrap rounded border-0 bg-transparent px-[7px] py-1 text-[11px] font-semibold uppercase tracking-[0.03em] text-muted-foreground transition-[background-color,color] duration-100 hover:text-foreground", tab === "subtitle" && "bg-secondary text-foreground hover:bg-secondary")}
        onClick={() => onChange("subtitle")}
      >
        {t("subtitleTab")}
      </button>
      <button
        type="button"
        className={cn("cursor-pointer whitespace-nowrap rounded border-0 bg-transparent px-[7px] py-1 text-[11px] font-semibold uppercase tracking-[0.03em] text-muted-foreground transition-[background-color,color] duration-100 hover:text-foreground", tab === "voice" && "bg-secondary text-foreground hover:bg-secondary")}
        onClick={() => onChange("voice")}
      >
        {t("voiceTab")}
      </button>
    </div>
  );
}

function ExportControl({
  workspaceId,
  projectId,
  sequenceId,
}: {
  workspaceId: string;
  projectId: string;
  sequenceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const startExport = useMutation({
    mutationFn: () => exportSequence(sequenceId),
    onSuccess: (job) => setJobId(job.id),
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 700;
    },
    refetchOnWindowFocus: true,
  });

  const status = jobId ? (job.data?.status ?? "queued") : null;
  React.useEffect(() => {
    if (status === "succeeded") {
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId, projectId] });
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
    }
  }, [status, qc, workspaceId, projectId]);

  const busy = startExport.isPending || status === "queued" || status === "running";

  return (
    <span className="mr-2 inline-flex items-center gap-1.5">
      {status === "running" && (
        <span className="timecode inline-flex items-center gap-1 text-[11px] text-muted-foreground">{Math.round((job.data?.progress ?? 0) * 100)}%</span>
      )}
      {status === "succeeded" && (
        <span className="inline-flex items-center gap-1 text-[11px] text-[var(--track-audio-text)]">
          <CircleCheck size={13} /> {t("exportDone")}
        </span>
      )}
      {status === "failed" && (
        <span className="inline-flex items-center gap-1 text-[11px] text-destructive" title={job.data?.error ?? undefined}>
          <CircleAlert size={13} /> {t("exportFailed")}
        </span>
      )}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => startExport.mutate()}>
        {busy ? <Loader2 size={13} className="animate-mibu-spin" /> : <Download size={13} />}
        {busy ? t("exporting") : t("exportVideo")}
      </Button>
    </span>
  );
}

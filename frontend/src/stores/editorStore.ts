import { create } from "zustand";

/**
 * Editor transient state only (plan §14.2): playhead, zoom, selection, and
 * the in-flight drag draft. Server truth stays in React Query.
 */

export interface DragDraft {
  clipId: string;
  trackId: string;
  timeline_start: number;
  src_in: number;
  src_out: number;
  kind: "move" | "trim-start" | "trim-end";
}

export const MIN_PX_PER_SECOND = 4;
export const MAX_PX_PER_SECOND = 240;
export const DEFAULT_PX_PER_SECOND = 40;

export interface DraggingAsset {
  id: string;
  kind: string;
  duration: number;
}

/** "select" drags/moves clips; "blade" splits a clip where you click. */
export type ToolMode = "select" | "blade";

/** DaVinci-style edit mode. "insert" ripples downstream clips aside when you
 * drop; "overwrite" drops in place (clips may overlap). */
export type EditMode = "insert" | "overwrite";

interface EditorState {
  playhead: number;
  playing: boolean;
  loop: boolean;
  playbackRate: number;
  volume: number;
  muted: boolean;
  pxPerSecond: number;
  selectedClipId: string | null;
  selectedClipIds: string[];
  dragDraft: DragDraft | null;
  draggingAsset: DraggingAsset | null;
  tool: ToolMode;
  editMode: EditMode;
  setPlayhead: (time: number) => void;
  setPlaying: (playing: boolean) => void;
  togglePlaying: () => void;
  toggleLoop: () => void;
  cyclePlaybackRate: () => void;
  setVolume: (volume: number) => void;
  toggleMuted: () => void;
  setPxPerSecond: (value: number) => void;
  zoomBy: (factor: number) => void;
  selectClip: (clipId: string | null) => void;
  toggleSelectClip: (clipId: string) => void;
  selectClips: (clipIds: string[]) => void;
  setDragDraft: (draft: DragDraft | null) => void;
  setDraggingAsset: (asset: DraggingAsset | null) => void;
  setTool: (tool: ToolMode) => void;
  setEditMode: (mode: EditMode) => void;
  toggleEditMode: () => void;
}

const PLAYBACK_RATES = [0.5, 1, 1.5, 2];

export const useEditorStore = create<EditorState>((set) => ({
  playhead: 0,
  playing: false,
  loop: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  pxPerSecond: DEFAULT_PX_PER_SECOND,
  selectedClipId: null,
  selectedClipIds: [],
  dragDraft: null,
  draggingAsset: null,
  tool: "select",
  editMode: "overwrite",
  setPlayhead: (time) => set({ playhead: Math.max(0, time) }),
  setPlaying: (playing) => set({ playing }),
  togglePlaying: () => set((state) => ({ playing: !state.playing })),
  toggleLoop: () => set((state) => ({ loop: !state.loop })),
  cyclePlaybackRate: () =>
    set((state) => ({
      playbackRate: PLAYBACK_RATES[(PLAYBACK_RATES.indexOf(state.playbackRate) + 1) % PLAYBACK_RATES.length],
    })),
  setVolume: (volume) => set({ volume: Math.min(1, Math.max(0, volume)), muted: false }),
  toggleMuted: () => set((state) => ({ muted: !state.muted })),
  setPxPerSecond: (value) =>
    set({ pxPerSecond: Math.min(MAX_PX_PER_SECOND, Math.max(MIN_PX_PER_SECOND, value)) }),
  zoomBy: (factor) =>
    set((state) => ({
      pxPerSecond: Math.min(MAX_PX_PER_SECOND, Math.max(MIN_PX_PER_SECOND, state.pxPerSecond * factor)),
    })),
  selectClip: (clipId) => set({ selectedClipId: clipId, selectedClipIds: clipId ? [clipId] : [] }),
  toggleSelectClip: (clipId) =>
    set((state) => {
      const ids = state.selectedClipIds.includes(clipId)
        ? state.selectedClipIds.filter((id) => id !== clipId)
        : [...state.selectedClipIds, clipId];
      return { selectedClipIds: ids, selectedClipId: ids[ids.length - 1] ?? null };
    }),
  selectClips: (clipIds) => set({ selectedClipIds: clipIds, selectedClipId: clipIds[clipIds.length - 1] ?? null }),
  setDragDraft: (draft) => set({ dragDraft: draft }),
  setDraggingAsset: (asset) => set({ draggingAsset: asset }),
  setTool: (tool) => set({ tool }),
  setEditMode: (editMode) => set({ editMode }),
  toggleEditMode: () => set((state) => ({ editMode: state.editMode === "insert" ? "overwrite" : "insert" })),
}));

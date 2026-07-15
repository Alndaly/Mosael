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

interface EditorState {
  playhead: number;
  playing: boolean;
  pxPerSecond: number;
  selectedClipId: string | null;
  dragDraft: DragDraft | null;
  setPlayhead: (time: number) => void;
  setPlaying: (playing: boolean) => void;
  togglePlaying: () => void;
  setPxPerSecond: (value: number) => void;
  zoomBy: (factor: number) => void;
  selectClip: (clipId: string | null) => void;
  setDragDraft: (draft: DragDraft | null) => void;
}

export const useEditorStore = create<EditorState>((set) => ({
  playhead: 0,
  playing: false,
  pxPerSecond: DEFAULT_PX_PER_SECOND,
  selectedClipId: null,
  dragDraft: null,
  setPlayhead: (time) => set({ playhead: Math.max(0, time) }),
  setPlaying: (playing) => set({ playing }),
  togglePlaying: () => set((state) => ({ playing: !state.playing })),
  setPxPerSecond: (value) =>
    set({ pxPerSecond: Math.min(MAX_PX_PER_SECOND, Math.max(MIN_PX_PER_SECOND, value)) }),
  zoomBy: (factor) =>
    set((state) => ({
      pxPerSecond: Math.min(MAX_PX_PER_SECOND, Math.max(MIN_PX_PER_SECOND, state.pxPerSecond * factor)),
    })),
  selectClip: (clipId) => set({ selectedClipId: clipId }),
  setDragDraft: (draft) => set({ dragDraft: draft }),
}));

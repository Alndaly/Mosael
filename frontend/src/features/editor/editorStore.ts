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
  /** 指针已松开、提交在途:草稿只为钉住落点等服务端回包,不再跟随指针。
   *  缓存追平草稿的那一帧把它视作已清,落位动画由该帧的过渡完成。 */
  settling?: boolean;
  /** 组拖(框选多个后拖动)时,随锚点一起移动的其余选中片段。
   *
   *  锚点(clipId)保持单片段语义不变——裁剪、插入模式的涟漪预览、落位判定都只认它,
   *  所以这些既有逻辑一行不用改;渲染侧另外把 followers 一并投影出去。 */
  followers?: { clipId: string; trackId: string; timeline_start: number }[];
}

export const MIN_PX_PER_SECOND = 4;
export const MAX_PX_PER_SECOND = 240;
export const DEFAULT_PX_PER_SECOND = 40;

export interface DraggingAsset {
  id: string;
  kind: string;
  duration: number;
}

export interface ClipClipboard {
  clipIds: string[];
  cut: boolean;
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
  /** 选中的片段。**只有这一份** —— 单选是"长度为一的列表",见 selectedClipId 选择器。 */
  selectedClipIds: string[];
  dragDraft: DragDraft | null;
  draggingAsset: DraggingAsset | null;
  /** 片段剪贴板:存片段 id,粘贴时由后端深拷贝。cut = 剪切 —— 粘贴时把这几段搬过去(见 EditorView)。 */
  clipboard: ClipClipboard | null;
  tool: ToolMode;
  editMode: EditMode;
  setPlayhead: (time: number) => void;
  setPlaying: (playing: boolean) => void;
  togglePlaying: () => void;
  /** J / K / L 穿梭:1 = L(正向,再按加速),-1 = J(倒放,再按加速),0 = K(停,倍速回 1)。 */
  shuttle: (direction: -1 | 0 | 1) => void;
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
  setClipboard: (clipboard: ClipClipboard | null) => void;
  setTool: (tool: ToolMode) => void;
  setEditMode: (mode: EditMode) => void;
  toggleEditMode: () => void;
}

const PLAYBACK_RATES = [0.5, 1, 1.5, 2];
/** 穿梭的档位(倍速的绝对值):每按一次同方向的键升一档。 */
const SHUTTLE_RATES = [1, 2, 4, 8];

/** 正常播放用的倍速:倒放和穿梭的高档位(4×、8×)都不是 —— 空格、K 之后回到 1。 */
function normalRate(rate: number): number {
  return PLAYBACK_RATES.includes(rate) ? rate : 1;
}

export const useEditorStore = create<EditorState>((set) => ({
  playhead: 0,
  playing: false,
  loop: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  pxPerSecond: DEFAULT_PX_PER_SECOND,
  selectedClipIds: [],
  dragDraft: null,
  draggingAsset: null,
  clipboard: null,
  tool: "select",
  editMode: "overwrite",
  setPlayhead: (time) => set({ playhead: Math.max(0, time) }),
  setPlaying: (playing) => set({ playing }),
  togglePlaying: () =>
    set((state) => (state.playing ? { playing: false } : { playing: true, playbackRate: normalRate(state.playbackRate) })),
  shuttle: (direction) =>
    set((state) => {
      if (direction === 0) return { playing: false, playbackRate: normalRate(state.playbackRate) };
      const sameWay = state.playing && Math.sign(state.playbackRate) === direction;
      const speed = sameWay
        ? (SHUTTLE_RATES.find((rate) => rate > Math.abs(state.playbackRate)) ?? SHUTTLE_RATES[SHUTTLE_RATES.length - 1])
        : 1;
      return { playing: true, playbackRate: direction * speed };
    }),
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
  selectClip: (clipId) => set({ selectedClipIds: clipId ? [clipId] : [] }),
  toggleSelectClip: (clipId) =>
    set((state) => {
      const ids = state.selectedClipIds.includes(clipId)
        ? state.selectedClipIds.filter((id) => id !== clipId)
        : [...state.selectedClipIds, clipId];
      return { selectedClipIds: ids };
    }),
  selectClips: (clipIds) => set({ selectedClipIds: clipIds }),
  setDragDraft: (draft) => set({ dragDraft: draft }),
  setDraggingAsset: (asset) => set({ draggingAsset: asset }),
  setClipboard: (clipboard) => set({ clipboard }),
  setTool: (tool) => set({ tool }),
  setEditMode: (editMode) => set({ editMode }),
  toggleEditMode: () => set((state) => ({ editMode: state.editMode === "insert" ? "overwrite" : "insert" })),
}));

/**
 * 当前"那一个"选中的片段 —— 属性面板、右键菜单、单片段快捷键读的都是它。
 *
 * **它是派生值,不是第二份状态。** 此前 store 里同时存 `selectedClipId` 和
 * `selectedClipIds`,恒等式由**每个写入口各自记得**维持:三个入口今天都写对了,所以两者
 * 永远一致 —— 而第四个入口("选中某轨全部片段"、"撤销后恢复选区")只要漏一行,两个读者就会
 * 看到不同的选中态,表现成"属性面板显示的是另一个片段",没有任何东西会报错。
 *
 * 取**最后一个**:多选是按点击顺序累加的,最后点的那个就是"现在说的这个"。
 */
export const selectedClipId = (state: EditorState): string | null =>
  state.selectedClipIds[state.selectedClipIds.length - 1] ?? null;
